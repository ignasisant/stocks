"""The chat's text embedder: a multilingual static model, cut to English and Spanish.

What chat/hybrid.py searches with. The model is minishlab's
potion-multilingual-128M — a static embedding (one vector per vocabulary
piece, a sentence is the mean of its pieces), distilled from bge-m3, so a
Spanish question and the English answer it is about land near each other.
The English-only potion-base-32M it replaced put "¿qué decidí sobre ASML?"
nearer to any Spanish text than to the English turn about ASML.

As published it does not fit the instance. Its vocabulary is 500k pieces for
101 languages, and the `tokenizers` library holds a Unigram vocabulary as a
byte trie at ~1.5KB a piece: 733MB resident for the tokenizer alone, on a 1GiB
instance whose busiest hour already peaks near 950MB. Two cuts, measured
2026-11-01 against the knowledge golden set and a cross-lingual memory set:

- **The vocabulary**, to the pieces that spell the top WORDS words of English
  and Spanish (lower case, capitalised, upper case for the commonest quarter,
  and capitalised again as the tail of a joined name), plus every Latin-1
  single character and every piece with no letter in it: 76k pieces. A
  Unigram segmentation only ever uses pieces that are substrings of the word,
  so a word made of kept pieces segments exactly as it did; rarer words fall
  back to shorter pieces, and other scripts drop out. Over the knowledge base
  and the tour, a line's vector sits at mean cosine 0.991 from the full
  model's, and every ranking measured is the same.
- **The tokenizer**, replaced by `_Vocab` below: the same Viterbi search over
  a dict, and the ids it produces were checked equal to `tokenizers`' on every
  knowledge passage, tour string and a live chat history.

Loaded, the whole model is ~41MB resident (the potion-base-32M it replaced
took ~97MB) and encodes a turn in well under a millisecond.

So the runtime needs numpy and nothing else, and the files are ours: built
once by `build()` (the image does it at build time, a dev machine on first
use), stamped with NAME so an index written by another vocabulary is redone
rather than searched (chat/memory.py).

This module imports nothing from `stocks`: the Dockerfile runs it as a plain
script, before the project is installed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
import tempfile
import unicodedata
from pathlib import Path

import numpy as np

SOURCE = "minishlab/potion-multilingual-128M"
REVISION = "73908c3438cf03b6a01bcb9611d62b23d0726f08"
# Stamped into every index built with these vectors. Change it whenever the
# source, the revision, the cut or the encoding changes.
NAME = "potion-multilingual-128M-en-es-1"
DIM = 256
LANGS = ("en", "es")
WORDS = 50_000
MAX_TOKENS = 512  # what the model was distilled with; model2vec cuts here too

_SPACE = "▁"
# The source tokenizer's normalizer, in order: NFKC (its precompiled charsmap,
# for the scripts kept here), runs of spaces folded, each ASCII punctuation
# mark spaced off into a word of its own, whitespace collapsed, ends stripped.
# `build()` refuses a source whose tokenizer says anything else.
_PUNCT_MARKS = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
_PUNCT = re.compile(f"([{re.escape(_PUNCT_MARKS)}])")
_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = re.sub(" {2,}", " ", unicodedata.normalize("NFKC", text))
    return _WS.sub(" ", _PUNCT.sub(r" \1 ", text)).strip()


class _Vocab:
    """A Unigram vocabulary and its search: piece -> id, score per id."""

    def __init__(self, pieces: list[str], scores: list[float], unknown: float,
                 skip: tuple[int, ...] = ()):
        self.ids = {p: i for i, p in enumerate(pieces) if i not in skip}
        self.scores = scores
        self.longest = max(map(len, self.ids))
        self.unknown = unknown

    def segment(self, word: str) -> list[int]:
        """`word` as piece ids: the segmentation with the highest summed score.

        The Unigram model's own search. A character no piece covers costs
        `unknown` (the source vocabulary's lowest score less 10, as
        `tokenizers` scores it) and yields no id — model2vec drops the
        unknown id before averaging anyway."""
        n = len(word)
        best = [(0.0, 0, -1)] + [(-1e18, 0, -1)] * n
        for end in range(1, n + 1):
            for start in range(max(0, end - self.longest), end):
                if best[start][0] <= -1e18:
                    continue
                piece = self.ids.get(word[start:end])
                if piece is not None:
                    score = best[start][0] + self.scores[piece]
                    if score > best[end][0]:
                        best[end] = (score, start, piece)
                elif end - start == 1:
                    score = best[start][0] + self.unknown
                    if score > best[end][0]:
                        best[end] = (score, start, -1)
        ids, end = [], n
        while end > 0:
            _, start, piece = best[end]
            if piece >= 0:
                ids.append(piece)
            end = start
        return ids[::-1]

    def tokenize(self, text: str) -> list[int]:
        """Piece ids for `text`. The source runs one search over the whole
        text with spaces as ▁; no piece has a ▁ past its first character, so
        a search per word finds the same pieces, at a fraction of the cost."""
        text = _normalize(text)
        ids: list[int] = []
        if text:
            for word in (_SPACE + text.replace(" ", _SPACE)).split(_SPACE)[1:]:
                ids.extend(self.segment(_SPACE + word))
        return ids[:MAX_TOKENS]


class Embedder:
    """The cut model, loaded from a directory `build()` wrote."""

    def __init__(self, directory: Path):
        meta = json.loads((directory / "meta.json").read_text())
        if meta.get("name") != NAME:
            raise ValueError(f"{directory} holds {meta.get('name')!r}, not {NAME!r}")
        # Strings in JSON, numbers in arrays: a JSON list of [piece, score]
        # pairs costs ~40MB of small objects to parse, which the allocator
        # keeps after they are dropped.
        pieces = json.loads((directory / "pieces.json").read_text())
        scores = np.load(directory / "scores.npy").tolist()
        self.vocab = _Vocab(pieces, scores, meta["unknown"])
        self.vectors = np.load(directory / "vectors.npy")
        if self.vectors.shape != (len(pieces), DIM) or len(scores) != len(pieces):
            raise ValueError(f"{directory}: {len(pieces)} pieces, "
                             f"{len(scores)} scores, vectors {self.vectors.shape}")

    def tokenize(self, text: str) -> list[int]:
        return self.vocab.tokenize(text)

    def encode(self, texts: list[str]) -> np.ndarray:
        """One unit-length float32 row per text; zeros for a text with no
        piece in it. int8 rows share one scale, so the mean's direction is
        the full-precision one's."""
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            ids = self.tokenize(text)
            if ids:
                out[row] = self.vectors[ids].astype(np.float32).mean(axis=0)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.clip(norms, 1e-9, None)


