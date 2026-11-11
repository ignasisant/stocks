"""Tell the owner when someone uploads a statement and gets nowhere.

An import that fails is the moment a new account is most likely to leave, and
the anonymised diagnostics (`portfolio.diagnostics`) only help if somebody
reads them. This turns each stuck upload into one `import.stuck` WARNING, and
the Cloud Monitoring policy `infra/monitoring/policy-import-stuck.json` mails
it to the alert channel as an incident — the same email an ERROR log sends,
while the reader may still be looking at the page:

* **failed** — the file was uploaded and could not be completed: nothing in
  it read, nothing importable once validated, a commit refused, the server
  crashed on it, or the browser could not even open it. Logged at once.
* **abandoned** — the preview had rows and no commit followed within
  `ABANDON_AFTER`. Not an error, but the same lost reader: a preview they did
  not trust, a broker picker they did not get past. Found by `sweep`, which the
  warm runs (boot and the Scheduler ticks) call; Cloud Run scales to zero, so
  a timer in the request would die with the instance.

What goes in the line is the diagnostic, never the statement: the
pseudonymous account slug, the masked filename, counts, the top skip reason
(already redacted). Never more than one incident per account and file a day
(`DEDUPE`), never more than `HOURLY_CAP` in an hour, and none at all for the
e2e accounts; what is held back is `import.stuck_quiet` with the reason.
Nothing here raises: it runs on failure paths.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from stocks import obs, storage, userstore
from stocks.config import DATA_DIR

STATE = DATA_DIR / "import_watch.json"
ABANDON_AFTER = timedelta(minutes=30)
# A preview older than this was never going to be committed; past it the
# sweep drops it without an email (an instance that slept through the window).
FORGET_AFTER = timedelta(days=2)
DEDUPE = timedelta(hours=24)
HOURLY_CAP = 12

FAILED = "failed"
ABANDONED = "abandoned"


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def _parse(stamp: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp))
    except ValueError:
        return None


def _user(fp: dict | None = None) -> str:
    return str((fp or {}).get("user") or obs.current().get("user") or "-")


def _restore() -> None:
    """The bucket's copy on an instance's first touch: Cloud Run scales to
    zero, so the preview and the sweep that reports it are rarely one
    process."""
    storage.restore_once(STATE, (STATE,))


def _test_account(user: str) -> bool:
    from stocks.portfolio import diagnostics

    return diagnostics.is_test_account(user)


# ------------------------------------------------------------- the watch list


def previewed(fp: dict, *, digest: str, importable: int, platform: str) -> None:
    """A preview that had rows to write: watched until a commit clears it."""
    user = _user(fp)
    if importable <= 0 or _test_account(user):
        return
    try:
        _restore()
        with userstore.edit(STATE) as state:
            state.setdefault("pending", {})[user] = {
                "at": _stamp(_now()),
                "platform": platform,
                "surface": fp.get("surface", ""),
                "file": fp.get("file", ""),
                "ext": fp.get("ext", ""),
                "bytes": fp.get("bytes", 0),
                "rows": importable,
                "skipped": fp.get("skipped", 0),
                "rejected": fp.get("rejected", 0),
                "digest": digest[:16],
            }
    except Exception as exc:  # noqa: BLE001 — a watch list is not worth a 500
        obs.warn("import.watch_failed", stage="previewed", error_type=type(exc).__name__)


def committed() -> None:
    """The account finished an import: whatever it previewed is done."""
    user = _user()
    try:
        _restore()
        with userstore.edit(STATE) as state:
            gone = state.get("pending", {}).pop(user, None)
    except Exception as exc:  # noqa: BLE001
        obs.warn("import.watch_failed", stage="committed", error_type=type(exc).__name__)
        return
    if gone:
        waited = _parse(gone.get("at"))
        obs.event(
            "import.watch_cleared",
            platform=gone.get("platform", ""),
            waited_s=round((_now() - waited).total_seconds()) if waited else None,
        )


def sweep(now: datetime | None = None) -> int:
    """Alert on every preview left uncommitted past `ABANDON_AFTER`; the count."""
    now = now or _now()
    due: list[tuple[str, dict]] = []
    try:
        _restore()
        with userstore.edit(STATE) as state:
            pending = state.get("pending", {})
            for user, item in list(pending.items()):
                at = _parse(item.get("at"))
                if at is None or now - at > FORGET_AFTER:
                    pending.pop(user)
                elif now - at >= ABANDON_AFTER:
                    due.append((user, pending.pop(user)))
    except Exception as exc:  # noqa: BLE001
        obs.warn("import.watch_failed", stage="sweep", error_type=type(exc).__name__)
        return 0
    for user, item in due:
        at = _parse(item.get("at"))
        minutes = round((now - at).total_seconds() / 60) if at else None
        _alert(
            ABANDONED,
            user,
            key=item.get("digest") or item.get("file", ""),
            platform=item.get("platform", ""),
            facts={
                "previewed": item.get("at", ""),
                "minutes": minutes,
                "surface": item.get("surface", ""),
                "file": item.get("file", ""),
                "ext": item.get("ext", ""),
                "bytes": item.get("bytes", 0),
                "importable": item.get("rows", 0),
                "skipped": item.get("skipped", 0),
                "rejected": item.get("rejected", 0),
            },
            now=now,
        )
    return len(due)


# ----------------------------------------------------------------- failures


def failed(fp: dict, *, stage: str, detail: str = "", digest: str = "") -> None:
    """An upload that could not be completed. `fp` is its diagnostics record
    (`diagnostics.report` / `client_failure`), `stage` where it stopped."""
    user = _user(fp)
    try:
        _restore()
        with userstore.edit(STATE) as state:
            # Told now; the sweep must not tell it again as abandoned.
            state.get("pending", {}).pop(user, None)
    except Exception:  # noqa: BLE001, S110 — the alert below matters more
        pass
    reasons = fp.get("reasons") or {}
    top = next(iter(reasons), "")
    _alert(
        FAILED,
        user,
        key=digest[:16] or f"{fp.get('file', '')}:{fp.get('bytes', 0)}",
        platform=str(fp.get("platform", "")),
        facts={
            "stage": stage,
            "detail": detail[:300],
            "surface": fp.get("surface", ""),
            "file": fp.get("file", ""),
            "ext": fp.get("ext", ""),
            "bytes": fp.get("bytes", 0),
            "encoding": fp.get("encoding", ""),
            "delimiter": fp.get("delimiter", ""),
            "columns": len(fp.get("headers") or []),
            "imported": fp.get("imported", 0),
            "skipped": fp.get("skipped", 0),
            "routine": fp.get("routine", 0),
            "rejected": fp.get("rejected", 0),
            "top_reason": f"{top} ×{reasons[top]}" if top else "",
            "top_type": next(iter(fp.get("types") or {}), ""),
            "top_issue": next(iter(fp.get("issues") or {}), ""),
            "error": " ".join(x for x in (fp.get("error_type", ""),
                                          fp.get("error", "")) if x),
            "diagnostic_id": fp.get("id", ""),
        },
    )


# ------------------------------------------------------------------ incident


def _alert(
    kind: str,
    user: str,
    *,
    key: str,
    platform: str,
    facts: dict,
    now: datetime | None = None,
) -> bool:
    """Log one `import.stuck` unless it is a test account, a repeat or over
    the cap. The monitoring policy on that event is what emails."""
    now = now or _now()
    fields: dict[str, Any] = {
        "kind": kind,
        "platform": platform,
        "stage": facts.get("stage", ""),
    }

    def quiet(why: str) -> bool:
        obs.event("import.stuck_quiet", why=why, user=user, **fields)
        return False

    if _test_account(user):
        return quiet("test_account")
    dedupe = hashlib.sha256(f"{kind}|{user}|{key}".encode()).hexdigest()[:24]
    try:
        _restore()
        with userstore.edit(STATE) as state:
            sent = state.setdefault("sent", {})
            for k, at in list(sent.items()):
                when = _parse(at)
                if when is None or now - when > DEDUPE:
                    sent.pop(k)
            if dedupe in sent:
                return quiet("repeat")
            hour = sum(1 for at in sent.values()
                       if (when := _parse(at)) and now - when < timedelta(hours=1))
            if hour >= HOURLY_CAP:
                return quiet("hourly_cap")
            sent[dedupe] = _stamp(now)
    except Exception as exc:  # noqa: BLE001
        obs.warn("import.watch_failed", stage="alert", error_type=type(exc).__name__)
        return False
    obs.warn(
        "import.stuck",
        user=user,
        **fields,
        **{k: v for k, v in facts.items() if k != "stage" and v not in ("", None)},
    )
    return True
