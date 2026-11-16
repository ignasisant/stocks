"""Answers worth a second look, found without a vote (chat/review.py)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from stocks.chat import conversations, engine, guard, review


@pytest.fixture
def seen(monkeypatch):
    out: list[tuple[str, dict]] = []
    monkeypatch.setattr(review.obs, "event",
                        lambda name, **f: out.append((name, f)))
    monkeypatch.setattr(review.obs, "warn",
                        lambda name, **f: out.append((name, f)))
    return out


def _reviews(seen):
    return [f for name, f in seen if name == review.EVENT]


# ------------------------------------------------------------------- figures


def test_the_pool_is_every_number_the_model_was_shown():
    shown = review.pool("Book: 1.234,50 EUR in NVDA", [
        {"role": "user", "content": "¿Cómo va NVDA a 182,40?"},
        {"role": "user", "content": [{"type": "text", "text": "P/E 54.3"},
                                     {"type": "image_url", "image_url": {}}]},
    ])
    assert {1234.5, 182.4, 54.3} <= set(shown)


def test_figures_counts_what_nothing_shown_states():
    shown = [182.4, 54.3]
    assert review.figures("NVDA cotiza a 182,40 con un PER de 54,3.", shown) == (2, 0)
    assert review.figures("RSI 71,2, MA50 en 168,90 y soporte en 155.", shown) == (3, 3)


def test_years_counts_and_windows_are_no_figures():
    assert review.figures("En 2025 subió 3 veces; media de 200 días.", []) == (0, 0)


def test_an_answer_whose_figures_come_from_nowhere_is_logged(seen):
    review.check_answer("RSI 71,2, MA50 en 168,90 y soporte en 155.",
                        system="Quote NVDA 182.40", messages=[],
                        provider="free", model="m", skills=["ticker"])
    [line] = _reviews(seen)
    assert line["kind"] == "figures"
    assert (line["figures"], line["unsourced"]) == (3, 3)
    assert line["skills"] == ["ticker"]
    # Counts only: never the figures, which can be the reader's amounts.
    assert not any(isinstance(v, float) for v in line.values())


def test_an_answer_quoting_what_it_was_shown_is_not(seen):
    review.check_answer("NVDA a 182,40, PER 54,3; tienes 1.234,50 €.",
                        system="NVDA 182.40 pe 54.3",
                        messages=[{"role": "user", "content": "value 1234.5"}],
                        provider="free", model="m", skills=[])
    assert _reviews(seen) == []


def test_one_worked_out_figure_is_below_the_flag(seen):
    # 182.40 × 10 shares: the model added it up, nothing invented.
    review.check_answer("Tus 10 acciones a 182,40 valen 1.824 €.",
                        system="NVDA 182.40, held 10 shares", messages=[],
                        provider="free", model="m", skills=[])
    assert _reviews(seen) == []


def test_a_failing_check_costs_a_lead_never_the_answer(seen, monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad")

    monkeypatch.setattr(review, "pool", boom)
    review.check_answer("x", system="", messages=[], provider="p", model="m",
                        skills=[])
    assert seen == [("chat.review_failed",
                     {"step": "figures", "error_type": "ValueError"})]


# ------------------------------------------------------------------ question


def _thread(question: str, then: str, *, answer_id: str = "a1") -> list[dict]:
    answer = {"role": "assistant", "content": "…", "provider": "free",
              "skills": ["ticker"]}
    if answer_id:
        answer["id"] = answer_id
    return [{"role": "user", "content": question}, answer,
            {"role": "user", "content": then}]


@pytest.mark.parametrize("said", [
    "Eso está mal, NVDA no está a ese precio",
    "no es correcto",
    "Te has equivocado con el PER",
    "esto no cuadra con mi broker",
    "te lo has inventado",
    "That's wrong",
    "you made that up",
    "Questo è sbagliato",
    "non è corretto il prezzo",
])
def test_a_complaint_is_logged_against_the_answer_above(seen, said):
    review.check_question(_thread("¿A cuánto está NVDA?", said))
    [line] = _reviews(seen)
    assert line == {"kind": "complaint", "answer": "a1", "provider": "free",
                    "skills": ["ticker"]}


@pytest.mark.parametrize("said", [
    "¿y AMD?",
    "Su tracking error es alto",
    "¿Qué hago si el trimestre fue mal?",
    "dame más detalle del margen",
])
def test_a_follow_up_is_no_complaint(seen, said):
    review.check_question(_thread("¿A cuánto está NVDA hoy?", said))
    assert _reviews(seen) == []


def test_the_same_question_again_is_a_rephrase(seen):
    review.check_question(_thread(
        "¿Cuál es el PER actual de Nvidia y su media histórica?",
        "Te pregunto el PER actual de Nvidia y su media histórica"))
    [line] = _reviews(seen)
    assert line["kind"] == "rephrase" and line["answer"] == "a1"


def test_an_answer_no_model_wrote_is_not_judged(seen):
    review.check_question(_thread("¿A cuánto está NVDA?", "eso está mal",
                                  answer_id=""))
    assert _reviews(seen) == []


def test_a_first_question_has_nothing_to_judge(seen):
    review.check_question([{"role": "user", "content": "eso está mal"}])
    assert _reviews(seen) == []


# -------------------------------------------------------------------- engine


@dataclass
class _Writes:
    reply: str
    id: str = "free"
    classifier_model: str = "cheap"
    default_model: str = "default-model"

    def available(self) -> bool:
        return True

    def complete(self, api_key, model, system, messages) -> str:
        return self.reply


def test_the_engine_reviews_answers_and_the_questions_after_them(
        seen, monkeypatch, tmp_path):
    from stocks import llm

    monkeypatch.setattr(guard, "mode", lambda: "off")
    monkeypatch.setattr(llm, "PROVIDERS", {"free": _Writes(
        "RSI 71,2, MA50 en 168,90, soporte en 155,30 y resistencia en 199,80.")})
    monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])
    (tmp_path / "watchlist.yaml").write_text("watchlist: []\n")
    paths = {"prefs_path": tmp_path / "prefs.json",
             "chat_path": tmp_path / "chat.json",
             "watchlist": tmp_path / "watchlist.yaml",
             "db": tmp_path / "portfolio.db"}
    prefs = {"chat_skills_mode": "off"}
    engine.answer(prefs=prefs, message="¿Cómo ves el gráfico de Tesla?",
                  lang="es", **paths)
    [flagged] = _reviews(seen)
    assert flagged["kind"] == "figures" and flagged["unsourced"] == 4

    first = conversations.load_chat(paths["chat_path"])[-1]["id"]
    engine.answer(prefs=prefs, message="Eso está mal, te lo has inventado",
                  lang="es", **paths)
    complaint = [f for f in _reviews(seen) if f["kind"] == "complaint"]
    assert [f["answer"] for f in complaint] == [first]


def test_an_account_that_said_no_is_not_reviewed(seen, monkeypatch, tmp_path):
    from stocks import llm

    monkeypatch.setattr(guard, "mode", lambda: "off")
    monkeypatch.setattr(llm, "PROVIDERS", {"free": _Writes(
        "RSI 71,2, MA50 en 168,90, soporte en 155,30 y resistencia en 199,80.")})
    monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])
    (tmp_path / "watchlist.yaml").write_text("watchlist: []\n")
    paths = {"prefs_path": tmp_path / "prefs.json",
             "chat_path": tmp_path / "chat.json",
             "watchlist": tmp_path / "watchlist.yaml",
             "db": tmp_path / "portfolio.db"}
    prefs = {"chat_skills_mode": "off", review.PREF: False}
    engine.answer(prefs=prefs, message="¿Cómo ves el gráfico de Tesla?",
                  lang="es", **paths)
    engine.answer(prefs=prefs, message="Eso está mal, te lo has inventado",
                  lang="es", **paths)
    assert _reviews(seen) == []


# --------------------------------------------------------------------- judge


@dataclass
class _Judge:
    """The free chain, answering the judge's call with fixed scores."""

    calls: list
    raises: Exception | None = None
    id: str = "free"
    classifier_model: str = "cheap"
    default_model: str = "default-model"

    def available(self) -> bool:
        return True

    def complete(self, api_key, model, system, messages) -> str:
        self.calls.append((api_key, system, messages))
        if self.raises is not None:
            raise self.raises
        return ('{"goals": [], "scores": ['
                '{"id": "answer_quality", "value": 2, "why": "NVDA at 182 is wrong"},'
                '{"id": "grounded", "value": 1, "why": "x"},'
                '{"id": "tone", "value": 5, "why": "x"}]}')


