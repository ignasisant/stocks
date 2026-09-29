"""The daily card's memory and its new context (stocks.chat.signals / daily).

The complaint this answers: the card said the same thing every morning — an
alert that fired weeks ago led it day after day. So what is tested here is
the card *not* repeating itself, and the calendars that give it something new
to say instead:

* a fired alert is an event for a few sessions, then a one-off "stale alert";
* a trigger already shown is held back until its figure moves, its phase
  advances or its cooldown runs out — and only what was actually shown counts;
* the Fed / ECB decision around the corner, and the one just taken;
* the tax calendar: a deadline, the year closing, the next bracket, a
  repurchase window letting go;
* the "see more" paragraphs, audited like the card.

Pure: no network, no clock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from stocks.chat import daily, signals
from stocks.config import Alert, Holding
from stocks.data import macro_calendar
from stocks.portfolio import tax
from stocks.portfolio.positions import RealizedSale

TODAY = date(2026, 9, 29)  # a Tuesday


def positions(**over) -> pd.DataFrame:
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


def sale(ticker: str, gain: float, sell_date: str) -> RealizedSale:
    return RealizedSale(
        ticker=ticker, buy_date="2024-01-05", sell_date=sell_date, quantity=5,
        cost=1000.0, proceeds=1000.0 + gain, currency="EUR",
    )


def aapl_alert(closes: list[float]) -> list[signals.Signal]:
    return signals.candidates(
        holdings=[Holding("AAPL", alerts=[Alert("above", price=260.0)])],
        closes={"AAPL": closes},
        today=TODAY,
    )


def remembered(*signals_: signals.Signal, last: date) -> dict:
    """`shown` as a card stored on `last` would have left it."""
    return {
        s.key: {"last": last.isoformat(), "run": 1, "v": signals.measure(s.kind, s.data)}
        for s in signals_
    }


# ------------------------------------------------------------ alerts, by age


def test_an_alert_that_just_crossed_is_an_event_with_its_age():
    (hit,) = aapl_alert([250.0, 255.0, 262.0, 265.0])
    assert hit.kind == signals.ALERT_HIT and hit.data["sessions"] == 2


def test_an_alert_past_its_level_for_weeks_is_a_stale_alert_not_news():
    (stale,) = aapl_alert([250.0] + [265.0] * 20)
    assert stale.kind == signals.ALERT_STALE and stale.data["sessions"] == 20
    assert stale.urgency < signals._URGENCY[signals.ALERT_HIT]


def test_the_crossing_already_shown_is_not_shown_again():
    """The bug that started this: AAPL above 260 led every card."""
    (hit,) = aapl_alert([250.0, 262.0])
    shown = remembered(hit, last=TODAY - timedelta(days=1))
    out = signals.candidates(
        holdings=[Holding("AAPL", alerts=[Alert("above", price=260.0)])],
        closes={"AAPL": [250.0, 262.0, 264.0]},
        shown=shown,
        today=TODAY,
    )
    assert out == []


def test_a_fresh_crossing_after_a_retreat_is_news_again():
    (hit,) = aapl_alert([262.0])
    shown = remembered(hit, last=TODAY - timedelta(days=8))
    out = signals.candidates(
        holdings=[Holding("AAPL", alerts=[Alert("above", price=260.0)])],
        # Crossed, fell back under, crossed again yesterday.
        closes={"AAPL": [262.0, 255.0, 250.0, 263.0]},
        shown=shown,
        today=TODAY,
    )
    assert [s.kind for s in out] == [signals.ALERT_HIT]


def test_moving_the_alert_makes_it_news():
    (hit,) = aapl_alert([250.0, 262.0])
    shown = remembered(hit, last=TODAY - timedelta(days=1))
    out = signals.candidates(
        holdings=[Holding("AAPL", alerts=[Alert("above", price=261.0)])],
        closes={"AAPL": [250.0, 262.0]},
        shown=shown,
        today=TODAY,
    )
    assert [s.kind for s in out] == [signals.ALERT_HIT]


def test_a_stale_alert_is_said_once_then_left_alone_for_its_cooldown():
    closes = [250.0] + [265.0] * 20
    (stale,) = aapl_alert(closes)
    kwargs = dict(
        holdings=[Holding("AAPL", alerts=[Alert("above", price=260.0)])],
        closes={"AAPL": closes},
    )
    week = remembered(stale, last=TODAY - timedelta(days=7))
    assert signals.candidates(**kwargs, shown=week, today=TODAY) == []
    month = remembered(stale, last=TODAY - timedelta(days=20))
    assert len(signals.candidates(**kwargs, shown=month, today=TODAY)) == 1


# --------------------------------------------------- repeats, by their figure


def test_an_unchanged_standing_trigger_is_held_back_until_its_cooldown():
    (drawdown,) = [
        s for s in signals.candidates(tbl=positions(), today=TODAY)
        if s.kind == signals.DRAWDOWN
    ]
    shown = remembered(drawdown, last=TODAY - timedelta(days=2))
    out = signals.candidates(tbl=positions(), shown=shown, today=TODAY)
    assert signals.DRAWDOWN not in [s.kind for s in out]
    later = remembered(drawdown, last=TODAY - timedelta(days=11))
    out = signals.candidates(tbl=positions(), shown=later, today=TODAY)
    kinds = [s.kind for s in out]
    assert signals.DRAWDOWN in kinds


def test_a_standing_trigger_whose_figure_moved_is_back():
    (drawdown,) = [
        s for s in signals.candidates(tbl=positions(), today=TODAY)
        if s.kind == signals.DRAWDOWN
    ]
    shown = remembered(drawdown, last=TODAY - timedelta(days=2))
    deeper = positions(pnl=[3000.0, -3200.0], pnl_pct=[1.0, -0.40])
    kinds = [s.kind for s in signals.candidates(tbl=deeper, shown=shown, today=TODAY)]
    assert signals.DRAWDOWN in kinds


def test_regenerating_today_sees_the_same_triggers():
    """Memory stamped today must not empty today's own Regenerate."""
    first = signals.candidates(tbl=positions(), today=TODAY)
    shown = remembered(*first, last=TODAY)
    assert signals.candidates(tbl=positions(), shown=shown, today=TODAY) == first


