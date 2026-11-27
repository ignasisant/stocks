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

from stocks import llm
from stocks.chat import learnings, market, memory_review


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


# ----------------------------------------------------------------- history


def _whys(path, lid):
    [item] = [i for i in learnings.load(path) if i.id == lid]
    return [h["why"] for h in item.history]


def test_a_correction_keeps_what_it_said_and_why(path):
    first = learnings.save(path, "Nunca más de un 10% en una sola posición").item
    learnings.save(path, "Nunca más de un 5% en una sola posición")
    [kept] = learnings.load(path)
    [entry] = kept.history
    assert entry["why"] == "said"
    assert entry["was"] == first.text and entry["day"] == kept.updated[:10]


def test_an_edit_by_hand_is_noted_and_undoing_it_takes_the_note_back(path):
    item = learnings.save(path, "Prefiero ETFs baratos").item
    learnings.edit(path, item.id, text="Prefiero ETFs de acumulación")
    assert _whys(path, item.id) == ["edited"]
    learnings.edit(path, item.id, text="Prefiero ETFs baratos")
    assert _whys(path, item.id) == []


def test_an_unasked_update_quotes_the_message_it_came_from(path):
    item = learnings.save(path, "Mi horizonte es de 10 años").item
    said = "Al final me jubilo antes, mi horizonte es de 5 años"
    learnings.apply(path, [learnings.Lesson("update", item.id,
                                            "Mi horizonte es de 5 años")],
                    said=said)
    [kept] = learnings.load(path)
    [entry] = kept.history
    assert entry["why"] == "learned" and entry["said"] == said
    assert entry["was"] == "Mi horizonte es de 10 años"


def test_an_unasked_update_from_earlier_words_quotes_nothing(path):
    item = learnings.save(path, "Mi horizonte es de 10 años").item
    learnings.apply(path, [learnings.Lesson("update", item.id,
                                            "Mi horizonte es de 5 años")],
                    said="Vale, cámbialo entonces")
    [kept] = learnings.load(path)
    assert kept.history[-1]["why"] == "learned"
    assert "said" not in kept.history[-1]


def test_a_superseded_memory_is_named_in_the_one_that_replaced_it(path):
    old = learnings.save(path, "Mi horizonte es de 10 años").item
    new = learnings.save(path, "Me jubilo en 2040, ese es mi horizonte").item
    learnings.supersede(path, new.id, old.id)
    [kept] = learnings.load(path)
    assert kept.history[-1]["why"] == "replaced"
    assert kept.history[-1]["was"] == old.text


def test_history_is_capped_and_survives_a_reload(path):
    item = learnings.save(path, "Prefiero ETFs baratos").item
    for n in range(learnings.MAX_HISTORY + 3):
        learnings.edit(path, item.id, text=f"Prefiero ETFs baratos, versión {n}")
    [kept] = learnings.load(path)
    assert len(kept.history) == learnings.MAX_HISTORY
    assert kept.history[-1]["was"].endswith(f"{learnings.MAX_HISTORY + 1}")


def test_a_history_entry_off_the_contract_is_dropped_on_load(path):
    item = learnings.save(path, "Vivo en Girona").item
    raw = json.loads(path.read_text())
    raw["items"][0]["history"] = [
        {"day": "2026-10-01", "why": "edited", "was": "Vivo en Lleida"},
        {"day": "ayer", "why": "edited", "was": "x"},
        {"day": "2026-10-02", "why": "hunch", "was": "x"},
        {"day": "2026-10-03", "why": "edited", "was": 3, "secret": "y"},
    ]
    path.write_text(json.dumps(raw))
    [kept] = learnings.load(path)
    assert kept.id == item.id
    assert kept.history == ({"day": "2026-10-01", "why": "edited",
                             "was": "Vivo en Lleida"},
                            {"day": "2026-10-03", "why": "edited"})


def test_retire_ends_a_memory_and_says_why(path):
    item = learnings.save(path, "Tengo 50 NVDA", tickers=["NVDA"]).item
    note = {"ticker": "NVDA", "event": "closed", "on": "2026-10-03"}
    done = learnings.retire(path, item.id, day="2026-10-03", why="book",
                            note=note)
    assert done is not None and done.until == "2026-10-03"
    assert done.history[-1] == {"day": done.updated[:10], "why": "book", **note}
    assert done.text not in learnings.block(learnings.load(path), day="2026-11-26")
    with pytest.raises(ValueError):
        learnings.retire(path, item.id, day="ayer", why="book")
    with pytest.raises(ValueError):
        learnings.retire(path, item.id, day="2026-10-03", why="hunch")


def test_retire_keeps_an_earlier_end_and_leaves_routines_alone(path):
    item = learnings.save(path, "Solo ETFs", tickers=["VWCE"]).item
    learnings.edit(path, item.id, until="2026-11-15")
    done = learnings.retire(path, item.id, day="2026-12-20", why="book")
    assert done is not None and done.until == "2026-11-15"
    routine = learnings.save(path, "Cada mañana dime cómo va NVDA",
                             tickers=["NVDA"]).item
    assert learnings.retire(path, routine.id, day="2026-10-03",
                            why="book") is None


