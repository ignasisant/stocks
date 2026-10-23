"""The SEO audit, pinned: what a crawler sees when it asks the running server.

`test_seo.py` checks the generators one at a time. This file checks the served
result, per landing variant and through the real gate and routes, for the
properties an audit looks at and nothing else would notice breaking: the
hreflang set reciprocates, nothing indexable is noindex (and nothing private is
indexable), robots.txt covers every route the app owns, the sitemap lists what
is served and only that, and the markup has none of the cheap mobile
Core Web Vitals traps. Field numbers (LCP, CLS, INP on a real phone) cannot be
asserted here; these are the regressions visible in the markup.
"""

import json
import re
import struct
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pytest
from starlette.testclient import TestClient

from stocks.web import landing, landing_static, markup, seo, server

BASE = "https://topstocks.example"
VARIANTS = sorted(landing.VARIANTS.items())  # [((lang, jur), path), ...]
IDS = [path for _, path in VARIANTS]


@pytest.fixture(autouse=True)
def _fresh_cache():
    landing_static.document.cache_clear()
    yield
    landing_static.document.cache_clear()


@pytest.fixture
def client(monkeypatch):
    landing_static.document.cache_clear()
    server._gzipped.cache_clear()
    monkeypatch.setattr(server, "secret", lambda *a, **k: "")
    return TestClient(server.app, base_url=BASE)


