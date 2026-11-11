"""A question about an earlier talk — "¿te acuerdas de lo que hablamos ayer?" —
names nothing a search could rank by, so it is answered by date: the
conversations of that day, or the latest ones (`recall.asked_back`,
`recall.back`). In prod (2026-11-11) the same question got "No conservo el
historial de conversaciones de días anteriores" while the index held the day
before word for word."""

from __future__ import annotations

from datetime import date

import pytest

from stocks.chat import clock, conversations, memory, toolbox
from stocks.chat.engine import recall
from stocks.chat.engine.recall import Span, asked_back

WED = date(2026, 11, 11)  # a Wednesday


# ------------------------------------------------------------- the question


@pytest.mark.parametrize(("message", "span"), [
    ("¿te acuerdas de lo que hablamos ayer?", Span("2026-11-10", "2026-11-10")),
    ("Te acuerdas de lo que hablamos ayer", Span("2026-11-10", "2026-11-10")),
    ("¿de qué hablamos anteayer?", Span("2026-11-09", "2026-11-09")),
    ("¿qué me dijiste hace 3 días?", Span("2026-11-08", "2026-11-08")),
    ("¿qué me dijiste hace tres días?", Span("2026-11-08", "2026-11-08")),
    ("lo que hablamos el lunes", Span("2026-11-09", "2026-11-09")),
    # On a Wednesday, "el miércoles" is a week ago, not today.
    ("lo que hablamos el miércoles", Span("2026-11-04", "2026-11-04")),
    ("¿qué hablamos la semana pasada?", Span("2026-11-02", "2026-11-08")),
    ("¿de qué hablamos el otro día?", Span("2026-11-04", "2026-11-10")),
    ("what did we discuss yesterday?", Span("2026-11-10", "2026-11-10")),
    ("do you remember what we talked about last week?",
     Span("2026-11-02", "2026-11-08")),
    ("ti ricordi di cosa abbiamo parlato ieri?", Span("2026-11-10", "2026-11-10")),
    # Undated: the latest conversations.
    ("¿te acuerdas de lo que hablamos?", Span()),
    ("¿recuerdas lo que te dije?", Span()),
    ("en la otra conversación te pregunté por Inditex", Span()),
    ("what did we talk about last time?", Span()),
    ("in our previous conversation you said something", Span()),
])
def test_a_question_about_an_earlier_talk_is_a_span(message, span):
    assert asked_back(message, WED) == span


@pytest.mark.parametrize("message", [
    # About the market or the book, not the talk.
    "¿qué pasó ayer en bolsa?",
    "¿te acuerdas de cuando cayó el S&P en 2020?",
    "la última vez que compré NVDA fue en marzo",
    "what happened to Nvidia yesterday?",
    # A memory command, not a question back.
    "recuerda que vendo ASML a 900",
    "recuerda que hablamos de vender ASML",
    # Could be this very conversation, which is already in the prompt.
    "¿qué dijiste de NVDA?",
    "you said NVDA was cheap, why?",
    "",
])
def test_anything_else_is_not(message):
    assert asked_back(message, WED) is None


# ------------------------------------------------------------- the lookup

needs_memory = pytest.mark.skipif(
    not memory.available(),
    reason="memory needs the embedder + sqlite-vec; the chat degrades without them",
)


def _talk(chat, monkeypatch, day: date, title: str, asked: str, said: str) -> str:
    monkeypatch.setattr(clock, "today", lambda: day)
    cid = conversations.new_conversation(chat)
    conversations.save_chat([{"role": "user", "content": asked},
                             {"role": "assistant", "content": said}], chat, cid)
    conversations.rename_conversation(cid, title, chat)
    book = conversations.load_book(chat)
    for conv in book["conversations"]:
        if conv["id"] == cid:
            conv["updated"] = f"{day.isoformat()}T10:00:00+00:00"
    conversations.save_book(book, chat)
    return cid


@pytest.fixture
def chat(tmp_path, monkeypatch):
    """Two earlier talks — Monday's about PEG, Tuesday's about Inditex — and
    the one in progress on Wednesday."""
    path = tmp_path / "chat.json"
    _talk(path, monkeypatch, date(2026, 11, 9), "Ratio PEG",
          "¿Qué es el ratio PEG y cómo se calcula?",
          "El PEG divide el PER entre el crecimiento esperado de beneficios")
    _talk(path, monkeypatch, date(2026, 11, 10), "Inditex dividendos",
          "¿Cuándo paga Inditex el próximo dividendo?",
          "Inditex reparte en dos pagos, noviembre y mayo, a partes iguales")
    monkeypatch.setattr(clock, "today", lambda: WED)
    conversations.new_conversation(path)
    return path