# -------------------------------------------------------------------- book


def _tx(day, ticker, action, qty):
    from stocks.portfolio.ledger import Transaction
    return Transaction(date=day, ticker=ticker, action=action, quantity=qty,
                       price=10.0, currency="USD", fee=0.0, note="")


def test_book_events_are_positions_opened_and_closed():
    events = memory_review.book_events([
        _tx("2026-01-02", "NVDA", "buy", 10),
        _tx("2026-06-01", "NVDA", "sell", 4),       # trimmed: no event
        _tx("2026-10-03", "NVDA", "sell", 6),
        _tx("2026-05-01", "SAN.MC", "buy", 5),
        _tx("2026-07-01", "SAN.MC", "sell", 5),
        _tx("2026-07-01", "SAN.MC", "buy", 5),      # bought back that day
        _tx("2026-03-01", "AAPL", "buy", 1),
        _tx("2026-04-01", "AAPL", "split", 4),
        _tx("2026-09-01", "AAPL", "sell", 4),       # all of the split shares
    ])
    assert events == {
        "NVDA": [("2026-01-02", "opened"), ("2026-10-03", "closed")],
        "SAN.MC": [("2026-05-01", "opened")],
        "AAPL": [("2026-03-01", "opened"), ("2026-09-01", "closed")],
    }


_SOLD = {"NVDA": [("2026-01-02", "opened"), ("2026-10-03", "closed")]}


def test_a_memory_said_before_the_sale_is_offered_to_retire(path):
    item = learnings.save(path, "Tengo 50 NVDA a 120", tickers=["NVDA"]).item
    _backdate(path, item.id, "2026-03-01")
    [p] = memory_review.from_book(learnings.load(path), _SOLD, "2026-11-26")
    assert (p.action, p.reason, p.ids) == ("retire", "book", (item.id,))
    assert (p.ticker, p.event, p.on) == ("NVDA", "closed", "2026-10-03")


@pytest.mark.parametrize(("text", "said"), [
    # Said after the sale: it already knows.
    ("No compro más NVDA hasta fin de año", "2026-10-20"),
    # Said on the day of the sale: it may be about that sale.
    ("Vendo todas mis NVDA hoy", "2026-10-03"),
])
def test_a_memory_said_after_the_trade_is_left_alone(path, text, said):
    item = learnings.save(path, text, tickers=["NVDA"]).item
    _backdate(path, item.id, said)
    assert memory_review.from_book(learnings.load(path), _SOLD,
                                   "2026-11-26") == []


@pytest.mark.parametrize(("kind", "text"), [
    ("constraint", "Nunca más de un 10 % en NVDA"),
    ("preference", "Prefiero no promediar a la baja en NVDA"),
])
def test_a_rule_or_a_taste_outlives_the_sale(path, kind, text):
    item = learnings.save(path, text, kind=kind, tickers=["NVDA"]).item
    _backdate(path, item.id, "2026-03-01")
    assert memory_review.from_book(learnings.load(path), _SOLD,
                                   "2026-11-26") == []


def test_a_name_never_traded_is_left_alone(path):
    item = learnings.save(path, "Quiero comprar ASML si baja de 600",
                          tickers=["ASML"]).item
    _backdate(path, item.id, "2026-03-01")
    assert memory_review.from_book(learnings.load(path), _SOLD,
                                   "2026-11-26") == []


def test_a_trade_after_today_or_an_expired_memory_is_left_alone(path):
    item = learnings.save(path, "Tengo 50 NVDA", tickers=["NVDA"]).item
    _backdate(path, item.id, "2026-03-01")
    assert memory_review.from_book(learnings.load(path), _SOLD,
                                   "2026-10-02") == []
    learnings.edit(path, item.id, until="2026-04-01")
    assert memory_review.from_book(learnings.load(path), _SOLD,
                                   "2026-11-26") == []


def test_a_memory_naming_the_bare_symbol_finds_its_listing(path):
    item = learnings.save(path, "Tengo 100 SAN", tickers=["SAN"]).item
    _backdate(path, item.id, "2026-03-01")
    events = {"SAN.MC": [("2026-01-02", "opened"), ("2026-10-03", "closed")]}
    [p] = memory_review.from_book(learnings.load(path), events, "2026-11-26")
    assert p.ticker == "SAN"
    two = {**events, "SAN.L": [("2026-05-01", "opened")]}
    assert memory_review.from_book(learnings.load(path), two,
                                   "2026-11-26") == []


