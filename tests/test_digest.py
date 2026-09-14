"""Daily digest builder (stocks.notify.digest)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from stocks.data.dividends import DividendEvent
from stocks.data.earnings import EarningsEvent
from stocks.notify import digest as dg

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


def test_render_full_digest_en():
    text = dg.render_digest(full_data(), "en")
    assert "<b>📊 TopStocks — daily digest</b> · Fri 14 Aug" in text
    assert "<b>Portfolio</b> €48,230" in text
    assert "Day +412 € (+0.86%)" in text
    assert "Week -1,105 € (-2.24%)" in text
    assert "▲ NVDA +3.2%" in text and "▼ UNH -2.8%" in text
    assert "• NVDA — Thu 20 Aug (T-6)" in text
    assert "💡 Nvidia drove most of today" in text


def test_render_spanish_labels():
    text = dg.render_digest(full_data(), "es")
    assert "resumen diario" in text
    assert "<b>Cartera</b>" in text
    assert "Día" in text and "Semana" in text
    assert "vie 14 ago" in text


def test_render_watchlist_only_omits_value_lines():
    data = dg.DigestData(date=D, watchlist_only=True,
                         movers=[("AAPL", 0.01)], earnings=[])
    text = dg.render_digest(data, "en")
    assert "Portfolio" not in text
    assert "▲ AAPL +1.0%" in text


def test_render_escapes_html_in_dynamic_text():
    data = dg.DigestData(date=D, movers=[("A&B<X>", 0.05)],
                         highlight="risk <on> & rising")
    text = dg.render_digest(data, "en")
    assert "A&amp;B&lt;X&gt;" in text
    assert "risk &lt;on&gt; &amp; rising" in text


def test_render_partial_sections_still_render():
    data = dg.DigestData(date=D, total=1000.0)  # no day/week/movers/earnings
    text = dg.render_digest(data, "en")
    assert "€1,000" in text
    assert "Top movers" not in text and "Earnings" not in text


def test_movers_capped_at_three_per_side():
    movers = [(f"G{i}", 0.01 * (10 - i)) for i in range(5)]
    movers += [(f"L{i}", -0.01 * (i + 1)) for i in range(5)]
    text = dg.render_digest(dg.DigestData(date=D, movers=movers), "en")
    assert text.count("▲") == 3 and text.count("▼") == 3


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
    monkeypatch.setattr(ap, "session_moves", lambda ts, max_workers=8: {"NVDA": 0.05})
    monkeypatch.setattr(dg, "calendar_events", lambda holdings: ([], []))

    data = dg.compute_digest_data(watchlist, db)
    assert data.watchlist_only is False
    assert data.total == 1000.0
    assert data.day == pytest.approx((50.0, 50.0 / 950.0))
    assert data.week == pytest.approx((100.0, 100.0 / 900.0))
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


def test_movers_are_ranked_by_money_not_percent():
    text = dg.render_digest(priced_data(), "en")
    gainers = text.split("Top movers")[1].splitlines()[1]
    # +9.0% on a small position must not outrank +3.2% on a large one.
    assert gainers.index("NVDA") < gainers.index("SMALL")
    assert "▲ NVDA +380 € (+3.2%)" in text
    assert "▼ UNH -180 € (-2.8%)" in text


def test_movers_fall_back_to_percent_ranking_without_a_book():
    """A watchlist has no weights, so the percentage is all there is."""
    data = dg.DigestData(date=D, watchlist_only=True,
                         movers=[("A", 0.01), ("B", 0.09)])
    text = dg.render_digest(data, "en")
    assert text.index("B +9.0%") < text.index("A +1.0%")
    assert "€" not in text


def test_ranked_movers_unions_quotes_and_values():
    """A quote that failed still moved the book; a name absent from the value
    frame still has a quote. Neither may drop out of the ranking."""
    data = dg.DigestData(date=D, movers=[("QUOTED", 0.02)],
                         contrib={"VALUED": 500.0})
    rows = dg.ranked_movers(data)
    assert {r[0] for r in rows} == {"QUOTED", "VALUED"}
    text = dg.render_digest(data, "en")
    assert "▲ VALUED +500 €" in text
    assert "▲ QUOTED +2.0%" in text  # no money figure to lead with


def test_money_movers_split_by_the_sign_of_the_money():
    """A name can be up on the day in percent and still be listed by its
    money — the sign that decides the list is the one being printed."""
    data = dg.DigestData(date=D, movers=[("A", 0.02)], contrib={"A": -50.0})
    text = dg.render_digest(data, "en")
    assert "▼ A -50 €" in text and "▲" not in text


# -------------------------------------------------------------- benchmark


def test_benchmark_line_reports_the_gap_both_ways():
    behind = dg.render_digest(priced_data(benchmark=(0.014, 0.02)), "en")
    assert "vs S&amp;P 500 +1.40% · behind by 0.54 pt" in behind
    ahead = dg.render_digest(priced_data(benchmark=(0.002, None)), "en")
    assert "vs S&amp;P 500 +0.20% · ahead by 0.66 pt" in ahead


def test_benchmark_line_omitted_when_incomparable():
    assert "S&amp;P" not in dg.render_digest(priced_data(benchmark=None), "en")
    assert "S&amp;P" not in dg.render_digest(
        priced_data(benchmark=(None, 0.02)), "en"
    )
    # No day change of our own to compare against.
    assert "S&amp;P" not in dg.render_digest(
        dg.DigestData(date=D, total=100.0, benchmark=(0.01, 0.01)), "en"
    )


def test_benchmark_line_is_translated():
    text = dg.render_digest(priced_data(benchmark=(0.014, None)), "es")
    assert "por detrás 0.54 pt" in text


# ------------------------------------------------------------- dividends


def test_dividend_section_shows_ex_dates_estimated_cash_and_receipts():
    data = priced_data(
        ex_dividends=[
            DividendEvent("KO", date(2026, 8, 16), 2, 0.51, "USD"),
            DividendEvent("MSFT", date(2026, 8, 20), 6, 0.83, "USD"),
        ],
        dividend_cash={"KO": 61.0},
        dividends_received=(124.0, 2),
    )
    text = dg.render_digest(data, "en")
    assert "<b>Dividends</b>" in text
    assert "• KO — ex-date Sun 16 Aug (T-2) · ~€61" in text
    assert "• MSFT — ex-date Thu 20 Aug (T-6)" in text
    assert "~€" not in text.split("MSFT")[1].splitlines()[0]  # no quantity held
    assert "€124 received over the last 7 days, from 2 payments" in text


def test_dividend_receipt_has_a_singular_form():
    data = priced_data(dividends_received=(38.0, 1))
    assert "from one payment" in dg.render_digest(data, "en")
    assert "de un pago" in dg.render_digest(data, "es")


def test_dividend_list_is_capped():
    events = [
        DividendEvent(f"T{i}", date(2026, 8, 15 + i), i + 1, 0.1, "EUR")
        for i in range(6)
    ]
    text = dg.render_digest(priced_data(ex_dividends=events), "en")
    assert text.count("ex-date") == dg.DIVIDENDS_SHOWN


# ------------------------------------------------------------- quiet days


def test_a_flat_empty_session_renders_short():
    data = dg.DigestData(date=D, total=48230.0, day=(12.0, 0.0002),
                         week=(-1105.0, -0.0224),
                         movers=[("NVDA", 0.001)],
                         contrib={"NVDA": 12.0},
                         highlight="should not be shown")
    assert data.quiet is True
    text = dg.render_digest(data, "en")
    assert "€48,230" in text and "Day +12 €" in text
    assert "Quiet session" in text
    assert "Top movers" not in text and "should not be shown" not in text


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


# ------------------------------------------------------- currency attribution


def test_fx_chip_appears_when_the_currency_explains_part_of_the_day():
    text = dg.render_digest(priced_data(fx_effect=-180.0), "en")
    assert "Day +412 € (+0.86%) · FX -180 €" in text
    assert "Divisa -180 €" in dg.render_digest(priced_data(fx_effect=-180.0), "es")


def test_fx_chip_hidden_when_it_is_rounding():
    """Below the floor the number is noise, and a line that shows up every
    evening is one the reader stops seeing on the evening it matters."""
    assert "FX" not in dg.render_digest(priced_data(fx_effect=12.0), "en")
    # Single-currency book: nothing computed at all.
    assert "FX" not in dg.render_digest(priced_data(fx_effect=None), "en")
    # A day that didn't move has no share to take.
    flat = dg.DigestData(date=D, total=100.0, day=(0.0, 0.0), fx_effect=5.0)
    assert "FX" not in dg.render_digest(flat, "en")


# --------------------------------------------------------- reported quarters


def _result(**over):
    from stocks.data.earnings import EarningsResult

    base = dict(ticker="NVDA", date=date(2026, 8, 13),
                eps_estimate=1.18, reported_eps=1.24, surprise_pct=5.1)
    base.update(over)
    return EarningsResult(**base)


def test_results_block_reads_beat_miss_eps_and_reaction():
    data = priced_data(results=[_result()], result_moves={"NVDA": 6.42})
    text = dg.render_digest(data, "en")
    assert "<b>Just reported</b>" in text
    assert "• NVDA — beat, EPS 1.24 vs 1.18 · +6.4%" in text


def test_results_degrade_to_whatever_is_known():
    no_eps = priced_data(results=[_result(eps_estimate=None, reported_eps=None,
                                          surprise_pct=-3.0)])
    assert "• NVDA — miss" in dg.render_digest(no_eps, "en")
    bare = priced_data(results=[_result(eps_estimate=None, reported_eps=None,
                                        surprise_pct=None)])
    assert "• NVDA\n" in dg.render_digest(bare, "en") + "\n"


def test_results_are_translated():
    data = priced_data(results=[_result()], result_moves={"NVDA": 6.42})
    text = dg.render_digest(data, "es")
    assert "Acaban de publicar" in text and "supera" in text


# ------------------------------------------------------------- import nudge


def test_stale_import_nudge_renders_with_the_age():
    text = dg.render_digest(priced_data(stale_import_days=63), "en")
    assert "📎 Your last statement import was 63 days ago" in text
    assert "the figures above may be out of date" in text
    assert "hace 63 días" in dg.render_digest(priced_data(stale_import_days=63), "es")


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


# ------------------------------------------------------------- deep links

ORIGIN = "https://topstocks.example"


def test_tickers_link_to_their_page_when_an_origin_is_configured():
    data = priced_data(
        ex_dividends=[DividendEvent("KO", date(2026, 8, 16), 2, 0.51, "USD")],
        results=[_result()],
        earnings=[EarningsEvent("ASML", date(2026, 8, 20), 6)],
    )
    text = dg.render_digest(data, "en", ORIGIN)
    for ticker in ("NVDA", "KO", "ASML"):
        assert f'<a href="{ORIGIN}/ticker?ticker={ticker}">{ticker}</a>' in text


def test_no_origin_renders_exactly_the_plain_message():
    data = priced_data(results=[_result()])
    assert dg.render_digest(data, "en") == dg.render_digest(data, "en", None)
    assert "<a href" not in dg.render_digest(data, "en")


def test_a_ticker_that_needs_escaping_survives_both_halves():
    """The symbol comes from a file the account controls and lands in both an
    href and a parse_mode='HTML' body."""
    text = dg.render_digest(
        dg.DigestData(date=D, movers=[("A&B", 0.05)]), "en", ORIGIN
    )
    assert "ticker=A%26B" in text and ">A&amp;B</a>" in text


def test_digest_buttons_follow_what_the_message_actually_says():
    plain = dg.digest_buttons(priced_data(), "en", ORIGIN)
    assert plain == [("Portfolio", f"{ORIGIN}/portfolio")]

    with_calendar = dg.digest_buttons(priced_data(results=[_result()]), "en", ORIGIN)
    assert [label for label, _ in with_calendar] == ["Portfolio", "Earnings"]

    nudged = dg.digest_buttons(priced_data(stale_import_days=63), "en", ORIGIN)
    assert nudged[-1] == ("Import statement", f"{ORIGIN}/import_transactions")


def test_digest_buttons_are_empty_without_an_origin(monkeypatch):
    monkeypatch.setattr(dg.links, "app_base", lambda: None)
    assert dg.digest_buttons(priced_data(stale_import_days=9), "en") == []


def test_digest_buttons_are_translated():
    labels = [
        label
        for label, _ in dg.digest_buttons(priced_data(results=[_result()]), "es", ORIGIN)
    ]
    assert labels == ["Cartera", "Resultados"]
