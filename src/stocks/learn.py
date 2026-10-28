"""The Learn page's curriculum: paths of short lessons, and a glossary.

Everything else in the app explains one number where it stands — a `?` beside
a KPI, a caption under a chart. This is the place that teaches investing from
the start, for a reader who does not yet know what a limit order or a savings
base is. It is general on purpose: the lessons point at the page where a
concept shows up ("in the app"), but they never read anybody's book.

Hand-written and shipped as files, in every language the app speaks:

- `web/learn/paths.yaml` — the paths in the order the page lists them, each an
  ordered list of lesson ids. A path's name and blurb are UI copy
  (`learn.path_<id>_title` / `_body` in `locales/<lang>/learn.json`).
- `web/learn/<lang>/<lesson-id>.md` — one lesson: frontmatter (`id`, `path`,
  `title`, `minutes`, `as_of`, `terms`, `app`) and a short markdown body. The
  same ids exist in every language; `tests/test_learn.py` holds them together.
- `web/learn/<lang>/glossary.yaml` — term id → label, aliases, a one- or
  two-sentence definition, and the lesson that teaches it, when one does.

Read once per process and kept: a few dozen small files, the same for every
reader. Nothing here is generated, so nothing here can be confidently wrong
about a tax rate on one visit and right on the next.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

LEARN_DIR = Path(__file__).resolve().parent / "web" / "learn"
LANGS = ("en", "es")
FALLBACK = "en"

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TERM = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


@dataclass(frozen=True)
class LearnPath:
    id: str
    icon: str  # Material Symbols ligature
    lessons: tuple[str, ...]


@dataclass(frozen=True)
class Lesson:
    id: str
    path: str
    title: str
    minutes: int
    as_of: str
    terms: tuple[str, ...]
    # Where the concept shows up in the app: a shell slug, optionally with a
    # query (`portfolio?tab=risk`). Empty when nothing on screen shows it.
    app: str
    body: str


@dataclass(frozen=True)
class Term:
    id: str
    label: str
    aliases: tuple[str, ...]
    desc: str
    lesson: str  # "" when no lesson teaches it yet


def _lang(lang: str | None) -> str:
    return lang if lang in LANGS else FALLBACK


def _meta(block: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in block.splitlines():
        key, _, value = line.partition(":")
        if value:
            meta[key.strip()] = value.strip()
    return meta


def _list(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def parse_lesson(text: str, name: str = "") -> Lesson:
    """One lesson file. Raises ValueError naming the file and what is wrong."""
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError(f"{name}: missing frontmatter")
    meta = _meta(m.group(1))
    for field in ("id", "path", "title", "minutes", "as_of"):
        if not meta.get(field):
            raise ValueError(f"{name}: frontmatter needs {field!r}")
    if not _ID.match(meta["id"]):
        raise ValueError(f"{name}: id {meta['id']!r} is not kebab-case")
    try:
        minutes = int(meta["minutes"])
    except ValueError:
        raise ValueError(f"{name}: minutes must be a whole number") from None
    body = m.group(2).strip()
    if not body:
        raise ValueError(f"{name}: empty body")
    return Lesson(
        id=meta["id"],
        path=meta["path"],
        title=meta["title"],
        minutes=minutes,
        as_of=meta["as_of"],
        terms=_list(meta.get("terms", "")),
        app=meta.get("app", ""),
        body=body,
    )


@lru_cache(maxsize=1)
def paths() -> tuple[LearnPath, ...]:
    """The paths in the order the page lists them."""
    raw = yaml.safe_load((LEARN_DIR / "paths.yaml").read_text(encoding="utf-8"))
    return tuple(
        LearnPath(id=entry["id"], icon=entry["icon"],
                  lessons=tuple(entry["lessons"]))
        for entry in raw["paths"]
    )


@lru_cache(maxsize=len(LANGS))
def lessons(lang: str) -> dict[str, Lesson]:
    """Every lesson in `lang`, by id."""
    out: dict[str, Lesson] = {}
    for file in sorted((LEARN_DIR / _lang(lang)).glob("*.md")):
        lesson = parse_lesson(file.read_text(encoding="utf-8"), file.name)
        if lesson.id != file.stem:
            raise ValueError(f"{file.name}: id {lesson.id!r} differs from the file name")
        out[lesson.id] = lesson
    return out


def lesson(lesson_id: str, lang: str | None) -> Lesson | None:
    return lessons(_lang(lang)).get(lesson_id)


def neighbours(lesson_id: str) -> tuple[str | None, str | None]:
    """The lessons before and after this one in its path."""
    for path in paths():
        if lesson_id in path.lessons:
            at = path.lessons.index(lesson_id)
            before = path.lessons[at - 1] if at > 0 else None
            after = path.lessons[at + 1] if at + 1 < len(path.lessons) else None
            return before, after
    return None, None


@lru_cache(maxsize=len(LANGS))
def glossary(lang: str) -> tuple[Term, ...]:
    """Every term in `lang`, sorted by label the way a reader scans a list."""
    raw = yaml.safe_load(
        (LEARN_DIR / _lang(lang) / "glossary.yaml").read_text(encoding="utf-8"))
    terms = []
    for term_id, entry in raw.items():
        if not _TERM.match(term_id):
            raise ValueError(f"glossary: id {term_id!r} is not snake_case")
        terms.append(Term(
            id=term_id,
            label=str(entry["label"]),
            aliases=tuple(str(a) for a in entry.get("aliases") or ()),
            desc=str(entry["desc"]).strip(),
            lesson=str(entry.get("lesson") or ""),
        ))
    return tuple(sorted(terms, key=lambda t: _folded(t.label)))


def _folded(text: str) -> str:
    """Sort key that files "Índice" under I, not after Z."""
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).casefold()
