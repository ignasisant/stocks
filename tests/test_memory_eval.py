"""Golden memory eval: what the assistant believes about its user after a few
sessions of them talking to it.

Each case is a short life — things said in words, days passing, questions
asked — and ends on what the next prompt's memory block says (or does not)
and what the user was told on the way. No model is called: every step here
is the deterministic half of memory (`engine.remember`, `learnings`,
`memory_review.plain`, `market.aliases` + `memory.about`). A regression in
any of them shows up as an assistant that believes the wrong thing — which is
what these cases name.
"""

from __future__ import annotations

import pytest

from stocks.chat import engine, learnings, market, memory, memory_review


@pytest.fixture
def life(tmp_path, monkeypatch):
    """One account: say things, ask things, read what the next prompt holds."""
    monkeypatch.setattr("stocks.storage.persist", lambda p: None)
    chat = tmp_path / "chat.json"
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        "watchlist:\n"
        "  - ticker: NVDA\n    name: NVIDIA Corporation\n"
        "  - ticker: ASML\n    name: ASML Holding N.V.\n")

    class Life:
        path = learnings.path_for(chat)
        told: list[str] = []
        changes: list[dict] = []

        def say(self, message: str) -> str:
            order = learnings.command(message)
            assert order is not None, f"not a memory command: {message}"
            note, changes = engine.remember(order, prefs={}, chat_path=chat,
                                            watchlist=watchlist, lang="es")
            self.told.append(note)
            self.changes.extend(changes)
            return note

        def ask(self, message: str, day: str) -> None:
            known = market.watchlist_names(watchlist)
            ids = engine.used_by(learnings.load(self.path), message, known)
            learnings.note_used(self.path, ids, day=day)

        def prompt(self, day: str = "2026-10-23") -> str:
            return learnings.block(learnings.load(self.path), day=day)

    return Life()


def test_a_corrected_limit_replaces_the_old_one(life):
    life.say("recuerda que nunca pongo más de un 10% en una sola posición")
    note = life.say("recuerda que nunca pongo más de un 5% en una sola posición")
    assert "Corregido" in note and "10%" in note
    assert "5%" in life.prompt() and "10%" not in life.prompt()
    [kept] = learnings.load(life.path)
    assert kept.replaced == ("Nunca pongo más de un 10% en una sola posición",)


def test_said_twice_is_kept_once(life):
    life.say("recuerda que vivo en Girona")
    assert "ya lo tenía" in life.say("recuerda que vivo en Girona").casefold()
    assert life.prompt().count("Girona") == 1


def test_forgotten_is_gone_from_the_next_prompt(life):
    life.say("recuerda que vivo en Girona")
    life.say("recuerda que prefiero dividendos crecientes")
    life.say("olvida lo de Girona")
    assert "Girona" not in life.prompt() and "dividendos" in life.prompt()


def test_a_dated_rule_stops_at_its_date(life):
    life.say("recuerda que hasta fin de mes no compro bancos")
    assert "bancos" in life.prompt("2026-10-31")
    assert "bancos" not in life.prompt("2026-11-01")
    # Still listed, so the reader sees it ran out rather than vanished.
    assert len(learnings.load(life.path)) == 1


def test_a_clashing_plan_is_flagged_not_merged(life):
    life.say("recuerda que quiero reducir mi posición en ASML")
    note = life.say("recuerda que quiero aumentar mi posición en ASML")
    assert "Puede chocar" in note
    added = life.changes[-1]
    assert added["op"] == "added" and added["related_id"]
    assert len(learnings.load(life.path)) == 2


def test_a_full_memory_names_the_one_used_least(life, monkeypatch):
    monkeypatch.setattr(learnings, "MAX_ITEMS", 2)
    life.say("recuerda que vivo en Girona y tributo en Cataluña")
    life.say("recuerda que nunca pongo más de un 10% en NVDA")
    life.ask("¿subo NVDA?", "2026-10-20")
    note = life.say("recuerda que prefiero dividendos crecientes")
    assert "Girona" in note and "NVDA" not in note
    assert len(learnings.load(life.path)) == 2


def test_questions_count_toward_the_memories_they_touch(life):
    life.say("recuerda que nunca pongo más de un 10% en NVDA")
    life.say("recuerda que vivo en Girona")
    life.ask("¿cómo va Nvidia?", "2026-10-21")
    life.ask("¿vendo NVDA?", "2026-10-22")
    used = learnings.usage(life.path)
    [nvda] = [i for i in learnings.load(life.path) if "NVDA" in i.text]
    assert used == {nvda.id: {"n": 2, "last": "2026-10-22"}}


def test_the_weekly_review_offers_to_drop_what_ran_out(life):
    life.say("recuerda que hasta fin de mes no compro bancos")
    life.say("recuerda que vivo en Girona")
    life.say("recuerda que prefiero dividendos crecientes")
    found = memory_review.plain(learnings.load(life.path),
                                learnings.usage(life.path), "2026-11-02")
    assert [(p.action, p.reason) for p in found] == [("drop", "expired")]
    memory_review.keep(life.path, found, "2026-11-02")
    memory_review.settle(life.path, found[0].sid, "apply", "2026-11-02")
    assert "bancos" not in learnings.block(learnings.load(life.path))
    assert len(learnings.load(life.path)) == 2


@pytest.mark.skipif(not memory.available(),
                    reason="the index needs model2vec + sqlite-vec")
def test_a_holding_is_recalled_under_its_other_name(tmp_path):
    index = tmp_path / memory.FILE
    memory.remember(index, [
        {"role": "user",
         "content": "NVDA ya pesa el 25% de mi cartera y no quiero que pase "
                    "del 30%, ¿recorto o espero a resultados?"},
        {"role": "assistant", "content": "Con un 25% en una sola acción, un "
                                         "mal trimestre mueve toda la cartera."},
    ], "t1")
    known = {"NVDA": "NVDA", "NVIDIA CORPORATION": "NVDA"}
    question = "¿y nvidia, la vendo?"
    assert memory.about(index, market.named(question)) == []
    widened = market.aliases(market.named(question), question, known)
    [hit] = memory.about(index, widened)
    assert hit.thread == "t1"
