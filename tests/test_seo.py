"""Search and social metadata for the landing pages.

Worth testing rather than eyeballing: none of it is visible on the page, so a
dropped canonical, a stale hreflang or an over-long title fails silently and
only shows up as a ranking or an ugly link preview weeks later. The length
budgets and the JSON-LD/FAQ agreement are the checks that would otherwise need
an external validator.
"""

import html
import json
import re
from xml.etree import ElementTree

import pytest

from stocks.i18n import LANGUAGES, translate
from stocks.web import landing, markup, seo
from stocks.web.landing import (
    ASSET_BASE,
    FAQ_COUNT,
    PATH_EN_ES,
    PATH_ES,
    PATH_ES_US,
    PATH_IT,
)

BASE = "https://topstocks.example"

# Search results truncate a title past ~60 characters and a description past
# ~160. Both are hand-written copy, so the only way they stay inside the budget
# is a test that fails when they don't.
TITLE_MAX = 60
DESCRIPTION_MAX = 160


@pytest.mark.parametrize("lang", sorted(LANGUAGES))
@pytest.mark.parametrize("jur", ["ES", "US"])
def test_title_and_description_fit_a_search_result(lang, jur):
    """Every variant's own copy, not just the default pair's."""
    for key, cap in (("seo_title", TITLE_MAX), ("seo_description", DESCRIPTION_MAX)):
        assert len(translate(landing.jur_key(f"landing.{key}", jur), lang)) <= cap


@pytest.mark.parametrize("lang", sorted(LANGUAGES))
def test_head_carries_the_page_identity(lang):
    head = seo.head(lang, BASE)
    # The head argues the language's own jurisdiction, so the copy it carries
    # is that variant's — the override where one exists, the shared string
    # where it doesn't. jur_key is the same resolution the page itself uses.
    jur = landing.jurisdiction_for(lang)
    title = translate(landing.jur_key("landing.seo_title", jur), lang)
    description = translate(landing.jur_key("landing.seo_description", jur), lang)

    assert f"<title>{markup.esc(title)}</title>" in head
    assert f'<meta name="description" content="{markup.esc(description)}">' in head
    assert f'<link rel="canonical" href="{BASE}{seo.path_for(lang)}">' in head
    assert '<meta charset="utf-8">' in head
    assert "width=device-width" in head


def test_canonical_differs_per_language():
    assert f'href="{BASE}/"' in seo.head("en", BASE)
    assert f'href="{BASE}{PATH_ES}"' in seo.head("es", BASE)
    # And the cross variants are addressable on their own URLs.
    assert (
        f'<link rel="canonical" href="{BASE}{PATH_EN_ES}">'
        in seo.head("en", BASE, jurisdiction="ES")
    )
    assert (
        f'<link rel="canonical" href="{BASE}{PATH_ES_US}">'
        in seo.head("es", BASE, jurisdiction="US")
    )


@pytest.mark.parametrize("lang", sorted(LANGUAGES))
def test_both_languages_declare_each_other_and_a_default(lang):
    head = seo.head(lang, BASE)
    # The set is per jurisdiction: the English US-tax page's Spanish
    # alternate is the Spanish US-tax page, not the Spanish-tax one (different
    # content, and declaring it an alternate would be a lie to the crawler).
    # The Italian page argues Italy's case alone, so it has no alternate.
    expected = {
        "en": ({"en": "/", "es": PATH_ES_US}, "/"),
        "es": ({"en": PATH_EN_ES, "es": PATH_ES}, PATH_EN_ES),
        "it": ({"it": PATH_IT}, PATH_IT),
    }
    alternates, default = expected[lang]
    declared = dict(re.findall(r'hreflang="([^"]+)" href="([^"]+)"', head))
    assert declared == {code: f"{BASE}{path}" for code, path in
                        {**alternates, "x-default": default}.items()}


@pytest.mark.parametrize("lang", sorted(LANGUAGES))
def test_share_card_is_absolute_and_sized(lang):
    """A relative or unsized og:image is the classic broken link preview."""
    head = seo.head(lang, BASE)
    assert f'property="og:image" content="{BASE}{ASSET_BASE}og.png"' in head
    assert f'property="og:image:width" content="{seo.OG_IMAGE_W}"' in head
    assert f'property="og:image:height" content="{seo.OG_IMAGE_H}"' in head
    assert 'name="twitter:card" content="summary_large_image"' in head
    assert f'name="twitter:image" content="{BASE}{ASSET_BASE}og.png"' in head


