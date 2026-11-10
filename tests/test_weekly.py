"""Weekly review (stocks.notify.weekly)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stocks.data.dividends import DividendEvent
from stocks.data.earnings import EarningsEvent
from stocks.notify import weekly as wk
from stocks.portfolio.ledger import Transaction

D = date(2026, 9, 13)  # a Sunday
# The autouse fixture below stubs `wk.recent_dividends`; these tests want the real one.
recent_dividends = wk.recent_dividends


def full_data(**over) -> wk.WeeklyData:
    base = dict(
        date=D,
        total=104_820.0,
        week=(1_940.0, 0.0189),
        month=(3_200.0, 0.0315),
        ytd=(12_400.0, 0.1340),
        benchmark={7: 0.0110, 30: 0.0240, (D - date(2026, 1, 1)).days: 0.0980},
        best=[("NVDA", 1_240.0, 0.081), ("KO", 210.0, 0.012)],
        worst=[("MELI", -820.0, -0.052)],
        dividends_received=(212.0, 3),
        ex_dividends=[DividendEvent("KO", date(2026, 9, 15), 2, 0.51, "USD")],
        dividend_cash={"KO": 55.0},
        earnings=[EarningsEvent("NVDA", date(2026, 9, 17), 4)],
        top_weight=0.68,
        effective_names=6.2,
        currency="EUR",
    )
    base.update(over)
    return wk.WeeklyData(**base)


# ------------------------------------------------------------------ compute


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No compute test may touch the network."""
    monkeypatch.setattr(wk, "upcoming_ex_dividends", lambda *a, **k: [])
    monkeypatch.setattr(wk, "calendar_events", lambda *a, **k: ([], []))
    monkeypatch.setattr(wk, "recent_dividends", lambda *a, **k: None)
    monkeypatch.setattr(wk, "index_closes", lambda *a, **k: None)


class _Pos:
    def __init__(self, ticker, quantity=1.0, currency="EUR"):
        self.ticker, self.quantity, self.currency = ticker, quantity, currency


def _book(monkeypatch, values: pd.DataFrame, positions, injected=None,
          shares: pd.DataFrame | None = None, txs=None, missing=()):
    """A book whose value path is `values` summed, with `injected` (the
    money put in, constant by default) as its flows. Each column is a leg
    priced in the book's currency at one share, unless `shares` says."""
    from stocks.analysis.portfolio.flows import Leg, Legs

    txs = txs if txs is not None else [
        Transaction("2020-01-02", t.ticker, "buy", 1, 1, "EUR") for t in positions
    ]
    monkeypatch.setattr(wk, "all_transactions", lambda path: txs)
    monkeypatch.setattr(wk, "build", lambda txs, base="EUR": (positions, []))
    value = values.sum(axis=1)
    put_in = pd.Series(
        float(value.iloc[0]) if injected is None else injected, index=value.index
    )
    flows = put_in.diff().fillna(0.0)
    twr = ((value - flows) / value.shift(1) - 1).iloc[1:]
    hist = pd.DataFrame({"value": value, "injected": put_in})
    legs = Legs()
    for col in values:
        q = shares[col] if shares is not None else pd.Series(1.0, index=values.index)
        px = (values[col] / q).where(q > 0)
        legs[col] = Leg(
            shares=q, value=values[col], px=px.ffill().bfill(),
            rate=pd.Series(1.0, index=values.index),
            marked=pd.Series(True, index=values.index),
        )
    hist.attrs["legs"] = legs
    monkeypatch.setattr(
        "stocks.analysis.portfolio.book_history",
        lambda txs, base="EUR": (hist, twr, list(missing)),
    )


def test_compute_reads_three_windows_and_the_weights_off_one_frame(
    tmp_path, monkeypatch
):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist: []\n")
    # The YTD anchor is the last close on or before 1 January — December 31.
    idx = pd.to_datetime(
        ["2025-12-31", "2026-08-14", "2026-09-06", "2026-09-13"]
    )
    values = pd.DataFrame(
        {"BIG": [600.0, 700.0, 760.0, 800.0], "SMALL": [100.0, 150.0, 180.0, 200.0]},
        index=idx,
    )
    _book(monkeypatch, values, [_Pos("BIG"), _Pos("SMALL")])

    data = wk.compute_weekly_data(
        watchlist, tmp_path / "portfolio.db", today=D
    )
    assert data.total == 1000.0
    assert data.week == pytest.approx((60.0, 60.0 / 940.0))
    assert data.month == pytest.approx((150.0, 150.0 / 850.0))
    assert data.ytd == pytest.approx((300.0, 300.0 / 700.0))
    # Ranked by money: BIG added 40 this week, SMALL 20.
    assert [t for t, _, _ in data.best] == ["BIG", "SMALL"]
    assert data.best[0][1] == pytest.approx(40.0)
    assert data.best[0][2] == pytest.approx(40.0 / 760.0)
    assert data.worst == []
    # Weights off the last row: 800/1000 and 200/1000, so the top 5 is all of it.
    assert data.top_weight == pytest.approx(1.0)
    assert data.effective_names == pytest.approx(1 / (0.8**2 + 0.2**2))


