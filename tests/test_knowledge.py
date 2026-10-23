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


def test_no_passage_is_a_stub_or_a_giant():
    # A tail of one short sentence has lost what it was about ("Losses carry
    # forward five years only if you opt for englobamento" — which country?).
    # Methodology passages measured 2026-10-23 after balancing: 155..896 chars,
    # median 576. The tour's own step bodies are short by nature.
    sizes = [len(p.text) for p in knowledge.passages()
             if not p.doc.startswith("tour:")]
    assert min(sizes) >= 150, min(sizes)
    assert max(sizes) <= knowledge.MAX_CHARS


def test_the_last_two_pieces_are_balanced_not_a_stub():
    text = " ".join(f"Sentence number {i} says something." for i in range(26))
    pieces = knowledge._cut(text, 500)
    assert len(pieces) == 2
    assert abs(len(pieces[0]) - len(pieces[1])) < 40


def test_a_list_is_cut_between_items_not_after_its_lead_in():
    text = "Export from: " + " ".join(
        f"- Broker {i}: choose the activity report and export it as CSV."
        for i in range(30))
    pieces = knowledge._cut(text, 300)
    assert len(pieces) > 1
    assert all(not p.endswith(":") for p in pieces)
    assert all(p.startswith(("Export", "- Broker")) for p in pieces)


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


# Questions no document answers, sharing no word with any of them. Nearest-
# neighbour search still has a nearest neighbour; these must come back empty
# rather than as "documentation" the model then answers from.
OFF_TOPIC = [
    "who won the champions league",
    "what's the P/E of Apple",
    "¿qué opinas de Tesla?",
    "¿hay app para iPhone?",
    "hello",
]


@pytest.mark.skipif(not hybrid.available(),
                    reason="the cut is on the semantic half's distance")
@pytest.mark.parametrize("question", OFF_TOPIC)
def test_a_question_nothing_answers_finds_nothing(question):
    assert knowledge.lookup(question) == []


# Out-of-scope questions that do share words with the knowledge base ("import",
# "score", "tax", "plan") but ask something it does not answer: another app's
# feature, a payment method, a topic no document covers. The keyword half
# matches the shared word and the semantic half always has a nearest passage, so
# before the unknown-word gate each of these came back as four passages of
# "documentation". Must abstain.
MUST_ABSTAIN = [
    "does the app have a mobile widget like Robinhood",
    "¿puedo pagar la suscripción premium con Bizum?",
    "¿tiene la app modo oscuro para Apple Watch?",
    "¿qué es el interés compuesto?",
    "what is a dividend aristocrat",
    "¿cuánto es el IVA en España?",
    "what is the tax rate on lottery winnings in Spain",
    "how is my pizza delivery score computed",
    "what does the quality score of my wine collection mean",
    "¿cómo importo contactos del móvil?",
    "what's the pulse rate of a healthy adult",
    "how do I reset my password",
]

# Still answered with passages today, and documented rather than pinned: the
# question is made of words the knowledge base does have ("share", "tax",
# "import"), so only reading the passages shows they do not answer it. The
# tool's own text tells the model to judge, not to quote.
KNOWN_NOT_ABSTAINED = [
    "how do I export my portfolio to Google Sheets like in Sharesight",
    "what is the capital gains tax in Japan",
    "how do I import a Python module",
    "how does a short squeeze work",
]

# In-scope controls, phrased the way the out-of-scope ones are: each shares a
# word with its neighbours above and must still find its document.
CONTROLS = [
    ("how do I import my DEGIRO account", {"importing"}),
    ("what is the tax rate on savings income in Spain", {"tax-spain"}),
    ("what does the quality score of a holding mean", {"review-scoring"}),
    ("how is the pulse score read", {"pulse-risk-appetite", "tour:pulse"}),
    ("how do I reset my Telegram alerts", {"tour:notify"}),
    ("¿cómo importo mi extracto de Revolut?", {"importing", "tour:import"}),
    ("does the app support Trading 212 imports", {"importing"}),
]


@pytest.fixture(params=["hybrid", "keywords"])
def index(request, monkeypatch):
    """The knowledge index with and without the embedding model: the
    out-of-scope gate is lexical first, so it must hold in both."""
    if request.param == "keywords":
        monkeypatch.setattr(hybrid, "available", lambda: False)
    elif not hybrid.available():
        pytest.skip("the hybrid index needs the embedding model")
    return knowledge._Index(knowledge.passages())


@pytest.mark.parametrize("question", MUST_ABSTAIN)
def test_an_out_of_scope_question_sharing_words_abstains(index, question):
    assert index.out_of_scope(question)
    assert index.search(question, 12) == []


@pytest.mark.parametrize(("question", "expected"), CONTROLS)
def test_in_scope_controls_still_find_their_document(index, question, expected):
    got = [index.items[i].doc for i in index.search(question, 12)[:4]]
    assert expected & set(got), f"{question!r} -> {got}"


@pytest.mark.parametrize("question", KNOWN_NOT_ABSTAINED)
def test_the_gate_is_not_a_judge_of_answers(index, question):
    # Pins the limit: if a better gate makes these abstain, move them up.
    assert not index.out_of_scope(question)


def test_the_unknown_word_gate_counts_words_the_index_lacks(index):
    assert not index.out_of_scope("how do I import my DEGIRO account")
    assert index.out_of_scope("Bizum")
    assert not index.out_of_scope("¿y?")  # nothing left after the stop words


