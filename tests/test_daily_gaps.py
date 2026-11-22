"""The daily card says what it could not check today.

A thesis no model read, an event rule whose sources failed, a held name whose
SEC filings did not come: the card is still written from what was read, and
says the rest in one line — on Home, on Today, in the chat thread it is filed
in and in the morning push. A card silent on a thesis it never read would
pass for one that held.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from stocks.chat import daily, journal
from stocks.views import briefing, daily_card

DAY = date(2026, 10, 1)
TODAY = date(2026, 10, 21)
PILLARS = ["Hyperscalers keep raising AI capex", "Data center revenue keeps growing"]


@pytest.fixture(autouse=True)
def _no_bucket(monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "decisions.json"


def _thesis(path, ticker):
    journal.add_criteria(path, ticker, [{"rule": "thesis", "pillars": PILLARS}], DAY)


def _owed(path, part):
    rows = journal.unchecked(path, TODAY)
    return sorted(r["ticker"] for r in rows if r["part"] == part)


def _news(text="Data center revenue grows"):
    return [{"source": "Reuters", "day": TODAY.isoformat(), "text": text}]


def test_a_thesis_no_model_read_or_the_round_ran_out_on_is_still_owed(path):
    for ticker in ("AMD", "NVDA", "TSM"):
        _thesis(path, ticker)
    assert _owed(path, "thesis") == ["AMD", "NVDA", "TSM"]

    def judge(ticker, pillars, passages):
        return None if ticker == "NVDA" else {"verdicts": []}

    journal.check_theses(path, TODAY, passages_of=lambda t, since: _news(),
                         judge=judge, max_calls=2)
    # AMD read; NVDA asked but no model answered; TSM past the round's calls.
    assert _owed(path, "thesis") == ["NVDA", "TSM"]


def test_an_event_rule_whose_sources_failed_is_owed_a_quiet_one_is_not(path):
    journal.add_criteria(path, "AMD", [{"rule": "ceo_change"}], DAY)
    journal.add_criteria(path, "INTC", [{"rule": "guidance_cut"}], DAY)

    def passages(ticker, since):
        if ticker == "AMD":
            raise RuntimeError("no source could be read")
        return []

    journal.check_slow(path, TODAY, quarters_of=list, passages_of=passages,
                       judge=lambda *a: pytest.fail("nothing to judge"))
    assert _owed(path, "rule") == ["AMD"]


def test_a_rule_with_nothing_to_read_it_by_is_never_owed(path):
    journal.add_criteria(path, "AMD", [{"rule": "below", "level": 100}], DAY)
    assert journal.unchecked(path, TODAY) == []


def test_a_name_with_no_sec_feed_and_no_headlines_was_not_read(monkeypatch):
    from stocks import loaders
    from stocks.data import edgar

    monkeypatch.setattr(edgar, "cik_for", lambda t: None)
    monkeypatch.setattr(loaders, "current_reports", lambda t: [])

    def down(ticker):
        raise TimeoutError

    monkeypatch.setattr(loaders, "headlines", down)
    # Raising is what keeps the rule unstamped for the next card.
    with pytest.raises(RuntimeError):
        briefing._passages("JD.L", TODAY)
    # A US name keeps its headlines when its 8-K feed fails, and the reverse.
    monkeypatch.setattr(edgar, "cik_for", lambda t: "0000001")
    assert briefing._passages("AMD", TODAY) == []
    monkeypatch.setattr(loaders, "current_reports", down)
    with pytest.raises(RuntimeError):
        briefing._passages("AMD", TODAY)
    monkeypatch.setattr(loaders, "headlines", lambda t: [])
    assert briefing._passages("AMD", TODAY) == []


def test_the_gaps_name_the_theses_rules_and_filings_left_unread(path):
    _thesis(path, "NVDA")
    journal.add_criteria(path, "AMD", [{"rule": "ceo_change"}], DAY)
    paths = SimpleNamespace(journal=path)
    gaps = briefing.card_gaps(paths, TODAY, ["TSM"])
    assert gaps == [{"part": "theses", "tickers": ["NVDA"]},
                    {"part": "rules", "tickers": ["AMD"]},
                    {"part": "filings", "tickers": ["TSM"]}]
    # Filings not read at all (the ticker map, or the job never got there).
    assert briefing.card_gaps(paths, TODAY, None)[-1] == {"part": "filings",
                                                          "tickers": []}
    assert briefing.card_gaps(paths, TODAY, [""])[-1] == {"part": "filings",
                                                          "tickers": []}


def test_a_clean_round_leaves_no_gap(path):
    _thesis(path, "NVDA")
    journal.check_theses(path, TODAY, passages_of=lambda t, since: _news(),
                         judge=lambda *a: {"verdicts": []})
    assert briefing.card_gaps(SimpleNamespace(journal=path), TODAY, []) == []


def test_an_unreadable_journal_is_not_all_clear(path, monkeypatch):
    def broken(path, day):
        raise ValueError

    monkeypatch.setattr(journal, "unchecked", broken)
    assert briefing.card_gaps(SimpleNamespace(journal=path), TODAY, []) == [
        {"part": "rules", "tickers": []}]


def test_a_failed_filings_feed_is_named(monkeypatch):
    from stocks import loaders
    from stocks.data import edgar

    monkeypatch.setattr(edgar, "cik_for", lambda t: "0000001")

    def reports(ticker):
        if ticker == "AMD":
            raise TimeoutError
        return []

    monkeypatch.setattr(loaders, "current_reports", reports)
    missed: list = []
    briefing._filings({"AMD", "NVDA"}, missed)
    assert missed == ["AMD"]


def _card(gaps, lang="es"):
    return daily.DailyAction(day=TODAY.isoformat(), headline="Todo tranquilo",
                             bullets=["Nada que hacer hoy"], focus=[], lang=lang,
                             gaps=gaps)


def test_the_card_says_its_gaps_on_screen_in_the_thread_and_kept_on_disk():
    gaps = [{"part": "theses", "tickers": ["BABA", "NVDA"]},
            {"part": "filings", "tickers": []}]
    card = _card(gaps)
    line = daily.gaps_line(card.gaps, "es")
    assert line.startswith("Sin revisar hoy: tesis de BABA, NVDA; los filings de la SEC")
    assert f"_{line}_" in daily.thread_text(card)
    assert daily.DailyAction.from_dict(card.to_dict()).gaps == gaps
    shown = daily_card.answer(card, TODAY, fresh=True)
    assert shown.gaps_note == line
    assert daily_card.answer(_card([]), TODAY, fresh=True).gaps_note is None
    # Yesterday's card on screen this morning: its gaps were yesterday's.
    assert daily_card.answer(card, TODAY, fresh=False).gaps_note is None
    assert "Sin revisar" not in daily.thread_text(_card([]))


def test_a_long_list_of_names_is_cut_with_a_count():
    names = [f"T{i}" for i in range(daily.fallback.GAP_NAMES + 3)]
    line = daily.gaps_line([{"part": "rules", "tickers": names}], "en")
    assert "T4 +3" in line and "T5" not in line
    # Stray shapes from an old file are dropped, not shown.
    stray = [{"part": "nope"}, "x", {"part": "rules", "tickers": [" "]}]
    assert daily.gaps_of(stray) == [{"part": "rules", "tickers": []}]


def test_the_morning_push_carries_the_gap_after_the_first_line(monkeypatch):
    from stocks.notify import schedule

    card = daily.DailyAction(
        day=TODAY.isoformat(), headline="Quiet day", bullets=[], focus=[], lang="en",
        thread="c1", items=[{"key": "a", "line": "AMD hit its stop"},
                            {"key": "b", "line": "NVDA reports Thursday"}],
        gaps=[{"part": "theses", "tickers": ["BABA"]}])
    sent = {}
    monkeypatch.setattr(schedule, "_current_card", lambda account, stand_in: card)
    monkeypatch.setattr("stocks.chat.conversations.mark_scheduled",
                        lambda *a: True)
    monkeypatch.setattr(schedule, "_push",
                        lambda account, message, kind: sent.update(message) or 1)
    monkeypatch.setattr(schedule, "_landing", lambda account: "/")
    account = SimpleNamespace(paths=SimpleNamespace(chat="chat.json"), label="x")
    schedule._briefing(account, TODAY)
    body = sent["body"].splitlines()
    assert body[:2] == ["Quiet day", "AMD hit its stop"]
    assert body[2].startswith("Not checked today: theses for BABA")


def test_the_card_model_is_told_not_to_write_past_its_gaps():
    from stocks.chat.daily import instructions

    facts = {"date": TODAY.isoformat(), "actions": [],
             "gaps": [{"part": "theses", "tickers": ["BABA"]}]}
    system, messages = instructions.prompt(facts, {}, "en")
    assert "never write past it" in system
    assert "BABA" in str(messages)
    brief, _ = instructions.prompt({**facts, "brief": {"asks": ["x"]}}, {}, "en")
    assert "never write past it" in brief
