"""The comparison card: several listings rebased to one day, in one currency.

`analysis.compare` is the arithmetic — the axis, the carry across another
market's holiday, the conversion before the rebase. The route on top promises
the rest: the indices when nothing is asked, the subject never twice, a name
with no price or no rate left off and named, never drawn in the wrong money.

Nothing here touches the network — every loader is replaced.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.analysis import compare
from stocks.analysis import portfolio as portfolio_mod
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.api.routes import ticker as ticker_route

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def series(days: list[str], values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex(days))


# --------------------------------------------------------------- arithmetic


def test_each_line_starts_at_zero_and_reads_as_a_fraction():
    axis = pd.DatetimeIndex(["2026-01-05", "2026-01-06", "2026-01-07"])
    out = compare.lines({"A": series(list(map(str, axis.date)), [10, 11, 15])}, {}, axis)
    assert out["A"] == pytest.approx([0.0, 0.1, 0.5])


def test_another_markets_holiday_is_carried_not_dropped():
    """A US holiday under a European subject: SPY has no bar that day, and
    reads its last close rather than leaving a hole in the line."""
    axis = pd.DatetimeIndex(["2026-01-05", "2026-01-06", "2026-01-07"])
    spy = series(["2026-01-02", "2026-01-05", "2026-01-07"], [100, 110, 121])
    out = compare.lines({"SPY": spy}, {}, axis)
    assert out["SPY"] == pytest.approx([0.0, 0.0, 0.1])


def test_a_line_opens_on_the_axis_day_from_the_close_before_it():
    """The window's first day can be a session the other market did not
    trade: its line starts from the close it last had, not a day late."""
    axis = pd.DatetimeIndex(["2026-01-06", "2026-01-07"])
    other = series(["2026-01-02", "2026-01-07"], [50, 55])
    assert compare.lines({"X": other}, {}, axis)["X"] == pytest.approx([0.0, 0.1])


def test_a_late_listing_starts_where_its_history_does():
    axis = pd.DatetimeIndex(["2026-01-05", "2026-01-06", "2026-01-07"])
    ipo = series(["2026-01-06", "2026-01-07"], [20, 30])
    out = compare.lines({"IPO": ipo}, {}, axis)
    assert out["IPO"][0] is None
    assert out["IPO"][1:] == pytest.approx([0.0, 0.5])


def test_the_currency_moves_the_line_before_the_rebase():
    """Flat in dollars, up 10 % in euros when the dollar gains 10 %: the
    reader's money is what moved."""
    axis = pd.DatetimeIndex(["2026-01-05", "2026-01-06"])
    flat = series(["2026-01-05", "2026-01-06"], [100, 100])
    rate = pd.Series([0.9, 0.99], index=axis)
    assert compare.lines({"SPY": flat}, {"SPY": rate}, axis)["SPY"] == pytest.approx(
        [0.0, 0.1]
    )


def test_a_name_with_no_closes_is_left_out():
    axis = pd.DatetimeIndex(["2026-01-05", "2026-01-06"])
    assert compare.lines({"GONE": pd.Series(dtype=float)}, {}, axis) == {}


def test_zoned_bars_land_on_their_own_calendar_day():
    stamps = pd.DatetimeIndex(["2026-01-05 00:00", "2026-01-06 00:00"]).tz_localize(
        "America/New_York"
    )
    assert list(compare.day_index(stamps).strftime("%Y-%m-%d")) == [
        "2026-01-05",
        "2026-01-06",
    ]


# -------------------------------------------------------------------- route

DAYS = ["2026-01-05", "2026-01-06", "2026-01-07"]


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: ESTC\n")
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)

    closes = {
        "ESTC": [10.0, 11.0, 12.0],
        "SPY": [100.0, 101.0, 102.0],
        "QQQ": [200.0, 210.0, 220.0],
        "EEM": [40.0, 40.0, 44.0],
        "XLK": [50.0, 55.0, 60.0],
        "SAN.MC": [5.0, 5.5, 6.0],
        "ODD.XX": [1.0, 1.0, 1.0],
    }
    monkeypatch.setattr(
        loaders,
        "price_bars",
        lambda t, label: pd.DataFrame({"Close": closes[t]}, index=pd.DatetimeIndex(DAYS)),
    )

    def bar_closes(t, label):
        if t not in closes:
            return pd.Series(dtype=float)
        return series(DAYS, closes[t])

    monkeypatch.setattr(loaders, "bar_closes", bar_closes)
    monkeypatch.setattr(
        ticker_route,
        "listing_currencies",
        lambda names: {n: {"SAN.MC": "EUR", "ODD.XX": None}.get(n, "USD") for n in names},
    )
    monkeypatch.setattr(
        portfolio_mod,
        "fx_frame",
        lambda currencies, index, base="EUR": {
            c: pd.Series(1.0, index=pd.DatetimeIndex(index))
            for c in currencies
            if c == "USD"
        },
    )
    monkeypatch.setattr(ticker_route, "_sector_of", lambda t: "Technology")
    monkeypatch.setattr(loaders, "related", lambda t: ("MDB", "BTC-USD"))
    monkeypatch.setattr(loaders, "sec_title", lambda t: {"ESTC": "Elastic N.V."}.get(t))


