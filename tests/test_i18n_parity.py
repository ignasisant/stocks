"""Every locale catalog carries the same keys, with the same format slots.

A missing key degrades silently at runtime — `i18n.t()` falls back to English,
so a half-translated page ships looking fine in development and mixed-language
in production. A mismatched `{placeholder}` is worse: `str.format` raises
KeyError on the page that uses it. Both are cheap to catch here.
"""

import json
import string
from pathlib import Path

import pytest

from stocks.web.i18n import DEFAULT_LANG, LANGUAGES

LOCALES = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web" / "locales"
OTHER_LANGS = sorted(set(LANGUAGES) - {DEFAULT_LANG})


def _catalog(lang: str, name: str) -> dict[str, str]:
    return json.loads((LOCALES / lang / name).read_text(encoding="utf-8"))


def _slots(value: str) -> set[str]:
    """Named `{placeholder}` fields in a catalog string."""
    return {
        field
        for _, field, _, _ in string.Formatter().parse(value)
        if field
    }


def _namespaces() -> list[str]:
    return sorted(p.name for p in (LOCALES / DEFAULT_LANG).glob("*.json"))


def test_default_catalog_is_not_empty():
    assert _namespaces(), "no English catalogs found — wrong LOCALES path?"


@pytest.mark.parametrize("lang", OTHER_LANGS)
def test_same_namespace_files(lang):
    assert sorted(p.name for p in (LOCALES / lang).glob("*.json")) == _namespaces()


@pytest.mark.parametrize("lang", OTHER_LANGS)
@pytest.mark.parametrize("name", _namespaces())
def test_same_keys(lang, name):
    base, other = _catalog(DEFAULT_LANG, name), _catalog(lang, name)
    assert set(other) == set(base), (
        f"{lang}/{name}: missing={sorted(set(base) - set(other))} "
        f"unexpected={sorted(set(other) - set(base))}"
    )


@pytest.mark.parametrize("lang", OTHER_LANGS)
@pytest.mark.parametrize("name", _namespaces())
def test_same_format_slots(lang, name):
    base, other = _catalog(DEFAULT_LANG, name), _catalog(lang, name)
    mismatched = {
        key: (sorted(_slots(base[key])), sorted(_slots(value)))
        for key, value in other.items()
        if key in base and _slots(base[key]) != _slots(value)
    }
    assert not mismatched, f"{lang}/{name}: placeholder mismatch {mismatched}"


@pytest.mark.parametrize("name", _namespaces())
def test_keys_are_namespaced(name):
    """Catalogs merge into one flat dict, so every key needs a dotted prefix.

    The prefix usually matches the filename, but not always — common.json
    carries the `nav.*` labels too. What matters is that no key is bare, since
    those are the ones that collide once the fragments are merged.
    """
    stray = [
        k for k in _catalog(DEFAULT_LANG, name) if "." not in k or k.startswith(".")
    ]
    assert not stray, f"{name}: keys with no namespace prefix: {stray}"


def test_validation_issue_keys_match_the_catalog():
    """`validate.ISSUE_TEXT` is the English source for the issue catalog.

    The CLI prints it and the web app translates the same keys, so a new issue
    added in one place and not the other ships as a raw key on the page.
    """
    from stocks.portfolio.validate import ISSUE_TEXT

    catalog = _catalog(DEFAULT_LANG, "validate.json")
    assert set(catalog) == set(ISSUE_TEXT)
    assert catalog == ISSUE_TEXT, "English catalog has drifted from ISSUE_TEXT"
