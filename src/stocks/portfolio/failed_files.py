"""The statements that failed to import, kept encrypted for fifteen days.

A masked fingerprint (stocks.portfolio.diagnostics) says what shape a file
had; it cannot say what a parser missed in a layout nobody has seen. For that
the file itself is the only evidence, so a failed import keeps it — never a
guest's, never the e2e suite's — for `KEEP_DAYS`, then it goes.

A file that read without an error is kept only when its reader says it read
wrong: the chat's "Report a problem" on an import offers to send the file with
the report, ticked by the reader (`api/routes/feedback.submit`). Nothing that
imported fine is kept on our own initiative.

* Encrypted with the deployment's Fernet key (`[chat] enc_key`, the one that
  already guards provider keys). No key, nothing kept: a statement in
  plaintext beside the account is a different promise, not a degraded mode.
* Stored under `data/imports/raw/<account slug>/<stamp>-<sha16>.<ext>.enc`.
  The original filename is not kept (it can carry a name); the same file
  uploaded twice is kept once.
* With a bucket configured they go straight to it and never touch the
  instance disk; without one (local dev) they sit under data/imports/raw/.
* `expire()` runs before the nightly snapshot (`stocks imports expire` in
  backup.yml) and the prefix is outside backups (`backup.live_keys`), so the
  fifteen days are not stretched by a month of snapshots. Deleting the account
  deletes its files (`purge_account`).

Nothing on the import path raises from here: losing the file must not cost
the reader the error they are being shown.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time

from stocks import atomic, obs, storage
from stocks.portfolio import diagnostics
from stocks.secrets_env import secret

KEEP_DAYS = 15
# A statement past this is a scan or an archive, not a layout to learn from.
MAX_BYTES = 8 * 1024 * 1024
PREFIX = "data/imports/raw/"

# `accounts.slug`: the readable base and its 8-hex digest. A guest, "anon" or
# "?" is no account, and nothing can be deleted on its behalf later.
_SLUG = re.compile(r"[a-z0-9_]{1,260}_[0-9a-f]{8}")
_EXT = re.compile(r"[a-z0-9]{1,5}")
_STAMP = "%Y%m%dT%H%M%SZ"
_NAME = re.compile(r"(\d{8}T\d{6}Z)-([0-9a-f]{16})\.([a-z0-9]{1,5})\.enc")


def _root():
    """data/imports/raw — read each call, so a test's diagnostics dir holds it."""
    return diagnostics.DIAGNOSTICS_DIR / "raw"


def _key() -> bytes | None:
    found = secret("CHAT_ENC_KEY", "chat", "enc_key")
    return found.encode() if found else None


