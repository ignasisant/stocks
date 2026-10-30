"""Weekly review (stocks.notify.weekly)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stocks.data.dividends import DividendEvent
from stocks.data.earnings import EarningsEvent
from stocks.notify import render
from stocks.notify import weekly as wk

D = date(2026, 9, 13)  # a Sunday


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
        drift=0.03,
        currency="EUR",
    )
    base.update(over)
    return wk.WeeklyData(**base)


# ---------------------------------------------------------------- rendering


def tr(lang: str = "en"):
    from stocks.web.i18n import translate

    return lambda key, **kw: translate(f"notify.{key}", lang, **kw)


def test_the_push_carries_the_week_in_the_title_and_opens_the_portfolio():
    msg = wk.weekly_message(full_data(highlight="Nvidia made the week."), "en")
    assert msg["title"] == "Your week +1,940 € (+1.89%) · portfolio €104,820"
    assert msg["body"].splitlines() == [
        "Month +3,200 € (+3.15%) · YTD +12,400 € (+13.40%)",
        "▲ NVDA +1,240 € (+8.1%) · ▼ MELI -820 € (-5.2%)",
        "Nvidia made the week.",
    ]
    assert msg["url"] == "/portfolio" and msg["tag"] == "weekly"


def test_the_push_is_translated():
    msg = wk.weekly_message(full_data(), "es")
    assert msg["title"] == "Tu semana +1,940 € (+1.89%) · cartera €104,820"
    assert msg["body"].startswith("Mes +3,200 € (+3.15%) · Año +12,400 € (+13.40%)")


def test_without_a_highlight_the_next_lines_move_up():
    lines = wk.weekly_message(full_data(), "en")["body"].splitlines()
    assert len(lines) == render.BODY_LINES
    assert lines[2].startswith("Top 5 = 68% of the book")


def test_benchmark_line_reads_the_same_windows_off_the_index():
    assert wk._benchmark_line(full_data(), tr()) == (
        "vs S&P 500 · Week +1.10% · Month +2.40% · YTD +9.80%"
    )
    assert wk._benchmark_line(full_data(benchmark={}), tr()) is None
    assert wk._benchmark_line(full_data(benchmark={7: None}), tr()) is None


def test_week_ahead_merges_prints_and_ex_dates_soonest_first():
    assert wk._ahead_line(full_data(), "en", tr()) == (
        "Week ahead: KO ex-date Tue 15 Sep ~€55, NVDA reports Thu 17 Sep"
    )
    assert wk._ahead_line(full_data(earnings=[], ex_dividends=[]), "en", tr()) is None


def test_concentration_reports_the_drift_and_the_equal_name_equivalent():
    assert wk._concentration_line(full_data(), tr()) == (
        "Top 5 = 68% of the book (+3 pt this week)"
        " · behaves like 6.2 equal-sized names"
    )


def test_concentration_drops_a_drift_too_small_to_mean_anything():
    """Below the floor the book was re-priced, not rebalanced."""
    line = wk._concentration_line(full_data(drift=0.004), tr())
    assert line.startswith("Top 5 = 68% of the book ·") and "pt this week" not in line
    # The first review of an account has nothing to compare against.
    assert "pt this week" not in wk._concentration_line(full_data(drift=None), tr())


def test_names_line_takes_the_top_of_each_side():
    assert wk._names_line(full_data(worst=[])) == "▲ NVDA +1,240 € (+8.1%)"
    assert wk._names_line(full_data(best=[], worst=[])) is None
    no_pct = full_data(best=[("A", 10.0, None)], worst=[])
    assert wk._names_line(no_pct) == "▲ A +10 €"


def test_sections_render_alone():
    msg = wk.weekly_message(wk.WeeklyData(date=D, total=1000.0), "en")
    assert msg["title"] == "Your week in review · Sun 13 Sep"  # no week change
    assert msg["body"] == ""


def test_a_watchlist_only_account_renders_a_title_and_nothing_else():
    msg = wk.weekly_message(wk.WeeklyData(date=D), "en")
    assert msg["title"] == "Your week in review · Sun 13 Sep"
    assert msg["body"] == ""


def test_dividend_receipt_has_a_singular_form():
    one = full_data(dividends_received=(38.0, 1))
    assert wk._dividends_line(one, tr()) == "€38 received this week, from one payment"
    assert "de un pago" in wk._dividends_line(one, tr("es"))
    assert wk._dividends_line(full_data(), tr()) == (
        "€212 received this week, from 3 payments"
    )


# ------------------------------------------------------------------ compute


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No compute test may touch the network."""
    monkeypatch.setattr(wk, "upcoming_ex_dividends", lambda *a, **k: [])
    monkeypatch.setattr(wk, "calendar_events", lambda *a, **k: ([], []))
    monkeypatch.setattr(wk, "recent_dividends", lambda *a, **k: None)
    monkeypatch.setattr(
        "stocks.analysis.portfolio.benchmark_changes", lambda *a, **k: {}
    )


class _Pos:
    def __init__(self, ticker, quantity=1.0, currency="EUR"):
        self.ticker, self.quantity, self.currency = ticker, quantity, currency


def _book(monkeypatch, values: pd.DataFrame, positions, injected=None):
    """A book whose value path is `values` summed, with `injected` (the
    money put in, constant by default) as its flows."""
    monkeypatch.setattr(wk, "all_transactions", lambda path: ["tx"])
    monkeypatch.setattr(wk, "build", lambda txs, base="EUR": (positions, []))
    monkeypatch.setattr(
        "stocks.analysis.portfolio.position_value_frames",
        lambda pos, period="1mo", base="EUR": (values, values),
    )
    value = values.sum(axis=1)
    put_in = pd.Series(
        float(value.iloc[0]) if injected is None else injected, index=value.index
    )
    flows = put_in.diff().fillna(0.0)
    twr = ((value - flows) / value.shift(1) - 1).iloc[1:]
    hist = pd.DataFrame({"value": value, "injected": put_in})
    monkeypatch.setattr(
        "stocks.analysis.portfolio.book_history",
        lambda txs, base="EUR": (hist, twr, []),
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

    monkeypatch.setattr("stocks.analysis.portfolio.position_value_frames", boom)
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
    assert "YTD" not in wk.weekly_message(data, "en")["body"]
