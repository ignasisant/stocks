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
from dataclasses import dataclass, replace
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
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z¿¡*\"“(]|- )")
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

# How near, by cosine distance, a passage must be to count on meaning alone —
# when the question shares no word with any passage. Measured 2026-10-14 over
# the golden set and off-topic questions: no single cut separates the two once
# keywords also matched (a right answer sits at 0.63, "capital de Francia" at
# 0.45), but with no keyword hit the right answers sat under 0.40 ("como veo
# los dividendos") and the noise above 0.53 (Tesla, iPhone, "hello").
_NEAR = 0.5

# A question whose own words are mostly absent from the whole knowledge base is
# about something it does not hold ("Bizum", "Apple Watch", "a short squeeze").
# The keyword half still matches the one word that does exist ("import",
# "score", "tax") and the semantic half always has a nearest neighbour, so such
# a question came back with four confident-looking passages. Measured
# 2026-10-23 over the golden set: no in-scope question has more than one word
# the index lacks (a verb form, a brand), so "half or more of the content
# words unknown", or two or more and at least 40%, is out of scope.
_UNKNOWN_SHARE = 0.5
_UNKNOWN_SHARE_PAIR = 0.4
# ...unless the question is semantically close to a passage anyway ("como veo
# los dividendos": "veo" is nowhere, the dividends step sits at 0.34). The
# out-of-scope questions measured sit at 0.42 and above.
_UNKNOWN_BUT_CLOSE = 0.4


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
    step: str = ""  # the guided-tour step whose page this is about, if any
    related: tuple[str, ...] = ()  # ids of the documents worth reading next

    def line(self) -> str:
        dated = f", as of {self.as_of}" if self.as_of else ""
        head = self.title if self.section == self.title else \
            f"{self.title} § {self.section}"
        return f"[{head}{dated}]\n{self.text}"


# ------------------------------------------------------------------ corpus


