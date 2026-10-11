"""knowledge: the app's own documentation, searchable from the chat."""

from datetime import date

import pytest

from stocks.chat import hybrid, knowledge, toolbox
from stocks.chat.toolbox import Context

# ------------------------------------------------------------------ corpus


def _docs() -> dict[str, list[knowledge.Passage]]:
    out: dict[str, list[knowledge.Passage]] = {}
    for path in sorted(knowledge.DOCS_DIR.glob("*.md")):
        out[path.name] = knowledge.parse_doc(path.read_text(encoding="utf-8"),
                                             path.name)
    return out


def test_every_knowledge_file_parses_with_its_frontmatter():
    docs = _docs()
    assert docs, "no knowledge files"
    ids = [passages[0].doc for passages in docs.values()]
    assert len(ids) == len(set(ids)), "two files share an id"
    for name, passages in docs.items():
        assert passages, name
        assert name == f"{passages[0].doc}.md", "the id names the file"
        assert passages[0].tags, f"{name}: tags are how a Spanish question finds it"


def test_knowledge_files_use_only_section_headings():
    # A `###` would be indexed as body text of the section above it.
    for path in knowledge.DOCS_DIR.glob("*.md"):
        assert "\n###" not in path.read_text(encoding="utf-8"), path.name


def test_the_methodology_was_checked_against_the_code_this_year():
    # Brackets, windows and thresholds change; a stale `as_of` is the prompt
    # to re-read the code and bump it.
    for name, passages in _docs().items():
        checked = date.fromisoformat(passages[0].as_of)
        assert (date.today() - checked).days <= 400, f"{name} as_of {checked}"


def test_every_passage_fits_its_share_of_a_result():
    # Four passages and their headers must fit one tool result uncut.
    for p in knowledge.passages():
        assert len(p.text) <= knowledge.MAX_CHARS + 300, (p.doc, p.section)


def test_the_tour_is_indexed_in_both_languages():
    tour = {(p.doc, p.lang) for p in knowledge.passages() if p.doc.startswith("tour:")}
    assert ("tour:import", "en") in tour and ("tour:import", "es") in tour
    # News cards repeat, in the past tense, what a step already says.
    assert not any(p.doc.startswith("tour:news") for p in knowledge.passages())


def test_a_doc_is_cut_by_section_and_keeps_its_date():
    doc = ("---\nid: x\ntitle: X doc\nas_of: 2026-10-01\ntags: equis\n---\n"
           "Intro line.\n\n## First\nOne.\n\n## Second\nTwo.\n")
    got = knowledge.parse_doc(doc)
    assert [(p.section, p.text) for p in got] == [
        ("X doc", "Intro line."), ("First", "One."), ("Second", "Two.")]
    assert {p.as_of for p in got} == {"2026-10-01"}
    assert "as of 2026-10-01" in got[1].line() and "X doc § First" in got[1].line()


def test_a_doc_without_frontmatter_is_refused():
    with pytest.raises(ValueError):
        knowledge.parse_doc("## Heading\nbody")
    with pytest.raises(ValueError):
        knowledge.parse_doc("---\nid: x\ntitle: X\n---\nno date")


def test_long_text_is_cut_between_sentences():
    text = " ".join(f"Sentence number {i} says something." for i in range(60))
    pieces = knowledge._cut(text, 200)
    assert len(pieces) > 1
    assert all(len(p) <= 200 for p in pieces)
    assert all(p.endswith(".") for p in pieces)
    assert " ".join(pieces) == text


# ------------------------------------------------------------------ search


def test_an_empty_question_searches_nothing():
    assert knowledge.lookup("   ") == []


def test_a_search_returns_one_passage_per_piece_of_the_app():
    hits = knowledge.lookup("Telegram notifications notificaciones digest")
    keys = [(h.doc, "" if h.doc.startswith("tour:") else h.section) for h in hits]
    assert len(keys) == len(set(keys)), "the same tour step twice, en + es"
    assert len(hits) <= knowledge.LOOKUP_LIMIT


