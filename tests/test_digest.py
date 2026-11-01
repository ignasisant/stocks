"""Daily digest builder (stocks.notify.digest)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from stocks.data.dividends import DividendEvent
from stocks.data.earnings import EarningsEvent
from stocks.notify import digest as dg
from stocks.notify import render
from stocks.web.i18n import translate

D = date(2026, 8, 14)  # a Friday


def full_data() -> dg.DigestData:
    return dg.DigestData(
        date=D,
        total=48230.0,
        day=(412.0, 0.0086),
        week=(-1105.0, -0.0224),
        movers=[("NVDA", 0.032), ("SHOP", 0.021), ("MELI", 0.014),
                ("TTD", -0.011), ("FSLR", -0.019), ("UNH", -0.028)],
        earnings=[EarningsEvent("NVDA", date(2026, 8, 20), 6)],
        highlight="Nvidia drove most of today's gain.",
    )


# ---------------------------------------------------------------- rendering


def test_the_push_carries_the_book_in_the_title_and_opens_today():
    msg = dg.digest_message(full_data(), "en")
    assert msg["title"] == "Portfolio €48,230 · today +412 € (+0.86%)"
    assert msg["body"].splitlines() == [
        "▲ NVDA +3.2% · ▼ UNH -2.8%",
        "Earnings, next 7 days: NVDA Thu 20 Aug",
        "Nvidia drove most of today's gain.",
    ]
    assert msg["url"] == "/today" and msg["tag"] == "digest"


def test_the_push_is_translated():
    msg = dg.digest_message(full_data(), "es")
    assert msg["title"] == "Cartera €48,230 · hoy +412 € (+0.86%)"
    assert "Resultados, próximos 7 días: NVDA jue 20 ago" in msg["body"]


def test_a_watchlist_falls_back_to_a_dated_title():
    data = dg.DigestData(date=D, watchlist_only=True,
                         movers=[("AAPL", 0.01)], earnings=[])
    msg = dg.digest_message(data, "en")
    assert msg["title"] == "Your daily digest · Fri 14 Aug"
    assert msg["body"] == "▲ AAPL +1.0%"
    assert dg.digest_message(data, "es")["title"] == "Tu resumen diario · vie 14 ago"


def test_partial_sections_still_render():
    msg = dg.digest_message(dg.DigestData(date=D, total=1000.0), "en")
    assert msg["title"] == "Your daily digest · Fri 14 Aug"  # no day change
    assert msg["body"] == ""


def test_the_body_keeps_the_lines_that_matter_most():
    """A lock screen shows three lines: the movers, the first calendar item
    and the narrated line win; the rest is what the tap is for."""
    data = priced_data(
        results=[_result()],
        dividends_received=(124.0, 2),
        benchmark=(0.014, None),
        highlight="Nvidia carried the day.",
    )
    lines = dg.digest_message(data, "en")["body"].splitlines()
    assert len(lines) == render.BODY_LINES
    assert lines[0].startswith("▲ NVDA")
    assert lines[1].startswith("Just reported: NVDA")
    assert lines[2] == "Nvidia carried the day."


# ------------------------------------------------------------ compute


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No compute test may touch the network.

    Every section here fails soft, so a live call would not fail the suite —
    it would just make it slow and non-deterministic, and quietly depend on
    Yahoo answering. Each test overrides the stub it actually asserts on.
    """
    monkeypatch.setattr(dg, "upcoming_ex_dividends", lambda *a, **k: [])
    monkeypatch.setattr(dg, "calendar_events", lambda *a, **k: ([], []))
    monkeypatch.setattr(dg, "_result_moves", lambda results: {})
    monkeypatch.setattr(dg, "_benchmark_changes", lambda *a, **k: None)
    monkeypatch.setattr("stocks.data.fx.prefetch", lambda pairs, quote="EUR": None)
    monkeypatch.setattr("stocks.data.fx.to_base", lambda a, c, d, b="EUR": a)


