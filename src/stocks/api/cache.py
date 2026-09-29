"""A tiny TTL memo — what `st.cache_data` does, without Streamlit.

The page loaders in `stocks.web.portfolio_data` are all wrapped in
`@st.cache_data`, and for good reason: a ledger replay plus a price burst for
a whole book is seconds of work and a pile of Yahoo requests. That decorator
needs a script run to key against, so it cannot cross into an ASGI worker.

This is the replacement, kept deliberately small: one dict, one lock, a TTL
and a cap. Keying follows the same convention as the pages — `(db path,
ledger mtime, base currency)` — so an import invalidates a book's entries the
moment the file changes rather than when a timer runs out.

Three things `st.cache_data` never had to solve:

* The shell opens a page as a dozen concurrent requests, and on a cold
  process every one of them misses the same key at the same moment. A memo
  that only *stores* results lets each of them compute its own — measured
  2026-09-27 as nine bulk downloads of one book (523 Yahoo requests for 76
  distinct URLs) behind a single cold Home, which is also the burst that
  trips Yahoo's throttle and the memory spike that has the container killed.
  So a miss is single-flight: the first caller computes, the rest wait for
  that result and share it, exception included.

* An entry that has just expired is not worthless. The reader who lands on
  minute sixteen used to pay the whole download in their request; now they
  get the fifteen-minute-old figure at once and the refresh lands in the
  background for whoever asks next (stale-while-revalidate). How long past
  its ttl an entry may still stand in is `stale_s`, three ttls by default.

* The source says no. Yahoo throttles a host for minutes at a time, and a
  memo that only lives in memory has nothing to offer when that lands on a
  fresh process — which is when it lands, because the cooldown and the
  restart are both what a burst produces. A memo declared `persist=<name>`
  lands every entry on disk under `data/memo/<name>/` and mirrors it to the
  storage bucket, and a new process reads it back. Past the stale window the
  fetch is still attempted first; only when it *fails* does the old entry
  come back, for up to `keep_s`, and the request is marked (`STALE`) so the
  response can say how old the figure is rather than pass it off as today's.
"""

from __future__ import annotations

import hashlib
import pickle
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar, cast

from stocks import obs
from stocks.config import DATA_DIR

F = TypeVar("F", bound=Callable[..., Any])

# `(stamp, value)` or `(stamp, value, wall[, since])`: the stamp is whatever
# `fresh` reads (a monotonic clock here, an object identity in
# `loaders._on_download`); the wall time is what a persisted entry's age is
# measured by across processes; `since` is set on an entry that was *built
# from* a salvaged one — a book priced off frames the source refused to
# refresh — so serving it marks the request just as serving the salvaged
# frames did. Staleness is a property of the figure, not of the request that
# first noticed it.
Entry = tuple

MEMO_DIR = DATA_DIR / "memo"
DISK_MAX_FILES = 256
KEEP_DEFAULT_S = 3 * 86400.0

# The marker. The API middleware sets a fresh holder per request; a memo that
# serves a salvaged entry writes its wall time into it, and the response goes
# out with `X-Data-Stale-Since`. A holder rather than a value because the
# sync routes run on a worker thread under a *copy* of the context: the
# reference is shared, a rebinding would not be.
STALE: ContextVar[dict[str, float] | None] = ContextVar("stale", default=None)


def mark_stale(wall: float) -> None:
    holder = STALE.get()
    if holder is not None:
        holder["since"] = min(holder.get("since", wall), wall)


class Flight:
    """One in-progress computation: what the followers of a miss wait on."""

    __slots__ = ("done", "error", "value")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None


