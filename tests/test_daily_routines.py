"""The daily card's sections (stocks.chat.daily, daily_book, daily_routines).

The card reads in four fixed sections — Portfolio, Today's alerts, Worth a
look, Your routines — and what is tested here is what each one promises:

* Portfolio is computed: the book's day, week and month against the index,
  only with the index in hand, and the month drawn from the same anchoring;
* every alert that fired is on the card, whatever the model wrote;
* a routine is answered from data fetched for it — the model's answer when
  it passes the audit, the computed one when it does not — and a routine
  whose data is still being fetched is shown unanswered, not as "no data";
* the card spends at most FREE_UNITS of the account's free allowance a day;
* the charts are attached after the card is built, never through the facts.

Pure: no network, no clock.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import pandas as pd

from stocks.chat import (
    charts,
    daily,
    daily_book,
    daily_routines,
    learnings,
    market,
    signals,
)

TODAY = date(2026, 9, 29)

INDEX = {
    "name": "S&P 500",
    "symbol": "SPY",
    "currency": "EUR",
    "as_of": "2026-09-28",
    "day_pct": 0.3,
    "week_pct": 1.1,
    "month_pct": None,
}

ALERT = {
    "kind": "alert_hit", "ticker": "AAPL", "rule": "above", "level": 260.0,
    "price": 265.0, "held": True, "gap_pct": 1.92, "sessions": 1,
    "key": "alert_hit:AAPL",
}
EARNINGS = {
    "kind": "earnings", "ticker": "NVDA", "in_days": 3, "date": "2026-10-02",
    "held": True, "phase": "soon", "key": "earnings:NVDA",
}


def book_facts(**over) -> dict:
    return {
        "date": TODAY.isoformat(),
        "currency": "EUR",
        "day": {"pct": 0.8, "amount": 120.0},
        "week": {"pct": 1.5, "amount": 220.0},
        "month": {"pct": -2.0, "amount": -300.0},
        "index": dict(INDEX),
        "actions": [dict(ALERT), dict(EARNINGS)],
    } | over


ROUTINES = [
    {
        "id": "r1",
        "ask": "how is NVDA doing",
        "quotes": [{"ticker": "NVDA", "price": 182.5, "currency": "USD",
                    "change_pct": 1.25}],
    },
    {"id": "r2", "ask": "is ASML above 700?"},
]


def daily_series(start: str, values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


# ------------------------------------------------------------- the portfolio


def test_a_window_is_anchored_as_the_basket_anchors_it():
    s = daily_series("2026-09-01", [100.0 + i for i in range(29)])  # to Sep 29
    assert daily_book.change(s, 1) == s.iloc[-1] / s.iloc[-2] - 1
    # The week opens on the last close at least seven calendar days back.
    assert daily_book.change(s, 7) == s.iloc[-1] / s.loc["2026-09-22"] - 1
    assert daily_book.change(s, 60) is None


def test_the_index_facts_carry_each_window(monkeypatch):
    s = daily_series("2026-08-20", [500.0 + i for i in range(41)])
    monkeypatch.setattr(daily_book, "index_series", lambda closes, ccy: (s, "EUR"))
    facts = daily_book.index_facts({}, "EUR")
    assert facts["name"] == "S&P 500" and facts["currency"] == "EUR"
    assert facts["as_of"] == s.index[-1].date().isoformat()
    assert facts["day_pct"] == round((540 / 539 - 1) * 100, 2)
    assert set(facts) >= {"week_pct", "month_pct"}


def test_no_index_means_no_section():
    assert daily_book.section(book_facts(index=None)) == {}
    assert daily_book.section(book_facts(index={})) == {}


def test_the_section_is_the_book_against_the_index():
    section = daily_book.section(book_facts())
    assert section["index"] == "S&P 500" and section["currency"] == "EUR"
    assert [r["window"] for r in section["rows"]] == ["day", "week", "month"]
    assert section["rows"][0] == {
        "window": "day", "pct": 0.8, "amount": 120.0, "index_pct": 0.3,
    }
    # The index's month did not download: the book's row stands without it.
    assert section["rows"][2]["index_pct"] is None


def test_a_watchlist_only_account_has_no_section():
    facts = book_facts(day={}, week={}, month={})
    assert daily_book.section(facts) == {}


def test_the_month_is_drawn_as_growth_from_its_first_day(monkeypatch):
    idx = pd.date_range("2026-08-20", "2026-09-29", freq="D")
    hist = pd.DataFrame(
        {"A": [100.0 + i for i in range(len(idx))],
         # Priced only from mid-window: summed over the names priced at both
         # ends, as basket_change sums them, so it is left out.
         "B": [None] * 20 + [50.0] * (len(idx) - 20)},
        index=idx,
    )
    spy = daily_series("2026-08-15", [400.0 + i for i in range(46)])
    monkeypatch.setattr(daily_book, "index_series", lambda closes, ccy: (spy, "EUR"))
    lines = daily_book.chart(hist, {}, "EUR", label="Your portfolio")
    book, index = lines
    assert book["symbol"] == daily_book.BOOK and book["label"] == "Your portfolio"
    assert book["values"][0] == 100.0
    start = hist["A"].loc["2026-08-30"]
    assert book["values"][-1] == round(hist["A"].iloc[-1] / start * 100, 4)
    assert book["index"] is True and index["index"] is True
    assert index["symbol"] == "SPY" and index["values"][0] == 100.0
    assert index["dates"][0] == book["dates"][0]


def test_no_history_draws_nothing():
    assert daily_book.chart(None, {}, "EUR") == []
    one = pd.DataFrame({"A": [1.0]}, index=pd.date_range("2026-09-29", periods=1))
    assert daily_book.chart(one, {}, "EUR") == []


def test_build_facts_drops_the_month_against_the_index_once_the_section_says_it():
    tbl = pd.DataFrame(
        {"value": [1000.0], "cost": [900.0], "pnl_pct": [0.11], "weight": [1.0],
         "day_pct": [0.01]},
        index=["NVDA"],
    )
    bench = signals.Signal(signals.VS_BENCH, "", 44, {"gap_pp": -3.4})
    without = daily.build_facts(tbl, signals=[bench], today=TODAY)
    assert [a["kind"] for a in without["actions"]] == [signals.VS_BENCH]
    month = dict(INDEX, month_pct=2.0)
    routines = daily_routines.seeded([learnings.Learning("r1", "how is NVDA",
                                                         kind="routine")])
    facts = daily.build_facts(tbl, signals=[bench], today=TODAY, index=month,
                              routines=routines)
    assert not facts.get("actions")
    assert facts["index"] == month
    assert facts["routines"] == [{"id": "r1", "ask": "how is NVDA", "pending": True}]


# ------------------------------------------------------------------ alerts


def test_an_alert_is_filed_under_alerts_and_the_rest_under_watch():
    assert daily.section_of(ALERT) == daily.ALERTS
    assert daily.section_of(EARNINGS) == daily.WATCH
    assert daily.section_of({"kind": "", "key": "line:0"}) == daily.WATCH


def test_a_fired_alert_the_model_left_out_is_on_the_card_first():
    raw = json.dumps({
        "headline": "NVDA reports Friday",
        "items": [{"key": "earnings:NVDA", "line": "NVDA reports in 3 days"}],
    })
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts())
    assert [i["key"] for i in card.items] == ["alert_hit:AAPL", "earnings:NVDA"]
    assert "AAPL" in card.items[0]["line"]


def test_an_alert_the_model_wrote_is_not_said_twice():
    raw = json.dumps({
        "headline": "AAPL crossed your 260 alert",
        "items": [
            {"key": "earnings:NVDA", "line": "NVDA reports in 3 days"},
            {"key": "alert_hit:AAPL", "line": "AAPL crossed 260, now 265"},
        ],
    })
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts())
    assert [i["key"] for i in card.items] == ["earnings:NVDA", "alert_hit:AAPL"]


def test_the_model_card_carries_the_computed_portfolio_section():
    raw = json.dumps({
        "headline": "Portfolio +0.8% vs S&P 500 +0.3%; NVDA reports Friday",
        "items": [{"key": "earnings:NVDA", "line": "NVDA reports in 3 days"}],
    })
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts())
    assert card.book == daily_book.section(book_facts())


def test_a_headline_misquoting_the_index_is_rejected():
    raw = json.dumps({
        "headline": "Portfolio +0.8% vs S&P 500 +0.9%",
        "items": [{"key": "earnings:NVDA", "line": "NVDA reports in 3 days"}],
    })
    assert daily.parse(raw, day=TODAY, lang="en", facts=book_facts()) is None


# ---------------------------------------------------------------- routines


def test_a_routine_is_answered_by_the_model_when_its_figures_are_sourced():
    raw = json.dumps({
        "headline": "NVDA reports Friday",
        "items": [{"key": "earnings:NVDA", "line": "NVDA reports in 3 days"}],
        "routines": [
            {"id": "r1", "answer": "NVDA is at 182.50, up 1.25% today."},
            # 640 is in no fact: the answer goes, the computed one stands in.
            {"id": "r2", "answer": "Not yet: ASML trades at 640, under 700."},
        ],
    })
    facts = book_facts(routines=ROUTINES)
    card = daily.parse(raw, day=TODAY, lang="en", facts=facts)
    assert card is not None  # one bad answer is not worth the card
    first, second = card.routines
    assert first == {"id": "r1", "text": "how is NVDA doing",
                     "answer": "NVDA is at 182.50, up 1.25% today.", "chart": None}
    assert second["answer"] == daily.routine_answer(ROUTINES[1], "en")
    assert "640" not in second["answer"]


def test_the_question_s_own_figures_count_as_sourced():
    raw = json.dumps({
        "headline": "NVDA reports Friday",
        "items": [{"key": "earnings:NVDA", "line": "NVDA reports in 3 days"}],
        "routines": [{"id": "r2", "answer": "No figure for ASML today against 700."}],
    })
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts(routines=ROUTINES))
    assert card.routines[1]["answer"] == "No figure for ASML today against 700."


def test_a_bare_price_is_audited_but_counts_names_and_years_are_not():
    facts = book_facts(routines=ROUTINES)
    assert daily._bare("NVDA at 182.50", facts) is None
    assert daily._bare("NVDA at 183.90", facts) == "183.90"
    assert daily._bare("NVDA at 640", facts) == "640"
    sourced = {**facts, "named": daily.figures(daily_book.INDEX_NAME)}
    assert daily._bare(
        "Up 3 months running, ahead of the S&P 500 in 2026; 7203.T and Q3 aside",
        sourced,
    ) is None


def test_a_routine_the_model_skipped_gets_the_computed_answer():
    card = daily.parse(
        json.dumps({"headline": "h", "items": [{"key": "earnings:NVDA", "line": "x"}]}),
        day=TODAY, lang="en", facts=book_facts(routines=ROUTINES),
    )
    assert card.routines[0]["answer"] == "NVDA at 182.50 USD (+1.25% today)"
    assert card.routines[1]["answer"] == daily.routine_answer({}, "en")


def test_a_routine_still_being_fetched_has_no_answer_yet():
    facts = {"routines": [{"id": "r1", "ask": "how is NVDA", "pending": True}]}
    assert daily.answered(facts, "en") == [
        {"id": "r1", "text": "how is NVDA", "answer": "", "chart": None}
    ]


def test_the_computed_answer_says_the_figures_plainly():
    routine = {
        "quotes": [{"ticker": "NVDA", "price": 182.5, "currency": "USD"}],
        "chart": {"window": "1m", "lines": [
            {"ticker": "NVDA", "change_pct": 10.0},
            {"portfolio": True, "change_pct": -1.5},
        ]},
    }
    answer = daily.routine_answer(routine, "en")
    assert answer == (
        "NVDA at 182.50 USD · NVDA: +10.00% (past month)"
        " · Your portfolio: -1.50% (past month)"
    )
    assert daily.routine_answer({}, "es").startswith("Hoy no hay datos")


def test_routines_are_answered_in_the_thread_the_card_is_filed_in():
    card = daily.computed(book_facts(routines=ROUTINES), "en", TODAY)
    text = daily.thread_text(card)
    assert "**how is NVDA doing**" in text
    assert "NVDA at 182.50 USD (+1.25% today)" in text


def _routine(rid: str, text: str, tickers=()) -> learnings.Learning:
    return learnings.Learning(rid, text, kind="routine", tickers=tuple(tickers))


def test_gather_fetches_each_routine_s_quotes(monkeypatch):
    monkeypatch.setattr(market, "mentioned", lambda text, known, lookup=None: [])
    monkeypatch.setattr(
        market, "quotes",
        lambda names: [market.Quote(n, price=100.0, currency="USD", prev_close=80.0)
                       for n in names],
    )
    facts, drawn = daily_routines.gather(
        [_routine("r1", "how is nvda", ["NVDA"])],
        watchlist=None, db=None, base="EUR", lookup=lambda name: "",
    )
    assert drawn == {}
    assert facts == [{
        "id": "r1", "ask": "how is nvda",
        "quotes": [{"ticker": "NVDA", "price": 100.0, "currency": "USD",
                    "change_pct": 25.0}],
    }]


def test_gather_draws_the_chart_a_routine_asks_for(monkeypatch):
    line = charts.Line(
        symbol="NVDA", currency="USD", dates=("2026-09-01", "2026-09-29"),
        values=(100.0, 110.0), first=100.0, first_on="2026-09-01", last=110.0,
        last_on="2026-09-29", high=112.0, high_on="2026-09-20", low=98.0,
        low_on="2026-09-03", sessions=20, along=(),
    )
    monkeypatch.setattr(charts, "wants", lambda text: True)
    monkeypatch.setattr(charts, "targets", lambda text, known, base, lookup: ["NVDA"])
    monkeypatch.setattr(charts, "build", lambda symbols, window, base, book=None:
                        charts.Chart(window, (line,)))
    monkeypatch.setattr(market, "mentioned", lambda text, known, lookup=None: [])
    monkeypatch.setattr(market, "quotes", lambda names: [])
    facts, drawn = daily_routines.gather(
        [_routine("r1", "chart NVDA")], watchlist=None, db=None, base="EUR",
        lookup=lambda name: "",
    )
    chart = facts[0]["chart"]
    assert chart["window"] == daily_routines.WINDOW
    assert chart["lines"][0]["ticker"] == "NVDA"
    assert chart["lines"][0]["change_pct"] == 10.0
    assert drawn["r1"]["window"] == daily_routines.WINDOW
    assert drawn["r1"]["series"][0]["values"] == [100.0, 110.0]


def test_a_routine_that_fails_or_runs_late_keeps_its_question(monkeypatch):
    def one(routine, known, db, base, lookup):
        if routine.id == "slow":
            time.sleep(0.5)
        if routine.id == "bad":
            raise RuntimeError("throttled")
        return {"id": routine.id, "ask": routine.text, "quotes": []}, None

    monkeypatch.setattr(daily_routines, "_one", one)
    facts, drawn = daily_routines.gather(
        [_routine("ok", "a"), _routine("bad", "b"), _routine("slow", "c")],
        watchlist=None, db=None, base="EUR", lookup=lambda n: "", budget_s=0.1,
    )
    assert facts == [
        {"id": "ok", "ask": "a", "quotes": []},
        {"id": "bad", "ask": "b"},
        {"id": "slow", "ask": "c"},
    ]
    assert drawn == {}


def test_routines_are_read_only_with_memory_on(tmp_path):
    chat = tmp_path / "chat.json"
    path = learnings.path_for(chat)
    learnings.add(path, "how is NVDA doing every morning", kind="routine")
    learnings.add(path, "I invest for ten years", kind="context")
    found = daily_routines.load({}, chat)
    assert [r.kind for r in found] == ["routine"]
    assert daily_routines.load({"chat_memory": False}, chat) == []
    assert daily_routines.load({}, None) == []


# ------------------------------------------------------- the free allowance


def test_the_card_spends_at_most_its_share_of_the_allowance():
    prefs: dict = {}
    spent = []

    def spend(p):
        spent.append(1)
        return True

    results = [daily.spend_unit(prefs, TODAY, spend) for _ in range(3)]
    assert results == [True, True, False]
    assert len(spent) == daily.FREE_UNITS == 2
    assert prefs[daily.UNITS_KEY] == {"day": TODAY.isoformat(), "used": 2}
    # A new day, a new share, in the same key.
    assert daily.spend_unit(prefs, TODAY + timedelta(days=1), spend) is True
    assert prefs[daily.UNITS_KEY] == {
        "day": (TODAY + timedelta(days=1)).isoformat(), "used": 1,
    }


def test_a_refused_unit_is_not_counted():
    prefs: dict = {}
    assert daily.spend_unit(prefs, TODAY, lambda p: False) is False
    assert daily.UNITS_KEY not in prefs


def test_generate_routes_every_unit_through_the_card_s_share(monkeypatch):
    prefs = {daily.UNITS_KEY: {"day": TODAY.isoformat(), "used": daily.FREE_UNITS}}
    asked = []

    def complete(prefs, system, messages, timeout_s, *, spend_free, accept):
        asked.append(spend_free(prefs))
        return None

    monkeypatch.setattr(daily.engine, "complete_attempts", complete)
    monkeypatch.setattr(daily.engine, "user_memory", lambda *a, **k: ([], []))
    daily.generate(prefs, {}, book_facts(), "en", TODAY, spend_free=lambda p: True)
    assert asked == [False]


# ----------------------------------------------------------- the computed card


def test_the_computed_card_opens_on_the_book_against_the_index():
    card = daily.computed(book_facts(), "en", TODAY)
    assert card.headline.startswith("Portfolio +0.80% vs the S&P 500 +0.30%")
    assert card.book["rows"][0]["pct"] == 0.8
    assert [i["key"] for i in card.items] == ["alert_hit:AAPL", "earnings:NVDA"]


def test_a_quiet_day_leaves_the_move_to_the_portfolio_section():
    card = daily.computed(book_facts(actions=[]), "en", TODAY)
    assert card.book
    assert not any("+0.80%" in b for b in card.bullets)


def test_without_the_index_the_computed_card_is_as_it_was():
    card = daily.computed(book_facts(index=None, actions=[]), "en", TODAY)
    assert card.book == {}
    assert any("+0.80%" in b for b in card.bullets)


# ------------------------------------------------------------- the charts


def test_charts_are_attached_after_the_card_is_built():
    facts = book_facts(routines=[{"id": "r1", "ask": "chart NVDA"}])
    card = daily.computed(facts, "en", TODAY)
    month = [{"symbol": "@BOOK", "dates": ["2026-09-01"], "values": [100.0]}]
    drawn = {"r1": {"window": "1m", "rebased": False, "series": []}}
    dressed = daily.dressed(card, month, drawn)
    assert dressed.book["chart"] == month
    assert dressed.routines[0]["chart"] == drawn["r1"]
    assert "chart" not in card.book  # the card itself is left as built
    stored = daily.DailyAction.from_dict(dressed.to_dict())
    assert stored.book["chart"] == month
    assert stored.routines[0]["chart"] == drawn["r1"]


def test_a_card_without_a_book_takes_no_chart():
    card = daily.computed(book_facts(index=None), "en", TODAY)
    assert daily.dressed(card, [{"symbol": "@BOOK"}]).book == {}
    assert daily.dressed(None, []) is None
