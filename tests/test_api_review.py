"""`GET /v1/review` over HTTP: the book judged, outside names beside it.

The verdict rules are `tests/test_review.py`'s. What is tested here is what
the route adds: held rows carry weight, target and the money to move; a sale
carries the tax the replay says it costs; a buy waits out an open repurchase
window; `?add=` weighs names nobody follows without writing anything.
Nothing reaches the network — every fetch is replaced.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.api.routes import review as route
from stocks.chat import whatif
from stocks.portfolio import ledger
from stocks.portfolio.ledger import Transaction

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

QUALITY = {
    "pe_fwd": 9.0, "fcf_yield": 0.10, "ev_ebitda": 9.0, "ev": 1e11,
    "roic": 0.41, "op_margin": 0.36, "moat": 80.0,
}
WEAK = {
    "pe_fwd": 40.0, "fcf_yield": 0.007, "ev_ebitda": 105.0, "ev": 1e12,
    "roic": 0.05, "op_margin": 0.17, "moat": 33.0,
}
METRICS = {"ADBE": QUALITY, "AMD": WEAK, "BKNG": QUALITY, "SNAP": WEAK}
KINDS = {"XEON.DE": "money_market"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def _cold_caches():
    memos = [
        fn for fn in vars(loaders).values() if callable(fn) and hasattr(fn, "cache_clear")
    ]
    for fn in memos:
        fn.cache_clear()
    yield
    for fn in memos:
        fn.cache_clear()


PROFILES = {
    "AMD": {"sector": "Technology", "quoteType": "EQUITY"},
    "BKNG": {"sector": "Consumer Cyclical", "quoteType": "EQUITY"},
    "XEON.DE": {"quoteType": "ETF"},
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(route, "_metrics", lambda symbol: METRICS.get(symbol))
    monkeypatch.setattr(route, "_kind", lambda symbol: KINDS.get(symbol, "stock"))
    monkeypatch.setattr(route.profiles, "known", lambda symbol: PROFILES.get(symbol))
    monkeypatch.setattr(loaders, "display_symbol", lambda ticker: ticker)
    monkeypatch.setattr(loaders, "basket_report_since", lambda *a, **k: None)
    monkeypatch.setattr(whatif, "_price", lambda ticker: (150.0, "EUR"))


@pytest.fixture
def book(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text(
        "watchlist:\n  - ticker: AMD\n    favorite: true\n    tags: [chips]\n"
        "  - ticker: BKNG\n    tags: [travel, travel]\n  - ticker: SNAP\n"
    )
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    paths.prefs.write_text(json.dumps({"currency": "EUR", "tax_residence": "ES"}))
    ledger.add_many(
        [
            Transaction("2026-01-02", "AMD", "buy", 10, 100.0, "EUR", 0.0),
            Transaction("2026-01-02", "XEON.DE", "buy", 50, 140.0, "EUR", 0.0),
            Transaction("2026-01-02", "ADBE", "buy", 10, 400.0, "EUR", 0.0),
            # A loss sold a month ago: buying ADBE back reopens it.
            Transaction(f"{_days_ago(30)}", "ADBE", "sell", 5, 380.0, "EUR", 0.0),
        ],
        path=paths.db,
    )
    table = pd.DataFrame(
        {
            "cost": [1_000.0, 8_200.0, 2_000.0],
            "value": [1_500.0, 8_200.0, 300.0],
            "pnl": [500.0, 0.0, -500.0],
            "pnl_pct": [0.5, 0.0, -0.25],
        },
        index=pd.Index(["AMD", "XEON.DE", "ADBE"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    return paths


def _days_ago(n: int) -> str:
    from datetime import date, timedelta

    return (date.today() - timedelta(days=n)).isoformat()


def _get(client, **params):
    response = client.get(
        "/v1/review", params={"account": EMAIL, **params}, headers=AUTH
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_book_is_judged_actions_first(client, book):
    body = _get(client)
    verdicts = {r["ticker"]: r["verdict"] for r in body["held"]}
    assert verdicts == {"AMD": "sell", "ADBE": "add", "XEON.DE": "cash"}
    assert [r["ticker"] for r in body["held"]] == ["AMD", "ADBE", "XEON.DE"]
    assert body["total"] == 10_000.0


def test_a_sale_carries_its_money_and_its_tax(client, book):
    amd = next(r for r in _get(client)["held"] if r["ticker"] == "AMD")
    assert amd["target_weight"] == 0.0
    assert amd["delta"] == pytest.approx(-1_500.0)
    assert (amd["pnl"], amd["pnl_pct"]) == (500.0, 0.5)
    # 10 shares bought at 100, sold at 150: a 500 gain, less the 100 ADBE
    # loss already booked this year, taxed in Spain.
    assert amd["tax"] is not None and amd["tax"] > 0


def test_a_buy_inside_the_repurchase_window_says_when(client, book):
    adbe = next(r for r in _get(client)["held"] if r["ticker"] == "ADBE")
    # 3% of a 10,000 book taken to 5%.
    assert adbe["delta"] == pytest.approx(200.0)
    assert adbe["buy_after"] is not None and adbe["buy_after"] > _days_ago(0)
    assert adbe["tax"] is None


def test_outside_names_are_the_unheld_watchlist_plus_add(client, book):
    body = _get(client, add="nvda, bkng")
    tickers = [r["ticker"] for r in body["candidates"]]
    # AMD is held, so it is not a candidate; BKNG once despite being in both.
    assert sorted(tickers) == ["BKNG", "NVDA", "SNAP"]
    verdicts = {r["ticker"]: r["verdict"] for r in body["candidates"]}
    assert verdicts == {"BKNG": "buy", "SNAP": "pass", "NVDA": "unrated"}
    assert body["added"] == ["NVDA", "BKNG"]
    assert all(r["held"] is False and r["weight"] is None for r in body["candidates"])


def test_every_row_carries_its_sector_for_the_filter(client, book):
    body = _get(client, add="bkng")
    sectors = {r["ticker"]: r["sector"] for r in body["held"] + body["candidates"]}
    # From the profile memo; a fund and a name never profiled have none.
    assert sectors["AMD"] == "Technology"
    assert sectors["BKNG"] == "Consumer Cyclical"
    assert sectors["XEON.DE"] is None
    assert sectors["ADBE"] is None


def test_every_row_says_where_the_watchlist_files_it(client, book):
    body = _get(client, add="nvda")
    rows = {r["ticker"]: r for r in body["held"] + body["candidates"]}
    # Held names carry their star and groups too: the page's "include"
    # filter narrows by them on both sides of the book.
    assert (rows["AMD"]["watched"], rows["AMD"]["favorite"]) == (True, True)
    assert rows["AMD"]["lists"] == ["chips"]
    assert rows["BKNG"]["lists"] == ["travel"]
    assert rows["SNAP"]["watched"] is True and rows["SNAP"]["favorite"] is False
    # Typed into the box, followed nowhere.
    assert (rows["NVDA"]["watched"], rows["NVDA"]["lists"]) == (False, [])


def test_the_plan_adds_up_the_moves(client, book):
    plan = _get(client)["plan"]
    assert plan["sells"] == pytest.approx(1_500.0)
    assert plan["buys"] == pytest.approx(200.0)
    assert plan["tax_currency"] == "EUR"


def test_add_refuses_what_is_not_a_ticker(client, book):
    response = client.get(
        "/v1/review", params={"account": EMAIL, "add": "AAPL,<script>"}, headers=AUTH
    )
    assert response.status_code == 422


def test_an_empty_book_still_answers_its_watchlist(client, book, monkeypatch):
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: pd.DataFrame())
    body = _get(client)
    assert body["held"] == [] and body["total"] is None
    assert {r["ticker"] for r in body["candidates"]} == {"AMD", "BKNG", "SNAP"}