def ask(client, symbol="ESTC", **params):
    return client.get(
        f"/v1/ticker/{symbol}/compare",
        params={"account": EMAIL, "base": "EUR", **params},
        headers=AUTH,
    )


def test_nothing_asked_draws_the_three_indices(client):
    body = ask(client).json()
    assert [(line["ticker"], line["role"]) for line in body["lines"]] == [
        ("ESTC", "subject"),
        ("SPY", "index"),
        ("QQQ", "index"),
        ("EEM", "index"),
    ]
    assert body["dates"] == DAYS and body["base"] == "EUR"
    assert body["lines"][0]["points"] == pytest.approx([0.0, 0.1, 0.2])
    assert body["lines"][0]["name"] == "Elastic N.V."


def test_the_picker_offers_the_sector_etf_and_related_names_but_no_coins(client):
    offered = [(o["ticker"], o["role"]) for o in ask(client).json()["offered"]]
    assert offered == [
        ("SPY", "index"),
        ("QQQ", "index"),
        ("EEM", "index"),
        ("XLK", "sector"),
        ("MDB", "peer"),
    ]


def test_the_chips_offer_a_handful_of_peers_not_yahoos_whole_list(client, monkeypatch):
    many = tuple(f"P{i}" for i in range(9))
    monkeypatch.setattr(loaders, "related", lambda t: many)
    peers = [o["ticker"] for o in ask(client).json()["offered"] if o["role"] == "peer"]
    assert peers == list(many[: compare.OFFERED_PEERS])


def test_asked_names_keep_their_order_and_the_subject_is_never_doubled(client):
    body = ask(client, **{"with": "xlk, estc,SAN.MC,xlk"}).json()
    assert [(line["ticker"], line["role"]) for line in body["lines"]] == [
        ("ESTC", "subject"),
        ("XLK", "sector"),
        ("SAN.MC", "pick"),
    ]


def test_an_empty_with_draws_the_subject_alone(client):
    assert [line["ticker"] for line in ask(client, **{"with": ""}).json()["lines"]] == [
        "ESTC"
    ]


def test_no_price_or_no_currency_is_named_not_drawn(client):
    """`ODD.XX` has no currency anyone could convert, `NOPE` no history: a line
    in the wrong money would read as a return it never made."""
    body = ask(client, **{"with": "SPY,ODD.XX,NOPE"}).json()
    assert [line["ticker"] for line in body["lines"]] == ["ESTC", "SPY"]
    assert body["missing"] == ["ODD.XX", "NOPE"]


def test_a_currency_without_a_rate_is_left_off(client):
    body = client.get(
        "/v1/ticker/ESTC/compare",
        params={"account": EMAIL, "base": "GBP", "with": "SAN.MC"},
        headers=AUTH,
    ).json()
    # The fake rate table knows USD only: euros cannot reach pounds here.
    assert [line["ticker"] for line in body["lines"]] == ["ESTC"]
    assert body["missing"] == ["SAN.MC"]


def test_at_most_six_names_beside_the_subject(client):
    many = ",".join(f"N{i}" for i in range(10))
    body = ask(client, **{"with": many}).json()
    assert len(body["missing"]) == compare.MAX_OTHERS


def test_an_intraday_range_is_refused(client):
    assert ask(client, range="1d").status_code == 422


# ------------------------------------------------------- review's windows

ANCHOR = pd.Timestamp("2026-10-16")


def test_a_window_reads_the_close_on_or_before_its_first_day():
    """Each window opens a day after a close: that close is the one read."""
    closes = series(
        ["2024-10-15", "2025-10-15", "2026-04-15", "2026-09-15", "2026-10-16"],
        [50, 60, 80, 90, 99],
    )
    out = compare.window_returns(closes, None, ANCHOR)
    assert out["1m"] == pytest.approx(0.1)
    assert out["6m"] == pytest.approx(99 / 80 - 1)
    assert out["1y"] == pytest.approx(99 / 60 - 1)
    assert out["2y"] == pytest.approx(99 / 50 - 1)


