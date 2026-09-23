"""KPIs, statements, valuation history, moat, insiders, funds and comps.

The arithmetic behind each of these has its own suite in `tests/` already, and
repeating it here would test `analysis/` twice. What is tested is the promise
the HTTP layer adds: that provenance travels with the number, that "we could not
compute this" is null rather than zero, and that "nobody covers this name" is
told apart from "nothing happened".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks.api import loaders
from stocks.api.app import app as fastapi_app

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@dataclass
class FakeRaw:
    """What `fetch_fundamentals` hands back, reduced to what these routes read."""

    ticker: str = "AAPL"
    info: dict | None = None
    income: pd.DataFrame | None = None
    income_q: pd.DataFrame | None = None

    def __post_init__(self):
        if self.info is None:
            self.info = {"currency": "USD", "longName": "Apple Inc"}


# ------------------------------------------------------------------- the KPI grid


def test_every_kpi_carries_where_it_came_from(client, monkeypatch):
    """`level` is the difference between a filed number and a forecast. A grid
    that prints them alike is how consensus wears a filing's authority."""
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr(
        "stocks.api.routes.ticker.compute_metrics",
        lambda raw: {"ticker": "AAPL", "currency": "USD", "pe_ttm": 28.4},
    )
    kpis = client.get("/v1/ticker/AAPL/metrics", headers=AUTH).json()["kpis"]
    assert kpis, "the grid is the whole KPI_SOURCES order, not just what was found"
    assert all(k["level"] in {"fact", "consensus", "derived"} for k in kpis)
    by_key = {k["key"]: k for k in kpis}
    assert by_key["pe_ttm"]["value"] == 28.4
    assert by_key["pe_ttm"]["formatted"] == "28.4x", "units baked in, once"


def test_a_missing_kpi_is_null_and_says_so_in_words(client, monkeypatch):
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr(
        "stocks.api.routes.ticker.compute_metrics",
        lambda raw: {"ticker": "AAPL", "pe_ttm": None},
    )
    body = client.get("/v1/ticker/AAPL/metrics", headers=AUTH).json()
    by_key = {k["key"]: k for k in body["kpis"]}
    assert by_key["pe_ttm"]["value"] is None
    assert by_key["pe_ttm"]["formatted"] == "n/a"


def test_a_kpi_with_no_band_gets_no_verdict(client, monkeypatch):
    """Absent, not "fair" — a neutral default reads as a judgement nobody made."""
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr(
        "stocks.api.routes.ticker.compute_metrics",
        lambda raw: {"ticker": "AAPL", "market_cap": 3.1e12},
    )
    body = client.get("/v1/ticker/AAPL/metrics", headers=AUTH).json()
    by_key = {k["key"]: k for k in body["kpis"]}
    assert by_key["market_cap"]["verdict"] is None


def test_a_label_kpi_survives_as_a_string(client, monkeypatch):
    """Not every KPI is a number; coercing a sector to a float would drop it."""
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr(
        "stocks.api.routes.ticker.compute_metrics",
        lambda raw: {"ticker": "AAPL", "currency": "USD", "quote_type": "EQUITY"},
    )
    body = client.get("/v1/ticker/AAPL/metrics", headers=AUTH).json()
    assert body["currency"] == "USD" and body["quote_type"] == "EQUITY"


# ------------------------------------------------------------------- statements


def test_reported_years_and_the_consensus_path_stay_separate(client, monkeypatch):
    """Two fields, not one series with a flag: a caller cannot draw a forecast
    as a reported figure by forgetting to look at the flag."""
    annual = pd.DataFrame(
        {"Revenue": [383.0, 391.0], "Net Income": [97.0, 93.0], "EPS": [6.13, 6.08]},
        index=[2023, 2024],
    )
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr("stocks.api.routes.ticker.annual_financials", lambda raw: annual)
    monkeypatch.setattr(
        "stocks.api.routes.ticker.quarterly_eps", lambda raw: pd.DataFrame()
    )
    monkeypatch.setattr(
        loaders, "estimates",
        lambda t: SimpleNamespace(earnings_estimate=pd.DataFrame()),
    )
    monkeypatch.setattr("stocks.api.routes.ticker.estimate_currency", lambda df: "USD")
    monkeypatch.setattr(
        "stocks.api.routes.ticker.projection",
        lambda raw, last_fy, **kw: pd.DataFrame(
            {"Revenue": [410.0], "EPS": [7.1]}, index=["2025E"]
        ),
    )
    body = client.get("/v1/ticker/AAPL/financials", headers=AUTH).json()
    assert [r["year"] for r in body["annual"]] == ["2023", "2024"]
    assert [r["period"] for r in body["projection"]] == ["2025E"]
    assert body["estimate_currency"] == "USD"


