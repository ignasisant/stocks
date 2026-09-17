"""Candidate actions for the daily card (stocks.chat.signals).

These are the triggers the card is allowed to talk about, so what matters is
that each one only fires when the book really justifies it: an alert level the
user set, a loss with a booked gain behind it, a print close enough to decide
before. Everything here is pure — no frame is fetched, no clock is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import pytest

from stocks.chat import signals
from stocks.config import Alert, Holding
from stocks.portfolio import tax
from stocks.portfolio.positions import RealizedSale

TODAY = date(2026, 9, 3)


@dataclass
class Event:
    ticker: str
    date: date
    days_until: int


def positions(**over) -> pd.DataFrame:
    """Two positions: NVDA up and heavy, ASML deep under cost."""
    frame = pd.DataFrame(
        {
            "shares": [10.0, 20.0],
            "ccy": ["USD", "EUR"],
            "cost": [3000.0, 8000.0],
            "value": [6000.0, 5600.0],
            "pnl": [3000.0, -2400.0],
            "pnl_pct": [1.0, -0.30],
            "weight": [0.52, 0.48],
        },
        index=["NVDA", "ASML"],
    )
    for col, values in over.items():
        frame[col] = values
    return frame


def sale(gain: float, sell_date: str = "2026-03-10") -> RealizedSale:
    return RealizedSale(
        ticker="MSFT", buy_date="2024-01-05", sell_date=sell_date, quantity=5,
        cost=1000.0, proceeds=1000.0 + gain, currency="EUR",
    )


# ------------------------------------------------------------ user's alerts


def test_a_fired_price_alert_is_the_top_action():
    holdings = [Holding("ASML", alerts=[Alert("below", price=300.0)])]
    out = signals.candidates(
        holdings=holdings, closes={"ASML": [305.0, 280.0]}, today=TODAY
    )
    assert [s.kind for s in out] == [signals.ALERT_HIT]
    assert out[0].data["level"] == 300.0 and out[0].data["price"] == 280.0
    assert out[0].data["rule"] == "below"


def test_an_alert_within_reach_is_a_softer_action():
    holdings = [Holding("ASML", alerts=[Alert("below", price=300.0)])]
    out = signals.candidates(
        holdings=holdings, closes={"ASML": [320.0, 306.0]}, today=TODAY
    )
    assert out[0].kind == signals.ALERT_NEAR
    assert out[0].data["gap_pct"] == pytest.approx(2.0)


def test_a_distant_alert_says_nothing():
    holdings = [Holding("ASML", alerts=[Alert("below", price=200.0)])]
    out = signals.candidates(
        holdings=holdings, closes={"ASML": [320.0, 306.0]}, today=TODAY
    )
    assert out == []


def test_history_based_alerts_are_left_to_the_notification_path():
    """drawdown/RSI/SMA rules need a full price history — a fetch this card
    does not make."""
    holdings = [Holding("ASML", alerts=[Alert("drawdown", pct=20.0)])]
    out = signals.candidates(
        holdings=holdings, closes={"ASML": [320.0, 306.0]}, today=TODAY
    )
    assert out == []


def test_an_unpriced_ticker_raises_nothing():
    holdings = [Holding("ZZZZ", alerts=[Alert("below", price=10.0)])]
    assert signals.candidates(holdings=holdings, closes={}, today=TODAY) == []


# ---------------------------------------------------------------- the ledger


def test_a_deep_drawdown_asks_for_a_thesis_review():
    out = signals.candidates(tbl=positions(), today=TODAY)
    kinds = {s.kind: s for s in out}
    assert kinds[signals.DRAWDOWN].ticker == "ASML"
    assert kinds[signals.DRAWDOWN].data["pnl_pct"] == -30.0


def test_concentration_fires_on_the_heavy_name_only():
    book = positions(weight=[0.52, 0.28])
    out = [s for s in signals.candidates(tbl=book, today=TODAY)
           if s.kind == signals.CONCENTRATION]
    assert [s.ticker for s in out] == ["NVDA"]
    assert out[0].data["weight_pct"] == 52.0


def test_harvest_needs_a_booked_gain_to_offset():
    """An open loss on its own is a fact the P/L column already shows; it
    becomes an action only against a realised gain."""
    assert not [
        s for s in signals.candidates(tbl=positions(), realized=[], today=TODAY)
        if s.kind == signals.HARVEST
    ]
    out = [
        s for s in signals.candidates(
            tbl=positions(), realized=[sale(900.0)],
            jurisdiction=tax.get("ES"), today=TODAY,
        )
        if s.kind == signals.HARVEST
    ]
    assert len(out) == 1 and out[0].ticker == "ASML"
    assert out[0].data == {
        "loss": 2400.0, "gain_ytd": 900.0, "offset": 900.0, "pnl_pct": -30.0,
        "currency": "EUR", "jurisdiction": "ES", "repurchase_window": "2m",
    }


def test_a_net_realised_loss_is_not_a_harvest_case():
    out = signals.candidates(
        tbl=positions(), realized=[sale(900.0), sale(-1500.0)],
        jurisdiction=tax.get("ES"), today=TODAY,
    )
    assert not [s for s in out if s.kind == signals.HARVEST]


def test_a_trivial_loss_is_not_worth_an_action():
    small = positions(pnl=[3000.0, -80.0])
    out = signals.candidates(
        tbl=small, realized=[sale(900.0)], jurisdiction=tax.get("ES"), today=TODAY
    )
    assert not [s for s in out if s.kind == signals.HARVEST]


def test_the_tax_year_boundary_follows_the_jurisdiction():
    """A 10 May 2026 disposal is the 2026/27 year in the UK and 2026 in Spain,
    so the same book offers different gains to offset."""
    may = [sale(900.0, "2026-05-10")]
    assert signals.realized_this_year(may, tax.get("UK"), TODAY) == 900.0
    assert signals.realized_this_year(may, tax.get("ES"), TODAY) == 900.0
    april = [sale(900.0, "2026-04-01")]  # before 6 April: last UK year
    assert signals.realized_this_year(april, tax.get("UK"), TODAY) == 0.0
    assert signals.realized_this_year(april, tax.get("ES"), TODAY) == 900.0


def test_no_jurisdiction_falls_back_to_the_calendar_year():
    assert signals.realized_this_year([sale(500.0)], None, TODAY) == 500.0
    assert signals.realized_this_year([sale(500.0, "2025-12-30")], None, TODAY) == 0.0


# ------------------------------------------------------------ calendar, price


def test_a_print_on_a_held_name_is_a_decision_date():
    out = [s for s in signals.candidates(
        tbl=positions(), earnings=[Event("ASML", date(2026, 9, 5), 2)], today=TODAY
    ) if s.kind == signals.EARNINGS]
    assert out[0].data["in_days"] == 2
    # Sooner sorts higher: tomorrow's print outranks Friday's.
    both = signals.candidates(
        tbl=positions(),
        earnings=[Event("ASML", date(2026, 9, 7), 4), Event("NVDA", date(2026, 9, 4), 1)],
        today=TODAY,
    )
    prints = [s.ticker for s in both if s.kind == signals.EARNINGS]
    assert prints == ["NVDA", "ASML"]


def test_a_print_on_a_name_you_do_not_hold_is_only_news():
    out = signals.candidates(
        tbl=positions(), earnings=[Event("TSLA", date(2026, 9, 5), 2)], today=TODAY
    )
    assert not [s for s in out if s.kind == signals.EARNINGS]


def test_a_watchlist_name_at_its_low_is_an_entry_case():
    out = [s for s in signals.candidates(
        tbl=positions(), extremes=[("TSLA", 180.0, "low", -0.012)], today=TODAY
    ) if s.kind == signals.LOW_52W]
    assert out[0].ticker == "TSLA" and out[0].data["gap_pct"] == 1.2


def test_a_held_name_at_its_low_is_left_to_the_drawdown_line():
    out = signals.candidates(
        tbl=positions(), extremes=[("ASML", 180.0, "low", -0.01)], today=TODAY
    )
    assert not [s for s in out if s.kind == signals.LOW_52W]


def test_a_52_week_high_is_not_an_action():
    out = signals.candidates(
        tbl=positions(), extremes=[("TSLA", 180.0, "high", None)], today=TODAY
    )
    assert out == [s for s in out if s.kind != signals.LOW_52W]


# ------------------------------------------------------------------ the set


def test_urgency_order_and_cap():
    out = signals.candidates(
        holdings=[Holding("ASML", alerts=[Alert("below", price=300.0)])],
        closes={"ASML": [305.0, 280.0]},
        tbl=positions(),
        realized=[sale(900.0)],
        jurisdiction=tax.get("ES"),
        earnings=[Event("ASML", date(2026, 9, 5), 2)],
        today=TODAY,
        limit=3,
    )
    assert [s.kind for s in out] == [
        signals.ALERT_HIT, signals.HARVEST, signals.EARNINGS
    ]


def test_an_empty_book_raises_no_actions():
    assert signals.candidates(tbl=pd.DataFrame(), today=TODAY) == []


# ----------------------------------------------------- rotation: caps and decay


def harvests(*tickers: str) -> list[signals.Signal]:
    """One harvest candidate per ticker — the shape a book of losers raises."""
    return [
        signals.Signal(signals.HARVEST, t, signals._URGENCY[signals.HARVEST],
                       {"loss": 900.0, "gain_ytd": 2000.0, "offset": 900.0})
        for t in tickers
    ]


def test_one_crowded_kind_cannot_take_the_whole_card():
    """The complaint this cap exists for: five losing positions and a booked
    gain used to produce five harvest lines and nothing else."""
    out = signals.candidates(
        market=[
            *harvests("AAA", "BBB", "CCC", "DDD", "EEE"),
            signals.Signal(signals.DRAWDOWN, "ZZZ", 55, {"pnl_pct": -31.0}),
            signals.Signal(signals.MARKET, "", 58, {"index": "S&P 500"}),
        ],
        today=TODAY,
    )
    kinds = [s.kind for s in out]
    assert kinds.count(signals.HARVEST) == 1
    assert {signals.MARKET, signals.DRAWDOWN} <= set(kinds)


def test_a_trigger_offered_for_days_sinks_below_a_fresh_one():
    shown = {"harvest:AAA": {"last": "2026-09-02", "run": 3}}
    out = signals.candidates(
        market=[
            *harvests("AAA"),
            signals.Signal(signals.DRAWDOWN, "ZZZ", 55, {"pnl_pct": -31.0}),
        ],
        shown=shown,
        today=TODAY,
    )
    # Harvest starts above drawdown (75 against 55) and ends under it.
    assert [s.kind for s in out] == [signals.DRAWDOWN, signals.HARVEST]


def test_an_event_never_decays():
    """A fired alert is today's news however long the level has been near."""
    alert = signals.Signal(signals.ALERT_HIT, "NVDA", 90, {"level": 150.0})
    shown = {"alert_hit:NVDA": {"last": "2026-09-02", "run": 9}}
    assert signals.decay(alert, shown, TODAY) == 90


