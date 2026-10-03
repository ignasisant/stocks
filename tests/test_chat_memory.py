"""memory: the long-term chat index — what gets stored, found and forgotten."""

import pytest

from stocks.chat import memory

pytestmark = pytest.mark.skipif(
    not memory.available(),
    reason="memory needs model2vec + sqlite-vec; the chat degrades without them",
)

_T1 = [
    {"role": "user",
     "content": "Estoy pensando en recortar mi posición en ASML, las reservas "
                "salieron flojas y ya pesa el 30% de mi cartera"},
    {"role": "assistant",
     "content": "El riesgo real es la concentración: con el 30% de la cartera "
                "un solo aviso de resultados mueve todo tu patrimonio"},
]
_T2 = [
    {"role": "user",
     "content": "what do you think about buying more Nvidia here, it has run a "
                "lot this year and I only hold a small position"},
    {"role": "assistant",
     "content": "Adding after a 200% run means paying for certainty you did "
                "not have before; size it so a 40% drawdown changes nothing"},
]


@pytest.fixture
def index(tmp_path):
    path = tmp_path / memory.FILE
    memory.remember(path, _T1, "t1")
    memory.remember(path, _T2, "t2")
    return path


# ------------------------------------------------------------------ storing


def test_remember_indexes_the_turns_worth_keeping(tmp_path):
    path = tmp_path / memory.FILE
    assert memory.remember(path, _T1, "t1") == 2
    assert path.exists()


def test_remember_is_idempotent(index):
    # Callers re-index the whole thread after every answer; storing the same
    # turn twice would double it in every future search.
    assert memory.remember(index, _T1, "t1") == 0


def test_only_the_new_turns_cost_anything(index):
    grown = _T1 + [{"role": "user",
                    "content": "y si en vez de recortar ASML compro más ahora "
                               "que ha caído tanto desde los máximos?"}]
    assert memory.remember(index, grown, "t1") == 1


def test_small_talk_is_not_a_memory(tmp_path):
    chatter = [{"role": "user", "content": "ok"},
               {"role": "assistant", "content": "gracias"},
               {"role": "user", "content": "y eso?"}]
    assert memory.remember(tmp_path / memory.FILE, chatter, "t1") == 0


def test_turns_that_are_not_the_conversation_are_skipped(tmp_path):
    system = [{"role": "system", "content": "x" * 200}]
    assert memory.remember(tmp_path / memory.FILE, system, "t1") == 0


def test_the_onboarding_walkthrough_is_not_a_memory(tmp_path):
    """Its steps are app copy shown to the reader, not something they said or
    were told about their book — indexed, they would answer "what have we
    talked about" with the tutorial."""
    tour = [{"role": "assistant", "content": "x" * 200, "guide": {"step": "import"}}]
    assert memory.remember(tmp_path / memory.FILE, tour, "t1") == 0


def test_a_long_turn_is_indexed_up_to_its_share(tmp_path):
    path = tmp_path / memory.FILE
    memory.remember(path, [{"role": "user", "content": "palabra " * 5000}], "t1")
    got = memory.recall(path, "palabra")
    assert got and len(got[0].text) <= memory.MAX_CHARS


