"""The night's thesis round, before the card.

The card's own round has 30 s for every thesis in the book and read a few a
night; the rest were named on the card as not checked. On the tick the card
comes due, the schedule first reads every owed thesis on its own
(`briefing.read_theses`): the news of all of them fetched at once, the model
asked name by name, each read stamped. The card goes on the next tick and
finds them read; a thesis the round found broken is on it all the same.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime

import pytest

from stocks import accounts
from stocks.chat import daily, exit_judge, journal
from stocks.notify import schedule
from stocks.views import briefing

DAY = date(2026, 10, 1)
TODAY = date(2026, 10, 21)
PILLARS = ["Hyperscalers keep raising AI capex", "Data center revenue keeps growing"]


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    found = accounts.paths_in(tmp_path / "jane")
    found.root.mkdir(parents=True)
    found.prefs.write_text(json.dumps({"language": "en"}))
    return found


def _thesis(paths, ticker):
    journal.add_criteria(paths.journal, ticker, [{"rule": "thesis",
                                                  "pillars": PILLARS}], DAY)


def _news(text):
    return [{"source": "Reuters", "day": TODAY.isoformat(), "text": text}]


@pytest.fixture
def night(paths, monkeypatch):
    """The round's clock on TODAY and a judge that says NVDA's capex pillar
    broke; the judge's calls are recorded."""
    monkeypatch.setattr(briefing, "now_day", lambda p=None: (datetime.now(UTC), TODAY))
    asked: list[str] = []

    def judge(ticker, pillars, passages):
        asked.append(ticker)
        if ticker == "NVDA":
            return {"verdicts": [{"pillar": "A", "verdict": "damaged", "item": 0,
                                  "quote": "Microsoft cuts its capex plan"}]}
        return {"verdicts": []}

    monkeypatch.setattr(exit_judge, "make_thesis_judge", lambda *a, **k: judge)
    return asked


def test_the_round_reads_every_owed_thesis_and_stamps_it(paths, night, monkeypatch):
    for ticker in ("AMD", "NVDA", "TSM"):
        _thesis(paths, ticker)
    news = {"AMD": "Data center revenue grows 30%",
            "NVDA": "Microsoft cuts its capex plan for AI data centers",
            "TSM": "Data center revenue keeps growing at TSMC"}
    monkeypatch.setattr(briefing, "thesis_passages",
                        lambda t, since: _news(news[t]))
    status = briefing.read_theses(paths)
    assert status == "read 3/3, met 1"
    assert sorted(night) == ["AMD", "NVDA", "TSM"]
    assert journal.unchecked(paths.journal, TODAY) == []
    [hit] = journal.theses_hit_on(paths.journal, TODAY)
    assert hit["ticker"] == "NVDA" and hit["verdict"] == "damaged"
    # Nothing owed: the next round asks nobody.
    assert briefing.read_theses(paths) == "nothing owed"


def test_a_name_whose_news_did_not_come_in_time_stays_owed(paths, night, monkeypatch):
    for ticker in ("AMD", "NVDA", "TSM"):
        _thesis(paths, ticker)
    monkeypatch.setattr(briefing, "THESIS_PASS_FETCH_S", 0.3)

    def fetch(ticker, since):
        if ticker == "AMD":
            time.sleep(1.0)
        if ticker == "TSM":
            raise RuntimeError("no source could be read")
        return _news("Data center revenue grows")

    monkeypatch.setattr(briefing, "thesis_passages", fetch)
    assert briefing.read_theses(paths) == "read 1/3, met 0"
    # Not stamped as read with nothing: the card's round, and its note, have them.
    owed = sorted(r["ticker"] for r in journal.unchecked(paths.journal, TODAY))
    assert owed == ["AMD", "TSM"]


# ------------------------------------------------------------------ the schedule


def _planned(paths, monkeypatch, now, last=None):
    paths.prefs.write_text(json.dumps({"language": "en",
                                       "last_seen": now.date().isoformat(),
                                       "schedule_last": last or {}}))
    monkeypatch.setattr(schedule, "_roster", lambda: [("jane", paths)])
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    return [a.runs for a in schedule.plan(now)]


def test_the_round_has_the_cards_tick_to_itself_and_the_card_the_next(
    paths, monkeypatch
):
    monday, tuesday = date(2026, 11, 2), date(2026, 11, 3)
    now = datetime(2026, 11, 3, 1, 15, tzinfo=UTC)  # 20:15 New York, Monday
    # No thesis: the card, as ever.
    assert _planned(paths, monkeypatch, now) == [[("card", monday)]]
    journal.add_criteria(paths.journal, "NVDA", [{"rule": "thesis",
                                                  "pillars": PILLARS}], monday)
    # Read for Tuesday's card, which the next tick writes.
    assert _planned(paths, monkeypatch, now) == [[("theses", tuesday)]]
    assert _planned(paths, monkeypatch, now, {"theses": "2026-11-03"}) == [
        [("card", monday)]]
    # Monday's mark (a morning round) does not stand for Tuesday's card.
    assert _planned(paths, monkeypatch, now, {"theses": "2026-11-02"}) == [
        [("theses", tuesday)]]


