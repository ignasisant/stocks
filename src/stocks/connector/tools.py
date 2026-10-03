"""The connector's tools: the API's read handlers, asked on a token's behalf.

Every tool is a thin call into a `stocks.api.routes` handler — the same
function the app's pages read — so a figure in Claude is the figure on the
page. The handlers are plain functions once FastAPI is out of the way: the
account is the `UserPaths` the token's holder resolves to, and every query
default is an ordinary value.

`_run` is the one road in. It resolves the account (never creating one: a
token is not a sign-in), spends from a per-account budget, binds the log
context, runs the handler on a worker thread, and turns every failure into a
tool error the model can read. Nothing it logs quotes the caller's data:
exception text can carry a ticker, a note or an amount, so a failure is
logged by its type and where it was raised, never by its message.

What comes back is the result twice, as MCP asks: structured content (what
the MCP App view draws) and the same JSON as text (what a model without
structured-content support reads), both trimmed to fit a context window.
"""

from __future__ import annotations

import json
import re
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.error import URLError

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException
from yfinance.exceptions import YFRateLimitError

from stocks import accounts, obs
from stocks.api import cache, deps
from stocks.api.schemas import AlertRule
from stocks.connector import store
from stocks.web import ratelimit

if TYPE_CHECKING:
    from stocks.accounts import UserPaths

# Per account, on top of the site's per-IP floor: claude.ai calls from shared
# addresses, so the IP bucket cannot tell one person from another.
TOOL_MAX = 60
TOOL_WINDOW_S = 60

# Characters of JSON one tool result may put in front of the model.
TEXT_LIMIT = 24_000

# The view draws a line, not a table: this many points draw one fine.
HISTORY_POINTS = 160

OVERVIEW_POSITIONS = 25
QUOTES_MAX = 20
CORRELATION_NAMES = 10

_SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,31}$")

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
WRITES = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
# Takes something away: a row, a followed ticker, a memory, an import.
DESTROYS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)

# Rows one `add_transactions` call may carry; a statement is an import.
ADD_MAX = 50

READ_ONLY_REFUSAL = (
    "This connection can only read. To let Claude edit, the person disconnects "
    "TopStocks in Claude and connects it again, ticking the box that lets "
    "Claude make changes on the consent screen."
)


class _Refused(Exception):
    """A request this tool will not run; the message is safe to show."""


# ------------------------------------------------------------------ the road


def can_write() -> bool:
    """Whether the token on this request was granted edits at consent."""
    token = get_access_token()
    return token is not None and store.WRITE_SCOPE in token.scopes


def _log_user(email: str) -> str:
    from stocks.api.app import LOG_USER

    return accounts.slug(email) if LOG_USER else "anon"


