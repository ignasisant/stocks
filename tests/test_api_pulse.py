"""The market regime over HTTP, and what it does to one book.

How the composite is built — which eight inputs, how they are aligned when they
land on different calendars — is `analysis.sentiment`'s job and is tested with
it. What is tested here is what this pair of endpoints decides: that a missing
input is named rather than averaged away, that the regime band travels as a key
and not as prose, that a figure nobody could measure is null rather than zero,
and that the headline beta is never handed back as if it were comparable with
the rolling one.

Nothing here touches the network: every loader is replaced.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.analysis import sentiment as sm
from stocks.analysis.sentiment import Component
from stocks.analysis.sentiment import Pulse as PulseData
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.portfolio import ledger
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


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test in this file may reach Yahoo or FRED.

    `/pulse` reads the bulk close series directly now (breadth and the
    stock/bond correlation are read off the same download the composite is
    built from), so a test that stubs `market_pulse` alone leaves a live
    request behind it. The tests that want their own closes override this by
    setting the loader again — a later `monkeypatch.setattr` on the same
    attribute wins.
    """
    monkeypatch.setattr(loaders, "pulse_closes", dict)
    monkeypatch.setattr(loaders, "pulse_rates", dict)


@pytest.fixture(autouse=True)
def _cold_caches():
    memos = (
        loaders.market_pulse,
        loaders.pulse_closes,
        loaders.pulse_rates,
        loaders.benchmark_sectors,
        loaders.basket_report,
        loaders.ledger_state,
    )
    for fn in memos:
        fn.cache_clear()
    yield
    for fn in memos:
        fn.cache_clear()


def days(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-01", periods=n)


def built() -> PulseData:
    """A composite sitting in "appetite", with one input that never built."""
    index = days(200)
    history = pd.Series(np.linspace(45.0, 68.0, len(index)), index=index)
    return PulseData(
        score=68.0,
        history=history,
        components=(
            Component(key="momentum", score=80.0, raw=0.12, then=61.0),
            Component(key="breadth", score=55.0, raw=0.58, then=float("nan")),
        ),
        missing=("credit",),
        as_of=index[-1],
    )


@pytest.fixture
def pulse(monkeypatch):
    monkeypatch.setattr(loaders, "market_pulse", lambda: built())


def test_the_band_travels_as_a_key_not_as_prose(client, pulse):
    """The label is localized downstream; shipping English here would make the
    API a second translation catalog."""
    payload = client.get("/v1/pulse", headers=AUTH).json()
    assert payload["regime"] == "appetite"
    assert payload["score"] == pytest.approx(68.0)


def test_an_input_that_never_built_is_named_not_averaged_away(client, pulse):
    payload = client.get("/v1/pulse", headers=AUTH).json()
    assert payload["missing"] == ["credit"]
    keys = [c["key"] for c in payload["components"]]
    assert keys == ["momentum", "breadth"]


def test_a_component_with_no_history_reads_null_rather_than_zero(client, pulse):
    payload = client.get("/v1/pulse", headers=AUTH).json()
    breadth = next(c for c in payload["components"] if c["key"] == "breadth")
    assert breadth["then"] is None  # the series does not reach back a month
    momentum = next(c for c in payload["components"] if c["key"] == "momentum")
    assert momentum["then"] == pytest.approx(61.0)


def test_the_quoted_row_is_named_because_it_is_not_always_today(client, pulse):
    payload = client.get("/v1/pulse", headers=AUTH).json()
    assert payload["as_of"] == str(days(200)[-1].date())


def test_the_history_is_trimmed_to_what_a_sparkline_draws(client, pulse):
    """Two years of daily points is mostly a flat line at the right edge."""
    payload = client.get("/v1/pulse", headers=AUTH).json()
    assert len(payload["history"]) == 90
    assert payload["history"][-1]["score"] == pytest.approx(68.0)


def test_a_composite_nobody_could_build_is_null_and_unknown(client, monkeypatch):
    monkeypatch.setattr(
        loaders,
        "market_pulse",
        lambda: PulseData(score=float("nan"), missing=("momentum", "breadth")),
    )
    payload = client.get("/v1/pulse", headers=AUTH).json()
    assert payload["score"] is None
    assert payload["regime"] == "unknown"
    assert payload["run"] == 0


def test_the_regime_is_open_to_a_guest_and_still_shut_about_an_account(
    client, monkeypatch
):
    """Inverted when guest mode landed. The regime is a reading of the market,
    identical for everybody looking at it, and it is the half of Sentiment the
    Streamlit app has always shown an anonymous visitor.

    `/v1/pulse/book` — the same numbers projected onto a holder's positions — is
    open too, because a guest has a book: the shared demo one. That one does
    take an `?account=`, which is where the second half of the claim lives:
    being readable by a guest is not permission to name somebody. `/v1/pulse`
    itself takes no account, so there is nothing to refuse it about."""
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("stocks.api.security.configured_token", lambda: "")
    assert client.get("/v1/pulse").status_code == 200
    refused = client.get("/v1/pulse/book", params={"account": "someone@example.com"})
    assert refused.status_code == 403


# ------------------------------------------------------------------- the book


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    ledger.add_many(
        [Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0)],
        path=paths.db,
    )
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    return paths