def _extension(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext if _EXT.fullmatch(ext) else "bin"


def _names(slug: str) -> list[str]:
    """The file names kept for one account, local and bucket."""
    folder = _root() / slug
    found = {p.name for p in folder.glob("*.enc")} if folder.is_dir() else set()
    found.update(k.rsplit("/", 1)[-1] for k in storage.list_keys(f"{PREFIX}{slug}/"))
    return sorted(found)


def _skip(why: str) -> None:
    obs.event("import.raw_skipped", reason=why)


def keep(user: str, filename: str, data: bytes) -> str | None:
    """Keep one failed (or reported) statement; its id (`<slug>/<name>`), or None."""
    try:
        if not _SLUG.fullmatch(user) or diagnostics.is_test_account(user):
            return None
        if not data:
            return None
        if len(data) > MAX_BYTES:
            _skip("too_big")
            return None
        key = _key()
        if key is None:
            _skip("no_key")
            return None
        from cryptography.fernet import Fernet

        digest = hashlib.sha256(data).hexdigest()[:16]
        held = _names(user)
        _drop_old(user, held)
        same = next((n for n in held if f"-{digest}." in n), None)
        if same is not None:
            return f"{user}/{same}"
        ext = _extension(filename)
        stamp = time.strftime(_STAMP, time.gmtime())
        rel = f"{user}/{stamp}-{digest}.{ext}.enc"
        blob = Fernet(key).encrypt(data)
        if storage.enabled():
            storage.write_key(PREFIX + rel, blob)
        else:
            (_root() / user).mkdir(parents=True, exist_ok=True)
            atomic.write_bytes(_root() / rel, blob)
        obs.event("import.raw_kept", ext=ext, bytes=len(data))
        return rel
    except Exception as exc:  # noqa: BLE001 — never on the reader's path
        obs.event("import.raw_failed", level=logging.WARNING,
                  error_type=type(exc).__name__)
        return None


def _cutoff(days: int, now: float | None = None) -> str:
    return time.strftime(_STAMP, time.gmtime((now or time.time()) - days * 86400))


def _expired(name: str, cutoff: str) -> bool:
    """Older than the cutoff — or a name this module never writes."""
    found = _NAME.fullmatch(name)
    return found is None or found.group(1) < cutoff


def _drop_old(slug: str, names: list[str]) -> None:
    """An account's own expired files, swept when it files a new one."""
    cutoff = _cutoff(KEEP_DAYS)
    for name in [n for n in names if _expired(n, cutoff)]:
        _delete(f"{slug}/{name}")
        names.remove(name)


def _delete(rel: str) -> None:
    (_root() / rel).unlink(missing_ok=True)
    storage.delete_key(PREFIX + rel)


_DIGEST = re.compile(r"[0-9a-f]{16}")


def held(user: str, digest: str) -> str | None:
    """The id of `user`'s kept file with this digest (sha256, 16 hex), if any.

    How a report names a statement we already have — one that failed to
    import was kept then — instead of sending it a second time. Only the
    account's own files, only while they last; never raises.
    """
    try:
        if not _SLUG.fullmatch(user) or not _DIGEST.fullmatch(digest):
            return None
        cutoff = _cutoff(KEEP_DAYS)
        found = next(
            (
                n
                for n in _names(user)
                if f"-{digest}." in n and not _expired(n, cutoff)
            ),
            None,
        )
        return f"{user}/{found}" if found else None
    except Exception:  # noqa: BLE001 — a lookup that fails is a file not held
        return None


def kept() -> list[str]:
    """Every kept file's id (`<slug>/<name>`), oldest first per account."""
    root = _root()
    found = {p.relative_to(root).as_posix() for p in root.glob("*/*.enc")} \
        if root.is_dir() else set()
    found.update(k.removeprefix(PREFIX) for k in storage.list_keys(PREFIX))
    return sorted(found)


def expire(days: int = KEEP_DAYS, now: float | None = None) -> tuple[int, int]:
    """Delete every file older than `days`, needing no key; (deleted, failed).

    Logged either way: the job that runs it may not fail the workflow, and a
    sweep that quietly stopped would break the fifteen days unseen.
    """
    cutoff = _cutoff(days, now)
    deleted = failed = 0
    for rel in kept():
        if not _expired(rel.rsplit("/", 1)[-1], cutoff):
            continue
        try:
            _delete(rel)
            deleted += 1
        except Exception:  # noqa: BLE001 — one stuck object must not stop the rest
            failed += 1
    obs.event("import.raw_expired",
              level=logging.WARNING if failed else logging.INFO,
              deleted=deleted, failed=failed)
    return deleted, failed


def purge_account(slug: str) -> int:
    """Delete everything kept for one account; how many files went."""
    if not _SLUG.fullmatch(slug):
        return 0
    names = _names(slug)
    for name in names:
        _delete(f"{slug}/{name}")
    return len(names)


def read(file_id: str) -> bytes:
    """One kept file, decrypted. Raises when missing or undecryptable."""
    slug, _, name = file_id.partition("/")
    if not _SLUG.fullmatch(slug) or not _NAME.fullmatch(name):
        raise ValueError(f"not a kept file id: {file_id}")
    key = _key()
    if key is None:
        raise RuntimeError("no [chat] enc_key to decrypt with")
    path = _root() / slug / name
    blob = path.read_bytes() if path.exists() else storage.read_key(PREFIX + file_id)
    if blob is None:
        raise FileNotFoundError(file_id)
    from cryptography.fernet import Fernet

    return Fernet(key).decrypt(blob)


def original_extension(file_id: str) -> str:
    found = _NAME.fullmatch(file_id.rsplit("/", 1)[-1])
    return found.group(3) if found else "bin"