class _Event:
    def __init__(self, ticker: str, when: date, today: date):
        self.ticker, self.date = ticker, when
        self.days_until = (when - today).days


def test_a_print_comes_back_only_when_its_phase_moves():
    prints = TODAY + timedelta(days=12)

    def card(on: date, shown=None) -> list[str]:
        out = signals.candidates(
            tbl=positions(), earnings=[_Event("ASML", prints, on)], shown=shown, today=on
        )
        return [s.kind for s in out]

    early = signals.candidates(
        tbl=positions(), earnings=[_Event("ASML", prints, TODAY)], today=TODAY
    )
    shown = remembered(*early, last=TODAY)
    assert signals.EARNINGS not in card(TODAY + timedelta(days=2), shown)  # still "week"
    assert signals.EARNINGS in card(TODAY + timedelta(days=8), shown)  # now "soon"


@dataclass
class _Result:
    ticker: str
    date: date
    eps_estimate: float | None
    reported_eps: float | None
    surprise_pct: float | None


def test_a_print_of_the_last_days_is_reported_against_its_estimate():
    out = signals.candidates(
        tbl=positions(),
        results=[
            _Result("NVDA", TODAY - timedelta(days=1), 1.10, 1.23, 11.8),
            _Result("ASML", TODAY - timedelta(days=20), 5.0, 5.1, 2.0),
        ],
        today=TODAY,
    )
    printed = [s for s in out if s.kind == signals.EARNINGS_RESULT]
    assert [s.ticker for s in printed] == ["NVDA"]
    assert printed[0].data["beat"] is True and printed[0].data["surprise_pct"] == 11.8


# ------------------------------------------------------------- the tax year


def test_a_filing_deadline_inside_a_month_is_a_line():
    out = signals.candidates(
        tbl=positions(), jurisdiction=tax.get("ES"), today=date(2026, 6, 20)
    )
    (due,) = [s for s in out if s.kind == signals.TAX_DEADLINE]
    assert due.data["deadline"] == "es_renta" and due.data["in_days"] == 10