class _Report:
    """Enough of a PortfolioReport for this route; the real one needs a fetch."""

    def __init__(self, returns: pd.DataFrame, allocations: dict[str, pd.Series]):
        self.returns = returns
        self.weights = {"AAPL": 0.6, "MSFT": 0.4}
        self._allocations = allocations

    def allocation(self, key: str) -> pd.Series:
        return self._allocations.get(key, pd.Series(dtype=float))


@pytest.fixture
def basket(monkeypatch):
    index = days(400)
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(
        {
            "AAPL": rng.normal(0.001, 0.02, len(index)),
            "MSFT": rng.normal(0.001, 0.015, len(index)),
        },
        index=index,
    )
    report = _Report(
        returns,
        {
            "currency": pd.Series({"USD": 0.7, "EUR": 0.3}),
            "sector": pd.Series({"Technology": 0.8, "Energy": 0.2}),
        },
    )
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: report
    )
    # A price path for the index, the long bond and the euro-dollar pair.
    index_prices = pd.Series(
        np.cumprod(1 + rng.normal(0.0008, 0.011, len(index))) * 4000, index=index
    )
    monkeypatch.setattr(
        loaders,
        "pulse_closes",
        lambda: {
            "^GSPC": index_prices,
            "TLT": pd.Series(
                np.cumprod(1 + rng.normal(0.0, 0.008, len(index))) * 95, index=index
            ),
            "EURUSD=X": pd.Series(
                np.linspace(1.10, 1.05, len(index)), index=index
            ),
        },
    )
    monkeypatch.setattr(
        loaders, "benchmark_sectors", lambda: {"Technology": 0.3, "Utilities": 0.1}
    )
    return report