def test_a_streak_that_stopped_is_forgotten():
    old = {"harvest:AAA": {"last": "2026-08-01", "run": 5}}
    assert signals.decay(harvests("AAA")[0], old, TODAY) == 75


def test_decay_stops_at_its_floor():
    forever = {"harvest:AAA": {"last": "2026-09-02", "run": 40}}
    assert signals.decay(harvests("AAA")[0], forever, TODAY) == 75 - signals.DECAY_MAX


def test_an_unreadable_memory_is_no_memory():
    for junk in ({"harvest:AAA": "yesterday"}, {"harvest:AAA": {"last": "nope"}}):
        assert signals.decay(harvests("AAA")[0], junk, TODAY) == 75


# ------------------------------------------------- the market, against the book


SESSIONS = pd.bdate_range("2024-01-01", periods=520)


def line(start: float, end: float, tail: tuple[float, float] | None = None):
    """A straight price series, optionally with a different last month glued on
    — enough shape for a trend, a drawdown and a monthly return."""
    import numpy as np

    s = pd.Series(np.linspace(start, end, len(SESSIONS)), index=SESSIONS)
    if tail:
        s.iloc[-25:] = np.linspace(*tail, 25)
    return s


def market_closes(**over):
    """SPY plus the eleven sector ETFs, all quietly rising unless overridden."""
    from stocks.analysis import sentiment as sm

    closes = {"SPY": line(400, 460), "EURUSD=X": line(1.10, 1.12)}
    closes |= {etf: line(100, 120) for etf in sm.SECTOR_ETFS.values()}
    return closes | over