def test_a_deposit_is_not_a_year_to_date_gain(tmp_path, monkeypatch):
    """Doubling the book in September is money put in, not return: the year
    is what the money made, over all the money that was at work."""
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist: []\n")
    idx = pd.to_datetime(["2025-12-31", "2026-08-14", "2026-09-06", "2026-09-13"])
    values = pd.DataFrame({"A": [1000.0, 1100.0, 2200.0, 2200.0]}, index=idx)
    _book(monkeypatch, values, [_Pos("A")],
          injected=[1000.0, 1000.0, 2000.0, 2000.0])

    data = wk.compute_weekly_data(watchlist, tmp_path / "portfolio.db", today=D)
    gain, pct = data.ytd
    assert gain == pytest.approx(200.0)
    assert pct == pytest.approx(200.0 / 2000.0)
    assert data.month == pytest.approx((100.0, 100.0 / 2100.0))


def test_compute_returns_early_for_an_account_with_no_book(tmp_path, monkeypatch):
    """A watchlist has nothing to review — the daily digest is its message."""
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n  - ticker: AAPL\n")

    def boom(*a, **k):
        raise AssertionError("should not have priced anything")

    monkeypatch.setattr("stocks.analysis.portfolio.book_history", boom)
    data = wk.compute_weekly_data(watchlist, tmp_path / "portfolio.db", today=D)
    assert data.total is None and data.best == [] and data.top_weight is None


def test_compute_keeps_only_next_weeks_calendar(tmp_path, monkeypatch):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist: []\n")
    idx = pd.to_datetime(["2026-09-06", "2026-09-13"])
    values = pd.DataFrame({"A": [900.0, 1000.0]}, index=idx)
    _book(monkeypatch, values, [_Pos("A")])
    monkeypatch.setattr(
        wk, "calendar_events",
        lambda holdings, ref=None: (
            [EarningsEvent("A", date(2026, 9, 16), 3),
             EarningsEvent("B", date(2026, 10, 20), 37)],
            [],
        ),
    )

    data = wk.compute_weekly_data(watchlist, tmp_path / "portfolio.db", today=D)
    assert [e.ticker for e in data.earnings] == ["A"]


def test_compute_sections_fail_independently(tmp_path, monkeypatch):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist: []\n")
    idx = pd.to_datetime(["2026-09-06", "2026-09-13"])
    values = pd.DataFrame({"A": [900.0, 1000.0]}, index=idx)
    _book(monkeypatch, values, [_Pos("A")])

    def boom(*a, **k):
        raise RuntimeError("throttled")

    monkeypatch.setattr(wk, "calendar_events", boom)
    monkeypatch.setattr(wk, "upcoming_ex_dividends", boom)
    monkeypatch.setattr(wk, "recent_dividends", boom)

    data = wk.compute_weekly_data(watchlist, tmp_path / "portfolio.db", today=D)
    assert data.total == 1000.0  # the part that worked is still there
    assert data.earnings == [] and data.ex_dividends == []
    assert data.dividends_received is None


def test_ytd_days_counts_back_to_new_year():
    assert wk.WeeklyData(date=date(2026, 1, 1)).ytd_days == 0
    assert wk.WeeklyData(date=date(2026, 12, 31)).ytd_days == 364


def test_ytd_is_dropped_when_the_history_starts_after_new_year(tmp_path, monkeypatch):
    """An account whose prices only reach mid-year has no year to date — the
    line is dropped rather than measured from whenever the data happens to
    start, which would read as a return the reader never earned."""
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist: []\n")
    idx = pd.to_datetime(["2026-09-06", "2026-09-13"])
    values = pd.DataFrame({"A": [900.0, 1000.0]}, index=idx)
    _book(monkeypatch, values, [_Pos("A")])

    data = wk.compute_weekly_data(watchlist, tmp_path / "portfolio.db", today=D)
    assert data.week is not None and data.ytd is None


