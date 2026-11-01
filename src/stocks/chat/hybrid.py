"""Hybrid search: static embeddings fused with SQLite's keyword index.

The machinery both of the chat's searchable stores run on — the account's
earlier conversations (chat/memory.py) and the app's own knowledge base
(chat/knowledge.py). Each store owns its schema and what goes into it; this
module owns how a question becomes a ranking.

Two small dependencies do the work, both chosen so this survives a Cloud Run
cold start with no network and no GPU:

- **a static embedding model** (chat/embedding.py: potion-multilingual-128M
  cut to English and Spanish, 256 dims) — a lookup table, not a transformer
  forward pass. CPU, well under a millisecond per turn, no torch, ~41MB
  resident. Multilingual on purpose: a user asks in Spanish about a turn they
  had in English. The English-only potion-base-32M before it put "¿qué decidí
  sobre ASML?" nearer to any Spanish text than to the English turn about ASML.
- **sqlite-vec** — vector search as a SQLite extension. No server, no daemon.

Search is **hybrid**: the vectors above, fused with SQLite's own FTS5 keyword
index. Neither half is enough on its own. A keyword index cannot find "the
conclusion about concentration" from "how much of one thing is too much",
while a static model averages a sentence into one point and blurs the one word
that mattered. But tickers, company names and numbers are exactly what a user
asks about later, and those the keyword half nails in any language. Ranks are
combined with reciprocal rank fusion, which needs no score calibration between
two searches whose numbers mean different things.

Both halves are optional. Without them `available()` is False and every store
built on this module stays out of the chat's way.
"""

from __future__ import annotations

import fcntl
import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from stocks import obs
from stocks.chat import embedding

DIM = embedding.DIM
# What the vectors are. Stored next to every index that persists them, so one
# written by another model is rebuilt instead of searched (chat/memory.py).
EMBEDDER = embedding.NAME

# Reciprocal rank fusion's damping constant. The literature's 60 was tuned on
# TREC runs of hundreds of documents; against the handful of candidates each
# half returns here it flattens rank 1 and rank 4 to within 5% of each other,
# which is the same as having no ranking. 10 keeps rank meaningful at this
# scale.
_RRF_K = 10

# A term matching more than this share of the index is not a search term, it is
# grammar ("qué", "sobre", "the", "position"). Derived from the corpus rather
# than a stopword list, so it works in whatever language the user writes —
# below _DF_MIN_NOTES there is not enough corpus to tell, and every term stays.
_DF_MAX_SHARE = 0.5
_DF_MIN_NOTES = 20

_WORD_RE = re.compile(r"[^\W\d_]{2,}|\d[\w.\-]*", re.UNICODE)


# ------------------------------------------------------------- dependencies


def _model_dir() -> tuple[Path, bool]:
    """Where the model lives, and whether a missing one may be built there.

    The image builds it at build time and points STOCKS_EMBED_MODEL at it: a
    serving instance never downloads 500MB to make one. Anywhere else (a dev
    machine, CI) it is built on first use into the user's cache, once."""
    baked = os.environ.get("STOCKS_EMBED_MODEL")
    if baked:
        return Path(baked), False
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache / "stocks" / embedding.NAME, True