def _cut(text: str, limit: int = MAX_CHARS) -> list[str]:
    """`text` in pieces of at most `limit` characters, split between sentences.

    The pieces are balanced: a section a little over the limit is cut in two
    halves, not into a full passage and a stub. A stub ("Losses carry forward
    five years only if you opt for englobamento.") has lost the country it was
    about, and ranks as if it were an answer. A sentence longer than the limit
    stands alone rather than being cut in half: an overlong passage costs some
    result room, a sentence missing its end costs the meaning."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return [text] if text else []
    groups: list[list[str]] = [[]]
    for sentence in _SENTENCE.split(text):
        size = sum(map(len, groups[-1])) + len(groups[-1])
        if groups[-1] and size + len(sentence) > limit:
            groups.append([])
        groups[-1].append(sentence)
    # Greedy packing leaves the last piece with whatever is over. Re-split the
    # last two where they are most even.
    if len(groups) > 1:
        both = groups[-2] + groups[-1]
        best = None
        for i in range(1, len(both)):
            a, b = len(" ".join(both[:i])), len(" ".join(both[i:]))
            if max(a, b) <= limit or i == 1 or i == len(both) - 1:
                if best is None or abs(a - b) < best[0]:
                    best = (abs(a - b), i)
        if best:
            groups[-2:] = [both[:best[1]], both[best[1]:]]
    return [" ".join(g) for g in groups]


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
    related = tuple(r.strip() for r in meta.get("related", "").split(",")
                    if r.strip())
    return [
        Passage(doc=meta["id"], title=meta["title"], section=section,
                text=piece, as_of=meta["as_of"], tags=meta.get("tags", ""),
                step=meta.get("step", ""), related=related)
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
                               section=title, text=piece, lang=lang,
                               step=m.group(1))
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

    def _semantic(self, query: str, depth: int,
                  within: float | None = None) -> list[int]:
        if not self.vectors:
            return []
        blobs = hybrid.embed([query])
        if not blobs:
            return []
        return [r[0] for r in self.db.execute(
            f"SELECT id, distance FROM {_TABLE}_vec"
            " WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (blobs[0], depth)) if within is None or r[1] <= within]

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

    def out_of_scope(self, query: str) -> bool:
        """Whether too many of the question's content words appear nowhere in
        the knowledge base for any passage to be an answer to it."""
        terms = {w.lower() for w in hybrid._WORD_RE.findall(query)} - _STOP
        if not terms:
            return False
        unknown = sum(
            1 for t in terms if not self.db.execute(
                f"SELECT 1 FROM {_TABLE}_fts WHERE {_TABLE}_fts MATCH ? LIMIT 1",
                (hybrid._stem(t),)).fetchone())
        share = unknown / len(terms)
        return share >= _UNKNOWN_SHARE or (
            unknown >= 2 and share >= _UNKNOWN_SHARE_PAIR)

    def search(self, query: str, depth: int) -> list[int]:
        """Row ids, best first — none when nothing is near enough to answer.

        Nearest-neighbour search always has a nearest neighbour: asked who won
        the league, it returns the sector screen. Handed to the model as
        "documentation", that passage reads as an answer. So when no word of
        the question matched anything, only a close semantic hit counts."""
        with self.lock:
            if self.out_of_scope(query) and not self._semantic(
                    query, 1, within=_UNKNOWN_BUT_CLOSE):
                return []
            lexical = self._lexical(query, depth)
            semantic = self._semantic(query, depth,
                                      within=None if lexical else _NEAR)
            return hybrid.fuse(semantic, lexical,
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
    """`hits` as one tool result, under HEADER, ending in the documents the
    hits point to that the search did not return.

    Last, so the result cap cuts it before any passage: a question that
    spans two documents ("why does my gain in euros differ from the one in
    dollars?") finds one, and this is how the model knows to read the other."""
    out = HEADER + "\n\n".join(p.line() for p in hits)
    shown = {p.doc for p in hits}
    titles = {p.doc: p.title for p in passages()}
    more = [d for p in hits for d in p.related if d not in shown and d in titles]
    more = list(dict.fromkeys(more))
    if more:
        out += "\n\nSee also (doc=…): " + "; ".join(
            f"{d} ({titles[d]})" for d in more)
    return out


def cited(result: str) -> list[Passage]:
    """The passages a lookup result quoted, read back from their headings.

    How the answer's sources are listed: the tool result is all the gather
    step keeps, and every passage in it opens with `Passage.line`'s heading.
    One per document, first seen first."""
    heads = {p.line().split("\n", 1)[0]: p for p in passages()}
    out: list[Passage] = []
    for line in result.splitlines():
        p = heads.get(line.strip())
        if p and all(q.doc != p.doc for q in out):
            out.append(p)
    return out


EXCERPT_CHARS = 1800


def excerpt(refs: tuple[tuple[str, str], ...], limit: int = EXCERPT_CHARS) -> str:
    """Fixed passages, by (doc, heading), as one block under HEADER — or "".

    For prompts that always need the same background (the Today page's market
    read explains the pulse score the same way every morning): no search, no
    index, no embedding model, so a cron runner pays nothing to build one. A
    reference that matches nothing is skipped; the block stops at `limit`
    characters rather than cutting a passage mid-way.
    """
    out: list[str] = []
    used = 0
    for doc, heading in refs:
        hit = next((p for p in passages()
                    if p.doc == doc and p.section.startswith(heading)), None)
        if hit is None:
            continue
        line = hit.line()
        if used + len(line) > limit:
            break
        out.append(line)
        used += len(line)
    return HEADER + "\n\n".join(out) if out else ""


# ------------------------------------------------------------------ browsing


def manifest() -> str:
    """One line per methodology document, `- <id>: <title>`.

    Read into the tool's description, so the model knows what exists before it
    searches — and that a question about something not listed (an iPhone app,
    the price of a plan) is not going to be answered by any search here."""
    titles: dict[str, str] = {}
    for p in passages():
        if not p.doc.startswith("tour:"):
            titles.setdefault(p.doc, p.title)
    return "\n".join(f"- {doc}: {title}" for doc, title in titles.items())


def contents(doc: str) -> str:
    """`doc`'s section headings, one per line under its title — or ""."""
    heads: list[str] = []
    title = ""
    for p in passages():
        if p.doc == doc:
            title = p.title
            if p.section != p.title and p.section not in heads:
                heads.append(p.section)
    if not title:
        return ""
    return f"{title} ({doc}). Sections:\n" + "\n".join(f"- {h}" for h in heads)


# One section read whole: with HEADER and its title line it still fits one
# tool result (toolbox.MAX_RESULT_CHARS) uncut.
SECTION_CHARS = 3200


def section(doc: str, heading: str, limit: int = SECTION_CHARS) -> Passage | None:
    """One whole section of `doc` as a single passage, or None.

    A search hit is a cut of at most MAX_CHARS; the explanation it came from
    can run to several. `heading` matches case-insensitively by prefix, so
    the model can name a section the way a search hit printed it. Stops
    between passages at `limit` characters, saying so, rather than mid-way."""
    want = heading.strip().lower()
    parts = [p for p in passages()
             if p.doc == doc and want and p.section.lower().startswith(want)]
    if not parts:
        return None
    first = parts[0]
    texts: list[str] = []
    used = 0
    for p in parts:
        if p.section != first.section:
            break
        if texts and used + len(p.text) > limit:
            texts.append("[…the section continues; search for the rest.]")
            break
        texts.append(p.text)
        used += len(p.text)
    return replace(first, text="\n".join(texts))


def page(step: str) -> str:
    """The in-app path a tour step lands on ("/portfolio?tab=tax"), or "".

    Built from the tour's own registry, the way the tour's button builds it,
    so a cited document opens the same screen the tour would."""
    from urllib.parse import urlencode

    from stocks.web import onboarding

    target = next((s for s in onboarding.STEPS if s.id == step), None)
    if target is None or target.page is None:
        return ""
    query = dict(target.query or {})
    tab = target.session.get("profile_tab")
    if tab and "tab" not in query:
        query["tab"] = str(tab)
    return f"/{target.page}" + (f"?{urlencode(query)}" if query else "")


def source(p: Passage) -> dict:
    """`p` as an answer's source: its document, and the screen it is about.

    `step` rides along so the reader's own language can title a tour step;
    a methodology document is titled by its own (English) title."""
    return {"title": "" if p.doc.startswith("tour:") else p.title,
            "url": page(p.step) if p.step else "", "step": p.step}
