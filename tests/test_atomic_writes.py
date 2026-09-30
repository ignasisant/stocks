"""Files a reader opens while they are being written.

The logo cache was written with a plain `write_text`: a request that read it
mid-write got half a JSON document, and every ticker cell of that page 500'd.
The fix is one helper (`stocks.atomic`); the guard below is what keeps the
next cache from being written the quick way.
"""

import json
import re
import threading
from pathlib import Path

import pytest

from stocks import atomic

SRC = Path(__file__).resolve().parents[1] / "src"

# A whole-file write of structured data, spelled the way that truncates first.
_RAW = re.compile(
    r"\.write_text\(\s*(?:json\.dumps|yaml_dump)\("  # path.write_text(json.dumps(…))
    r"|\bjson\.dump\("  # json.dump(obj, open_file)
)


def test_no_structured_file_is_written_in_place():
    offenders = [
        f"{path.relative_to(SRC)}:{number}: {line.strip()}"
        for path in sorted(SRC.rglob("*.py"))
        if path.name != "atomic.py"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if _RAW.search(line)
    ]
    assert not offenders, (
        "write through stocks.atomic (write_json / write_text) so a reader "
        "never sees half a file:\n" + "\n".join(offenders)
    )


def test_a_reader_sees_the_old_file_or_the_new_one_whole(tmp_path):
    target = tmp_path / "cache.json"
    atomic.write_json(target, {"n": 0})
    small, big = {"n": 1}, {"n": 2, "pad": "x" * 200_000}
    torn: list[str] = []
    stop = threading.Event()

    def read() -> None:
        while not stop.is_set():
            try:
                json.loads(target.read_text())
            except json.JSONDecodeError as exc:
                torn.append(str(exc))

    readers = [threading.Thread(target=read) for _ in range(2)]
    for reader in readers:
        reader.start()
    try:
        for i in range(200):
            atomic.write_json(target, big if i % 2 else small)
    finally:
        stop.set()
        for reader in readers:
            reader.join()
    assert not torn
    assert json.loads(target.read_text()) == big


def test_concurrent_writers_leave_one_writers_file_and_no_temporaries(tmp_path):
    target = tmp_path / "cache.json"
    payloads = [{"writer": n, "pad": str(n) * 50_000} for n in range(4)]
    threads = [
        threading.Thread(
            target=lambda p=p: [atomic.write_json(target, p) for _ in range(20)]
        )
        for p in payloads
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert json.loads(target.read_text()) in payloads
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def test_an_object_that_will_not_encode_leaves_the_old_file(tmp_path):
    target = tmp_path / "cache.json"
    atomic.write_json(target, {"kept": True})
    with pytest.raises(TypeError):
        atomic.write_json(target, {"bad": object()})
    assert json.loads(target.read_text()) == {"kept": True}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def test_a_failed_rename_cleans_up_its_temporary(tmp_path, monkeypatch):
    target = tmp_path / "cache.json"
    atomic.write_json(target, {"kept": True})

    def refuse(src, dst):
        raise OSError("disk says no")

    monkeypatch.setattr(atomic.os, "replace", refuse)
    with pytest.raises(OSError):
        atomic.write_json(target, {"new": True})
    assert json.loads(target.read_text()) == {"kept": True}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]