def test_the_consensus_band_and_the_extrapolation_flag_both_travel(
    client, monkeypatch
):
    """The page shades a min-max band around the consensus EPS line and draws
    extrapolated periods differently from polled ones. Both need the columns
    `data.estimates.projection` actually emits — `RevenueLow`, not
    `Revenue Low`, which is how they silently arrived as null.
    """
    annual = pd.DataFrame({"Revenue": [391.0], "EPS": [6.08]}, index=[2024])
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr("stocks.api.routes.ticker.annual_financials", lambda raw: annual)
    monkeypatch.setattr(
        "stocks.api.routes.ticker.quarterly_eps", lambda raw: pd.DataFrame()
    )
    monkeypatch.setattr(
        loaders, "estimates",
        lambda t: SimpleNamespace(earnings_estimate=pd.DataFrame()),
    )
    monkeypatch.setattr("stocks.api.routes.ticker.estimate_currency", lambda df: "USD")
    monkeypatch.setattr(
        "stocks.api.routes.ticker.projection",
        lambda raw, last_fy, **kw: pd.DataFrame(
            {
                "Revenue": [410.0, 440.0],
                "RevenueLow": [400.0, float("nan")],
                "RevenueHigh": [420.0, float("nan")],
                "RevenueExt": [False, True],
                "EPS": [7.1, 7.9],
                "EPSLow": [6.8, float("nan")],
                "EPSHigh": [7.4, float("nan")],
                "EPSExt": [False, True],
            },
            index=["2025E", "2026E"],
        ),
    )
    polled, carried = client.get(
        "/v1/ticker/AAPL/financials", headers=AUTH
    ).json()["projection"]
    assert (polled["eps_low"], polled["eps_high"]) == (6.8, 7.4)
    assert polled["revenue_low"] == 400.0
    assert polled["eps_extrapolated"] is False
    # Past the last published estimate: a growth rate carried forward, and no
    # range — nobody polled it, so there is nothing to shade.
    assert carried["eps_extrapolated"] is True
    assert (carried["eps_low"], carried["revenue_high"]) == (None, None)


def test_a_company_with_no_statements_still_answers(client, monkeypatch):
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr(
        "stocks.api.routes.ticker.annual_financials", lambda raw: pd.DataFrame()
    )
    monkeypatch.setattr(
        "stocks.api.routes.ticker.quarterly_eps", lambda raw: pd.DataFrame()
    )
    body = client.get("/v1/ticker/NOSUCH/financials", headers=AUTH).json()
    assert body["annual"] == [] and body["projection"] == []


# ------------------------------------------------------------ valuation history


def test_the_multiple_says_which_feed_reconstructed_it(client, monkeypatch):
    """A P/E with no provenance is a number somebody will act on."""
    pe = pd.Series([25.0, 28.0], index=pd.to_datetime(["2024-01-01", "2024-06-30"]))
    stats = pd.DataFrame(
        {"mean": [26.0], "median": [25.5], "low": [20.0], "high": [31.0],
         "percentile": [72.0], "premium": [0.077]},
        index=["5y"],
    )
    monkeypatch.setattr(
        loaders, "valuation",
        lambda t: {"source": "SEC EDGAR", "pe": pe, "stats": stats, "current": 28.0},
    )
    body = client.get("/v1/ticker/AAPL/valuation", headers=AUTH).json()
    assert body["source"] == "SEC EDGAR"
    assert body["dates"] == ["2024-01-01", "2024-06-30"]