@lru_cache(maxsize=1)
def _model() -> embedding.Embedder | None:
    """The static embedding model, or None when it cannot be loaded.

    Cached for the process. A miss is not an error anywhere — it just means
    no search."""
    directory, buildable = _model_dir()
    try:
        if buildable and not (directory / "meta.json").exists():
            # One builder at a time: pytest-xdist workers all get here at once.
            directory.parent.mkdir(parents=True, exist_ok=True)
            with open(directory.parent / f"{directory.name}.lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if not (directory / "meta.json").exists():
                    obs.event("chat.embed.model_build", dir=str(directory))
                    embedding.build(directory)
        return embedding.Embedder(directory)
    except Exception as exc:
        obs.warn("chat.memory.model_unavailable", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        return None


def available() -> bool:
    """Whether this deploy can search by meaning at all."""
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        return False
    return _model() is not None


def embed(texts: list[str]) -> list[bytes] | None:
    """`texts` as sqlite-vec float32 blobs, or None when embedding is off."""
    model = _model()
    if model is None or not texts:
        return None
    try:
        import sqlite_vec

        # Unit length, so the cosine distance the index is built on is a pure
        # angle rather than one that tracks text length.
        return [sqlite_vec.serialize_float32(v.tolist()) for v in model.encode(texts)]
    except Exception as exc:
        obs.warn("chat.memory.embed_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        return None


def load_vec(db: sqlite3.Connection) -> None:
    """Load sqlite-vec into `db`, and lock extension loading again after."""
    import sqlite_vec

    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)


# ------------------------------------------------------------------ search


def _content_terms(db: sqlite3.Connection | None, terms: set[str],
                   table: str, max_share: float = _DF_MAX_SHARE) -> set[str]:
    """`terms` without the ones this corpus treats as grammar.

    A word in half the stored rows tells the search nothing — it only drags in
    every row that happens to contain it, which is how "¿qué decidí sobre
    ASML?" comes back with a conversation about Nvidia. Dropped only once
    there is enough corpus for document frequency to mean anything, and never
    all of them: a question made entirely of common words still has to search
    for something."""
    if db is None or len(terms) < 2:
        return terms
    try:
        total = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if total < _DF_MIN_NOTES:
            return terms
        keep = set()
        for term in terms:
            hits = db.execute(
                f"SELECT count(*) FROM {table}_fts WHERE {table}_fts MATCH ?",
                (f'"{term}"',)).fetchone()[0]
            if hits <= total * max_share:
                keep.add(term)
        return keep or terms
    except Exception as exc:
        obs.warn("chat.memory.content_terms_failed",
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return terms


def _stem(term: str) -> str:
    """`term` as an FTS5 prefix query that also matches its other forms.

    FTS5 ships no Spanish stemmer, and the porter one is English-only.
    Clipping the ending is crude and close enough: "recompré" finds
    "recompra", "pérdida" finds "pérdidas", "deduce" finds "deducible". Short
    words stay exact — clipped, they would match half the corpus."""
    if len(term) < 6 or not term.isalpha():
        return f'"{term}"'
    return f'"{term[:max(5, len(term) - 3)]}"*'


def fts_query(text: str, db: sqlite3.Connection | None = None,
              table: str = "notes", stem: bool = False,
              max_share: float = _DF_MAX_SHARE) -> str:
    """`text` as an FTS5 MATCH expression, or "" when there is nothing to match.

    Built from extracted words rather than passed through: a raw question is a
    syntax error to FTS5 the moment it contains a quote, a hyphen or the word
    "OR". Each term is quoted and OR-ed, so the match is "any of these words"
    and BM25 decides which row had the most telling ones. `table` names the
    store whose `<table>_fts` index the grammar words are measured against;
    `stem` matches each long word by its prefix (`_stem`). A corpus written in
    two languages lowers `max_share`: each language's grammar is in at most
    the share of rows written in it."""
    terms = {w.lower() for w in _WORD_RE.findall(text or "")}
    terms = _content_terms(db, terms, table, max_share)
    quote = _stem if stem else (lambda t: f'"{t}"')
    return " OR ".join(sorted({quote(t) for t in terms})) if terms else ""


def fuse(*rankings: list[int]) -> list[int]:
    """Row ids ordered by reciprocal rank fusion across several rankings.

    RRF because the two halves' scores are not comparable — a cosine distance
    and a BM25 score have neither the same scale nor the same direction — but
    their *ranks* are. A row both searches like beats one that either loves.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, row_id in enumerate(ranking):
            scores[row_id] = scores.get(row_id, 0.0) + 1 / (_RRF_K + rank + 1)
    return sorted(scores, key=lambda i: -scores[i])