def test_the_same_thread_in_two_accounts_never_mixes(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    memory.remember(a, _T1, "t1")
    memory.remember(b, _T2, "t1")
    assert "ASML" in memory.recall(a, "ASML")[0].text
    assert not [m for m in memory.recall(b, "ASML") if "ASML" in m.text]


# ------------------------------------------------------------------ finding


def test_recall_finds_the_turn_by_its_words(index):
    got = memory.recall(index, "¿qué decidí sobre ASML?")
    assert got and "ASML" in got[0].text


def test_recall_finds_a_turn_that_shares_no_words(index):
    # The point of the embedding half: no term here appears in the note.
    got = memory.recall(index, "how much of one holding is too much")
    assert any("concentración" in m.text for m in got)


def test_recall_ignores_accents_the_user_did_not_type(index):
    assert memory.recall(index, "concentracion de la cartera")


def test_recall_skips_the_conversation_in_progress(index):
    threads = {m.thread for m in memory.recall(index, "ASML", exclude_thread="t1")}
    assert "t1" not in threads


def test_recall_ranks_best_first(index):
    got = memory.recall(index, "Nvidia")
    assert [m.rank for m in got] == sorted(m.rank for m in got)


def test_recall_respects_the_limit(index):
    assert len(memory.recall(index, "cartera position", limit=1)) == 1


def test_recall_without_an_index_is_empty(tmp_path):
    assert memory.recall(tmp_path / "never-written.db", "anything") == []


def test_recall_of_nothing_searches_nothing(index):
    assert memory.recall(index, "   ") == []


# ------------------------------------------------------------- fts queries


@pytest.mark.parametrize("raw", [
    '¿qué decidí sobre "ASML"?',
    "AND OR NOT NEAR",
    "BRK.B vs BRK-B",
    "50% -- drop",
])
def test_a_question_never_becomes_an_fts_syntax_error(index, raw):
    # FTS5 treats quotes, hyphens and its own keywords as syntax; a raw
    # question is a crash waiting for the first user who types one.
    memory.recall(index, raw)  # must not raise


def test_the_fts_query_is_the_words_the_user_typed():
    assert memory.fts_query("¿qué tal ASML?") == '"asml" OR "qué" OR "tal"'
    assert memory.fts_query("!!! ---") == ""


# --------------------------------------------------------------- auto recall

_FILLER = ("Antes de nada conviene repasar la cartera entera, el peso de cada "
           "posición, la liquidez disponible y el horizonte que tienes para "
           "este dinero. ") * 3  # well past the lead


def _index(tmp_path, *turns, thread="t9"):
    path = tmp_path / memory.FILE
    memory.remember(path, [{"role": "assistant", "content": t} for t in turns],
                    thread)
    return path


def test_about_finds_the_turn_that_names_it_early(index):
    [hit] = memory.about(index, ["ASML"])
    assert (hit.thread, hit.role, hit.rank) == ("t1", "user", 1)
    assert hit.text == " ".join(_T1[0]["content"].split())


def test_about_matches_a_name_in_any_case_or_accent(index):
    assert [m.thread for m in memory.about(index, ["NVIDIA"])] == ["t2"]
    assert [m.thread for m in memory.about(index, ["posición"])] == ["t1"]


def test_a_single_passing_mention_is_not_what_a_turn_is_about(tmp_path):
    path = _index(tmp_path, _FILLER + "Por cierto, ASML también cayó.")
    assert len(_FILLER) > memory._LEAD
    assert memory.about(path, ["ASML"]) == []


def test_a_name_said_twice_is_what_a_turn_is_about_wherever_it_is(tmp_path):
    path = _index(tmp_path, _FILLER + "ASML cayó, y ASML sigue cara.")
    assert len(memory.about(path, ["ASML"])) == 1


def test_about_ranks_the_turn_that_opens_with_the_name_first(tmp_path):
    path = _index(tmp_path,
                  "Sobre ASML: la cartera de pedidos es lo que mueve la acción "
                  "este trimestre, más que el margen.",
                  _FILLER + "ASML cayó, y ASML sigue cara, y ASML ya no es "
                  "la que era.")
    ranked = memory.about(path, ["ASML"])
    assert [m.text[:10] for m in ranked] == ["Sobre ASML", _FILLER[:10]]
    assert [m.rank for m in ranked] == [1, 2]


def test_about_respects_the_limit(tmp_path):
    turns = [f"ASML, nota {n}: la cartera de pedidos manda sobre el margen "
             "este trimestre." for n in range(5)]
    path = _index(tmp_path, *turns)
    assert len(memory.about(path, ["ASML"])) == memory.ABOUT_LIMIT
    assert len(memory.about(path, ["ASML"], limit=1)) == 1


def test_about_skips_the_conversation_in_progress(index):
    assert memory.about(index, ["ASML"], exclude_thread="t1") == []


def test_a_tool_call_a_model_printed_is_not_a_memory_of_anything(tmp_path):
    path = _index(tmp_path, '[{"tool": "quote", "args": {"ticker": "ASML"}}, '
                            '{"tool": "news", "args": {"ticker": "ASML"}}]')
    assert memory.about(path, ["ASML"]) == []


def test_a_pair_is_found_however_its_hyphen_was_typed(tmp_path):
    # U+2011, the non-breaking hyphen models like to print.
    path = _index(tmp_path, "Tu SOL\u2011EUR ya pesa un 12% de la cartera, más "
                            "de lo que dijiste que querías en cripto.")
    assert len(memory.about(path, ["SOL-EUR"])) == 1
    assert len(memory.about(path, ["SOL"])) == 1


def test_a_name_made_of_one_letter_parts_is_still_found(tmp_path):
    path = _index(tmp_path, "El S&P 500 lleva un 18% en el año y casi todo es "
                            "cosa de siete compañías.")
    assert len(memory.about(path, ["S&P"])) == 1


def test_a_recalled_turn_is_quoted_up_to_its_share(tmp_path):
    path = _index(tmp_path, "ASML " + "y la cartera de pedidos " * 60)
    [hit] = memory.about(path, ["ASML"])
    assert len(hit.text) == memory._QUOTE_CHARS


def test_about_nothing_or_without_an_index_is_empty(index, tmp_path):
    assert memory.about(index, []) == []
    assert memory.about(index, ["!!!"]) == []
    assert memory.about(tmp_path / "none.db", ["ASML"]) == []


def test_augment_quotes_the_turns_under_the_message(index):
    hits = memory.about(index, ["ASML"])
    out = memory.augment("¿y ASML?", hits)
    assert out.startswith("¿y ASML?\n\n---\n" + memory.QUOTE_HEADER)
    assert out.endswith(hits[0].line())
    assert memory.augment("¿y ASML?", []) == "¿y ASML?"


# ---------------------------------------------------------------- forgetting


def test_forget_drops_one_threads_memories(index):
    assert memory.forget(index, "t1") == 2
    assert {m.thread for m in memory.recall(index, "position cartera")} == {"t2"}


def test_forget_of_an_unknown_thread_is_harmless(index):
    assert memory.forget(index, "nope") == 0


def test_a_forgotten_turn_can_be_remembered_again(index):
    memory.forget(index, "t1")
    assert memory.remember(index, _T1, "t1") == 2


# ------------------------------------------------------------- degradation


def test_nothing_is_indexed_when_the_model_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "available", lambda: False)
    assert memory.remember(tmp_path / memory.FILE, _T1, "t1") == 0
    assert memory.recall(tmp_path / memory.FILE, "ASML") == []


def test_a_broken_embedder_does_not_break_the_conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "embed", lambda texts: None)
    assert memory.remember(tmp_path / memory.FILE, _T1, "t1") == 0


def test_an_unwritable_index_does_not_break_the_conversation(tmp_path):
    blocked = tmp_path / "file.txt"
    blocked.write_text("not a database")
    assert memory.remember(blocked, _T1, "t1") == 0
    assert memory.recall(blocked, "ASML") == []
    assert memory.about(blocked, ["ASML"]) == []
