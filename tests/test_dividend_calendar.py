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


def test_fetch_ex_dividend_declares_a_rate_limit_it_swallows(monkeypatch):
    """Nothing comes back either way, but a cached "nothing declared" must be
    told apart from a throttled host — so the cooldown is tripped."""
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.fetch import clear_throttle, throttle_remaining

    def limited(_ticker):
        raise YFRateLimitError()

    monkeypatch.setattr("stocks.data.fetch.info", limited)
    clear_throttle()
    try:
        assert dv.fetch_ex_dividend("MSFT") == (None, None, None)
        assert throttle_remaining() > 0
    finally:
        clear_throttle()


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


# ------------------------------------------------------------------- history


class _FakeTicker:
    """Enough of yfinance.Ticker for fetch_history: a series and metadata."""

    def __init__(self, symbol: str):
        self.symbol = symbol

    @property
    def dividends(self):
        import pandas as pd

        idx = pd.to_datetime(["2025-03-14", "2025-06-13", "2025-09-12"])
        return pd.Series([0.51, 0.51, 0.0], index=idx)  # a 0 is not a payment

    @property
    def history_metadata(self):
        return {"currency": "usd"}


def test_fetch_history_reads_ex_dates_amounts_and_currency(monkeypatch):
    dv.clear_history_cache()
    monkeypatch.setattr("yfinance.Ticker", _FakeTicker)
    history = dv.fetch_history("KO")
    assert history.payments == (("2025-03-14", 0.51), ("2025-06-13", 0.51))
    assert history.currency == "USD"
    assert history.ticker == "KO"


def test_fetch_history_memoizes_and_never_asks_a_throttled_yahoo(monkeypatch):
    dv.clear_history_cache()
    built: list[str] = []

    class Counting(_FakeTicker):
        def __init__(self, symbol):
            built.append(symbol)
            super().__init__(symbol)

    monkeypatch.setattr("yfinance.Ticker", Counting)
    dv.fetch_history("KO")
    dv.fetch_history("KO")
    assert built == ["KO"]  # second read came from the memo

    from stocks.data.fetch import clear_throttle, trip_throttle

    dv.clear_history_cache()
    built.clear()
    trip_throttle()
    try:
        assert dv.fetch_history("KO").payments == ()
        assert built == []  # the cooldown is respected without a request
    finally:
        clear_throttle()


def test_fetch_history_swallows_a_dead_symbol(monkeypatch):
    dv.clear_history_cache()

    class Broken:
        def __init__(self, symbol):
            raise ValueError("no such ticker")

    monkeypatch.setattr("yfinance.Ticker", Broken)
    assert dv.fetch_history("NOPE") == dv.DividendHistory("NOPE")


def test_histories_drops_the_names_with_nothing_to_estimate_from(monkeypatch):
    dv.clear_history_cache()

    def fake(ticker: str):
        if ticker == "KO":
            return dv.DividendHistory("KO", (("2025-03-14", 0.51),), "USD")
        return dv.DividendHistory(ticker)

    monkeypatch.setattr(dv, "fetch_history", fake)
    assert list(dv.histories(["KO", "NVDA", "KO"])) == ["KO"]
    assert dv.histories([]) == {}


# ---------------------------------------------------------------- projection

PROJ_REF = date(2026, 10, 2)  # a Friday


def _history(*rows: tuple[int, float]) -> dv.DividendHistory:
    """Payments `days` before PROJ_REF, oldest first."""
    from datetime import timedelta

    return dv.DividendHistory(
        "KO",
        tuple(
            ((PROJ_REF - timedelta(days=d)).isoformat(), a)
            for d, a in sorted(rows, reverse=True)
        ),
        "USD",
    )


def test_a_quarterly_payer_repeats_last_year_on_the_same_weekday():
    history = _history((300, 0.51), (209, 0.51), (118, 0.51), (27, 0.53))
    events = dv.project(history, PROJ_REF)
    assert [e.days_until for e in events] == [64, 155, 246, 337]
    # 364 days, not a calendar year: the weekday the company used survives.
    paid = [date.fromisoformat(day) for day, _ in history.payments]
    assert [e.ex_date.weekday() for e in events] == [d.weekday() for d in paid]
    # Even payers step up: the latest rate stands for every slot.
    assert {e.per_share for e in events} == {0.53}
    assert {e.currency for e in events} == {"USD"}


def test_an_interim_and_a_final_keep_their_own_amounts():
    events = dv.project(_history((250, 0.40), (70, 1.10)), PROJ_REF)
    assert [(e.days_until, e.per_share) for e in events] == [(114, 0.40), (294, 1.10)]


def test_a_special_dividend_is_not_a_slot():
    history = _history((300, 0.5), (209, 0.5), (150, 3.0), (118, 0.5), (27, 0.5))
    events = dv.project(history, PROJ_REF)
    assert len(events) == 4 and all(e.per_share == 0.5 for e in events)


def test_a_payer_gone_quiet_is_not_promised_a_date():
    # Quarterly until five months ago, then nothing: suspended, or late.
    assert dv.project(_history((330, 0.5), (240, 0.5), (150, 0.5)), PROJ_REF) == []
    assert dv.project(_history((400, 0.5)), PROJ_REF) == []
    assert dv.project(dv.DividendHistory("KO"), PROJ_REF) == []


def test_a_declared_date_stands_in_for_the_guess_next_to_it():
    from datetime import timedelta

    history = _history((300, 0.51), (209, 0.51), (118, 0.51), (27, 0.53))
    declared = [PROJ_REF + timedelta(days=60)]
    events = dv.project(history, PROJ_REF, declared)
    assert [e.days_until for e in events] == [155, 246, 337]


def test_a_slot_that_drifted_past_the_year_s_edge_is_not_drawn_twice():
    # Five payments inside 52 weeks: the oldest is this quarter's, paid a few
    # days later last year — its guess lands next to the one just paid.
    history = _history((362, 0.5), (272, 0.5), (181, 0.5), (90, 0.5), (1, 0.5))
    events = dv.project(history, PROJ_REF)
    assert all(e.days_until > 30 for e in events)