def test_a_listing_younger_than_the_window_has_no_return_for_it():
    closes = series(["2026-01-02", "2026-10-15"], [10, 12])
    out = compare.window_returns(closes, None, ANCHOR)
    assert out["6m"] == pytest.approx(0.2)
    assert out["1y"] is None and out["2y"] is None


def test_a_window_return_is_in_the_readers_money():
    axis = compare.window_axis(ANCHOR)
    flat = pd.Series(100.0, index=axis)
    rate = pd.Series([0.8, 0.8, 0.8, 0.9, 1.0], index=axis)
    out = compare.window_returns(flat, rate, ANCHOR)
    assert out["2y"] == pytest.approx(0.25)
    assert out["1m"] == pytest.approx(1 / 0.9 - 1)


def test_a_window_opens_on_the_first_session_on_or_after_its_day():
    """`history.shape`'s cut, so a column and the plan's chart read one close."""
    sessions = pd.bdate_range(end=ANCHOR, periods=600)
    days = compare.window_days(ANCHOR, sessions)
    assert days["6m"] == pd.Timestamp("2026-04-16")  # a Thursday: itself
    saturday = compare.window_days(pd.Timestamp("2026-08-15"), sessions)
    # 2026-07-15 is a Wednesday; 2026-02-15 a Sunday, so the Monday after.
    assert saturday["1m"] == pd.Timestamp("2026-07-15")
    assert saturday["6m"] == pd.Timestamp("2026-02-16")


# --------------------------------------------------------- review's route


@pytest.fixture
def returns_offline(monkeypatch):
    from stocks.api.routes import review as review_route

    # SPY's sessions: weekdays up to a Friday, so a window opening on a weekend
    # moves to the Monday, as the price chart starts it.
    sessions = pd.bdate_range(end=ANCHOR, periods=600)
    monkeypatch.setattr(
        loaders, "bar_closes", lambda t, label: pd.Series(1.0, index=sessions)
    )
    # Oldest window first: 2y, 1y, 6m, 1m, then the last session.
    closes = {
        "ESTC": [100.0, 100.0, 100.0, 100.0, 130.0],
        "SPY": [100.0, 100.0, 100.0, 100.0, 110.0],
        "XLK": [100.0, 100.0, 100.0, 100.0, 120.0],
        "SAN.MC": [5.0, 5.0, 5.0, 5.0, 6.0],
    }
    monkeypatch.setattr(
        loaders,
        "window_closes",
        lambda t, days: (
            pd.Series(closes[t], index=pd.DatetimeIndex(days.split(",")))
            if t in closes
            else pd.Series(dtype=float)
        ),
    )
    monkeypatch.setattr(
        review_route,
        "listing_currencies",
        lambda names: {n: {"SAN.MC": "EUR"}.get(n, "USD") for n in names},
    )
    monkeypatch.setattr(
        review_route,
        "_profile",
        lambda s: {
            "sector": "Technology" if s == "ESTC" else None,
            "country": None,
            "currency": None,
        },
    )


def ask_returns(client, names):
    return client.get(
        "/v1/review/returns",
        params={"account": EMAIL, "base": "EUR", "names": names},
        headers=AUTH,
    )


def test_each_name_comes_with_the_index_and_its_sectors_etf(client, returns_offline):
    body = ask_returns(client, "estc,SAN.MC,NOPE").json()
    rows = {row["ticker"]: row for row in body["names"]}
    assert list(rows) == ["ESTC", "SAN.MC"]
    assert rows["ESTC"]["returns"]["1y"] == pytest.approx(0.3)
    assert rows["ESTC"]["sector_etf"] == "XLK"
    assert rows["SAN.MC"]["sector_etf"] is None
    assert [b["ticker"] for b in body["benchmarks"]] == ["SPY", "XLK"]
    assert body["benchmarks"][0]["returns"]["2y"] == pytest.approx(0.1)
    assert body["missing"] == ["NOPE"] and body["pending"] == 0
    assert body["as_of"] == "2026-10-16"  # SPY's last session


def test_a_name_that_is_not_a_ticker_is_refused(client, returns_offline):
    assert ask_returns(client, "ESTC,../etc").status_code == 422
