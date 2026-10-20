"""Answers every account shares, kept across boots and instances.

Some lookups come back the same for everyone and barely move: which listings
Yahoo offers for "asml" is one. Memoised per process, each one costs a network
round-trip on every cold boot of every instance — and Cloud Run scales to
zero, so that is most first searches of the day. A `SharedMemo` keeps them in
one JSON file that rides the storage bucket: read (the local file merged with
the bucket's copy) on first use, and written back at most once every
`flush_s`, on its own thread, so no reader ever waits on an upload.

Merged, not replaced, at both ends: two instances learn different keys in the
same minute, and a push reads the bucket's copy first so neither one drops
what the other learned. On a key both know, the later expiry wins.

Never account data: whatever lands here is served to every account, so a key
or a value must be something any of them could have asked the source for.
"""

from __future__ import annotations

import atexit
import json
import threading
import time
from pathlib import Path
from typing import Any

from stocks import atomic, obs

_VERSION = 1


def _parse(raw: bytes | str | None) -> dict[str, list]:
    """`{key: [expires_at, value]}` from a file's text; {} for anything else.

    A broken or older file is a cold cache, never an error: every entry can be
    asked for again.
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict) or data.get("v") != _VERSION:
        return {}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {
        str(k): v
        for k, v in entries.items()
        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], (int, float))
    }


def _merge(into: dict[str, list], other: dict[str, list]) -> None:
    """Fold `other` into `into`; on a shared key the later expiry wins."""
    for key, entry in other.items():
        mine = into.get(key)
        if mine is None or entry[0] > mine[0]:
            into[key] = entry


class SharedMemo:
    """A string-keyed memo every account and every instance reads.

    `ttl` is how long an answer stands, `cap` how many are kept (the ones
    expiring soonest go first). `put` may set its own ttl — an empty answer
    should not stand as long as a real one.
    """

    def __init__(
        self, path: Path, *, ttl: float, cap: int, flush_s: float = 60.0
    ) -> None:
        self.path = path
        self.ttl = ttl
        self.cap = cap
        self.flush_s = flush_s
        self._entries: dict[str, list] | None = None
        self._lock = threading.Lock()
        # One flush at a time, held across the upload: a second one waits for
        # the first rather than return early while its file is half-way out.
        self._flushing = threading.Lock()
        self._dirty = False
        self._pushed = float("-inf")
        self._timer: threading.Timer | None = None
        atexit.register(self._flush_quiet)

    def get(self, key: str) -> Any | None:
        """The standing answer for `key`, or None."""
        hit = self._load().get(key)
        if hit is None or hit[0] <= time.time():
            return None
        return hit[1]

    def items(self) -> list[tuple[str, Any]]:
        """Every standing `(key, value)`, for a caller that indexes them."""
        now = time.time()
        return [(k, v[1]) for k, v in list(self._load().items()) if v[0] > now]

    def put(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        """Keep `value` for `key`; it reaches the file and bucket shortly."""
        entries = self._load()
        life = self.ttl if ttl is None else ttl
        with self._lock:
            entries[key] = [time.time() + life, value]
            self._dirty = True
            if self._timer is None:
                wait = max(0.0, self.flush_s - (time.monotonic() - self._pushed))
                self._timer = threading.Timer(wait, self._flush_quiet)
                self._timer.daemon = True
                self._timer.start()

    def clear(self) -> None:
        """Forget everything in memory; the next read loads the file again."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._entries, self._dirty, self._timer = None, False, None
            self._pushed = float("-inf")

    def flush(self) -> None:
        """Write what this process learned, merged with the bucket's copy.

        The bucket is read first and a failed read skips the push (the
        entries stay dirty for the next flush): writing blind would replace
        what every other instance learned with this one's subset.
        """
        with self._flushing:
            self._flush()

    def _flush(self) -> None:
        from stocks import storage

        with self._lock:
            self._timer = None
            if not self._dirty or self._entries is None:
                return
            # The path with the entries: a memo pointed elsewhere (a test's
            # scratch) mid-flush must not land these where it used to point.
            path, mine, entries = self.path, dict(self._entries), self._entries
            self._dirty = False
        try:
            theirs = _parse(storage.read(path)) if storage.enabled() else {}
            merged = dict(theirs)
            _merge(merged, mine)
            kept = self._prune(merged)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic.write_json(path, {"v": _VERSION, "entries": kept})
            storage.persist(path)
        except Exception:
            with self._lock:
                self._dirty = self._dirty or self._entries is entries
            raise
        with self._lock:
            self._pushed = time.monotonic()
            if self._entries is entries:
                _merge(entries, theirs)

    def _flush_quiet(self) -> None:
        with obs.swallow("shared_memo.flush", file=self.path.name):
            self.flush()

    def _load(self) -> dict[str, list]:
        """The entries, read once per process: local file, then the bucket."""
        if self._entries is not None:
            return self._entries
        with self._lock:
            if self._entries is None:
                entries = {}
                try:
                    entries = _parse(self.path.read_bytes())
                except OSError:
                    pass
                with obs.swallow("shared_memo.restore", file=self.path.name):
                    from stocks import storage

                    if storage.enabled():
                        _merge(entries, _parse(storage.read(self.path)))
                self._entries = entries
            return self._entries

    def _prune(self, entries: dict[str, list]) -> dict[str, list]:
        """Drop the expired, then keep the `cap` that stand longest."""
        now = time.time()
        live = [(k, v) for k, v in entries.items() if v[0] > now]
        live.sort(key=lambda item: item[1][0], reverse=True)
        return dict(sorted(live[: self.cap]))
