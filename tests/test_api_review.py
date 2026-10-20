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
from stocks.analysis import review as engine
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
# Weak enough that no tax bill holds its sale (`engine.COSTLY_FLOOR`).
WEAK = {
    "pe_fwd": 40.0, "fcf_yield": 0.007, "ev_ebitda": 105.0, "ev": 1e12,
    "roic": 0.03, "op_margin": 0.08, "moat": 20.0,
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
    "AMD": {
        "sector": "Technology",
        "country": "United States",
        "currency": "USD",
        "quoteType": "EQUITY",
    },
    "BKNG": {
        "sector": "Consumer Cyclical",
        "country": "United States",
        "currency": "USD",
        "quoteType": "EQUITY",
    },
    "XEON.DE": {"currency": "EUR", "quoteType": "ETF"},
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
            "shares": [10.0, 50.0, 5.0],
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


def test_every_scored_name_is_recorded_for_the_maps_trail(client, book):
    from datetime import date

    from stocks.data import score_history

    body = _get(client)
    adbe = next(r for r in body["held"] if r["ticker"] == "ADBE")
    point = score_history.at("ADBE", date.today(), 0)
    assert point == (round(adbe["quality"], 1), round(adbe["cheapness"], 1))
    assert score_history.at("XEON.DE", date.today(), 0) is None  # cash: no score


def test_a_sale_carries_its_money_and_its_tax(client, book):
    amd = next(r for r in _get(client)["held"] if r["ticker"] == "AMD")
    assert amd["target_weight"] == 0.0
    assert amd["delta"] == pytest.approx(-1_500.0)
    assert (amd["pnl"], amd["pnl_pct"]) == (500.0, 0.5)
    # 10 shares bought at 100, sold at 150: a 500 gain, less the 100 ADBE
    # loss already booked this year, taxed in Spain.
    assert amd["tax"] is not None and amd["tax"] > 0


def test_a_held_share_is_priced_in_the_currency_it_trades_in(client, book, monkeypatch):
    table = loaders.positions_table().assign(ccy=["USD", "EUR", "EUR"])
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    monkeypatch.setattr(
        loaders, "spot_rates", lambda ccys, base="EUR": {"USD": 0.5, "EUR": 1.0}
    )
    body = _get(client, add="bkng")
    rows = {r["ticker"]: r for r in body["held"] + body["candidates"]}
    # 1,500 EUR over 10 shares at 0.5 EUR a dollar: the dollar quote.
    assert (rows["AMD"]["price"], rows["AMD"]["currency"]) == (300.0, "USD")
    assert rows["XEON.DE"]["price"] == pytest.approx(164.0)
    # Never profiled, so no code to print it under; an outside name has none.
    assert rows["ADBE"]["price"] is None
    assert rows["BKNG"]["price"] is None


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
    # ADBE's add to 5% and BKNG, bought outside with what the sale leaves.
    assert plan["buys"] == pytest.approx(200.0 + 500.0)
    assert plan["tax_currency"] == "EUR"


def test_add_refuses_what_is_not_a_ticker(client, book):
    response = client.get(
        "/v1/review", params={"account": EMAIL, "add": "AAPL,<script>"}, headers=AUTH
    )
    assert response.status_code == 422


def test_an_empty_book_still_answers_its_watchlist(client, book, monkeypatch):
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(loaders, "ledger_state", lambda *a, **k: ([], [], []))
    body = _get(client)
    assert body["held"] == [] and body["total"] is None
    assert {r["ticker"] for r in body["candidates"]} == {"AMD", "BKNG", "SNAP"}


def test_sales_share_one_replay_priced_at_the_book(client, book, monkeypatch):
    replays = []
    real = whatif.replay
    monkeypatch.setattr(
        whatif, "replay", lambda **kw: replays.append(kw) or real(**kw)
    )

    def no_quote(ticker):
        raise AssertionError(f"quoted {ticker}: the book already priced it")

    monkeypatch.setattr(whatif, "_price", no_quote)
    monkeypatch.setitem(METRICS, "ADBE", WEAK)  # a second sale
    held = {r["ticker"]: r for r in _get(client)["held"]}
    assert held["AMD"]["tax"] is not None and held["ADBE"]["tax"] is not None
    assert len(replays) == 1


def test_what_the_page_proposes_goes_in_the_journal_once(client, book, monkeypatch):
    from stocks.chat import journal

    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    _get(client, add="nvda")
    _get(client, add="nvda")
    entries = journal.load(book.journal)
    # Sell, add and buy are proposals; cash, pass and unrated are not, and a
    # second visit the same day is the same entries.
    assert {(e.ticker, e.action) for e in entries} == {
        ("AMD", "sell"), ("ADBE", "add"), ("BKNG", "buy")}
    assert all(e.times == 1 and e.state == "open" for e in entries)
    amd = next(e for e in entries if e.ticker == "AMD")
    assert amd.snapshot["target_weight"] == 0.0 and amd.reasons


def test_a_plan_that_moves_nothing_is_advice_to_stay(client, book, monkeypatch):
    from stocks.chat import journal

    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    moving = loaders.positions_table()
    still = pd.DataFrame(
        {
            "shares": [10.0, 5.0],
            "cost": [1_000.0, 2_000.0],
            "value": [5_000.0, 5_000.0],
            "pnl": [4_000.0, 3_000.0],
            "pnl_pct": [4.0, 1.5],
        },
        index=pd.Index(["ADBE", "BKNG"], name="ticker"),
    )
    current = {"table": still}
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: current["table"])
    body = _get(client)
    assert (body["plan"]["sells"], body["plan"]["buys"]) == (0, 0)
    # (BKNG is outside too: the ledger, not the priced table, says what is held.)
    entries = journal.load(book.journal)
    [stay] = [e for e in entries if e.source == "review" and not e.ticker]
    assert (stay.action, stay.subject, stay.ticker) == ("stay", "review:book", "")
    assert stay.snapshot == {"value": 10_000.0, "currency": "EUR"}
    # A plan that moves again withdraws it.
    current["table"] = moving
    _get(client)
    entries = journal.load(book.journal)
    assert next(e for e in entries if e.action == "stay").state == "lapsed"
    assert {e.action for e in entries if e.state == "open"} == {"sell", "add", "buy"}