def test_the_headline_beta_is_kept_apart_from_the_rolling_one(
    client, account, basket
):
    """They are different windows: subtracting one from the other is not drift,
    which is exactly what a single `beta`/`beta_then` pair would invite."""
    payload = client.get(
        "/v1/pulse/book", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["beta"] is not None
    assert payload["beta_rolling"] is not None
    assert "beta_then" not in payload


def test_a_book_reads_its_own_stance_with_a_dead_band(client, account, basket):
    payload = client.get(
        "/v1/pulse/book", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["stance"] in {"amplify", "track", "cushion"}


def test_the_dollar_share_comes_off_the_book_and_not_a_guess(
    client, account, basket
):
    payload = client.get(
        "/v1/pulse/book", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["usd_share"] == pytest.approx(0.7)
    assert payload["currency_weights"]["EUR"] == pytest.approx(0.3)
    # The euro-dollar pair fell over the window, so the dollar gained on it and
    # a dollar-heavy book carried a tailwind, not a drag.
    assert payload["fx_drag"] is not None


def test_a_sector_the_book_does_not_hold_is_a_real_underweight(
    client, account, basket
):
    """Dropping it would hide the biggest active positions a book has."""
    payload = client.get(
        "/v1/pulse/book", params={"account": EMAIL}, headers=AUTH
    ).json()
    tilt = payload["sector_tilt"]
    assert tilt["Technology"] == pytest.approx(0.5)  # 0.8 held vs 0.3 benchmark
    assert tilt["Utilities"] == pytest.approx(-0.1)  # held none of it
    assert tilt["Energy"] == pytest.approx(0.2)  # benchmark holds none of it


def test_an_empty_book_gets_nulls_and_not_a_beta_of_zero(
    client, account, monkeypatch
):
    """Zero would read as a basket the market cannot move."""
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: None
    )
    payload = client.get(
        "/v1/pulse/book", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["beta"] is None
    assert payload["usd_share"] is None
    assert payload["sector_tilt"] == {}


def test_a_dead_price_feed_leaves_the_exposure_unmeasured(
    client, account, basket, monkeypatch
):
    """No index series is "nobody could measure this", not "beta 0"."""
    monkeypatch.setattr(loaders, "pulse_closes", dict)
    payload = client.get(
        "/v1/pulse/book", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["beta"] is None
    assert payload["bond_correlation"] is None
    # The book's own shape needs no feed, so it still answers.
    assert payload["usd_share"] == pytest.approx(0.7)


# ------------------------------------------------------------- the detail blocks


@pytest.fixture
def sources(monkeypatch):
    """Prices, FRED series and an inflation frame, all local."""
    index = days(300)
    rng = np.random.default_rng(3)

    def walk(start: float) -> pd.Series:
        return pd.Series(
            np.cumprod(1 + rng.normal(0.0005, 0.01, len(index))) * start, index=index
        )

    closes = {t: walk(100.0) for t in ("^GSPC", "SPY", "XLK", "XLE", "GC=F")}
    closes["^VIX"] = walk(18.0)
    monkeypatch.setattr(loaders, "pulse_closes", lambda: closes)
    monkeypatch.setattr(
        loaders,
        "pulse_rate_rows",
        lambda: {
            "DGS10": pd.Series(np.linspace(4.0, 4.33, len(index)), index=index),
            "DFEDTARU": pd.Series([5.5] * len(index), index=index),
        },
    )
    # The real shape: ONE ROW PER AREA, not a column per area of a daily
    # series. Writing this fixture the other way around is what hid a bug that
    # made the whole block unrenderable — the route iterated columns and tried
    # to take a float of the string "EA".
    monkeypatch.setattr(
        loaders,
        "inflation",
        lambda: pd.DataFrame(
            [
                {
                    "area": "EA",
                    "period": "2026-08",
                    "headline": 2.1,
                    "core": 2.4,
                    "prior": 2.3,
                    "six_months": 3.0,
                    "momentum": -0.9,
                    "path": [3.0, 2.8, 2.6, 2.4, 2.3, 2.1],
                },
                {
                    "area": "US",
                    "period": "2026-07",
                    "headline": 2.9,
                    "core": 3.1,
                    "prior": 2.7,
                    "six_months": 2.5,
                    "momentum": 0.4,
                    "path": [2.5, 2.6, 2.7, 2.8, 2.7, 2.9],
                },
            ]
        ),
    )
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: None
    )
    return closes


def blocks_of(payload) -> dict:
    return {b["block"]: b for b in payload["blocks"]}


def test_every_block_comes_back_by_default(client, account, sources):
    payload = client.get(
        "/v1/pulse/tables", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert {b["block"] for b in payload["blocks"]} == {
        "factors",
        "indices",
        "gauges",
        "rates",
        "inflation",
        "rotation",
        "cross",
    }


def test_a_client_can_ask_for_one_tab(client, account, sources):
    payload = client.get(
        "/v1/pulse/tables",
        params={"account": EMAIL, "blocks": "rates"},
        headers=AUTH,
    ).json()
    assert [b["block"] for b in payload["blocks"]] == ["rates"]


def test_a_block_nobody_ships_is_refused(client, account, sources):
    response = client.get(
        "/v1/pulse/tables",
        params={"account": EMAIL, "blocks": "astrology"},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_a_rate_moves_in_basis_points_not_percent(client, account, sources):
    """"The 10-year rose 7.4%" is how a reader misreads 33 basis points."""
    rates = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "rates"},
            headers=AUTH,
        ).json()
    )["rates"]
    assert rates["unit"] == "basis_points"
    row = next(r for r in rates["rows"] if r["key"] == "DGS10")
    assert row["changes"]["year"] > 10  # tens of bp, not a fraction
    assert row["welcome"] == -1  # a rising yield is the unwelcome direction


def test_a_policy_rate_carries_no_trend_label(client, account, sources):
    """It steps when a committee decides and is flat in between; a moving
    average on it would be noise dressed as a signal."""
    rates = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "rates"},
            headers=AUTH,
        ).json()
    )["rates"]
    policy = next(r for r in rates["rows"] if r["key"] == "DFEDTARU")
    assert policy["state"] is None
    assert policy["welcome"] == 0