def test_the_keyword_half_alone_still_answers(monkeypatch):
    monkeypatch.setattr(hybrid, "available", lambda: False)
    index = knowledge._Index(knowledge.passages())
    assert not index.vectors
    top = [index.items[i].doc for i in index.search("Modelo 720", 12)[:4]]
    assert "tax-spain" in top


def test_spanish_questions_lean_on_the_keywords():
    assert knowledge._spanish_weight("¿cómo importo DEGIRO?") < 1.0
    assert knowledge._spanish_weight("tramos del ahorro") < 1.0
    assert knowledge._spanish_weight("how do I import DEGIRO") == 1.0


def test_the_result_is_framed_as_documentation():
    hits = knowledge.lookup("Modelo 720")
    out = knowledge.block(hits)
    assert out.startswith(knowledge.HEADER)
    assert "as of" in out


# The eval set: a question a user would type, and a document the answer must
# come from among the top hits. Kept to questions whose answer lives in one
# obvious place; a ranking change that drops one of these is a regression.
GOLDEN = [
    ("why is my loss deferred after I bought back", {"tax-spain", "tax-engine"}),
    ("¿por qué no se deduce mi pérdida si recompré?", {"tax-spain", "tax-engine"}),
    ("¿necesito presentar el modelo 720?", {"tax-spain"}),
    ("tramos de la base del ahorro", {"tax-spain"}),
    ("dónde cambio mi residencia fiscal", {"tour:prefs", "tax-engine"}),
    ("which share matching does the UK use", {"tax-engine"}),
    ("how do I import my DEGIRO account", {"importing", "tour:import"}),
    ("mi extracto de DEGIRO no se importa", {"importing", "tour:import"}),
    ("can I import from Binance", {"importing", "tour:import"}),
    ("why is a position held at cost", {"cost-basis-and-currency", "importing"}),
    ("what exchange rate is used to convert my trades",
     {"cost-basis-and-currency"}),
    ("qué es la rentabilidad ponderada por tiempo",
     {"returns-and-risk", "tour:risk"}),
    ("how is the money-weighted return annualised", {"returns-and-risk"}),
    ("what does the five-year projection assume", {"returns-and-risk",
                                                   "tour:projection"}),
    ("how do I turn on Telegram alerts", {"tour:notify"}),
    ("¿cómo activo las alertas de Telegram?", {"tour:notify"}),
    ("how does the daily briefing work", {"tour:daily"}),
    ("can I use my own OpenAI key in the chat", {"tour:assistant"}),
    ("cómo se calcula la TIR", {"returns-and-risk"}),
    ("why does the review page say trim", {"review-scoring"}),
    ("¿por qué me dice recortar esta posición?", {"review-scoring", "tour:review"}),
    ("how is the quality score computed", {"review-scoring"}),
    ("what does the risk appetite score mean", {"pulse-risk-appetite"}),
    ("¿qué significa Euforia en el pulso?", {"pulse-risk-appetite", "tour:pulse"}),
    ("how does my portfolio react to this regime", {"pulse-risk-appetite"}),
    ("how are sector peers chosen", {"sector-screen"}),
    ("¿cómo se elige la cohorte del sector?", {"sector-screen"}),
]


@pytest.mark.skipif(not hybrid.available(),
                    reason="the eval measures the full hybrid ranking")
@pytest.mark.parametrize(("question", "expected"), GOLDEN)
def test_golden_questions_find_their_document(question, expected):
    got = [h.doc for h in knowledge.lookup(question)]
    assert expected & set(got), f"{question!r} -> {got}"


# ------------------------------------------------------------------ the tool


def test_the_tool_answers_from_the_documentation():
    out = toolbox.executor(Context())("lookup_knowledge", {"query": "Modelo 720"})
    assert out.startswith(knowledge.HEADER)
    assert len(out) <= toolbox.MAX_RESULT_CHARS + 10


def test_the_tool_without_a_query_does_not_search():
    out = toolbox.executor(Context())("lookup_knowledge", {})
    assert "no query" in out.lower()


def test_the_tool_is_not_offered_without_documents(monkeypatch):
    monkeypatch.setattr(knowledge, "available", lambda: False)
    assert "lookup_knowledge" not in [s.name for s in toolbox.specs(Context())]
