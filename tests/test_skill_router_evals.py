"""Trigger evals for the skill router's offline half (the keyword fallback).

The questions live in evals/router/triggers.yaml. The floors below come from
the measured baseline: raise them when the vocabulary improves, never lower
them to make a change pass. The live LLM router is measured, not gated, by
scripts/eval_router.py."""

import pytest

from stocks.chat import router_eval
from stocks.web import chat_skills

CASES = router_eval.load()
ROWS = router_eval.score(chat_skills.heuristic, CASES)

# Measured 2026-10-23 over 6 should / 3 near-miss questions per skill:
# 101/102 recall, 1/51 false positives. Floors leave one question of slack
# for a skill and a few overall.
MIN_RECALL_SKILL = 5 / 6
MIN_RECALL_TOTAL = 0.95
MAX_FP_SKILL = 1 / 3
MAX_FP_TOTAL = 0.05


def test_every_skill_has_trigger_cases():
    assert set(CASES) == chat_skills.valid_ids()
    for sid, c in CASES.items():
        assert len(c["should"]) >= 6, sid
        assert len(c["near_miss"]) >= 3, sid
        assert len(set(c["should"] + c["near_miss"])) == len(
            c["should"] + c["near_miss"]), sid


def test_every_skill_has_keywords():
    for s in chat_skills.catalog():
        assert len(s.keywords) >= 8, s.id


@pytest.mark.parametrize("sid", sorted(CASES))
def test_skill_recall(sid):
    row = ROWS[sid]
    assert row.recall >= MIN_RECALL_SKILL, (sid, row.missed)


@pytest.mark.parametrize("sid", sorted(CASES))
def test_skill_near_miss(sid):
    row = ROWS[sid]
    assert row.fp_rate <= MAX_FP_SKILL, (sid, row.leaked)


def test_totals():
    recall, fp = router_eval.totals(ROWS)
    assert recall >= MIN_RECALL_TOTAL
    assert fp <= MAX_FP_TOTAL


@pytest.mark.parametrize("text", ["hola, ¿qué tal?", "how do I import my statement?",
                                  "gracias", ""])
def test_chatter_picks_nothing(text):
    assert chat_skills.heuristic(text) == []


def test_heuristic_folds_accents_and_caps_at_max_auto():
    assert chat_skills.heuristic("INFLACIÓN y tipos del BCE") == ["macro"]
    got = chat_skills.heuristic(
        "bitcoin etf dividend yield rsi fed inflation earnings")
    assert len(got) == chat_skills.MAX_AUTO


def test_whole_word_keywords():
    assert "crypto" not in chat_skills.heuristic("is this ethical?")
    assert "crypto" in chat_skills.heuristic("is ETH a buy?")