def test_og_locale_is_a_locale_not_a_language_code():
    assert 'property="og:locale" content="es_ES"' in seo.head("es", BASE)
    assert 'property="og:locale:alternate" content="en_US"' in seo.head("es", BASE)


def test_the_page_asks_to_be_indexed_with_a_large_preview():
    head = seo.head("en", BASE)
    assert 'name="robots" content="index, follow, max-image-preview:large"' in head


def test_extra_styles_land_last():
    """The caller controls CSS order; the metadata must not sit after it."""
    head = seo.head("en", BASE, extra_styles="<style>.x{}</style>")
    assert head.endswith("<style>.x{}</style>")


def test_unknown_language_falls_back_to_english():
    assert seo.head("klingon", BASE) == seo.head("en", BASE)


def test_fonts_are_preconnected_before_they_are_requested():
    head = seo.head("en", BASE)
    assert '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' in head
    assert head.index("preconnect") < head.index('rel="stylesheet"')


# ------------------------------------------------------------- structured data


def _graph(lang: str) -> list[dict]:
    block = seo.json_ld(lang, BASE)
    body = block[block.index(">") + 1 : block.rindex("</script>")]
    return json.loads(body)["@graph"]


@pytest.mark.parametrize("lang", sorted(LANGUAGES))
def test_structured_data_is_valid_json_with_the_three_nodes(lang):
    types = {node["@type"] for node in _graph(lang)}
    assert types == {"WebSite", "SoftwareApplication", "FAQPage"}


def test_structured_data_never_closes_the_script_early():
    """A literal "</script>" in the JSON would end the element mid-object."""
    block = seo.json_ld("en", BASE)
    body = block[block.index(">") + 1 : block.rindex("</script>")]
    # Nothing in today's copy needs escaping; the invariant is what matters,
    # because one "<" added to a FAQ answer would otherwise break the element.
    assert "<" not in body


@pytest.mark.parametrize("lang", sorted(LANGUAGES))
def test_faq_structured_data_matches_the_visible_section(lang):
    """Marking up questions the page does not show is how FAQ results get lost."""
    faq = next(n for n in _graph(lang) if n["@type"] == "FAQPage")
    assert len(faq["mainEntity"]) == FAQ_COUNT
    first = faq["mainEntity"][0]
    assert first["name"] == translate("landing.faq_q1", lang)
    assert first["acceptedAnswer"]["text"] == translate("landing.faq_a1", lang)


def test_the_app_is_declared_free():
    app = next(n for n in _graph("en") if n["@type"] == "SoftwareApplication")
    assert app["isAccessibleForFree"] is True
    assert app["offers"]["price"] == 0
    assert app["applicationCategory"] == "FinanceApplication"


# -------------------------------------------------------------------- robots


def test_robots_allows_the_landing_and_disallows_the_app():
    body = seo.robots_txt(BASE)
    assert "User-agent: *" in body
    # "/" cannot be blanket-disallowed: it is the landing for anyone without
    # the app cookie, which includes every crawler.
    assert "Allow: /$" in body
    for path in (PATH_ES, PATH_EN_ES, PATH_ES_US):
        assert f"Allow: {path}" in body
    for private in ("/portfolio", "/profile", "/import_transactions", "/legacy/"):
        assert f"Disallow: {private}" in body
    assert f"Sitemap: {BASE}/sitemap.xml" in body


def _robots_group(agent: str) -> list[str]:
    """The rules a crawler calling itself `agent` would apply."""
    # Consecutive User-agent lines share one group of rules (RFC 9309).
    out, active, in_agents = [], False, False
    for line in seo.robots_txt(BASE).splitlines():
        if line.lower().startswith("user-agent:"):
            name = line.split(":", 1)[1].strip()
            active = (active and in_agents) or name == agent
            in_agents = True
        elif line.strip():
            in_agents = False
            if active:
                out.append(line.strip())
        else:
            active, in_agents = False, False
    return out


def test_robots_never_disallows_the_landing_itself():
    # Scoped to the "*" group: the AI-crawler groups below it *do* say
    # "Disallow: /", and that is the point of them.
    assert "Disallow: /" not in _robots_group("*"), "would delist the landing page"