def test_compute_digest_data_watchlist_only(tmp_path, monkeypatch):
    """No ledger transactions -> movers/earnings from the watchlist."""
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    db = tmp_path / "portfolio.db"  # missing file -> no transactions

    import stocks.analysis.portfolio as ap

    monkeypatch.setattr(ap, "session_moves", lambda ts, max_workers=8: {"AAPL": 0.012})
    monkeypatch.setattr(
        dg, "calendar_events",
        lambda holdings: ([EarningsEvent("AAPL", date(2026, 8, 18), 4)], []),
    )

    data = dg.compute_digest_data(watchlist, db)
    assert data.watchlist_only is True
    assert data.total is None
    assert data.movers == [("AAPL", 0.012)]
    assert data.earnings[0].ticker == "AAPL"


def test_compute_digest_data_with_ledger(tmp_path, monkeypatch):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist: []\n")
    db = tmp_path / "portfolio.db"

    class FakePosition:
        ticker = "NVDA"

    monkeypatch.setattr(dg, "all_transactions", lambda path: ["tx"])
    monkeypatch.setattr(
        dg, "build", lambda txs, base="EUR": ([FakePosition()], [])
    )

    import stocks.analysis.portfolio as ap

    idx = pd.to_datetime(["2026-08-06", "2026-08-13", "2026-08-14"])
    values = pd.DataFrame({"NVDA": [900.0, 950.0, 1000.0]}, index=idx)
    monkeypatch.setattr(
        ap,
        "position_value_frames",
        lambda pos, period="1mo", base="EUR": (values, values),
    )
    # 500 of the week's rise was a deposit: the week is what the money made,
    # over the 400 at work plus the 500 put in.
    hist = pd.DataFrame(
        {"value": [400.0, 950.0, 1000.0], "injected": [400.0, 900.0, 900.0]},
        index=idx,
    )
    twr = pd.Series([450.0 / 400.0 - 1, 50.0 / 950.0], index=idx[1:])
    monkeypatch.setattr(ap, "book_history", lambda txs, base="EUR": (hist, twr, []))
    monkeypatch.setattr(ap, "session_moves", lambda ts, max_workers=8: {"NVDA": 0.05})
    monkeypatch.setattr(dg, "calendar_events", lambda holdings: ([], []))

    data = dg.compute_digest_data(watchlist, db)
    assert data.watchlist_only is False
    assert data.total == 1000.0
    assert data.day == pytest.approx((50.0, 50.0 / 950.0))
    gain, pct = data.week
    assert gain == pytest.approx(100.0)
    assert pct == pytest.approx(100.0 / 900.0)
    assert data.movers == [("NVDA", 0.05)]


def test_compute_sections_fail_independently(tmp_path, monkeypatch):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n  - ticker: AAPL\n")

    import stocks.analysis.portfolio as ap

    def boom(*a, **k):
        raise RuntimeError("throttled")

    monkeypatch.setattr(ap, "session_moves", boom)
    monkeypatch.setattr(dg, "calendar_events", boom)

    data = dg.compute_digest_data(watchlist, tmp_path / "portfolio.db")
    assert data.movers == [] and data.earnings == []  # dropped, not raised


# -------------------------------------------------- money-weighted movers


def priced_data(**over) -> dg.DigestData:
    """A book where the loudest percentage is NOT the biggest contributor."""
    base = dict(
        date=D,
        total=48230.0,
        day=(412.0, 0.0086),
        movers=[("SMALL", 0.090), ("NVDA", 0.032), ("UNH", -0.028),
                ("TINY", -0.070)],
        contrib={"NVDA": 380.0, "SMALL": 45.0, "TINY": -13.0, "UNH": -180.0},
    )
    base.update(over)
    return dg.DigestData(**base)


def tr(lang: str = "en"):
    return lambda key, **kw: translate(f"notify.{key}", lang, **kw)


def test_movers_are_ranked_by_money_not_percent():
    # +9.0% on a small position must not outrank +3.2% on a large one.
    assert dg.movers_line(priced_data()) == "▲ NVDA +380 € (+3.2%) · ▼ UNH -180 € (-2.8%)"