@pytest.fixture
def judge(monkeypatch):
    from stocks import llm

    review._reset()
    monkeypatch.setattr(review, "judge_mode", lambda: "on")
    monkeypatch.setattr(review.random, "random", lambda: 1.0)  # never sampled
    fake = _Judge([])
    monkeypatch.setattr(llm, "PROVIDERS", {"free": fake})
    yield fake
    review._reset()


def _queue(**over):
    args = {"system": "", "messages": [{"role": "user", "content": "q + quotes"}],
            "steps": [], "provider": "free", "skills": ["ticker"],
            "prefs": {}, "flagged": True}
    args.update(over)
    return review.judge_answer("a1", "¿A cuánto está NVDA?", "A 182 €.", **args)


def test_a_flagged_free_answer_is_judged_scores_only(seen, judge):
    _queue().result(timeout=5)
    [line] = [f for f in _reviews(seen) if f["kind"] == "judged"]
    assert line == {"kind": "judged", "answer": "a1", "provider": "free",
                    "skills": ["ticker"], "reason": "figures", "tools": 0,
                    "answer_quality": 2, "grounded": 1, "tone": 5}
    # On the free chain, with no key of the reader's.
    [(key, _system, messages)] = judge.calls
    assert key == "" and "q + quotes" in messages[-1]["content"]
    assert not review.judging()


