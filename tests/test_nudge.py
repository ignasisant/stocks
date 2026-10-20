"""Dormant-account reminder (stocks.notify.nudge)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from stocks.notify import fanout, nudge
from stocks.notify import state as state_mod
from stocks.notify import weekly as weekly_mod

TODAY = date(2026, 10, 21)
ORIGIN = "https://topstocks.example"


def _state(**over) -> dict:
    s = state_mod.load_state(__import__("pathlib").Path("/nonexistent"))
    s.update(over)
    return s


# ---------------------------------------------------------------- when


def test_an_account_never_seen_on_the_web_is_left_alone():
    assert nudge.due(_state(), {"telegram_chat_id": 1}, TODAY) is None


def test_quiet_for_less_than_a_week_is_not_dormant():
    assert nudge.due(_state(), {"last_seen": "2026-10-15"}, TODAY) is None


def test_the_first_reminder_comes_after_a_week():
    assert nudge.due(_state(), {"last_seen": "2026-10-14"}, TODAY) == 1


def test_the_second_waits_a_week_and_there_is_no_third():
    prefs = {"last_seen": "2026-10-01"}
    state = _state()
    assert nudge.due(state, prefs, date(2026, 10, 8)) == 1
    state_mod.remember_nudge(state, datetime(2026, 10, 8, 10, tzinfo=UTC))
    assert nudge.due(state, prefs, date(2026, 10, 9)) is None
    assert nudge.due(state, prefs, date(2026, 10, 14)) is None
    assert nudge.due(state, prefs, date(2026, 10, 15)) == 2
    state_mod.remember_nudge(state, datetime(2026, 10, 15, 10, tzinfo=UTC))
    assert nudge.due(state, prefs, date(2026, 10, 30)) is None
    assert nudge.due(state, prefs, date(2027, 3, 1)) is None


def test_coming_back_after_a_reminder_starts_a_new_spell():
    state = _state()
    state_mod.remember_nudge(state, datetime(2026, 9, 1, 10, tzinfo=UTC))
    state_mod.remember_nudge(state, datetime(2026, 9, 8, 10, tzinfo=UTC))
    # Visited on 20 Sep, after both reminders; quiet since.
    prefs = {"last_seen": "2026-09-20"}
    assert nudge.due(state, prefs, date(2026, 9, 26)) is None
    assert nudge.due(state, prefs, date(2026, 9, 27)) == 1
    assert state_mod.nudges_sent(state) == []


def test_a_malformed_last_seen_never_raises():
    assert nudge.days_away({"last_seen": "yesterday"}, TODAY) is None


def test_every_toggle_off_means_no_messages():
    assert not nudge.wants_messages({"telegram_chat_id": 1, "notify_digest": False,
                                     "notify_weekly": False, "notify_alerts": False})
    assert nudge.wants_messages({"telegram_chat_id": 1, "notify_digest": False})
    assert not nudge.wants_messages({"notify_digest": True})


# ---------------------------------------------------------------- what


def test_render_with_a_book_en():
    data = nudge.NudgeData(
        days=9, number=1, total=104_820.0, week=(1_940.0, 0.0189),
        mover=("NVDA", 1_240.0, 0.081),
    )
    text = nudge.render(data, "en", ORIGIN)
    assert text.startswith(
        "<b>👋 TopStocks — still here</b>\n9 days since your last visit."
    )
    assert "Portfolio €104,820 · week +1,940 € (+1.89%)." in text
    link = '<a href="https://topstocks.example/ticker?ticker=NVDA">NVDA</a>'
    assert f"Biggest move: {link} +8.1%." in text
    assert "Last reminder" not in text
    assert nudge.buttons(data, "en", ORIGIN) == [
        ("Portfolio", "https://topstocks.example/portfolio")
    ]


def test_render_empty_book_es_and_the_last_reminder_says_so():
    data = nudge.NudgeData(days=14, number=2)
    text = nudge.render(data, "es", ORIGIN)
    assert "14 días desde tu última visita." in text
    assert "Tu libro sigue vacío" in text
    assert "Último aviso de este tipo" in text
    assert nudge.buttons(data, "es", ORIGIN) == [
        ("Importar extracto", "https://topstocks.example/import_transactions")
    ]


def test_render_escapes_the_ticker_and_drops_a_mover_without_a_percent():
    data = nudge.NudgeData(
        days=8, number=1, total=10.0, week=None, mover=("A&B", 1.0, None),
    )
    text = nudge.render(data, "en", None)
    assert "Biggest move" not in text
    assert "week –." in text
    data.mover = ("A&B", 1.0, 0.02)
    assert "A&amp;B +2.0%" in nudge.render(data, "en", None)


def test_buttons_are_empty_without_an_origin(monkeypatch):
    monkeypatch.setattr(nudge.links, "app_base", lambda: None)
    assert nudge.buttons(nudge.NudgeData(days=8, number=1), "en") == []


# ---------------------------------------------------------------- fan-out


def _user(tmp_path, slug, prefs):
    root = tmp_path / "users" / slug
    root.mkdir(parents=True)
    (root / "prefs.json").write_text(json.dumps(prefs))
    return root


@pytest.fixture
def local(monkeypatch, tmp_path):
    from stocks import storage

    monkeypatch.setattr(storage, "_cached", {"config": None})
    monkeypatch.setattr(fanout, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(fanout, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fanout, "WATCHLIST_FILE", tmp_path / "watchlist.yaml")
    monkeypatch.setattr(
        weekly_mod, "compute_weekly_data",
        lambda watchlist, db, base="EUR", today=None: weekly_mod.WeeklyData(
            date=today or TODAY, total=5_000.0, week=(50.0, 0.01),
            best=[("KO", 20.0, 0.012)],
        ),
    )
    return tmp_path


def test_fanout_sends_once_and_records_it(local, monkeypatch):
    _user(local, "jane_ab12cd34", {"telegram_chat_id": 111, "last_seen": "2026-10-01"})
    _user(local, "bob_ef56ab78", {"telegram_chat_id": 222, "last_seen": "2026-10-20"})
    _user(local, "eve_12345678", {"last_seen": "2026-10-01"})  # not linked
    sent = []
    monkeypatch.setattr(
        nudge.telegram, "send_message",
        lambda text, chat_id, parse_mode=None, buttons=None: sent.append((chat_id, text)),
    )
    monkeypatch.setattr(nudge.telegram, "pace", lambda: None)
    assert nudge.run_nudge_fanout(today=TODAY) == {
        "jane_ab12cd34": "sent #1", "bob_ef56ab78": "skipped: active",
    }
    assert [c for c, _ in sent] == [111]
    assert "20 days since your last visit." in sent[0][1]
    state = json.loads((local / "users/jane_ab12cd34/alerts_state.json").read_text())
    assert len(state["nudges"]) == 1

    # The same day again: nothing new goes out.
    again = nudge.run_nudge_fanout(today=TODAY)
    assert again["jane_ab12cd34"] == "skipped: already nudged"
    assert len(sent) == 1


def test_fanout_dry_run_sends_nothing(local, monkeypatch, capsys):
    _user(local, "jane_ab12cd34", {"telegram_chat_id": 111, "last_seen": "2026-10-01"})
    monkeypatch.setattr(
        nudge.telegram, "send_message",
        lambda *a, **kw: pytest.fail("dry run must not send"),
    )
    status = nudge.run_nudge_fanout(dry_run=True, today=TODAY)
    assert status == {"jane_ab12cd34": "dry-run"}
    assert "jane_ab12cd34" in capsys.readouterr().out
    assert not (local / "users/jane_ab12cd34/alerts_state.json").exists()


def test_fanout_marks_a_blocked_account(local, monkeypatch):
    _user(local, "jane_ab12cd34", {"telegram_chat_id": 111, "last_seen": "2026-10-01"})

    def blocked(*a, **kw):
        raise nudge.telegram.TelegramBlocked("blocked")

    monkeypatch.setattr(nudge.telegram, "send_message", blocked)
    monkeypatch.setattr(nudge.telegram, "pace", lambda: None)
    assert nudge.run_nudge_fanout(today=TODAY) == {"jane_ab12cd34": "blocked"}
    state = json.loads((local / "users/jane_ab12cd34/alerts_state.json").read_text())
    assert state["delivery"]["blocked"] is True
    assert "nudges" not in state
    assert nudge.run_nudge_fanout(today=TODAY) == {"jane_ab12cd34": "skipped: blocked"}


def test_fanout_still_writes_when_the_book_cannot_be_computed(local, monkeypatch):
    _user(local, "jane_ab12cd34", {"telegram_chat_id": 111, "last_seen": "2026-10-01"})

    def boom(*a, **kw):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(weekly_mod, "compute_weekly_data", boom)
    sent = []
    monkeypatch.setattr(
        nudge.telegram, "send_message",
        lambda text, chat_id, parse_mode=None, buttons=None: sent.append(text),
    )
    monkeypatch.setattr(nudge.telegram, "pace", lambda: None)
    assert nudge.run_nudge_fanout(today=TODAY) == {"jane_ab12cd34": "sent #1"}
    assert "Your book is still empty" in sent[0]