def test_movers_fall_back_to_percent_ranking_without_a_book():
    """A watchlist has no weights, so the percentage is all there is."""
    data = dg.DigestData(date=D, watchlist_only=True,
                         movers=[("A", 0.01), ("B", 0.09), ("C", -0.02)])
    assert dg.movers_line(data) == "▲ B +9.0% · ▼ C -2.0%"


def test_ranked_movers_unions_quotes_and_values():
    """A quote that failed still moved the book; a name absent from the value
    frame still has a quote. Neither may drop out of the ranking."""
    data = dg.DigestData(date=D, movers=[("QUOTED", -0.02)],
                         contrib={"VALUED": 500.0})
    rows = dg.ranked_movers(data)
    assert {r[0] for r in rows} == {"QUOTED", "VALUED"}
    # No money figure for QUOTED: it is sided by its percentage, not a flat 0.
    assert dg.movers_line(data) == "▲ VALUED +500 € · ▼ QUOTED -2.0%"


def test_money_movers_split_by_the_sign_of_the_money():
    """A name can be up on the day in percent and still be listed by its
    money — the sign that decides the side is the one being printed."""
    data = dg.DigestData(date=D, movers=[("A", 0.02)], contrib={"A": -50.0})
    assert dg.movers_line(data) == "▼ A -50 € (+2.0%)"


def test_no_movers_is_no_line():
    assert dg.movers_line(dg.DigestData(date=D)) is None


# -------------------------------------------------------------- benchmark


def test_benchmark_line_reports_the_gap_both_ways():
    behind = dg.benchmark_line(priced_data(benchmark=(0.014, 0.02)), tr())
    assert behind == "vs S&P 500 +1.40% · behind by 0.54 pt"
    ahead = dg.benchmark_line(priced_data(benchmark=(0.002, None)), tr())
    assert ahead == "vs S&P 500 +0.20% · ahead by 0.66 pt"


def test_benchmark_line_omitted_when_incomparable():
    assert dg.benchmark_line(priced_data(benchmark=None), tr()) is None
    assert dg.benchmark_line(priced_data(benchmark=(None, 0.02)), tr()) is None
    # No day change of our own to compare against.
    bare = dg.DigestData(date=D, total=100.0, benchmark=(0.01, 0.01))
    assert dg.benchmark_line(bare, tr()) is None


def test_benchmark_line_is_translated():
    line = dg.benchmark_line(priced_data(benchmark=(0.014, None)), tr("es"))
    assert line.endswith("por detrás 0.54 pt")


# ------------------------------------------------------------- dividends


def test_dividend_lines_show_ex_dates_estimated_cash_and_receipts():
    data = priced_data(
        ex_dividends=[
            DividendEvent("KO", date(2026, 8, 16), 2, 0.51, "USD"),
            DividendEvent("MSFT", date(2026, 8, 20), 6, 0.83, "USD"),
        ],
        dividend_cash={"KO": 61.0},  # no quantity held of MSFT
        dividends_received=(124.0, 2),
    )
    assert dg.calendar_lines(data, "en") == [
        "Ex-dividend: KO Sun 16 Aug ~€61, MSFT Thu 20 Aug",
        "€124 received over the last 7 days, from 2 payments",
    ]


def test_dividend_receipt_has_a_singular_form():
    data = priced_data(dividends_received=(38.0, 1))
    assert "from one payment" in dg.calendar_lines(data, "en")[0]
    assert "de un pago" in dg.calendar_lines(data, "es")[0]


# ------------------------------------------------------------- quiet days


def test_a_calendar_entry_keeps_the_full_digest():
    """An ex-date or a print is news even on a session that did nothing."""
    flat = dict(date=D, total=100.0, day=(0.1, 0.0002), movers=[("A", 0.001)])
    assert dg.DigestData(**flat).quiet is True
    assert dg.DigestData(
        **flat, earnings=[EarningsEvent("A", date(2026, 8, 18), 4)]
    ).quiet is False
    assert dg.DigestData(
        **flat, ex_dividends=[DividendEvent("A", date(2026, 8, 18), 4)]
    ).quiet is False
    assert dg.DigestData(**flat, dividends_received=(10.0, 1)).quiet is False