def test_the_tax_year_closing_with_gains_booked_is_a_line():
    out = signals.candidates(
        tbl=positions(),
        realized=[sale("MSFT", 900.0, "2026-03-10")],
        jurisdiction=tax.get("ES"),
        today=date(2026, 11, 15),
    )
    (end,) = [s for s in out if s.kind == signals.TAX_YEAR_END]
    assert end.data["end"] == "2026-12-31" and end.data["gain_ytd"] == 900.0
    assert end.data["open_losses"] == 2400.0


def test_the_tax_year_follows_the_jurisdiction():
    assert signals._year_end(tax.get("UK"), date(2026, 3, 1)) == date(2026, 4, 5)
    assert signals._year_end(tax.get("ES"), date(2026, 3, 1)) == date(2026, 12, 31)


def test_the_next_savings_bracket_within_reach_is_a_line():
    out = signals.candidates(
        tbl=positions(),
        realized=[sale("MSFT", 5200.0, "2026-03-10")],
        jurisdiction=tax.get("ES"),
        today=TODAY,
    )
    (bracket,) = [s for s in out if s.kind == signals.TAX_BRACKET]
    assert bracket.data["room"] == 800.0 and bracket.data["next_rate_pct"] == 21.0


def test_a_bracket_far_away_or_in_another_currency_says_nothing():
    far = signals.candidates(
        tbl=positions(), realized=[sale("MSFT", 1500.0, "2026-03-10")],
        jurisdiction=tax.get("ES"), today=TODAY,
    )
    usd = signals.candidates(
        tbl=positions(), realized=[sale("MSFT", 5200.0, "2026-03-10")],
        jurisdiction=tax.get("ES"), currency="USD", today=TODAY,
    )
    assert signals.TAX_BRACKET not in [s.kind for s in far + usd]


def test_a_loss_sale_whose_window_lets_go_this_week_is_a_line():
    out = signals.candidates(
        tbl=positions(),
        realized=[sale("PYPL", -600.0, "2026-08-02")],
        jurisdiction=tax.get("ES"),
        today=TODAY,
    )
    (clear,) = [s for s in out if s.kind == signals.REPURCHASE_CLEAR]
    assert clear.ticker == "PYPL" and clear.data["clear_date"] == "2026-10-03"


def test_a_name_bought_back_has_no_window_to_wait_for():
    out = signals.candidates(
        tbl=positions(),
        realized=[sale("ASML", -600.0, "2026-08-02")],
        jurisdiction=tax.get("ES"),
        today=TODAY,
    )
    assert signals.REPURCHASE_CLEAR not in [s.kind for s in out]


def test_the_tax_lines_share_two_places_on_the_card():
    out = signals.candidates(
        tbl=positions(),
        realized=[sale("MSFT", 5200.0, "2026-03-10"), sale("PYPL", -600.0, "2026-10-12")],
        jurisdiction=tax.get("ES"),
        today=date(2026, 12, 10),
    )
    family = {signals.HARVEST, signals.TAX_DEADLINE, signals.TAX_YEAR_END,
              signals.TAX_BRACKET, signals.REPURCHASE_CLEAR}
    assert len([s for s in out if s.kind in family]) == 2


# --------------------------------------------------------- the central banks


def rate(*points: tuple[str, float]) -> pd.Series:
    return pd.Series(
        [v for _, v in points], index=pd.to_datetime([d for d, _ in points])
    )


def test_a_decision_inside_the_week_is_announced_with_the_rate():
    rates = {
        "DFEDTARL": rate(("2026-09-17", 3.75)),
        "DFEDTARU": rate(("2026-09-17", 4.0)),
    }
    (event,) = signals.macro_candidates(date(2026, 10, 23), rates, banks=("fed",))
    assert event.kind == signals.MACRO_EVENT and event.data["date"] == "2026-10-28"
    assert (event.data["rate_low"], event.data["rate"]) == (3.75, 4.0)


def test_a_cut_is_read_off_the_series_the_day_after():
    rates = {
        "DFEDTARL": rate(("2026-10-28", 3.75), ("2026-10-29", 3.5)),
        "DFEDTARU": rate(("2026-10-28", 4.0), ("2026-10-29", 3.75)),
    }
    (result,) = signals.macro_candidates(date(2026, 10, 30), rates, banks=("fed",))
    assert result.data["decision"] == "cut" and result.data["change_bp"] == -25


