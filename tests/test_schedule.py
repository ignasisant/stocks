"""Scheduled runs: the briefing, the day's numbers and the weekly review, each at
the account's own time, filed as a chat thread and pushed to open it.

What is tested here:

* when a run comes due — the account's local wall clock and weekdays, a
  catch-up window that stops a missed run going out at midnight, never twice
  the same local day, and across a daylight-saving change;
* the settings as the app applies them, a bad stored value read as the
  default; the next day's card built after each US close, whoever reads it;
* the tick: runs marked done even when they fail, and the ones it could not
  start left for the next tick;
* each run's thread: listed with its job, replaced on a re-run of the same
  day, and opened for the model with what it was;
* the route: the API token alone, one tick at a time; the settings: a zone
  that does not exist and a job that does not exist are refused.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import scheduled
from stocks.api.app import app as fastapi_app
from stocks.chat import conversations, daily, engine
from stocks.notify import schedule
from tests.patching import patch_loaders

MADRID = ZoneInfo("Europe/Madrid")
WEEKDAYS = [0, 1, 2, 3, 4]


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# ------------------------------------------------------------------ due


def test_a_run_is_due_from_its_local_time_on_a_listed_day():
    morning = {"on": True, "time": "08:30", "days": WEEKDAYS}
    # Monday 2 Nov 2026, Madrid on winter time (UTC+1).
    assert schedule.due(morning, MADRID, at("2026-11-02T07:29"), None) is None
    assert schedule.due(morning, MADRID, at("2026-11-02T07:31"), None) == date(
        2026, 11, 2
    )


def test_summer_time_moves_the_utc_instant_not_the_local_one():
    morning = {"on": True, "time": "08:30", "days": WEEKDAYS}
    # Wednesday 1 Jul 2026, UTC+2: 06:31 UTC is 08:31 in Madrid.
    assert schedule.due(morning, MADRID, at("2026-07-01T06:31"), None) == date(2026, 7, 1)
    assert schedule.due(morning, MADRID, at("2026-07-01T06:29"), None) is None


def test_not_on_a_day_left_out_nor_switched_off():
    morning = {"on": True, "time": "08:30", "days": WEEKDAYS}
    saturday = at("2026-10-31T09:00")
    assert schedule.due(morning, MADRID, saturday, None) is None
    off = {**morning, "on": False}
    assert schedule.due(off, MADRID, at("2026-11-02T09:00"), None) is None


def test_never_twice_the_same_local_day():
    morning = {"on": True, "time": "08:30", "days": WEEKDAYS}
    now = at("2026-11-02T09:00")
    assert schedule.due(morning, MADRID, now, "2026-11-02") is None
    assert schedule.due(morning, MADRID, now, "2026-10-30") == date(2026, 11, 2)


def test_a_missed_run_goes_out_late_but_not_past_the_catch_up():
    morning = {"on": True, "time": "08:30", "days": WEEKDAYS}
    assert schedule.due(morning, MADRID, at("2026-11-02T13:00"), None) == date(
        2026, 11, 2
    )
    assert schedule.due(morning, MADRID, at("2026-11-02T14:00"), None) is None


def test_a_late_slot_catches_up_across_midnight_as_its_own_day():
    evening = {"on": True, "time": "22:30", "days": WEEKDAYS}
    # Friday 22:30 Madrid missed; 00:30 Saturday local still delivers Friday's.
    assert schedule.due(evening, MADRID, at("2026-10-30T23:30"), None) == date(
        2026, 10, 30
    )
    assert schedule.due(evening, MADRID, at("2026-10-30T23:30"), "2026-10-30") is None


# ------------------------------------------------------------------ settings


def test_defaults_until_set_and_a_bad_value_reads_as_the_default():
    assert schedule.slots({}) == {
        job: {"on": True, **schedule.DEFAULTS[job]} for job in schedule.JOBS
    }
    prefs = {
        "notify_digest": False,
        "schedules": {"digest": {"time": "25:99", "days": [5, 5, 9, 1]}},
    }
    digest = schedule.slot(prefs, "digest")
    assert digest == {"on": False, "time": "22:30", "days": [1, 5]}


def test_an_unknown_zone_is_the_default_one():
    assert schedule.zone({"timezone": "Mars/Olympus"}) == MADRID
    assert schedule.zone({"timezone": "America/New_York"}) == ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    ("utc", "expected"),
    [
        ("2026-11-02T21:47", None),  # Monday 16:47 New York: after hours still on
        ("2026-11-03T01:10", None),  # 20:10: the window shut, the prints land
        ("2026-11-03T01:15", date(2026, 11, 2)),  # 20:15: Monday's session
        ("2026-11-03T07:20", None),  # past the catch-up
        ("2026-11-01T01:15", None),  # Saturday: no session
        ("2026-11-27T01:15", None),  # Thanksgiving: no session
        ("2026-07-07T00:15", date(2026, 7, 6)),  # summer time, same 20:15
    ],
)
def test_the_card_is_built_after_each_us_close(utc, expected):
    assert schedule.card_due(at(utc), None) == expected
    assert schedule.card_due(at(utc), expected) is None  # once a session


def test_runs_are_spent_on_accounts_somebody_reads():
    today = date(2026, 10, 31)
    assert schedule.eligible({}, devices=1, today=today)
    assert schedule.eligible({"last_seen": "2026-10-20T10:00:00Z"}, 0, today)
    assert not schedule.eligible({"last_seen": "2026-10-01"}, 0, today)
    assert not schedule.eligible({}, 0, today)


# ------------------------------------------------------------------ the tick


@pytest.fixture
def account(tmp_path, monkeypatch) -> schedule.Account:
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    paths = accounts.paths_in(tmp_path / "jane")
    paths.root.mkdir(parents=True)
    paths.prefs.write_text(json.dumps({"language": "en"}))
    return schedule.Account("jane", paths, {"language": "en"})


def test_a_run_that_fails_is_still_marked_run(account, monkeypatch):
    """Otherwise every tick until the catch-up closed would pay for the same
    failure again."""

    def broken(acc, day):
        raise RuntimeError("model down")

    monkeypatch.setitem(schedule.RUNNERS, "digest", broken)
    status = schedule.run(account, "digest", date(2026, 11, 2))
    assert status == "error: RuntimeError"
    stored = json.loads(account.paths.prefs.read_text())
    assert stored["schedule_last"] == {"digest": "2026-11-02"}
    assert stored["language"] == "en"


def test_runs_past_the_budget_wait_for_the_next_tick(account, monkeypatch):
    account.runs = [("digest", date(2026, 11, 2)), ("weekly", date(2026, 11, 2))]
    monkeypatch.setattr(schedule, "plan", lambda now: [account])
    ran: list[str] = []
    monkeypatch.setitem(
        schedule.RUNNERS, "digest", lambda a, d: ran.append("digest") or "filed"
    )
    monkeypatch.setitem(
        schedule.RUNNERS, "weekly", lambda a, d: ran.append("weekly") or "filed"
    )

    assert schedule.tick(at("2026-11-02T22:00"), budget_s=-1) == {
        "due": 2,
        "ran": 0,
        "deferred": 2,
    }
    assert ran == []
    assert schedule.tick(at("2026-11-02T22:00")) == {"due": 2, "ran": 2, "deferred": 0}
    assert ran == ["digest", "weekly"]


def test_the_plan_takes_only_whats_due(account, monkeypatch):
    account.paths.prefs.write_text(
        json.dumps(
            {
                "language": "en",
                "last_seen": "2026-11-01",
                "schedule_last": {"briefing": "2026-11-02"},
            }
        )
    )
    monkeypatch.setattr(schedule, "_roster", lambda: [("jane", account.paths)])
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    # Monday 08:45 Madrid: the briefing already went out, nothing else is due.
    assert schedule.plan(at("2026-11-02T07:45")) == []
    # 02:15: the next day's card, after the US after-hours, and the day's
    # numbers still inside their catch-up.
    (due,) = schedule.plan(at("2026-11-03T01:15"))
    assert due.runs == [("card", date(2026, 11, 2)), ("digest", date(2026, 11, 2))]


# ------------------------------------------------------------------ the email

FRIDAY = date(2026, 11, 6)


class _Paths:
    db = Path("portfolio.db")


@pytest.fixture
def imported(monkeypatch):
    from stocks.portfolio import demo

    monkeypatch.setattr(demo, "has_real", lambda db: True)


def test_the_email_goes_out_friday_night_after_the_us_close(imported):
    prefs = {"email": "a@example.com"}
    # 23:00 Madrid on winter time is 22:00 UTC.
    assert schedule.email_due(prefs, _Paths, at("2026-11-06T21:59"), None) is None
    assert schedule.email_due(prefs, _Paths, at("2026-11-06T22:01"), None) == FRIDAY
    assert schedule.email_due(prefs, _Paths, at("2026-11-06T22:01"), "2026-11-06") is None
    assert schedule.email_due(prefs, _Paths, at("2026-11-05T22:01"), None) is None


def test_no_email_without_an_address_or_once_switched_off(imported):
    now = at("2026-11-06T22:01")
    assert schedule.email_due({}, _Paths, now, None) is None
    off = {"email": "a@example.com", "notify_weekly_email": False}
    assert schedule.email_due(off, _Paths, now, None) is None


def test_the_onboarding_sample_is_not_a_book_to_report(monkeypatch):
    from stocks.portfolio import demo

    monkeypatch.setattr(demo, "has_real", lambda db: False)
    prefs = {"email": "a@example.com"}
    assert schedule.email_due(prefs, _Paths, at("2026-11-06T22:01"), None) is None


def test_an_account_with_no_device_and_no_visit_still_gets_the_email(
    account, monkeypatch, imported
):
    account.paths.prefs.write_text(json.dumps({"email": "a@example.com"}))
    monkeypatch.setattr(schedule, "_roster", lambda: [("jane", account.paths)])
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    (due,) = schedule.plan(at("2026-11-06T22:01"))
    assert due.runs == [("weekly_email", FRIDAY)]


# ------------------------------------------------------------------ the thread


@pytest.fixture
def chat(tmp_path) -> Path:
    return tmp_path / "chat.json"


def test_a_run_is_a_thread_of_its_own_listed_with_its_job(chat, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    conversations.save_chat([{"role": "user", "content": "hola"}], chat)
    active = conversations.active_conversation(chat)["id"]

    cid = conversations.save_scheduled_thread(
        "digest", "2026-11-02", "Day's numbers · Nov 2", "**€48,230**\n\n- NVDA +3%", chat
    )

    assert cid != active
    assert conversations.active_conversation(chat)["id"] == active
    listed = conversations.list_conversations(chat, cards=False)
    meta = next(c for c in listed if c["id"] == cid)
    assert meta["scheduled"] == "digest" and meta["title"] == "Day's numbers · Nov 2"


def test_the_same_run_again_replaces_its_turn(chat, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    first = conversations.save_scheduled_thread("digest", "2026-11-02", "t", "one", chat)
    again = conversations.save_scheduled_thread("digest", "2026-11-02", "t", "two", chat)
    assert first == again
    (turn,) = conversations.load_chat(chat, first)
    assert turn["content"] == "two" and turn["scheduled"] == "digest"


def test_a_run_can_be_rated_and_says_when_it_was_filed(chat, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    cid = conversations.save_scheduled_thread("digest", "2026-11-02", "t", "one", chat)
    (turn,) = conversations.load_chat(chat, cid)
    assert turn["id"] and turn["at"]
    assert conversations.rate_turn(turn["id"], "up", chat)["thread"] == cid
    (turn,) = conversations.load_chat(chat, cid)
    assert turn["rating"] == "up"


def test_a_run_filed_before_ids_gets_a_stable_one(chat, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    cid = conversations.save_scheduled_thread("digest", "2026-11-02", "t", "one", chat)
    book = json.loads(chat.read_text())
    for conv in book["conversations"]:
        for m in conv["messages"]:
            m.pop("id", None)
    chat.write_text(json.dumps(book))
    (turn,) = conversations.load_chat(chat, cid)
    assert turn["id"] == f"{cid}-0"
    assert conversations.load_chat(chat, cid)[0]["id"] == turn["id"]
    assert conversations.rate_turn(turn["id"], "down", chat) is not None


def test_the_model_is_told_what_the_thread_opened_with():
    history = [
        {
            "role": "assistant",
            "content": "**€48,230**",
            "scheduled": "digest",
            "run": "2026-11-02",
        },
        {"role": "user", "content": "why did NVDA move?"},
    ]
    opener, said, asked = engine.recent(history)
    assert opener["role"] == "user" and "2026-11-02" in opener["content"]
    assert said["content"] == "**€48,230**" and asked["role"] == "user"


def test_the_briefing_thread_is_the_cards_marked(chat, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    card = daily.DailyAction(
        day="2026-11-02",
        headline="h",
        bullets=["x"],
        lang="en",
        as_of="2026-10-30",
        items=[{"key": "k", "kind": "", "line": "x", "tickers": []}],
    )
    cid = daily.record(chat, card)
    assert conversations.mark_scheduled(cid, "briefing", "2026-11-02", chat)
    listed = conversations.list_conversations(chat, cards=False)
    meta = next(c for c in listed if c["id"] == cid)
    assert meta["scheduled"] == "briefing" and meta["daily"] == "2026-11-02"
    assert not conversations.mark_scheduled("nope", "briefing", "2026-11-02", chat)


def test_the_notification_opens_the_thread():
    assert schedule.thread_url("a b/c") == "/?thread=a%20b%2Fc"


# ------------------------------------------------------------------ the route

TOKEN = "s3cret-token"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    return TestClient(fastapi_app)


@pytest.fixture
def ticked(monkeypatch):
    from stocks import cache

    calls: list[bool] = []

    def fake(now=None, budget_s=schedule.TICK_BUDGET_S):
        calls.append(cache.SYNC.get())
        return {"due": 1, "ran": 1, "deferred": 0}

    monkeypatch.setattr(schedule, "tick", fake)
    return calls


def test_the_tick_wants_the_api_token(client, ticked, monkeypatch):
    from stocks import session

    assert client.post("/v1/schedule/tick").status_code == 401
    monkeypatch.setattr(session, "signed_in_email", lambda cookies: "a@example.com")
    assert client.post("/v1/schedule/tick").status_code == 401
    assert ticked == []


def test_the_tick_runs_in_place_and_once_at_a_time(client, ticked):
    res = client.post("/v1/schedule/tick", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.json() == {"due": 1, "ran": 1, "deferred": 0}
    assert ticked == [True]
    assert scheduled._running.acquire(blocking=False)
    try:
        busy = client.post(
            "/v1/schedule/tick", headers={"Authorization": f"Bearer {TOKEN}"}
        )
    finally:
        scheduled._running.release()
    assert busy.json() == {"busy": True}
    assert ticked == [True]


# ------------------------------------------------------------------ the settings

EMAIL = "holder@example.com"


@pytest.fixture
def signed_in(client, sign_in, tmp_path, monkeypatch):

    paths = accounts.paths_for(EMAIL, None, users_dir=tmp_path / "users")
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR", "notify_weekly": True}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=None: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    patch_loaders(monkeypatch, "db_mtime", lambda db: 1.0)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    session = sign_in(client, EMAIL)
    session.paths = paths
    return session


def test_a_run_is_timed_and_switched_whole(signed_in):
    res = signed_in.put(
        "/v1/schedules/weekly", json={"on": False, "time": "7:05", "days": [6, 5, 5]}
    )
    assert res.status_code == 200
    assert res.json()["schedules"]["weekly"] == {
        "on": False,
        "time": "07:05",
        "days": [5, 6],
    }
    assert res.json()["notify_weekly"] is False
    assert res.json()["schedules"]["digest"]["time"] == "22:30"  # untouched
    stored = json.loads(signed_in.paths.prefs.read_text())
    assert stored["schedules"] == {"weekly": {"time": "07:05", "days": [5, 6]}}


@pytest.mark.parametrize(
    "job, body",
    [
        ("lunch", {"on": True, "time": "12:00", "days": [0]}),
        ("digest", {"on": True, "time": "noon", "days": [0]}),
        ("digest", {"on": True, "time": "12:00", "days": [7]}),
    ],
)
def test_a_run_the_app_cannot_keep_is_refused(signed_in, job, body):
    assert signed_in.put(f"/v1/schedules/{job}", json=body).status_code in (404, 422)


def test_the_browser_sends_its_zone_and_a_made_up_one_is_refused(signed_in):
    assert (
        signed_in.patch("/v1/prefs", json={"timezone": "Mars/Olympus"}).status_code == 422
    )
    res = signed_in.patch("/v1/prefs", json={"timezone": "America/New_York"})
    assert res.json()["timezone"] == "America/New_York"


def test_a_token_cannot_time_anybodys_runs(signed_in):
    res = TestClient(fastapi_app).put(
        "/v1/schedules/digest",
        params={"account": EMAIL},
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"on": True, "time": "12:00", "days": [0]},
    )
    assert res.status_code == 403


# ------------------------------------------------------------------ restore


def test_a_reboot_restores_the_devices_it_pushes_to(tmp_path, monkeypatch):
    """The push and device lists were left out of the restore, so after a
    reboot the server pushed to nobody."""
    from stocks import storage

    restored: list[Path] = []
    monkeypatch.setattr(
        storage, "restore_once", lambda group, files: restored.extend(files)
    )
    paths = accounts.paths_in(tmp_path / "jane")
    accounts.restore_account(paths, seed=False)
    assert {paths.push, paths.devices, paths.journal, paths.verdicts} <= set(restored)


def test_the_briefing_files_the_card_the_evening_wrote(account, monkeypatch):
    """The card job wrote Tuesday's card on Monday night; Tuesday's briefing
    files it without asking a model again, and a card left from an older day
    is not pushed as this one."""
    from stocks.views import briefing, daily_card

    card = daily.DailyAction(day="2026-11-03", headline="h", bullets=["x"],
                             lang="en", as_of="2026-11-02")
    asked: list[bool] = []
    monkeypatch.setattr(daily_card, "request",
                        lambda paths, lang, force: asked.append(force))
    monkeypatch.setattr(daily_card, "stored", lambda paths: card)
    monkeypatch.setattr(briefing, "running", lambda paths: None)
    now = datetime(2026, 11, 3, 8, 30, tzinfo=MADRID)
    day = {"d": date(2026, 11, 3)}
    monkeypatch.setattr(briefing, "now_day", lambda paths=None: (now, day["d"]))
    assert schedule._card(account, date(2026, 11, 2)) == "llm: 2026-11-03"
    assert asked == [False]

    day["d"] = date(2026, 11, 4)
    assert schedule._briefing(account, date(2026, 11, 4)) == "skipped: no card"
