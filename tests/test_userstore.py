"""The per-account JSON file: forgiving reads, locked edits, guarded writes,
a mirror whose failure is logged rather than raised."""

from __future__ import annotations

import json
import threading

import pytest

from stocks import accounts, obs, storage, userstore


@pytest.fixture
def mirrored(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(storage, "persist", lambda p: seen.append(p.name))
    return seen


def test_a_missing_corrupt_or_misshapen_file_reads_as_the_default(tmp_path):
    path = tmp_path / "x.json"
    assert userstore.read(path) == {}
    path.write_text("{not json")
    assert userstore.read(path) == {}
    path.write_text("[1, 2]")
    assert userstore.read(path) == {}
    assert userstore.read(path, list) == [1, 2]


def test_write_is_mirrored_and_reads_back(tmp_path, mirrored):
    path = tmp_path / "deep" / "x.json"
    userstore.write(path, {"a": 1})
    assert userstore.read(path) == {"a": 1}
    assert mirrored == ["x.json"]


def test_an_edit_that_changes_nothing_writes_nothing(tmp_path, mirrored):
    path = tmp_path / "x.json"
    userstore.write(path, {"a": 1})
    with userstore.edit(path) as value:
        value["a"] = 1
    assert mirrored == ["x.json"]
    with userstore.edit(path) as value:
        value["b"] = 2
    assert userstore.read(path) == {"a": 1, "b": 2}
    assert mirrored == ["x.json", "x.json"]


def test_an_edit_that_raises_writes_nothing(tmp_path, mirrored):
    path = tmp_path / "x.json"
    with pytest.raises(RuntimeError), userstore.edit(path) as value:
        value["a"] = 1
        raise RuntimeError
    assert not path.exists() and mirrored == []


def test_concurrent_edits_of_one_file_all_land(tmp_path, mirrored):
    path = tmp_path / "x.json"

    def bump():
        for _ in range(25):
            with userstore.edit(path) as value:
                value["n"] = value.get("n", 0) + 1

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert userstore.read(path) == {"n": 100}


def test_the_guest_directory_is_never_written(tmp_path, monkeypatch, mirrored):
    monkeypatch.setattr(accounts, "GUEST_DIR", tmp_path / "guest")
    path = tmp_path / "guest" / "x.json"
    with pytest.raises(accounts.GuestIsReadOnly):
        userstore.write(path, {"a": 1})
    with pytest.raises(accounts.GuestIsReadOnly):
        userstore.remove(path)
    assert not path.exists() and mirrored == []


def test_a_failed_mirror_is_logged_not_raised(tmp_path, monkeypatch):
    warned: list[tuple[str, dict]] = []
    monkeypatch.setattr(storage, "persist", lambda p: 1 / 0)
    monkeypatch.setattr(obs, "warn", lambda event, **kw: warned.append((event, kw)))
    path = tmp_path / "x.json"
    userstore.write(path, {"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}
    assert warned == [("storage.persist_failed",
                       {"file": "x.json", "error_type": "ZeroDivisionError"})]


def test_remove_deletes_here_and_in_the_bucket(tmp_path, mirrored):
    path = tmp_path / "x.json"
    userstore.write(path, {"a": 1})
    userstore.remove(path)
    assert not path.exists()
    assert mirrored == ["x.json", "x.json"]