def test_a_name_bought_mid_week_counts_from_its_purchase(tmp_path, monkeypatch):
    """Its purchase is money put in, not its gain: B made 50 since Thursday,
    and its percent is over the days it was held."""
    idx = pd.to_datetime(["2026-09-06", "2026-09-10", "2026-09-13"])
    values = pd.DataFrame(
        {"A": [1000.0, 1000.0, 990.0], "B": [0.0, 500.0, 550.0]}, index=idx
    )
    shares = pd.DataFrame({"A": [1.0, 1.0, 1.0], "B": [0.0, 1.0, 1.0]}, index=idx)
    txs = [
        Transaction("2026-09-06", "A", "buy", 1, 1000, "EUR"),
        Transaction("2026-09-10", "B", "buy", 1, 500, "EUR"),
    ]
    _book(monkeypatch, values, [_Pos("A"), _Pos("B")],
          injected=[1000.0, 1500.0, 1500.0], shares=shares, txs=txs)

    data = wk.compute_weekly_data(tmp_path / "w.yaml", tmp_path / "p.db", today=D)
    assert data.best == [("B", pytest.approx(50.0), pytest.approx(0.10))]
    assert data.worst == [("A", pytest.approx(-10.0), pytest.approx(-0.01))]
    assert data.week == pytest.approx((40.0, 40.0 / 1500.0))


def test_since_start_leads_and_the_index_is_on_the_same_money(tmp_path, monkeypatch):
    idx = pd.to_datetime(["2026-03-02", "2026-09-06", "2026-09-13"])
    values = pd.DataFrame({"A": [1000.0, 1100.0, 1210.0]}, index=idx)
    _book(monkeypatch, values, [_Pos("A")])
    spy = pd.Series([100.0, 105.0, 110.0], index=idx)
    monkeypatch.setattr(wk, "index_closes", lambda base, first: spy)

    data = wk.compute_weekly_data(tmp_path / "w.yaml", tmp_path / "p.db", today=D)
    assert data.start == date(2026, 3, 2)
    assert data.since == pytest.approx((210.0, 0.21))
    assert data.benchmark[data.since_days] == pytest.approx(0.10)
    assert data.benchmark_gain[data.since_days] == pytest.approx(100.0)
    assert data.as_of == date(2026, 9, 13)


def test_no_index_in_the_books_currency_means_no_comparison(tmp_path, monkeypatch):
    idx = pd.to_datetime(["2026-09-06", "2026-09-13"])
    _book(monkeypatch, pd.DataFrame({"A": [900.0, 1000.0]}, index=idx), [_Pos("A")])
    data = wk.compute_weekly_data(tmp_path / "w.yaml", tmp_path / "p.db", today=D)
    assert data.week is not None and data.benchmark == {} and data.as_of is None


def test_unpriced_names_are_listed_and_counted_at_cost(tmp_path, monkeypatch):
    idx = pd.to_datetime(["2026-09-06", "2026-09-13"])
    values = pd.DataFrame({"A": [900.0, 1000.0], "ZZZ": [500.0, 500.0]}, index=idx)
    _book(monkeypatch, values, [_Pos("A"), _Pos("ZZZ")], missing=["ZZZ"])
    data = wk.compute_weekly_data(tmp_path / "w.yaml", tmp_path / "p.db", today=D)
    assert data.total == 1500.0 and data.missing == ["ZZZ"]
    assert data.largest == ("A", pytest.approx(1000 / 1500))


def test_the_week_ahead_reads_held_names_not_the_watchlist(tmp_path, monkeypatch):
    idx = pd.to_datetime(["2026-09-06", "2026-09-13"])
    _book(monkeypatch, pd.DataFrame({"A": [900.0, 1000.0]}, index=idx),
          [_Pos("A"), _Pos("SOLD", quantity=0.0)])
    asked = []
    monkeypatch.setattr(
        wk, "calendar_events",
        lambda holdings, ref=None: (
            asked.extend(h.ticker for h in holdings), ([], []))[1],
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n  - ticker: FOLLOWED\n")
    wk.compute_weekly_data(watchlist, tmp_path / "p.db", today=D)
    assert asked == ["A"]


# ----------------------------------------------------------------- dividends


def test_recent_dividends_nets_withholding_inside_the_window():
    txs = [
        Transaction(date="2026-09-12", ticker="KO", action="dividend",
                    price=100.0, fee=15.0, currency="EUR"),
        Transaction(date="2026-09-10", ticker="PG", action="dividend",
                    price=40.0, fee=0.0, currency="EUR"),
        Transaction(date="2026-07-01", ticker="JNJ", action="dividend",
                    price=999.0, fee=0.0, currency="EUR"),   # outside window
        Transaction(date="2026-09-11", ticker="KO", action="buy",
                    quantity=1, price=50.0, currency="EUR"),  # not a dividend
    ]
    got = recent_dividends(txs, "EUR", today=D, to_base=lambda a, c, d: a)
    assert got == (125.0, 2)  # (100-15) + 40


def test_recent_dividends_is_none_when_the_window_is_empty():
    txs = [Transaction(date="2026-01-01", ticker="KO", action="dividend",
                       price=10.0, currency="EUR")]
    assert recent_dividends(txs, "EUR", today=D, to_base=lambda a, c, d: a) is None
    assert recent_dividends([], "EUR", today=D) is None