class _Doc(HTMLParser):
    """The tags an audit reads, collected in document order."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.in_head = False
        self.noscript = 0
        self.head_tags: list[tuple[str, dict[str, str | None]]] = []
        self.feed(html)

    def handle_endtag(self, tag):
        if tag == "noscript":
            self.noscript -= 1

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "noscript":
            self.noscript += 1
        elif self.noscript:
            return  # the no-JavaScript fallback is not what a browser renders
        self.tags.append((tag, a))
        if tag == "head":
            self.in_head = True
        elif tag == "body":
            self.in_head = False
        elif self.in_head:
            self.head_tags.append((tag, a))

    def find(self, tag: str, **where: str) -> list[dict[str, str | None]]:
        return [
            a
            for t, a in self.tags
            if t == tag and all(a.get(k) == v for k, v in where.items())
        ]

    def meta(self, key: str, value: str) -> str:
        (m,) = self.find("meta", **{key: value})
        return m["content"] or ""


def _doc(code: str, jur: str) -> tuple[str, _Doc]:
    html = landing_static.document(code, BASE, jur)
    return html, _Doc(html)


def _hreflangs(doc: _Doc) -> dict[str, str]:
    return {
        a["hreflang"]: a["href"]
        for a in doc.find("link", rel="alternate")
        if a.get("hreflang")
    }


# ------------------------------------------------------------- the document


@pytest.mark.parametrize(("variant", "path"), VARIANTS, ids=IDS)
def test_html_lang_matches_the_variants_language(variant, path):
    code, jur = variant
    html, doc = _doc(code, jur)
    assert re.match(rf'<!doctype html><html lang="{code}">', html)
    assert doc.meta("property", "og:locale").split("_")[0] == code
    other = {"en_US", "es_ES"} - {doc.meta("property", "og:locale")}
    alts = {a["content"] for a in doc.find("meta", property="og:locale:alternate")}
    assert alts == other


@pytest.mark.parametrize(("variant", "path"), VARIANTS, ids=IDS)
def test_canonical_is_absolute_self_referencing_and_matches_og_url(variant, path):
    code, jur = variant
    _, doc = _doc(code, jur)
    (canonical,) = doc.find("link", rel="canonical")
    assert canonical["href"] == f"{BASE}{path}"
    assert doc.meta("property", "og:url") == canonical["href"]


@pytest.mark.parametrize(("variant", "path"), VARIANTS, ids=IDS)
def test_the_landing_is_indexable(variant, path):
    code, jur = variant
    _, doc = _doc(code, jur)
    robots = doc.meta("name", "robots").lower()
    assert "noindex" not in robots and "nofollow" not in robots
    assert robots.startswith("index")


def test_every_variant_has_its_own_title_and_description():
    titles, descriptions = {}, {}
    for (code, jur), path in VARIANTS:
        html, doc = _doc(code, jur)
        title = re.search(r"<title>(.*?)</title>", html).group(1)
        assert 10 <= len(title) <= 60, path
        description = doc.meta("name", "description")
        assert 70 <= len(description) <= 160, path
        assert doc.meta("property", "og:title") == title
        assert doc.meta("property", "og:description") == description
        titles.setdefault(title, []).append(path)
        descriptions.setdefault(description, []).append(path)
    assert all(len(v) == 1 for v in titles.values()), titles
    assert all(len(v) == 1 for v in descriptions.values()), descriptions


@pytest.mark.parametrize(("variant", "path"), VARIANTS, ids=IDS)
def test_one_h1_and_no_skipped_heading_levels(variant, path):
    code, jur = variant
    _, doc = _doc(code, jur)
    levels = [int(t[1]) for t, _ in doc.tags if re.fullmatch(r"h[1-6]", t)]
    assert levels.count(1) == 1
    assert levels[0] == 1
    assert all(b - a <= 1 for a, b in zip(levels, levels[1:], strict=False))


@pytest.mark.parametrize(("variant", "path"), VARIANTS, ids=IDS)
def test_every_image_has_alt_and_dimensions(variant, path):
    code, jur = variant
    _, doc = _doc(code, jur)
    imgs = [a for t, a in doc.tags if t == "img"]
    assert imgs, "the brand mark is an <img>"
    for img in imgs:
        assert img.get("alt"), img
        # width/height reserve the box before the file lands (no layout shift).
        assert (img.get("width") or "").isdigit(), img
        assert (img.get("height") or "").isdigit(), img


@pytest.mark.parametrize(("variant", "path"), VARIANTS, ids=IDS)
def test_structured_data_is_valid_and_points_at_this_page(variant, path):
    code, jur = variant
    _, doc = _doc(code, jur)
    html = landing_static.document(code, BASE, jur)
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert len(blocks) == 1
    data = json.loads(blocks[0])
    assert data["@context"] == "https://schema.org"
    kinds = {n["@type"] for n in data["@graph"]}
    assert kinds == {"WebSite", "SoftwareApplication", "FAQPage"}
    ids = [n["@id"] for n in data["@graph"]]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith(f"{BASE}{path}#") for i in ids)
    site = next(n for n in data["@graph"] if n["@type"] == "WebSite")
    assert site["inLanguage"] == code
    for n in data["@graph"]:
        for key in ("url", "image", "codeRepository"):
            if key in n:
                assert n[key].startswith("https://"), (key, n[key])


# ----------------------------------------------------------------- hreflang


@pytest.mark.parametrize(("variant", "path"), VARIANTS, ids=IDS)
def test_hreflang_is_absolute_complete_and_reciprocal(variant, path):
    code, jur = variant
    _, doc = _doc(code, jur)
    mine = _hreflangs(doc)
    assert set(mine) == {"en", "es", "x-default"}
    assert all(h.startswith(BASE + "/") for h in mine.values())
    assert mine[code] == f"{BASE}{path}", "a page lists itself"
    assert mine["x-default"] == mine["en"]
    # Every alternate must declare this page back with the same set, or search
    # engines discard the pair.
    by_url = {f"{BASE}{p}": k for k, p in landing.VARIANTS.items()}
    for target in set(mine.values()):
        tcode, tjur = by_url[target]
        assert _hreflangs(_doc(tcode, tjur)[1]) == mine, target


# ------------------------------------------------------------- Core Web Vitals


@pytest.mark.parametrize(("variant", "path"), VARIANTS, ids=IDS)
def test_nothing_in_the_head_blocks_rendering_except_inline_css(variant, path):
    code, jur = variant
    html, doc = _doc(code, jur)
    for tag, a in doc.head_tags:
        if tag == "script":
            assert not a.get("src"), "no external script in the head"
        if tag == "link" and a.get("rel") == "stylesheet":
            # The only external sheet is the webfont one, and only as the
            # non-blocking media="print" swap.
            assert a.get("href") == seo.FONTS_HREF
            # No inline handler: the page's CSP refuses one, a hashed script
            # flips the media instead.
            assert a.get("media") == "print" and "onload" not in a
    # And nothing outside the head pulls an external script or sheet either.
    assert not [a for t, a in doc.tags if t == "script" and a.get("src")]
    # The no-JavaScript fallback is the blocking copy, kept for crawlers.
    assert (
        f'<noscript><link rel="stylesheet" href="{markup.esc(seo.FONTS_HREF)}">' in html
    )


def test_the_webfont_stylesheet_swaps_and_is_preconnected():
    assert "display=swap" in seo.FONTS_HREF
    _, doc = _doc("en", "US")
    origins = {a["href"] for a in doc.find("link", rel="preconnect")}
    assert origins == {"https://fonts.googleapis.com", "https://fonts.gstatic.com"}
    (gstatic,) = doc.find("link", rel="preconnect", href="https://fonts.gstatic.com")
    assert "crossorigin" in gstatic


def test_no_font_face_blocks_text_for_long():
    html = landing_static.document("en", BASE, "US")
    for face in re.findall(r"@font-face\s*{[^}]*}", html):
        assert re.search(r"font-display:\s*(swap|optional|fallback)", face), face


def test_the_viewport_is_responsive_and_does_not_forbid_zoom():
    _, doc = _doc("en", "US")
    viewport = doc.meta("name", "viewport")
    assert "width=device-width" in viewport and "initial-scale=1" in viewport
    assert "user-scalable=no" not in viewport and "maximum-scale" not in viewport


def test_the_share_card_is_the_size_it_declares():
    png = (Path(seo.__file__).parent / "assets" / "og.png").read_bytes()
    w, h = struct.unpack(">II", png[16:24])
    assert (w, h) == (seo.OG_IMAGE_W, seo.OG_IMAGE_H)
    assert len(png) < 300_000, "WhatsApp drops share cards past ~300 KB"


# ------------------------------------------------------- served, end to end


@pytest.mark.parametrize("path", IDS)
def test_served_landing_is_200_html_and_not_noindexed(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "x-robots-tag" not in r.headers
    assert 'name="robots" content="index' in r.text


def test_served_app_shell_is_noindex(client):
    for path in ("/portfolio", "/home", "/review", "/ticker?ticker=AAPL"):
        r = client.get(path, follow_redirects=False)
        assert "noindex" in r.headers.get("x-robots-tag", ""), path


def test_legal_pages_are_noindex_and_not_in_the_sitemap(client):
    r = client.get("/legal/privacy")
    assert 'content="noindex"' in r.text
    assert "/legal/" not in client.get("/sitemap.xml").text


def test_sitemap_lists_exactly_the_served_landing_variants(client):
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    tree = ElementTree.fromstring(client.get("/sitemap.xml").content)
    locs = [e.text for e in tree.findall("s:url/s:loc", ns)]
    assert sorted(locs) == sorted(f"{BASE}{p}" for p in landing.LANDING_PATHS)
    assert {loc.split("/")[2] for loc in locs} == {"topstocks.example"}
    # The two languages are both present.
    assert f"{BASE}/" in locs and f"{BASE}{landing.PATH_ES}" in locs
    # No private route, and no query string, slips in.
    for loc in locs:
        assert "?" not in loc
        path = loc.removeprefix(BASE)
        assert path in landing.LANDING_PATHS
        assert not _blocked_for_search(path), path


def test_sitemap_alternates_match_the_pages_own_hreflang(client):
    ns = {
        "s": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "x": "http://www.w3.org/1999/xhtml",
    }
    tree = ElementTree.fromstring(client.get("/sitemap.xml").content)
    by_url = {f"{BASE}{p}": k for k, p in landing.VARIANTS.items()}
    for url in tree.findall("s:url", ns):
        loc = url.find("s:loc", ns).text
        listed = {a.get("hreflang"): a.get("href") for a in url.findall("x:link", ns)}
        code, jur = by_url[loc]
        assert listed == _hreflangs(_doc(code, jur)[1]), loc


def _group(agent: str) -> list[tuple[str, str]]:
    """(directive, path) rules a crawler named `agent` applies, per RFC 9309."""
    rules, active, in_agents = [], False, False
    for line in seo.robots_txt(BASE).splitlines():
        if line.lower().startswith("user-agent:"):
            name = line.split(":", 1)[1].strip()
            active = (active and in_agents) or name == agent
            in_agents = True
        elif line.strip():
            in_agents = False
            if active:
                key, _, value = line.partition(":")
                rules.append((key.strip().lower(), value.strip()))
        else:
            active, in_agents = False, False
    return rules


def _blocked(agent: str, path: str) -> bool:
    """Longest matching rule wins, Allow beating Disallow on a tie."""
    best = (-1, False)
    for key, pattern in _group(agent):
        if key not in ("allow", "disallow") or not pattern:
            continue
        end = pattern.endswith("$")
        pat = pattern.rstrip("$")
        if (path == pat) if end else path.startswith(pat):
            if len(pattern) > best[0] or (len(pattern) == best[0] and key == "allow"):
                best = (len(pattern), key == "disallow")
    return best[1] if best[0] >= 0 else False


def _blocked_for_search(path: str) -> bool:
    return _blocked("*", path)


def test_robots_blocks_search_crawlers_from_the_app_only():
    for path in ("/", *landing.LANDING_PATHS, "/lp/og.png", "/lp/manifest.webmanifest"):
        assert not _blocked_for_search(path), path
    for path in ("/portfolio", "/ticker?ticker=AAPL", "/api/v1/me", "/mcp", "/token"):
        assert _blocked_for_search(path), path


def _public(path: str) -> bool:
    """Routes that are documents or probes meant for everyone."""
    return (
        server._is_marketing_path(path)
        or path + "/" in landing.LANDING_PATHS
        or path.startswith("/.well-known/")
    )


def test_robots_covers_every_route_the_app_owns():
    """A route added to server.py is either public on purpose or disallowed."""
    missing = []
    for route in server.routes:
        path = route.path.split("{")[0]
        if path == "/" or _public(path):
            continue
        if not (_blocked_for_search(path) or _blocked_for_search(path + "/")):
            missing.append(route.path)
    assert not missing, f"served but crawlable and not marketing: {missing}"


def test_link_preview_bots_can_fetch_the_ticker_card_but_not_the_rest():
    for agent in seo.PREVIEW_BOTS:
        assert not _blocked(agent, "/ticker?ticker=AAPL"), agent
        assert not _blocked(agent, "/"), agent
        assert _blocked(agent, "/portfolio"), agent
        assert _blocked(agent, "/api/v1/me"), agent
    # Search crawlers still may not.
    assert _blocked("*", "/ticker?ticker=AAPL")
