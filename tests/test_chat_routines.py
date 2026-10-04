"""Routines: what the user wants to see every day, kept as a memory.

A routine is the one kind of memory that is a request rather than a fact
about the user — "cada mañana enséñame cómo voy contra el S&P" — and the
daily card is where it gets answered. What is tested here:

* the words that ask for one ("cada mañana enséñame…", "añade X a mi acción
  diaria") and the ones that only sound like it;
* the cap, apart from the memory's own: the card answers them in one call;
* the third way in — the same question on ROUTINE_DAYS different days
  (`learnings.notice`) — and that a routine the user deleted stays deleted;
* the chat's note, the drawer's change and the Telegram line that say so.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from stocks.chat import engine, learnings
from stocks.chat.learnings import Command

DAY = date(2026, 10, 3)


def day(n: int) -> str:
    """`n` days after DAY, as `notice` takes it."""
    return (DAY + timedelta(days=n)).isoformat()


@pytest.fixture
def path(tmp_path, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda p: None)
    return tmp_path / learnings.FILE


def stored(path) -> dict:
    return json.loads(path.read_text())


# -------------------------------------------------------------- the words


@pytest.mark.parametrize("message, expected", [
    ("cada mañana enséñame cómo voy contra el S&P",
     Command("remember", "cada mañana enséñame cómo voy contra el S&P",
             kind="routine")),
    ("Enséñame cada mañana cómo va mi cartera?",
     Command("remember", "Enséñame cada mañana cómo va mi cartera",
             kind="routine")),
    ("todos los días dime qué ha pasado con mis alertas",
     Command("remember", "todos los días dime qué ha pasado con mis alertas",
             kind="routine")),
    ("every morning show me how I'm doing against the S&P",
     Command("remember", "every morning show me how I'm doing against the S&P",
             kind="routine")),
    ("añade el precio del oro a mi acción diaria",
     Command("remember", "el precio del oro", kind="routine")),
    ("add the EUR/USD rate to my daily card",
     Command("remember", "the EUR/USD rate", kind="routine")),
    # Too short to stand alone: the request is kept whole.
    ("añade el oro a mi acción diaria",
     Command("remember", "añade el oro a mi acción diaria", kind="routine")),
])
def test_asking_for_something_every_day_is_a_routine(message, expected):
    assert learnings.command(message) == expected


def test_a_question_after_the_routine_is_still_answered():
    order = learnings.command("cada mañana dime el precio del oro, ¿cuánto está hoy?")
    assert order == Command("remember", "cada mañana dime el precio del oro",
                            "¿cuánto está hoy?", kind="routine")


@pytest.mark.parametrize("message", [
    "cada día NVDA baja, ¿por qué?",
    "todos los días me dices lo mismo",
    "recuérdame mañana vender",
    "¿qué tal NVDA hoy?",
])
def test_an_observation_or_a_complaint_is_not_a_routine(message):
    assert learnings.command(message) is None


@pytest.mark.parametrize("text, kind", [
    ("Cada mañana quiero ver cómo va el oro", "routine"),
    ("Every morning tell me if I'm near my goal", "routine"),
    ("Mi objetivo es jubilarme a los 55", "goal"),
    ("No me digas cada día lo mismo", "context"),
    ("Never send me the daily summary", "constraint"),
])
def test_a_routine_is_told_apart_by_its_every_day(text, kind):
    assert learnings.guess_kind(text) == kind


def test_remember_that_with_an_every_day_is_a_routine_too(path):
    order = learnings.command("recuerda que cada mañana quiero ver el oro")
    item, _ = learnings.add(path, order.text, kind=order.kind or None)
    assert item.kind == "routine"


# ---------------------------------------------------------------- the cap


def test_routines_are_capped_apart_from_the_memory(path):
    for n in range(learnings.MAX_ROUTINES):
        learnings.add(path, f"Cada mañana dime cómo va la posición {n}")
    with pytest.raises(learnings.RoutinesFull):
        learnings.add(path, "Cada mañana dime cómo va el oro")
    # A fact still fits, and a full routine list is a Full to the API (409).
    learnings.add(path, "Prefiero dividendos crecientes")
    assert issubclass(learnings.RoutinesFull, learnings.Full)


def test_a_memory_turned_into_a_routine_respects_the_cap(path):
    for n in range(learnings.MAX_ROUTINES):
        learnings.add(path, f"Cada mañana dime cómo va la posición {n}")
    fact, _ = learnings.add(path, "Sigo el precio del oro")
    with pytest.raises(learnings.RoutinesFull):
        learnings.edit(path, fact.id, kind="routine")


# ------------------------------------------------------------- the prompt


def test_routines_ride_in_a_section_of_their_own(path):
    learnings.add(path, "Prefiero dividendos crecientes")
    learnings.add(path, "Cada mañana dime cómo voy contra el S&P")
    block = learnings.block(learnings.load(path))
    facts, routines = block.split("Daily routines")
    assert "Prefiero dividendos crecientes" in facts
    assert "contra el S&P" not in facts
    assert "Cada mañana dime cómo voy contra el S&P" in routines
    assert block == learnings.block(learnings.load(path)), "byte-stable"


def test_routines_alone_still_make_a_block(path):
    learnings.add(path, "Cada mañana dime cómo voy contra el S&P")
    block = learnings.block(learnings.load(path))
    assert block.startswith("Daily routines") and "Saved memories" not in block


# ------------------------------------------------------- asked, day after day


@pytest.mark.parametrize("message, asked", [
    ("¿cómo va mi cartera?", True),
    ("como voy contra el S&P 500", True),
    ("what's my best position this week?", True),
    ("hola", False),
    ("recuerda que tengo 40 años", False),
    ("Te cuento: " + "mucho contexto " * 20 + "¿qué hago?", False),
])
def test_only_short_questions_are_logged(message, asked):
    assert learnings.asks(message) is asked


def test_the_same_question_on_three_days_becomes_a_routine(path):
    assert learnings.notice(path, "¿Cómo va mi cartera contra el S&P 500?",
                            day=day(0)) is None
    assert learnings.notice(path, "¿cómo va la cartera contra el S&P 500 hoy?",
                            day=day(2)) is None
    made = learnings.notice(path, "¿Cómo va mi cartera contra el S&P 500?",
                            day=day(5), thread="c_1")

    assert made["op"] == "added" and made["auto"] is True
    assert made["kind"] == "routine" and made["repeated"] == 3
    [item] = learnings.load(path)
    assert item.text == "¿Cómo va mi cartera contra el S&P 500?"
    assert item.kind == "routine" and item.thread == "c_1"
    assert learnings.take_unseen(path) == [made], "said on the next turn"
    assert "asked" not in stored(path), "its log went with it"


def test_asking_twice_on_one_day_counts_once(path):
    for _ in range(3):
        learnings.notice(path, "¿cómo va mi cartera contra el S&P 500?", day=day(0))
    assert learnings.notice(path, "¿cómo va mi cartera contra el S&P 500?",
                            day=day(1)) is None
    assert learnings.load(path) == []
    assert len(stored(path)["asked"]) == 2


def test_days_outside_the_window_do_not_count(path):
    question = "¿cómo va mi cartera contra el S&P 500?"
    learnings.notice(path, question, day=day(0))
    learnings.notice(path, question, day=day(1))
    late = day(learnings.ROUTINE_WINDOW + 1)
    assert learnings.notice(path, question, day=late) is None
    assert [e["day"] for e in stored(path)["asked"]] == [late], "old days pruned"


def test_different_questions_do_not_add_up(path):
    learnings.notice(path, "¿cómo va mi cartera contra el S&P 500?", day=day(0))
    learnings.notice(path, "¿cuánto he cobrado en dividendos este año?", day=day(1))
    assert learnings.notice(path, "¿qué resultados publican esta semana?",
                            day=day(2)) is None
    assert learnings.load(path) == []


def test_a_follow_up_is_not_a_daily_question_but_an_opener_is(path):
    for n in range(3):
        assert learnings.notice(path, "¿seguro?", day=day(n)) is None
    assert not path.exists(), "not even logged"
    for n in range(2):
        learnings.notice(path, "¿cómo va mi cartera?", day=day(n), opener=True)
    made = learnings.notice(path, "¿cómo va mi cartera?", day=day(2), opener=True)
    assert made is not None


def test_one_word_and_a_ticker_is_a_question(path):
    for n in range(2):
        learnings.notice(path, "¿y NVDA?", day=day(n), tickers=["NVDA"])
    made = learnings.notice(path, "¿y NVDA?", day=day(2), tickers=["NVDA"])
    assert made["text"] == "¿y NVDA?"
    assert learnings.load(path)[0].tickers == ("NVDA",)


def test_a_question_the_card_already_answers_is_not_logged(path):
    learnings.add(path, "Cada mañana dime cómo va mi cartera contra el S&P 500")
    for n in range(4):
        assert learnings.notice(path, "¿cómo va mi cartera contra el S&P 500?",
                                day=day(n)) is None
    assert len(learnings.load(path)) == 1


def test_a_routine_the_user_deleted_does_not_come_back(path):
    question = "¿cómo va mi cartera contra el S&P 500?"
    for n in range(3):
        made = learnings.notice(path, question, day=day(n))
    learnings.drop(path, made["id"])
    for n in range(3, 10):
        assert learnings.notice(path, question, day=day(n)) is None
    assert learnings.load(path) == []
    assert stored(path)["declined"]


def test_no_room_adds_nothing_and_starts_the_count_over(path):
    for n in range(learnings.MAX_ROUTINES):
        learnings.add(path, f"Cada mañana dime cómo va la posición {n}")
    question = "¿cuánto he cobrado en dividendos este año?"
    for n in range(3):
        assert learnings.notice(path, question, day=day(n)) is None
    assert len(learnings.load(path)) == learnings.MAX_ROUTINES
    assert "asked" not in stored(path)


def test_the_log_survives_every_other_write(path):
    learnings.notice(path, "¿cómo va mi cartera contra el S&P 500?", day=day(0))
    item, _ = learnings.add(path, "Prefiero dividendos crecientes")
    learnings.edit(path, item.id, text="Prefiero dividendos que crecen")
    learnings.take_unseen(path)
    learnings.drop(path, item.id)
    assert len(stored(path)["asked"]) == 1
    learnings.clear(path)
    assert not path.exists(), "forget everything forgets the log too"


# ------------------------------------------------------------- the chat


def test_the_chat_says_it_went_on_the_daily_card(tmp_path, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda p: None)
    chat = tmp_path / "chat.json"
    order = learnings.command("cada mañana enséñame cómo voy contra el S&P")
    note, [change] = engine.remember(order, prefs={}, chat_path=chat,
                                     watchlist=tmp_path / "watchlist.yaml",
                                     lang="es")
    assert "acción diaria" in note and "contra el S&P" in note
    assert change["kind"] == "routine" and change["op"] == "added"


def test_a_routine_past_the_cap_is_refused_in_words(tmp_path, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda p: None)
    chat = tmp_path / "chat.json"
    path = learnings.path_for(chat)
    for n in range(learnings.MAX_ROUTINES):
        learnings.add(path, f"Cada mañana dime cómo va la posición {n}")
    order = learnings.command("cada mañana enséñame cómo va el oro")
    note, changes = engine.remember(order, prefs={}, chat_path=chat,
                                    watchlist=tmp_path / "watchlist.yaml",
                                    lang="en")
    assert changes == []
    assert str(learnings.MAX_ROUTINES) in note and "pencil" in note


def test_a_plain_question_is_logged_without_a_model(tmp_path, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda p: None)
    handed = []
    monkeypatch.setattr(engine, "complete_attempts",
                        lambda *a, **k: handed.append(a))
    chat = tmp_path / "chat.json"
    done = engine.learn({}, chat, [{"role": "user", "content": "¿cómo va mi cartera?"}],
                        tmp_path / "watchlist.yaml")
    assert done is not None and done.wait(5)
    assert handed == []
    [entry] = stored(learnings.path_for(chat))["asked"]
    assert entry["day"] == datetime.now(UTC).date().isoformat()


def test_telegram_tells_a_routine_as_the_daily_card(monkeypatch):
    from stocks.chat import bot

    reply = engine.Reply(text="ok", provider_id="groq", learned=(
        {"op": "added", "id": "m_1", "text": "Cada mañana dime cómo voy",
         "kind": "routine", "auto": True, "repeated": 3},))
    note = bot._memory_note(reply, "es")
    assert "Añadido a tu acción diaria: «Cada mañana dime cómo voy»" in note