def coalesced(
    store: dict[tuple, Entry],
    flights: dict[tuple, Flight],
    lock: threading.Lock,
    key: tuple,
    *,
    fresh: Callable[[Entry], bool],
    compute: Callable[[], Entry],
    max_entries: int,
    usable: Callable[[Entry], bool] | None = None,
    load: Callable[[], Entry | None] | None = None,
    salvage: Callable[[Entry], bool] | None = None,
    landed: Callable[[Entry], None] | None = None,
) -> Any:
    """The value for `key`: from `store` while `fresh(entry)`, else computed once.

    Concurrent misses on one key share the first caller's outcome, value or
    exception, so a throttled download costs one attempt and not one per
    waiter. A failure is not stored: the next caller after the flight tries
    again. The miss and the flight's registration happen under one lock,
    which is what makes "computed once" a guarantee rather than a likelihood.

    `usable(entry)` says an entry past `fresh` may still be served at once
    while the refresh runs on a background thread. `load()` supplies an entry
    for a key the store has never seen (the disk). `salvage(entry)` says an
    entry too old even for `usable` may stand in when — and only when — the
    computation fails; that is the one path that marks the request stale.
    `landed(entry)` is told about every entry that lands.
    """
    if load is not None:
        with lock:
            missing = key not in store
        if missing and (loaded := load()) is not None:
            with lock:
                store.setdefault(key, loaded)
    with lock:
        entry = store.get(key)
        if entry is not None and fresh(entry):
            _remark(entry)
            return entry[1]
        flight = flights.get(key)
        leader = flight is None
        if flight is None:
            flight = flights[key] = Flight()
        stale = entry is not None and usable is not None and usable(entry)
    if stale:
        _remark(entry)
        if leader:
            threading.Thread(
                target=_land,
                args=(store, flights, lock, key, flight, compute, max_entries),
                kwargs={"background": True, "landed": landed},
                name="cache-refresh",
                daemon=True,
            ).start()
        return entry[1]
    if not leader:
        flight.done.wait()
        if flight.error is None:
            return flight.value
        return _fallback(entry, salvage, flight.error)
    try:
        return _land(
            store, flights, lock, key, flight, compute, max_entries, landed=landed
        )
    except Exception as exc:
        return _fallback(entry, salvage, exc)


def _remark(entry: Entry) -> None:
    """An entry built from a salvaged one marks every request it answers."""
    if len(entry) > 3 and entry[3] is not None:
        mark_stale(entry[3])


def _fallback(entry: Entry | None, salvage, exc: BaseException) -> Any:
    """The old entry when the source refused and it may still stand in; else
    the failure, unchanged."""
    if (
        entry is not None
        and salvage is not None
        and isinstance(exc, Exception)
        and salvage(entry)
    ):
        wall = entry[2] if len(entry) > 2 else time.time()
        mark_stale(wall)
        obs.warn(
            "cache.served_stale",
            age_s=round(time.time() - wall),
            error_type=type(exc).__name__,
        )
        return entry[1]
    raise exc


def _land(
    store: dict[tuple, Entry],
    flights: dict[tuple, Flight],
    lock: threading.Lock,
    key: tuple,
    flight: Flight,
    compute: Callable[[], Entry],
    max_entries: int,
    background: bool = False,
    landed: Callable[[Entry], None] | None = None,
) -> Any:
    """Run a flight to the ground: compute, store, release the waiters.

    In the background the exception is logged and swallowed — the stale entry
    stays, and nobody is on the stack to raise to — but the waiters that
    joined the flight without an entry of their own still get it raised.
    """
    # The compute runs under a holder of its own, so a salvage anywhere
    # beneath it (a frame this figure is built from) is caught here and
    # travels on the entry — and from there to every request it answers,
    # including the ones a background refresh never sees.
    token = STALE.set({})
    try:
        entry = compute()
    except BaseException as exc:
        flight.error = exc
        with lock:
            flights.pop(key, None)
        flight.done.set()
        if background:
            obs.warn(
                "cache.refresh_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            return None
        raise
    finally:
        since = (STALE.get() or {}).get("since")
        STALE.reset(token)
    if since is not None and len(entry) >= 3:
        entry = (*entry[:3], since)
        mark_stale(since)
    with lock:
        # Re-inserted rather than updated so a refreshed key moves to the
        # young end of the dict: eviction is oldest-inserted-first, and a hot
        # entry that kept its original slot would be the first one dropped.
        store.pop(key, None)
        store[key] = entry
        while len(store) > max_entries:
            store.pop(next(iter(store)))
        flights.pop(key, None)
    flight.value = entry[1]
    flight.done.set()
    if landed is not None:
        with obs.swallow("cache.persist"):
            landed(entry)
    return entry[1]


# ------------------------------------------------------------------- the disk
def _disk_path(name: str, key: tuple) -> Path:
    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:24]
    return MEMO_DIR / name / f"{digest}.pkl"


def _write(path: Path, entry: Entry) -> None:
    """Land one entry on disk (atomically) and mirror it to the bucket.

    The mirror runs on its own thread: an upload is network time the reader
    who caused the refresh should not sit through, and a copy that arrives a
    moment late is still there for the next process.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    blob = {
        "wall": entry[2],
        "value": entry[1],
        "since": entry[3] if len(entry) > 3 else None,
    }
    tmp.write_bytes(pickle.dumps(blob, protocol=pickle.HIGHEST_PROTOCOL))
    tmp.replace(path)
    _trim(path.parent)
    threading.Thread(
        target=_mirror, args=(path,), name="cache-mirror", daemon=True
    ).start()


def _mirror(path: Path) -> None:
    with obs.swallow("cache.mirror", path=path.name):
        from stocks import storage

        storage.persist(path)


def _trim(directory: Path) -> None:
    """Keep a memo's directory to `DISK_MAX_FILES`, oldest written first out."""
    files = sorted(directory.glob("*.pkl"), key=lambda p: p.stat().st_mtime)
    for old in files[: max(0, len(files) - DISK_MAX_FILES)]:
        old.unlink(missing_ok=True)


