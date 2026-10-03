"""Home's daily card, filed in the chat as a conversation of its own.

It is one assistant: what the card told the reader on Home is something it
said, so the chat has to know it. What is tested here:

* each card day is one thread, titled with the day, that never becomes the
  active one by itself — the card is written in the background, and a reader
  mid-conversation must not find the next answer landing in it;
* the same card filed twice changes nothing; a card rewritten the same day
  replaces its turn until the reader answers it, and lands after their turns
  once they have;
* the cards nobody answered are capped apart, so a month of them cannot push
  the reader's conversations out of the book;
* the model gets the card in a card thread even though the thread opens with
  it (`engine.recent`), and the chat's prompt quotes the latest card wherever
  the question is asked (`engine.card_block`);
* the other surfaces do not read old card lines back as the user talking.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from stocks import accounts
from stocks.chat import daily, engine, memory
from stocks.web import auth

DAY = "2026-10-03"


@pytest.fixture
def chat(tmp_path) -> Path:
    return tmp_path / "chat.json"


def card(day: str = DAY, headline: str = "NVDA crossed your alert",
         lines=("NVDA closed above your 180 alert.", "Earnings for ASML in 2 days."),
         lang: str = "en") -> daily.DailyAction:
    return daily.DailyAction(
        day=day, headline=headline, bullets=list(lines), lang=lang,
        as_of="2026-10-02",
        items=[{"key": f"k{n}", "kind": "", "line": line, "tickers": []}
               for n, line in enumerate(lines)],
    )


def thread_of(chat: Path, cid: str) -> dict:
    return next(c for c in auth.load_book(chat)["conversations"] if c["id"] == cid)


# ------------------------------------------------------------------ filing


def test_a_card_is_filed_as_its_own_thread_titled_with_its_day(chat):
    auth.save_chat([{"role": "user", "content": "hola"}], chat)
    active = auth.active_conversation(chat)["id"]

    cid = daily.record(chat, card())

    assert cid and cid != active
    assert auth.active_conversation(chat)["id"] == active, "never takes the active slot"
    meta = next(c for c in auth.list_conversations(chat) if c["id"] == cid)
    assert meta["title"] == "Daily action · Oct 3"
    assert meta["daily"] == DAY and not meta["title_auto"]
    (turn,) = thread_of(chat, cid)["messages"]
    assert turn["role"] == "assistant" and turn["daily"] == DAY
    assert turn["content"] == (
        "**NVDA crossed your alert**\n\n"
        "- NVDA closed above your 180 alert.\n- Earnings for ASML in 2 days."
    )


def test_the_title_is_in_the_cards_language(chat):
    assert daily.thread_title(DAY, "es") == "Acción diaria · 3 oct"
    assert daily.thread_title(DAY, "en") == "Daily action · Oct 3"


def test_a_card_on_an_account_that_never_chatted_starts_the_book(chat):
    cid = daily.record(chat, card())
    convs = auth.list_conversations(chat)
    assert any(c["id"] == cid for c in convs)
    assert auth.active_conversation(chat)["id"] != cid
    assert auth.load_chat(chat) == [], "the reader's next message goes elsewhere"


def test_the_same_card_twice_changes_nothing(chat):
    cid = daily.record(chat, card())
    before = chat.read_text()
    assert daily.record(chat, card()) == cid
    assert chat.read_text() == before


def test_a_rewritten_card_replaces_its_turn_until_somebody_answers(chat):
    cid = daily.record(chat, card(headline="Stand-in"))
    assert daily.record(chat, card(headline="Written")) == cid
    (turn,) = thread_of(chat, cid)["messages"]
    assert turn["content"].startswith("**Written**")


def test_a_card_rewritten_after_the_reader_answered_lands_after_their_turns(chat):
    cid = daily.record(chat, card(headline="Stand-in"))
    auth.set_active_conversation(cid, chat)
    asked = [*auth.load_chat(chat),
             {"role": "user", "content": "¿por qué NVDA?"},
             {"role": "assistant", "content": "Porque cruzó tu alerta."}]
    auth.save_chat(asked, chat)

    daily.record(chat, card(headline="Written"))

    turns = thread_of(chat, cid)["messages"]
    assert [t["role"] for t in turns] == ["assistant", "user", "assistant", "assistant"]
    assert turns[0]["content"].startswith("**Stand-in**"), "what they asked about stays"
    assert turns[-1]["content"].startswith("**Written**")


def test_each_day_is_its_own_thread(chat):
    first = daily.record(chat, card(day="2026-10-02"))
    second = daily.record(chat, card(day="2026-10-03"))
    assert first != second


def test_a_card_that_cannot_be_filed_keeps_the_days_thread(chat, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(auth, "save_card_thread", broken)
    assert daily.record(chat, card()) == ""
    earlier = daily.DailyAction.from_dict({**card().to_dict(), "thread": "c_keep"})
    assert daily.filed(earlier, card(), chat) == "c_keep"
    yesterday = daily.DailyAction.from_dict(
        {**card(day="2026-10-02").to_dict(), "thread": "c_old"})
    assert daily.filed(yesterday, card(), chat) == ""


def test_the_thread_survives_the_card_file(chat):
    stored = daily.DailyAction.from_dict({**card().to_dict(), "thread": "c_1"})
    assert stored.thread == "c_1"
    assert daily.DailyAction.from_dict(card().to_dict()).thread == ""


def test_the_card_file_sits_beside_the_chat_in_every_account(tmp_path):
    paths = accounts.paths_for("someone@example.com", None, users_dir=tmp_path)
    assert daily.card_path(paths.chat) == paths.action
    owner = accounts.paths_for("o@example.com", "o@example.com", users_dir=tmp_path)
    assert daily.card_path(owner.chat) == owner.action
    assert daily.card_path(accounts.guest_paths().chat) == accounts.guest_paths().action


# --------------------------------------------------------------------- cap


def _thread(i: int, *, daily_day: str = "", user: bool = True) -> dict:
    turns = []
    if daily_day:
        turns.append({"role": "assistant", "content": "card", "daily": daily_day})
    if user:
        turns.append({"role": "user", "content": str(i)})
    return {"id": f"c_{i:04d}", "title": str(i), "title_auto": True,
            "created": "2020-01-01T00:00:00+00:00",
            "updated": f"2020-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00",
            "messages": turns, **({"daily": daily_day} if daily_day else {})}


def test_unanswered_cards_are_capped_apart_from_conversations(chat):
    talk = [_thread(i) for i in range(auth.MAX_CONVERSATIONS)]
    cards = [_thread(1000 + i, daily_day=f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
                     user=False)
             for i in range(auth.MAX_CARD_THREADS + 10)]
    book = auth.load_book(chat)
    book["conversations"] = talk + cards
    book["active"] = talk[0]["id"]
    auth.save_book(book, chat)

    kept = {c["id"] for c in auth.list_conversations(chat)}
    assert {c["id"] for c in talk} <= kept, "no conversation made room for a card"
    kept_cards = [c for c in cards if c["id"] in kept]
    assert len(kept_cards) == auth.MAX_CARD_THREADS
    assert cards[-1]["id"] in kept and cards[0]["id"] not in kept  # newest kept


def test_a_card_the_reader_answered_is_kept_like_a_conversation(chat):
    answered = _thread(1, daily_day="2026-01-01", user=True)
    cards = [_thread(100 + i, daily_day=f"2026-02-{1 + i:02d}", user=False)
             for i in range(auth.MAX_CARD_THREADS)]
    book = auth.load_book(chat)
    book["conversations"] = [answered, *cards]
    book["active"] = cards[0]["id"]
    auth.save_book(book, chat)
    assert answered["id"] in {c["id"] for c in auth.list_conversations(chat)}


# ------------------------------------------------------------- the chat


def test_a_card_thread_reaches_the_model_with_the_card_in_it():
    history = [{"role": "assistant", "content": "**Card**\n\n- line", "daily": DAY},
               {"role": "user", "content": "¿por qué?"}]
    msgs = engine.recent(history)
    assert msgs[0] == {"role": "user",
                       "content": engine.CARD_OPENER.format(day=DAY)}
    assert msgs[1] == {"role": "assistant", "content": "**Card**\n\n- line"}
    assert msgs[-1]["content"] == "¿por qué?"


def test_any_other_leading_answer_is_still_trimmed():
    history = [{"role": "assistant", "content": "hello"},
               {"role": "user", "content": "hi"}]
    assert engine.recent(history) == [{"role": "user", "content": "hi"}]


def test_the_chat_prompt_quotes_the_latest_card(chat):
    daily.card_path(chat).write_text(json.dumps(card().to_dict()))
    block = engine.card_block(chat, today=date(2026, 10, 3))
    assert "**NVDA crossed your alert**" in block
    assert "- Earnings for ASML in 2 days." in block
    assert "2026-10-02" in block, "says which session its figures are from"


def test_an_old_or_missing_card_is_not_quoted(chat):
    assert engine.card_block(chat, today=date(2026, 10, 3)) == ""
    daily.card_path(chat).write_text(json.dumps(card(day="2026-09-20").to_dict()))
    assert engine.card_block(chat, today=date(2026, 10, 3)) == ""
    daily.card_path(chat).write_text("{broken")
    assert engine.card_block(chat, today=date(2026, 10, 3)) == ""


def test_the_other_surfaces_do_not_read_old_cards_back_as_the_user(chat, monkeypatch):
    cid = daily.record(chat, card())
    other = auth.active_conversation(chat)["id"]
    auth.save_chat([{"role": "user", "content": "x"}], chat)
    hits = [
        memory.Memory(thread=cid, role="assistant", when=DAY, text="NVDA card", rank=1),
        memory.Memory(thread=cid, role="user", when=DAY, text="NVDA me", rank=2),
        memory.Memory(thread=other, role="assistant", when=DAY, text="NVDA chat", rank=3),
    ]
    monkeypatch.setattr(memory, "about", lambda *a, **k: list(hits))

    assert [h.text for h in engine.talk_about({}, chat, ["NVDA"])] == [
        "NVDA card", "NVDA me", "NVDA chat"]
    assert [h.text for h in engine.talk_about({}, chat, ["NVDA"], cards=False)] == [
        "NVDA me", "NVDA chat"]
    assert [h.text for h in engine.user_memory({}, chat, ["NVDA"])[1]] == [
        "NVDA me", "NVDA chat"]