def test_an_ecb_hold_is_not_guessed_before_the_rate_would_move():
    rates = {"ECBDFR": rate(("2026-10-29", 2.0), ("2026-10-30", 2.0))}
    assert signals.macro_candidates(date(2026, 10, 31), rates, banks=("ecb",)) == []


def test_no_series_is_no_rate_line():
    assert signals.macro_candidates(date(2026, 10, 23), {}, banks=("fed",)) == []


def test_the_rate_series_is_only_wanted_near_a_decision():
    assert signals.macro_due("fed", date(2026, 10, 23))
    assert not signals.macro_due("fed", date(2026, 10, 10))


def test_the_calendars_cover_the_year_ahead():
    """Fails once a calendar runs out: add the next year's dates, read off the
    sources in stocks/data/macro_calendar.py."""
    ahead = date.today() + timedelta(days=200)
    for bank in (macro_calendar.FED, macro_calendar.ECB):
        assert macro_calendar.next_decision(bank, ahead) is not None, bank


def test_the_calendars_are_sorted_decision_days():
    for dates in macro_calendar.DECISIONS.values():
        assert list(dates) == sorted(set(dates))
        assert all(d.weekday() in (2, 3) for d in dates)  # Wednesday / Thursday


# ------------------------------------------------------ what the card stores


FACTS = {
    "date": TODAY.isoformat(),
    "currency": "EUR",
    "actions": [
        {"kind": "alert_hit", "ticker": "AAPL", "rule": "above", "level": 260.0,
         "price": 265.0, "held": True, "gap_pct": 1.92, "sessions": 1,
         "key": "alert_hit:AAPL"},
        {"kind": "earnings", "ticker": "NVDA", "in_days": 3, "date": "2026-10-02",
         "held": True, "phase": "soon", "key": "earnings:NVDA"},
        {"kind": "macro_event", "ticker": "", "bank": "fed", "date": "2026-10-28",
         "in_days": 6, "rate": 4.0, "rate_low": 3.75, "phase": "week",
         "key": "macro_event:fed"},
    ],
}


def test_the_model_ties_each_line_to_its_trigger():
    raw = json.dumps({
        "headline": "NVDA reports Friday, AAPL crossed your alert",
        "items": [
            {"key": "earnings:NVDA", "line": "NVDA reports in 3 days: decide first"},
            {"key": "made-up", "line": "AAPL crossed your 260 alert, now 265"},
        ],
    })
    card = daily.parse(raw, day=TODAY, lang="en", known={"AAPL", "NVDA"}, facts=FACTS)
    assert [i["key"] for i in card.items] == ["earnings:NVDA", "alert_hit:AAPL"]
    assert card.bullets == [i["line"] for i in card.items]
    assert card.focus == ["NVDA", "AAPL"]


def test_one_line_is_a_card():
    item = {"key": "earnings:NVDA", "line": "NVDA reports"}
    raw = json.dumps({"headline": "h", "items": [item]})
    assert daily.parse(raw, day=TODAY, lang="en", facts=FACTS) is not None


def test_only_what_the_card_showed_is_remembered():
    raw = json.dumps({
        "headline": "NVDA reports Friday",
        "items": [{"key": "earnings:NVDA", "line": "NVDA reports in 3 days"}],
    })
    card = daily.parse(raw, day=TODAY, lang="en", facts=FACTS)
    stored = daily.to_store(None, card, FACTS)
    assert set(stored["shown"]) == {"earnings:NVDA"}
    measured = stored["shown"]["earnings:NVDA"]["v"]
    assert measured == {"date": "2026-10-02", "phase": "soon"}
    line = {
        "day": TODAY.isoformat(), "key": "earnings:NVDA", "line": "NVDA reports in 3 days"
    }
    assert stored["past"] == [line]


