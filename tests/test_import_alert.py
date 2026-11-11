"""Owner email when an upload gets nowhere (stocks.notify.import_alert)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from stocks import obs
from stocks.notify import import_alert

USER = "ana_7f3a"


@pytest.fixture
def alert(tmp_path, monkeypatch):
    """Every incident line and every held-back one, recorded."""
    monkeypatch.setattr(import_alert, "STATE", tmp_path / "import_watch.json")
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(obs, "event", lambda name, **f: events.append((name, f)))
    monkeypatch.setattr(obs, "warn", lambda name, **f: events.append((name, f)))
    with obs.context(user=USER):
        yield events


def _fp(**extra):
    return {"user": USER, "surface": "import", "file": "export_##.csv", "ext": "csv",
            "bytes": 2048, "platform": "trade_republic", **extra}


def _stuck(events):
    return [f for name, f in events if name == "import.stuck"]


def _quiet(events):
    return [f["why"] for name, f in events if name == "import.stuck_quiet"]


def test_a_failure_is_one_incident_a_day(alert):
    import_alert.failed(_fp(id="abc", reasons={"bad header": 3}),
                        stage="nothing_importable", digest="d" * 64)
    import_alert.failed(_fp(id="abc"), stage="nothing_importable", digest="d" * 64)

    line, = _stuck(alert)
    assert (line["kind"], line["user"], line["stage"]) == (
        "failed", USER, "nothing_importable")
    assert (line["diagnostic_id"], line["top_reason"]) == ("abc", "bad header ×3")
    assert _quiet(alert) == ["repeat"]


def test_another_file_from_the_same_account_is_its_own_incident(alert):
    import_alert.failed(_fp(), stage="crash", digest="a" * 64)
    import_alert.failed(_fp(), stage="crash", digest="b" * 64)

    assert len(_stuck(alert)) == 2


def test_the_hourly_cap_holds(alert, monkeypatch):
    monkeypatch.setattr(import_alert, "HOURLY_CAP", 2)

    for n in range(3):
        import_alert.failed(_fp(), stage="crash", digest=f"{n}" * 64)

    assert len(_stuck(alert)) == 2
    assert _quiet(alert) == ["hourly_cap"]


def test_e2e_accounts_are_never_an_incident(alert):
    import_alert.failed(_fp(user="e2e_1731_42_import"), stage="crash")

    assert _stuck(alert) == []
    assert _quiet(alert) == ["test_account"]


def test_an_uncommitted_preview_is_reported_after_the_wait(alert):
    import_alert.previewed(_fp(), digest="e" * 64, importable=12,
                           platform="trade_republic")
    started = import_alert._now()

    assert import_alert.sweep(started + timedelta(minutes=5)) == 0
    assert import_alert.sweep(started + import_alert.ABANDON_AFTER) == 1
    assert import_alert.sweep(started + timedelta(hours=2)) == 0

    line, = _stuck(alert)
    assert (line["kind"], line["user"], line["importable"]) == (
        "abandoned", USER, 12)


def test_a_commit_clears_the_watch(alert):
    import_alert.previewed(_fp(), digest="e" * 64, importable=3, platform="degiro")

    import_alert.committed()

    assert import_alert.sweep(import_alert._now() + timedelta(hours=1)) == 0
    assert _stuck(alert) == []
    assert any(name == "import.watch_cleared" for name, _ in alert)


def test_a_failure_replaces_the_watch_so_it_is_told_once(alert):
    import_alert.previewed(_fp(), digest="e" * 64, importable=3, platform="degiro")

    import_alert.failed(_fp(), stage="commit_no_broker", digest="e" * 64)

    assert import_alert.sweep(import_alert._now() + timedelta(hours=1)) == 0
    assert len(_stuck(alert)) == 1


def test_a_stale_preview_is_dropped_without_an_incident(alert):
    import_alert.previewed(_fp(), digest="e" * 64, importable=3, platform="degiro")

    later = import_alert._now() + import_alert.FORGET_AFTER + timedelta(minutes=1)
    assert import_alert.sweep(later) == 0
    assert _stuck(alert) == []


def test_every_label_the_policy_extracts_is_on_the_line(alert):
    import json
    from pathlib import Path

    policy = json.loads((Path(__file__).resolve().parents[1] / "infra" / "monitoring"
                         / "policy-import-stuck.json").read_text())
    labels = policy["conditions"][0]["conditionMatchedLog"]["labelExtractors"]
    import_alert.failed(_fp(id="abc", reasons={"r": 1}), stage="crash")

    line, = _stuck(alert)
    missing = [k for k, v in labels.items()
               if v != f"EXTRACT(jsonPayload.{k})" or k not in line]
    assert not missing


def test_nothing_raises_when_the_state_is_unwritable(alert, monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(import_alert, "STATE", blocker / "import_watch.json")

    import_alert.previewed(_fp(), digest="e", importable=1, platform="x")
    import_alert.committed()
    assert import_alert.sweep() == 0
    import_alert.failed(_fp(), stage="crash")
