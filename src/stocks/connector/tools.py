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
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException
from yfinance.exceptions import YFRateLimitError

from stocks import accounts, obs
from stocks.api import cache, deps
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


class _Refused(Exception):
    """A request this tool will not run; the message is safe to show."""


# ------------------------------------------------------------------ the road


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


async def _run(tool: str, work: Callable[[UserPaths], dict]) -> CallToolResult:
    token = get_access_token()
    email = token.subject if token is not None else None
    if not email:
        return _error("Not signed in to TopStocks.")
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
) -> CallToolResult:
    def work(paths: UserPaths) -> dict:
        from stocks.api.routes import portfolio

        page = portfolio.transactions(paths, limit, offset, base)
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
                {"kind": m.kind, "text": m.text, "tickers": list(m.tickers),
                 "since": m.created[:10]}
                for m in saved
            ],
        }

    return await _run("investor_context", work)


# ------------------------------------------------------------------ catalog


@dataclass(frozen=True)
class Spec:
    fn: Callable[..., Awaitable[CallToolResult]]
    title: str
    description: str
    view: bool = False

    @property
    def name(self) -> str:
        return self.fn.__name__  # ty: ignore[unresolved-attribute]

    def kwargs(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "annotations": READ_ONLY,
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
         "The imported ledger, newest first: buys, sells, dividends, fees, "
         "transfers. Page with limit and offset."),
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
)