def test_a_computed_card_is_remembered_and_counted():
    card = daily.computed(FACTS, "en", TODAY)
    first = daily.DailyAction.from_dict(daily.to_store(None, card, FACTS))
    assert set(first.shown) == {"alert_hit:AAPL", "earnings:NVDA", "macro_event:fed"}
    again = daily.DailyAction.from_dict(daily.to_store(first, card, FACTS))
    assert again.tries == 2
    # Same day, stamped again: the run is not extended by a second write.
    assert again.shown["earnings:NVDA"]["run"] == 1


def test_a_written_card_is_never_up_for_replacement():
    card = daily.DailyAction(day=TODAY.isoformat(), headline="h", bullets=["a"])
    assert not daily.wants_upgrade(card, now=card.generated + 10**6)


def test_the_stand_in_gives_up_after_its_tries():
    card = daily.DailyAction(
        day=TODAY.isoformat(), headline="h", bullets=["a"], source="computed",
        tries=daily.UPGRADE_TRIES,
    )
    assert not daily.wants_upgrade(card, now=10**9)


def test_previous_days_lines_reach_the_prompt_but_not_the_audit():
    past = [
        {"day": "2026-09-28", "key": "alert_hit:AAPL", "line": "AAPL +7.5% past 260"},
        {"day": TODAY.isoformat(), "key": "x", "line": "today's own"},
    ]
    system, messages = daily.prompt(FACTS, {}, "en", past=past)
    assert "AAPL +7.5% past 260" in system and "today's own" not in system
    assert "7.5" not in messages[0]["content"]
    assert daily.audit(["AAPL is up 7.5%"], FACTS) == "7.5%"


def test_the_computed_headline_names_the_day_and_is_never_cut_mid_word():
    card = daily.computed(FACTS, "en", TODAY)
    assert card.headline.startswith("AAPL: alert fired · NVDA reports in 3 days")
    assert len(card.headline) <= daily.HEADLINE_CHARS
    assert not card.headline.endswith(("…", " "))
    assert len(card.items) == 3


def test_a_long_line_is_clipped_at_a_word():
    clipped = daily._clip("word " * 40, 30)
    assert len(clipped) <= 30 and clipped.endswith("word…")


# ---------------------------------------------------------------- see more


def stored_card() -> daily.DailyAction:
    card = daily.computed(FACTS, "en", TODAY)
    return daily.DailyAction.from_dict(daily.to_store(None, card, FACTS))


def test_every_line_with_a_trigger_has_a_computed_paragraph():
    for lang in ("en", "es"):
        texts = daily.detail_computed(stored_card(), {}, lang)
        assert set(texts) == {"alert_hit:AAPL", "earnings:NVDA", "macro_event:fed"}
        assert all(len(t) > 60 for t in texts.values())


def test_a_paragraph_with_an_invented_figure_is_dropped_alone():
    card = stored_card()
    raw = json.dumps({"details": [
        {"key": "earnings:NVDA", "text": "NVDA reports on Friday; decide first."},
        {"key": "alert_hit:AAPL", "text": "AAPL is up 12.3% since the cross."},
    ]})
    assert daily.parse_detail(raw, card, {}, "en") == {
        "earnings:NVDA": "NVDA reports on Friday; decide first."
    }


def test_the_press_release_figures_may_be_quoted():
    card = stored_card()
    release = "Revenue of $96.2 billion, up 106% from a year ago."
    sources = {"earnings:NVDA": {
        "ticker": "NVDA", "release": release, "release_figures": daily.figures(release),
    }}
    raw = json.dumps({"details": [
        {"key": "earnings:NVDA",
         "text": "Last quarter NVDA grew revenue 106% to $96.2 billion."},
    ]})
    assert daily.parse_detail(raw, card, sources, "en")
    assert daily.parse_detail(raw, card, {}, "en") is None


def test_the_detail_prompt_carries_each_line_with_its_action_and_source():
    card = stored_card()
    system, messages = daily.detail_prompt(
        card, {"macro_event:fed": {"bank": "fed", "history": []}}, {}, "es"
    )
    payload = json.loads(messages[0]["content"])
    keyed = {line["key"]: line for line in payload["lines"]}
    assert keyed["macro_event:fed"]["source"] == {"bank": "fed", "history": []}
    assert keyed["earnings:NVDA"]["action"]["in_days"] == 3
    assert "Spanish" in system