def test_a_gauge_reports_a_percentile_instead_of_a_year_change(
    client, account, sources
):
    """These series mean-revert: a percent change over a year on one of them is
    close to meaningless, and where it sits in its own year is the reading."""
    gauges = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "gauges"},
            headers=AUTH,
        ).json()
    )["gauges"]
    vix = next(r for r in gauges["rows"] if r["key"] == "^VIX")
    assert "year" not in vix["changes"]
    assert 0 <= vix["percentile"] <= 100
    assert vix["welcome"] == -1  # a rising fear gauge is not good news


def test_rotation_reports_excess_over_the_index_not_the_raw_move(
    client, account, sources
):
    """The question is which sectors led, and a difference of two numbers the
    reader can both see is the answer to it."""
    rotation = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "rotation"},
            headers=AUTH,
        ).json()
    )["rotation"]
    row = next(r for r in rotation["rows"] if r["key"] == "XLK")
    spx_only = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "cross"},
            headers=AUTH,
        ).json()
    )
    assert spx_only  # the cross block still answers on the same fetch
    # An excess return is small next to a raw one over the same window.
    assert abs(row["changes"]["month"]) < 1.0


def test_a_block_whose_source_died_keeps_its_place(client, account, sources,
                                                   monkeypatch):
    """An absent block reads as "nothing is happening here", which is a
    different and wrong claim."""
    from yfinance.exceptions import YFRateLimitError

    def throttled():
        raise YFRateLimitError

    monkeypatch.setattr(loaders, "pulse_closes", throttled)
    payload = client.get(
        "/v1/pulse/tables",
        params={"account": EMAIL, "blocks": "indices,rates"},
        headers=AUTH,
    ).json()
    by_block = blocks_of(payload)
    assert by_block["indices"]["unavailable"] == "rate_limited"
    assert by_block["indices"]["rows"] == []
    # The block on the other source is untouched.
    assert by_block["rates"]["unavailable"] is None
    assert by_block["rates"]["rows"]


def test_a_block_with_no_rows_says_so_rather_than_looking_healthy(
    client, account, monkeypatch, sources
):
    monkeypatch.setattr(loaders, "inflation", lambda: pd.DataFrame())
    block = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "inflation"},
            headers=AUTH,
        ).json()
    )["inflation"]
    assert block["unavailable"] == "no_data"


def test_a_book_that_cannot_be_priced_still_gets_the_market_read(
    client, account, sources, monkeypatch
):
    """Personalisation failing means less personalisation, never a lost block:
    the market read stands on its own for a reader with no book at all."""

    def boom(db, mtime, base, period):
        raise RuntimeError("no prices")

    monkeypatch.setattr(loaders, "basket_report", boom)
    block = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "indices"},
            headers=AUTH,
        ).json()
    )["indices"]
    assert block["unavailable"] is None
    assert block["rows"]
    assert all(row["weight"] is None for row in block["rows"])


def test_inflation_reads_the_frame_it_is_actually_given(client, account, sources):
    """`macro.inflation()` is one row per area — area, period, headline, core,
    prior, six_months, momentum, path — and not a column per area of a daily
    series like every other block here. Reading it the other way round made the
    whole block unrenderable: the route took a float of the string "EA", and its
    own `except Exception` reported that as "no_data" forever."""
    block = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "inflation"},
            headers=AUTH,
        ).json()
    )["inflation"]
    assert block["unavailable"] is None, "the block has to be able to render at all"
    rows = {row["key"]: row for row in block["rows"]}
    assert set(rows) == {"EA", "US"}
    assert rows["EA"]["value"] == pytest.approx(2.1)
    assert rows["EA"]["spark"][-1] == pytest.approx(2.1)
    assert rows["EA"]["welcome"] == -1  # cooling is the welcome direction


