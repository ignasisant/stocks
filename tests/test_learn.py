"""The Learn curriculum's files hold together.

Hand-written content in two languages drifts one edit at a time: a lesson
added in Spanish and not in English, a term a lesson leans on that the
glossary never defined, an "in the app" link to a tab that was renamed. Each
of those renders as a hole on the page rather than an error, so they are
caught here instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from stocks import learn
from stocks.chat import navigate

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "frontend" / "app" / "src" / "shell" / "Icon.tsx"
LOCALES = ROOT / "src" / "stocks" / "web" / "locales"


def _ids(lang: str) -> set[str]:
    return set(learn.lessons(lang))


def test_every_lesson_exists_in_every_language():
    en = _ids("en")
    assert en, "no lessons shipped"
    for lang in learn.LANGS:
        assert _ids(lang) == en, f"{lang} lessons differ from en"


@pytest.mark.parametrize("lang", learn.LANGS)
def test_a_lessons_frontmatter_matches_across_languages(lang):
    """Only the title and body are translated; where it sits, how long it
    takes and what it links to are the same lesson in every language."""
    for lesson_id, en in learn.lessons("en").items():
        other = learn.lesson(lesson_id, lang)
        assert other is not None
        for field in ("path", "minutes", "as_of", "terms", "app"):
            assert getattr(other, field) == getattr(en, field), (lang, lesson_id, field)


def test_paths_list_exactly_the_lessons_on_disk():
    listed = [i for path in learn.paths() for i in path.lessons]
    assert len(listed) == len(set(listed)), "a lesson is listed twice"
    assert set(listed) == _ids("en")


def test_a_lesson_says_the_path_that_lists_it():
    for path in learn.paths():
        for lesson_id in path.lessons:
            assert learn.lesson(lesson_id, "en").path == path.id


@pytest.mark.parametrize("lang", learn.LANGS)
def test_every_term_a_lesson_names_is_defined(lang):
    defined = {t.id for t in learn.glossary(lang)}
    for lesson in learn.lessons(lang).values():
        missing = set(lesson.terms) - defined
        assert not missing, (lesson.id, missing)


def test_the_glossary_defines_the_same_terms_in_every_language():
    en = {t.id: t.lesson for t in learn.glossary("en")}
    for lang in learn.LANGS:
        assert {t.id: t.lesson for t in learn.glossary(lang)} == en, lang


@pytest.mark.parametrize("lang", learn.LANGS)
def test_a_terms_lesson_exists(lang):
    ids = _ids(lang)
    for term in learn.glossary(lang):
        assert not term.lesson or term.lesson in ids, (term.id, term.lesson)


def test_in_the_app_points_at_a_page_and_tab_the_shell_has():
    for lesson in learn.lessons("en").values():
        if not lesson.app:
            continue
        page, _, query = lesson.app.partition("?")
        assert page in navigate.PAGES, (lesson.id, page)
        tab = dict(p.split("=", 1) for p in query.split("&") if p).get("tab")
        assert tab is None or tab in navigate.PAGES[page], (lesson.id, tab)


def test_path_icons_are_drawn_by_the_shell():
    """No icon font: a name the inline set lacks draws nothing."""
    drawn = set(re.findall(r"^\s*([a-z_]+):\s*\"M", ICONS.read_text(), re.M))
    for path in learn.paths():
        assert path.icon in drawn, path.icon


@pytest.mark.parametrize("lang", learn.LANGS)
def test_every_path_has_its_name_and_blurb(lang):
    catalog = json.loads((LOCALES / lang / "learn.json").read_text())
    for path in learn.paths():
        key = path.id.replace("-", "_")
        for part in ("title", "body"):
            assert catalog.get(f"learn.path_{key}_{part}"), (lang, key, part)


def test_the_glossary_reads_in_alphabetical_order_whatever_the_accents():
    labels = [t.label for t in learn.glossary("es")]
    folded = [learn._folded(label) for label in labels]
    assert folded == sorted(folded)


def test_a_lesson_without_frontmatter_is_refused_by_name():
    with pytest.raises(ValueError, match="broken.md"):
        learn.parse_lesson("no frontmatter here", "broken.md")


_HEAD = "---\nid: a\npath: start\ntitle: A\nminutes: 1\nas_of: 2026-01-01\n"


def test_a_lessons_quiz_is_optional_and_parsed():
    plain = learn.parse_lesson(_HEAD + "---\nBody", "a.md")
    assert plain.quiz is None
    text = (
        _HEAD + "quiz_q: Q?\nquiz_options: x | y | z\nquiz_answer: 2\n"
        "quiz_why: Because.\n---\nBody"
    )
    quiz = learn.parse_lesson(text, "a.md").quiz
    assert quiz == learn.Quiz("Q?", ("x", "y", "z"), 1, "Because.")


@pytest.mark.parametrize(
    "extra",
    [
        "quiz_q: Q?\n",
        "quiz_q: Q?\nquiz_options: x\nquiz_answer: 1\nquiz_why: w\n",
        "quiz_q: Q?\nquiz_options: x | y\nquiz_answer: 3\nquiz_why: w\n",
        "quiz_q: Q?\nquiz_options: x | y\nquiz_answer: b\nquiz_why: w\n",
    ],
)
def test_a_broken_quiz_is_refused_by_file_name(extra):
    with pytest.raises(ValueError, match="a.md"):
        learn.parse_lesson(_HEAD + extra + "---\nBody", "a.md")


@pytest.mark.parametrize("lang", learn.LANGS)
def test_a_quiz_has_the_same_shape_in_every_language(lang):
    for lesson_id, en in learn.lessons("en").items():
        a, b = en.quiz, learn.lesson(lesson_id, lang).quiz
        assert (a is None) == (b is None), (lang, lesson_id)
        if a and b:
            assert (len(a.options), a.answer) == (len(b.options), b.answer)


def test_an_unknown_language_reads_as_english():
    some = next(iter(_ids("en")))
    assert learn.lesson(some, "fr") == learn.lesson(some, "en")


def test_neighbours_stop_at_a_paths_ends():
    path = learn.paths()[0]
    assert learn.neighbours(path.lessons[0])[0] is None
    assert learn.neighbours(path.lessons[-1])[1] is None
    assert learn.neighbours(path.lessons[0])[1] == path.lessons[1]


def test_try_steps_are_optional_and_parsed():
    assert learn.parse_lesson(_HEAD + "---\nBody", "a.md").steps == ()
    text = (
        _HEAD
        + "try: Open **NVDA**. => ticker | Then risk. => portfolio?tab=risk\n---\nBody"
    )
    assert learn.parse_lesson(text, "a.md").steps == (
        learn.Step("Open **NVDA**.", "ticker"),
        learn.Step("Then risk.", "portfolio?tab=risk"),
    )


def test_a_try_step_without_a_screen_is_refused():
    with pytest.raises(ValueError, match="try step"):
        learn.parse_lesson(_HEAD + "try: Open it\n---\nBody", "a.md")


def test_try_steps_exist_in_every_language_with_the_same_screens():
    for lesson_id in learn.lessons("en"):
        screens = {
            lang: [s.app for s in learn.lessons(lang)[lesson_id].steps]
            for lang in learn.LANGS
        }
        assert screens["es"] == screens["en"] == screens["it"], lesson_id


def test_live_figures_are_optional_and_checked():
    assert learn.parse_lesson(_HEAD + "---\nBody", "a.md").live is None
    text = _HEAD + "live: NVDA | price, cap\nlive_why: Why.\n---\nBody"
    assert learn.parse_lesson(text, "a.md").live == learn.Live(
        "NVDA", ("price", "cap"), "Why."
    )
    for bad in ("live: NVDA | price\n", "live: NVDA | beta\nlive_why: w\n"):
        with pytest.raises(ValueError, match="live"):
            learn.parse_lesson(_HEAD + bad + "---\nBody", "a.md")


def test_live_figures_name_the_same_facts_in_every_language():
    for lesson_id in learn.lessons("en"):
        shown = {
            lang: (lv.ticker, lv.facts)
            if (lv := learn.lessons(lang)[lesson_id].live)
            else None
            for lang in learn.LANGS
        }
        assert shown["es"] == shown["en"] == shown["it"], lesson_id
