"""The connector's tools, called the way Claude calls them: JSON-RPC at `/mcp`.

The token comes straight from the ledger rather than through the consent
dance (`test_connector_oauth.py` walks that). What matters here is what a
tool answers with: the account the token names and no other, the same
figures the app's own routes compute, a size a model can read, and an error
sentence — never a traceback — when anything underneath gives way.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.connector import oauth, store, tools
from stocks.connector.server import Door
from stocks.portfolio import ledger
from stocks.portfolio.ledger import Transaction

ORIGIN = "https://testserver"
EMAIL = "holder@example.com"
PROTOCOL = "2025-11-25"


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", ORIGIN)
    door = Door()
    app = Starlette(
        routes=[Route(p, door) for p in oauth.PATHS],
        lifespan=lambda app: door.lifespan(),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        yield client


@pytest.fixture(autouse=True)
def _offline_prices(monkeypatch):
    """Nothing below a tool may reach Yahoo from a test."""
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(loaders, "basket_values", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(loaders, "quotes", lambda tickers: {})


@pytest.fixture
def book(monkeypatch, tmp_path):
    """One account: a watchlist, two buys and a sale, in EUR."""
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    ledger.add_many([
        Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 2.0, note="t"),
        Transaction("2024-02-01", "AAPL", "buy", 5, 110.0, "EUR", 1.0, note="t"),
        Transaction("2024-03-01", "AAPL", "sell", 4, 130.0, "EUR", 1.5, note="t"),
    ], path=paths.db)
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    for fn in vars(loaders).values():
        if callable(fn) and hasattr(fn, "cache_clear"):
            fn.cache_clear()
    return paths


@pytest.fixture
def token(book) -> str:
    return store.ledger().issue(
        email=EMAIL, client_id="c1", client_name="Claude", client_kind="cimd",
        redirect_host="claude.ai",
    ).access


def rpc(client: TestClient, token: str, method: str, params: dict | None = None,
        **headers):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
            **headers,
        },
    )


def call(client: TestClient, token: str, name: str, **arguments) -> dict:
    r = rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" not in body, body
    return body["result"]


def ok(result: dict) -> dict:
    assert not result.get("isError"), result["content"][0]["text"]
    return result["structuredContent"]


# ------------------------------------------------------------------ catalog


def test_every_tool_is_listed_read_only(site, token):
    r = rpc(site, token, "tools/list")
    listed = {t["name"]: t for t in r.json()["result"]["tools"]}
    assert set(listed) == {spec.name for spec in tools.TOOLS}
    for tool in listed.values():
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["destructiveHint"] is False
        assert tool["title"]
        assert tool["description"]


def test_nothing_that_writes_or_wanders_is_exposed(site, token):
    names = {t["name"] for t in rpc(site, token, "tools/list").json()["result"]["tools"]}
    for word in ("import", "delete", "add", "remove", "write", "web", "recall"):
        assert not any(word in n for n in names), names


# -------------------------------------------------------------- the book


def test_the_overview_puts_priced_holdings_first(site, token, monkeypatch):
    """An unpriced name ranks by nothing it is worth today, so it goes last."""
    table = pd.DataFrame(
        {
            "shares": [6.0, 5.0],
            "ccy": ["EUR", "EUR"],
            "cost": [600.0, 1000.0],
            "value": [900.0, float("nan")],
            "pnl": [300.0, float("nan")],
            "pnl_pct": [0.5, float("nan")],
        },
        index=pd.Index(["AAPL", "MSFT"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    data = ok(call(site, token, "portfolio_overview"))
    assert data["kind"] == "overview"
    assert data["summary"]["base"] == "EUR"
    assert data["summary"]["unpriced"] == 1
    assert [p["ticker"] for p in data["positions"]] == ["AAPL", "MSFT"]
    assert data["positions"][1]["value"] is None
    assert data["positions_total"] == 2
    # Each row says where its logo is, absolute on this site or None.
    assert all("logo" in p for p in data["positions"])


def test_text_and_structure_carry_the_same_figures(site, token):
    result = call(site, token, "list_positions")
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_transactions_page_newest_first(site, token):
    data = ok(call(site, token, "list_transactions", limit=2))
    dates = [row["date"] for row in data["transactions"]]
    assert dates == sorted(dates, reverse=True)
    assert len(dates) == 2


def test_the_tax_report_lists_the_sale(site, token):
    data = ok(call(site, token, "tax_report"))
    assert data["kind"] == "tax"
    assert [s["ticker"] for s in data["sales"]] == ["AAPL"]


def test_the_watchlist_is_the_accounts_own(site, token):
    data = ok(call(site, token, "get_watchlist"))
    assert "AAPL" in json.dumps(data)


# ----------------------------------------------------- the shared memory


def test_claude_reads_the_memory_the_assistant_keeps(site, token, book):
    """One AI, one memory: what the user told the app's assistant reaches
    Claude too, with the profile sentence the chat is given."""
    from stocks.chat import learnings

    learnings.add(book.learnings, "Nunca pasaré de un 10% en ASML",
                  kind="constraint", tickers=["ASML"])
    learnings.add(book.learnings, "Cada día dime cómo va el Nasdaq", kind="routine")
    book.prefs.write_text(json.dumps({
        "currency": "EUR",
        "investor_profile": {"risk": "conservative", "horizon": "1_3y", "set": True},
    }))
    data = ok(call(site, token, "investor_context"))
    assert data["kind"] == "context"
    assert data["memory_enabled"] is True
    assert [(m["kind"], m["text"]) for m in data["memories"]] == [
        ("constraint", "Nunca pasaré de un 10% en ASML"),
        ("routine", "Cada día dime cómo va el Nasdaq"),
    ]
    assert data["memories"][0]["tickers"] == ["ASML"]
    assert data["profile"]["set"] is True
    assert "a conservative" in data["profile"]["persona"]


def test_memory_switched_off_is_no_memory_here_either(site, token, book):
    from stocks.chat import learnings

    learnings.add(book.learnings, "Prefiero dividendos crecientes")
    book.prefs.write_text(json.dumps({"currency": "EUR", "chat_memory": False}))
    data = ok(call(site, token, "investor_context"))
    assert data["memory_enabled"] is False
    assert data["memories"] == []
    assert "dividendos" not in result_text(call(site, token, "investor_context"))


def test_the_server_tells_claude_to_read_the_memory_first():
    from stocks.connector import server

    assert "investor_context" in server.INSTRUCTIONS
    assert "investor_context" in {spec.name for spec in tools.TOOLS}


def result_text(result: dict) -> str:
    return result["content"][0]["text"]


@pytest.mark.parametrize("name, arguments", [
    ("portfolio_performance", {"window": "1y"}),
    ("income_report", {}),
    ("risk_metrics", {}),
])
def test_the_analytic_tools_answer_offline(site, token, name, arguments):
    result = call(site, token, name, **arguments)
    assert not result.get("isError"), result["content"][0]["text"]


def test_money_can_be_asked_for_in_another_currency(site, token, monkeypatch):
    from stocks.api.routes import portfolio

    seen: list[str | None] = []
    real = portfolio.positions

    def spy(paths, base=None):
        seen.append(base)
        return real(paths, "EUR")

    monkeypatch.setattr(portfolio, "positions", spy)
    ok(call(site, token, "list_positions", base="USD"))
    assert seen == ["USD"]


# ------------------------------------------------------------ the market


def test_quotes_are_deduplicated_and_upper_cased(site, token, monkeypatch):
    from stocks.api.routes import market
    from stocks.api.schemas import Quotes

    asked: list[str] = []

    def quotes(tickers: str):
        asked.append(tickers)
        return Quotes(quotes=[])

    monkeypatch.setattr(market, "quotes", quotes)
    ok(call(site, token, "get_quotes", tickers=["aapl", "AAPL ", "msft"]))
    assert asked == ["AAPL,MSFT"]


@pytest.mark.parametrize("tool, arguments, module, handler, expected", [
    ("ticker_details", {"ticker": "aapl", "base": "USD"},
     "ticker", "metrics", ("AAPL", "USD")),
    ("search_tickers", {"query": " apple ", "limit": 5},
     "search", "find", ("<paths>", "apple", 5)),
    ("upcoming_earnings", {}, "earnings", "earnings", ("<paths>",)),
])
def test_the_market_tools_ask_their_route_the_right_question(
    site, token, book, monkeypatch, tool, arguments, module, handler, expected
):
    """What each tool hands the route it wraps; the 4xx detail comes back."""
    from importlib import import_module

    from starlette.exceptions import HTTPException

    seen: list[tuple] = []

    def spy(*args):
        seen.append(tuple("<paths>" if a == book else a for a in args))
        raise HTTPException(404, "no such thing")

    monkeypatch.setattr(import_module(f"stocks.api.routes.{module}"), handler, spy)
    result = call(site, token, tool, **arguments)
    assert seen == [expected]
    assert result["isError"] is True
    assert result["content"][0]["text"] == "no such thing"


@pytest.mark.parametrize("bad", ["../etc", "A B", "<script>", "X" * 40])
def test_a_ticker_that_is_not_a_symbol_is_refused_in_words(site, token, bad):
    result = call(site, token, "ticker_details", ticker=bad)
    assert result["isError"] is True
    assert "ticker" in result["content"][0]["text"].lower()


# ----------------------------------------------------------------- failure


def test_an_internal_failure_is_a_sentence_and_a_place(site, token, monkeypatch, caplog):
    from stocks.api.routes import portfolio

    def boom(*a, **k):
        raise RuntimeError("holder@example.com owns 11 AAPL")

    monkeypatch.setattr(portfolio, "positions", boom)
    result = call(site, token, "list_positions")
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "AAPL" not in text and "Traceback" not in text
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "mcp.tool_failed" in logged
    assert "holder@example.com" not in logged
    assert "owns 11" not in logged


def test_a_throttled_feed_says_so(site, token, monkeypatch):
    from yfinance.exceptions import YFRateLimitError

    from stocks.api.routes import market

    def throttled(tickers: str):
        raise YFRateLimitError()

    monkeypatch.setattr(market, "quotes", throttled)
    result = call(site, token, "get_quotes", tickers=["AAPL"])
    assert result["isError"] is True
    assert "rate limiting" in result["content"][0]["text"]


def test_a_burst_hits_the_accounts_own_wall(site, token, monkeypatch):
    monkeypatch.setattr(tools, "TOOL_MAX", 3)
    for _ in range(3):
        ok(call(site, token, "get_watchlist"))
    result = call(site, token, "get_watchlist")
    assert result["isError"] is True
    assert "try again" in result["content"][0]["text"]


def test_a_token_whose_account_is_gone_reads_nothing(site, monkeypatch, tmp_path):
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    users = tmp_path / "nobody"
    real = accounts.paths_for
    monkeypatch.setattr(
        accounts, "paths_for",
        lambda email, owner=None, users_dir=users: real(email, owner, users_dir=users),
    )
    ghost = store.ledger().issue(
        email="ghost@example.com", client_id="c1", client_name="Claude",
        client_kind="cimd", redirect_host="claude.ai",
    ).access
    result = call(site, ghost, "get_watchlist")
    assert result["isError"] is True
    assert not (users / accounts.slug("ghost@example.com")).exists()


# ----------------------------------------------------------- size and shape


def test_a_long_answer_is_cut_to_fit_and_says_so():
    rows = [{"ticker": f"T{i}", "note": "x" * 200} for i in range(500)]
    data, text = tools._fit({"kind": "positions", "positions": rows})
    assert len(text) <= tools.TEXT_LIMIT
    assert data["truncated"] is True
    assert json.loads(text) == data


def test_floats_lose_noise_not_meaning():
    assert tools._compact({"v": 0.1 + 0.2, "n": [1 / 3]}) == {
        "v": 0.3, "n": [0.33333333]}


def test_a_long_history_keeps_its_last_point():
    points = list(range(1000))
    thinned = tools._thin(points, 160)
    assert len(thinned) == 160
    assert thinned[0] == 0 and thinned[-1] == 999


# --------------------------------------------------------------- the view


def test_the_view_is_served_as_an_mcp_app(site, token):
    from stocks.connector import views

    r = rpc(site, token, "resources/read", {"uri": views.URI})
    (content,) = r.json()["result"]["contents"]
    assert content["mimeType"] == "text/html;profile=mcp-app"
    assert '"origin":"https://testserver"' in content["text"]
    assert views.CONFIG_MARK not in content["text"]
    # Logos come from the mirror on this site, the one origin it may load.
    assert content["_meta"]["ui"]["csp"]["resourceDomains"] == [ORIGIN]
    tools_ = rpc(site, token, "tools/list").json()["result"]["tools"]
    listed = {t["name"]: t for t in tools_}
    assert listed["portfolio_overview"]["_meta"]["ui"]["resourceUri"] == views.URI