def test_a_quiet_market_making_highs_says_nothing():
    """The card refuses to be a market summary: a broad market in an uptrend
    is not something the reader has to do anything about."""
    assert signals.market_candidates(market_closes()) == []


def test_an_index_off_its_high_is_the_backdrop():
    out = signals.market_candidates(market_closes(SPY=line(400, 460, (460, 400))))
    assert [s.kind for s in out] == [signals.MARKET]
    data = out[0].data
    assert data["trend"] == "down" and data["from_high_pct"] < -signals.INDEX_DIP_PCT
    assert data["sectors_read"] == 11


def test_a_narrow_market_fires_on_breadth_alone():
    """The index itself is fine; most sectors are not. That gap is the reading
    the index level cannot give on its own."""
    from stocks.analysis import sentiment as sm

    sagging = {etf: line(100, 80) for etf in list(sm.SECTOR_ETFS.values())[:8]}
    out = signals.market_candidates(market_closes(**sagging))
    assert [s.kind for s in out] == [signals.MARKET]
    assert out[0].data["breadth_pct"] < signals.BREADTH_LOW_PCT


def test_the_largest_sector_bet_is_one_line_with_its_month():
    out = signals.market_candidates(
        market_closes(),
        book_sectors=pd.Series({"Technology": 0.55, "Energy": 0.45}),
        bench_sectors={"Technology": 0.32, "Energy": 0.04, "Utilities": 0.08},
    )
    tilt = [s for s in out if s.kind == signals.SECTOR_TILT]
    assert len(tilt) == 1
    assert tilt[0].data["sector"] == "Energy"  # +41pp beats Technology's +23
    assert tilt[0].data["excess_month_pct"] is not None
    assert tilt[0].key == "sector_tilt:Energy"  # keyed on the bet, not a ticker