def test_inflation_quotes_the_horizons_a_monthly_print_actually_has(
    client, account, sources
):
    """A weekly change in a series published twelve times a year is arithmetic
    on data that does not exist."""
    block = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "inflation"},
            headers=AUTH,
        ).json()
    )["inflation"]
    changes = {row["key"]: row["changes"] for row in block["rows"]}
    assert set(changes["EA"]) == {"print", "half_year"}
    assert changes["EA"]["print"] == pytest.approx(-0.2)  # 2.1 against a 2.3 prior
    assert changes["EA"]["half_year"] == pytest.approx(-0.9)
    assert "week" not in changes["US"]


def test_each_area_carries_its_own_reference_month(client, account, sources):
    """The euro-area flash estimate and the US CPI release are weeks apart, and
    one "latest" label over both silently misdates one of them."""
    block = blocks_of(
        client.get(
            "/v1/pulse/tables",
            params={"account": EMAIL, "blocks": "inflation"},
            headers=AUTH,
        ).json()
    )["inflation"]
    periods = {row["key"]: row["name"] for row in block["rows"]}
    assert periods == {"EA": "2026-08", "US": "2026-07"}


# ------------------------------------------------- breadth and the bond pair


@pytest.fixture
def market(monkeypatch):
    """Two years of closes for enough of the market to read breadth off."""
    index = days(400)
    rng = np.random.default_rng(11)

    def walk(start: float, drift: float) -> pd.Series:
        return pd.Series(
            np.cumprod(1 + rng.normal(drift, 0.008, len(index))) * start, index=index
        )

    closes: dict[str, pd.Series] = {}
    for entry in sm.INDICES:
        closes[entry.ticker] = walk(100.0, 0.0008)  # every index in an uptrend
    for ticker in sm.SECTOR_ETFS.values():
        closes[ticker] = walk(50.0, 0.0008)
    closes["SPY"] = walk(400.0, 0.0008)
    closes["TLT"] = walk(90.0, -0.0004)
    for _key, first, second in sm.FACTOR_PAIRS:
        closes.setdefault(first, walk(80.0, 0.0006))
        closes.setdefault(second, walk(80.0, 0.0004))
    monkeypatch.setattr(loaders, "pulse_closes", lambda: closes)
    return closes


def test_breadth_counts_both_sides_of_the_fraction(client, market):
    """Hits and total, never a percentage: three of four and thirty of forty
    are the same fraction and not the same statement — and a denominator that
    shrank because a source failed has to be visible."""
    body = client.get("/v1/pulse", headers=AUTH).json()
    indices = body["breadth_indices"]
    # The denominator is every index that could be read, not every index there
    # is — that is the number a shrinking source shows up in.
    assert indices["total"] == len(sm.INDICES)
    assert 0 <= indices["hits"] <= indices["total"]
    assert indices["window"] == 200
    sectors = body["breadth_sectors"]
    assert sectors["total"] == len(sm.SECTOR_ETFS)
    assert sectors["window"] == sm.TREND_SLOW


def test_breadth_nobody_could_read_is_not_breadth_of_zero(client, monkeypatch):
    monkeypatch.setattr(loaders, "pulse_closes", dict)
    body = client.get("/v1/pulse", headers=AUTH).json()
    assert body["breadth_indices"] is None
    assert body["breadth_sectors"] is None


def test_the_stock_bond_pair_is_the_market_s_not_the_reader_s(client, market):
    """SPY against TLT — the same number for every account. `/pulse/book`
    answers the other question, and the two are not interchangeable."""
    body = client.get("/v1/pulse", headers=AUTH).json()
    assert body["stock_bond_correlation"] is not None
    assert -1.0 <= body["stock_bond_correlation"] <= 1.0
    assert body["stock_bond_correlation_then"] is not None


def test_a_dead_price_burst_costs_the_cards_and_not_the_score(
    client, monkeypatch
):
    """None of the three is why a reader opened this endpoint. The composite is
    cached separately and still answers; breadth and the correlation simply are
    not there."""

    def throttled():
        raise RuntimeError("yahoo said no")

    monkeypatch.setattr(loaders, "market_pulse", lambda: built())
    monkeypatch.setattr(loaders, "pulse_closes", throttled)
    body = client.get("/v1/pulse", headers=AUTH)
    assert body.status_code == 200
    payload = body.json()
    assert payload["score"] == 68.0, "the regime is what this call is for"
    assert payload["stock_bond_correlation"] is None
    assert payload["breadth_indices"] is None


