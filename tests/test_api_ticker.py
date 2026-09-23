"""The per-ticker routes: bars, quote, calendar, and this account's holding.

The shaping of a price frame — how much history a range downloads, where it is
trimmed, which indicator columns come with it — is `analysis.history`'s job and
is tested with the rest of the analysis. What is tested here is what the HTTP
layer promises on top: that an absent value crosses the wire as null and not as
zero, that a range nobody defined is refused rather than guessed at, and that a
holding reads as "not held" instead of as a position worth nothing.

Nothing here touches the network — every loader is replaced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.portfolio.custody import Custody
from stocks.portfolio.ledger import Transaction

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    return paths


def frame() -> pd.DataFrame:
    """Three daily bars, with the slower averages still in their warm-up."""
    return pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [11.0, 12.0, 13.0],
            "Low": [9.0, 10.0, 11.0],
            "Close": [10.5, 11.5, 12.5],
            "Volume": [100.0, 200.0, 300.0],
            "SMA20": [float("nan"), 11.0, 12.0],
            "SMA50": [float("nan")] * 3,
            "SMA200": [float("nan")] * 3,
            "RSI14": [float("nan"), 55.0, 60.0],
            "Dividends": [0.0, 0.25, 0.0],
        },
        index=pd.to_datetime(["2024-03-01", "2024-03-04", "2024-03-05"]),
    )


# ------------------------------------------------------------------------ bars


def test_bars_carry_the_series_a_chart_needs(client, monkeypatch):
    monkeypatch.setattr(loaders, "price_bars", lambda t, label: frame())
    body = client.get("/v1/ticker/aapl/bars", params={"range": "1y"}, headers=AUTH).json()
    assert body["ticker"] == "AAPL" and body["range"] == "1y"
    assert body["interval"] == "1d"
    assert body["dates"][0].startswith("2024-03-01")
    assert body["series"]["Close"] == [10.5, 11.5, 12.5]


def test_an_indicators_warmup_is_null_not_zero(client, monkeypatch):
    """SMA50 has no value for its first 49 bars. Plotted as 0 it draws a cliff
    through the middle of the chart."""
    monkeypatch.setattr(loaders, "price_bars", lambda t, label: frame())
    body = client.get("/v1/ticker/AAPL/bars", headers=AUTH).json()
    assert body["series"]["SMA50"] == [None, None, None]
    assert body["series"]["SMA200"] == [None, None, None]
    assert body["series"]["SMA20"] == [None, 11.0, 12.0]


def test_dividends_ride_with_the_bars(client, monkeypatch):
    """They come out of the history frame, so there is no second round trip and
    no way for the two to disagree."""
    monkeypatch.setattr(loaders, "price_bars", lambda t, label: frame())
    body = client.get("/v1/ticker/AAPL/bars", headers=AUTH).json()
    assert body["dividends"] == [0.0, 0.25, 0.0]


def test_the_axis_breaks_come_with_the_bars(client, monkeypatch):
    """Without them a weekend renders as a flat gap in the candles."""
    monkeypatch.setattr(loaders, "price_bars", lambda t, label: frame())
    body = client.get("/v1/ticker/AAPL/bars", headers=AUTH).json()
    assert {"bounds": ["sat", "mon"]} in body["rangebreaks"]


def test_timestamps_carry_no_zone(client, monkeypatch):
    """Exchange-local wall time: stamping them UTC slides every session by its
    own offset, and the hour-based breaks stop lining up with the axis."""
    monkeypatch.setattr(loaders, "price_bars", lambda t, label: frame())
    body = client.get("/v1/ticker/AAPL/bars", headers=AUTH).json()
    assert not any(s.endswith("Z") or "+" in s for s in body["dates"])


def test_a_range_nobody_defined_is_refused(client, monkeypatch):
    monkeypatch.setattr(loaders, "price_bars", lambda t, label: frame())
    response = client.get("/v1/ticker/AAPL/bars", params={"range": "7y"}, headers=AUTH)
    assert response.status_code == 422


def test_a_ticker_with_no_history_still_answers(client, monkeypatch):
    monkeypatch.setattr(loaders, "price_bars", lambda t, label: pd.DataFrame())
    body = client.get("/v1/ticker/NOSUCH/bars", headers=AUTH).json()
    assert body["dates"] == [] and body["series"] == {}


# ----------------------------------------------------------------------- quote


def test_the_quote_says_whether_the_market_is_open(client, monkeypatch):
    """The page overrides the last bar only off-session; inside it, the bars
    already track the live price."""
    monkeypatch.setattr(
        "stocks.api.routes.ticker.session_quote",
        lambda t: {"price": 190.0, "pct": 0.012, "session": "post",
                   "as_of": "2024-03-05"},
    )
    monkeypatch.setattr("stocks.api.routes.ticker.market_live", lambda t: False)
    body = client.get("/v1/ticker/AAPL/quote", headers=AUTH).json()
    assert body["market_open"] is False
    assert body["session"] == "post" and body["pct"] == 0.012


def test_an_unquotable_ticker_reads_null_not_zero(client, monkeypatch):
    monkeypatch.setattr("stocks.api.routes.ticker.session_quote", lambda t: None)
    monkeypatch.setattr("stocks.api.routes.ticker.market_live", lambda t: True)
    body = client.get("/v1/ticker/NOSUCH/quote", headers=AUTH).json()
    assert body["price"] is None and body["pct"] is None


# ---------------------------------------------------------------------- events


@dataclass
class FakeResult:
    date: date
    eps_estimate: float | None = None
    reported_eps: float | None = None
    surprise_pct: float | None = None

    @property
    def beat(self) -> bool | None:
        return None if self.surprise_pct is None else self.surprise_pct >= 0


def test_reported_and_upcoming_dates_are_told_apart(client, monkeypatch):
    dates = [date(2024, 2, 1), date(2024, 5, 1)]
    results = [FakeResult(date(2024, 2, 1), 1.0, 1.2, 20.0)]
    monkeypatch.setattr(loaders, "earnings", lambda t: (dates, results))
    monkeypatch.setattr("stocks.api.routes.ticker.is_crypto", lambda t: False)
    monkeypatch.setattr("stocks.api.routes.ticker.is_fund", lambda t: False)

    rows = client.get("/v1/ticker/AAPL/events", headers=AUTH).json()["earnings"]
    assert [r["date"] for r in rows] == ["2024-02-01", "2024-05-01"]
    assert rows[0]["reported_eps"] == 1.2 and rows[0]["beat"] is True
    assert rows[1]["reported_eps"] is None, "a date that has not reported yet"


def test_a_fund_is_not_asked_for_a_calendar(client, monkeypatch):
    """It pays distributions and never reports, so the round trip only ever
    comes back with "no earnings dates found"."""
    called = []
    monkeypatch.setattr(loaders, "earnings", lambda t: called.append(t) or ([], []))
    monkeypatch.setattr("stocks.api.routes.ticker.is_crypto", lambda t: False)
    monkeypatch.setattr("stocks.api.routes.ticker.is_fund", lambda t: True)

    assert client.get("/v1/ticker/SPY/events", headers=AUTH).json()["earnings"] == []
    assert called == []


def test_a_coin_is_not_asked_either(client, monkeypatch):
    called = []
    monkeypatch.setattr(loaders, "earnings", lambda t: called.append(t) or ([], []))
    monkeypatch.setattr("stocks.api.routes.ticker.is_crypto", lambda t: True)

    assert client.get("/v1/ticker/BTC-EUR/events", headers=AUTH).json()["earnings"] == []
    assert called == []


# -------------------------------------------------------------------- position


@dataclass
class FakePosition:
    ticker: str
    quantity: float
    cost_native: float
    currency: str

    @property
    def avg_cost_native(self) -> float:
        return self.cost_native / self.quantity


def test_a_ticker_this_account_does_not_hold(client, account, monkeypatch):
    """"Not held" is a different answer from "held, worth nothing"."""
    monkeypatch.setattr(loaders, "native_positions", lambda db, m: {})
    body = client.get(
        "/v1/ticker/AAPL/position", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body == {
        "ticker": "AAPL", "held": False, "shares": None, "currency": None,
        "cost_native": None, "avg_cost_native": None, "base": None,
        "value": None, "weight": None, "trades": [], "brokers": {},
        "custody": [],
    }


FILLS = (
    Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "USD", 1.0),
    Transaction("2024-03-01", "AAPL", "sell", 4, 130.0, "USD", 1.0),
    Transaction("2024-02-01", "MSFT", "buy", 5, 200.0, "USD", 1.0),
)


@pytest.fixture
def ledger(monkeypatch):
    monkeypatch.setattr(loaders, "ledger_state", lambda *a, **k: (list(FILLS), [], []))


def test_a_closed_position_still_reports_where_it_was_entered(
    client, account, ledger, monkeypatch
):
    """The fills are the only part of a chart that was ever the reader's. A
    sold-out name keeps its markers."""
    monkeypatch.setattr(loaders, "native_positions", lambda db, m: {})
    body = client.get(
        "/v1/ticker/AAPL/position", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["held"] is False
    assert [(t["action"], t["date"]) for t in body["trades"]] == [
        ("buy", "2024-01-02"),
        ("sell", "2024-03-01"),
    ]


def test_fills_are_scaled_to_todays_shares(client, account, ledger, monkeypatch):
    """Ledger prices are as-traded, Yahoo's bars are split-adjusted. Raw, a
    pre-split buy plots twenty times above the candles it belongs on."""
    monkeypatch.setattr(loaders, "native_positions", lambda db, m: {})
    monkeypatch.setattr(
        "stocks.portfolio.corporate.split_factors",
        lambda txs: {"AAPL": [("2024-02-01", 4.0)]},
    )
    body = client.get(
        "/v1/ticker/AAPL/position", params={"account": EMAIL}, headers=AUTH
    ).json()
    buy = body["trades"][0]
    # Bought at 100 for 10 before a 4:1 split; today that is 25 for 40.
    assert (buy["price"], buy["quantity"]) == (25.0, 40.0)
    # The split is not after the sell, so that row is untouched.
    assert body["trades"][1]["price"] == 130.0


def test_a_held_position_reports_native_cost_and_the_broker_split(
    client, account, monkeypatch
):
    monkeypatch.setattr(
        loaders, "native_positions",
        lambda db, m: {"AAPL": FakePosition("AAPL", 10.0, 1000.0, "USD")},
    )
    monkeypatch.setattr(
        loaders, "custody",
        lambda db, m: {"AAPL": {
            "Revolut": Custody("AAPL", "Revolut", 6.0, 600.0),
            "IBKR": Custody("AAPL", "IBKR", 4.0, 400.0),
        }},
    )
    monkeypatch.setattr(
        loaders, "positions_table",
        lambda db, m, base: pd.DataFrame(
            {"shares": [10.0], "ccy": ["USD"], "cost": [900.0], "value": [1200.0]},
            index=pd.Index(["AAPL"], name="ticker"),
        ),
    )
    body = client.get(
        "/v1/ticker/AAPL/position", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["held"] is True
    assert (body["shares"], body["currency"]) == (10.0, "USD")
    assert body["avg_cost_native"] == 100.0, "in USD, not converted to the base"
    assert body["value"] == 1200.0 and body["weight"] == pytest.approx(1.0)
    assert body["brokers"] == {"Revolut": 6.0, "IBKR": 4.0}


def test_custody_marks_are_ready_to_draw_and_largest_first(
    client, account, monkeypatch
):
    """The header prints a brand mark per custodian, so the split travels
    resolved: a front end re-deriving key -> brand keeps its own copy of a
    table that changes when a broker is renamed."""
    monkeypatch.setattr(
        loaders, "native_positions",
        lambda db, m: {"AAPL": FakePosition("AAPL", 10.0, 1000.0, "USD")},
    )
    monkeypatch.setattr(
        loaders, "custody",
        lambda db, m: {"AAPL": {
            "manual": Custody("AAPL", "manual", 2.0, 200.0),
            "revolut": Custody("AAPL", "revolut", 8.0, 800.0),
        }},
    )
    monkeypatch.setattr(loaders, "positions_table", lambda db, m, base: pd.DataFrame())
    monkeypatch.setattr(loaders, "brand_logo", lambda key: f"/logo/{key}.png")
    marks = client.get(
        "/v1/ticker/AAPL/position", params={"account": EMAIL}, headers=AUTH
    ).json()["custody"]

    assert [m["broker"] for m in marks] == ["revolut", "manual"], "largest first"
    assert marks[0]["share"] == pytest.approx(0.8)
    assert marks[0]["name"] == "Revolut" and marks[0]["shares"] == 8.0
    # A hand-entered row is not a brand: its name is a translated string, and a
    # language-neutral payload has no business picking one.
    assert marks[1]["name"] == ""


@pytest.fixture
def no_fetch(monkeypatch):
    """Nothing in this file may reach Yahoo.

    Both metrics tests stub `compute_metrics`, which is the second half of the
    route — the first half still asks `loaders.fundamentals` for the raw
    payload, and that fetches. They passed only while some earlier test left
    that memo warm; the day the memo was cold the suite hung for fifteen
    minutes on a curl timeout, which is how this fixture came to exist.
    """
    monkeypatch.setattr(loaders, "fundamentals", lambda ticker: object())


def test_the_grid_is_the_domain_s_nine_tiles_and_names_its_strings(
    client, monkeypatch, no_fetch
):
    """The page draws a handful of KPIs, not all 23. Which handful is a domain
    decision both front ends read, and the labels travel as i18n key NAMES —
    translating here would give this API a language."""
    from stocks.analysis.fundamentals import FUNDAMENTAL_TILES

    monkeypatch.setattr(
        "stocks.api.routes.ticker.compute_metrics",
        lambda raw: {"currency": "USD", "pe_ttm": 30.0},
    )
    body = client.get("/v1/ticker/AAPL/metrics", headers=AUTH).json()
    assert [tile["key"] for tile in body["grid"]] == [t.key for t in FUNDAMENTAL_TILES]
    assert body["grid"][0]["label_key"].startswith("ticker.kpi_")
    assert len(body["kpis"]) > len(body["grid"]), "kpis is the whole table"
    # Nothing translated, and nothing converted until somebody asks.
    assert body["market_cap_base"] is None and body["base"] is None


def test_a_dollar_market_cap_is_restated_only_when_a_base_is_asked_for(
    client, monkeypatch, no_fetch
):
    """The one figure on that grid that belongs to the reader rather than the
    company. It is a query parameter and not an account dependency: every other
    number here is the company's, and a token-holding script names nobody."""
    monkeypatch.setattr(
        "stocks.api.routes.ticker.compute_metrics",
        lambda raw: {"currency": "USD", "market_cap": 2_000_000_000.0},
    )
    monkeypatch.setattr("stocks.data.fx.spot", lambda a, b: (0.9, "2026-09-18"))

    plain = client.get("/v1/ticker/AAPL/metrics", headers=AUTH).json()
    assert plain["market_cap_base"] is None, "no base asked, no conversion"

    body = client.get(
        "/v1/ticker/AAPL/metrics", params={"base": "eur"}, headers=AUTH
    ).json()
    assert body["market_cap_base"] == pytest.approx(1_800_000_000.0)
    assert (body["fx_rate"], body["fx_as_of"], body["base"]) == (0.9, "2026-09-18", "EUR")
    assert body["market_cap_base_formatted"], "formatted server-side, printed as-is"

    # A company already quoting in the reader's money is not converted twice.
    same = client.get(
        "/v1/ticker/AAPL/metrics", params={"base": "usd"}, headers=AUTH
    ).json()
    assert same["market_cap_base"] is None

    assert client.get(
        "/v1/ticker/AAPL/metrics", params={"base": "XYZ"}, headers=AUTH
    ).status_code == 422