def test_a_real_move_is_never_quiet_and_nor_is_a_missing_one():
    assert dg.DigestData(date=D, total=100.0, day=(50.0, 0.02)).quiet is False
    # No day change computed at all: silence there is a missing number, not a
    # calm market, so the digest still says everything it knows.
    assert dg.DigestData(date=D, total=100.0, movers=[("A", 0.5)]).quiet is False


# --------------------------------------------------- compute, new sections


def test_recent_dividends_nets_withholding_inside_the_window():
    from stocks.portfolio.ledger import Transaction

    txs = [
        Transaction(date="2026-08-13", ticker="KO", action="dividend",
                    price=100.0, fee=15.0, currency="EUR"),
        Transaction(date="2026-08-10", ticker="PG", action="dividend",
                    price=40.0, fee=0.0, currency="EUR"),
        Transaction(date="2026-07-01", ticker="JNJ", action="dividend",
                    price=999.0, fee=0.0, currency="EUR"),   # outside window
        Transaction(date="2026-08-12", ticker="KO", action="buy",
                    quantity=1, price=50.0, currency="EUR"),  # not a dividend
    ]
    got = dg.recent_dividends(txs, "EUR", today=D, to_base=lambda a, c, d: a)
    assert got == (125.0, 2)  # (100-15) + 40


def test_recent_dividends_is_none_when_the_window_is_empty():
    from stocks.portfolio.ledger import Transaction

    txs = [Transaction(date="2026-01-01", ticker="KO", action="dividend",
                       price=10.0, currency="EUR")]
    assert dg.recent_dividends(txs, "EUR", today=D, to_base=lambda a, c, d: a) is None
    assert dg.recent_dividends([], "EUR", today=D) is None


def test_compute_fills_contributions_from_the_same_frame_as_the_day_change(
    tmp_path, monkeypatch
):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist: []\n")

    class FakePosition:
        ticker = "NVDA"
        quantity = 10.0
        currency = "USD"

    monkeypatch.setattr(dg, "all_transactions", lambda path: ["tx"])
    monkeypatch.setattr(dg, "build", lambda txs, base="EUR": ([FakePosition()], []))
    monkeypatch.setattr(dg, "calendar_events", lambda holdings: ([], []))

    import stocks.analysis.portfolio as ap

    idx = pd.to_datetime(["2026-08-13", "2026-08-14"])
    values = pd.DataFrame({"NVDA": [950.0, 1000.0]}, index=idx)
    monkeypatch.setattr(
        ap,
        "position_value_frames",
        lambda pos, period="1mo", base="EUR": (values, values),
    )
    monkeypatch.setattr(ap, "session_moves", lambda ts, max_workers=8: {"NVDA": 0.05})
    monkeypatch.setattr(dg, "_benchmark_changes", lambda *a, **k: (0.01, 0.02))

    data = dg.compute_digest_data(watchlist, tmp_path / "portfolio.db")
    assert data.contrib == {"NVDA": 50.0}
    assert data.contrib["NVDA"] == pytest.approx(data.day[0])
    assert data.benchmark == (0.01, 0.02)