@pytest.mark.parametrize("over", [
    {"provider": "openai"},  # the reader's own key: never to the free chain
    {"prefs": {review.PREF: False}},  # switched off in Profile
    {"flagged": False},  # not flagged, and the sample did not draw it
])
def test_no_judgment_when_not_due(seen, judge, over):
    assert _queue(**over) is None
    assert judge.calls == []


def test_off_unless_the_deploy_says_on(seen, judge, monkeypatch):
    monkeypatch.setattr(review, "judge_mode", lambda: "off")
    assert _queue() is None and judge.calls == []


def test_the_daily_cap_holds(seen, judge, monkeypatch):
    monkeypatch.setattr(review, "DAILY_CAP", 2)
    queued = [_queue() for _ in range(3)]
    assert queued[2] is None
    for f in queued[:2]:
        f.result(timeout=5)
    assert len(judge.calls) == 2


def test_an_empty_pot_stops_judging_for_the_day(seen, judge):
    from stocks import llm

    judge.raises = llm.FreeTierExhausted("all free backends failed")
    _queue().result(timeout=5)
    assert ("chat.review_failed",
            {"step": "judge", "error_type": "FreeTierExhausted"}) in seen
    judge.raises = None
    assert _queue() is None
    assert len(judge.calls) == 1


def test_the_material_is_the_prompt_cut_to_size():
    from stocks import llm

    system = llm.Prompt("persona", "BOOK " + "x" * 9000, "turn part")
    shown = review.material(system, [{"role": "user", "content": "q" * 9000}],
                            [{"tool": "quote", "arg": "NVDA", "out": "182.4"}])
    assert "BOOK" in shown and "persona" not in shown and "turn part" not in shown
    assert "- quote(NVDA): 182.4" in shown
    assert len(shown) < 9000