@pytest.mark.parametrize(("said", "book", "found"), [
    ("SAN.MC", "SAN.PA", False),    # another venue is another company
    ("BTC-USD", "BTC-EUR", True),   # one coin against another currency
    ("BTC-USD", "BTCS", False),
    ("SAN", "SANM", False),
])
def test_only_a_bare_symbol_or_a_coin_reaches_another_label(path, said, book,
                                                            found):
    item = learnings.save(path, f"Tengo {said}", tickers=[said]).item
    _backdate(path, item.id, "2026-03-01")
    events = {book: [("2026-01-02", "opened"), ("2026-10-03", "closed")]}
    got = memory_review.from_book(learnings.load(path), events, "2026-11-26")
    assert bool(got) is found


def test_applying_a_book_proposal_retires_the_memory(path):
    item = learnings.save(path, "Tengo 50 NVDA", tickers=["NVDA"]).item
    _backdate(path, item.id, "2026-03-01")
    [p] = memory_review.from_book(learnings.load(path), _SOLD, "2026-11-26")
    memory_review.add_book(path, [p], "2026-11-26")
    assert memory_review.pending(path, "2026-11-26") == [p]
    done = memory_review.settle(path, p.sid, "apply", "2026-11-26")
    assert done is not None and done["changes"][0]["op"] == "updated"
    [kept] = learnings.load(path)
    assert kept.until == "2026-10-03" and kept.history[-1]["why"] == "book"
    # Retired, it is out of the book's reach for good.
    assert memory_review.from_book(learnings.load(path), _SOLD,
                                   "2026-11-27") == []


def test_a_dismissed_book_proposal_stays_away_for_good(path):
    item = learnings.save(path, "Tengo 50 NVDA", tickers=["NVDA"]).item
    _backdate(path, item.id, "2026-03-01")
    [p] = memory_review.from_book(learnings.load(path), _SOLD, "2026-11-26")
    memory_review.add_book(path, [p], "2026-11-26")
    memory_review.settle(path, p.sid, "dismiss", "2026-11-26")
    assert memory_review.add_book(path, [p], "2027-06-01") == []


def test_the_book_is_read_daily_without_making_it_a_new_week(path):
    a, b, c = _three(path)
    memory_review.keep(path, [], "2026-10-23")
    item = learnings.save(path, "Tengo 50 NVDA", tickers=["NVDA"]).item
    assert memory_review.book_due(path, "2026-10-24")
    _backdate(path, item.id, "2026-03-01")
    [p] = memory_review.from_book(learnings.load(path), _SOLD, "2026-10-24")
    memory_review.add_book(path, [p], "2026-10-24")
    assert not memory_review.book_due(path, "2026-10-24")
    assert memory_review.book_due(path, "2026-10-25")
    assert memory_review.due(path, "2026-10-30")  # the week still counts
    assert memory_review.pending(path, "2026-10-24") == [p]


def test_book_proposals_go_before_the_weeks(path):
    a, _, _ = _three(path)
    week = memory_review.proposal("drop", (a.id,), "idle")
    memory_review.keep(path, [week], "2026-10-23")
    item = learnings.save(path, "Tengo 50 NVDA", tickers=["NVDA"]).item
    _backdate(path, item.id, "2026-03-01")
    [p] = memory_review.from_book(learnings.load(path), _SOLD, "2026-10-24")
    assert memory_review.add_book(path, [p], "2026-10-24") == [p, week]


def test_a_list_with_no_holding_named_has_no_book_to_read(path):
    _three(path)
    assert not memory_review.book_due(path, "2026-10-24")


def test_the_daily_run_reads_the_book_beside_the_chat(path, tmp_path):
    from stocks.portfolio import ledger

    chat = tmp_path / "chat.json"
    item = learnings.save(path, "Tengo 50 NVDA", tickers=["NVDA"]).item
    _backdate(path, item.id, "2026-03-01")
    # A list of one: too short for the week's review, not for the book.
    assert not memory_review.due(path, "2026-11-26")
    assert memory_review.start({}, chat, day="2026-11-26") is None  # no book
    ledger.add_many([_tx("2026-01-02", "NVDA", "buy", 50),
                     _tx("2026-10-03", "NVDA", "sell", 50)],
                    tmp_path / "portfolio.db")
    done = memory_review.start({}, chat, day="2026-11-26")
    assert done is not None and done.wait(10)
    [p] = memory_review.pending(path, "2026-11-26")
    assert (p.action, p.on) == ("retire", "2026-10-03")
    assert memory_review.start({}, chat, day="2026-11-26") is None  # read today


def test_the_book_sid_differs_by_trade():
    one = memory_review.proposal("retire", ("m_1",), "book", ticker="NVDA",
                                 event="closed", on="2026-10-03")
    two = memory_review.proposal("retire", ("m_1",), "book", ticker="NVDA",
                                 event="opened", on="2026-11-03")
    assert one.sid != two.sid
    # The other reasons' sids are what they were before the book.
    assert memory_review.proposal("drop", ("m_1",), "idle").sid == \
        memory_review._sid("drop", ("m_1",), "")


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
