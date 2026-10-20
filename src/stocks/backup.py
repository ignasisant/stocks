"""Point-in-time snapshots of the persistence bucket, and their restore path.

The bucket behind stocks.storage is a mirror, not a backup: every write —
including a corrupt portfolio.db or a bad migration — syncs to it immediately
and replaces the only copy. R2 has no bucket versioning, so this module keeps
history the plain way: a daily (cron) or on-demand server-side copy of every
live object under a stamped prefix,

    backups/2026-08-31T04-17-02Z/data/users/<slug>/portfolio.db
    backups/2026-08-31T04-17-02Z/watchlist.yaml
    ...

and a restore that copies one stamp's tree back over the live keys. Copies are
CopyObject calls — no object bytes ever travel through the job runner.

Run from the CLI (`stocks backup run|list|restore`) and from the scheduled
workflow (.github/workflows/backup.yml). Everything here needs [storage]
configured; without it the commands refuse rather than silently do nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from stocks import obs, storage

PREFIX = "backups/"
KEEP_DEFAULT = 30  # snapshots retained by prune (roughly a month of dailies)

# CopyObject calls in flight at once. Each is one round trip to R2 for a
# server-side copy, so the job is latency-bound: a serial loop over every
# live object outgrew the cron's timeout as accounts grew. Below
# storage.MAX_POOL so the client never queues on its own connections.
WORKERS = 16


def _each(fn: Callable[[str], None], keys: Iterable[str]) -> int:
    """Apply `fn` to every key, WORKERS at a time; returns the count.

    The first failure propagates (the map re-raises when it reaches it), so a
    run that could not copy something ends loud rather than with a snapshot
    that quietly misses an account.
    """
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return sum(1 for _ in pool.map(fn, keys))


def _require_storage() -> None:
    if not storage.enabled():
        raise RuntimeError(
            "[storage] is not configured — backups snapshot the persistence "
            "bucket, so there is nothing to back up (set STOCKS_STORAGE_* or "
            "the [storage] secrets)."
        )


def _stamp(now: float | None = None) -> str:
    """UTC timestamp usable as a key segment (no colons: S3 keys allow them,
    but every shell/urls quoting problem starts there)."""
    return time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime(now))


# The API's persisted memos (stocks.api.cache): price frames that refetch
# themselves, mirrored so a fresh host can answer while Yahoo says no. Not
# user data — a snapshot that carried them would grow by megabytes a day for
# nothing anyone would ever restore.
MEMO_PREFIX = "data/memo/"


def live_keys() -> list[str]:
    """Every key that belongs to the live tree (i.e. not a snapshot)."""
    return [
        k
        for k in storage.list_keys()
        if not k.startswith(PREFIX) and not k.startswith(MEMO_PREFIX)
    ]


def snapshots() -> list[str]:
    """Existing snapshot stamps, oldest first."""
    stamps = {
        k.removeprefix(PREFIX).split("/", 1)[0]
        for k in storage.list_keys(PREFIX)
        if "/" in k.removeprefix(PREFIX)
    }
    return sorted(stamps)


def run(keep: int = KEEP_DEFAULT) -> tuple[str, int]:
    """Snapshot every live object under a new stamp; prune to `keep` stamps.

    Returns (stamp, object count). The snapshot is written before anything is
    pruned, so an interrupted run can only ever leave an extra snapshot, never
    fewer than `keep`.
    """
    _require_storage()
    stamp = _stamp()
    keys = live_keys()
    with obs.timed("backup.run", stamp=stamp, objects=len(keys)):
        _each(lambda key: storage.copy_key(key, f"{PREFIX}{stamp}/{key}"), keys)
    prune(keep)
    return stamp, len(keys)


def prune(keep: int = KEEP_DEFAULT) -> list[str]:
    """Drop the oldest snapshots beyond `keep`; returns the stamps removed."""
    _require_storage()
    if keep < 1:
        raise ValueError("keep must be >= 1 — pruning everything is deletion")
    doomed = snapshots()[:-keep]
    for stamp in doomed:
        _each(storage.delete_key, storage.list_keys(f"{PREFIX}{stamp}/"))
        obs.event("backup.prune", stamp=stamp)
    return doomed


def restore(stamp: str, only: str = "") -> int:
    """Copy one snapshot's objects back over the live keys; returns the count.

    `only` narrows the restore to live keys under that prefix (e.g.
    "data/users/jane_example_com_1a2b3c4d/" for a single account). Keys the
    snapshot holds are overwritten; live keys the snapshot lacks are left
    alone — a restore never deletes.

    A running app process keeps its local files (which it treats as
    authoritative) until it restarts, so restore + redeploy/restart is the
    full procedure — see README "Backups".
    """
    _require_storage()
    if stamp not in snapshots():
        raise ValueError(
            f"no snapshot {stamp!r} — `stocks backup list` shows what exists"
        )
    src_prefix = f"{PREFIX}{stamp}/{only}"
    fields: dict[str, Any] = {"only": only} if only else {}
    with obs.timed("backup.restore", stamp=stamp, **fields):
        return _each(
            lambda key: storage.copy_key(key, key.removeprefix(f"{PREFIX}{stamp}/")),
            storage.list_keys(src_prefix),
        )