def test_the_windows_offered_are_the_ones_the_page_can_select(client, monkeypatch):
    """The selector's options are a domain table, not a page's constant: both
    front ends draw it, and two different option sets are two different
    questions wearing the same label. Each window carries its own span so a
    client can trim the series without a second copy of the table."""
    from stocks.analysis.pe_history import DISPLAY_WINDOWS

    days = pd.date_range("2016-01-01", periods=2600, freq="D")
    pe = pd.Series(range(len(days)), index=days, dtype=float)
    monkeypatch.setattr(
        loaders, "valuation",
        lambda t: {"source": "SEC EDGAR", "pe": pe, "stats": None, "current": 28.0},
    )
    windows = client.get("/v1/ticker/AAPL/valuation", headers=AUTH).json()["windows"]
    assert [w["window"] for w in windows] == list(DISPLAY_WINDOWS)
    assert {w["window"]: w["days"] for w in windows} == DISPLAY_WINDOWS
    # A 1y mean over a rising series has to sit above the 5y one, or the
    # windows are all being computed over the same slice.
    by_window = {w["window"]: w["mean"] for w in windows}
    assert by_window["1y"] > by_window["5y"]


def test_a_name_no_feed_covers_reads_as_no_source(client, monkeypatch):
    """Null source, not a silently empty chart that looks like a flat P/E."""
    monkeypatch.setattr(
        loaders, "valuation",
        lambda t: {"source": None, "pe": None, "stats": None, "current": None},
    )
    body = client.get("/v1/ticker/XYZ.PA/valuation", headers=AUTH).json()
    assert body["source"] is None and body["pe"] == [] and body["windows"] == []


# ------------------------------------------------------------------------- moat


@dataclass
class FakePillar:
    key: str
    label: str
    score: float | None
    detail: str


@dataclass
class FakeMoat:
    ticker: str
    pillars: tuple
    score: float | None
    rating: str | None
    years: int


def test_an_unscored_pillar_is_null_not_zero(client, monkeypatch):
    """Zero is a verdict — "no advantage". Null is the absence of one."""
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr(
        "stocks.api.routes.ticker.moat_score",
        lambda raw: FakeMoat(
            "AAPL",
            (
                FakePillar("roic", "ROIC", 88.0, "10y mean 42%"),
                FakePillar("dilution", "Dilution", None, "no share count"),
            ),
            83.5,
            "wide",
            10,
        ),
    )
    body = client.get("/v1/ticker/AAPL/moat", headers=AUTH).json()
    by_key = {p["key"]: p for p in body["pillars"]}
    assert by_key["roic"]["score"] == 88.0
    assert by_key["dilution"]["score"] is None
    assert body["rating"] == "wide" and body["years"] == 10


def test_too_few_pillars_means_no_composite(client, monkeypatch):
    """A rating assembled from two pillars is a guess with a number on it."""
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr(
        "stocks.api.routes.ticker.moat_score",
        lambda raw: FakeMoat("X", (FakePillar("roic", "ROIC", None, ""),), None, None, 2),
    )
    body = client.get("/v1/ticker/X/moat", headers=AUTH).json()
    assert body["score"] is None and body["rating"] is None


# --------------------------------------------------------------------- insiders


@dataclass
class FakeTx:
    date: date | None
    insider: str
    relationship: str
    code: str
    acquired: bool
    shares: float
    price: float | None
    currency: str | None = "USD"

    @property
    def is_open_market(self) -> bool:
        """P/S only — what `summarize` counts. Grants, exercises and tax
        withholding are excluded so the net is discretionary, not grant noise."""
        return self.code in ("P", "S")

    @property
    def value(self) -> float | None:
        """Notional in `currency`; None without a price. A property here for
        the same reason it is one on `InsiderTx` — a stub that carries fewer
        of them than the real row tests a route nobody ships."""
        return None if self.price is None else self.shares * self.price


def test_a_disposal_comes_back_signed(client, monkeypatch):
    """So a table can sort and sum without re-deriving direction from a flag."""
    txs = [
        FakeTx(date(2024, 5, 1), "tim cook", "CEO", "S", False, 500.0, 190.0),
        FakeTx(date(2024, 4, 1), "luca maestri", "CFO", "P", True, 100.0, 170.0),
    ]
    monkeypatch.setattr(loaders, "insiders", lambda t: txs)
    body = client.get("/v1/ticker/AAPL/insiders", headers=AUTH).json()
    shares = {t["insider"]: t["shares"] for t in body["trades"]}
    assert shares["Tim Cook"] == -500.0
    assert shares["Luca Maestri"] == 100.0
    assert body["source"] == "SEC"