def test_mondays_card_is_written_by_the_briefing_and_read_for_before_it(
    paths, monkeypatch
):
    """No session closes on Sunday, so no card run: the morning briefing
    writes Monday's card, and the round goes a tick before it."""
    monday = date(2026, 11, 9)
    now = datetime(2026, 11, 9, 7, 45, tzinfo=UTC)  # 08:45 Madrid
    assert _planned(paths, monkeypatch, now) == [[("briefing", monday)]]
    journal.add_criteria(paths.journal, "NVDA", [{"rule": "thesis",
                                                  "pillars": PILLARS}], monday)
    assert _planned(paths, monkeypatch, now) == [[("theses", monday)]]
    assert _planned(paths, monkeypatch, now, {"theses": "2026-11-09"}) == [
        [("briefing", monday)]]
    # A card already standing for Monday (written on a visit): a round now
    # would stamp breaks it never tells. Its own round read them.
    paths.action.write_text(json.dumps(daily.DailyAction(
        day=monday.isoformat(), headline="Quiet", bullets=["Nothing to do"], focus=[],
        lang="en").to_dict()))
    assert _planned(paths, monkeypatch, now) == [[("briefing", monday)]]
    # Nothing due on a Sunday: no round either.
    assert _planned(paths, monkeypatch, datetime(2026, 11, 8, 10, 0, tzinfo=UTC)) == []


def test_the_round_is_marked_run_like_any_other(paths, monkeypatch):
    monkeypatch.setattr(briefing, "read_theses", lambda p: "read 3/3, met 0")
    account = schedule.Account("jane", paths, {"language": "en"})
    assert schedule.run(account, "theses", date(2026, 11, 2)) == "read 3/3, met 0"
    stored = json.loads(paths.prefs.read_text())
    assert stored["schedule_last"] == {"theses": "2026-11-02"}


def test_the_rounds_summary_says_whose_and_how_far_it_got(paths, night, monkeypatch):
    """`briefing.thesis_pass` is how prod says whether the round read the
    book (`left`): under the account it read, the judge's events too."""
    from stocks import obs

    _thesis(paths, "NVDA")
    monkeypatch.setattr(briefing, "thesis_passages",
                        lambda t, since: _news("Microsoft cuts its capex plan"))
    seen: list[tuple[str, dict, dict]] = []
    monkeypatch.setattr(obs, "event", lambda name, **f: seen.append(
        (name, f, obs._fields())))
    account = schedule.Account("jane", paths, {"language": "en"})
    schedule.run(account, "theses", TODAY)
    [(_, fields, ambient)] = [s for s in seen if s[0] == "briefing.thesis_pass"]
    assert ambient["user"] == "jane"
    assert {k: fields[k] for k in ("owed", "fetched", "asked", "met", "left")} == {
        "owed": 1, "fetched": 1, "asked": 1, "met": 1, "left": 0}
    assert all(a.get("user") == "jane" for n, _, a in seen
               if n.startswith("journal."))


def test_a_round_short_two_nights_running_is_a_warning(paths, night, monkeypatch):
    """One short night is a slow feed; two is a round that does not fit the
    book, emailed (infra/monitoring/policy-thesis-pass-short.json)."""
    from stocks import obs

    _thesis(paths, "NVDA")
    warned: list[dict] = []
    monkeypatch.setattr(obs, "warn", lambda name, **f: warned.append(
        {"event": name, **f}) if name.startswith("briefing.") else None)

    def down(ticker, since):
        raise RuntimeError("no source could be read")

    monkeypatch.setattr(briefing, "thesis_passages", down)

    def night_of(day):
        monkeypatch.setattr(briefing, "now_day", lambda p=None: (datetime.now(UTC), day))
        briefing.read_theses(paths)

    night_of(TODAY)
    assert warned == []
    night_of(TODAY)  # the same day again counts once
    assert warned == []
    night_of(date(2026, 10, 22))
    [w] = warned
    assert w["event"] == "briefing.thesis_pass_short"
    assert (w["runs"], w["left"], w["owed"], w["fetched"]) == (2, 1, 1, 0)
    # A round that reads them all ends the streak.
    monkeypatch.setattr(briefing, "thesis_passages", lambda t, since: [])
    night_of(date(2026, 10, 23))
    monkeypatch.setattr(briefing, "thesis_passages", down)
    night_of(date(2026, 10, 26))
    assert len(warned) == 1
    stored = json.loads(paths.prefs.read_text())["thesis_pass_short"]
    assert stored == {"day": "2026-10-26", "runs": 1}


def test_the_round_is_charged_to_the_shared_pot_not_the_readers_chat(
    paths, monkeypatch
):
    """Forty theses read at 01:15 UTC would take a new day's chat allowance;
    the night's judgements spend the shared pot only (`spend_in_background`)."""
    monkeypatch.setattr(briefing, "now_day", lambda p=None: (datetime.now(UTC), TODAY))
    _thesis(paths, "NVDA")
    monkeypatch.setattr(briefing, "thesis_passages", lambda t, since: _news("x"))
    charged = []

    def make(prefs, **kw):
        charged.append(kw["spend_free"])
        return lambda *a: {"verdicts": []}

    monkeypatch.setattr(exit_judge, "make_thesis_judge", make)
    briefing.read_theses(paths)
    briefing.check_theses(paths, {}, TODAY)
    assert charged == [briefing.spend_in_background] * 2
    assert "free_msgs" not in paths.prefs.read_text()