def test_ai_crawlers_are_turned_away_from_everything():
    for agent in seo.AI_CRAWLERS:
        assert _robots_group(agent) == ["Disallow: /"], agent


def test_a_search_crawler_is_still_welcome():
    # Google-Extended is the Gemini-training token and blocking it must not
    # touch Googlebot, which is what puts the landing in search results.
    assert "Google-Extended" in seo.AI_CRAWLERS
    assert "Googlebot" not in seo.AI_CRAWLERS
    assert "Applebot" not in seo.AI_CRAWLERS  # only Applebot-Extended is blocked
    assert _robots_group("Googlebot") == []  # falls through to the "*" group


# ------------------------------------------------------------------- sitemap


def test_sitemap_is_well_formed_and_lists_every_variant():
    xml = seo.sitemap_xml(BASE, lastmod="2026-08-31")
    root = ElementTree.fromstring(xml)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text for e in root.findall(".//s:loc", ns)]
    assert locs == [
        f"{BASE}/", f"{BASE}{PATH_ES}", f"{BASE}{PATH_EN_ES}", f"{BASE}{PATH_ES_US}",
        f"{BASE}{PATH_IT}",
    ]
    assert all(e.text == "2026-08-31" for e in root.findall(".//s:lastmod", ns))


def test_every_sitemap_url_carries_the_full_alternate_set():
    """Including itself — the spec requires the self-referencing xhtml:link."""
    xml = seo.sitemap_xml(BASE)
    root = ElementTree.fromstring(xml)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9",
          "xhtml": "http://www.w3.org/1999/xhtml"}
    for url in root.findall("s:url", ns):
        langs = {e.get("hreflang") for e in url.findall("xhtml:link", ns)}
        alone = url.find("s:loc", ns).text == f"{BASE}{PATH_IT}"
        assert langs == ({"it", "x-default"} if alone else {"en", "es", "x-default"})


def test_sitemap_without_a_lastmod_omits_the_element():
    assert "<lastmod>" not in seo.sitemap_xml(BASE)


def test_absolute_urls_have_no_double_slash():
    """A trailing slash on the base plus a leading slash on the path."""
    xml = seo.sitemap_xml(BASE + "/")
    assert not re.search(r"https://[^\"<]*//", xml)


def test_the_share_card_declares_its_type():
    # Slack and LinkedIn will skip an image they have to sniff.
    assert '<meta property="og:image:type" content="image/png">' in seo.head("en", BASE)


def test_robots_disallows_every_app_page_it_can_see():
    body = seo.robots_txt(BASE)
    for path in seo.app_page_paths():
        assert f"Disallow: {path}" in body
    for prefix in seo.APP_PREFIXES:
        assert f"Disallow: {prefix}" in body


def test_the_page_paths_track_the_navigation_table():
    paths = seo.app_page_paths()
    assert "/portfolio" in paths and "/ticker" in paths
    assert not any(p.startswith("/_") for p in paths)


# ------------------------------------------------------------ ticker share card


def test_a_ticker_card_names_the_symbol_and_fits_a_preview():
    title, tags = seo.ticker_head("NVDA", BASE, "en", name="NVIDIA Corporation")
    assert title == "NVDA · NVIDIA Corporation · TopStocks"
    assert len(title) <= 60
    assert f'property="og:title" content="{title}"' in tags
    assert f'property="og:url" content="{BASE}/ticker?ticker=NVDA"' in tags
    # Its own drawing (`og_image.ticker_png`), for a name the memo holds.
    assert f'property="og:image" content="{BASE}/og/ticker/NVDA.png"' in tags
    assert f'name="twitter:image" content="{BASE}/og/ticker/NVDA.png"' in tags
    assert 'property="og:image:alt" content="NVDA · NVIDIA Corporation"' in tags
    assert 'name="twitter:card" content="summary_large_image"' in tags
    description = re.search(r'name="description" content="([^"]*)"', tags).group(1)
    assert "NVDA" in description and "NVIDIA" in description
    assert len(description) <= 160