def test_a_sector_bet_inside_the_noise_is_not_a_bet():
    out = signals.market_candidates(
        market_closes(),
        book_sectors=pd.Series({"Technology": 0.35, "Energy": 0.65}),
        bench_sectors={"Technology": 0.32, "Energy": 0.60},
    )
    assert not [s for s in out if s.kind == signals.SECTOR_TILT]


def test_the_unreadable_buckets_are_not_a_sector_bet():
    """"Unknown" is a failed metadata lookup and crypto has no equity sector —
    neither is a decision the reader made."""
    out = signals.market_candidates(
        market_closes(),
        book_sectors=pd.Series({"Unknown": 0.6, "Crypto": 0.3, "Energy": 0.1}),
        bench_sectors={"Energy": 0.04, "Technology": 0.32},
    )
    assert not [s for s in out if s.kind == signals.SECTOR_TILT]


def test_the_book_beside_the_index_only_when_they_parted():
    apart = signals.market_candidates(
        market_closes(), book_month_pct=1.0, bench_month_pct=-6.0
    )
    gap = [s for s in apart if s.kind == signals.VS_BENCH]
    assert gap and gap[0].data["gap_pp"] == 7.0
    together = signals.market_candidates(
        market_closes(), book_month_pct=1.0, bench_month_pct=0.5
    )
    assert not [s for s in together if s.kind == signals.VS_BENCH]


def test_currency_counts_when_it_moved_and_the_book_is_exposed():
    moved = market_closes(**{"EURUSD=X": line(1.10, 1.12, (1.12, 1.06))})
    out = signals.market_candidates(
        moved, currency_weights=pd.Series({"USD": 0.72, "EUR": 0.28})
    )
    fx = [s for s in out if s.kind == signals.FX]
    assert fx and fx[0].data["currency"] == "USD"
    # EURUSD quotes dollars per euro: a falling pair is a RISING dollar, and
    # the sign of this number is the whole point of the line.
    assert fx[0].data["move_month_pct"] > 0
    assert fx[0].data["drag_month_pct"] > 0


def test_a_flat_month_is_not_a_currency_action():
    out = signals.market_candidates(
        market_closes(), currency_weights=pd.Series({"USD": 0.72, "EUR": 0.28})
    )
    assert not [s for s in out if s.kind == signals.FX]


def test_a_home_currency_book_carries_no_currency_line():
    moved = market_closes(**{"EURUSD=X": line(1.10, 1.12, (1.12, 1.06))})
    out = signals.market_candidates(
        moved, currency_weights=pd.Series({"EUR": 1.0})
    )
    assert not [s for s in out if s.kind == signals.FX]


def test_no_market_data_is_no_market_lines():
    """Yahoo throttles the hosted deploy routinely; the card degrades to the
    book's own triggers rather than to an error."""
    assert signals.market_candidates({}) == []
    assert signals.market_candidates(None, book_sectors=None) == []