def _read(path: Path, not_before: float) -> Entry | None:
    """The entry on disk (the bucket's copy first on a fresh host), as a store
    entry whose age is what it was when it landed, or None.

    `not_before` is the memo's last `cache_clear`: a copy written before it
    was cleared on purpose and may only stand in for a failed fetch, never
    answer one — the bucket must not undo a refresh. Anything unreadable is
    dropped rather than retried.
    """
    if not path.exists():
        with obs.swallow("cache.restore", path=path.name):
            from stocks import storage

            storage.restore(path)
    if not path.exists():
        return None
    try:
        blob = pickle.loads(path.read_bytes())
        wall = float(blob["wall"])
        value = blob["value"]
        since = blob.get("since")
    except Exception:  # noqa: BLE001 — a stale format is a miss, not a fault
        path.unlink(missing_ok=True)
        return None
    age = max(0.0, time.time() - wall)
    # Written before the memo was last cleared on purpose: never fresh and
    # never within grace, so the next reader fetches — but still there to
    # stand in if that fetch is refused. A stamp of -inf is exactly that.
    stamp = float("-inf") if wall <= not_before else time.monotonic() - age
    entry: Entry = (stamp, value, wall)
    return (*entry, since) if since is not None else entry


def ttl_cache(
    ttl_s: float,
    max_entries: int = 32,
    stale_s: float | None = None,
    persist: str | None = None,
    keep_s: float | None = None,
) -> Callable[[F], F]:
    """Memoize a function on its arguments for `ttl_s` seconds.

    Arguments must be hashable — pass paths as strings and ticker lists as
    tuples, which is what the callers here do anyway.

    Past `ttl_s` an entry is served stale for another `stale_s` (three ttls
    unless said otherwise; 0 for a strict expiry) while a background refresh
    replaces it. With `persist`, entries also land under `data/memo/<name>/`
    and stand in for a failed fetch for up to `keep_s` (three days unless
    said otherwise) — see the module docstring.

    Eviction is oldest-inserted-first once `max_entries` is reached. A book's
    worth of cached frames is a few MB and this runs beside Streamlit in one
    container, so the cap matters more than the hit rate.
    """
    grace = 3 * ttl_s if stale_s is None else stale_s
    keep = (KEEP_DEFAULT_S if persist else 0.0) if keep_s is None else keep_s

    def decorate(fn: F) -> F:
        store: dict[tuple, Entry] = {}
        flights: dict[tuple, Flight] = {}
        lock = threading.Lock()
        cleared_at = [0.0]

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            # The stamp is taken before the call, so an entry's life is
            # counted from when its computation started, not when it landed.
            return coalesced(
                store,
                flights,
                lock,
                key,
                fresh=lambda entry: time.monotonic() - entry[0] < ttl_s,
                usable=lambda entry: time.monotonic() - entry[0] < ttl_s + grace,
                compute=lambda: (time.monotonic(), fn(*args, **kwargs), time.time()),
                max_entries=max_entries,
                load=(lambda: _read(_disk_path(persist, key), cleared_at[0]))
                if persist
                else None,
                salvage=(lambda entry: time.time() - entry[2] < keep)
                if keep > 0
                else None,
                landed=(lambda entry: _write(_disk_path(persist, key), entry))
                if persist
                else None,
            )

        def cache_clear(expire: bool = True) -> None:
            """Drop the entries. With `expire` (the default, and what a forced
            refresh means) the disk copies written so far stop answering
            reads — the next one fetches — but stay as the fallback for a
            fetch that is refused: a reader pressing "refresh" during a
            throttle must not turn the last good figures into nothing.
            `expire=False` is memory alone, which is what a restart loses."""
            store.clear()
            if expire and persist:
                cleared_at[0] = time.time()

        # `cache_clear` hangs off the wrapper the way functools' caches do it,
        # so a test (or a forced refresh) can drop the entries without reaching
        # into this module. Assigned through an untyped alias because a
        # signature-preserving decorator has nowhere to declare the extra
        # attribute, and `cast` is what hands the caller back its own type.
        clearable: Any = wrapper
        clearable.cache_clear = cache_clear
        return cast(F, wrapper)

    return decorate
