"""A chat run's progress on disk, so a restart does not lose the turn.

A run (`api/runs.py`) lives in memory: a deploy or a crash used to take the
turn in flight with it, question and all — chat.json is written only once the
answer is — and a deep research is a minute or two of lookups and model
rounds that a crash can land in the middle of. So each run also keeps a
checkpoint, one file per thread: what was asked and how (the run's own props,
so the turn can be built again), every lookup the research has made with what
it returned, the research's plan, the finished evidence once the gather is
over, and the provider whose free unit was charged.

The process that picks it up — the next one, after the restart — finds it
when the thread is opened or the run is followed again (`orphan`) and starts
the same run id over. The research asks its lookups again and is answered
from here (`known`), so nothing already fetched is fetched twice, and a
finished gather is not run at all. A unit already charged is not charged
again (`prepaid`).

Not for a turn on the reader's own key held for the session only (`held`):
that key never touches a disk, so a checkpoint could not run the turn again.

The file is local and mirrored to the bucket like every user file, written on
a thread of its own so no lookup waits on the bucket, at most once every
`FLUSH_S` while something changed. Beside it a tiny beat file is rewritten
every `BEAT_S`: it is how a second process tells a run another one is still
answering (a deploy's old and new instance overlap) from one nobody is. Only
a checkpoint whose beat is older than `STALE_S` is picked up — short, so a
reader whose stream dropped with the process is answered again within their
client's reconnects — and none older than `MAX_AGE_S`: by then the reader has
long moved on, and the question is just dropped.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from stocks import atomic, obs, storage

FLUSH_S = 2.0
BEAT_S = 5.0
STALE_S = 15.0
MAX_AGE_S = 15 * 60.0
#: A run that has already been picked up this many times is not again: what
#: keeps killing the process may be the turn itself.
MAX_RESUMES = 2

#: How a run was asked, beyond the question — what `_events` needs to build
#: it again. Never a key.
PROPS = ("lang", "staged_import", "view", "focus", "guided", "linked", "depth",
         "brief")


def folder(chat_path: Path) -> Path:
    return chat_path.with_name(f"{chat_path.stem}_runs")


def _path(chat_path: Path, thread: str) -> Path:
    # A thread id is the app's own hex; anything else is kept out of the path.
    safe = "".join(c for c in thread if c.isalnum() or c in "-_")[:64] or "_"
    return folder(chat_path) / f"{safe}.json"


def _beat_path(path: Path) -> Path:
    return path.with_suffix(".beat")


def _save(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(path, body)
    storage.persist(path)


def _remove(path: Path) -> None:
    for each in (path, _beat_path(path)):
        each.unlink(missing_ok=True)
        storage.persist(each)


class Checkpoint:
    """One run's progress, written as it goes and deleted when it is over.

    Every method is safe from any thread and never raises: a checkpoint that
    cannot be written costs the restart, not the answer."""

    def __init__(self, path: Path, record: dict):
        self.path, self.record = path, record
        self._lock = threading.Lock()
        # The file's own: a write to the bucket is never waited on by a
        # lookup filing its result, only by the next write.
        self._io = threading.Lock()
        self._dirty = threading.Event()
        self._closed = threading.Event()
        self._written = 0.0
        self._beaten = 0.0
        self._writer = threading.Thread(target=self._loop, daemon=True,
                                        name=f"chat-checkpoint-{record['rid'][:8]}")

    # --------------------------------------------------------------- opening

    @classmethod
    def open(cls, chat_path: Path, *, rid: str, thread: str, question: str,
             props: dict) -> Checkpoint:
        """A new run's checkpoint, written at once: the question is on disk
        before anything is spent on it."""
        point = cls(_path(chat_path, thread), {
            "rid": rid, "thread": thread, "question": question,
            "props": {k: props[k] for k in PROPS if k in props},
            "started": time.time(), "calls": [], "plan": [],
            "evidence": None, "charged": "", "resumes": 0,
        })
        point._start()
        return point

    @classmethod
    def resume(cls, chat_path: Path, record: dict) -> Checkpoint:
        """The run in `record` picked up again, beating from now on."""
        record = {**record, "resumes": int(record.get("resumes") or 0) + 1}
        point = cls(_path(chat_path, str(record["thread"])), record)
        point._start()
        return point

    def _start(self) -> None:
        self._beat()
        self._write()
        self._writer.start()

    # ----------------------------------------------------------- the research

    def known(self) -> dict[tuple[str, str], str]:
        """The lookups already made, by `agent._key`, with what they returned."""
        from stocks.chat import agent

        with self._lock:
            return {agent._key(c["name"], c["args"]): c["result"]
                    for c in self.record["calls"]}

    def called(self, name: str, args: dict, result: str) -> None:
        with self._lock:
            self.record["calls"].append(
                {"name": name, "args": dict(args or {}), "result": result})
        self._dirty.set()

    def planned(self, plan: list[dict]) -> None:
        with self._lock:
            self.record["plan"] = list(plan)
        self._dirty.set()

    @property
    def plan(self) -> list[dict]:
        with self._lock:
            return list(self.record["plan"])

    @property
    def evidence(self) -> dict | None:
        """The gather's finished result, once it is: {calls, ok, missing},
        `calls` as `called` keeps them."""
        with self._lock:
            return self.record["evidence"]

    def gathered(self, calls: list, ok: bool, missing: str) -> None:
        with self._lock:
            self.record["evidence"] = {
                "calls": [{"name": c.name, "args": dict(c.args or {}),
                           "result": c.result} for c in calls],
                "ok": ok, "missing": missing}
        self._write()

    # --------------------------------------------------------------- charging

    @property
    def prepaid(self) -> str:
        """The provider whose free unit this run already paid, or ""."""
        with self._lock:
            return str(self.record["charged"] or "")

    def charged(self, provider_id: str) -> None:
        """Paid on `provider_id` ("" once refunded). Written at once: a
        restart right after it must not charge the reader twice."""
        with self._lock:
            self.record["charged"] = provider_id
        self._write()

    # ------------------------------------------------------------- the file

    def close(self) -> None:
        """The run is over, whichever way: the checkpoint goes."""
        self._closed.set()
        self._dirty.set()
        with self._io:
            try:
                _remove(self.path)
            except Exception as exc:  # noqa: BLE001 — see the class
                obs.warn("chat.checkpoint_failed", op="close",
                         error_type=type(exc).__name__)

    def _loop(self) -> None:
        while not self._closed.is_set():
            left = BEAT_S - (time.monotonic() - self._beaten)
            if self._dirty.wait(max(0.0, left)) and not self._closed.is_set():
                # Changes coalesce: a gather's burst of lookups is one write.
                time.sleep(max(0.0, FLUSH_S - (time.monotonic() - self._written)))
                self._write()
            if time.monotonic() - self._beaten >= BEAT_S:
                self._beat()

    def _write(self) -> None:
        with self._lock:
            self._dirty.clear()
            body = json.dumps(self.record, ensure_ascii=False, default=str)
        with self._io:
            if self._closed.is_set():
                return
            try:
                _save(self.path, body)
            except Exception as exc:  # noqa: BLE001 — see the class
                obs.warn("chat.checkpoint_failed", op="write",
                         error_type=type(exc).__name__)
            self._written = time.monotonic()

    def _beat(self) -> None:
        with self._io:
            if self._closed.is_set():
                return
            try:
                _save(_beat_path(self.path), repr(time.time()))
            except Exception as exc:  # noqa: BLE001 — see the class
                obs.warn("chat.checkpoint_failed", op="beat",
                         error_type=type(exc).__name__)
            self._beaten = time.monotonic()


# ------------------------------------------------------------------ finding

_listed: set[str] = set()
_listed_lock = threading.Lock()


def _restore(chat_path: Path) -> None:
    """Pull this account's checkpoints from the bucket, once per process: a
    run another process left can only predate this one's first look."""
    where = folder(chat_path)
    with _listed_lock:
        if str(where) in _listed:
            return
        _listed.add(str(where))
    key = storage._key(where)
    if key is None:
        return
    try:
        for name in storage.list_keys(key + "/"):
            storage.restore(where / Path(name).name)
    except Exception as exc:  # noqa: BLE001 — nothing to resume, then
        obs.warn("chat.checkpoint_failed", op="restore",
                 error_type=type(exc).__name__)


