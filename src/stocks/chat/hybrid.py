"""Hybrid search: static embeddings fused with SQLite's keyword index.

The machinery both of the chat's searchable stores run on — the account's
earlier conversations (chat/memory.py) and the app's own knowledge base
(chat/knowledge.py). Each store owns its schema and what goes into it; this
module owns how a question becomes a ranking.

Two small dependencies do the work, both chosen so this survives a Cloud Run
cold start with no network and no GPU:

- **model2vec** (`potion-base-32M`, 512 dims) — static embeddings: a lookup
  table, not a transformer forward pass. CPU, milliseconds per turn, no torch.
  Baked into the image like the tiktoken table, quantized to int8 (~74MB
  resident against ~169MB as float32, same ranking — see the Dockerfile). The
  smaller potion-base-8M would cost less still, but 8M ranked an unrelated
  answer above the right one on the first question tried, and a memory that
  returns the wrong memory is worse than no memory.
- **sqlite-vec** — vector search as a SQLite extension. No server, no daemon.

Search is **hybrid**: the vectors above, fused with SQLite's own FTS5 keyword
index. Neither half is enough on its own. The static model is trained on
English and misranks Spanish — "¿qué decidí sobre ASML?" put an unrelated
Nvidia answer first in testing — while a keyword index cannot find "the
conclusion about concentration" from "how much of one thing is too much". But
tickers, company names and numbers are exactly what a user asks about later,
and those the keyword half nails in any language. Ranks are combined with
reciprocal rank fusion, which needs no score calibration between two searches
whose numbers mean different things.

Both dependencies are optional. Without them `available()` is False and every
store built on this module stays out of the chat's way.
"""

from __future__ import annotations

import os
import re
import sqlite3
from functools import lru_cache

from stocks import obs

# The hub id, unless a deploy points at a directory holding the same weights.
# The image bakes them with `save_pretrained` and sets STOCKS_EMBED_MODEL to
# where they landed: what the hub serves for this repo is the safetensors file
# *and* an ONNX copy of it, and `from_pretrained` fetches both while reading
# only the first — 123MB of image for a file nothing opens. Deleting it from
# the HF cache afterwards is not an option: the next offline load fails the
# snapshot completeness check. A plain directory sidesteps the cache entirely.
MODEL = os.environ.get("STOCKS_EMBED_MODEL") or "minishlab/potion-base-32M"
DIM = 512

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


@lru_cache(maxsize=1)
def _model():
    """The static embedding model, or None when it cannot be loaded.

    Cached for the process: loading reads (and on a cold machine downloads)
    ~124MB. A miss is not an error anywhere — it just means no search."""
    try:
        from model2vec import StaticModel

        return StaticModel.from_pretrained(MODEL)
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
        import numpy as np
        import sqlite_vec

        vectors = np.asarray(model.encode(texts), dtype="float32")
        # Normalized, so the cosine distance the index is built on is a pure
        # angle: model2vec's raw vectors are not unit length, and their
        # magnitudes track text length, which would rank long turns as "close"
        # to everything.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.clip(norms, 1e-9, None)
        return [sqlite_vec.serialize_float32(v.tolist()) for v in vectors]
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


def fuse(*rankings: list[int], weights: tuple[float, ...] = ()) -> list[int]:
    """Row ids ordered by reciprocal rank fusion across several rankings.

    RRF because the two halves' scores are not comparable — a cosine distance
    and a BM25 score have neither the same scale nor the same direction — but
    their *ranks* are. A row both searches like beats one that either loves.
    `weights`, one per ranking (1.0 when left out), tilts the vote toward the
    half that is better at this particular question.
    """
    scores: dict[int, float] = {}
    for n, ranking in enumerate(rankings):
        weight = weights[n] if n < len(weights) else 1.0
        for rank, row_id in enumerate(ranking):
            scores[row_id] = scores.get(row_id, 0.0) + weight / (_RRF_K + rank + 1)
    return sorted(scores, key=lambda i: -scores[i])
