"""Writes a reader never sees half of.

`Path.write_text` truncates the file and then fills it: a reader that opens it
in between — another request thread, the bucket mirror uploading it, a second
process on the same volume — reads nothing, or the first half. Most of the
JSON files here are read on the hot path and forgive only a *missing* file, so
a torn one surfaced as a `JSONDecodeError` on a page that had nothing to do
with it (the logo cache, 2026-09: every ticker cell of a book 500'd).

So every write lands beside its target and is renamed over it. `os.replace`
is atomic within one filesystem, and the temporary sits in the same directory
to keep it on the same one: a reader sees the old file or the new one, whole.
The temporary's name is unique per process and thread, so two writers of one
file cannot tear each other's temporary either — the last rename wins, and
what it leaves is one writer's file, not a splice of both. It starts with a
dot and ends in `.tmp`, so no `*.json` glob or bucket listing mistakes a
half-written one for data.

No `fsync`: the deploys run on an ephemeral filesystem that the bucket mirror
makes durable, so power-loss ordering buys nothing here. What this guards is
the concurrent reader, and for that the rename is enough.

`tests/test_atomic_writes.py` fails on a raw `write_text(json.dumps(…))` in
`src`, so the next cache written the quick way is caught in review, not in
production.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


def _temporary(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")


def write_bytes(path: Path, data: bytes) -> None:
    """Replace `path` with `data` in one step. The directory must exist."""
    path = Path(path)
    tmp = _temporary(path)
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Replace `path` with `text` in one step. The directory must exist."""
    write_bytes(path, text.encode(encoding))


def write_json(path: Path, obj: Any, **dumps: Any) -> None:
    """Replace `path` with `json.dumps(obj, **dumps)` in one step.

    Serialised before anything touches the disk, so an object that will not
    encode raises with the old file still in place.
    """
    write_text(path, json.dumps(obj, **dumps))
