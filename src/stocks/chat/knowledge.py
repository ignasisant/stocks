"""The app's own knowledge base: how TopStocks works and how it computes things.

The model knows investing in general and nothing about this app in particular.
Asked "why is my Revolut PDF not importing?", "how is the money-weighted return
annualised?" or "does the app apply the two-month rule?", it answers from what
such apps usually do — plausibly, and wrong in exactly the details the user is
asking about. The answers exist; they are just not anywhere the chat can see.

Two sources, read from the repo at first use:

- **The guided tour's copy** (`web/locales/<lang>/tour.json`): what every page
  and feature does and where it lives, in English and Spanish, kept current by
  the update-tutorial skill every time a feature ships. Indexing it rather than
  restating it is what keeps "how do I…" answers from drifting away from the
  app. Both languages go in: the static embedding model misranks Spanish, and
  the Spanish copy is what lets the keyword half catch a Spanish question.
- **Hand-written methodology** (`web/knowledge/*.md`): what the tour is too
  short for — how returns, cost basis, tax and scores are actually computed,
  what each broker's export must look like. Each file carries an `as_of` date,
  quoted with every passage so a tax figure reads as dated, and `tags`: the
  Spanish (and other) words a reader would type, added to the keyword index
  only.

Every source is cut into passages short enough that four of them fit one tool
result, and searched with the same hybrid ranking as the account's memory
(chat/hybrid.py). The index is small — a few hundred passages — so it is built
in memory, once per process, rather than shipped as a file: nothing to bake
into the image, nothing to go stale beside the copy it was built from.

Without the embedding model the index is keywords only: worse at paraphrase,
still right about every page name, broker and tax term, so the tool stays.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from stocks import obs
from stocks.chat import hybrid

_WEB = Path(__file__).resolve().parents[1] / "web"
DOCS_DIR = _WEB / "knowledge"
LOCALES_DIR = _WEB / "locales"
LANGS = ("en", "es")

LOOKUP_LIMIT = 4  # passages per search
# One passage's share of a search result. Four of these plus their headers stay
# under toolbox.MAX_RESULT_CHARS, so a result is never cut mid-passage.
MAX_CHARS = 900

_TABLE = "passages"
# BM25 weights of the head (title + section), tags and body columns.
_RANK = "4.0, 2.0, 1.0"
# The corpus is half English, half Spanish: a word in a fifth of all passages
# is in nearly half of its own language's, which makes it grammar.
_DF_MAX_SHARE = 0.2
# The DF filter above still lets through the short grammar words of a
# language that is only half the corpus ("se", "mi", "por"). The corpus is
# written in exactly these two languages, so they are simply listed.
_STOP = frozenset("""
a al como con cual cuando de del donde el en es esta este hay la las le lo los
mas me mi mis muy no o para pero por que qué quien se si sin sobre su sus te tu
tus un una uno y ya yo cómo cuál dónde porque está están estoy tengo
an and are as at be by can do does for from has have how i if in is it its me
my of on or the this to was what when where which who why with you your
""".split())

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
_SECTION = re.compile(r"^## +(.+)$", re.M)
_SENTENCE = re.compile(r"(?<=[.!?:])\s+(?=[A-Z¿¡*\"“(])")
# A tour step is a `<key>_title` with a `<key>_body` beside it. News cards are
# release notes ("new: …"), not a description of the app as it stands: the
# step they point at already says it in the present tense.
_TOUR_TITLE = re.compile(r"^tour\.(?!news_)(\w+)_title$")

HEADER = (
    "Passages from the TopStocks documentation, maintained with the app. "
    "Cite the document when you use one. A passage dated 'as of' states the "
    "rules the app applied then: say so when the question is about current "
    "tax law.\n\n"
)


# Words only Spanish has, among the ones a question is made of.
_SPANISH = frozenset("""
al como cual cuando del donde el en es esta este hay la las los mas mi mis muy
para pero por que qué quien se si sin sobre su sus tu tus un una uno ya yo cómo
cuál dónde porque está están estoy tengo puedo debo necesito
""".split())
# The semantic half's vote on a Spanish question. The embedding model is
# English-trained: asked in Spanish it ranks the Spanish tour copy first for
# being Spanish, whatever it says, while the keyword half — stems, tags — is
# still reading the question.
_SPANISH_SEMANTIC = 0.15


def _spanish_weight(query: str) -> float:
    words = {w.strip("¿?¡!.,;:()\"'").lower() for w in query.split()}
    spanish = bool(words & _SPANISH) or any(c in query for c in "¿¡ñáéíóú")
    return _SPANISH_SEMANTIC if spanish else 1.0


@dataclass(frozen=True)
class Passage:
    doc: str  # "importing", or "tour:<step>" for the guided tour's copy
    title: str  # the document's title
    section: str  # the heading this passage sits under
    text: str
    lang: str = "en"
    as_of: str = ""  # ISO date the methodology was checked against the code
    tags: str = ""  # extra search terms, keyword index only

    def line(self) -> str:
        dated = f", as of {self.as_of}" if self.as_of else ""
        head = self.title if self.section == self.title else \
            f"{self.title} § {self.section}"
        return f"[{head}{dated}]\n{self.text}"


# ------------------------------------------------------------------ corpus


def _cut(text: str, limit: int = MAX_CHARS) -> list[str]:
    """`text` in pieces of at most `limit` characters, split between sentences.

    A sentence longer than the limit stands alone rather than being cut in
    half: an overlong passage costs some result room, a sentence missing its
    end costs the meaning."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return [text] if text else []
    pieces, current = [], ""
    for sentence in _SENTENCE.split(text):
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _meta(block: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in block.splitlines():
        key, _, value = line.partition(":")
        if value:
            meta[key.strip()] = value.strip()
    return meta


def parse_doc(text: str, name: str = "") -> list[Passage]:
    """One knowledge file as passages: one or more per `##` section, plus the
    intro above the first heading when there is one."""
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError(f"{name}: missing frontmatter")
    meta = _meta(m.group(1))
    for field in ("id", "title", "as_of"):
        if not meta.get(field):
            raise ValueError(f"{name}: frontmatter needs {field!r}")
    body = m.group(2)
    heads = list(_SECTION.finditer(body))
    sections = [(meta["title"], body[:heads[0].start() if heads else len(body)])]
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        sections.append((head.group(1).strip(), body[head.end():end]))
    return [
        Passage(doc=meta["id"], title=meta["title"], section=section,
                text=piece, as_of=meta["as_of"], tags=meta.get("tags", ""))
        for section, raw in sections
        for piece in _cut(raw)
    ]


def _docs() -> list[Passage]:
    out: list[Passage] = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        try:
            out.extend(parse_doc(path.read_text(encoding="utf-8"), path.name))
        except (OSError, ValueError) as exc:
            obs.warn("chat.knowledge.doc_skipped", doc=path.name,
                     error_type=type(exc).__name__, error=str(exc)[:200])
    return out


def _tour() -> list[Passage]:
    out: list[Passage] = []
    for lang in LANGS:
        try:
            copy = json.loads(
                (LOCALES_DIR / lang / "tour.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            obs.warn("chat.knowledge.tour_skipped", lang=lang,
                     error_type=type(exc).__name__, error=str(exc)[:200])
            continue
        for key, title in copy.items():
            m = _TOUR_TITLE.match(key)
            if not m:
                continue
            body = copy.get(f"tour.{m.group(1)}_body")
            if not body:
                continue
            out.extend(Passage(doc=f"tour:{m.group(1)}", title=title,
                               section=title, text=piece, lang=lang)
                       for piece in _cut(body))
    return out


@lru_cache(maxsize=1)
def passages() -> tuple[Passage, ...]:
    """Every passage the knowledge base holds, in a fixed order."""
    return tuple(_docs() + _tour())


# ------------------------------------------------------------------- index


class _Index:
    """The in-memory search index, built on first use and shared by every
    request thread — one connection, so every query holds the lock."""

    def __init__(self, items: tuple[Passage, ...]):
        self.items = items
        self.lock = threading.Lock()
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.vectors = False
        # Three columns so a word in a heading or a tag outweighs the same
        # word in passing (`_RANK`). remove_diacritics 2 so "tributacion"
        # finds "tributación".
        self.db.execute(
            f"CREATE VIRTUAL TABLE {_TABLE}_fts USING fts5("
            ' head, tags, body, tokenize="unicode61 remove_diacritics 2")')
        # A plain table of ids too: hybrid's grammar filter counts rows in it.
        self.db.execute(f"CREATE TABLE {_TABLE} (id INTEGER PRIMARY KEY)")
        for i, p in enumerate(items):
            self.db.execute(f"INSERT INTO {_TABLE} (id) VALUES (?)", (i,))
            self.db.execute(
                f"INSERT INTO {_TABLE}_fts (rowid, head, tags, body)"
                " VALUES (?, ?, ?, ?)",
                (i, f"{p.title} {p.section}", p.tags, p.text))
        blobs = hybrid.embed([f"{p.title}. {p.section}. {p.text}" for p in items]) \
            if items and hybrid.available() else None
        if blobs:
            hybrid.load_vec(self.db)
            self.db.execute(
                f"CREATE VIRTUAL TABLE {_TABLE}_vec USING vec0("
                f" id INTEGER PRIMARY KEY, embedding float[{hybrid.DIM}]"
                " distance_metric=cosine)")
            self.db.executemany(
                f"INSERT INTO {_TABLE}_vec (id, embedding) VALUES (?, ?)",
                list(enumerate(blobs)))
            self.vectors = True

    def _semantic(self, query: str, depth: int) -> list[int]:
        if not self.vectors:
            return []
        blobs = hybrid.embed([query])
        if not blobs:
            return []
        return [r[0] for r in self.db.execute(
            f"SELECT id FROM {_TABLE}_vec WHERE embedding MATCH ? AND k = ?"
            " ORDER BY distance", (blobs[0], depth))]

    def _lexical(self, query: str, depth: int) -> list[int]:
        words = [w for w in query.split()
                 if w.strip("¿?¡!.,;:()\"'").lower() not in _STOP]
        match = hybrid.fts_query(" ".join(words), self.db, _TABLE, stem=True,
                                 max_share=_DF_MAX_SHARE)
        if not match:
            return []
        return [r[0] for r in self.db.execute(
            f"SELECT rowid FROM {_TABLE}_fts WHERE {_TABLE}_fts MATCH ?"
            f" ORDER BY bm25({_TABLE}_fts, {_RANK}) LIMIT ?", (match, depth))]

    def search(self, query: str, depth: int) -> list[int]:
        with self.lock:
            return hybrid.fuse(self._semantic(query, depth),
                               self._lexical(query, depth),
                               weights=(_spanish_weight(query), 1.0))


_BUILD = threading.Lock()


@lru_cache(maxsize=1)
def _index() -> _Index | None:
    with _BUILD:
        try:
            return _Index(passages())
        except Exception as exc:
            obs.warn("chat.knowledge.index_failed",
                     error_type=type(exc).__name__, error=str(exc)[:300])
            return None


def available() -> bool:
    """Whether there is anything to search."""
    return bool(passages())


def lookup(query: str, limit: int = LOOKUP_LIMIT) -> list[Passage]:
    """The passages that best answer `query`, best first.

    One passage per piece of the app: the English and Spanish copy of a tour
    step, or two cuts of the same section, are the same answer twice, and the
    second spends room a different document should have had. Never raises."""
    if not query.strip():
        return []
    index = _index()
    if index is None:
        return []
    try:
        order = index.search(query, max(limit * 4, 12))
    except Exception as exc:
        obs.warn("chat.knowledge.search_failed",
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return []
    out: list[Passage] = []
    seen: set[tuple[str, str]] = set()
    for i in order:
        p = index.items[i]
        key = (p.doc, p.section if not p.doc.startswith("tour:") else "")
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) == limit:
            break
    return out


def block(hits: list[Passage]) -> str:
    """`hits` as one tool result, under HEADER."""
    return HEADER + "\n\n".join(p.line() for p in hits)