@needs_memory
def test_yesterday_brings_back_yesterday_s_talk(chat):
    hits, threads, lead = recall.earlier({}, chat, "¿te acuerdas de lo que "
                                                   "hablamos ayer?", today=WED)
    assert [t["title"] for t in threads] == ["Inditex dividendos"]
    assert "Inditex" in hits[0].text and hits[0].title == "Inditex dividendos"
    assert "on 2026-11-10" in lead
    out = memory.augment("¿te acuerdas?", hits, lead)
    assert lead in out and memory.QUOTE_HEADER in out
    assert "Inditex dividendos" in out and "PEG" not in out


@needs_memory
def test_undated_brings_back_the_latest_talks_newest_first(chat):
    _, threads, lead = recall.earlier({}, chat, "¿te acuerdas de lo que "
                                               "hablamos?", today=WED)
    assert [t["title"] for t in threads] == ["Inditex dividendos", "Ratio PEG"]
    assert "most recent" in lead


@needs_memory
def test_a_day_with_no_talk_says_so_and_brings_the_latest(chat):
    _, threads, lead = recall.earlier({}, chat, "¿de qué hablamos el "
                                               "jueves?", today=WED)
    assert "nothing was said" in lead and "2026-11-05" in lead
    assert threads[0]["title"] == "Inditex dividendos"


@needs_memory
def test_the_conversation_in_progress_is_not_an_earlier_one(chat, monkeypatch):
    conversations.save_chat([{"role": "user", "content": "¿Qué hablamos hoy "
                              "de Ferrovial y su dividendo?"},
                             {"role": "assistant", "content": "Nada aún"}], chat)
    _, threads, _ = recall.earlier({}, chat, "¿te acuerdas de lo que "
                                            "hablamos?", today=WED)
    assert "Ferrovial" not in str(threads)


@needs_memory
def test_a_deleted_talk_never_comes_back(chat):
    yesterday = next(c for c in conversations.list_conversations(chat)
                     if c["title"] == "Inditex dividendos")
    conversations.delete_conversation(yesterday["id"], chat)
    hits, threads, _ = recall.earlier({}, chat, "¿te acuerdas de lo que "
                                               "hablamos?", today=WED)
    assert [t["title"] for t in threads] == ["Ratio PEG"]
    assert all("Inditex" not in h.text for h in hits)


@needs_memory
def test_a_card_nobody_answered_is_not_a_talk(chat, monkeypatch):
    conversations.save_card_thread("2026-11-10", "Tu día",
                                   "Hoy NVDA presenta resultados", chat)
    _, threads, _ = recall.earlier({}, chat, "¿qué hablamos ayer?", today=WED)
    assert [t["title"] for t in threads] == ["Inditex dividendos"]


def test_recall_switched_off_says_so_instead_of_no_history(chat):
    hits, threads, lead = recall.earlier({"chat_recall": False}, chat,
                                         "¿te acuerdas de lo que hablamos "
                                         "ayer?", today=WED)
    assert (hits, threads) == ([], [])
    assert lead == recall._BACK_OFF


def test_no_chat_yet_is_no_earlier_talk(tmp_path):
    _, _, lead = recall.earlier({}, tmp_path / "chat.json",
                                "¿qué hablamos ayer?", today=WED)
    assert lead == recall._BACK_NONE


def test_any_other_message_has_no_lead(tmp_path):
    assert recall.earlier({}, tmp_path / "chat.json", "¿cómo va NVDA?",
                          today=WED) == ([], [], "")


# ------------------------------------------------------------- the index


@needs_memory
def test_between_keeps_the_days_asked(chat):
    index = conversations.memory_path(chat)
    days = {m.when for m in memory.between(index, "2026-11-10", "2026-11-10")}
    assert days == {"2026-11-10"}
    assert {m.when for m in memory.between(index)} == {"2026-11-09",
                                                       "2026-11-10"}


@needs_memory
def test_recall_by_query_keeps_to_the_days(chat):
    index = conversations.memory_path(chat)
    hits = memory.recall(index, "dividendo", since="2026-11-09",
                         until="2026-11-09")
    assert hits and all(h.when == "2026-11-09" for h in hits)


def test_augment_with_a_lead_and_nothing_quoted():
    out = memory.augment("¿y ayer?", [], "Say none is kept.")
    assert out == "¿y ayer?\n\n---\nSay none is kept."
    assert memory.QUOTE_HEADER not in out


@needs_memory
def test_the_recall_tool_takes_dates_without_a_query(chat):
    ctx = toolbox.Context(memory_db=conversations.memory_path(chat))
    out = toolbox.TOOLS["recall"][1]({"since": "2026-11-09",
                                      "until": "2026-11-09"}, ctx)
    assert out.startswith(memory.QUOTE_HEADER)
    assert "PEG" in out and "Inditex" not in out
    assert toolbox.TOOLS["recall"][1]({}, ctx) == "No query or dates given."
