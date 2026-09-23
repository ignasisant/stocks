r"""Every literal catalog key the React front ends use actually ships.

A key that does not exist does not fail anywhere: `useT` falls back to the key
itself, so the screen prints `profile.iv_risk_help` where a sentence belongs and
nobody notices until a user does. It is the single most common mistake made
building these pages — invented keys were reported by four separate reviewers
during the migration, including in code written by the person warning about it.

Only literal keys are checked. `t(\`profile.iv_${group}_${option}\`)` is a
family, not a key, and the option ids behind it come from the server — those are
covered by the Python tests that assert a label exists for every jurisdiction,
every profile option and every alert type.

Parsed rather than imported because the other side is TypeScript. The regex is
deliberately dumb: anything that looks like `t("some.key")` counts, so a key
cannot slip in through a call shape this test does not recognise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FRONTENDS = [REPO / "frontend" / "app" / "src"]
CATALOGS = REPO / "src" / "stocks" / "web" / "locales"

# `t("a.b")`, `tr("a.b")`, and the `label: "a.b"` / `tile: "a.b"` table entries
# the pages use to name a key without calling through it.
_CALL = re.compile(r'\bt\w*\(\s*"([a-z][a-z0-9_]*\.[a-z0-9_.]+)"')
_FIELD = re.compile(
    r'\b(?:label|tile|title|help|key)\s*:\s*"([a-z][a-z0-9_]*\.[a-z0-9_.]+)"'
)

# Keys the front ends compose from a stem the server sends. Listed rather than
# pattern-matched: a prefix that silently swallowed real keys would turn this
# test into decoration.
_SERVER_STEMS = ("chat.free_", "chat.skill.")


@pytest.fixture(scope="module")
def shipped() -> set[str]:
    """Every key in the English catalogs — parity with Spanish is another test."""
    keys: set[str] = set()
    for path in (CATALOGS / "en").glob("*.json"):
        keys |= set(json.loads(path.read_text(encoding="utf-8")))
    return keys


def _used() -> dict[str, list[str]]:
    """key -> the files that name it."""
    out: dict[str, list[str]] = {}
    for root in FRONTENDS:
        for path in root.rglob("*.ts*"):
            # A test's fixture names keys that are deliberately absent — that
            # is what it is testing. Reading them here would make this file
            # fail on somebody else's passing test.
            if ".test." in path.name or "__tests__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for match in (*_CALL.finditer(text), *_FIELD.finditer(text)):
                out.setdefault(match.group(1), []).append(
                    str(path.relative_to(REPO))
                )
    return out


def test_the_catalogs_ship_every_key_the_front_ends_ask_for(shipped):
    missing = {
        key: sorted(set(files))
        for key, files in _used().items()
        if key not in shipped and not key.startswith(_SERVER_STEMS)
    }
    assert not missing, "keys used but never written:\n" + "\n".join(
        f"  {key} — {', '.join(files)}" for key, files in sorted(missing.items())
    )


def test_the_test_is_actually_reading_the_front_ends():
    """A regex that matched nothing would pass the check above forever."""
    used = _used()
    assert len(used) > 200, f"only found {len(used)} keys — the parse is broken"