def test_the_net_and_the_cluster_signal_actually_travel(client, monkeypatch):
    """`asdict` on the domain's summary drops its properties in silence, which
    shipped a net of 0.00 for every company on earth — and a payload that
    defaults a field to zero cannot be told from one that computed it."""
    # Dated from today: the summary is a trailing window, and a fixture pinned
    # to a calendar date silently ages out of it.
    recent = date.today() - timedelta(days=7)
    txs = [
        FakeTx(recent, "a director", "Director", "P", True, 100.0, 10.0),
        FakeTx(recent, "b director", "Director", "P", True, 100.0, 10.0),
        FakeTx(recent, "c officer", "CFO", "S", False, 50.0, 10.0),
    ]
    monkeypatch.setattr(loaders, "insiders", lambda t: txs)
    summary = client.get("/v1/ticker/AAPL/insiders", headers=AUTH).json()["summary"]
    assert summary["net_value"] == pytest.approx(1500.0), "2000 bought, 500 sold"
    # Two distinct buyers outweighing the sells: the signal the page calls out.
    assert summary["cluster_buy"] is True


def test_a_row_carries_its_own_notional_and_whether_it_was_a_real_trade(
    client, monkeypatch
):
    """A grant is not a purchase. Both ride the row so a chart of conviction
    does not have to re-derive either from the raw Form 4 code."""
    txs = [
        FakeTx(date(2024, 5, 1), "tim cook", "CEO", "S", False, 500.0, 190.0),
        FakeTx(date(2024, 4, 1), "tim cook", "CEO", "A", True, 1000.0, None),
    ]
    monkeypatch.setattr(loaders, "insiders", lambda t: txs)
    rows = client.get("/v1/ticker/AAPL/insiders", headers=AUTH).json()["trades"]
    sale, grant = rows[0], rows[1]
    assert sale["value"] == pytest.approx(-95_000.0), "signed, like the shares"
    assert sale["is_open_market"] is True
    assert grant["value"] is None and grant["is_open_market"] is False


def test_a_name_nobody_files_for_says_so(client, monkeypatch):
    """Null source rather than an empty list — "no coverage" and "no trades"
    are different claims and the page words them differently."""
    monkeypatch.setattr(loaders, "insiders", lambda t: [])
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw(info={"longName": ""}))
    body = client.get("/v1/ticker/XYZ/insiders", headers=AUTH).json()
    assert body["source"] is None and body["summary"] is None and body["trades"] == []


def test_a_german_issuer_falls_through_to_bafin(client, monkeypatch):
    """The same disclosure, published by a different regulator in EUR."""
    monkeypatch.setattr(loaders, "insiders", lambda t: [])
    monkeypatch.setattr(
        loaders, "fundamentals", lambda t: FakeRaw(info={"longName": "Nemetschek SE"})
    )
    monkeypatch.setattr(
        "stocks.api.routes.ticker.bafin_transactions",
        lambda ticker, issuer: [
            FakeTx(date(2024, 3, 1), "a holder", "Director", "P", True, 10.0, 90.0, "EUR")
        ],
    )
    body = client.get("/v1/ticker/NEM.DE/insiders", headers=AUTH).json()
    assert body["source"] == "BaFin"
    assert body["trades"][0]["currency"] == "EUR"


# ------------------------------------------------------------------------ funds


def test_a_company_is_not_a_fund_and_that_is_an_answer(client, monkeypatch):
    monkeypatch.setattr(loaders, "fund_profile", lambda t: None)
    body = client.get("/v1/ticker/AAPL/fund", headers=AUTH).json()
    assert body["is_fund"] is False and body["holdings"] == []


