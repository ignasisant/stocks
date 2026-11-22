"""The sector's funds: the catalog's derived facts, the reader's returns, the
book's look-through, and the `/funds` endpoint.

What is pinned here is what a reader would misread if it broke: a share class
counted as two companies (concentration halved), a podium name listed at
another exchange printed as "not among its ten largest", a part-of-the-sector
fund passed off as the sector, a fund listed after the book started given the
book's first day, and a series nobody could convert shown in the wrong money.

No network: profiles are written inline, closes are synthetic.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import loaders
from stocks.analysis import sector_funds as catalog
from stocks.analysis.sectors import SectorScan
from stocks.api.app import app as fastapi_app
from stocks.views import sector_funds as views
from tests.patching import patch_loaders

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TECH = "Technology"


def profile(holdings, sectors, **extra) -> dict:
    return {
        "name": extra.get("name", "Some Fund"),
        "quote_type": "ETF",
        "currency": extra.get("currency", "USD"),
        "family": "iShares",
        "expense_ratio": extra.get("expense_ratio", 0.0015),
        "holdings": holdings,
        "sectors": sectors,
        "fetched": "2026-11-21",
    }


# ------------------------------------------------------------ derived facts


def test_two_share_classes_are_one_company():
    """GOOGL + GOOG is one holding to a reader judging concentration."""
    lines = catalog.merged_holdings(
        [
            ["GOOGL", "Alphabet Inc Class A", 0.04],
            ["MSFT", "Microsoft Corp", 0.05],
            ["GOOG", "Alphabet Inc Class C", 0.03],
        ]
    )
    assert lines[0][0] == "GOOGL" and lines[0][2] == pytest.approx(0.07)
    assert [s for s, _, _ in lines] == ["GOOGL", "MSFT"]


def test_a_line_without_a_symbol_is_dropped():
    lines = catalog.merged_holdings(
        [[None, "Cash", 0.02], ["", "Swap", 0.01], ["MSFT", "Microsoft", 0.05]]
    )
    assert [s for s, _, _ in lines] == ["MSFT"]


def test_the_merged_line_takes_the_cohort_spelling():
    lines = catalog.merged_holdings(
        [["GOOGL", "Alphabet Inc Class A", 0.04], ["GOOG", "Alphabet Inc Class C", 0.03]],
        prefer={"GOOG"},
    )
    assert lines == [("GOOG", "Alphabet Inc Class C", pytest.approx(0.07))]


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("Banco Santander, S.A.", "Banco Santander SA"),
        ("Nestlé S.A.", "Nestle SA"),
        ("ASML Holding N.V.", "ASML Holding NV"),
        ("Enel S.p.A.", "Enel SpA"),
        ("L'Oréal S.A.", "LOreal SA"),
        ("Deutsche Bank Aktiengesellschaft", "Deutsche Bank AG"),
        ("BNP Paribas Act. Cat.A", "BNP Paribas SA"),
    ],
)
def test_two_spellings_of_one_company_share_a_key(one, other):
    """The cohort names a company as its filings do, the fund as its data
    vendor does; dots, accents and legal forms must not tell them apart."""
    assert catalog._company(one) == catalog._company(other)


def test_different_companies_keep_different_keys():
    assert catalog._company("Banco Santander SA") != catalog._company("Banco Sabadell SA")
    assert catalog._company("Alphabet Inc Class A") == catalog._company(
        "Alphabet Inc Class C"
    )
    # A class keyword is a word of its own: "CLP" and "Cato" are names.
    assert catalog._company("CLP Holdings Ltd") == "clp"
    assert catalog._company("Cato Corp") == "cato"
    assert catalog._company("Sera Prognostics Inc") == "sera prognostics"


def test_a_holding_listed_elsewhere_counts_as_the_cohort_name():
    """MSCI World Materials holds BHP at Sydney; the cohort ranks it in London."""
    lines = catalog._listed_as(
        [("BHP.AX", "BHP Group Ltd", 0.06), ("RIO", "Rio Tinto", 0.03)],
        cohort={"BHP.L"},
        names={"BHP.L": "BHP Group Limited"},
    )
    assert lines[0][0] == "BHP.L"
    assert lines[1][0] == "RIO"


def tech_stored(**over) -> dict:
    """Every curated tech vehicle backed by one pure profile."""
    pure = profile(
        [
            ["NVDA", "NVIDIA Corp", 0.2],
            ["AAPL", "Apple Inc", 0.15],
            ["MSFT", "Microsoft", 0.1],
        ],
        [["Technology", 0.95], ["Communication Services", 0.05]],
    )
    stored = {v.symbol: pure for v in catalog.vehicles(TECH)}
    stored.update(over)
    return stored


def test_a_fund_mostly_outside_the_sector_is_left_out():
    first = catalog.vehicles(TECH)[0].symbol
    stored = tech_stored(
        **{first: profile([["X", "X", 0.1]], [["Technology", 0.4], ["Industrials", 0.6]])}
    )
    facts = catalog.sector_facts(TECH, stored)
    assert first not in {f.symbol for f in facts}
    assert len(facts) == len(catalog.vehicles(TECH)) - 1


def test_a_vehicle_without_a_stored_profile_is_left_out():
    first = catalog.vehicles(TECH)[0].symbol
    stored = tech_stored()
    del stored[first]
    assert first not in {f.symbol for f in catalog.sector_facts(TECH, stored)}


def test_podium_outside_the_ten_lines_is_none_not_zero():
    facts = catalog.sector_facts(
        TECH, tech_stored(), cohort=("NVDA", "AAPL", "AVGO"), podium=("NVDA", "AVGO")
    )[0]
    assert dict(facts.podium) == {"NVDA": pytest.approx(0.2), "AVGO": None}
    assert facts.cohort_weight == pytest.approx(0.35)  # MSFT is not in the cohort
    assert facts.top10 == pytest.approx(0.45)
    assert facts.top3 == pytest.approx(0.45)


def test_every_disclosed_line_says_what_it_is_to_the_page():
    """The card draws all the disclosed lines, not the three largest: each
    one is a podium name, another ranked company, or neither."""
    facts = catalog.sector_facts(
        TECH, tech_stored(), cohort=("NVDA", "AAPL"), podium=("NVDA",)
    )[0]
    assert [(line.symbol, line.role) for line in facts.lines] == [
        ("NVDA", "podium"),
        ("AAPL", "cohort"),
        ("MSFT", "other"),
    ]
    assert sum(line.weight for line in facts.lines) == pytest.approx(facts.top10)


def test_a_banks_only_fund_says_so():
    """EXV1 is 100 % Financials by Yahoo's split but holds banks alone: the
    purity is honest, the card must still say it is a part of the sector."""
    banks = [v for v in catalog.vehicles("Financial Services") if v.only]
    assert banks and all(v.only == "banks" for v in banks)
    stored = {
        v.symbol: profile(
            [["SAN.MC", "Banco Santander", 0.1]], [["Financial Services", 1.0]]
        )
        for v in catalog.vehicles("Financial Services")
    }
    facts = {f.symbol: f for f in catalog.sector_facts("Financial Services", stored)}
    assert facts[banks[0].symbol].only == "banks"
    assert all(f.only is None for s, f in facts.items() if s != banks[0].symbol)


def test_every_sector_has_vehicles_and_no_symbol_twice_in_one():
    from stocks.analysis.sectors import SECTORS

    for sector in SECTORS:
        symbols = [v.symbol for v in catalog.vehicles(sector)]
        assert symbols, sector
        assert len(symbols) == len(set(symbols)), sector


def test_refresh_keeps_last_nights_profile_when_yahoo_says_nothing(tmp_path, monkeypatch):
    from stocks.data import funds as data_funds

    monkeypatch.setattr(catalog, "FUNDS_FILE", tmp_path / "sector_funds.json")
    monkeypatch.setattr(catalog.storage, "enabled", lambda: False)
    keep, fresh = catalog.symbols()[:2]
    catalog.save({keep: profile([["A", "A", 0.1]], [["Technology", 1.0]], name="old")})

    class P:
        name, quote_type, currency, family, expense_ratio = (
            "new",
            "ETF",
            "USD",
            "x",
            0.001,
        )
        holdings = (type("H", (), {"symbol": "B", "name": "B", "weight": 0.2})(),)
        sectors = (("Technology", 1.0),)

    def fetch(symbol):
        if symbol == fresh:
            return P()
        if symbol == keep:
            raise TimeoutError
        return None

    monkeypatch.setattr(data_funds, "fetch_profile", fetch)
    status = catalog.refresh(pause_s=0)
    stored = catalog.load(restore=False)
    assert status[keep].endswith("kept") and stored[keep]["name"] == "old"
    assert status[fresh] == "ok" and stored[fresh]["name"] == "new"


# ------------------------------------------------------------ the returns


def closes(start: str, end: str, daily: float = 0.0004) -> pd.Series:
    days = pd.bdate_range(start, end)
    return pd.Series([100 * (1 + daily) ** i for i in range(len(days))], index=days)


@pytest.fixture
def market(monkeypatch):
    """Tech's vehicles: the first listed late, the second only in a currency
    nobody can convert, the rest since long before the book."""
    today = pd.Timestamp.today().normalize()
    symbols = [v.symbol for v in catalog.vehicles(TECH)]
    late, foreign, *rest = symbols
    series = {s: closes("2019-01-01", today) for s in rest}
    series[late] = closes("2025-06-02", today)
    series[foreign] = closes("2019-01-01", today)
    stored = {s: {"currency": "EUR"} for s in symbols}
    stored[foreign] = {"currency": "XXX"}
    patch_loaders(monkeypatch, "sector_funds", lambda: stored)
    monkeypatch.setattr(views, "_closes", lambda symbols, period: series)
    monkeypatch.setattr(
        views, "_book_start", lambda paths, base: pd.Timestamp("2024-03-04")
    )
    monkeypatch.setattr(
        "stocks.analysis.portfolio.fx_frame",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no rate")),
    )
    return late, foreign, rest


def test_returns_start_on_the_books_first_day(market):
    _late, _foreign, rest = market
    out = views.returns(TECH, None, "EUR", own_book=True)
    assert out["since"] == "2024-03-04"
    row = next(r for r in out["returns"] if r["ticker"] == rest[0])
    assert row["since"] is not None and row["since"] > row["y1"] > 0
    assert row["opens"] is None


def test_a_fund_listed_after_the_book_says_where_it_opens(market):
    late, _foreign, _rest = market
    out = views.returns(TECH, None, "EUR", own_book=True)
    row = next(r for r in out["returns"] if r["ticker"] == late)
    assert row["opens"] == "2025-06-02"
    assert row["since"] is not None


def test_a_series_nobody_can_convert_has_no_number(market):
    """Half exchange rate is worse than no figure."""
    _late, foreign, _rest = market
    out = views.returns(TECH, None, "EUR", own_book=True)
    row = next(r for r in out["returns"] if r["ticker"] == foreign)
    assert row == {"ticker": foreign, "y1": None, "since": None, "opens": None}


def test_a_guest_gets_the_year_and_no_first_day(market):
    _late, _foreign, rest = market
    out = views.returns(TECH, None, "EUR", own_book=False)
    assert out["since"] is None
    row = next(r for r in out["returns"] if r["ticker"] == rest[0])
    assert row["since"] is None and row["y1"] is not None


def test_only_spanish_residents_switch_funds_untaxed(monkeypatch):
    monkeypatch.setattr(views.tax_prefs, "load", lambda path: {})
    paths = type("P", (), {"prefs": "x"})()
    monkeypatch.setattr(views.tax_prefs, "resolve", lambda prefs: ("ES", None))
    assert views.transfer_free(paths) is True
    monkeypatch.setattr(views.tax_prefs, "resolve", lambda prefs: ("DE", None))
    assert views.transfer_free(paths) is False


# ----------------------------------------------------------- the look-through


def test_look_through_names_the_fund_and_never_exceeds_the_bucket(monkeypatch):
    from stocks.loaders import book

    table = pd.DataFrame({"value": {"AAPL": 600.0, "IWDA.AS": 400.0}})
    monkeypatch.setattr(book, "positions_table", lambda db, mtime, base: table)
    meta = {
        "AAPL": {"sector": "Technology"},
        "IWDA.AS": {"sector_weights": {"Technology": 0.25, "Financial Services": 0.75}},
    }
    via = book.allocation_via_funds("db", 0.0, "EUR", meta, "sector")
    weights = book.allocation_weights("db", 0.0, "EUR", meta, "sector", {})
    assert via["Technology"] == {"IWDA.AS": pytest.approx(0.1)}
    assert via["Financial Services"] == {"IWDA.AS": pytest.approx(0.3)}
    assert "AAPL" not in via["Technology"]
    assert weights["Technology"] == pytest.approx(0.7)


# --------------------------------------------------------------- endpoint


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    loaders.sector_scans.cache_clear()
    scan = SectorScan(
        sector=TECH,
        as_of="2026-11-21",
        tickers=("NVDA", "AAPL", "AVGO"),
        metrics=(),
        scores={},
        podium=("NVDA", "AVGO"),
    )
    patch_loaders(monkeypatch, "sector_scans", lambda: {TECH: scan})
    patch_loaders(monkeypatch, "sector_funds", tech_stored)
    patch_loaders(monkeypatch, "listing_names", lambda tickers: {})
    return TestClient(fastapi_app)


def test_the_endpoint_lists_the_vehicles_with_the_podium_as_a_floor(client):
    payload = client.get(f"/v1/sectors/{TECH}/funds", headers=AUTH).json()
    assert [f["ticker"] for f in payload["funds"]] == [
        v.symbol for v in catalog.vehicles(TECH)
    ]
    first = payload["funds"][0]
    assert first["purity"] == 0.95
    assert first["expense_ratio"] == 0.0015
    assert {p["ticker"]: p["weight"] for p in first["podium"]} == {
        "NVDA": 0.2,
        "AVGO": None,
    }


def test_an_unknown_sector_is_a_404(client):
    assert client.get("/v1/sectors/Cryptozoology/funds", headers=AUTH).status_code == 404


def test_no_stored_profiles_is_an_empty_card_not_an_error(client, monkeypatch):
    patch_loaders(monkeypatch, "sector_funds", lambda: {})
    payload = client.get(f"/v1/sectors/{TECH}/funds", headers=AUTH).json()
    assert payload == {"sector": TECH, "funds": []}


def test_an_empty_read_is_asked_again_after_a_while(monkeypatch):
    """A deploy that boots before the first publish must not serve an empty
    fund card for the cache's hour once the file is there."""
    from stocks.loaders import market

    reads = iter([{}, {}, {"XDWT.DE": {"name": "x"}}])
    monkeypatch.setattr(catalog, "load", lambda **_: next(reads))
    market._stored_funds.cache_clear()
    market._empty_since.clear()
    clock = [1000.0]
    monkeypatch.setattr(market.time, "monotonic", lambda: clock[0])
    assert market.sector_funds() == {}
    clock[0] += 60
    assert market.sector_funds() == {}  # within the retry window: the memo
    clock[0] += market._EMPTY_RETRY_S
    assert market.sector_funds() == {}  # retried, still missing
    clock[0] += market._EMPTY_RETRY_S
    assert market.sector_funds() == {"XDWT.DE": {"name": "x"}}
    market._stored_funds.cache_clear()
    market._empty_since.clear()