def _read(path: Path) -> dict | None:
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and record.get("rid") else None


def _last_beat(path: Path) -> float:
    """When the run behind `path` last said it was alive — the bucket's copy
    first, since another process may still be writing it."""
    beat = _beat_path(path)
    try:
        raw = storage.read(beat) if storage.enabled() else None
        return float(raw.decode() if raw is not None else beat.read_text())
    except (OSError, ValueError):
        return 0.0


def _dropped(path: Path, record: dict, why: str) -> None:
    obs.event("chat.checkpoint_dropped", why=why,
              age=round(time.time() - float(record.get("started") or 0)))
    try:
        _remove(path)
    except Exception:  # noqa: BLE001 — dropped either way next boot
        pass


def orphan(chat_path: Path, *, thread: str = "", rid: str = "") -> dict | None:
    """The checkpoint of a run nobody is answering any more, on `thread` or
    with id `rid`; None when there is none, or it is still beating.

    The caller has already checked this process has no such run. One too old
    to be worth finishing, or already picked up too often, is deleted on the
    way."""
    _restore(chat_path)
    if thread:
        paths = [_path(chat_path, thread)]
    else:
        paths = sorted(folder(chat_path).glob("*.json"))
    for path in paths:
        record = _read(path)
        if record is None or (rid and record["rid"] != rid):
            continue
        now = time.time()
        if now - float(record.get("started") or 0) > MAX_AGE_S:
            _dropped(path, record, "old")
        elif now - _last_beat(path) < STALE_S:
            continue
        elif int(record.get("resumes") or 0) >= MAX_RESUMES:
            _dropped(path, record, "resumed")
        else:
            return record
    return None


def discard(chat_path: Path, rid: str) -> bool:
    """Delete run `rid`'s checkpoint, beating or not: the reader stopped it.
    True when there was one."""
    _restore(chat_path)
    for path in sorted(folder(chat_path).glob("*.json")):
        record = _read(path)
        if record is not None and record["rid"] == rid:
            _dropped(path, record, "stopped")
            return True
    return False


def _reset() -> None:
    """Forget which accounts were listed. Tests only."""
    with _listed_lock:
        _listed.clear()
