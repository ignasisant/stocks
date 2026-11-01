"""The Spanish-tax lessons as public, indexable pages: `/es/guias/`, `/guides/`.

The Learn page (`stocks.learn`) is a page of the app, and the app is a
JavaScript shell kept out of search indexes. Its tax path is also exactly what
somebody types into a search box in April — "cómo declarar Revolut", "regla de
los dos meses" — so the same files are served here a second time, as plain
documents a crawler reads in full: one page per lesson per language, an index
per language, and a sitemap entry for each (`sitemap_pages`).

Same delivery as `legal`: built from constants, cached, inline CSS hashed into
the page's own CSP, no font request. Only the paths in `PUBLIC` are served; a
path joins once each of its lessons carries a `slug` and a `description` in
every language (`tests/test_guides.py` holds that).

The body is the lesson's markdown, in the subset the files use: `##`
headings, paragraphs, `-` lists, `**bold**` and `*italic*`. Everything is
escaped first, so a stray `<` in a lesson is text, never markup.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from stocks import learn
from stocks.web import csp
from stocks.web.i18n import translate
from stocks.web.landing import (
    ASSET_BASE,
    PATH_EN,
    PATH_ES,
    PATH_GUIDES_EN,
    PATH_GUIDES_ES,
)
from stocks.web.markup import esc

# Where each language's guides live. The Spanish ones sit under the Spanish
# landing's `/es/`, which the gate and robots.txt already treat as public.
PATHS = {"en": PATH_GUIDES_EN, "es": PATH_GUIDES_ES}

# The learn paths published here: the tax path is the one people search for.
PUBLIC = ("tax-es",)

# Where an unmatched locale lands: these guides are written for Spanish
# residents first, so the Spanish page is the source.
X_DEFAULT = "es"

TITLE_MAX = 60
DESCRIPTION_MAX = 160

_UI = {
    "en": {
        "index_title": "Spanish tax guides for investors",
        "index_body": "Short guides to declaring shares, ETFs and dividends "
                      "on a Spanish tax return, with worked examples in euros.",
        "home": "Guides",
        "reviewed": "Reviewed",
        "minutes": "{n} min read",
        "related": "More guides",
        "cta_title": "Let TopStocks do the sums",
        "cta_body": "Import your broker's statement and it works out FIFO, "
                    "each trade in euros and the two-month rule for you.",
        "cta_guest": "Try it with sample data",
        "cta_signin": "Sign in with Google",
        "other_lang": "Leer en español",
    },
    "es": {
        "index_title": "Guías de fiscalidad para inversores en España",
        "index_body": "Guías cortas para declarar acciones, ETF y dividendos "
                      "en la renta, con ejemplos en euros.",
        "home": "Guías",
        "reviewed": "Revisado",
        "minutes": "{n} min de lectura",
        "related": "Más guías",
        "cta_title": "Deja que TopStocks haga las cuentas",
        "cta_body": "Importa el extracto de tu bróker y calcula FIFO, cada "
                    "operación en euros y la regla de los dos meses.",
        "cta_guest": "Probar con datos de ejemplo",
        "cta_signin": "Entrar con Google",
        "other_lang": "Read in English",
    },
}

# The legal pages' dark surface, plus a reading measure and the CTA box.
_CSS = """
:root { color-scheme: dark; }
body { margin: 0; background: #18161C; color: #E8E5EF;
       font: 17px/1.7 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 42rem; margin: 0 auto; padding: 2.5rem 1rem 4rem; }