# ------------------------------------------------------------------- build


def _fetch(name: str, into: Path) -> Path:
    import httpx

    url = f"https://huggingface.co/{SOURCE}/resolve/{REVISION}/{name}"
    path = into / name
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with path.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    return path


def _read_safetensors(path: Path) -> np.ndarray:
    with path.open("rb") as f:
        (size,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(size))
    spec = header["embeddings"]
    if spec["dtype"] != "F32" or spec["shape"][1] != DIM:
        raise ValueError(f"unexpected embeddings tensor: {spec}")
    return np.memmap(path, dtype="<f4", mode="r", offset=8 + size
                     + spec["data_offsets"][0], shape=tuple(spec["shape"]))


def _check_tokenizer(tok: dict) -> None:
    """Refuse a source tokenizer that `_normalize` / `_Vocab` would not
    reproduce: a new upload under the same name must not quietly re-split."""
    model = tok["model"]
    steps = tok["normalizer"]["normalizers"]
    inner = [(s["type"], s.get("pattern")) for s in steps[0].get("normalizers", [])]
    spaced = [(s["pattern"].get("String"), s["content"]) for s in steps[1:-2]]
    pre = tok["pre_tokenizer"]
    ok = (model["type"] == "Unigram" and not model.get("byte_fallback")
          and inner == [("Precompiled", None), ("Replace", {"Regex": " {2,}"})]
          and spaced == [(m, f" {m} ") for m in _PUNCT_MARKS]
          and steps[-2]["pattern"] == {"Regex": "\\s+"} and steps[-1]["type"] == "Strip"
          and pre["type"] == "Metaspace" and pre["replacement"] == _SPACE
          and pre["prepend_scheme"] == "always"
          and not any(_SPACE in p[1:] for p, _s in model["vocab"]))
    if not ok:
        raise ValueError(f"{SOURCE}@{REVISION}: tokenizer is not the one this "
                         "module reproduces")


def build(dest: Path, words: int = WORDS, source: Path | None = None) -> Path:
    """Download the source, cut it, and write it to `dest`, whole or not at
    all. Needs `wordfreq` (a dev dependency; the image adds it for this step
    only), ~600MB of download and ~1GB of memory for a minute — never run on
    a serving instance. `source`: a directory already holding the source's
    tokenizer.json and model.safetensors, instead of downloading them."""
    from wordfreq import top_n_list

    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        def fetch(name: str) -> Path:
            return source / name if source else _fetch(name, Path(tmp))

        tok = json.loads(fetch("tokenizer.json").read_text())
        _check_tokenizer(tok)
        full = _read_safetensors(fetch("model.safetensors"))
        listed = tok["model"]["vocab"]
        pieces = [p for p, _s in listed]
        scores = [s for _p, s in listed]
        unknown = min(scores) - 10.0  # over the whole source
        specials = tuple(i for i, p in enumerate(pieces) if p in ("[PAD]", "[UNK]"))
        vocab = _Vocab(pieces, scores, unknown, skip=specials)

        keep: set[int] = set()
        for lang in LANGS:
            common = top_n_list(lang, words, wordlist="large")
            capitalised = [w.capitalize() for w in common]
            for form in common + capitalised + [w.upper() for w in common[: words // 4]]:
                keep.update(vocab.tokenize(form))
            # ...and as the second half of a joined name: "TopStocks" is
            # ▁Top + Stock + s, and without the bare "Stock" it would be
            # spelled out of fragments that mean nothing.
            for form in capitalised:
                keep.update(vocab.segment(form))
        for piece, i in vocab.ids.items():
            bare = piece.lstrip(_SPACE)
            if all(ord(c) < 0x100 or c == _SPACE for c in piece) and (
                    len(bare) <= 1 or not any(c.isalpha() for c in bare)):
                keep.add(i)

        order = sorted(keep)
        rows = np.asarray(full[order], dtype=np.float32)
        scale = float(np.abs(rows).max()) / 127.0
        quantized = np.clip(np.round(rows / scale), -127, 127).astype(np.int8)

        # Written in place inside a directory no reader knows of yet, then
        # swapped in whole (no stocks.atomic: this module stands alone).
        out = Path(tmp) / "out"
        out.mkdir()
        np.save(out / "vectors.npy", quantized)
        np.save(out / "scores.npy", np.asarray([scores[i] for i in order]))
        kept = json.dumps([pieces[i] for i in order], ensure_ascii=False)
        meta = json.dumps({"name": NAME, "source": SOURCE, "revision": REVISION,
                           "langs": LANGS, "words": words, "pieces": len(order),
                           "unknown": unknown})
        (out / "pieces.json").write_text(kept)
        (out / "meta.json").write_text(meta)
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(out, dest)
    return dest


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
