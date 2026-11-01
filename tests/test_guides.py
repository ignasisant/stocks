"""The public guides: the Spanish-tax lessons as indexable pages.

These pages exist to be found from a search box, so what is checked here is
what a search result and a crawler read: a title and a description that fit, a
canonical and hreflang pair that point at each other, structured data that
parses, and a body that cannot carry markup a lesson file did not mean.
"""

import json
import re

import pytest

from stocks import learn
from stocks.web import guides, seo

BASE = "https://topstocks.example"
LANGS = tuple(guides.PATHS)


def test_every_public_path_is_a_real_learn_path():
    known = {p.id for p in learn.paths()}
    assert set(guides.PUBLIC) <= known
    assert guides.lesson_ids()


@pytest.mark.parametrize("lang", LANGS)
def test_every_guide_names_its_own_slug_and_description(lang):
    """The fallbacks are for the app; a public page gets written ones."""
    for lesson_id in guides.lesson_ids():
        lesson = learn.lesson(lesson_id, lang)
        assert lesson.slug != lesson.id, (lang, lesson_id)
        assert lesson.description, (lang, lesson_id)
        assert len(lesson.description) <= guides.DESCRIPTION_MAX, (lang, lesson_id)


@pytest.mark.parametrize("lang", LANGS)
def test_slugs_are_unique_within_a_language(lang):
    slugs = [learn.lesson(i, lang).slug for i in guides.lesson_ids()]
    assert len(slugs) == len(set(slugs))
    for slug in slugs:
        assert guides.find(slug, lang).slug == slug


def test_a_lesson_outside_the_public_paths_has_no_page():
    private = next(
        i for p in learn.paths() if p.id not in guides.PUBLIC for i in p.lessons
    )
    assert guides.find(learn.lesson(private, "en").slug, "en") is None
    assert guides.find("no-such-guide", "es") is None


def _head(html: str) -> str:
    return html.split("</head>", 1)[0]


@pytest.mark.parametrize("lang", LANGS)
def test_each_page_carries_what_a_result_line_needs(lang):
    for lesson_id in guides.lesson_ids():
        html = guides.page(lesson_id, lang, BASE)
        title = re.search(r"<title>(.*?)</title>", html).group(1)
        assert len(title) <= guides.TITLE_MAX, title
        assert f'<html lang="{lang}">' in html
        assert 'name="robots"' not in _head(html), "guides are meant to be indexed"
        canonical = f'<link rel="canonical" href="{BASE}{guides.href(lesson_id, lang)}">'
        assert canonical in html
        for code in (*LANGS, "x-default"):
            assert f'hreflang="{code}"' in _head(html)


def test_the_language_pair_points_at_each_other():
    for lesson_id in guides.lesson_ids():
        es = guides.page(lesson_id, "es", BASE)
        en = guides.page(lesson_id, "en", BASE)
        es_url = f"{BASE}{guides.href(lesson_id, 'es')}"
        en_url = f"{BASE}{guides.href(lesson_id, 'en')}"
        for html in (es, en):
            assert f'hreflang="es" href="{es_url}"' in html
            assert f'hreflang="en" href="{en_url}"' in html
            assert f'hreflang="x-default" href="{es_url}"' in html


@pytest.mark.parametrize("lang", LANGS)
def test_structured_data_parses(lang):
    html = guides.page("revolut-tax-return", lang, BASE)
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    data = json.loads(block.group(1))
    article, crumbs = data
    assert article["@type"] == "Article"
    assert article["dateModified"] == learn.lesson("revolut-tax-return", lang).as_of
    assert crumbs["@type"] == "BreadcrumbList"
    assert crumbs["itemListElement"][-1]["item"].endswith(
        guides.href("revolut-tax-return", lang))


def test_the_body_is_escaped_before_markdown_is_applied():
    html = guides.render_body(
        "Hi <script>x</script> **bold** and *it*\n\n## Head\n- one\n- **two**"
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<strong>bold</strong>" in html and "<em>it</em>" in html
    assert "<h2>Head</h2>" in html
    assert "<ul><li>one</li><li><strong>two</strong></li></ul>" in html


def test_a_list_after_a_paragraph_line_closes_the_paragraph():
    html = guides.render_body("Intro line\n- a\n- b\nAfter")
    assert html == "<p>Intro line</p><ul><li>a</li><li>b</li></ul><p>After</p>"


def test_the_cta_carries_the_source_token_and_language():
    html = guides.page("fifo", "es", BASE)
    assert 'href="/portfolio?tab=tax&amp;guest=1&amp;lang=es&amp;src=guide-fifo"' in html
    assert 'href="/?signin=1&amp;lang=es&amp;src=guide-fifo"' in html
    en = guides.page("forms-720-721", "en", BASE)
    assert 'href="/profile?guest=1&amp;src=guide-forms-720-721"' in en


@pytest.mark.parametrize("lang", LANGS)
def test_the_index_lists_every_guide(lang):
    html = guides.index(lang, BASE)
    for lesson_id in guides.lesson_ids():
        assert f'href="{guides.href(lesson_id, lang)}"' in html


def test_the_policy_allows_exactly_the_documents_own_blocks():
    html = guides.page("fifo", "en", BASE)
    policy = guides.policy(html)
    assert "fonts.googleapis" not in policy
    assert "'unsafe-inline'" not in policy


def test_the_sitemap_lists_both_languages_of_every_guide():
    xml = seo.sitemap_xml(BASE, lastmod="2026-10-31", pages=guides.sitemap_pages())
    for lesson_id in guides.lesson_ids():
        for lang in LANGS:
            assert f"<loc>{BASE}{guides.href(lesson_id, lang)}</loc>" in xml
    for path in guides.PATHS.values():
        assert f"<loc>{BASE}{path}</loc>" in xml


def test_robots_allows_the_guides():
    lines = seo.robots_txt(BASE).splitlines()
    star = lines[lines.index("User-agent: *"):]
    assert f"Allow: {guides.PATHS['en']}" in star
    assert not any(
        line.startswith("Disallow:") and guides.PATHS["es"].startswith(line[10:])
        for line in star if line != "Disallow: /"
    )