def test_a_reviewed_answer_is_found_by_its_id():
    book = {"conversations": [{"id": "c1", "messages": [
        {"role": "user", "content": "¿PER de NVDA?"},
        {"role": "assistant", "id": "a1", "content": "54"},
        {"role": "user", "content": "¿Y AMD?"},
        {"role": "assistant", "id": "a2", "content": "90"}]}]}
    question, answer = review.find(book, "a2")
    assert question == "¿Y AMD?" and answer["content"] == "90"
    assert review.find(book, "zz") is None


def test_the_engine_hands_the_stored_answer_to_the_judge(
        seen, monkeypatch, tmp_path):
    from stocks import llm

    monkeypatch.setattr(guard, "mode", lambda: "off")
    monkeypatch.setattr(llm, "PROVIDERS", {"free": _Writes(
        "RSI 71,2, MA50 en 168,90, soporte en 155,30 y resistencia en 199,80.")})
    monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])
    handed = []
    monkeypatch.setattr(review, "judge_answer",
                        lambda *a, **k: handed.append((a, k)))
    (tmp_path / "watchlist.yaml").write_text("watchlist: []\n")
    engine.answer(prefs={"chat_skills_mode": "off"},
                  message="¿Cómo ves el gráfico de Tesla?", lang="es",
                  prefs_path=tmp_path / "prefs.json",
                  chat_path=tmp_path / "chat.json",
                  watchlist=tmp_path / "watchlist.yaml",
                  db=tmp_path / "portfolio.db")
    [((answer_id, question, answer), k)] = handed
    stored = conversations.load_chat(tmp_path / "chat.json")[-1]
    assert answer_id == stored["id"] and answer == stored["content"]
    assert question == "¿Cómo ves el gráfico de Tesla?"
    assert k["provider"] == "free" and k["flagged"] is True


# ── stocks review-answer ───────────────────────────────────────────────────


def _cli_account(tmp_path, monkeypatch, prefs: dict | None) -> None:
    import json

    from stocks import config, storage

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "enabled", lambda: False)
    home = tmp_path / "users" / "u1"
    home.mkdir(parents=True)
    if prefs is not None:
        (home / "prefs.json").write_text(json.dumps(prefs))
    (home / "chat.json").write_text(json.dumps([
        {"role": "user", "content": "¿Cuánto pesa NVDA?"},
        {"role": "assistant", "id": "a1", "content": "Un 12 %.",
         "provider": "free"},
    ]))


def _review_answer(answer: str = "a1") -> None:
    import argparse

    from stocks import cli

    cli.cmd_review_answer(argparse.Namespace(user="u1", answer=answer))


def test_review_answer_prints_the_question_and_the_answer(
        tmp_path, monkeypatch, capsys):
    _cli_account(tmp_path, monkeypatch, {})
    _review_answer()
    out = capsys.readouterr().out
    assert "Q: ¿Cuánto pesa NVDA?" in out
    assert "A: Un 12 %." in out


def test_review_answer_refuses_an_account_that_switched_review_off(
        tmp_path, monkeypatch, capsys):
    _cli_account(tmp_path, monkeypatch, {review.PREF: False})
    with pytest.raises(SystemExit, match="switched answer review off"):
        _review_answer()
    assert "NVDA" not in capsys.readouterr().out


def test_review_answer_refuses_when_the_choice_cannot_be_read(
        tmp_path, monkeypatch, capsys):
    """No prefs.json is no answer to "may this be read?": fail closed."""
    _cli_account(tmp_path, monkeypatch, None)
    with pytest.raises(SystemExit, match="no prefs.json"):
        _review_answer()
    assert "NVDA" not in capsys.readouterr().out