def test_compute_prices_upcoming_dividends_against_held_quantities(
    tmp_path, monkeypatch
):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist: []\n")

    class Held:
        ticker = "KO"
        quantity = 120.0
        currency = "USD"

    monkeypatch.setattr(dg, "all_transactions", lambda path: ["tx"])
    monkeypatch.setattr(dg, "build", lambda txs, base="EUR": ([Held()], []))
    monkeypatch.setattr(dg, "calendar_events", lambda holdings: ([], []))
    monkeypatch.setattr(
        dg, "upcoming_ex_dividends",
        lambda tickers, within_days=7: [
            DividendEvent("KO", date(2026, 8, 16), 2, 0.51, "USD"),
            DividendEvent("PG", date(2026, 8, 18), 4, 1.05, "USD"),  # not held
        ],
    )
    monkeypatch.setattr("stocks.data.fx.to_base", lambda a, c, d, b="EUR": a * 0.9)

    import stocks.analysis.portfolio as ap

    monkeypatch.setattr(
        ap,
        "position_value_frames",
        lambda pos, period="1mo", base="EUR": (pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(ap, "session_moves", lambda ts, max_workers=8: {})

    data = dg.compute_digest_data(watchlist, tmp_path / "portfolio.db")
    assert [e.ticker for e in data.ex_dividends] == ["KO", "PG"]
    assert data.dividend_cash == pytest.approx({"KO": 120 * 0.51 * 0.9})


def test_compute_skips_the_benchmark_without_a_day_change(tmp_path, monkeypatch):
    """Nothing to compare against — the fetch would be pure waste."""
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n  - ticker: AAPL\n")

    def boom(*a, **k):
        raise AssertionError("should not have fetched the benchmark")

    monkeypatch.setattr(dg, "_benchmark_changes", boom)
    import stocks.analysis.portfolio as ap

    monkeypatch.setattr(ap, "session_moves", lambda ts, max_workers=8: {"AAPL": 0.01})
    monkeypatch.setattr(dg, "calendar_events", lambda holdings: ([], []))

    data = dg.compute_digest_data(watchlist, tmp_path / "portfolio.db")
    assert data.benchmark is None


# --------------------------------------------------------- reported quarters


def _result(**over):
    from stocks.data.earnings import EarningsResult

    base = dict(ticker="NVDA", date=date(2026, 8, 13),
                eps_estimate=1.18, reported_eps=1.24, surprise_pct=5.1)
    base.update(over)
    return EarningsResult(**base)


def test_results_line_reads_beat_miss_and_reaction():
    data = priced_data(results=[_result()], result_moves={"NVDA": 6.42})
    assert dg.calendar_lines(data, "en") == ["Just reported: NVDA beat +6.4%"]


def test_results_degrade_to_whatever_is_known():
    miss = priced_data(results=[_result(surprise_pct=-3.0)])
    assert dg.calendar_lines(miss, "en") == ["Just reported: NVDA miss"]
    bare = priced_data(results=[_result(eps_estimate=None, reported_eps=None,
                                        surprise_pct=None)])
    assert dg.calendar_lines(bare, "en") == ["Just reported: NVDA"]


def test_results_are_translated():
    data = priced_data(results=[_result()], result_moves={"NVDA": 6.42})
    assert dg.calendar_lines(data, "es") == ["Acaban de publicar: NVDA supera +6.4%"]


# ------------------------------------------------------------- import nudge


def test_stale_import_line_carries_the_age():
    data = priced_data(stale_import_days=63)
    assert dg.calendar_lines(data, "en") == [
        "Last statement import 63 days ago — your book may be out of date."
    ]
    assert "hace 63 días" in dg.calendar_lines(data, "es")[0]


def test_stale_import_days_only_fires_on_monday_and_only_when_old(tmp_path):
    import json

    from stocks.portfolio.last_import import ImportRecord, save

    record = tmp_path / "last_import.json"
    save(ImportRecord(filename="x.csv", imported_at="2026-06-01T10:00:00",
                      tx_ids=[1]), record)
    monday, friday = date(2026, 9, 7), date(2026, 9, 4)
    assert dg.stale_import_days(record, monday) == 98
    assert dg.stale_import_days(record, friday) is None  # not the nudge day

    save(ImportRecord(filename="x.csv", imported_at="2026-09-01T10:00:00",
                      tx_ids=[1]), record)
    assert dg.stale_import_days(record, monday) is None  # 6 days is not stale

    # An account that types its ledger by hand has no record to nag about.
    assert dg.stale_import_days(tmp_path / "nope.json", monday) is None
    record.write_text(json.dumps({"filename": "x", "imported_at": "not-a-date",
                                  "tx_ids": []}))
    assert dg.stale_import_days(record, monday) is None


def test_a_print_or_a_nudge_keeps_the_full_digest():
    flat = dict(date=D, total=100.0, day=(0.1, 0.0002), movers=[("A", 0.001)])
    assert dg.DigestData(**flat, results=[_result()]).quiet is False
    assert dg.DigestData(**flat, stale_import_days=63).quiet is False


def test_compute_reads_both_directions_off_one_earnings_fetch(
    tmp_path, monkeypatch
):
    """The rear-view is free — calendar_events already pulled the reported
    columns — so it must not cost a second pass over the watchlist."""
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n  - ticker: NVDA\n")

    calls: list[str] = []

    def fake_calendar(holdings):
        calls.append("fetch")
        return (
            [EarningsEvent("NVDA", date.today() + timedelta(days=3), 3),
             EarningsEvent("KO", date.today() + timedelta(days=40), 40)],
            [_result(date=date.today() - timedelta(days=1)),
             _result(ticker="OLD", date=date.today() - timedelta(days=30))],
        )

    monkeypatch.setattr(dg, "calendar_events", fake_calendar)
    monkeypatch.setattr(dg, "_result_moves", lambda results: {"NVDA": 6.4})
    import stocks.analysis.portfolio as ap

    monkeypatch.setattr(ap, "session_moves", lambda ts, max_workers=8: {})

    data = dg.compute_digest_data(watchlist, tmp_path / "portfolio.db")
    assert calls == ["fetch"]
    assert [e.ticker for e in data.earnings] == ["NVDA"]   # KO is 40 days out
    assert [r.ticker for r in data.results] == ["NVDA"]    # OLD is stale news
    assert data.result_moves == {"NVDA": 6.4}


def test_compute_skips_the_nudge_without_a_book(tmp_path, monkeypatch):
    """A watchlist-only account has no imported book to be stale."""
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n  - ticker: AAPL\n")

    def boom(*a, **k):
        raise AssertionError("should not have read the import record")

    monkeypatch.setattr(dg, "stale_import_days", boom)
    import stocks.analysis.portfolio as ap

    monkeypatch.setattr(ap, "session_moves", lambda ts, max_workers=8: {})
    data = dg.compute_digest_data(
        watchlist, tmp_path / "portfolio.db", import_record=tmp_path / "li.json"
    )
    assert data.stale_import_days is None


# ------------------------------------------------------------- calendar


def test_calendar_lines_put_what_can_be_missed_first():
    """A deadline outranks a print that happened, which outranks one coming,
    which outranks cash; the import reminder is about the app, so it is last."""
    from stocks.portfolio.tax import deadlines

    data = priced_data(
        tax_deadlines=deadlines.due_soon("ES", date(2027, 3, 5)),
        results=[_result()],
        earnings=[EarningsEvent("ASML", date(2026, 8, 20), 6)],
        ex_dividends=[DividendEvent("KO", date(2026, 8, 16), 2, 0.51, "USD")],
        dividends_received=(38.0, 1),
        stale_import_days=63,
    )
    lines = dg.calendar_lines(data, "en")
    assert [line.split()[0] for line in lines] == [
        "🗓", "Just", "Earnings,", "Ex-dividend:", "€38", "Last",
    ]


def test_an_undated_print_is_left_out_of_the_calendar():
    data = priced_data(earnings=[EarningsEvent("ASML", None, None)])
    assert dg.calendar_lines(data, "en") == []


def test_a_tax_deadline_is_named_and_keeps_the_full_digest():
    from stocks.portfolio.tax import deadlines

    today = date(2027, 3, 5)
    data = dg.DigestData(
        date=today,
        day=(0.0, 0.0),
        tax_deadlines=deadlines.due_soon("ES", today),
    )
    assert not data.quiet
    first = dg.calendar_lines(data, "es")[0]
    assert first.startswith("🗓 ") and "Modelo 720 (2026)" in first
    assert first.endswith("mié 31 mar")
