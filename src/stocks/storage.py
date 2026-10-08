"""Optional S3-compatible persistence for user data (Cloudflare R2, S3, MinIO).

Deploy targets with ephemeral filesystems (containers, Cloud Run) lose
data/users/ and the imported ledgers on every restart or redeploy. When a
bucket is configured, every user-data write is mirrored to it (persist) and
each account's files are pulled back on first access after a boot
(restore_once). Unconfigured, every function is a no-op, so local dev, tests
and the CLI keep working on the plain filesystem.

Configuration — [storage] in .streamlit/secrets.toml, or the equivalent
STOCKS_STORAGE_* environment variables (env wins):

    [storage]
    endpoint_url      = "https://<account-id>.r2.cloudflarestorage.com"
    bucket            = "aguait-user-data"
    access_key_id     = "..."
    secret_access_key = "..."
    # region = "auto"        # default; use e.g. "eu-west-1" for AWS S3

Object keys are the file paths relative to the repo root (e.g.
"data/users/jane_example_com/portfolio.db", or "watchlist.yaml" for the
owner account), so one bucket mirrors both the per-user dirs and the
owner's repo-root book.

A restored file keeps the mtime it had when it was persisted (object
metadata, else the object's LastModified): caches key on a file's mtime, and
a restore that stamped "now" made every boot look like a fresh write — the
persisted memos keyed on it never hit again.

Consistency model: single app container. On the first touch of an account
per process the bucket copy wins (the local checkout only has git-seeded or
no files); from then on the local file is authoritative and every write
pushes, so the bucket is always current for the next boot.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from stocks import atomic, secrets_env
from stocks.config import PROJECT_ROOT

_ENV_PREFIX = "STOCKS_STORAGE_"
# Object metadata key carrying the file's mtime at persist time.
_MTIME = "mtime"
_lock = threading.Lock()
_restored: set[str] = set()
# One lock per restore group, held for the whole download. A group is marked
# restored only once its files are on disk, so a second request for the same
# account waits for the first one's restore instead of running against an
# empty directory — where it read prefs as {} and could write that back over
# the bucket copy, provider keys and all.
_group_locks: dict[str, threading.Lock] = {}
_cached: dict[str, object] = {}
# Per-process bucket listings of flat file pools (restore_stem).
_listings: dict[str, frozenset[str]] = {}


def _secrets_section() -> dict:
    """[storage] from .streamlit/secrets.toml, {} when unavailable."""
    return secrets_env.section("storage")


def _config() -> dict | None:
    """Resolved storage settings, or None when persistence is off."""
    if "config" not in _cached:
        section = {
            k: str(os.environ.get(_ENV_PREFIX + k.upper()) or v).strip()
            for k, v in (
                {
                    "endpoint_url": "",
                    "bucket": "",
                    "access_key_id": "",
                    "secret_access_key": "",
                    "region": "auto",
                }
                | _secrets_section()
            ).items()
        }
        needed = ("bucket", "access_key_id", "secret_access_key")
        _cached["config"] = section if all(section.get(k) for k in needed) else None
    return _cached["config"]  # ty: ignore[invalid-return-type]


def _group_lock(tag: str) -> threading.Lock:
    with _lock:
        return _group_locks.setdefault(tag, threading.Lock())


def enabled() -> bool:
    return _config() is not None


def _client():
    """One boto3 S3 client per process."""
    if "client" not in _cached:
        try:
            import boto3
        except ImportError as e:  # configured but dependency missing: fail loud
            raise RuntimeError(
                "[storage] is configured but boto3 is not installed — "
                "run `uv sync` (boto3 is a main dependency)."
            ) from e
        cfg = _config() or {}
        _cached["client"] = boto3.client(
            "s3",
            endpoint_url=cfg.get("endpoint_url") or None,
            region_name=cfg.get("region") or "auto",
            aws_access_key_id=cfg["access_key_id"],
            aws_secret_access_key=cfg["secret_access_key"],
        )
    return _cached["client"]


def _key(path: Path) -> str | None:
    """Bucket key for a local file: its path relative to the repo root.

    None (skip) for paths outside the repo — nothing personal lives there.
    """
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return None


def persist(path: Path) -> None:
    """Mirror one local write to the bucket (delete when the file is gone).

    Call after the local write has fully committed (file closed / connection
    committed). No-op when storage is unconfigured. Errors propagate: a
    silent persist failure would look saved and still vanish on restart.
    """
    if not enabled():
        return
    key = _key(path)
    if key is None:
        return
    cfg = _config() or {}
    if path.exists():
        _client().put_object(
            Bucket=cfg["bucket"],
            Key=key,
            Body=path.read_bytes(),
            Metadata={_MTIME: repr(path.stat().st_mtime)},
        )
    else:
        _client().delete_object(Bucket=cfg["bucket"], Key=key)


def restore(path: Path) -> bool:
    """Pull one file from the bucket, overwriting local. True when it existed."""
    if not enabled():
        return False
    key = _key(path)
    if key is None:
        return False
    cfg = _config() or {}
    client = _client()
    try:
        obj = client.get_object(Bucket=cfg["bucket"], Key=key)
    except client.exceptions.NoSuchKey:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_bytes(path, obj["Body"].read())
    _stamp(path, obj)
    return True


def _stamp(path: Path, obj: dict) -> None:
    """Give a restored file the mtime it was persisted with.

    Falls back to the object's LastModified for objects written before the
    metadata existed — not the original mtime, but stable from one boot to
    the next, which is what a cache key needs. Neither: left as written.
    """
    when = None
    try:
        when = float((obj.get("Metadata") or {})[_MTIME])
    except (KeyError, TypeError, ValueError):
        modified = obj.get("LastModified")
        if modified is not None:
            when = modified.timestamp()
    if when is not None:
        os.utime(path, (when, when))


def _listing(directory: Path, prefix: str) -> frozenset[str]:
    """Names of the bucket objects directly under `directory`, listed once per
    process (one LIST page per thousand names, no bodies). Nested keys are
    skipped. A failure raises before anything is kept, so the next touch
    lists again."""
    tag = f"list:{directory.resolve()}"
    with _group_lock(tag):
        names = _listings.get(tag)
        if names is None:
            cfg = _config() or {}
            pages = _client().get_paginator("list_objects_v2").paginate(
                Bucket=cfg["bucket"], Prefix=prefix + "/"
            )
            names = frozenset(
                name
                for page in pages
                for obj in page.get("Contents", [])
                if (name := obj["Key"].removeprefix(prefix + "/"))
                and "/" not in name
                and name not in (".", "..")
            )
            _listings[tag] = names
    return names


def restore_stem(directory: Path, stem: str) -> str | None:
    """Pull the bucket's `stem.<ext>` back into `directory`; its name, or None.

    For flat pools of generated files whose extension isn't known up front
    (mirrored logos: it depends on what the host served); fixed-name user data
    uses restore_once. Only the one file asked for is downloaded: pulling the
    whole pool on first touch held every caller behind a thousand sequential
    GETs after each boot. A local file wins — a running process has fresher
    mirrors than the bucket.
    """
    if not enabled():
        return None
    prefix = _key(directory)
    if prefix is None:
        return None
    # Exact stem: "BRK.png" is not BRK.B's logo, nor "BRK.B.png" BRK's.
    name = next(
        (n for n in sorted(_listing(directory, prefix)) if n.rpartition(".")[0] == stem),
        None,
    )
    if name is None:
        return None
    dest = directory / name
    with _group_lock(f"file:{dest.resolve()}"):
        if not dest.exists():
            cfg = _config() or {}
            body = _client().get_object(Bucket=cfg["bucket"], Key=f"{prefix}/{name}")
            directory.mkdir(parents=True, exist_ok=True)
            atomic.write_bytes(dest, body["Body"].read())
            _stamp(dest, body)
    return name


def read(path: Path) -> bytes | None:
    """The bucket's copy of a local file, leaving the local one alone; None
    when missing, outside the repo, or storage is off. For files the caller
    merges rather than replaces (a cache shipped in the image that the
    running host also adds to)."""
    key = _key(path)
    return read_key(key) if key is not None else None


def read_key(key: str) -> bytes | None:
    """One object's bytes by bucket key, or None (missing / storage off).

    For bucket-only data with no local mirror (the Telegram update queue);
    file-backed data goes through restore().
    """
    if not enabled():
        return None
    cfg = _config() or {}
    client = _client()
    try:
        return client.get_object(Bucket=cfg["bucket"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None


def delete_key(key: str) -> None:
    """Delete one object by bucket key. No-op when storage is unconfigured."""
    if not enabled():
        return
    cfg = _config() or {}
    _client().delete_object(Bucket=cfg["bucket"], Key=key)


def copy_key(src: str, dst: str) -> None:
    """Server-side copy of one object (no download). No-op when storage is off.

    Used by stocks.backup to snapshot and restore whole key trees without
    pulling user data through the machine running the job.
    """
    if not enabled():
        return
    cfg = _config() or {}
    _client().copy_object(
        Bucket=cfg["bucket"], Key=dst,
        CopySource={"Bucket": cfg["bucket"], "Key": src},
    )


def list_keys(prefix: str = "") -> list[str]:
    """All bucket keys under `prefix` ([] when storage is unconfigured).

    Used by headless jobs to enumerate accounts (data/users/<slug>/...)
    without a local checkout of the user data.
    """
    if not enabled():
        return []
    cfg = _config() or {}
    keys: list[str] = []
    pages = _client().get_paginator("list_objects_v2").paginate(
        Bucket=cfg["bucket"], Prefix=prefix
    )
    for page in pages:
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    return keys


def restore_once(group: Path, files: tuple[Path, ...]) -> None:
    """Restore a group of files the first time `group` is touched this process.

    After that the local copies are authoritative (every write persists), so
    later requests skip the bucket round-trips. A request arriving while the
    restore runs waits for it: the group counts as restored only once every
    file is down. A failure leaves it unmarked, so the next touch retries
    instead of caching a half-restore.
    """
    if not enabled():
        return
    tag = str(group.resolve())
    if tag in _restored:
        return
    with _group_lock(tag):
        if tag in _restored:
            return
        for f in files:
            restore(f)
        with _lock:
            _restored.add(tag)