def _where(exc: BaseException) -> str:
    """`module:line` of the frame that raised — a location, never a value."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "?"
    last = frames[-1]
    return f"{last.filename.rsplit('/', 1)[-1]}:{last.lineno}"


def _error(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


def _compact(value: Any) -> Any:
    """Floats to 8 significant digits; nothing a reader can see, half the bytes."""
    if isinstance(value, float):
        return float(f"{value:.8g}")
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _longest(value: Any) -> list | None:
    """The longest list anywhere inside `value`."""
    best: list | None = None
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            if best is None or len(node) > len(best):
                best = node
            stack.extend(node)
    return best


def _fit(data: dict) -> tuple[dict, str]:
    """`data` and its JSON, longest lists halved until it fits `TEXT_LIMIT`.

    Lists are built most-important-first (largest holding, newest trade), so
    the half kept is the one to keep. A trimmed result says so.
    """
    text = _dump(data)
    while len(text) > TEXT_LIMIT:
        biggest = _longest(data)
        if biggest is None or len(biggest) <= 1:
            break
        del biggest[max(1, len(biggest) // 2):]
        data["truncated"] = True
        text = _dump(data)
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT] + "…"
    return data, text


async def _run(tool: str, work: Callable[[UserPaths], dict], *,
               write: bool = False) -> CallToolResult:
    token = get_access_token()
    email = token.subject if token is not None else None
    if not email:
        return _error("Not signed in to TopStocks.")
    # The listing already hides these from a read-only token; this is the
    # check that counts, since a client can call a name it was never shown.
    if write and not can_write():
        obs.event("mcp.tool", tool=tool, outcome="read_only", ms=0)
        return _error(READ_ONLY_REFUSAL)
    started = time.monotonic()
    outcome = "ok"
    with obs.context(user=_log_user(email), surface="mcp"):
        try:
            paths = await anyio.to_thread.run_sync(deps.resolve_account, email)
            key = f"mcp::{paths.root}"
            if not ratelimit.allow(key, max_events=TOOL_MAX, window_s=TOOL_WINDOW_S):
                outcome = "throttled"
                wait = ratelimit.retry_after(key, window_s=TOOL_WINDOW_S)
                return _error(f"Too many TopStocks requests; try again in {wait} s.")
            holder: dict[str, float] = {}
            stale = cache.STALE.set(holder)
            try:
                data = await anyio.to_thread.run_sync(work, paths)
            finally:
                cache.STALE.reset(stale)
            if "since" in holder:
                data["stale_since"] = datetime.fromtimestamp(
                    holder["since"], tz=UTC
                ).isoformat(timespec="seconds")
            data, text = _fit(_compact(data))
            return CallToolResult(
                content=[TextContent(type="text", text=text)], structured_content=data
            )
        except _Refused as exc:
            outcome = "refused"
            return _error(str(exc))
        except ValidationError as exc:
            outcome = "invalid"
            return _error("; ".join(e["msg"] for e in exc.errors()))
        except HTTPException as exc:
            outcome = f"http_{exc.status_code}"
            if exc.status_code < 500 and isinstance(exc.detail, str):
                return _error(exc.detail)
            return _error("TopStocks could not answer right now; try again shortly.")
        except YFRateLimitError:
            outcome = "rate_limited"
            return _error(
                "The market data provider is rate limiting TopStocks; "
                "try again in a minute."
            )
        except URLError:
            outcome = "offline"
            return _error("The market data provider could not be reached.")
        except Exception as exc:  # noqa: BLE001 — the model gets a sentence, the log a place
            outcome = "failed"
            obs.warn("mcp.tool_failed", tool=tool, error_type=type(exc).__name__,
                     where=_where(exc))
            return _error("TopStocks hit an internal error answering this.")
        finally:
            obs.event("mcp.tool", tool=tool, outcome=outcome,
                      ms=round((time.monotonic() - started) * 1000))


# ---------------------------------------------------------------- arguments

Base = Annotated[
    str | None,
    Field(description="Currency to report money in (e.g. EUR, USD); "
                      "defaults to the account's own."),
]
Ticker = Annotated[
    str,
    Field(min_length=1, max_length=32,
          description="Ticker as TopStocks lists it, e.g. AAPL, SAN.MC, BTC-EUR."),
]
Window = Literal["inception", "6mo", "1y", "2y", "5y"]
RiskPeriod = Literal["inception", "6mo", "1y", "2y", "5y"]

# `/performance` windows to the `/history` span covering the same days.
_HISTORY_FOR: dict[str, str] = {
    "inception": "all", "6mo": "6m", "1y": "1y", "2y": "2y", "5y": "5y",
}


def _symbol(raw: str) -> str:
    code = raw.strip().upper()
    if not _SYMBOL_RE.match(code):
        raise _Refused("That is not a ticker symbol TopStocks can look up.")
    return code


def _plain(model: BaseModel, **exclude: Any) -> dict:
    return model.model_dump(mode="json", exclude=exclude or None)


def _by_size(rows: list[dict]) -> list[dict]:
    """Largest holding first; an unpriced one by its cost, after the priced."""
    return sorted(rows, key=lambda r: (r.get("value") is None,
                                       -(r.get("value") or r.get("cost") or 0)))


def _thin(points: list, keep: int) -> list:
    """At most `keep` points, evenly spaced, the last one always kept."""
    if len(points) <= keep:
        return points
    step = len(points) / keep
    picked = [points[int(i * step)] for i in range(keep - 1)]
    return [*picked, points[-1]]


def _origin() -> str | None:
    from stocks.web.server import public_origin

    return public_origin()


def _logo(ticker: str, origin: str | None) -> str | None:
    """The mirrored logo as an absolute URL on this site, or None.

    The view runs on the host's origin, so the API's site-relative path has to
    name ours — and the view's CSP admits this one origin for images, so a
    logo only the third-party CDN has is left to the view's initials rather
    than handed over as a URL it would be refused.
    """
    from stocks.api import loaders

    src = loaders.logo(ticker)
    if not origin or not src or not src.startswith("/") or src.startswith("//"):
        return None
    return f"{origin}{src}"


# -------------------------------------------------------------------- tools


async def portfolio_overview(base: Base = None) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        summary = portfolio.summary(paths, base)
        held = portfolio.positions(paths, base)
        rows = _by_size([_plain(p, custody=True) for p in held.positions])
        shown = rows[:OVERVIEW_POSITIONS]
        origin = _origin()
        for row in shown:
            row["logo"] = _logo(row["ticker"], origin)
        return {
            "kind": "overview",
            "summary": _plain(summary),
            "positions": shown,
            "positions_total": len(rows),
            "unpriced": held.unpriced,
        }

    return await _run("portfolio_overview", work)


async def list_positions(base: Base = None) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        held = portfolio.positions(paths, base)
        return {
            "kind": "positions",
            "base": held.base,
            "positions": _by_size([_plain(p) for p in held.positions]),
            "unpriced": held.unpriced,
        }

    return await _run("list_positions", work)


async def portfolio_performance(window: Window = "inception",
                                base: Base = None) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        perf = portfolio.performance(paths, base, window)
        series = portfolio.history(paths, base, _HISTORY_FOR[window])
        return {
            "kind": "performance",
            "performance": _plain(perf),
            "history": {
                "start": series.start,
                "end": series.end,
                "points": _thin([_plain(p) for p in series.points], HISTORY_POINTS),
                "missing": series.missing,
            },
        }

    return await _run("portfolio_performance", work)


async def list_transactions(
    limit: Annotated[int, Field(ge=1, le=200, description="Rows to return.")] = 50,
    offset: Annotated[int, Field(ge=0, description="Newest rows to skip.")] = 0,
    base: Base = None,
    ticker: Annotated[str, Field(
        max_length=40,
        description="The security however it is known: stored label, ISIN or "
                    "bare symbol across venues (GRF finds GRF.MC).")] = "",
    broker: Annotated[str, Field(
        max_length=40, description="The note's first word, e.g. ibkr, degiro.")] = "",
    action: Annotated[str, Field(
        max_length=20, description="buy, sell, dividend, fee, split, capital, "
                                   "transfer_in or transfer_out.")] = "",
    date_from: Annotated[str, Field(max_length=10,
                                    description="ISO date, inclusive.")] = "",
    date_to: Annotated[str, Field(max_length=10,
                                  description="ISO date, inclusive.")] = "",
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        page = portfolio.transactions(
            paths, limit, offset, base, ticker=ticker.strip(),
            broker=broker.strip().lower(), action=action.strip().lower(),
            since=date_from.strip(), until=date_to.strip(),
        )
        return {"kind": "transactions", **_plain(page)}

    return await _run("list_transactions", work)


async def income_report(
    year: Annotated[
        int | None,
        Field(ge=1970, le=2100, description="Only fees from this calendar year."),
    ] = None,
    base: Base = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        return {
            "kind": "income",
            "dividends": _plain(portfolio.dividends_(paths, base)),
            "fees": _plain(portfolio.fees_(paths, base, year)),
        }

    return await _run("income_report", work)


async def risk_metrics(period: RiskPeriod = "inception",
                       base: Base = None) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        report = portfolio.risk(paths, base, period)
        data = _plain(report, curves=True)
        top = sorted(report.weights, key=lambda t: -report.weights[t])[:CORRELATION_NAMES]
        data["correlation"] = {
            a: {b: v for b, v in row.items() if b in top}
            for a, row in report.correlation.items() if a in top
        }
        return {"kind": "risk", **data}

    return await _run("risk_metrics", work)


async def tax_report() -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        data = _plain(portfolio.tax_(paths))
        data["sales"] = sorted(data["sales"], key=lambda s: s["sell_date"], reverse=True)
        return {"kind": "tax", **data}

    return await _run("tax_report", work)


async def get_quotes(
    tickers: Annotated[list[str], Field(min_length=1, max_length=QUOTES_MAX,
                                        description="Tickers to quote.")],
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import market

        codes = list(dict.fromkeys(_symbol(t) for t in tickers))
        return {"kind": "quotes", **_plain(market.quotes(",".join(codes)))}

    return await _run("get_quotes", work)


async def ticker_details(ticker: Ticker, base: Base = None) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import ticker as routes

        code = _symbol(ticker)
        metrics = routes.metrics(code, base)
        return {
            "kind": "ticker",
            "quote": _plain(routes.quote(code, base)),
            "metrics": {
                **_plain(metrics, kpis=True, grid=True),
                "kpis": [_plain(k, desc=True) for k in metrics.kpis],
            },
            "position": _plain(routes.position(code, paths, base)),
        }

    return await _run("ticker_details", work)


async def search_tickers(
    query: Annotated[str, Field(min_length=1, max_length=80,
                                description="Symbol or company name.")],
    limit: Annotated[int, Field(ge=1, le=25)] = 10,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import search

        return {"kind": "search", **_plain(search.find(paths, query.strip(), limit))}

    return await _run("search_tickers", work)


async def get_watchlist() -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import watchlist

        return {"kind": "watchlist", **_plain(watchlist.watchlist(paths))}

    return await _run("get_watchlist", work)


async def upcoming_earnings() -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import earnings

        return {"kind": "calendar", **_plain(earnings.earnings(paths))}

    return await _run("upcoming_earnings", work)


async def investor_context() -> CallToolResult:
    """Who the figures belong to: the investor profile and the memories the
    app's assistant keeps, so Claude advises the same person the chat does.

    Read under the same switch the app's own surfaces honour
    (`engine.memory_on`): memory off is no memories, here as everywhere. The
    list rather than `engine.user_memory`'s block, because that block is
    worded for the app's own prompt (it points at rules this server does not
    send); the profile sentence is `engine.persona`'s, through the profile
    route, so it is the one the chat is given."""
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import prefs as profile_routes
        from stocks.chat import engine, learnings

        enabled = engine.memory_on(accounts.load_prefs(paths.prefs))
        saved = learnings.load(paths.learnings) if enabled else []
        return {
            "kind": "context",
            "profile": _plain(profile_routes.profile(paths)),
            "memory_enabled": enabled,
            "memories": [
                {"id": m.id, "kind": m.kind, "text": m.text,
                 "tickers": list(m.tickers),
                 "since": m.created[:10]}
                for m in saved
            ],
        }

    return await _run("investor_context", work)


# ----------------------------------------------------------- the book, read
# What the edit tools work from: rows by id, what looks wrong, what was
# changed and by whom, and what a sale would cost in tax.


async def check_book() -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        return {"kind": "book_health", **_plain(portfolio.health(paths))}

    return await _run("check_book", work)


async def change_history(
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        return {"kind": "changes", **_plain(portfolio.list_changes(paths, limit))}

    return await _run("change_history", work)


async def simulate_sale(
    ticker: Ticker,
    shares: Annotated[float | None, Field(
        gt=0, description="Shares to sell; omitted sells the whole holding.")] = None,
    price: Annotated[float | None, Field(
        gt=0, description="Sale price per share; omitted uses today's.")] = None,
    currency: Annotated[str | None, Field(
        min_length=3, max_length=3,
        description="Currency of `price`; defaults to the holding's.")] = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from dataclasses import asdict

        from stocks.chat import whatif

        code = _symbol(ticker)
        quoted = (price, (currency or "").upper()) if price is not None else None
        sale = whatif.simulate(db=paths.db, prefs_path=paths.prefs, ticker=code,
                               shares=shares, price=quoted)
        if sale is None:
            raise _Refused(f"No holding of {code} to sell, or no price to sell it at.")
        return {"kind": "sale", **asdict(sale), "extra_tax": sale.extra_tax}

    return await _run("simulate_sale", work)


async def get_preferences() -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import prefs

        view = prefs._view(accounts.load_prefs(paths.prefs))
        return {"kind": "preferences", **_plain(view)}

    return await _run("get_preferences", work)


async def get_alerts(ticker: Ticker) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import watchlist_edit

        return {"kind": "alerts", **_plain(watchlist_edit.alerts(paths, _symbol(ticker)))}

    return await _run("get_alerts", work)


async def missing_splits() -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import import_statement

        return {"kind": "splits", **_plain(import_statement.splits_scan(paths))}

    return await _run("missing_splits", work)


# ---------------------------------------------------------- the book, edited
# Every edit to the ledger goes through `stocks.portfolio.edits`, the road
# the app, the chat and Telegram take, in two calls. Without `plan_token` a
# tool writes nothing and returns the plan: each row before and after, the
# holdings and realized gains it moves, and the token. Called again with the
# same arguments and that token, it applies exactly that plan — or refuses,
# if the book moved in between. The host asks the person before each call;
# the plan is what they are asked about. Every applied edit is journalled
# under source "mcp" and `undo_change` takes it back.

PlanToken = Annotated[str | None, Field(
    max_length=64,
    description="Leave out to preview. To apply, the plan_token the preview "
                "returned, with the same other arguments.")]
Ids = Annotated[list[int], Field(min_length=1, max_length=200,
                                 description="Row ids from list_transactions.")]


def _edit(paths: UserPaths, ops: list[dict], plan_token: str | None,
          summary: str) -> dict:
    from stocks.api.routes import portfolio
    from stocks.portfolio import edits

    if plan_token is None:
        planned = _plain(portfolio.plan_change(paths, portfolio.EditOps(ops=ops)))
        planned["plan_token"] = planned.pop("token")
        planned["next"] = (
            "Nothing was written. Show the person these changes and effects; "
            "if they agree, call this tool again with the same arguments and "
            "this plan_token."
            if planned["ok"] else
            "This edit cannot be applied: see problems. Nothing was written."
        )
        return {"kind": "edit_plan", "applied": False, "summary": summary, **planned}
    try:
        done = edits.commit(ops, plan_token, source="mcp", summary=summary,
                            path=paths.db)
    except edits.Stale as exc:
        raise _Refused(
            f"{exc} Preview it again and show the person the new plan."
        ) from exc
    except edits.EditError as exc:
        raise _Refused(str(exc)) from exc
    obs.event("ledger.edited", rows=len(done.changes), via="mcp")
    return {"kind": "edit_done", "applied": True,
            **_plain(portfolio._change(done)),
            "next": f"Applied. undo_change with change_id {done.id} takes it back."}


def _rows(paths: UserPaths) -> list:
    from stocks.portfolio.ledger import all_transactions

    return all_transactions(paths.db)


def _with_broker(note: str, broker: str) -> str:
    """`note` with its first word — the broker — replaced."""
    rest = note.split(" ", 1)[1] if " " in note.strip() else ""
    return f"{broker.strip().lower()} {rest}".strip()


class NewTransaction(BaseModel):
    model_config = {"extra": "forbid"}

    date: str = Field(min_length=10, max_length=10, description="YYYY-MM-DD.")
    ticker: str = Field(min_length=1, max_length=40)
    action: Literal["buy", "sell", "dividend", "fee", "split", "capital",
                    "transfer_in", "transfer_out"]
    quantity: float = Field(ge=0, description="Shares; for a split, the ratio.")
    price: float = Field(ge=0, description="Per share; for a dividend or fee, "
                                           "the amount.")
    currency: str = Field(min_length=3, max_length=3)
    fee: float = Field(default=0.0, ge=0)
    broker: str = Field(default="", max_length=40,
                        description="Lowercase broker, e.g. ibkr. Empty is manual.")
    note: str = Field(default="", max_length=300)


async def add_transactions(
    rows: Annotated[list[NewTransaction], Field(min_length=1, max_length=ADD_MAX)],
    plan_token: PlanToken = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        ops = [{"op": "add", "row": {
            **r.model_dump(exclude={"broker", "note"}),
            "note": f"{r.broker.strip().lower()} {r.note.strip()}".strip(),
        }} for r in rows]
        return _edit(paths, ops, plan_token, f"Add {len(rows)} transaction(s)")

    return await _run("add_transactions", work, write=True)


async def edit_transaction(
    id: Annotated[int, Field(description="Row id from list_transactions.")],
    date: Annotated[str | None, Field(min_length=10, max_length=10)] = None,
    ticker: Annotated[str | None, Field(min_length=1, max_length=40)] = None,
    action: Annotated[str | None, Field(max_length=20)] = None,
    quantity: Annotated[float | None, Field(ge=0)] = None,
    price: Annotated[float | None, Field(ge=0)] = None,
    currency: Annotated[str | None, Field(min_length=3, max_length=3)] = None,
    fee: Annotated[float | None, Field(ge=0)] = None,
    broker: Annotated[str | None, Field(
        min_length=1, max_length=40,
        description="Replaces the note's first word, which names the broker.")] = None,
    plan_token: PlanToken = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        given = {"date": date, "ticker": ticker, "action": action,
                 "quantity": quantity, "price": price, "currency": currency,
                 "fee": fee}
        fields = {k: v for k, v in given.items() if v is not None}
        if broker is not None:
            row = next((t for t in _rows(paths) if t.id == id), None)
            if row is None:
                raise _Refused(f"There is no transaction {id} in this book.")
            fields["note"] = _with_broker(row.note, broker)
        if not fields:
            raise _Refused("Name at least one field to change.")
        return _edit(paths, [{"op": "update", "id": id, "fields": fields}],
                     plan_token, f"Edit transaction {id}")

    return await _run("edit_transaction", work, write=True)


async def delete_transactions(ids: Ids, plan_token: PlanToken = None) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        return _edit(paths, [{"op": "delete", "ids": list(dict.fromkeys(ids))}],
                     plan_token, f"Delete {len(set(ids))} transaction(s)")

    return await _run("delete_transactions", work, write=True)


async def rename_security(
    to: Annotated[str, Field(min_length=1, max_length=40,
                             description="The label to book them under, e.g. GRF.MC.")],
    label: Annotated[str | None, Field(
        min_length=1, max_length=40,
        description="Every row stored under exactly this label (an ISIN, a "
                    "broker code).")] = None,
    broker: Annotated[str | None, Field(
        min_length=1, max_length=40, description="Only that broker's rows.")] = None,
    ids: Annotated[list[int] | None, Field(
        min_length=1, max_length=200,
        description="These rows instead of a label.")] = None,
    plan_token: PlanToken = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.portfolio.fees import broker_of

        if ids:
            chosen = list(dict.fromkeys(ids))
        elif label:
            wanted = label.strip().upper()
            chosen = [t.id for t in _rows(paths) if t.ticker.upper() == wanted
                      and (not broker or broker_of(t) == broker.strip().lower())]
            if not chosen:
                raise _Refused(f"No transactions are stored under {wanted}.")
        else:
            raise _Refused("Name the rows: a label or ids.")
        target = to.strip().upper()
        return _edit(paths, [{"op": "relabel", "ids": chosen, "to": target}],
                     plan_token, f"Book {len(chosen)} row(s) under {target}")

    return await _run("rename_security", work, write=True)


async def record_transfer(
    out_ids: Annotated[list[int], Field(
        min_length=1, max_length=50,
        description="The rows that left the old broker (booked as sells).")],
    in_ids: Annotated[list[int], Field(
        max_length=50,
        description="The rows that arrived at the new one (booked as buys).")],
    to: Annotated[str | None, Field(
        min_length=1, max_length=40,
        description="Label to book every row of both legs under, when the "
                    "brokers spelled the company differently.")] = None,
    plan_token: PlanToken = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        ops: list[dict] = [{"op": "set_action", "ids": list(out_ids),
                            "action": "transfer_out"}]
        if in_ids:
            ops.append({"op": "set_action", "ids": list(in_ids),
                        "action": "transfer_in"})
        if to:
            ops.append({"op": "relabel", "ids": [*out_ids, *in_ids],
                        "to": to.strip().upper()})
        return _edit(paths, ops, plan_token, "Shares moved between brokers")

    return await _run("record_transfer", work, write=True)


async def apply_fix(
    key: Annotated[str, Field(min_length=1, max_length=200,
                              description="A finding's key from check_book.")],
    plan_token: PlanToken = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api import loaders
        from stocks.portfolio import demo, doctor

        rows = demo.without(_rows(paths))
        found = doctor.by_key(rows, key, loaders.display_symbol)
        if found is None:
            raise _Refused("No such finding any more; run check_book again.")
        if not found.fix:
            raise _Refused("That finding has no fix to apply; it needs the person "
                           "to say which rows are right.")
        return _edit(paths, found.fix, plan_token, f"Fix {found.kind} in {found.ticker}")

    return await _run("apply_fix", work, write=True)


async def edit_book(
    ops: Annotated[list[dict], Field(
        min_length=1, max_length=200,
        description="Applied in order: add{row}, update{id, fields}, "
                    "delete{ids}, set_action{ids, action}, relabel{ids, to}, "
                    "split_row{id, quantity}. A row an earlier op adds is -1, "
                    "-2, … to later ones.")],
    summary: Annotated[str, Field(max_length=300,
                                  description="What the edit is, in words.")] = "",
    plan_token: PlanToken = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        return _edit(paths, ops, plan_token, summary or "Edit")

    return await _run("edit_book", work, write=True)


Confirm = Annotated[bool, Field(
    description="false previews what would be undone; true does it.")]


async def undo_change(
    change_id: Annotated[int | None, Field(
        description="From change_history; omitted is the newest not undone.")] = None,
    confirm: Confirm = False,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio
        from stocks.portfolio import edits

        if change_id is None:
            target = edits.last_undoable(paths.db)
            if target is None:
                raise _Refused("There is no edit left to undo.")
        else:
            target = next((c for c in edits.history(paths.db, 500)
                           if c.id == change_id), None)
            if target is None:
                raise _Refused(f"There is no change {change_id}.")
        if not confirm:
            return {"kind": "undo_plan", "applied": False,
                    **_plain(portfolio._change(target)),
                    "next": "Nothing was written. Call again with confirm true "
                            "to put these rows back as they were."}
        try:
            done = edits.undo(target.id, path=paths.db)
        except (edits.Conflict, LookupError) as exc:
            raise _Refused(str(exc)) from exc
        obs.event("ledger.undone", rows=len(done.changes), via="mcp")
        return {"kind": "undo_done", "applied": True, **_plain(portfolio._change(done))}

    return await _run("undo_change", work, write=True)


async def undo_last_import(confirm: Confirm = False) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import import_statement

        if not confirm:
            return {"kind": "import_undo_plan", "applied": False,
                    **_plain(import_statement.last(paths)),
                    "next": "Nothing was written. Call again with confirm true "
                            "to delete these rows."}
        return {"kind": "import_undone", "applied": True,
                **_plain(import_statement.undo(paths))}

    return await _run("undo_last_import", work, write=True)


class SplitPick(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    date: str = Field(min_length=10, max_length=10)


async def apply_splits(
    splits: Annotated[list[SplitPick], Field(
        min_length=1, max_length=200,
        description="Which splits missing_splits reported, by ticker and date.")],
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import import_statement

        body = import_statement.ApplySplits(splits=[
            import_statement.SplitPick(ticker=s.ticker, date=s.date) for s in splits
        ])
        return {"kind": "splits_applied",
                **_plain(import_statement.splits_apply(paths, body))}

    return await _run("apply_splits", work, write=True)


# ------------------------------------------------- watchlist, memory, settings
# Small, whole and reversible by the next call, so applied at once: the host
# already asks the person before each one.


async def follow_ticker(
    ticker: Ticker,
    favorite: bool | None = None,
    tags: Annotated[list[str] | None, Field(
        max_length=20, description="Replaces its tags; [] removes them.")] = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import watchlist_edit

        body = watchlist_edit.NewEntry(ticker=_symbol(ticker), favorite=favorite,
                                       tags=tags)
        return {"kind": "watchlist_entry", **_plain(watchlist_edit.add(paths, body))}

    return await _run("follow_ticker", work, write=True)


async def unfollow_ticker(ticker: Ticker) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import watchlist_edit

        code = _symbol(ticker)
        watchlist_edit.drop(paths, code)
        return {"kind": "unfollowed", "ticker": code}

    return await _run("unfollow_ticker", work, write=True)


async def set_alerts(
    ticker: Ticker,
    alerts: Annotated[list[AlertRule], Field(
        max_length=20, description="The whole set; [] clears them.")],
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import watchlist_edit

        body = watchlist_edit.AlertsBody(alerts=alerts)
        done = watchlist_edit.set_alerts(paths, _symbol(ticker), body)
        return {"kind": "alerts", **_plain(done)}

    return await _run("set_alerts", work, write=True)


async def remember(
    text: Annotated[str, Field(min_length=1, max_length=240)],
    kind: Annotated[str | None, Field(
        description="goal, preference, decision, constraint, context or "
                    "routine (shown daily); guessed from the wording when "
                    "omitted.")] = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import chat_memory

        saved = chat_memory.add(chat_memory.NewMemory(text=text, kind=kind), paths)
        return {"kind": "memory", **_plain(saved)}

    return await _run("remember", work, write=True)


async def forget(
    memory_id: Annotated[str, Field(min_length=1, max_length=64,
                                    description="From investor_context.")],
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import chat_memory

        chat_memory.drop(memory_id, paths)
        return {"kind": "forgotten", "id": memory_id}

    return await _run("forget", work, write=True)


async def set_preferences(
    currency: Annotated[str | None, Field(description="Base currency, e.g. EUR.")] = None,
    language: Annotated[str | None, Field(description="en or es.")] = None,
    tax_residence: Annotated[str | None, Field(
        description="Country code whose tax rules apply, e.g. ES; auto follows "
                    "the browser.")] = None,
    tax_filing_status: str | None = None,
    tax_other_income: Annotated[float | None, Field(ge=0)] = None,
    tax_niit: bool | None = None,
    tax_church_rate: Annotated[float | None, Field(ge=0, le=1)] = None,
    tax_subnational_rate: Annotated[float | None, Field(ge=0, le=1)] = None,
    notify_digest: bool | None = None,
    notify_weekly: bool | None = None,
    notify_alerts: bool | None = None,
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import prefs

        given: dict[str, Any] = {
            "currency": currency, "language": language,
            "tax_residence": tax_residence, "tax_filing_status": tax_filing_status,
            "tax_other_income": tax_other_income, "tax_niit": tax_niit,
            "tax_church_rate": tax_church_rate,
            "tax_subnational_rate": tax_subnational_rate,
            "notify_digest": notify_digest, "notify_weekly": notify_weekly,
            "notify_alerts": notify_alerts,
        }
        patch = prefs.PrefsPatch.model_validate(
            {k: v for k, v in given.items() if v is not None}
        )
        return {"kind": "preferences", **_plain(prefs.update(paths, patch))}

    return await _run("set_preferences", work, write=True)


# ------------------------------------------------------------------ catalog


@dataclass(frozen=True)
class Spec:
    fn: Callable[..., Awaitable[CallToolResult]]
    title: str
    description: str
    view: bool = False
    # Listed and run only for a token granted `store.WRITE_SCOPE`.
    write: bool = False
    destructive: bool = False

    @property
    def name(self) -> str:
        return self.fn.__name__  # ty: ignore[unresolved-attribute]

    def kwargs(self) -> dict[str, Any]:
        if not self.write:
            annotations = READ_ONLY
        else:
            annotations = DESTROYS if self.destructive else WRITES
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "annotations": annotations,
        }


TOOLS: tuple[Spec, ...] = (
    Spec(portfolio_overview, "Portfolio overview",
         "Totals for the whole portfolio (value, cost, profit) and the largest "
         f"{OVERVIEW_POSITIONS} holdings with weight and today's move. Start here.",
         view=True),
    Spec(investor_context, "Investor profile and memories",
         "Who the portfolio belongs to: their investor profile (risk, horizon, "
         "focus, constraints, notes; `set` false means nobody filled it in) and "
         "what they told the TopStocks assistant to remember — goals, "
         "preferences, decisions, constraints, and `routine` items they asked "
         "to see daily. Context to frame advice by, never a source of figures. "
         "Read it before advising."),
    Spec(list_positions, "All positions",
         "Every holding: shares, cost, value, profit, weight and day move, "
         "largest first."),
    Spec(portfolio_performance, "Performance",
         "Returns over a window — time-weighted (TWR, the selection) and "
         "money-weighted (IRR, the money) — with volatility, drawdown and the "
         "daily value versus capital paid in.",
         view=True),
    Spec(list_transactions, "Transactions",
         "The ledger as stored, newest first, each row with its id: buys, "
         "sells, dividends, fees, transfers. Narrow by ticker, broker, action "
         "and dates; page with limit and offset."),
    Spec(income_report, "Dividends and fees",
         "Dividends received per year (gross, withheld, net) with the forward "
         "estimate, and what brokers charged in commission and spread."),
    Spec(risk_metrics, "Risk",
         "Volatility, maximum drawdown, betas, concentration, allocation by "
         "sector/country/currency, and correlation between the largest holdings."),
    Spec(tax_report, "Tax report",
         "Realized gains and losses per tax year under the account's own "
         "jurisdiction and share-matching rule, with each sale."),
    Spec(get_quotes, "Quotes",
         f"Current price and day move for up to {QUOTES_MAX} tickers."),
    Spec(ticker_details, "Ticker details",
         "One ticker: quote, valuation and quality metrics, and the account's "
         "own position and trades in it."),
    Spec(search_tickers, "Search tickers",
         "Find a ticker by symbol or company name, the account's own first."),
    Spec(get_watchlist, "Watchlist",
         "The tickers the account follows, with tags and any shares held."),
    Spec(upcoming_earnings, "Calendar",
         "Coming earnings dates, ex-dividend dates, tax deadlines and central "
         "bank decisions for the account's tickers."),
    Spec(check_book, "Check the book",
         "Mistakes in the ledger, each with the edit that fixes it: shares "
         "that moved broker but read as a sale and a new buy (often under a "
         "different ticker), one company under two labels, a trade imported "
         "twice, a sale of shares that never arrived. Fix one with apply_fix."),
    Spec(change_history, "Edit history",
         "Hand edits to the ledger, newest first, with where each came from "
         "(app, chat, telegram, mcp) and the rows it touched. Undoable by id."),
    Spec(simulate_sale, "Simulate a sale",
         "What selling some or all of a holding today would realize and add "
         "to this tax year's bill, under the account's own tax rules."),
    Spec(get_preferences, "Preferences",
         "Base currency, language, tax residence and filing details, and "
         "which notifications are on."),
    Spec(get_alerts, "Alerts",
         "One followed ticker's alert rules."),
    Spec(missing_splits, "Missing splits",
         "Stock splits the ledger lacks for current holdings, priced against "
         "the market's corporate-actions history. Slow: one lookup per holding."),
    # ---- edits, only with the write scope
    Spec(add_transactions, "Add transactions",
         f"Add up to {ADD_MAX} rows typed in by hand. Preview first: without "
         "plan_token nothing is written.", write=True),
    Spec(edit_transaction, "Edit a transaction",
         "Change fields of one row by id. Preview first: without plan_token "
         "nothing is written.", write=True, destructive=True),
    Spec(delete_transactions, "Delete transactions",
         "Delete rows by id. Preview first: without plan_token nothing is "
         "written.", write=True, destructive=True),
    Spec(rename_security, "Rename a security",
         "Book rows under another label — the fix when two brokers spelled "
         "one company differently (an ISIN vs GRF.MC). Preview first.",
         write=True, destructive=True),
    Spec(record_transfer, "Record a transfer",
         "Turn a sale at one broker and a buy at another into one move of "
         "shares, so no gain is realized and the cost basis carries over. "
         "Preview first.", write=True, destructive=True),
    Spec(apply_fix, "Apply a fix",
         "Apply the edit check_book proposed for one finding, by its key. "
         "Preview first.", write=True, destructive=True),
    Spec(edit_book, "Edit the book",
         "Any combination of row edits as one undoable change, for what the "
         "other tools cannot say. Preview first.", write=True, destructive=True),
    Spec(undo_change, "Undo an edit",
         "Put back the rows one edit changed. confirm false previews.",
         write=True, destructive=True),
    Spec(undo_last_import, "Undo the last import",
         "Delete exactly the rows the last statement import added. confirm "
         "false previews.", write=True, destructive=True),
    Spec(apply_splits, "Apply splits",
         "Write the splits missing_splits reported, named by ticker and date.",
         write=True),
    Spec(follow_ticker, "Follow a ticker",
         "Add a ticker to the watchlist, or set its favorite flag and tags.",
         write=True),
    Spec(unfollow_ticker, "Unfollow a ticker",
         "Remove a ticker from the watchlist, with its tags and alerts.",
         write=True, destructive=True),
    Spec(set_alerts, "Set alerts",
         "Replace a followed ticker's alert rules with this set. Read "
         "get_alerts first to keep the ones not being changed.",
         write=True, destructive=True),
    Spec(remember, "Remember",
         "Save something the person wants the TopStocks assistant to keep in "
         "mind; a routine is shown in their daily briefing.", write=True),
    Spec(forget, "Forget",
         "Delete one saved memory by its id from investor_context.",
         write=True, destructive=True),
    Spec(set_preferences, "Set preferences",
         "Change base currency, language, tax residence and filing details, "
         "or notifications. Only the fields given change.", write=True),
)

WRITE_NAMES = frozenset(spec.name for spec in TOOLS if spec.write)
