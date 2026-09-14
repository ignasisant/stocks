"""Forward-looking ex-dividend calendar (stocks.data.dividends)."""

from __future__ import annotations

from datetime import date

from stocks.data import dividends as dv

REF = date(2026, 8, 14)  # a Friday


def test_build_events_keeps_only_the_window_soonest_first():
    raw = {
        "MSFT": (date(2026, 8, 20), 0.83, "USD"),
        "KO": (date(2026, 8, 16), 0.51, "USD"),
        "PG": (date(2026, 9, 30), 1.05, "USD"),   # beyond the window
        "JNJ": (date(2026, 8, 1), 1.24, "USD"),   # already gone ex
        "NVDA": (None, None, None),               # no known date
    }
    events = dv.build_events(raw, REF, within_days=7)
    assert [e.ticker for e in events] == ["KO", "MSFT"]
    assert [e.days_until for e in events] == [2, 6]
    assert events[0].per_share == 0.51 and events[0].currency == "USD"


def test_build_events_keeps_today_and_is_deterministic_on_ties():
    raw = {
        "B": (REF, 0.10, "EUR"),
        "A": (REF, 0.20, "EUR"),
    }
    events = dv.build_events(raw, REF, within_days=7)
    # An ex-date of today has not been missed — the position still qualifies.
    assert [e.ticker for e in events] == ["A", "B"]
    assert all(e.days_until == 0 for e in events)


def test_event_cash_scales_by_quantity_and_survives_an_unknown_amount():
    known = dv.DividendEvent("KO", REF, 0, per_share=0.51, currency="USD")
    assert known.cash(120) == 61.2
    unknown = dv.DividendEvent("KO", REF, 0, per_share=None, currency="USD")
    assert unknown.cash(120) is None


def test_epoch_date_parses_and_rejects():
    assert dv._epoch_date(1_755_129_600) == date(2025, 8, 14)
    for bad in (None, "", "soon", 0, -1, float("nan")):
        assert dv._epoch_date(bad) is None


def test_positive_float_rejects_zero_and_junk():
    assert dv._positive_float("0.83") == 0.83
    for bad in (None, "", "n/a", 0, -0.5):
        assert dv._positive_float(bad) is None


def test_fetch_ex_dividend_skips_crypto_without_a_quote(monkeypatch):
    """A coin has no ex-date, and asking Yahoo for one is a wasted round trip
    on every digest a crypto holder receives."""
    def boom(_ticker):
        raise AssertionError("should not have fetched")

    monkeypatch.setattr("stocks.data.fetch.info", boom)
    assert dv.fetch_ex_dividend("BTC-EUR") == (None, None, None)


def test_fetch_ex_dividend_swallows_a_dead_symbol(monkeypatch):
    def boom(_ticker):
        raise RuntimeError("throttled")

    monkeypatch.setattr("stocks.data.fetch.info", boom)
    assert dv.fetch_ex_dividend("NOPE") == (None, None, None)


def test_fetch_ex_dividend_reads_the_quote_blob(monkeypatch):
    monkeypatch.setattr(
        "stocks.data.fetch.info",
        lambda t: {
            "exDividendDate": 1_755_129_600,
            "lastDividendValue": 0.83,
            "currency": "usd",
        },
    )
    assert dv.fetch_ex_dividend("MSFT") == (date(2025, 8, 14), 0.83, "USD")


def test_upcoming_ex_dividends_deduplicates_and_needs_no_network_when_empty(
    monkeypatch,
):
    calls: list[str] = []

    def fake(ticker: str):
        calls.append(ticker)
        return date(2026, 8, 18), 0.25, "EUR"

    monkeypatch.setattr(dv, "fetch_ex_dividend", fake)
    events = dv.upcoming_ex_dividends(["KO", "KO", "MSFT"], ref=REF)
    assert sorted(calls) == ["KO", "MSFT"]
    assert [e.ticker for e in events] == ["KO", "MSFT"]

    calls.clear()
    assert dv.upcoming_ex_dividends([], ref=REF) == [] and not calls