def test_a_funds_basket_comes_back_as_fractions(client, monkeypatch):
    """0.075 is 7.5%. Percent-scaling on the wire is how a weight gets
    multiplied by a hundred twice."""
    from stocks.data.funds import FundHolding, FundProfile

    monkeypatch.setattr(
        loaders, "fund_profile",
        lambda t: FundProfile(
            ticker="SPY", name="SPDR S&P 500", quote_type="ETF", currency="USD",
            expense_ratio=0.000945,
            holdings=(FundHolding("AAPL", "Apple Inc", 0.0704),),
            sectors=(("Technology", 0.4),),
        ),
    )
    body = client.get("/v1/ticker/SPY/fund", headers=AUTH).json()
    assert body["is_fund"] is True
    assert body["expense_ratio"] == 0.000945
    assert body["holdings"][0]["weight"] == 0.0704
    assert body["sectors"] == [["Technology", 0.4]]


# ------------------------------------------------------------------ comparables


def test_the_subject_keeps_its_place_at_the_front(client, monkeypatch):
    """Order is the caller's — the subject leads, the peers follow."""
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw(ticker=t))
    monkeypatch.setattr(
        "stocks.api.routes.comparables.compute_metrics",
        lambda raw: {"ticker": raw.ticker, "pe_ttm": 20.0},
    )
    body = client.get(
        "/v1/comparables", params={"tickers": "aapl,msft,aapl"}, headers=AUTH
    ).json()
    assert body["tickers"] == ["AAPL", "MSFT"], "deduped in place, order kept"
    assert set(body["rows"]) == {"AAPL", "MSFT"}
    assert len(body["rows"]["AAPL"]) == len(body["labels"])


def test_a_two_horse_race_has_no_podium(client, monkeypatch):
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw(ticker=t))
    monkeypatch.setattr(
        "stocks.api.routes.comparables.compute_metrics",
        lambda raw: {"ticker": raw.ticker, "pe_ttm": 20.0},
    )
    body = client.get("/v1/comparables", params={"tickers": "A,B"}, headers=AUTH).json()
    assert body["medals"] == {}


def test_the_fan_out_is_bounded(client):
    """Each name is a fundamentals pull, and Yahoo throttles cloud IPs hard."""
    many = ",".join(f"T{i}" for i in range(20))
    response = client.get("/v1/comparables", params={"tickers": many}, headers=AUTH)
    assert response.status_code == 422


def test_an_empty_list_is_refused(client):
    response = client.get("/v1/comparables", params={"tickers": " , "}, headers=AUTH)
    assert response.status_code == 422


# ------------------------------------------------- when the upstream says no


def test_a_throttled_upstream_is_a_503_with_a_reason_not_a_500(
    client, monkeypatch
):
    """Yahoo throttling this deployment is weather, not a fault in this service.

    It has to be distinguishable too: a client that gets 500 has no idea
    whether retrying is pointless or the whole answer.
    """
    from yfinance.exceptions import YFRateLimitError

    def throttled(_ticker):
        raise YFRateLimitError()

    monkeypatch.setattr(loaders, "fundamentals", throttled)
    response = client.get("/v1/ticker/AAPL/financials", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["reason"] == "rate_limited"
    assert response.headers["retry-after"] == "60"


def test_an_unreachable_upstream_says_offline_instead(client, monkeypatch):
    from urllib.error import URLError

    def dropped(_ticker):
        raise URLError("no route to host")

    monkeypatch.setattr(loaders, "fundamentals", dropped)
    response = client.get("/v1/ticker/AAPL/metrics", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["reason"] == "offline"


def test_a_verdict_ships_the_tone_its_band_carries(client, monkeypatch):
    """The labels are a growing set — "net cash", "buybacks", "heavy dilution".
    A client colouring by label shows every band it has not heard of as
    neutral, which is the one reading a verdict must never have."""
    monkeypatch.setattr(loaders, "fundamentals", lambda t: FakeRaw())
    monkeypatch.setattr(
        "stocks.api.routes.ticker.compute_metrics",
        lambda raw: {"ticker": "AAPL", "pe_ttm": 9.0, "net_debt_ebitda": -0.4},
    )
    body = client.get("/v1/ticker/AAPL/metrics", headers=AUTH).json()
    kpis = {k["key"]: k for k in body["kpis"]}
    assert (kpis["pe_ttm"]["verdict"], kpis["pe_ttm"]["verdict_tone"]) == (
        "cheap",
        "green",
    )
    assert kpis["net_debt_ebitda"]["verdict"] == "net cash"
    assert kpis["net_debt_ebitda"]["verdict_tone"] == "green"