def test_a_ticker_card_without_a_name_is_the_symbol_in_the_readers_language():
    title, tags = seo.ticker_head("BTC-EUR", BASE, "es")
    assert title == "BTC-EUR · TopStocks"
    assert 'property="og:locale" content="es_ES"' in tags
    # No name, no drawing: the route would serve the landing's card anyway.
    assert f'property="og:image" content="{BASE}{seo.OG_IMAGE}"' in tags
    wanted = markup.esc(translate("ticker.seo_description", "es", name="BTC-EUR"))
    assert f'property="og:description" content="{wanted}"' in tags


@pytest.mark.parametrize("lang", sorted(LANGUAGES))
def test_the_longest_card_description_still_fits(lang):
    """A 32-character symbol and a name cut at NAME_MAX, in either language."""
    who = "X" * 32 + " · " + "N" * seo.NAME_MAX
    assert len(translate("ticker.seo_description", lang, name=who)) <= 160


def test_a_long_or_hostile_name_is_cut_and_escaped():
    title, tags = seo.ticker_head("X", BASE, "en", name="<b>" + "a" * 80)
    assert "<b>" not in tags and "&lt;b&gt;" in tags
    assert len(title) <= len("X · ") + seo.NAME_MAX + len(" · TopStocks")


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("nvda", "NVDA"),
        (" btc-eur ", "BTC-EUR"),
        ("BRK.B", "BRK.B"),
        ("^GSPC", "^GSPC"),
        ("EURUSD=X", "EURUSD=X"),
        ("", None),
        (None, None),
        ("<script>", None),
        ("NV DA", None),
        ("A" * 33, None),
    ],
)
def test_only_a_symbol_gets_a_card(raw, want):
    assert seo.ticker_symbol(raw) == want


def test_a_symbol_is_escaped_in_its_image_path():
    assert seo.ticker_image_path("^GSPC") == "/og/ticker/%5EGSPC.png"
    assert seo.ticker_image_path("EURUSD=X") == "/og/ticker/EURUSD%3DX.png"


def test_preview_bots_may_fetch_the_images_and_search_crawlers_not():
    assert f"Allow: {seo.OG_PREFIX}" in _robots_group("Slackbot")
    assert f"Disallow: {seo.OG_PREFIX}" in _robots_group("*")


def test_a_shared_answer_card_says_who_asked_in_the_language_they_asked_in():
    """The question titles it; the description names the sharer and the app
    before the answer, in the share's language whatever the crawler sent."""
    share = {"id": "AbCdEfGh123", "question": "¿Vendo NVDA?", "by": "Ana",
             "lang": "es", "content": "**Sí**: con ••• € de ganancia. " * 20}
    title, tags = seo.share_head(share, BASE, "en")
    assert title == "¿Vendo NVDA? · TopStocks"
    description = re.search(r'property="og:description" content="([^"]*)"', tags).group(1)
    assert description.startswith("Ana se lo preguntó a la IA de TopStocks: Sí: con")
    assert len(html.unescape(description)) <= seo.SHARE_DESCRIPTION_MAX
    assert 'property="og:locale" content="es_ES"' in tags
    # A re-share of the canonical URL is still counted as a share.
    assert ('property="og:url" content="https://topstocks.example/'
            '?share=AbCdEfGh123&amp;src=share"') in tags

    # The picture is the answer's own, named by the same id.
    assert ('property="og:image" content="https://topstocks.example/'
            'og/share/AbCdEfGh123.png"') in tags
    assert ('property="og:image:alt" content="Ana se lo preguntó a la IA de '
            'TopStocks: ¿Vendo NVDA?"') in tags

    _, tags = seo.share_head({**share, "by": "", "lang": ""}, BASE, "en")
    assert 'content="TopStocks&#x27; AI answers: Sí' in tags


def test_a_shared_list_card_names_the_list_and_its_symbols():
    share = {"id": "AbCdEfGh123", "kind": "watchlist", "title": "Semis",
             "tickers": ["NVDA", "ASML"], "by": "Ana", "lang": "es"}
    title, tags = seo.share_head(share, BASE, "en")
    assert title == "Semis · TopStocks"
    description = re.search(r'property="og:description" content="([^"]*)"', tags).group(1)
    assert html.unescape(description) == (
        "Ana ha compartido una lista en TopStocks: NVDA, ASML")
    untitled, tags = seo.share_head({**share, "title": "", "by": ""}, BASE, "en")
    assert untitled == "NVDA, ASML · TopStocks"
    assert "Una lista en TopStocks: NVDA, ASML" in html.unescape(tags)