def test_the_alert_editor_is_offered_the_domain_s_own_field_table(client):
    """`/alert-types` is what stops a client inventing a rule shape. A type
    added to the domain has to reach both editors without either being
    edited, and a field list copied into one of them does not."""
    from stocks.config import ALERT_FORMS

    forms = client.get("/v1/alert-types", headers=AUTH).json()["forms"]
    assert [f["type"] for f in forms] == [f.type for f in ALERT_FORMS]
    by_type = {f["type"]: f for f in forms}
    assert by_type["above"]["field"] == "price"
    assert by_type["drawdown"] == {
        "type": "drawdown", "field": "pct", "default": 5.0, "window": None,
    }
    # The ones that ask for no number at all still carry their lookback.
    assert by_type["sma_cross"]["field"] is None
    assert by_type["sma_cross"]["window"] == 50


def test_an_unpriced_holding_keeps_its_shares_and_loses_only_its_value(
    client, account, monkeypatch
):
    """A throttled price pass must not turn a real position into a zero."""
    monkeypatch.setattr(
        loaders, "native_positions",
        lambda db, m: {"AAPL": FakePosition("AAPL", 10.0, 1000.0, "USD")},
    )
    monkeypatch.setattr(loaders, "custody", lambda db, m: {})
    monkeypatch.setattr(
        loaders, "positions_table",
        lambda db, m, base: pd.DataFrame(
            {"shares": [10.0], "ccy": ["USD"], "cost": [900.0],
             "value": [float("nan")]},
            index=pd.Index(["AAPL"], name="ticker"),
        ),
    )
    body = client.get(
        "/v1/ticker/AAPL/position", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["shares"] == 10.0 and body["cost_native"] == 1000.0
    assert body["value"] is None and body["weight"] is None


# ------------------------------------------------------------ comps suggestions


def test_peers_are_suggestions_with_names_where_the_sec_map_has_them(
    client, monkeypatch
):
    monkeypatch.setattr(loaders, "related", lambda t: ("MSFT", "NOKIA.HE"))
    monkeypatch.setattr(
        loaders, "sec_title", lambda t: "Microsoft Corp" if t == "MSFT" else None
    )
    body = client.get("/v1/ticker/AAPL/peers", headers=AUTH).json()
    assert body["related"] == [
        {"ticker": "MSFT", "name": "Microsoft Corp"},
        # Not a US filer: a bare symbol rather than a round trip per suggestion.
        {"ticker": "NOKIA.HE", "name": ""},
    ]


def test_a_coin_is_never_suggested_as_a_comparable(client, monkeypatch):
    """The comps table ranks on KPIs a coin has none of."""
    monkeypatch.setattr(loaders, "related", lambda t: ("BTC-EUR", "MSFT"))
    monkeypatch.setattr(loaders, "sec_title", lambda t: None)
    body = client.get("/v1/ticker/AAPL/peers", headers=AUTH).json()
    assert [p["ticker"] for p in body["related"]] == ["MSFT"]


def test_no_suggestions_is_an_empty_list_not_a_failure(client, monkeypatch):
    monkeypatch.setattr(loaders, "related", lambda t: ())
    assert client.get("/v1/ticker/ZZQQ/peers", headers=AUTH).json()["related"] == []


def test_the_momentum_read_travels_with_the_bars(client, monkeypatch):
    """The bands are the domain's. Shipping only the number would let each
    front end pick its own threshold for "overbought"."""
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    frame = pd.DataFrame(
        {"Close": [1.0, 2.0, 3.0], "RSI14": [float("nan"), 50.0, 81.0]}, index=index
    )
    monkeypatch.setattr(loaders, "price_bars", lambda t, label: frame)
    body = client.get("/v1/ticker/AAPL/bars?range=1m", headers=AUTH).json()
    assert (body["rsi_verdict"], body["rsi_tone"]) == ("overbought", "red")


def test_an_indicator_still_warming_up_has_no_verdict(client, monkeypatch):
    index = pd.date_range("2024-01-01", periods=2, freq="D")
    frame = pd.DataFrame(
        {"Close": [1.0, 2.0], "RSI14": [float("nan"), float("nan")]}, index=index
    )
    monkeypatch.setattr(loaders, "price_bars", lambda t, label: frame)
    body = client.get("/v1/ticker/AAPL/bars?range=1m", headers=AUTH).json()
    assert body["rsi_verdict"] is None and body["rsi_tone"] is None


# ------------------------------------------------------ identity and reference


def test_the_profile_prints_the_resolved_symbol_not_the_stored_label(
    client, account, monkeypatch
):
    """A holding the ledger keeps as an ISIN has to read as its ticker in the
    header. The ledger and every link keep the original string."""
    monkeypatch.setattr(loaders, "display_symbol", lambda t: "NOW")
    monkeypatch.setattr(loaders, "company_name", lambda t, w: "ServiceNow, Inc.")
    monkeypatch.setattr(loaders, "logo", lambda t: "/app/static/logos/NOW.png")
    body = client.get(
        "/v1/ticker/US81762P1021/profile", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["ticker"] == "US81762P1021"
    assert body["symbol"] == "NOW"
    assert body["name"] == "ServiceNow, Inc."


def test_a_name_no_source_knows_comes_back_empty_never_invented(
    client, account, monkeypatch
):
    monkeypatch.setattr(loaders, "display_symbol", lambda t: t)
    monkeypatch.setattr(loaders, "company_name", lambda t, w: None)
    monkeypatch.setattr(loaders, "logo", lambda t: None)
    body = client.get(
        "/v1/ticker/ZZQQ/profile", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert (body["name"], body["logo"]) == ("", None)


def test_the_profile_is_keyed_to_the_asking_account(client, account, monkeypatch):
    """A name someone set by hand on their own list must not render for
    another account, so the watchlist path is an argument, not a lookup."""
    asked = []
    monkeypatch.setattr(loaders, "display_symbol", lambda t: t)
    monkeypatch.setattr(loaders, "logo", lambda t: None)
    monkeypatch.setattr(
        loaders, "company_name", lambda t, w: asked.append(w) or "Apple"
    )
    client.get("/v1/ticker/AAPL/profile", params={"account": EMAIL}, headers=AUTH)
    assert asked == [str(account.watchlist)]


def test_a_coin_gets_asset_stats_instead_of_fundamentals(client, monkeypatch):
    monkeypatch.setattr(
        loaders,
        "crypto_info",
        lambda t: {
            "marketCap": 1.2e12,
            "volume24Hr": 3.4e10,
            "circulatingSupply": 19_700_000,
            "fiftyTwoWeekHigh": 108000.0,
            "fiftyTwoWeekLow": 49000.0,
        },
    )
    body = client.get("/v1/ticker/BTC-EUR/crypto", headers=AUTH).json()
    assert body["quote"] == "EUR"
    assert body["market_cap"] == 1.2e12
    assert body["circulating_supply"] == 19_700_000


def test_asking_a_share_for_coin_stats_is_empty_rather_than_an_error(client):
    """A client that asks is not making a mistake it should be punished for."""
    body = client.get("/v1/ticker/AAPL/crypto", headers=AUTH).json()
    assert body["market_cap"] is None and body["ticker"] == "AAPL"


def test_every_kpi_says_where_it_loads_from_and_where_to_verify_it(client):
    """The verification hierarchy is a claim this project makes about its own
    numbers; a client repeating it from memory is how it goes stale."""
    kpis = client.get("/v1/kpi-sources", headers=AUTH).json()["kpis"]
    assert len(kpis) > 10
    assert all(row["loader"] and row["verify"] for row in kpis)
    assert {row["level"] for row in kpis} <= {"fact", "consensus", "derived"}


def test_fills_are_found_under_the_label_the_position_is_built_on(
    client, account, monkeypatch
):
    """A book fed by two brokers spells one holding two ways — DEGIRO books
    under the ISIN, IBKR under the symbol. Positions already unify them, so a
    chart keyed on the raw ledger shows no entry for a position you hold."""
    monkeypatch.setattr(loaders, "native_positions", lambda db, m: {})
    monkeypatch.setattr(
        loaders,
        "ledger_state",
        lambda *a, **k: (
            [
                Transaction(
                    "2024-01-02", "US00724F1012", "buy", 5, 500.0, "USD", 1.0,
                    note="ISIN US00724F1012",
                ),
                Transaction(
                    "2024-06-01", "ADBE", "buy", 3, 450.0, "USD", 1.0,
                    note="ISIN US00724F1012",
                ),
            ],
            [],
            [],
        ),
    )
    body = client.get(
        "/v1/ticker/ADBE/position", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert [t["date"] for t in body["trades"]] == ["2024-01-02", "2024-06-01"]