def test_an_add_the_sales_cannot_pay_for_waits_for_new_money(
    client, book, monkeypatch
):
    table = pd.DataFrame(
        {
            "shares": [50.0, 5.0],
            "cost": [9_700.0, 300.0],
            "value": [9_700.0, 300.0],
            "pnl": [0.0, 0.0],
            "pnl_pct": [0.0, 0.0],
        },
        index=pd.Index(["XEON.DE", "ADBE"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    body = _get(client)
    adbe = next(r for r in body["held"] if r["ticker"] == "ADBE")
    assert adbe["verdict"] == "hold" and adbe["reasons"][0] == "needs_new_money"
    assert adbe["delta"] is None
    # 3% of a 10,000 book to the 5% line.
    assert adbe["new_money"] == pytest.approx(200.0)
    plan = body["plan"]
    assert (plan["sells"], plan["buys"]) == (0, 0)
    assert plan["new_money"] == pytest.approx(200.0)
    # The idle cash counts it beside the outside buy.
    [idle] = [n for n in body["notes"] if n["key"] == "cash_heavy"]
    assert idle["count"] == 2


def _scored_as(monkeypatch, metrics, quality, cheapness):
    real = engine.score

    def score(m):
        if m is metrics:
            return engine.Scores(quality, cheapness, cheap_reads=2)
        return real(m)

    monkeypatch.setattr(engine, "score", score)


def test_a_sale_the_page_proposed_holds_to_the_plain_line(client, book, monkeypatch):
    from datetime import date

    from stocks.chat import journal

    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    near = dict(WEAK)
    monkeypatch.setitem(METRICS, "AMD", near)
    _scored_as(monkeypatch, near, 37.0, 10.0)
    # Light enough not to be trimmed instead, and at a loss: no tax holds it.
    table = pd.DataFrame(
        {
            "shares": [10.0, 50.0, 5.0],
            "cost": [1_000.0, 8_200.0, 2_000.0],
            "value": [500.0, 9_000.0, 500.0],
            "pnl": [-500.0, 800.0, -1_500.0],
            "pnl_pct": [-0.5, 0.1, -0.75],
        },
        index=pd.Index(["AMD", "XEON.DE", "ADBE"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    amd = next(r for r in _get(client)["held"] if r["ticker"] == "AMD")
    assert amd["verdict"] == "hold" and amd["reasons"][0] == "close_call"
    journal.record(
        book.journal,
        [
            journal.Shown(
                source="review", subject="review:AMD", action="sell", ticker="AMD"
            )
        ],
        date.today(),
    )
    amd = next(r for r in _get(client)["held"] if r["ticker"] == "AMD")
    assert amd["verdict"] == "sell"


def test_a_sale_dearer_in_tax_than_its_case_waits(client, book, monkeypatch):
    # Weak but not hopeless (quality 33), sold at a 50% gain: Spain's tax
    # is over 5% of what the sale raises.
    _scored_as(monkeypatch, WEAK, 33.0, 2.0)
    body = _get(client)
    amd = next(r for r in body["held"] if r["ticker"] == "AMD")
    assert amd["verdict"] == "hold" and amd["reasons"][0] == "sale_costly"
    assert amd["delta"] is None and amd["tax"] is None
    assert body["plan"]["sells"] == 0


def test_a_book_of_one_or_two_companies_is_told_so(client, book, monkeypatch):
    # 82% in a money-market fund, with ADBE to add and BKNG to buy: the only
    # thing to say is that the cash sits idle beside them.
    [idle] = _get(client)["notes"]
    assert (idle["key"], idle["count"]) == ("cash_heavy", 2)
    assert idle["weight"] == pytest.approx(0.82)
    table = pd.DataFrame(
        {
            "shares": [10.0, 5.0],
            "cost": [1_000.0, 2_000.0],
            "value": [5_000.0, 5_000.0],
            "pnl": [4_000.0, 3_000.0],
            "pnl_pct": [4.0, 1.5],
        },
        index=pd.Index(["ADBE", "BKNG"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    body = _get(client)
    [note] = [n for n in body["notes"] if n["key"] == "few_names"]
    assert note["count"] == 2
    # Half the book each, and neither is cut for it.
    assert {r["verdict"] for r in body["held"]} == {"hold"}
    assert body["plan"]["sells"] == 0


def test_a_concentration_cut_dear_in_tax_is_staged(client, book, monkeypatch):
    # BKNG bought at 50 and worth 600: a sale is almost all gain.
    ledger.add_many(
        [Transaction("2026-01-02", "BKNG", "buy", 10, 50.0, "EUR", 0.0)], path=book.db
    )
    table = pd.DataFrame(
        {
            "shares": [10.0, 50.0, 5.0, 10.0],
            "cost": [1_000.0, 8_200.0, 2_000.0, 500.0],
            "value": [1_500.0, 8_200.0, 300.0, 6_000.0],
            "pnl": [500.0, 0.0, -500.0, 5_500.0],
            "pnl_pct": [0.5, 0.0, -0.25, 11.0],
        },
        index=pd.Index(["AMD", "XEON.DE", "ADBE", "BKNG"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    held = {r["ticker"]: r for r in _get(client)["held"]}
    bkng = held["BKNG"]
    assert bkng["verdict"] == "trim"
    assert bkng["reasons"][:2] == ["concentrated", "tax_staged"]
    # Three companies: the line is 35%, the even share a third; a good name
    # is cut halfway to that, and staging takes half of the cut.
    line, even, weight = 0.35, 1 / 3, 6_000 / 16_000
    halfway = (line + even) / 2
    assert bkng["target_weight"] == pytest.approx(weight - (weight - halfway) / 2)
    assert bkng["tax"] > 0
    # A sale for quality is not staged.
    assert held["AMD"]["verdict"] == "sell" and "tax_staged" not in held["AMD"]["reasons"]


def test_open_losses_that_would_cut_the_plans_tax_are_named(client, book, monkeypatch):
    # BKNG's trim and AMD's sale realise gains; INTC, unrated and kept,
    # sits 800 under its cost.
    ledger.add_many(
        [
            Transaction("2026-01-02", "BKNG", "buy", 10, 50.0, "EUR", 0.0),
            Transaction("2026-01-02", "INTC", "buy", 10, 100.0, "EUR", 0.0),
        ],
        path=book.db,
    )
    table = pd.DataFrame(
        {
            "shares": [10.0, 50.0, 5.0, 10.0, 10.0],
            "cost": [1_000.0, 8_200.0, 2_000.0, 500.0, 1_000.0],
            "value": [1_500.0, 8_200.0, 300.0, 6_000.0, 200.0],
            "pnl": [500.0, 0.0, -500.0, 5_500.0, -800.0],
            "pnl_pct": [0.5, 0.0, -0.25, 11.0, -0.8],
        },
        index=pd.Index(["AMD", "XEON.DE", "ADBE", "BKNG", "INTC"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    body = _get(client)
    held = {r["ticker"]: r for r in body["held"]}
    assert held["INTC"]["verdict"] == "unrated"
    [note] = [n for n in body["notes"] if n["key"] == "tax_offset"]
    # ADBE, the add, is not offered for sale even though it is under cost.
    assert note["tickers"] == ["INTC"] and note["count"] == 1
    # 800 of loss against gains taxed at 19%: about 152 back.
    assert note["amount"] == pytest.approx(800 * 0.19, rel=0.05)
    assert note["day"] > _days_ago(0)


def test_no_sale_in_the_plan_means_no_offset_note(client, book, monkeypatch):
    table = pd.DataFrame(
        {
            "shares": [50.0, 10.0],
            "cost": [8_200.0, 1_000.0],
            "value": [8_200.0, 200.0],
            "pnl": [0.0, -800.0],
            "pnl_pct": [0.0, -0.8],
        },
        index=pd.Index(["XEON.DE", "INTC"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    assert "tax_offset" not in [n["key"] for n in _get(client)["notes"]]


def test_without_a_chosen_residence_the_tax_is_said_to_be_assumed(client, book):
    book.prefs.write_text(json.dumps({"currency": "EUR"}))
    body = _get(client)
    # Taxed as the rest of the app taxes it, and the page says so.
    assert body["jurisdiction"] == "ES" and body["tax_status"] != "chosen"


def test_a_chosen_residence_is_not_flagged(client, book):
    body = _get(client)
    assert (body["jurisdiction"], body["tax_status"]) == ("ES", "chosen")


def test_a_non_eur_base_prices_moves_in_it_and_tax_in_the_jurisdictions(
    client, book, monkeypatch
):
    from stocks.data import fx

    monkeypatch.setattr(
        fx, "rate_on", lambda day, base, quote: 1.0 if base == quote else 0.9
    )
    monkeypatch.setattr(fx, "prefetch", lambda *a, **k: None)
    body = _get(client, base="USD")
    assert body["base"] == "USD"
    assert body["plan"]["tax_currency"] == "EUR"
    amd = next(r for r in body["held"] if r["ticker"] == "AMD")
    assert amd["delta"] == pytest.approx(-1_500.0)
    assert amd["tax"] is not None


def test_a_name_without_a_kind_is_judged_as_a_company(client, book, monkeypatch):
    monkeypatch.setattr(route, "_kind", lambda symbol: KINDS.get(symbol))
    verdicts = {r["ticker"]: r["verdict"] for r in _get(client)["held"]}
    assert verdicts["AMD"] == "sell" and verdicts["ADBE"] == "add"


def test_every_row_carries_its_currency_and_country(client, book):
    body = _get(client)
    rows = {r["ticker"]: r for r in body["held"] + body["candidates"]}
    assert (rows["AMD"]["country"], rows["AMD"]["currency"]) == ("United States", "USD")
    assert (rows["XEON.DE"]["country"], rows["XEON.DE"]["currency"]) == (None, "EUR")
    assert rows["BKNG"]["currency"] == "USD"
    # A name the profile memo has never seen says nothing, not a guess.
    assert (rows["SNAP"]["country"], rows["SNAP"]["currency"]) == (None, None)


def test_a_pence_quote_reads_as_pounds(client, book, monkeypatch):
    monkeypatch.setitem(
        PROFILES,
        "SNAP",
        {"country": "United Kingdom", "currency": "GBp", "quoteType": "EQUITY"},
    )
    snap = next(r for r in _get(client)["candidates"] if r["ticker"] == "SNAP")
    assert snap["currency"] == "GBP"


def _us_book(monkeypatch):
    monkeypatch.setitem(PROFILES, "ADBE", PROFILES["AMD"])
    table = pd.DataFrame(
        {
            "shares": [10.0, 10.0, 10.0],
            "cost": [3_000.0, 3_000.0, 3_000.0],
            "value": [3_000.0, 3_000.0, 4_000.0],
            "pnl": [0.0, 0.0, 1_000.0],
            "pnl_pct": [0.0, 0.0, 0.33],
        },
        index=pd.Index(["AMD", "ADBE", "BKNG"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)


def test_a_book_quoted_in_dollars_for_a_euro_reader_is_named(client, book, monkeypatch):
    _us_book(monkeypatch)
    notes = {n["key"]: n for n in _get(client)["notes"]}
    assert notes["currency_heavy"]["currency"] == "USD"
    assert notes["currency_heavy"]["weight"] == pytest.approx(1.0)
    # Three US companies, all of it: a one-country book too.
    assert notes["country_heavy"]["country"] == "United States"
    assert notes["country_heavy"]["count"] == 3


def test_an_indexed_book_says_the_companies_are_satellites(client, book, monkeypatch):
    monkeypatch.setitem(KINDS, "XEON.DE", "equity_fund")
    notes = {n["key"]: n for n in _get(client)["notes"]}
    assert notes["fund_core"]["weight"] == pytest.approx(0.82)
    assert notes["fund_core"]["count"] == 2
    assert "cash_heavy" not in notes


def test_one_event_names_the_read_without_a_ticker(client, book, monkeypatch):
    seen = []
    monkeypatch.setattr(
        route.obs, "event", lambda name, **fields: seen.append((name, fields))
    )
    _get(client)
    [(name, fields)] = [e for e in seen if e[0] == "api.review"]
    assert fields["jurisdiction"] == "ES" and fields["base"] == "EUR"
    assert fields["held"] == 3 and fields["verdicts"]["sell"] == 1
    assert fields["kinds"] == {"stock": 2, "money_market": 1}
    assert fields["notes"] == ["cash_heavy"]
    assert not any(t in repr(fields) for t in ("AMD", "ADBE", "XEON", "BKNG"))


def test_the_lines_the_copy_quotes_travel_with_the_answer(client, book):
    lines = _get(client)["lines"]
    # Two companies: too few for a concentration line; the rest at their
    # narrow-book values.
    assert lines == {
        "concentrated": None,
        "small": engine.SMALL,
        "add_to": engine.ADD_TO,
        "sector": engine.SECTOR_LINE,
    }


def test_what_the_sales_free_and_the_book_cannot_take_goes_to_the_outside_buys(
    client, book
):
    body = _get(client)
    bkng = next(r for r in body["candidates"] if r["ticker"] == "BKNG")
    # AMD's 1,500 pays ADBE's 200; BKNG opens at the add line, 5%.
    assert bkng["target_weight"] == pytest.approx(engine.ADD_TO)
    assert bkng["delta"] == pytest.approx(500.0)
    assert bkng["reasons"][0] == engine.R_REDEPLOY
    # A pass is never sized; what no buy takes is the plan's unplaced cash.
    snap = next(r for r in body["candidates"] if r["ticker"] == "SNAP")
    assert snap["delta"] is None and snap["target_weight"] is None
    assert body["plan"]["sells"] - body["plan"]["buys"] == pytest.approx(800.0)


def test_an_outside_buy_inside_the_repurchase_window_is_sized_and_dated(client, book):
    # BKNG sold at a loss a month ago: buying it back reopens that loss.
    ledger.add_many(
        [
            Transaction("2026-01-02", "BKNG", "buy", 1, 500.0, "EUR", 0.0),
            Transaction(f"{_days_ago(30)}", "BKNG", "sell", 1, 400.0, "EUR", 0.0),
        ],
        path=book.db,
    )
    bkng = next(r for r in _get(client)["candidates"] if r["ticker"] == "BKNG")
    assert bkng["delta"] == pytest.approx(500.0)
    assert bkng["buy_after"] is not None and bkng["buy_after"] > _days_ago(0)


def test_no_sale_means_no_outside_buy_is_sized(client, book, monkeypatch):
    monkeypatch.setitem(METRICS, "AMD", QUALITY)
    body = _get(client)
    assert all(r["delta"] is None for r in body["candidates"])


def test_the_offset_lines_follow_the_jurisdictions_currency(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(route.fx, "spot", lambda a, b: (11.0, "spot"))
    assert route._lines(SimpleNamespace(currency="SEK")) == (150.0 * 11, 25.0 * 11)
    assert route._lines(SimpleNamespace(currency="EUR")) == (150.0, 25.0)

    def down(a, b):
        raise OSError("offline")

    seen = []
    monkeypatch.setattr(route.fx, "spot", down)
    monkeypatch.setattr(route.obs, "event", lambda name, **f: seen.append(name))
    assert route._lines(SimpleNamespace(currency="SEK")) == (150.0, 25.0)
    assert seen == ["review.fx_missing"]


def test_an_open_loss_is_read_in_the_tax_currency_not_the_pages(monkeypatch):
    from types import SimpleNamespace

    # Bought for 1,000 dollars; 10 shares at 90 euros read as a loss on a
    # euro page, but at 1.2 dollars a euro the tax sees an 80-dollar gain.
    monkeypatch.setattr(route.fx, "spot", lambda a, b: (1.2, "spot"))
    held = SimpleNamespace(cost=1_000.0, quantity=10.0)
    book = SimpleNamespace(currency="USD", held=lambda ticker: held)
    assert route._unrealised(book, ("X", 10.0, 90.0, "EUR")) == pytest.approx(80.0)


def test_a_slow_book_answers_within_its_budget_and_says_what_is_pending(
    client, book, monkeypatch
):
    import threading
    import time

    release = threading.Event()

    def slow(symbol):
        if symbol == "BKNG":
            release.wait(5)
        return METRICS.get(symbol)

    monkeypatch.setattr(route, "_metrics", slow)
    monkeypatch.setattr(route, "GATHER_BUDGET_S", 0.3)
    started = time.perf_counter()
    try:
        data = _get(client)
    finally:
        release.set()
    assert time.perf_counter() - started < 3
    assert data["pending"] == 1
    bkng = next(r for r in data["candidates"] if r["ticker"] == "BKNG")
    assert bkng["verdict"] == "unrated"
    # The others were read whole.
    amd = next(r for r in data["held"] if r["ticker"] == "AMD")
    assert amd["quality"] is not None


def test_a_book_read_in_time_has_nothing_pending(client, book):
    assert _get(client)["pending"] == 0


@pytest.fixture
def warned(monkeypatch):
    """Every once-a-window warning and `data.inconsistency` line the read
    writes, as (event, fields)."""
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        route.obs,
        "warn_once",
        lambda name, key="", **fields: seen.append((name, fields)) or True,
    )
    monkeypatch.setattr(
        route.consistency,
        "report",
        lambda kind, **fields: seen.append((f"data.{kind}", fields)) or True,
    )
    return seen


def test_the_read_says_why_a_company_read_blank_by_exchange_not_by_name(
    client, book, monkeypatch, warned
):
    seen = []
    monkeypatch.setattr(
        route.obs, "event", lambda name, **fields: seen.append((name, fields))
    )
    _get(client, add="SAN.MC")
    [fields] = [f for name, f in seen if name == "api.review"]
    assert fields["unrated"] == {"no_metrics": 1}
    assert fields["unrated_venues"] == {"MC": 1}
    assert fields["added"] == 1 and fields["added_blank"] == 1
    assert fields["added_venues"] == {"MC": 1}
    assert fields["lenses"] == {"standard": 4}
    assert {"gather", "prices", "risk"} <= set(fields["phases"])
    assert fields["invariants"] == []
    assert "SAN" not in repr(fields)


def test_a_sound_plan_raises_no_invariant(client, book, warned):
    _get(client)
    assert not [f for name, f in warned if name == "review.invariant"]


def _row(verdict, *, held=True, weight=None, target=None, delta=None, tax=None):
    return route.ReviewRow(
        ticker="X",
        symbol="X",
        held=held,
        verdict=verdict,
        weight=weight,
        target_weight=target,
        delta=delta,
        tax=tax,
    )


def test_a_plan_that_cannot_be_right_is_named_by_kind(warned):
    held = [
        _row("trim", weight=0.6, target=0.3, delta=-300.0),
        _row("add", weight=0.3, target=0.5, delta=-10.0),
        _row("hold", weight=0.3),
    ]
    outside = [_row("buy", held=False, target=1.2, delta=50.0)]
    kinds = route._invariants(held, outside, replayed=True)
    assert set(kinds) == {
        "weights_off",
        "target_out_of_range",
        "delta_against_verdict",
        "sale_untaxed",
    }
    said = {f["kind"]: f for name, f in warned if name == "review.invariant"}
    assert said["delta_against_verdict"]["verdicts"] == {"add": 1}
    assert said["sale_untaxed"] == {"kind": "sale_untaxed", "count": 2, "replayed": True}


def test_a_book_mostly_sold_is_an_odd_read_with_its_shape(warned):
    held = [_row("sell") for _ in range(4)] + [_row("hold"), _row("core")]
    route._odd_read(held, route.Counter(), jurisdiction="UK", base="GBP")
    [(name, fields)] = warned
    assert name == "review.odd_read"
    assert fields["kind"] == "sells" and fields["companies"] == 6
    assert fields["jurisdiction"] == "UK"
    # Blanks a late pull explains are not a misread.
    warned.clear()
    route._odd_read(
        [_row("unrated") for _ in range(5)], route.Counter(pending=5), base="EUR"
    )
    assert warned == []


def test_a_name_priced_off_a_broken_cash_flow_is_logged_with_its_ratios(
    client, book, monkeypatch, warned
):
    monkeypatch.setitem(METRICS, "ADBE", {**QUALITY, "ev": -1e9})
    _get(client)
    [fields] = [f for name, f in warned if name == "data.metric_suspect"]
    assert fields["ticker"] == "ADBE" and fields["source"] == "review"
    assert fields["ev_not_positive"] is True


def test_a_bank_industry_no_lens_lists_is_named_by_industry(
    client, book, monkeypatch, warned
):
    monkeypatch.setitem(METRICS, "AMD", {**QUALITY, "industry": "Banks - Savings"})
    _get(client)
    assert ("review.industry_unmapped", {"industry": "Banks - Savings"}) in warned


@pytest.mark.parametrize(
    ("symbol", "venue"),
    [("SAN.MC", "MC"), ("VOD.L", "L"), ("AAPL", "none"), ("BRK.B", "B")],
)
def test_a_failure_is_placed_by_exchange(symbol, venue):
    assert route._venue(symbol) == venue


# ------------------------------------------------------------- the import wall


def test_an_account_with_no_import_is_walled_not_judged(client, book, monkeypatch):
    """The starter watchlist is not something to judge: the page is the reason
    to import, so it answers `locked` and judges nothing."""
    from stocks.portfolio import demo

    paths = book
    ledger.delete_many([t.id for t in ledger.all_transactions(paths.db)], paths.db)
    demo.seed(paths.db)  # a demo book is for looking, not an import
    gathered = []
    monkeypatch.setattr(route, "_gather", lambda *a: gathered.append(a) or ({}, set()))
    body = _get(client)
    assert body["locked"] is True
    assert body["held"] == [] and body["candidates"] == []
    assert gathered == []


def test_an_account_with_an_import_is_not_walled(client, book):
    assert _get(client)["locked"] is False


def test_the_preview_judges_the_shared_demo_book(client, book, monkeypatch):
    monkeypatch.setattr(accounts, "guest_paths", lambda: book)
    response = client.get("/v1/review/preview", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["locked"] is False
    assert {r["ticker"] for r in body["held"]} == {"AMD", "XEON.DE", "ADBE"}
