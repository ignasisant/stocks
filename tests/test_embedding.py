"""embedding: the cut multilingual model and the tokenizer that replaces `tokenizers`."""

import copy

import numpy as np
import pytest

from stocks.chat import embedding, hybrid

# ------------------------------------------------------------------ search


def _vocab(**scores):
    pieces = list(scores)
    return embedding._Vocab(pieces, [scores[p] for p in pieces], unknown=-30.0)


def test_the_segmentation_with_the_best_total_score_wins():
    vocab = _vocab(**{"▁ab": -1.0, "▁a": -1.0, "b": -1.0, "c": -2.0})
    assert vocab.segment("▁ab") == [0]  # one piece at -1 beats two at -2
    assert vocab.segment("▁abc") == [0, 3]


def test_a_character_no_piece_covers_is_dropped_not_fatal():
    vocab = _vocab(**{"▁a": -1.0, "b": -1.0})
    assert vocab.segment("▁a€b") == [0, 1]


def test_punctuation_is_a_word_of_its_own():
    assert embedding._normalize("  ¿qué tal,ASML?\n") == "¿qué tal , ASML ?"
    assert embedding._normalize("BTC-EUR 5%") == "BTC - EUR 5 %"


def test_a_text_is_cut_where_the_model_was_trained_to_read():
    vocab = _vocab(**{"▁a": -1.0})
    assert len(vocab.tokenize("a " * 2000)) == embedding.MAX_TOKENS


# ---------------------------------------------------------- the source check


def _source_tokenizer():
    marks = [{"type": "Replace", "pattern": {"String": m}, "content": f" {m} "}
             for m in embedding._PUNCT_MARKS]
    return {
        "model": {"type": "Unigram", "byte_fallback": False, "unk_id": 1,
                  "vocab": [["[PAD]", 0.0], ["[UNK]", 0.0], ["▁hola", -2.0]]},
        "normalizer": {"type": "Sequence", "normalizers": [
            {"type": "Sequence", "normalizers": [
                {"type": "Precompiled", "precompiled_charsmap": "…"},
                {"type": "Replace", "pattern": {"Regex": " {2,}"}, "content": " "}]},
            *marks,
            {"type": "Replace", "pattern": {"Regex": "\\s+"}, "content": " "},
            {"type": "Strip", "strip_left": True, "strip_right": True}]},
        "pre_tokenizer": {"type": "Metaspace", "replacement": "▁",
                          "prepend_scheme": "always", "split": False},
    }


def test_the_source_tokenizer_this_module_reproduces_is_accepted():
    embedding._check_tokenizer(_source_tokenizer())


@pytest.mark.parametrize("change", [
    lambda t: t["normalizer"]["normalizers"].pop(3),  # one mark less
    lambda t: t["pre_tokenizer"].update(prepend_scheme="first"),
    lambda t: t["model"].update(byte_fallback=True),
    lambda t: t["model"]["vocab"].append(["▁de▁la", -3.0]),  # a piece across words
])
def test_a_source_tokenizer_that_splits_differently_is_refused(change):
    tok = copy.deepcopy(_source_tokenizer())
    change(tok)
    with pytest.raises(ValueError):
        embedding._check_tokenizer(tok)


# ------------------------------------------------------------- the model

needs_model = pytest.mark.skipif(not hybrid.available(),
                                 reason="needs the built model")


@needs_model
def test_every_row_is_unit_length_and_an_empty_text_is_zero():
    rows = hybrid._model().encode(["¿qué decidí sobre ASML?", "", "   "])
    assert np.isclose(np.linalg.norm(rows[0]), 1.0, atol=1e-5)
    assert not rows[1].any() and not rows[2].any()


@needs_model
def test_a_joined_name_keeps_the_pieces_it_is_made_of():
    model = hybrid._model()
    by_id = {i: p for p, i in model.vocab.ids.items()}
    assert [by_id[i] for i in model.tokenize("TopStocks")] == ["▁Top", "Stock", "s"]


@needs_model
def test_the_same_meaning_in_either_language_lands_together():
    a, b, c = hybrid._model().encode([
        "I sold half my position to cut the risk",
        "Vendí la mitad de mi posición para reducir el riesgo",
        "La pizza de anoche estaba buenísima",
    ])
    assert a @ b > 0.4 > 0.2 > a @ c  # measured 0.55 and 0.11
