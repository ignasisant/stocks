"""The saved memories' life after they are saved: when they stop holding
(`until`), the words they replaced, how often the user's questions touch them,
which one a full list offers to let go, what a new one may clash with, and the
weekly tidy-up that proposes — never makes — changes (`chat/memory_review.py`).

Also the two retrieval helpers memory leans on: a holding found under every
name it goes by (`market.aliases`), and the deep-gather loop clearing tool
results it has already read (`llm._clear_old_results`).
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from stocks.chat import learnings, market, memory_review
from stocks.web import llm


@pytest.fixture
def path(tmp_path, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda p: None)
    return tmp_path / learnings.FILE


def _backdate(path, lid, day):
    """Make `lid` look saved on `day`."""
    items = [replace(i, created=f"{day}T09:00:00+00:00",
                     updated=f"{day}T09:00:00+00:00") if i.id == lid else i
             for i in learnings.load(path)]
    learnings._save(path, items)


# --------------------------------------------------------------------- until


@pytest.mark.parametrize(("text", "until"), [
    ("Hasta fin de año no vendo nada", "2026-12-31"),
    ("No compro más bancos hasta final de mes", "2026-10-31"),
    ("Hasta mayo no toco la cartera", "2027-05-31"),
    ("Until December I'm not adding to tech", "2026-12-31"),
    ("Esta semana no opero", "2026-10-25"),
    ("Hasta el 15/11/2026 solo ETFs", "2026-11-15"),
    ("Hasta el 2/3 no vendo", "2027-03-02"),
    ("Until 2027-03-15 no options", "2027-03-15"),
    ("Hasta el 40/13 nada", ""),
    ("Tengo 40 años y vivo en Girona", ""),
    ("Prefiero dividendos crecientes", ""),
])
def test_until_reads_the_end_a_statement_names(text, until):
    assert learnings.until_in(text, "2026-10-23") == until


def test_a_span_counts_from_today():
    assert learnings.until_in("durante los próximos 3 meses no vendo",
                              "2026-10-23") == "2027-01-21"


def test_an_expired_memory_stays_listed_and_leaves_the_prompt(path):
    item, _ = learnings.add(path, "Hasta fin de mes no compro bancos")
    assert item.until
    later = "9999-01-01"
    assert item.expired(later) and not item.expired(item.until)
    assert "bancos" in learnings.block(learnings.load(path), day=item.until)
    assert "bancos" not in learnings.block(learnings.load(path), day=later)
    assert learnings.load(path) == [item]


def test_until_is_set_cleared_and_checked_by_hand(path):
    item, _ = learnings.add(path, "Prefiero ETFs de acumulación")
    assert item.until == ""
    dated = learnings.edit(path, item.id, until="2027-03-31")
    assert dated is not None and dated.until == "2027-03-31"
    cleared = learnings.edit(path, item.id, until="")
    assert cleared is not None and cleared.until == ""
    with pytest.raises(ValueError):
        learnings.edit(path, item.id, until="next tuesday")


def test_a_routine_never_expires(path):
    item, _ = learnings.add(path, "Cada mañana dime cómo va ASML hasta fin de año",
                            kind="routine")
    assert item.until == ""


# ------------------------------------------------------- correct and clash


def test_other_figures_correct_the_memory_instead_of_adding_one(path):
    first = learnings.save(path, "Nunca más de un 10% en una sola posición")
    again = learnings.save(path, "Nunca más de un 5% en una sola posición")
    assert again.op == "updated" and again.item.id == first.item.id
    assert again.before == "Nunca más de un 10% en una sola posición"
    [kept] = learnings.load(path)
    assert kept.text == "Nunca más de un 5% en una sola posición"
    assert kept.replaced == ("Nunca más de un 10% en una sola posición",)


def test_the_same_words_are_known_not_added(path):
    learnings.save(path, "Vivo en Girona")
    assert learnings.save(path, "vivo en girona.").op == "known"
    assert len(learnings.load(path)) == 1


def test_a_new_memory_names_the_one_it_may_clash_with(path):
    old = learnings.save(path, "Quiero reducir mi exposición a ASML",
                         tickers=["ASML"]).item
    new = learnings.save(path, "Quiero aumentar mi posición en ASML este año",
                         tickers=["ASML"])
    assert new.op == "added" and new.related == old


def test_unrelated_memories_name_nothing(path):
    learnings.save(path, "Vivo en Girona")
    assert learnings.save(path, "Prefiero dividendos crecientes").related is None


def test_supersede_keeps_the_old_words_and_drops_the_old_memory(path):
    old = learnings.save(path, "Mi horizonte es de 10 años").item
    new = learnings.save(path, "Me jubilo en 2040, ese es mi horizonte").item
    kept, gone = learnings.supersede(path, new.id, old.id)
    assert gone == old and kept.replaced == (old.text,)
    assert [i.id for i in learnings.load(path)] == [new.id]
    assert learnings.supersede(path, new.id, old.id) is None
    assert learnings.supersede(path, new.id, new.id) is None


def test_rewording_keeps_at_most_a_few_old_wordings(path):
    item = learnings.save(path, "Prefiero ETFs baratos").item
    for n in range(learnings.MAX_REPLACED + 2):
        learnings.edit(path, item.id, text=f"Prefiero ETFs baratos, versión {n}")
    [kept] = learnings.load(path)
    assert len(kept.replaced) == learnings.MAX_REPLACED
    assert kept.replaced[-1] == f"Prefiero ETFs baratos, versión {learnings.MAX_REPLACED}"


def test_the_prompt_block_ignores_usage_and_old_wordings(path):
    """The block rides every prompt, cached: counting uses must not change it."""
    item = learnings.save(path, "Nunca más de un 10% en ASML", tickers=["ASML"]).item
    before = learnings.block(learnings.load(path), day="2026-10-23")
    learnings.note_used(path, [item.id], day="2026-10-23")
    assert learnings.block(learnings.load(path), day="2026-10-23") == before


# --------------------------------------------------------------------- usage


def test_a_question_uses_the_memories_it_is_about(path):
    asml = learnings.save(path, "Nunca más de un 10% en ASML", tickers=["ASML"]).item
    girona = learnings.save(path, "Vivo en Girona y pago IRPF catalán").item
    items = learnings.load(path)
    assert learnings.relevant(items, "¿Compro más?", ["ASML"]) == [asml.id]
    assert learnings.relevant(items, "¿cómo tributa el IRPF catalán?") == [girona.id]
    assert learnings.relevant(items, "¿qué tal el mercado hoy?") == []


def test_uses_are_counted_beside_the_list(path):
    item = learnings.save(path, "Vivo en Girona").item
    learnings.note_used(path, [item.id, "m_gone"], day="2026-10-01")
    learnings.note_used(path, [item.id], day="2026-10-20")
    assert learnings.usage(path) == {item.id: {"n": 2, "last": "2026-10-20"}}
    raw = json.loads(path.read_text())
    assert "used" in raw and all(set(i).isdisjoint({"n", "used", "last"})
                                 for i in raw["items"])
    learnings.drop(path, item.id)
    learnings.save(path, "Prefiero dividendos crecientes")
    assert learnings.usage(path) == {}


def test_a_full_list_offers_the_expired_one_first(path):
    used = learnings.save(path, "Vivo en Girona").item
    done = learnings.save(path, "Hasta fin de mes no compro bancos").item
    learnings.note_used(path, [used.id])
    items = learnings.load(path)
    assert learnings.suggest_drop(items, learnings.usage(path),
                                  day="9999-01-01") == done


def test_otherwise_the_least_used_one(path):
    a = learnings.save(path, "Vivo en Girona").item
    b = learnings.save(path, "Prefiero dividendos crecientes").item
    learnings.save(path, "Cada mañana dime cómo va ASML", kind="routine")
    learnings.note_used(path, [a.id])
    least = learnings.suggest_drop(learnings.load(path), learnings.usage(path))
    assert least == b


def test_idle_needs_age_as_well_as_silence(path):
    item = learnings.save(path, "Vivo en Girona").item
    assert not learnings.idle(item, {}, "2026-10-23")
    _backdate(path, item.id, "2026-01-01")
    [old] = learnings.load(path)
    assert learnings.idle(old, {}, "2026-10-23")
    assert not learnings.idle(old, {old.id: {"n": 1, "last": "2026-10-01"}},
                              "2026-10-23")


# ------------------------------------------------------------ weekly review


def _three(path):
    a = learnings.save(path, "Vivo en Girona").item
    b = learnings.save(path, "Prefiero dividendos crecientes").item
    c = learnings.save(path, "Hasta fin de mes no compro bancos").item
    return a, b, c


def test_plain_proposals_need_no_model(path):
    a, b, c = _three(path)
    _backdate(path, a.id, "2026-01-01")
    items = learnings.load(path)
    found = memory_review.plain(items, {b.id: {"n": 1, "last": "9998-12-31"}},
                                "9999-01-01")
    by_id = {p.ids[0]: p for p in found}
    assert by_id[c.id].reason == "expired"
    assert by_id[a.id].reason == "idle"
    assert b.id not in by_id


def test_two_memories_that_say_the_same_are_offered_as_one(path):
    a = learnings.save(path, "Prefiero ETFs de acumulación baratos").item
    b = learnings.save(path, "Prefiero ETFs de acumulación baratos siempre").item
    found = memory_review.plain(learnings.load(path), {}, "2026-10-23")
    [merge] = [p for p in found if p.action == "merge"]
    assert set(merge.ids) == {a.id, b.id} and merge.reason == "same"


def _reply(*ops):
    return json.dumps({"ops": list(ops)})


def test_model_proposals_are_held_to_the_users_words(path):
    a, b, c = _three(path)
    items = learnings.load(path)
    said = "Ya no vivo en Girona, me he mudado a Valencia\n" + "\n".join(
        i.text for i in items)
    got = memory_review.proposals(_reply(
        {"action": "reword", "ids": [a.id], "text": "Vivo en Valencia",
         "reason": "Te mudaste."},
        {"action": "reword", "ids": [b.id], "text": "Prefiero cripto apalancada"},
        {"action": "merge", "ids": [a.id], "text": "Vivo en Valencia"},
        {"action": "drop", "ids": ["m_made_up"]},
        {"action": "explode", "ids": [c.id]},
    ), items, said)
    assert got is not None
    [reword] = got
    assert reword.action == "reword" and reword.text == "Vivo en Valencia"
    assert reword.reason == "model" and reword.note == "Te mudaste."


def test_a_reply_off_the_contract_is_none(path):
    _three(path)
    assert memory_review.proposals("lo siento", learnings.load(path), "") is None


def test_due_weekly_and_only_for_a_list_worth_tidying(path):
    learnings.save(path, "Vivo en Girona")
    assert not memory_review.due(path, "2026-10-23")
    learnings.save(path, "Prefiero dividendos crecientes")
    learnings.save(path, "Tengo cuarenta años")
    assert memory_review.due(path, "2026-10-23")
    memory_review.keep(path, [], "2026-10-23")
    assert not memory_review.due(path, "2026-10-29")
    assert memory_review.due(path, "2026-10-30")


def test_keep_dedupes_and_never_proposes_two_changes_to_one_memory(path):
    a, b, c = _three(path)
    one = memory_review.proposal("drop", (a.id,), "idle")
    other = memory_review.proposal("reword", (a.id,), "model", text="Vivo en Valencia")
    third = memory_review.proposal("drop", (c.id,), "expired")
    kept = memory_review.keep(path, [one, one, other, third], "2026-10-23")
    assert kept == [one, third]
    assert memory_review.pending(path, "2026-10-23") == [one, third]


def test_applying_a_reword_changes_the_memory_and_closes_the_proposal(path):
    a, _, _ = _three(path)
    p = memory_review.proposal("reword", (a.id,), "model", text="Vivo en Valencia")
    memory_review.keep(path, [p], "2026-10-23")
    done = memory_review.settle(path, p.sid, "apply", "2026-10-23")
    assert done is not None and done["op"] == "apply"
    [change] = done["changes"]
    assert change["op"] == "updated" and change["before"] == "Vivo en Girona"
    [now] = [i for i in learnings.load(path) if i.id == a.id]
    assert now.text == "Vivo en Valencia" and now.replaced == ("Vivo en Girona",)
    assert memory_review.pending(path, "2026-10-23") == []
    assert memory_review.settle(path, p.sid, "apply", "2026-10-23") is None


def test_applying_a_merge_keeps_one_memory(path):
    a = learnings.save(path, "Prefiero ETFs de acumulación").item
    b = learnings.save(path, "Me gustan los ETFs baratos").item
    learnings.save(path, "Vivo en Girona")
    p = memory_review.proposal("merge", (a.id, b.id), "model",
                               text="Prefiero ETFs de acumulación baratos")
    memory_review.keep(path, [p], "2026-10-23")
    done = memory_review.settle(path, p.sid, "apply", "2026-10-23")
    assert done is not None
    ids = [i.id for i in learnings.load(path)]
    assert a.id in ids and b.id not in ids
    [kept] = [i for i in learnings.load(path) if i.id == a.id]
    assert kept.text == "Prefiero ETFs de acumulación baratos"
    assert "Me gustan los ETFs baratos" in kept.replaced


def test_a_dismissed_proposal_stays_away_for_a_month(path):
    a, _, _ = _three(path)
    p = memory_review.proposal("drop", (a.id,), "idle")
    memory_review.keep(path, [p], "2026-10-01")
    assert memory_review.settle(path, p.sid, "dismiss", "2026-10-01") == {
        "op": "dismiss", "changes": []}
    assert [i.id for i in learnings.load(path)].count(a.id) == 1
    assert memory_review.keep(path, [p], "2026-10-08") == []
    assert memory_review.keep(path, [p], "2026-11-15") == [p]


def test_a_proposal_about_a_deleted_memory_is_not_open(path):
    a, _, _ = _three(path)
    p = memory_review.proposal("drop", (a.id,), "idle")
    memory_review.keep(path, [p], "2026-10-23")
    learnings.drop(path, a.id)
    assert memory_review.pending(path, "2026-10-23") == []
    assert memory_review.settle(path, p.sid, "apply", "2026-10-23") is None


def test_the_review_runs_only_when_memory_is_on_and_due(path, tmp_path):
    chat = tmp_path / "chat.json"
    assert memory_review.start({"chat_memory": False}, chat, day="2026-10-23") is None
    assert memory_review.start({}, chat, day="2026-10-23") is None  # nothing saved


# ------------------------------------------------------------------- aliases


_KNOWN = {"NVDA": "NVDA", "NVIDIA CORPORATION": "NVDA",
          "ASML": "ASML", "ASML HOLDING N.V.": "ASML",
          "BANCO SANTANDER, S.A.": "SAN.MC", "SAN.MC": "SAN.MC",
          "BANCO BILBAO VIZCAYA ARGENTARIA, S.A.": "BBVA.MC"}


def test_a_ticker_brings_its_company_name():
    out = market.aliases(["NVDA"], "¿qué tal NVDA?", _KNOWN)
    assert "NVIDIA CORPORATION" in out
    assert "nvidia" in [o.casefold() for o in out if o != "NVIDIA CORPORATION"]


def test_a_lowercase_company_name_counts_as_named():
    out = market.aliases([], "¿y nvidia, sigue cara?", _KNOWN)
    assert "NVDA" in out


def test_a_name_that_fits_two_holdings_is_not_widened():
    out = market.aliases(["Banco"], "¿qué banco compro?", _KNOWN)
    assert out == ["Banco"]


def test_aliases_without_a_watchlist_change_nothing():
    assert market.aliases(["Tesla"], "¿y Tesla?", {}) == ["Tesla"]


# ---------------------------------------------------------- context editing


def _round(n, size):
    return [{"content": f"r{n} " + "x" * size}]


def test_old_tool_results_are_cleared_once_the_loop_grows_long():
    rounds = [_round(n, 30_000) for n in range(4)]
    assert llm._clear_old_results(rounds) == 2
    for batch in rounds[:2]:
        assert batch[0]["content"].endswith(llm.CLEARED)
        assert len(batch[0]["content"]) <= llm.CLEARED_CHARS + len(llm.CLEARED)
    for batch in rounds[2:]:
        assert not batch[0]["content"].endswith(llm.CLEARED)
    # Cleared once: a second pass over the same rounds finds nothing to do.
    assert llm._clear_old_results(rounds) == 0


def test_a_short_loop_is_left_whole():
    rounds = [_round(n, 10_000) for n in range(4)]
    assert llm._clear_old_results(rounds) == 0
    assert not any(b[0]["content"].endswith(llm.CLEARED) for b in rounds)
