"""Dormant-account reminder (stocks.notify.nudge)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from stocks.notify import fanout, nudge
from stocks.notify import state as state_mod
from stocks.notify import weekly as weekly_mod

TODAY = date(2026, 10, 21)


def _state(**over) -> dict:
    s = state_mod.load_state(__import__("pathlib").Path("/nonexistent"))
    s.update(over)
    return s


# ---------------------------------------------------------------- when


def test_an_account_never_seen_on_the_web_is_left_alone():
    assert nudge.due(_state(), {"currency": "EUR"}, TODAY) is None


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


def test_every_toggle_off_or_no_device_means_no_messages():
    off = {"notify_digest": False, "notify_weekly": False, "notify_alerts": False}
    assert not nudge.wants_messages(off, devices=1)
    assert nudge.wants_messages({"notify_digest": False}, devices=1)
    assert not nudge.wants_messages({"notify_digest": True}, devices=0)


# ---------------------------------------------------------------- what


def test_render_with_a_book_en():
    data = nudge.NudgeData(
        days=9, number=1, total=104_820.0, week=(1_940.0, 0.0189),
        mover=("NVDA", 1_240.0, 0.081),
    )
    message = nudge.render(data, "en")
    assert message["title"] == "TopStocks — still here"
    assert message["body"].splitlines() == [
        "9 days since your last visit.",
        "Portfolio €104,820 · week +1,940 € (+1.89%).",
        "Biggest move: NVDA +8.1%.",
    ]
    assert message["url"] == "/portfolio"
    assert message["tag"] == "nudge"


def test_render_empty_book_es_and_the_last_reminder_says_so():
    message = nudge.render(nudge.NudgeData(days=14, number=2), "es")
    lines = message["body"].splitlines()
    assert lines[0] == "14 días desde tu última visita."
    # The farewell rides on the last line rather than taking one of its own.
    assert lines[1].startswith("Tu libro sigue vacío")
    assert "Último aviso de este tipo" in lines[1]
    assert message["url"] == "/import_transactions"


def test_render_drops_a_mover_without_a_percent():
    data = nudge.NudgeData(
        days=8, number=1, total=10.0, week=None, mover=("A&B", 1.0, None),
    )
    message = nudge.render(data, "en")
    assert "Biggest move" not in message["body"]
    assert "week –." in message["body"]
    data.mover = ("A&B", 1.0, 0.02)
    assert "A&B +2.0%" in nudge.render(data, "en")["body"]


# ---------------------------------------------------------------- fan-out


def _user(tmp_path, slug, prefs, devices=1):
    root = tmp_path / "users" / slug
    root.mkdir(parents=True)
    (root / "prefs.json").write_text(json.dumps(prefs))
    if devices:
        rows = {f"row{i}": {"endpoint": f"https://push.example/{i}"}
                for i in range(devices)}
        (root / "push.json").write_text(json.dumps({"subscriptions": rows}))
    return root


@pytest.fixture
def pushed(monkeypatch):
    """Record every push instead of sending it; each reaches one device."""
    sent: list[tuple[str, dict]] = []

    def send_all(path, message, *, topic=""):
        assert topic == "nudge"
        sent.append((path.parent.name, message))
        return 1

    monkeypatch.setattr(nudge.webpush, "send_all", send_all)
    return sent


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


def test_fanout_sends_once_and_records_it(local, pushed):
    _user(local, "jane_ab12cd34", {"last_seen": "2026-10-01"})
    _user(local, "bob_ef56ab78", {"last_seen": "2026-10-20"})
    _user(local, "eve_12345678", {"last_seen": "2026-10-01"}, devices=0)  # no device
    assert nudge.run_nudge_fanout(today=TODAY) == {
        "jane_ab12cd34": "sent #1", "bob_ef56ab78": "skipped: active",
    }
    assert [slug for slug, _ in pushed] == ["jane_ab12cd34"]
    assert pushed[0][1]["body"].startswith("20 days since your last visit.")
    state = json.loads((local / "users/jane_ab12cd34/alerts_state.json").read_text())
    assert len(state["nudges"]) == 1

    # The same day again: nothing new goes out.
    again = nudge.run_nudge_fanout(today=TODAY)
    assert again["jane_ab12cd34"] == "skipped: already nudged"
    assert len(pushed) == 1


def test_fanout_dry_run_sends_nothing(local, monkeypatch, capsys):
    _user(local, "jane_ab12cd34", {"last_seen": "2026-10-01"})
    monkeypatch.setattr(
        nudge.webpush, "send_all",
        lambda *a, **kw: pytest.fail("dry run must not send"),
    )
    status = nudge.run_nudge_fanout(dry_run=True, today=TODAY)
    assert status == {"jane_ab12cd34": "dry-run"}
    assert "jane_ab12cd34" in capsys.readouterr().out
    assert not (local / "users/jane_ab12cd34/alerts_state.json").exists()


def test_an_undelivered_nudge_is_not_counted(local, monkeypatch, pushed):
    """A reminder no device took was never read: it must not use up one of
    the two, and tomorrow's run tries again."""
    _user(local, "jane_ab12cd34", {"last_seen": "2026-10-01"})
    sent = nudge.webpush.send_all
    monkeypatch.setattr(nudge.webpush, "send_all", lambda *a, **kw: 0)
    assert nudge.run_nudge_fanout(today=TODAY) == {"jane_ab12cd34": "not delivered"}
    state = state_mod.load_state(local / "users/jane_ab12cd34/alerts_state.json")
    assert state_mod.nudges_sent(state) == []

    monkeypatch.setattr(nudge.webpush, "send_all", sent)
    assert nudge.run_nudge_fanout(today=TODAY) == {"jane_ab12cd34": "sent #1"}


def test_fanout_still_writes_when_the_book_cannot_be_computed(
    local, monkeypatch, pushed
):
    _user(local, "jane_ab12cd34", {"last_seen": "2026-10-01"})

    def boom(*a, **kw):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(weekly_mod, "compute_weekly_data", boom)
    assert nudge.run_nudge_fanout(today=TODAY) == {"jane_ab12cd34": "sent #1"}
    assert "Your book is still empty" in pushed[0][1]["body"]
    assert pushed[0][1]["url"] == "/import_transactions"
