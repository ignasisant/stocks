"""The memo every account shares: its file, its bucket copy, its expiry."""

from __future__ import annotations

import json
import time

import pytest

from stocks import storage
from stocks.data.shared_memo import SharedMemo


@pytest.fixture
def bucket(monkeypatch):
    """An in-memory stand-in for the storage bucket, keyed by file name."""
    held: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "enabled", lambda: True)
    monkeypatch.setattr(storage, "read", lambda path: held.get(path.name))
    monkeypatch.setattr(
        storage, "persist", lambda path: held.__setitem__(path.name, path.read_bytes())
    )
    return held


def _memo(tmp_path, **kw) -> SharedMemo:
    return SharedMemo(
        tmp_path / "memo.json",
        ttl=kw.pop("ttl", 60.0),
        cap=kw.pop("cap", 10),
        flush_s=3600.0,
    )


def test_an_answer_stands_until_it_expires(tmp_path):
    memo = _memo(tmp_path)
    memo.put("A", [1])
    memo.put("B", [2], ttl=-1.0)
    assert memo.get("A") == [1]
    assert memo.get("B") is None
    assert memo.get("C") is None


def test_a_new_process_reads_back_what_the_last_one_flushed(tmp_path):
    memo = _memo(tmp_path)
    memo.put("A", [1])
    memo.flush()
    memo.clear()
    assert _memo(tmp_path).get("A") == [1]


def test_a_flush_keeps_what_another_instance_pushed(tmp_path, bucket):
    one, two = _memo(tmp_path / "one"), _memo(tmp_path / "two")
    one.put("A", [1])
    one.flush()
    two.put("B", [2])
    two.flush()
    stored = json.loads(bucket["memo.json"])["entries"]
    assert set(stored) == {"A", "B"}
    assert two.get("A") == [1]  # and the flusher learns the other's keys


def test_a_failed_bucket_read_pushes_nothing(tmp_path, bucket, monkeypatch):
    memo = _memo(tmp_path)
    memo.put("A", [1])

    def down(_path):
        raise OSError("bucket unreachable")

    monkeypatch.setattr(storage, "read", down)
    with pytest.raises(OSError):
        memo.flush()
    assert "memo.json" not in bucket
    monkeypatch.setattr(storage, "read", lambda path: bucket.get(path.name))
    memo.flush()  # still dirty, so the next flush carries it
    assert "A" in json.loads(bucket["memo.json"])["entries"]


def test_the_cap_keeps_the_answers_that_stand_longest(tmp_path):
    memo = _memo(tmp_path, cap=2)
    memo.put("old", 1, ttl=10.0)
    memo.put("mid", 2, ttl=20.0)
    memo.put("new", 3, ttl=30.0)
    memo.flush()
    stored = json.loads((tmp_path / "memo.json").read_text())["entries"]
    assert set(stored) == {"mid", "new"}


def test_a_broken_file_is_a_cold_cache(tmp_path):
    (tmp_path / "memo.json").write_text("{not json")
    assert _memo(tmp_path).get("A") is None
    (tmp_path / "memo.json").write_text(
        json.dumps({"v": 0, "entries": {"A": [time.time() + 99, 1]}})
    )
    assert _memo(tmp_path).get("A") is None
