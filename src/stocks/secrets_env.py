"""Env-first secret resolution shared by the web app and headless jobs.

The deploy keeps its secrets in `secrets.toml` at the project root (the
entrypoint writes $STOCKS_SECRETS_TOML there); cron jobs (GitHub Actions) only
have environment variables. `secret()` checks the environment first, then the
matching section of that file — the same precedence storage.py uses — so one
code path serves both runtimes. With no file at all (bare CI run), or one that
is not valid TOML, the fallback is simply empty.

The file is read relative to the working directory, parsed with the standard
library, and re-read only when its mtime moves — looked at no more often than
every `RECHECK_S`.
"""

from __future__ import annotations

import logging
import os
import time
import tomllib
from pathlib import Path

log = logging.getLogger(__name__)

#: Relative on purpose: the server, the CLI and the cron jobs all run from the
#: project root, and a test that `chdir`s somewhere else gets no secrets.
SECRETS_FILE = Path("secrets.toml")

#: How long one look at the file answers for. A request reads a dozen
#: secrets, and each look is a resolve and two stats — syscalls that hand the
#: GIL away. Behind a page's worth of busy loaders every hand-back waits for
#: the lock again, and a read that costs a millisecond took seconds (the chat
#: drawer's opening read, 8 s on a phone while Home was still loading).
RECHECK_S = 5.0

_parsed: dict[tuple[str, int], dict] = {}
#: The file last looked at, when, and what it held.
_looked: tuple[Path, float, dict] | None = None


def _load() -> dict:
    """The whole file as a dict, {} when it is missing or unreadable."""
    global _looked
    now = time.monotonic()
    looked = _looked
    if looked is not None and looked[0] == SECRETS_FILE and now - looked[1] < RECHECK_S:
        return looked[2]
    data = _read()
    _looked = (SECRETS_FILE, now, data)
    return data


def _read() -> dict:
    path = SECRETS_FILE.resolve()
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}
    if stamp not in _parsed:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            # The type only: a decode error quotes the offending line.
            log.warning("secrets file unreadable: %s", type(exc).__name__)
            data = {}
        _parsed.clear()
        _parsed[stamp] = data
    return _parsed[stamp]


def section(name: str) -> dict:
    """One `[name]` table of the secrets file, a fresh dict, {} when absent."""
    table = _load().get(name)
    return dict(table) if isinstance(table, dict) else {}


def secret(env_var: str, section_name: str, key: str, default: str = "") -> str:
    """`os.environ[env_var]`, else `[section_name] key` of the file, else `default`."""
    val = (os.environ.get(env_var) or "").strip()
    if val:
        return val
    return str(section(section_name).get(key, default)).strip() or default
