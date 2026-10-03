"""Env-first secret resolution shared by the web app and headless jobs.

The deploy keeps its secrets in `.streamlit/secrets.toml` (the entrypoint
writes $STREAMLIT_SECRETS_TOML there; the path is the one the app has always
read, kept so no deploy has to move its file); cron jobs (GitHub Actions) only
have environment variables. `secret()` checks the environment first, then the
matching section of that file — the same precedence storage.py uses — so one
code path serves both runtimes. With no file at all (bare CI run), or one that
is not valid TOML, the fallback is simply empty.

The file is read relative to the working directory, parsed with the standard
library, and re-read only when its mtime moves.
"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

log = logging.getLogger(__name__)

#: Relative on purpose: the server, the CLI and the cron jobs all run from the
#: project root, and a test that `chdir`s somewhere else gets no secrets.
SECRETS_FILE = Path(".streamlit") / "secrets.toml"

_parsed: dict[tuple[str, int], dict] = {}


def _load() -> dict:
    """The whole file as a dict, {} when it is missing or unreadable."""
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