.crumbs { font-size: 0.85rem; color: #8E88A0; margin: 0 0 1.5rem; }
h1 { font-size: 1.8rem; line-height: 1.25; margin: 0 0 0.5rem; }
h2 { font-size: 1.2rem; margin: 2.2rem 0 0.5rem; }
p, li { color: #C9C4D4; }
p { margin: 0.7rem 0; }
ul { padding-left: 1.3rem; }
li { margin: 0.35rem 0; }
strong { color: #E8E5EF; }
a { color: #9AD1FF; }
a:focus-visible { outline: 2px solid #9AD1FF; outline-offset: 2px; }
.meta { color: #8E88A0; font-size: 0.85rem; margin: 0 0 1.5rem; }
.cta { margin: 2.5rem 0; padding: 1.25rem; border: 1px solid #2C2933;
       border-radius: 12px; background: #201E26; }
.cta h2 { margin-top: 0; }
.cta .go { display: flex; gap: 0.75rem 1.25rem; flex-wrap: wrap;
           align-items: center; margin-top: 1rem; }
.cta .main { background: #9AD1FF; color: #18161C; font-weight: 600;
             padding: 0.6rem 1rem; border-radius: 8px; text-decoration: none; }
.list { list-style: none; padding: 0; }
.list li { margin: 0 0 1.25rem; }
.list a { font-weight: 600; }
.list p { margin: 0.2rem 0 0; font-size: 0.95rem; }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #2C2933;
         font-size: 0.85rem; color: #8E88A0; }
footer nav { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
@media (pointer: coarse) {
  footer nav a, .cta a { display: inline-flex; align-items: center;
                         min-height: 44px; }
}
"""


def _lang(lang: str | None) -> str:
    return lang if lang in PATHS else "en"


def lesson_ids() -> tuple[str, ...]:
    """Every published lesson, in the order its path lists it."""
    return tuple(i for p in learn.paths() if p.id in PUBLIC for i in p.lessons)


def href(lesson_id: str, lang: str) -> str:
    """The lesson's public path in `lang`."""
    lesson = learn.lesson(lesson_id, lang)
    assert lesson is not None, lesson_id
    return f"{PATHS[_lang(lang)]}{lesson.slug}"


def find(slug: str, lang: str) -> learn.Lesson | None:
    """The published lesson at `slug` in `lang`, or None."""
    lesson = learn.by_slug(slug, _lang(lang))
    return lesson if lesson is not None and lesson.id in lesson_ids() else None


def _alternates(lesson_id: str | None) -> dict[str, str]:
    """hreflang → path for a lesson (or for the index when None)."""
    out = {
        code: href(lesson_id, code) if lesson_id else path
        for code, path in PATHS.items()
    }
    return {**out, "x-default": out[X_DEFAULT]}


# ------------------------------------------------------------------ markdown

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"\*(.+?)\*")


def _inline(text: str) -> str:
    out = esc(text)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    return _ITALIC.sub(r"<em>\1</em>", out)


def _plain(text: str) -> str:
    return text.replace("**", "").replace("*", "")


def render_body(md: str) -> str:
    """The lesson body as HTML: headings, paragraphs and lists, escaped."""
    html: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if para:
            html.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if items:
            lis = "".join(f"<li>{_inline(i)}</li>" for i in items)
            html.append(f"<ul>{lis}</ul>")
            items.clear()

    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("## "):
            flush()
            html.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("- "):
            if para:
                flush()
            items.append(line[2:])
        else:
            if items:
                flush()
            para.append(line)
    flush()
    return "".join(html)


def description(lesson: learn.Lesson) -> str:
    """The search-result line: the file's own, or the opening paragraph cut."""
    if lesson.description:
        return lesson.description
    first = _plain(lesson.body.split("\n\n", 1)[0].replace("\n", " "))
    if len(first) <= DESCRIPTION_MAX:
        return first
    return first[: DESCRIPTION_MAX - 1].rsplit(" ", 1)[0] + "…"


def page_title(title: str) -> str:
    """`<title>`: the site name only when it still fits a result line."""
    full = f"{title} · TopStocks"
    return full if len(full) <= TITLE_MAX else title


# ------------------------------------------------------------------ document

def _abs(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _json_ld(data: list[dict]) -> str:
    # `<` escaped so no string in the data can close the script block.
    text = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/ld+json">{text}</script>'


def _app_href(page: str, lang: str, src: str, *, signin: bool = False) -> str:
    """A CTA into the app: the lesson's page as a guest, or the sign-in."""
    tail = ("&lang=es" if lang == "es" else "") + f"&src={src}"
    if signin:
        return f"/?signin=1{tail}"
    sep = "&" if "?" in page else "?"
    return f"/{page}{sep}guest=1{tail}"


def _cta(lang: str, app: str, src: str) -> str:
    ui = _UI[lang]
    guest = esc(_app_href(app or "portfolio", lang, src))
    signin = esc(_app_href("", lang, src, signin=True))
    return (
        '<aside class="cta">'
        f"<h2>{esc(ui['cta_title'])}</h2><p>{esc(ui['cta_body'])}</p>"
        '<div class="go">'
        f'<a class="main" href="{guest}">{esc(ui["cta_guest"])}</a>'
        f'<a href="{signin}">{esc(ui["cta_signin"])}</a>'
        "</div></aside>"
    )


def _document(
    lang: str, base_url: str, *, title: str, desc: str, main: str,
    alternates: dict[str, str], og_type: str, ld: list[dict],
) -> str:
    canonical = _abs(base_url, alternates[lang])
    links = "".join(
        f'<link rel="alternate" hreflang="{code}" href="{esc(_abs(base_url, p))}">'
        for code, p in alternates.items()
    )
    other = "en" if lang == "es" else "es"
    legal_q = "?lang=es" if lang == "es" else ""
    home = PATH_ES if lang == "es" else PATH_EN
    og_image = f"{ASSET_BASE}og.png"

    def tr(key: str) -> str:
        return translate(key, lang)

    return (
        "<!doctype html>"
        f'<html lang="{lang}"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" '
        'content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<meta name="theme-color" content="#18161C">'
        f"<title>{esc(page_title(title))}</title>"
        f'<meta name="description" content="{esc(desc)}">'
        f'<link rel="canonical" href="{esc(canonical)}">{links}'
        f'<link rel="icon" href="{ASSET_BASE}topstocks-icon.svg" type="image/svg+xml">'
        f'<link rel="icon" href="{ASSET_BASE}icon-192.png" type="image/png"'
        ' sizes="192x192">'
        f'<meta property="og:type" content="{og_type}">'
        f'<meta property="og:title" content="{esc(title)}">'
        f'<meta property="og:description" content="{esc(desc)}">'
        f'<meta property="og:url" content="{esc(canonical)}">'
        '<meta property="og:site_name" content="TopStocks">'
        f'<meta property="og:locale" content="{"es_ES" if lang == "es" else "en_US"}">'
        f'<meta property="og:image" content="{esc(_abs(base_url, og_image))}">'
        '<meta name="twitter:card" content="summary_large_image">'
        f"{_json_ld(ld)}"
        f"<style>{_CSS}</style>"
        "</head><body><main>"
        f"{main}"
        "<footer><nav>"
        f'<a href="{home}">TopStocks</a>'
        f'<a href="{esc(alternates[other])}" hreflang="{other}">'
        f'{esc(_UI[lang]["other_lang"])}</a>'
        f'<a href="/legal/privacy{legal_q}">{esc(tr("landing.footer_privacy"))}</a>'
        f'<a href="/legal/terms{legal_q}">{esc(tr("landing.footer_terms"))}</a>'
        "</nav>"
        f"<p>{esc(tr('landing.footer_disclaimer'))}</p>"
        "</footer></main></body></html>"
    )


def _crumbs(lang: str, base_url: str, lesson: learn.Lesson | None) -> tuple[str, dict]:
    """The visible trail and its BreadcrumbList."""
    ui = _UI[lang]
    trail = [("TopStocks", PATH_ES if lang == "es" else PATH_EN),
             (ui["home"], PATHS[lang])]
    if lesson is not None:
        trail.append((lesson.title, href(lesson.id, lang)))
    html = " › ".join(
        f'<a href="{esc(p)}">{esc(name)}</a>' for name, p in trail[:-1]
    )
    ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": n, "name": name,
             "item": _abs(base_url, p)}
            for n, (name, p) in enumerate(trail, 1)
        ],
    }
    return f'<p class="crumbs">{html}</p>', ld


@lru_cache(maxsize=64)
def page(lesson_id: str, lang: str, base_url: str) -> str:
    """One lesson's public page."""
    lang = _lang(lang)
    lesson = learn.lesson(lesson_id, lang)
    assert lesson is not None and lesson_id in lesson_ids(), lesson_id
    ui = _UI[lang]
    desc = description(lesson)
    crumbs, crumbs_ld = _crumbs(lang, base_url, lesson)
    related = [
        learn.lesson(i, lang) for i in lesson_ids() if i != lesson_id
    ]
    main = (
        f"{crumbs}<article>"
        f"<h1>{esc(lesson.title)}</h1>"
        f'<p class="meta">{esc(ui["reviewed"])}: '
        f'<time datetime="{esc(lesson.as_of)}">{esc(lesson.as_of)}</time>'
        f" · {esc(ui['minutes'].format(n=lesson.minutes))}</p>"
        f"{render_body(lesson.body)}"
        "</article>"
        f"{_cta(lang, lesson.app, f'guide-{lesson.id}'[:32])}"
        f"<h2>{esc(ui['related'])}</h2>"
        '<ul class="list">'
        + "".join(
            f'<li><a href="{esc(href(x.id, lang))}">{esc(x.title)}</a></li>'
            for x in related if x is not None
        )
        + "</ul>"
    )
    article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": lesson.title,
        "description": desc,
        "inLanguage": lang,
        "dateModified": lesson.as_of,
        "mainEntityOfPage": _abs(base_url, href(lesson.id, lang)),
        "publisher": {"@type": "Organization", "name": "TopStocks"},
    }
    return _document(
        lang, base_url, title=lesson.title, desc=desc, main=main,
        alternates=_alternates(lesson_id), og_type="article",
        ld=[article, crumbs_ld],
    )


@lru_cache(maxsize=8)
def index(lang: str, base_url: str) -> str:
    """The language's list of guides."""
    lang = _lang(lang)
    ui = _UI[lang]
    crumbs, crumbs_ld = _crumbs(lang, base_url, None)
    items = "".join(
        f'<li><a href="{esc(href(x.id, lang))}">{esc(x.title)}</a>'
        f"<p>{esc(description(x))}</p></li>"
        for i in lesson_ids()
        if (x := learn.lesson(i, lang)) is not None
    )
    main = (
        f"{crumbs}<h1>{esc(ui['index_title'])}</h1>"
        f"<p>{esc(ui['index_body'])}</p>"
        f'<ul class="list">{items}</ul>'
        f"{_cta(lang, 'portfolio?tab=tax', 'guide-index')}"
    )
    return _document(
        lang, base_url, title=ui["index_title"], desc=ui["index_body"],
        main=main, alternates=_alternates(None), og_type="website",
        ld=[crumbs_ld],
    )


@lru_cache(maxsize=128)
def policy(document: str) -> str:
    """The CSP header for a document built here: its own blocks, no fonts."""
    return csp.for_document(document, fonts=False)


def sitemap_pages() -> list[tuple[str, dict[str, str], str]]:
    """(path, hreflang alternates, lastmod) for every guide page and index."""
    newest = max(
        (x.as_of for i in lesson_ids() for lang in PATHS
         if (x := learn.lesson(i, lang)) is not None),
        default="",
    )
    out = [(PATHS[lang], _alternates(None), newest) for lang in PATHS]
    for i in lesson_ids():
        alts = _alternates(i)
        for lang in PATHS:
            lesson = learn.lesson(i, lang)
            out.append((alts[lang], alts, lesson.as_of if lesson else ""))
    return out