# ------------------------------------------------------ the rest of a row


def test_factor_pairs_are_one_ratio_each(client, market, account):
    """A pair rises when the first side leads. The subtraction a reader would
    otherwise do in their head is the whole reading, so it is done here."""
    body = client.get(
        "/v1/pulse/tables", params={"account": EMAIL, "blocks": "factors"},
        headers=AUTH,
    ).json()
    block = body["blocks"][0]
    assert block["block"] == "factors"
    keys = [row["key"] for row in block["rows"]]
    assert "equal_cap" in keys, "RSP/SPY is in the fixture's closes"
    row = next(r for r in block["rows"] if r["key"] == "equal_cap")
    assert row["name"] == "RSP/SPY"
    # Neither side of a tilt is good news — which one a reader wants leading is
    # a question about their own book.
    assert row["welcome"] == 0
    assert row["as_of"], "a row says which observation it quotes"


def test_a_pair_with_a_missing_leg_is_dropped_not_halved(
    client, monkeypatch, account
):
    index = days(300)
    only_one = {"IVW": pd.Series(np.linspace(1.0, 2.0, len(index)), index=index)}
    monkeypatch.setattr(loaders, "pulse_closes", lambda: only_one)
    body = client.get(
        "/v1/pulse/tables", params={"account": EMAIL, "blocks": "factors"},
        headers=AUTH,
    ).json()
    assert body["blocks"][0]["rows"] == []


def test_a_sector_you_hold_none_of_is_zero_and_no_book_is_null(
    client, market, account, monkeypatch
):
    """The block's own caption says a sector you do not hold counts as zero.
    That is only true for a reader who has a book at all — null is reserved for
    the one who has none, and rendering it as 0.0% would be a claim about an
    allocation that does not exist."""
    monkeypatch.setattr(loaders, "benchmark_sectors", lambda: {"Technology": 0.31})

    def one_sector(db, mtime, ccy, span):
        class Report:
            weights = {"XLK": 1.0}

            def allocation(self, key):
                return {"Technology": 1.0} if key == "sector" else {}

        return Report()

    monkeypatch.setattr(loaders, "basket_report", one_sector)
    rows = client.get(
        "/v1/pulse/tables", params={"account": EMAIL, "blocks": "rotation"},
        headers=AUTH,
    ).json()["blocks"][0]["rows"]
    by_sector = {row["name"]: row for row in rows}
    assert by_sector["Technology"]["weight"] == pytest.approx(1.0)
    held_none = next(r for name, r in by_sector.items() if name != "Technology")
    assert held_none["weight"] == 0.0, "a book that holds none of it holds zero"
    # And the benchmark's own share, so the reader's number means something.
    assert by_sector["Technology"]["spy_weight"] == pytest.approx(0.31)


def test_a_reader_with_no_book_has_no_weights_at_all(
    client, market, account, monkeypatch
):
    monkeypatch.setattr(loaders, "basket_report", lambda *a, **k: None)
    rows = client.get(
        "/v1/pulse/tables", params={"account": EMAIL, "blocks": "rotation"},
        headers=AUTH,
    ).json()["blocks"][0]["rows"]
    assert all(row["weight"] is None for row in rows)


def test_the_conditions_index_is_published_not_discarded(
    client, account, monkeypatch
):
    """`pulse_rate_rows` fetches NFCI on every rates request. It used to be
    thrown away here, so the page that wanted to quote it could not while the
    request paid for it anyway."""
    index = days(300)
    series = {
        "DGS10": pd.Series(np.linspace(3.5, 4.2, len(index)), index=index),
        "NFCI": pd.Series(np.linspace(-0.4, -0.1, len(index)), index=index),
    }
    monkeypatch.setattr(loaders, "pulse_rate_rows", lambda: series)
    rows = client.get(
        "/v1/pulse/tables", params={"account": EMAIL, "blocks": "rates"},
        headers=AUTH,
    ).json()["blocks"][0]["rows"]
    nfci = next(r for r in rows if r["key"] == "NFCI")
    assert nfci["value"] == pytest.approx(-0.1)
    # Tighter conditions are the bad direction, and the index rises as they
    # tighten.
    assert nfci["welcome"] == -1
    assert nfci["as_of"], "a row says which observation it quotes"
