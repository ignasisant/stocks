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


def test_an_unknown_language_reads_as_english():
    some = next(iter(_ids("en")))
    assert learn.lesson(some, "fr") == learn.lesson(some, "en")


def test_neighbours_stop_at_a_paths_ends():
    path = learn.paths()[0]
    assert learn.neighbours(path.lessons[0])[0] is None
    assert learn.neighbours(path.lessons[-1])[1] is None
    assert learn.neighbours(path.lessons[0])[1] == path.lessons[1]
