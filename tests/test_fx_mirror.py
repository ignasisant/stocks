"""`data.fx`: the rate history's copy in the bucket.

A container starts without the file, and without the copy every rate ever
asked for was asked of the ECB again, one request and one rewrite of the
file per date, inside whichever request wanted it. Restored once when the
file is missing; mirrored at most once per window after a save.
"""

from __future__ import annotations

import json

import pytest

from stocks import storage
from stocks.data import fx


@pytest.fixture
def history(tmp_path, monkeypatch):
    path = tmp_path / "fx_history.json"
    monkeypatch.setattr(fx, "FX_CACHE", path)
    monkeypatch.setattr(fx, "_mirrored_at", 0.0)
    monkeypatch.setattr(fx, "_mirror_timer", None)
    yield path
    if fx._mirror_timer is not None:
        fx._mirror_timer.cancel()


def test_a_missing_file_is_restored_from_the_bucket_once(history, monkeypatch):
    monkeypatch.setattr(storage, "enabled", lambda: True)
    asked: list = []

    def restore(path):
        asked.append(path)
        path.write_text(json.dumps({"EURUSD:2026-01-02": 1.1}))
        return True

    monkeypatch.setattr(storage, "restore", restore)
    assert fx._load_cache() == {"EURUSD:2026-01-02": 1.1}
    assert fx._load_cache() == {"EURUSD:2026-01-02": 1.1}
    assert asked == [history], "on disk after the first"


def test_a_restore_that_fails_is_an_empty_history(history, monkeypatch):
    monkeypatch.setattr(storage, "enabled", lambda: True)

    def restore(path):
        raise OSError("bucket down")

    monkeypatch.setattr(storage, "restore", restore)
    assert fx._load_cache() == {}


def test_saves_are_mirrored_at_most_once_per_window(history, monkeypatch):
    monkeypatch.setattr(storage, "enabled", lambda: True)
    pushed: list = []
    monkeypatch.setattr(storage, "persist", pushed.append)
    fx._save_cache({"a": 1.0})
    assert pushed == [history], "the first save goes at once"
    fx._save_cache({"a": 1.0, "b": 2.0})
    fx._save_cache({"a": 1.0, "b": 2.0, "c": 3.0})
    assert pushed == [history], "inside the window: one timer, no copy yet"
    timer = fx._mirror_timer
    assert timer is not None
    timer.cancel()
    fx._mirror_now()
    assert pushed == [history, history]
    assert fx._mirror_timer is None
    assert json.loads(history.read_text()) == {"a": 1.0, "b": 2.0, "c": 3.0}


def test_a_mirror_that_fails_does_not_fail_the_save(history, monkeypatch):
    monkeypatch.setattr(storage, "enabled", lambda: True)

    def persist(path):
        raise RuntimeError("no bucket")

    monkeypatch.setattr(storage, "persist", persist)
    fx._save_cache({"a": 1.0})
    assert json.loads(history.read_text()) == {"a": 1.0}


def test_without_a_bucket_nothing_is_asked_or_mirrored(history, monkeypatch):
    touched: list = []
    monkeypatch.setattr(storage, "persist", touched.append)
    monkeypatch.setattr(storage, "restore", touched.append)
    assert fx._load_cache() == {}
    fx._save_cache({"a": 1.0})
    assert touched == []