@pytest.mark.skipif(not hybrid.available(),
                    reason="the cut is on the semantic half's distance")
def test_a_close_paraphrase_without_shared_words_still_answers():
    # "dividendos" is too common in the corpus to count as a keyword, so this
    # one rides on meaning alone — and is close enough to.
    assert "tour:income" in [h.doc for h in knowledge.lookup("como veo los dividendos")]


# ------------------------------------------------------------------ browsing


def test_the_manifest_lists_every_document_once():
    lines = knowledge.manifest().splitlines()
    ids = [line.split(":")[0].removeprefix("- ") for line in lines]
    assert sorted(ids) == sorted(p.stem for p in knowledge.DOCS_DIR.glob("*.md"))
    assert not any(i.startswith("tour:") for i in ids)


def test_a_document_reads_as_its_sections():
    toc = knowledge.contents("tax-spain")
    assert toc.startswith("Spanish tax") and "- Savings base brackets" in toc
    assert knowledge.contents("nope") == ""


def test_a_section_reads_whole_and_dated():
    whole = knowledge.section("tax-spain", "savings base")
    assert whole is not None and whole.section == "Savings base brackets"
    assert "19%" in whole.text and whole.as_of
    assert knowledge.section("tax-spain", "nope") is None
    assert knowledge.section("tax-spain", "") is None


def test_every_section_fits_one_result_uncut():
    for doc, head in {(p.doc, p.section) for p in knowledge.passages()
                      if not p.doc.startswith("tour:")}:
        out = knowledge.block([knowledge.section(doc, head)])
        assert len(out) <= toolbox.MAX_RESULT_CHARS, (doc, head)


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


def test_the_tool_lists_the_documents_it_holds():
    spec = next(s for s in toolbox.specs(Context()) if s.name == "lookup_knowledge")
    assert "- tax-spain: " in spec.description
    assert spec.schema["required"] == []


def test_the_tool_browses_a_document_then_a_section():
    run = toolbox.executor(Context())
    assert "- Savings base brackets" in run("lookup_knowledge", {"doc": "tax-spain"})
    out = run("lookup_knowledge", {"doc": "tax-spain", "section": "Savings base"})
    assert out.startswith(knowledge.HEADER) and "19%" in out
    assert "- tax-spain: " in run("lookup_knowledge", {"doc": "nope"})
    assert "Sections:" in run("lookup_knowledge",
                              {"doc": "tax-spain", "section": "nope"})


def test_the_tool_says_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(knowledge, "lookup", lambda q: [])
    out = toolbox.executor(Context())("lookup_knowledge", {"query": "anything"})
    assert "does not cover it" in out


# ------------------------------------------------------------------ links


def test_every_link_in_the_frontmatter_points_somewhere():
    from stocks.web import onboarding

    steps = {s.id for s in onboarding.STEPS}
    ids = {p.stem for p in knowledge.DOCS_DIR.glob("*.md")}
    for name, passages in _docs().items():
        first = passages[0]
        assert not first.step or first.step in steps, f"{name}: step {first.step}"
        assert first.doc not in first.related, f"{name} links to itself"
        assert set(first.related) <= ids, f"{name}: related {first.related}"


def test_a_result_points_to_the_related_documents_it_left_out():
    hit = knowledge.section("tax-spain", "Savings base")
    out = knowledge.block([hit])
    assert out.rstrip().splitlines()[-1].startswith("See also (doc=…): tax-engine (")
    # A document the search already returned is not pointed to again.
    out = knowledge.block([hit, knowledge.section("tax-engine", "Which countries"),
                           knowledge.section("cost-basis-and-currency", "Cost basis")])
    tail = out.split("See also", 1)[1]
    assert "tax-engine" not in tail and "tax-spain" not in tail
    assert "importing (" in tail


def test_a_result_reads_back_as_the_documents_it_quoted():
    hits = [knowledge.section("tax-spain", "Savings base"),
            knowledge.section("tax-spain", "Two-month"),
            next(p for p in knowledge.passages() if p.doc == "tour:import")]
    got = knowledge.cited(knowledge.block(hits))
    assert [p.doc for p in got] == ["tax-spain", "tour:import"]
    assert knowledge.cited("[not a heading]\nhttps://example.com") == []


def test_a_cited_document_opens_the_screen_it_is_about():
    spain = knowledge.source(knowledge.section("tax-spain", "Savings base"))
    assert spain == {"title": "Spanish tax (IRPF) as the app computes it",
                     "url": "/portfolio?tab=tax", "step": "tax"}
    tour = knowledge.source(next(p for p in knowledge.passages()
                                 if p.doc == "tour:notify"))
    assert tour == {"title": "", "url": "/profile?tab=notify", "step": "notify"}
    assert knowledge.page("assistant") == ""  # a drawer, not a screen
    assert knowledge.page("daily") == "/"
    assert knowledge.page("nope") == ""


def test_the_gather_step_lists_the_documents_it_read():
    from stocks.chat.agent import Evidence
    from stocks.web.llm import ToolCall

    result = knowledge.block([knowledge.section("tax-spain", "Savings base")])
    ev = Evidence(calls=[ToolCall("lookup_knowledge", {"query": "tramos"}, result),
                         ToolCall("lookup_knowledge", {"query": "again"}, result)])
    assert ev.sources() == [knowledge.source(knowledge.section("tax-spain", "Savings"))]
