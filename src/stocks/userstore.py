"""One account's JSON files: read forgivingly, edit under a lock, mirror.

Every per-account file (devices, push subscriptions, alert edges, the last
import, shares, the daily card, the journal…) needs the same five things
around its own format, and each module used to write them itself — so each got
a different subset. One locked its read-modify-write and the next did not; one
logged a failed bucket push and the next raised it into the request that had
already saved; one refused the shared guest directory and the next wrote into
every visitor's session at once.

So the file is the unit, and this module owns it:

* `read(path, default)` — the stored value, or `default()` when the file is
  missing, unreadable or not the shape `default` makes. A corrupt file means
  "nothing stored", never an error page.
* `edit(path, default)` — a context manager: the value under a per-path lock,
  written back on a clean exit if it changed. Two requests (or a request and
  the daily card's background job) editing one file queue instead of the later
  undoing the earlier.
* `write(path, value)` — the whole value, refused in the guest directory,
  atomic on disk, then mirrored. `mirror=` swaps the mirror (tests, or a
  caller that must see the bucket fail).
* `persist(path)` — the bucket mirror after a committed local write. A failure
  is logged and swallowed: the local write has landed and the caller's answer
  is true, but the copy vanishes on the next container restart, so the log is
  what tells us.

Within one process. Two processes writing one file (an instance and a job) are
still last-writer-wins; the journal and the push log merge the bucket's copy
before they write because they are the files where that has bitten.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from stocks import atomic, obs, storage

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def lock(path: Path) -> threading.RLock:
    """The lock `edit` holds for `path`; re-entrant, so an edit may call a
    helper that edits the same file."""
    with _locks_guard:
        return _locks.setdefault(str(Path(path).resolve()), threading.RLock())


def read(path: Path, default: Callable[[], Any] = dict) -> Any:
    """What `path` holds, or `default()` when it is missing, unreadable or of
    another type than `default()`."""
    empty = default()
    try:
        value = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return empty
    except (OSError, ValueError, TypeError) as exc:
        obs.warn("userstore.unreadable", file=Path(path).name,
                 error_type=type(exc).__name__)
        return empty
    return value if isinstance(value, type(empty)) else empty


def persist(path: Path) -> None:
    """Mirror one committed local write to the bucket; a failure is logged."""
    try:
        storage.persist(path)
    except Exception as exc:  # noqa: BLE001 — the local copy is good
        obs.warn("storage.persist_failed", file=Path(path).name,
                 error_type=type(exc).__name__)


def write(
    path: Path, value: Any, *, mirror: Callable[[Path], None] | None = None,
    **dumps: Any,
) -> None:
    """Replace `path` with `value` as JSON, then mirror it.

    Refused (`accounts.GuestIsReadOnly`) inside the shared guest directory.
    `dumps` reach `json.dumps`; the default is two-space indent.
    """
    from stocks import accounts

    path = accounts.writable(Path(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(path, value, **(dumps or {"indent": 2}))
    (mirror or persist)(path)


def remove(path: Path, *, mirror: Callable[[Path], None] | None = None) -> None:
    """Delete `path` here and in the bucket."""
    from stocks import accounts

    path = accounts.writable(Path(path))
    path.unlink(missing_ok=True)
    (mirror or persist)(path)


@contextmanager
def edit(
    path: Path, default: Callable[[], Any] = dict, *,
    mirror: Callable[[Path], None] | None = None, **dumps: Any,
) -> Generator[Any]:
    """The value of `path` to change in place, written back if it changed.

    Held under `lock(path)` from the read to the write. An exception inside
    the block writes nothing. A body that has to replace the value rather than
    change it clears and refills it (`value.clear(); value.update(...)`).
    """
    with lock(path):
        value = read(path, default)
        before = json.dumps(value, sort_keys=True, default=str)
        yield value
        if json.dumps(value, sort_keys=True, default=str) != before:
            write(path, value, mirror=mirror, **dumps)
