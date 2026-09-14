"""Weekly review (stocks.notify.weekly)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stocks.data.dividends import DividendEvent
from stocks.data.earnings import EarningsEvent
from stocks.notify import weekly as wk

D = date(2026, 9, 13)  # a Sunday
ORIGIN = "https://topstocks.example"


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


def test_render_full_review_en():
    text = wk.render_weekly(full_data(), "en")
    assert "<b>🗓 TopStocks — week in review</b> · Sun 13 Sep" in text
    assert "<b>Portfolio</b> €104,820" in text
    assert "Week +1,940 € (+1.89%)" in text
    assert "Month +3,200 € (+3.15%)" in text and "YTD +12,400 € (+13.40%)" in text
    assert "vs S&amp;P 500 · Week +1.10% · Month +2.40% · YTD +9.80%" in text
    assert "<b>Best of the week</b>\n▲ NVDA +1,240 € (+8.1%)" in text
    assert "<b>Worst of the week</b>\n▼ MELI -820 € (-5.2%)" in text
    assert "€212 received this week, from 3 payments" in text


def test_render_spanish_labels():
    text = wk.render_weekly(full_data(), "es")
    assert "la semana en revisión" in text
    assert "Mes" in text and "Año" in text
    assert "Lo mejor de la semana" in text and "Lo peor de la semana" in text
    assert "dom 13 sep" in text


def test_week_ahead_merges_prints_and_ex_dates_soonest_first():
    text = wk.render_weekly(full_data(), "en")
    ahead = text.split("<b>Week ahead</b>\n")[1].split("\n\n")[0].splitlines()
    assert ahead[0].startswith("• KO — ex-date Tue 15 Sep (T-2) · ~€55")
    assert ahead[1].startswith("• NVDA — reports Thu 17 Sep (T-4)")


def test_week_ahead_is_capped():
    events = [
        EarningsEvent(f"T{i}", date(2026, 9, 14 + i), i + 1) for i in range(8)
    ]
    text = wk.render_weekly(full_data(earnings=events), "en")
    ahead = text.split("<b>Week ahead</b>\n")[1].split("\n\n")[0].splitlines()
    assert len(ahead) == wk.AHEAD_SHOWN


def test_concentration_reports_the_drift_and_the_equal_name_equivalent():
    text = wk.render_weekly(full_data(), "en")
    assert "Top 5 = 68% of the book (+3 pt this week)" in text
    assert "behaves like 6.2 equal-sized names" in text


def test_concentration_drops_a_drift_too_small_to_mean_anything():
    """Below the floor the book was re-priced, not rebalanced."""
    text = wk.render_weekly(full_data(drift=0.004), "en")
    assert "Top 5 = 68% of the book ·" in text and "pt this week" not in text
    # The first review of an account has nothing to compare against.
    assert "pt this week" not in wk.render_weekly(full_data(drift=None), "en")


def test_sections_render_alone():
    bare = wk.WeeklyData(date=D, total=1000.0)
    text = wk.render_weekly(bare, "en")
    assert "€1,000" in text
    for absent in ("Best of the week", "Week ahead", "Concentration", "vs S&amp;P"):
        assert absent not in text


def test_a_watchlist_only_account_renders_a_title_and_nothing_else():
    text = wk.render_weekly(wk.WeeklyData(date=D), "en")
    assert text == "<b>🗓 TopStocks — week in review</b> · Sun 13 Sep"


def test_dividend_receipt_has_a_singular_form():
    assert "from one payment" in wk.render_weekly(
        full_data(dividends_received=(38.0, 1)), "en"
    )
    assert "de un pago" in wk.render_weekly(
        full_data(dividends_received=(38.0, 1)), "es"
    )


def test_tickers_link_when_an_origin_is_configured():
    text = wk.render_weekly(full_data(), "en", ORIGIN)
    for ticker in ("NVDA", "MELI", "KO"):
        assert f'<a href="{ORIGIN}/ticker?ticker={ticker}">{ticker}</a>' in text
    assert wk.render_weekly(full_data(), "en") == wk.render_weekly(
        full_data(), "en", None
    )


def test_escapes_html_in_dynamic_text():
    data = full_data(best=[("A&B<X>", 10.0, 0.01)], highlight="risk <on> & rising")
    text = wk.render_weekly(data, "en")
    assert "A&amp;B&lt;X&gt;" in text and "risk &lt;on&gt; &amp; rising" in text


def test_buttons_follow_the_calendar():
    assert wk.weekly_buttons(full_data(earnings=[]), "en", ORIGIN) == [
        ("Portfolio", f"{ORIGIN}/portfolio")
    ]
    assert [x for x, _ in wk.weekly_buttons(full_data(), "es", ORIGIN)] == [
        "Cartera", "Resultados"
    ]


def test_buttons_are_empty_without_an_origin(monkeypatch):
    monkeypatch.setattr(wk.links, "app_base", lambda: None)
    assert wk.weekly_buttons(full_data(), "en") == []


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


def _book(monkeypatch, values: pd.DataFrame, positions):
    monkeypatch.setattr(wk, "all_transactions", lambda path: ["tx"])
    monkeypatch.setattr(wk, "build", lambda txs, base="EUR": (positions, []))
    monkeypatch.setattr(
        "stocks.analysis.portfolio.position_value_frames",
        lambda pos, period="1y", base="EUR": (values, values),
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
    assert "YTD" not in wk.render_weekly(data, "en")


def test_body_text_escapes_only_what_telegram_documents():
    """Python's default escape turns an apostrophe into `&#x27;`, which
    Telegram is not documented to decode — an LLM sentence would arrive
    showing the entity. Only & < > are escaped in body text."""
    data = full_data(highlight="Thursday's print & the <gap> after it")
    text = wk.render_weekly(data, "en")
    assert "Thursday's print &amp; the &lt;gap&gt; after it" in text
    assert "&#x27;" not in text


def test_an_href_still_escapes_its_quotes():
    from stocks.notify.render import ticker_link

    assert ticker_link('A"B', "https://x.example").startswith(
        '<a href="https://x.example/ticker?ticker=A%22B">'
    )
