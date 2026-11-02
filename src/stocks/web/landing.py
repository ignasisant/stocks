"""Marketing landing page — the first thing an anonymous visitor sees.

Ported from the Claude Design canvas file `Aguait Landing.dc.html`. This module
owns only the *markup*: `landing_static` wraps these sections in a standalone
HTML document (head, SEO tags, JSON-LD) that `server.py` serves at `/` and
`/es/` straight from Starlette, with no script of the app's own to wait for.
That is what makes the page crawlable and instant; the app itself starts at
the first CTA click.

Two things shape how this is written:

* **The CTAs are links, not buttons.** A designed landing puts its calls to
  action inside flex rows, sticky bars and centred hero blocks; a static page
  has no widget layer to put a button in anyway. Every CTA is an anchor
  carrying a query parameter, and any query parameter on `/` is what tells
  `server.py` to hand the request to the app instead of the landing —
  `?signin=1` is taken by `server.LandingGate`, which bounces the visitor
  into the app's own sign-in, `?guest=1` drops them straight into the app
  as a guest.
* **Phones get a fixed CTA bar, not a squeezed header.** The page is very
  long, so the sign-in call to action leaves the top bar on narrow viewports
  and reappears as a fixed bottom bar (`.ag-l-mbar`) that follows the reader
  down. Everything else is width-driven CSS — see `MOBILE_RULES`.
* **No raw colour literals.** Everything reads `var(--ag-*)` from
  `ds.ds_vars_css()`, which `landing_static` inlines into the document
  head. Tints the tokens don't ship are derived with `color-mix()` rather than
  hard-coded rgba, so the palette stays single-source.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from stocks.portfolio import tax
from stocks.web.i18n import DEFAULT_LANG, LANGUAGES, has, translate
from stocks.web.landing_css import CSS, MOBILE_RULES, TINY_CSS
from stocks.web.markup import esc

# Query parameters the in-page anchors set. Read by `server.LandingGate` and
# `server._entry_kind`.
PARAM_SIGNIN = "signin"
PARAM_GUEST = "guest"

# Browser paths this module hard-codes: the language pair the sections link
# between, and the asset mount server.py serves the brand mark from. Absolute,
# because /es/ is one segment deeper than / and a relative logo URL would
# resolve against the wrong directory there.
PATH_EN = "/"
PATH_ES = "/es/"
# Language and tax residence are independent: an English-reading filer in Spain
# and a Spanish-reading filer in the US both exist, and the pitch is a
# country's case, so each combination is its own indexable page rather than a
# query parameter (any query parameter on `/` is what hands the request to the
# app). The two defaults keep their short URLs; the cross pairs are explicit.
PATH_EN_ES = "/en-es/"  # English copy, Spanish rules
PATH_ES_US = "/es-us/"  # Spanish copy, US rules
ASSET_BASE = "/lp/"
# The public Spanish-tax guides (`web/guides.py`), one index per language.
PATH_GUIDES_EN = "/guides/"
PATH_GUIDES_ES = "/es/guias/"

# The language this render is for. A ContextVar rather than an argument because
# every section below reads it through tr() — threading a code through fifteen
# builders to reach a dict lookup would be all noise. Set by render_language().
_LANG: ContextVar[str] = ContextVar("landing_lang", default=DEFAULT_LANG)

# The tax jurisdiction this render argues from. The page makes a *country's*
# case — the euro basis and the two-month rule, or the USD basis and the wash
# sale — so it follows the reader's language rather than a separate control:
# an anonymous visitor has no profile to read a tax residence from, and a
# fourth landing variant per language pair would be four indexed pages arguing
# past each other. The language toggle switches both, and `render_language`
# takes an explicit override for the day that stops being true.
JURISDICTION_BY_LANG = {"en": "US", "es": "ES"}
# Unset rather than defaulting to one country: outside a render (seo.py called
# directly, a test) the right jurisdiction is the language's own, not Spain's.
_JUR: ContextVar[str | None] = ContextVar("landing_jur", default=None)

# (language, jurisdiction) -> the one URL that serves it. Two pages became four
# when the copy split by country; the pairs a language defaults to keep the
# short paths so nothing already indexed moves.
VARIANTS: dict[tuple[str, str], str] = {
    ("en", "US"): PATH_EN,
    ("es", "ES"): PATH_ES,
    ("en", "ES"): PATH_EN_ES,
    ("es", "US"): PATH_ES_US,
}
LANDING_PATHS: tuple[str, ...] = tuple(VARIANTS.values())


def jurisdiction_for(lang: str) -> str:
    return tax.normalize(JURISDICTION_BY_LANG.get(lang, tax.DEFAULT_CODE))


def variant_path(lang: str, jurisdiction: str | None = None) -> str:
    """The URL serving `lang` under `jurisdiction` (its default if unset)."""
    code = lang if lang in LANGUAGES else DEFAULT_LANG
    jur = tax.normalize(jurisdiction or jurisdiction_for(code))
    return VARIANTS.get((code, jur), PATH_EN)


def variant_for(path: str) -> tuple[str, str] | None:
    """(language, jurisdiction) a landing path serves, or None if it isn't one.

    Accepts the path with or without its trailing slash, so the redirect that
    canonicalizes `/es` can ask about `/es` directly.
    """
    wanted = path if path.endswith("/") else f"{path}/"
    for (lang, jur), p in VARIANTS.items():
        if p == wanted or p.rstrip("/") == path.rstrip("/"):
            return lang, jur
    return None


@contextmanager
def render_language(lang: str, jurisdiction: str | None = None):
    """Render the sections in `lang`. Wraps every landing_static build."""
    code = lang if lang in LANGUAGES else DEFAULT_LANG
    lang_token = _LANG.set(code)
    jur_token = _JUR.set(tax.normalize(jurisdiction or jurisdiction_for(code)))
    try:
        yield
    finally:
        _JUR.reset(jur_token)
        _LANG.reset(lang_token)


def active_language() -> str:
    """The language this render is for, as `render_language()` set it."""
    return _LANG.get()


def active_jurisdiction() -> str:
    """The tax jurisdiction this render argues from ("ES", "US")."""
    return active_jurisdiction_for(active_language())


def active_jurisdiction_for(lang: str) -> str:
    """The render's jurisdiction, or the one `lang` defaults to outside one.

    seo.py takes its language as an argument rather than from the context (the
    cron and the tests call it directly), so it has to be able to ask "which
    country goes with *this* language" without a render in progress.
    """
    return _JUR.get() or jurisdiction_for(lang)


def jur_key(key: str, jurisdiction: str | None = None) -> str:
    """`landing.us_hero_title` when that copy exists, else `landing.hero_title`.

    Most of the page is country-neutral, so only the keys a jurisdiction
    actually disputes need an override — the rest fall through to one string
    per language. seo.py resolves through here too, so the title, description
    and FAQ rich result argue the same case as the page.
    """
    prefix = "landing."
    if not key.startswith(prefix):
        return key
    jur = jurisdiction or active_jurisdiction()
    scoped = f"{prefix}{jur.lower()}_{key[len(prefix):]}"
    return scoped if has(scoped) else key


def tr(key: str, /, **kwargs) -> str:
    """`i18n.t()` bound to the render language and jurisdiction."""
    return translate(jur_key(key), _LANG.get(), **kwargs)

# Illustrative figures for the product mocks. Plausible, obviously a sample —
# never presented as anyone's real book.
_BENCHMARK = "SPY"
_FISCAL_YEAR = 2026
_CHART_YEARS = ("2023", "2024", "2025", "2026")

# The public repository. One definition for the whole site: the top bar and
# footer links here, the "codeRepository" in seo.py's structured data, and the
# contact address the legal pages send people to. A stale owner slug here is a
# 404 on the one link that backs up the "read the source yourself" claim, so it
# is imported rather than retyped.
GITHUB_URL = "https://github.com/ignasisant/stocks"

# Q/A pairs in the FAQ section (landing.faq_q1..q8 / faq_a1..a8). `seo.py`
# reads the same range to emit the FAQPage structured data, so the rich result
# and the visible section can never drift apart.
FAQ_COUNT = 8

# Brokers the Import page actually parses (stocks.portfolio.platforms), in the
# order that page lists them. The last entry is the catch-all schema.
_BROKERS = (
    ("Revolut", "CSV · PDF", False),
    ("Revolut Crypto", "CSV", False),
    ("Trading 212", "CSV", False),
    ("DEGIRO", "CSV", False),
    ("Interactive Brokers", "CSV", False),
    ("ClickTrade / Saxo", "XLSX · CSV", False),
    (None, None, True),  # generic CSV — label comes from the catalog
)


# ------------------------------------------------------------------ numbers
# The mocks are the loudest part of the page, so they follow the reader's own
# conventions: "€48,230" and "+47.7%" in English, "48.230 €" and "+47,7 %" in
# Spanish. Kept local and tiny — the app's real formatters work off live frames
# and a display-currency preference neither of which exists on a landing page.


def _is_es() -> bool:
    return active_language() == "es"


def _group(digits: str) -> str:
    sep = "." if _is_es() else ","
    out, count = [], 0
    for ch in reversed(digits):
        if count and count % 3 == 0:
            out.append(sep)
        out.append(ch)
        count += 1
    return "".join(reversed(out))


def _symbol() -> str:
    """The currency the mocks are denominated in, per jurisdiction."""
    return "$" if tax.get(active_jurisdiction()).currency == "USD" else "€"


def _money(amount: int, *, signed: bool = False) -> str:
    sign = ""
    if signed:
        sign = "−" if amount < 0 else "+"
    body = _group(str(abs(amount)))
    sym = _symbol()
    return f"{sign}{body} {sym}" if _is_es() else f"{sign}{sym}{body}"


def _plain(amount: int, *, signed: bool = False) -> str:
    """A bare grouped figure — for table cells that already have a € header."""
    sign = ("−" if amount < 0 else "+") if signed else ""
    return f"{sign}{_group(str(abs(amount)))}"


def _pct(value: float, *, signed: bool = True) -> str:
    sign = ("−" if value < 0 else "+") if signed else ""
    body = f"{abs(value):.1f}"
    if _is_es():
        return f"{sign}{body.replace('.', ',')} %"
    return f"{sign}{body}%"


def _dec(value: float, places: int) -> str:
    body = f"{value:.{places}f}"
    return body.replace(".", ",") if _is_es() else body


def _rows(n: int) -> str:
    return tr("landing.row_n" if n == 1 else "landing.rows_n", n=n)


# ------------------------------------------------------------------- assets

_G_MARK = (
    '<svg class="ag-l-g" viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M21.35 11.1H12v3.9h5.4c-.5 2.5-2.7 3.9-5.4 3.9a6 6 0 1 1 0-12'
    "c1.5 0 2.9.55 3.95 1.45l2.9-2.9A9.9 9.9 0 0 0 12 2a10 10 0 1 0 0 20"
    'c5.75 0 9.55-4.05 9.55-9.75 0-.4-.05-.8-.2-1.15z"></path></svg>'
)

_GITHUB_MARK = (
    '<svg class="ag-l-gh" viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79'
    "-.25.79-.55v-1.94c-3.2.7-3.87-1.54-3.87-1.54-.52-1.33-1.28-1.68-1.28-1.68"
    "-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.03 1.76 2.69 1.25 3.35"
    ".96.1-.75.4-1.25.72-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19"
    "-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0"
    "c2.2-1.49 3.16-1.18 3.16-1.18.63 1.59.24 2.76.12 3.05.74.81 1.19 1.83 1.19"
    " 3.09 0 4.41-2.7 5.38-5.26 5.66.41.36.78 1.06.78 2.14v3.17c0 .3.2.67.8.55"
    'A11.51 11.51 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5z"></path></svg>'
)

_WARN_MARK = (
    '<svg class="ag-l-warnicon" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 '
    '2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" '
    'x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>'
    "</svg>"
)

_CHECK_MARK = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="var(--ag-brand-accent)" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true"><path d="M20 6L9 17l-5-5"></path></svg>'
)


# ------------------------------------------------------------------ sections


def _mark(width_class: str = "") -> str:
    src = esc(f"{ASSET_BASE}topstocks-icon.svg")
    cls = f' class="{width_class}"' if width_class else ""
    return f'<img src="{src}" alt="TopStocks" width="28" height="28"{cls}>'


def _lang_toggle(*, footer: bool = False) -> str:
    """EN / ES switch — one indexable URL each, paired by hreflang in the head.

    The switch keeps the jurisdiction: a reader on the Spanish-tax page who
    wants English wants the English *Spanish-tax* page, not a different
    country's argument.
    """
    es = _is_es()
    jur = active_jurisdiction()
    en_href, es_href = variant_path("en", jur), variant_path("es", jur)
    en_part = '<span class="on">EN</span>' if not es else f'<a href="{en_href}">EN</a>'
    es_part = '<span class="on">ES</span>' if es else f'<a href="{es_href}">ES</a>'
    if footer:
        return f'<div class="ag-l-foot-lang">{en_part}<span>·</span>{es_part}</div>'
    return f'<div class="ag-l-lang">{en_part}{es_part}</div>'


def _jur_toggle(*, footer: bool = False) -> str:
    """Spain-tax / US-tax switch, keeping the language.

    Footer-only in the chrome (the header has no room on a phone) plus one
    contextual link in the tax section, which is where a reader discovers the
    page is arguing the wrong country at them.
    """
    lang = active_language()
    here = active_jurisdiction()
    parts = []
    for code in ("ES", "US"):
        label = esc(tr(f"landing.jur_{code.lower()}"))
        parts.append(
            f'<span class="on">{label}</span>' if code == here
            else f'<a href="{variant_path(lang, code)}">{label}</a>'
        )
    if footer:
        return (
            f'<div class="ag-l-foot-lang">{parts[0]}<span>·</span>{parts[1]}</div>'
        )
    return f'<div class="ag-l-lang">{parts[0]}{parts[1]}</div>'


def _jur_switch_link() -> str:
    """"Filing in the US instead?" — the other country's page, same language."""
    other = "US" if active_jurisdiction() == "ES" else "ES"
    href = variant_path(active_language(), other)
    return (
        f'<a class="ag-l-jurswitch" href="{href}">'
        f'{esc(tr(f"landing.jur_switch_{other.lower()}"))}</a>'
    )


def _legal_lang_q() -> str:
    """Query string that keeps the legal pages in this page's language."""
    return "?lang=es" if _is_es() else ""


def _guides_path() -> str:
    return PATH_GUIDES_ES if _is_es() else PATH_GUIDES_EN


def _app_href(param: str) -> str:
    """The app entry URL for a CTA.

    Always root-absolute with the query parameter: `server.py` hands any
    parameterised request for `/` to the app, so this one link both leaves
    the landing and tells the app what the visitor asked for. The Spanish page
    carries its language along, since the app resolves that per session.
    """
    lang = "" if not _is_es() else "&lang=es"
    return f"{PATH_EN}?{param}=1{lang}"


def _signin_link(cls: str, label: str, *, with_mark: bool = True) -> str:
    mark = _G_MARK if with_mark else ""
    href = esc(_app_href(PARAM_SIGNIN))
    return f'<a class="{cls}" href="{href}">{mark}{esc(label)}</a>'


def _guest_link(label: str) -> str:
    href = esc(_app_href(PARAM_GUEST))
    return f'<a class="ag-l-cta-text" href="{href}">{esc(label)} →</a>'


def _top_bar() -> str:
    return f"""
<header class="ag-l-bar"><div class="ag-l-wrap ag-l-bar-in">
  <div class="ag-l-brand">{_mark()}<span>TopStocks</span></div>
  <div class="ag-l-spacer"></div>
  {_lang_toggle()}
  <a class="ag-l-ghlink" href="{esc(GITHUB_URL)}" target="_blank"
     rel="noopener noreferrer">{_GITHUB_MARK}{esc(tr("landing.nav_github"))}</a>
  {_signin_link("ag-l-cta-ghost", tr("common.sign_in_google"), with_mark=False)}
</div></header>"""


def _hero() -> str:
    kpis = (
        (tr("landing.kpi_cost"), _money(48230), ""),
        (tr("landing.kpi_value"), _money(61484), ""),
        (tr("landing.kpi_unrealised"), _money(13254, signed=True), "ag-l-up"),
        (
            tr("landing.kpi_realised", year=_FISCAL_YEAR),
            _money(2141, signed=True),
            "ag-l-up",
        ),
    )
    kpi_html = "".join(
        f'<div class="ag-l-kpi"><span class="ag-l-kpi-l">{esc(label)}</span>'
        f'<span class="ag-l-num ag-l-kpi-v {cls}">{esc(value)}</span></div>'
        for label, value, cls in kpis
    )

    positions = (
        ("MSFT", 18940, 6120, 47.7),
        ("ASML", 12306, 3485, 39.5),
        ("ITX.MC", 9872, 2410, 32.3),
        ("PYPL", 4517, -1893, -29.5),
    )
    rows = "".join(
        f'<div class="ag-l-tr"><span class="ag-l-tk">{esc(tk)}</span>'
        f'<span class="ag-l-dim">{esc(_plain(val))}</span>'
        f'<span class="ag-l-tk {"ag-l-up" if pl >= 0 else "ag-l-down"}">'
        f"{esc(_plain(pl, signed=True))}</span>"
        f'<span class="{"ag-l-up" if pl >= 0 else "ag-l-down"}">'
        f"{esc(_pct(pct))}</span></div>"
        for tk, val, pl, pct in positions
    )

    axis = "".join(f"<span>{esc(y)}</span>" for y in _CHART_YEARS)

    return f"""
<section class="ag-l-wrap ag-l-hero">
  <div class="ag-l-hero-copy">
    <div class="ag-l-badge"><i></i>
      <b class="ag-l-mono">{esc(tr("landing.hero_badge"))}</b></div>
    <h1>{esc(tr("landing.hero_title"))}</h1>
    <p class="ag-l-lede">{esc(tr("landing.hero_sub"))}</p>
    <div class="ag-l-ctarow">
      {_signin_link("ag-l-cta", tr("common.sign_in_google"))}
      {_guest_link(tr("landing.cta_guest"))}
    </div>
    <div class="ag-l-trust">{esc(tr("landing.trust_strip"))}</div>
  </div>
  <div class="ag-l-card">
    <div class="ag-l-kpis">{kpi_html}</div>
    <div class="ag-l-tbl">
      <div class="ag-l-th">
        <span>{esc(tr("landing.col_position"))}</span>
        <span>{esc(tr("landing.col_value_eur"))}</span>
        <span>{esc(tr("landing.col_pl_eur"))}</span>
        <span>{esc(tr("landing.col_pl_pct"))}</span>
      </div>{rows}
    </div>
    <div class="ag-l-chart">
      <div class="ag-l-legend">
        <span><span class="ag-l-sw ag-l-sw-twr"></span>
          {esc(tr("landing.legend_twr"))}</span>
        <span><span class="ag-l-sw ag-l-sw-bm"></span>{esc(_BENCHMARK)}</span>
      </div>
      <svg viewBox="0 0 560 130" preserveAspectRatio="none" aria-hidden="true">
        <line x1="0" y1="110" x2="560" y2="110" stroke="var(--ag-surface-card)"
              stroke-width="1"></line>
        <line x1="0" y1="70" x2="560" y2="70" stroke="var(--ag-surface-card)"
              stroke-width="1"></line>
        <line x1="0" y1="30" x2="560" y2="30" stroke="var(--ag-surface-card)"
              stroke-width="1"></line>
        <path d="M0,108 C40,104 60,96 90,98 C120,100 140,84 180,80 C220,76 240,88
                 280,78 C320,68 340,52 390,48 C440,44 460,56 500,40 C530,28 545,26
                 560,22" fill="none" stroke="var(--ag-landing-info)"
              stroke-width="1.6" opacity="0.65"></path>
        <path d="M0,110 C40,108 60,100 90,102 C120,104 150,78 190,72 C230,66 250,84
                 290,70 C330,56 350,44 400,38 C450,32 470,48 510,28 C535,18 548,16
                 560,12" fill="none" stroke="var(--ag-brand-accent)"
              stroke-width="2.2"></path>
      </svg>
      <div class="ag-l-axis ag-l-mono">{axis}</div>
    </div>
  </div>
</section>"""


def _brokers() -> str:
    tiles = []
    for name, formats, generic in _BROKERS:
        if generic:
            name = tr("landing.broker_generic")
            formats = tr("landing.broker_generic_note")
        cls = "ag-l-broker generic" if generic else "ag-l-broker"
        tiles.append(
            f'<div class="{cls}"><b>{esc(name)}</b>'
            f'<i class="ag-l-mono">{esc(formats)}</i></div>'
        )
    return f"""
<section class="ag-l-wrap ag-l-brokers">
  <div class="ag-l-brokers-line">{esc(tr("landing.brokers_line"))}</div>
  <div class="ag-l-brokergrid">{"".join(tiles)}</div>
</section>"""


def _gap() -> str:
    pairs = (
        ("landing.gap_p1", "landing.gap_b1", "landing.gap_s1"),
        ("landing.gap_p2", "landing.gap_b2", "landing.gap_s2"),
        ("landing.gap_p3", "landing.gap_b3", "landing.gap_s3"),
    )
    blocks = "".join(
        f'<div class="ag-l-gap">'
        f'<div><b class="ag-l-down">{esc(tr(head))}</b>'
        f"<p>{esc(tr(body))}</p></div>"
        f'<div><b class="ag-l-up">{esc(tr("landing.gap_does"))}</b>'
        f"<p>{esc(tr(fix))}</p></div></div>"
        for head, body, fix in pairs
    )

    fifo = f"""
<div class="ag-l-diagram">
  <span class="ag-l-mono ag-l-eyebrow-sm">{esc(tr("landing.fifo_label"))}</span>
  <div class="ag-l-lots">
    <div class="ag-l-lot sold ag-l-f10">
      <b>{esc(tr("landing.fifo_lot", n=1, year=2022))}</b>
      <i class="ag-l-mono">{esc(tr("landing.fifo_sold", n=10))}</i></div>
    <div class="ag-l-lotpair ag-l-f12">
      <div class="ag-l-lot sold ag-l-f5">
        <b>{esc(tr("landing.fifo_lot", n=2, year=2023))}</b>
        <i class="ag-l-mono">{esc(tr("landing.fifo_sold", n=5))}</i></div>
      <div class="ag-l-lot held ag-l-f7"><b>&nbsp;</b>
        <i class="ag-l-mono">{esc(tr("landing.fifo_held", n=7))}</i></div>
    </div>
    <div class="ag-l-lot held ag-l-f8">
      <b>{esc(tr("landing.fifo_lot", n=3, year=2025))}</b>
      <i class="ag-l-mono">{esc(tr("landing.fifo_held", n=8))}</i></div>
  </div>
  <span class="ag-l-note">{esc(tr("landing.fifo_note"))}</span>
</div>"""

    buy = esc(tr("landing.fx_buy"))
    sell = esc(tr("landing.fx_sell"))
    rate_lo = esc(_dec(1.098, 3))
    rate_hi = esc(_dec(1.132, 3))
    fx = f"""
<div class="ag-l-diagram">
  <span class="ag-l-mono ag-l-eyebrow-sm">{esc(tr("landing.fx_label"))}</span>
  <div class="ag-l-tl">
    <div class="ag-l-tl-rail"></div>
    <div class="ag-l-tl-tick ag-l-at8"></div>
    <div class="ag-l-tl-lab ag-l-mono ag-l-at8">
      {buy} 03·2022<br>{rate_lo} $/€</div>
    <div class="ag-l-tl-tick ag-l-at72"></div>
    <div class="ag-l-tl-lab ag-l-mono ag-l-at72">
      {sell} 05·2025<br>{rate_hi} $/€</div>
    <div class="ag-l-tl-tick faint ag-l-at96"></div>
    <div class="ag-l-tl-lab ag-l-mono faint ag-l-at96">
      {esc(tr("landing.fx_today"))}<br>{esc(tr("landing.fx_spot"))}</div>
  </div>
  <div class="ag-l-compare">
    <div class="broker"><small>{esc(tr("landing.fx_broker"))}</small>
      <b class="ag-l-num">{esc(_money(1412, signed=True))}</b></div>
    <div class="ours"><small>{esc(tr("landing.fx_topstocks"))}</small>
      <b class="ag-l-num">{esc(_money(1168, signed=True))}</b></div>
  </div>
  <span class="ag-l-note">{esc(tr("landing.fx_note"))}</span>
</div>"""

    return f"""
<section class="ag-l-band"><div class="ag-l-wrap ag-l-sec">
  <div class="ag-l-head">
    <h2>{esc(tr("landing.gap_title"))}</h2>
    <p>{esc(tr("landing.gap_sub"))}</p>
  </div>
  <div class="ag-l-gaps">{blocks}</div>
  <div class="ag-l-diagrams">{fifo}{fx}</div>
</div></section>"""


def _how() -> str:
    buckets = (
        ("ok", tr("landing.imp_clean"), 214),
        ("warn", tr("landing.imp_warn"), 3),
        ("bad", tr("landing.imp_reject"), 1),
        ("skip", tr("landing.imp_skip"), 6),
    )
    bucket_html = "".join(
        f'<div class="ag-l-bucket {cls}"><b>{esc(label)}</b>'
        f'<i class="ag-l-mono">{esc(_rows(n))}</i></div>'
        for cls, label, n in buckets
    )

    mini_rows = "".join(
        f'<div class="ag-l-mini-r"><span class="ag-l-tk">{esc(tk)}</span>'
        f'<span class="ag-l-up">{esc(_plain(pl, signed=True))}</span>'
        f'<span class="ag-l-dim">{esc(_pct(w, signed=False))}</span></div>'
        for tk, pl, w in (
            ("MSFT", 6120, 30.8),
            ("ASML", 3485, 20.0),
            ("ITX.MC", 2410, 16.1),
        )
    )

    return f"""
<section class="ag-l-wrap ag-l-sec">
  <h2>{esc(tr("landing.how_title"))}</h2>
  <div class="ag-l-steps">
    <div class="ag-l-step">
      <h3>{esc(tr("landing.step1_title"))}</h3>
      <div class="ag-l-gbtn"><span>{_G_MARK}
        {esc(tr("common.sign_in_google"))}</span></div>
      <p>{esc(tr("landing.step1_body"))}</p>
    </div>
    <div class="ag-l-step">
      <h3>{esc(tr("landing.step2_title"))}</h3>
      <div class="ag-l-buckets">{bucket_html}</div>
      <p>{esc(tr("landing.step2_body"))}</p>
    </div>
    <div class="ag-l-step">
      <h3>{esc(tr("landing.step3_title"))}</h3>
      <div class="ag-l-mini">
        <div class="ag-l-mini-h">
          <span>{esc(tr("landing.col_position"))}</span>
          <span>{esc(tr("landing.col_eur_pl"))}</span>
          <span>{esc(tr("landing.col_weight"))}</span>
        </div>{mini_rows}
      </div>
      <p>{esc(tr("landing.step3_body"))}</p>
    </div>
  </div>
</section>"""


# The assistant's skill library (web/skills/*.md), in the order the chat panel's
# own picker lists them — sorted by id, because each file is named after it.
# Labels come from the chat catalog, so the landing and the picker can never
# call the same lens two different things, and both stay bilingual for free.
_LENSES = (
    "bear-case", "crypto", "dividend", "earnings-review", "emerging-markets",
    "energy", "etfs", "financials", "growth-momentum", "healthcare", "macro",
    "portfolio-risk", "spain-tax", "tax", "tech", "technical", "us-tax", "value",
)

# App operations the assistant performs on its own (chat/tools.py). Only the
# five additive ones are named: the other three are the same tools in reverse
# (unfavorite, untag, remove_ticker) and read as filler in a chip strip.
_AI_ACTIONS = ("alert", "tag", "watchlist", "position", "favourite")

# The BYOK providers, in registry order (web/llm.py PROVIDERS). Brand names, so
# they are literal; the free tier in front of them is a phrase that translates.
_AI_MODELS = ("CLAUDE", "CHATGPT", "GEMINI")

# The sample answer's realised gain. Its tax line is derived from the same
# headline rate the IRPF panel uses, so the two mocks agree with each other.
_AI_GAIN = 4180


def _assistant() -> str:
    """The assistant section: one worked exchange, then what carries it.

    The mock is the only place the landing reproduces app chrome, and it earns
    that by being the claim itself — "the answer is about your book" is not
    something a paragraph can show. Every figure in it is a figure that already
    appears elsewhere on the page (MSFT at 30.8% of the book, 1/HHI 6.8, a
    15-share sale matched across two lots), so a reader who scrolls back finds
    the same numbers rather than a second, contradictory sample portfolio.
    """
    rate = _PANEL_RATE.get(active_jurisdiction(), 19.0)

    # Escaped first, marked up second: the sentence names its two figures
    # inline and bolds them, exactly like the provenance paragraph.
    answer = esc(tr("landing.ai_a")).format(
        tech=esc(_pct(48.2, signed=False)),
        msft=esc(_pct(30.8, signed=False)),
        names=esc(_dec(6.8, 1)),
        shares=esc(_plain(15)),
        gain=f"<b>{esc(_money(_AI_GAIN))}</b>",
        tax=f"<b>{esc(_money(round(_AI_GAIN * rate / 100)))}</b>",
    )

    tags = "".join(
        f'<span class="ag-l-tag {cls}">{esc(tr(key))}</span>'
        for key, cls in (
            ("landing.ai_src_ledger", "fact"),
            ("landing.ai_src_rule", "derived"),
            ("landing.ai_src_fx", "source"),
        )
    )

    chat = f"""
<div class="ag-l-chat">
  <div class="ag-l-chat-h">
    <span class="ag-l-avatar" aria-hidden="true">A</span>
    <b>{esc(tr("landing.ai_who"))}</b>
    <span class="ag-l-mono ag-l-chip">
      {esc(tr("landing.ai_context", n=24, value=_money(61484)))}</span>
  </div>
  <div class="ag-l-ask">{esc(tr("landing.ai_q"))}</div>
  <div class="ag-l-said">
    <p>{answer}</p>
    <div class="ag-l-tags">{tags}</div>
    <div class="ag-l-action">{_CHECK_MARK}
      <span>{esc(tr("landing.ai_action", price="$390"))}</span>
      <i class="ag-l-mono ag-l-chip">{esc(tr("landing.ai_action_tag"))}</i>
    </div>
  </div>
  <div class="ag-l-composer">
    <span>{esc(tr("landing.ai_composer"))}</span>
    <i class="ag-l-mono ag-l-chip">{esc(tr("landing.ai_websearch"))}</i>
  </div>
</div>"""

    action_chips = "".join(
        f'<span>{esc(tr(f"landing.ai_act_{name}"))}</span>' for name in _AI_ACTIONS
    )
    models = "".join(
        f"<span>{esc(m)}</span>"
        for m in (tr("landing.ai_free"), *_AI_MODELS)
    )

    cards = f"""
<div class="ag-l-aicards">
  <div class="ag-l-tile">
    <h3>{esc(tr("landing.ai_c1_h"))}</h3>
    <p>{esc(tr("landing.ai_c1_b"))}</p>
  </div>
  <div class="ag-l-tile">
    <h3>{esc(tr("landing.ai_c2_h"))}</h3>
    <div class="ag-l-chips">{action_chips}</div>
    <p class="ag-l-aside">{esc(tr("landing.ai_c2_b"))}</p>
  </div>
  <div class="ag-l-tile">
    <h3>{esc(tr("landing.ai_c3_h"))}</h3>
    <div class="ag-l-models">{models}</div>
    <p>{esc(tr("landing.ai_c3_b"))}</p>
  </div>
</div>"""

    lenses = "".join(
        f'<span>{esc(translate(f"chat.skill.{lens}", active_language()))}</span>'
        for lens in _LENSES
    )

    notes = "".join(
        f'<div class="ag-l-brandtile"><h3>{esc(tr(f"landing.ai_n{i}_h"))}</h3>'
        f'<p>{esc(tr(f"landing.ai_n{i}_b"))}</p></div>'
        for i in range(1, 4)
    )

    return f"""
<section class="ag-l-band"><div class="ag-l-wrap ag-l-sec">
  <div class="ag-l-head">
    <span class="ag-l-eyebrow">{esc(tr("landing.ai_eyebrow"))}</span>
    <h2>{esc(tr("landing.ai_title"))}</h2>
    <p>{esc(tr("landing.ai_body"))}</p>
  </div>
  <div class="ag-l-ai">{chat}{cards}</div>
  <div class="ag-l-lenses">
    <div class="ag-l-lenses-h">
      <h3>{esc(tr("landing.ai_lenses_title", n=len(_LENSES)))}</h3>
      <p>{esc(tr("landing.ai_lenses_sub"))}</p>
    </div>
    <div class="ag-l-lensgrid">{lenses}</div>
  </div>
  <div class="ag-l-ainotes">{notes}</div>
</div></section>"""


def _provenance() -> str:
    cards = (
        ("landing.prov_k1_label", {}, "$391.0B", "fact", "landing.tag_fact",
         "landing.prov_k1_src", {}),
        ("landing.prov_k2_label", {"year": 2027}, "$8.42", "consensus",
         "landing.tag_consensus", "landing.prov_k2_src", {"n": 31}),
        ("landing.prov_k3_label", {}, _pct(3.1, signed=False), "derived",
         "landing.tag_derived", "landing.prov_k3_src", {}),
    )
    card_html = "".join(
        f'<div class="ag-l-provcard"><div class="ag-l-provcard-h">'
        f"<span>{esc(tr(label, **largs))}</span>"
        f'<span class="ag-l-tag {cls}">{esc(tr(tag))}</span></div>'
        f'<b class="ag-l-num">{esc(value)}</b>'
        f"<small>{esc(tr(src, **sargs))}</small></div>"
        for label, largs, value, cls, tag, src, sargs in cards
    )
    card_html += (
        '<div class="ag-l-provcard"><div class="ag-l-provcard-h">'
        f'<span>{esc(tr("landing.prov_k4_label"))}</span></div>'
        '<b class="ag-l-num ag-l-na">n/a</b>'
        f'<small>{esc(tr("landing.prov_k4_src"))}</small></div>'
    )

    # The body names its three tags inline and colours each one, so the template
    # is escaped first and the marked-up words are substituted afterwards.
    body = esc(tr("landing.prov_body")).format(
        fact=f'<b class="fact">{esc(tr("landing.prov_word_fact"))}</b>',
        consensus=f'<b class="consensus">{esc(tr("landing.prov_word_consensus"))}</b>',
        derived=f'<b class="derived">{esc(tr("landing.prov_word_derived"))}</b>',
    )

    return f"""
<section class="ag-l-prov"><div class="ag-l-wrap ag-l-prov-in">
  <h2>{esc(tr("landing.prov_title"))}</h2>
  <div class="ag-l-provrow">{card_html}</div>
  <p>{body}</p>
</div></section>"""


def _bento() -> str:
    # Pills are symbols and statute references — language-neutral, so they stay
    # literal data rather than catalog entries. The tax ones are still
    # jurisdiction-specific: a statute cite is the one thing that cannot be
    # translated across borders.
    risk_pills = (
        f"TWR {_pct(18.4)}",
        f"1/HHI {_dec(6.8, 1)}",
        f"β {_dec(1.12, 2)} vs {_BENCHMARK}",
        f"max DD {_pct(-22.6)}",
    )
    tax_pills = _TAX_PILLS.get(active_jurisdiction(), _TAX_PILLS["ES"])

    def pills(items: tuple[str, ...]) -> str:
        inner = "".join(f'<span class="ag-l-pill">{esc(p)}</span>' for p in items)
        return f'<div class="ag-l-pills">{inner}</div>'

    # No AI or notifications tile: the assistant has its own section upstream, and a
    # one-paragraph summary of it here read as a second, weaker pitch.
    small = (
        ("landing.f_deep_title", "landing.f_deep_body"),
        ("landing.f_earnings_title", "landing.f_earnings_body"),
        ("landing.f_alerts_title", "landing.f_alerts_body"),
        ("landing.f_crypto_title", "landing.f_crypto_body"),
    )
    small_html = "".join(
        f'<div class="ag-l-tile"><h3>{esc(tr(title))}</h3>'
        f"<p>{esc(tr(body))}</p></div>"
        for title, body in small
    )

    return f"""
<section class="ag-l-wrap ag-l-sec">
  <h2>{esc(tr("landing.bento_title"))}</h2>
  <div class="ag-l-bento-lg">
    <div class="ag-l-tile"><h3>{esc(tr("landing.f_portfolio_title"))}</h3>
      <p>{esc(tr("landing.f_portfolio_body"))}</p>{pills(risk_pills)}</div>
    <div class="ag-l-tile"><h3>{esc(tr("landing.f_tax_title"))}</h3>
      <p>{esc(tr("landing.f_tax_body"))}</p>{pills(tax_pills)}</div>
  </div>
  <div class="ag-l-bento-sm">{small_html}</div>
</section>"""


def _depth_a() -> str:
    legs = (
        ("2022-03-14", tr("landing.fx_buy"), 10, 280.50, 1.0982),
        ("2025-05-09", tr("landing.fx_sell"), 10, 438.20, 1.1324),
    )
    leg_html = []
    for i, (date, verb, qty, price, rate) in enumerate(legs):
        if i:
            leg_html.append('<div class="ag-l-legjoin"></div>')
        leg_html.append(
            f'<div class="ag-l-leg"><span class="ag-l-dot"></span>'
            f'<span class="ag-l-mono">{esc(date)} · {esc(verb)} {qty} @ '
            f'${esc(_dec(price, 2))}</span>'
            f'<b class="ag-l-mono">ECB {esc(_dec(rate, 4))}</b></div>'
        )

    return f"""
<section class="ag-l-rule"><div class="ag-l-wrap ag-l-depth">
  <div class="ag-l-depth-copy">
    <span class="ag-l-eyebrow">{esc(tr("landing.depthA_eyebrow"))}</span>
    <h2>{esc(tr("landing.depthA_title"))}</h2>
    <p>{esc(tr("landing.depthA_body"))}</p>
  </div>
  <div class="ag-l-flat">
    <span class="ag-l-mono ag-l-eyebrow-sm">MSFT ·
      {esc(tr("landing.depthA_label"))}</span>
    <div class="ag-l-legs">{"".join(leg_html)}</div>
    <div class="ag-l-split">
      <div class="broker"><small>{esc(tr("landing.depthA_broker"))}</small>
        <b class="ag-l-num">{esc(_money(1412, signed=True))}</b></div>
      <div class="ours"><small>{esc(tr("landing.depthA_topstocks"))}</small>
        <b class="ag-l-num">{esc(_money(1168, signed=True))}</b></div>
    </div>
  </div>
</div></section>"""


# Statute pills on the tax feature card, per jurisdiction.
_TAX_PILLS = {
    "ES": ("art. 37 LIRPF", "art. 33.5.f", "Modelo 720", "19–30%"),
    "US": ("FIFO", "IRC 1091", "Form 8938", "0/15/20%"),
}

# Headline rate on the panel's sample base: Spain's first savings-base bracket,
# the US long-term middle rate. Illustrative, like every figure in the mocks.
_PANEL_RATE = {"ES": 19.0, "US": 15.0}


def _depth_b() -> str:
    rate = _pct(_PANEL_RATE.get(active_jurisdiction(), 19.0), signed=False)
    rows = f"""
<div class="ag-l-irpf-r"><span>{esc(tr("landing.irpf_gains"))}</span>
  <b class="ag-l-up">{esc(_money(2521, signed=True))}</b></div>
<div class="ag-l-irpf-r"><span>{esc(tr("landing.irpf_losses"))}</span>
  <b class="ag-l-down">{esc(_money(-380, signed=True))}</b></div>
<div class="ag-l-irpf-r ag-l-warnrow">
  <span>{_WARN_MARK}{esc(tr("landing.irpf_deferred"))}</span>
  <b class="ag-l-struck">{esc(_money(-612, signed=True))}</b></div>
<div class="ag-l-irpf-r total"><span>{esc(tr("landing.irpf_net"))}</span>
  <b>{esc(_money(2141))}</b></div>
<div class="ag-l-irpf-r total">
  <span>{esc(tr("landing.irpf_tax", rate=rate))}</span>
  <b>{esc(_money(407))}</b></div>
<div class="ag-l-irpf-r"><span>{esc(tr("landing.irpf_carry"))}</span>
  <b class="ag-l-down">{esc(_money(-612, signed=True))}</b></div>"""

    return f"""
<section class="ag-l-band"><div class="ag-l-wrap ag-l-depth">
  <div class="ag-l-flat sunken">
    <span class="ag-l-mono ag-l-eyebrow-sm">
      {esc(tr("landing.irpf_label", year=_FISCAL_YEAR))}</span>
    <div class="ag-l-irpf">{rows}</div>
  </div>
  <div class="ag-l-depth-copy">
    <span class="ag-l-eyebrow">{esc(tr("landing.depthB_eyebrow"))}</span>
    <h2>{esc(tr("landing.depthB_title"))}</h2>
    <p>{esc(tr("landing.depthB_body"))}</p>
    <div class="ag-l-disclaimer">{esc(tr("landing.depthB_disclaimer"))}</div>
    {_jur_switch_link()}
  </div>
</div></section>"""


def _trust() -> str:
    items = "".join(
        f'<div class="ag-l-trustitem"><b>{esc(tr(f"landing.t{i}_h"))}</b>'
        f'<span>{esc(tr(f"landing.t{i}_b"))}</span></div>'
        for i in range(1, 6)
    )
    return f"""
<section class="ag-l-wrap ag-l-sec">
  <h2>{esc(tr("landing.trust_title"))}</h2>
  <div class="ag-l-trustgrid">{items}</div>
</section>"""


def _faq() -> str:
    qs = "".join(
        f'<details class="ag-l-q"><summary>{esc(tr(f"landing.faq_q{i}"))}</summary>'
        f'<p>{esc(tr(f"landing.faq_a{i}"))}</p></details>'
        for i in range(1, FAQ_COUNT + 1)
    )
    return f"""
<section class="ag-l-band"><div class="ag-l-faq">
  <h2>{esc(tr("landing.faq_title"))}</h2>
  <div class="ag-l-qs">{qs}</div>
</div></section>"""


def _final() -> str:
    return f"""
<section class="ag-l-rule"><div class="ag-l-wrap ag-l-final">
  <h2>{esc(tr("landing.final_title"))}</h2>
  <div class="ag-l-ctarow">
    {_signin_link("ag-l-cta", tr("common.sign_in_google"))}
    {_guest_link(tr("landing.cta_guest_short"))}
  </div>
</div></section>"""


def _footer() -> str:
    return f"""
<footer class="ag-l-rule"><div class="ag-l-wrap ag-l-foot">
  <div class="ag-l-foot-row">
    <div class="ag-l-brand">{_mark()}<span>TopStocks</span></div>
    <a href="{esc(GITHUB_URL)}" target="_blank"
       rel="noopener noreferrer">{esc(tr("landing.nav_github"))}</a>
    <a href="{_guides_path()}">{esc(tr("landing.footer_guides"))}</a>
    <a href="/legal/privacy{_legal_lang_q()}">{esc(tr("landing.footer_privacy"))}</a>
    <a href="/legal/terms{_legal_lang_q()}">{esc(tr("landing.footer_terms"))}</a>
    {_lang_toggle(footer=True)}
    {_jur_toggle(footer=True)}
  </div>
  <p class="ag-l-fine">{esc(tr("landing.footer_disclaimer"))}</p>
</div></footer>"""


def _mobile_bar() -> str:
    """The fixed bottom CTA, phones only.

    Rendered on every viewport and hidden by default — `MOBILE_RULES` is what
    reveals it, so the switch stays in one place with the rest of the phone
    layout. The guest link is not duplicated here: it sits in the hero, one
    screen up, and a second line would cost another 30px of a 640px-tall
    viewport for the whole scroll.
    """
    label = tr("common.sign_in_google")
    return (
        '<div class="ag-l-mbar">'
        + _signin_link("ag-l-cta", label)
        + "</div>"
    )


# The bar's reveal. An IntersectionObserver on the two in-page CTA rows,
# toggling one class on the page root — no scroll handler, no layout reads.
# Wired once per document and retried through a MutationObserver, because this
# block can reach the DOM before the markup it observes. Its failure mode is
# the bar staying visible, which is the state the stylesheet already gives it.
_BAR_JS = """
<script>
(function () {
  if (window.__topstocksLandingBar) return;  /* wire once */
  window.__topstocksLandingBar = true;
  const wire = () => {
    const root = document.querySelector(".ag-l");
    const ctas = document.querySelectorAll(
      ".ag-l-hero .ag-l-ctarow, .ag-l-final .ag-l-ctarow"
    );
    if (!root || ctas.length !== 2) return false;
    root.classList.add("cta-visible");  /* no flash of the bar at the top */
    const onScreen = new Set();
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) onScreen.add(e.target);
        else onScreen.delete(e.target);
      });
      root.classList.toggle("cta-visible", onScreen.size !== 0);
    }, {threshold: 0.35});
    ctas.forEach((el) => io.observe(el));
    return true;
  };
  if (!wire()) {
    const mo = new MutationObserver(() => { if (wire()) mo.disconnect(); });
    mo.observe(document.body, {subtree: true, childList: true});
  }
})();
</script>
"""


# Carry the source token from the landing's own URL onto the CTA links, so the
# click that leaves for the app says where the reader came from. It has to
# happen in the browser: the document is one cached string per language and
# host (`landing_static.document`), and a per-request token would give every
# campaign its own copy of ~90KB.
#
# `web.attribution` owns the vocabulary — the parameter name and the shape of a
# token are asserted equal on both sides in `tests/test_attribution.py`, so this
# cannot quietly drift into forwarding something the server then drops.
_SRC_JS = """
<script>
(function () {
  try {
    const q = new URLSearchParams(location.search);
    const raw = q.get("utm_source") || q.get("src") || q.get("ref") || "";
    const src = raw
      .toLowerCase()
      .replace(/[^a-z0-9._+-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 32);
    if (!src) return;
    document.querySelectorAll('a[href^="/?"]').forEach((a) => {
      a.setAttribute("href", a.getAttribute("href") + "&src=" + encodeURIComponent(src));
    });
  } catch (e) {}
})();
</script>
"""


def _mobile_css_body() -> str:
    """The phone rules again, at a wider breakpoint, for User-Agent gating.

    `CSS` already applies them under `max-width: 640px`, which is the right
    trigger — layout should follow width. But a phone can report a CSS
    viewport wider than that (large handsets, landscape, a stale zoom). Where
    the two disagree below 900px, believe the User-Agent: a touch device wants
    the stacked layout and the thumb-reachable CTA either way.

    `landing_static` ships this in a `<style media="not all">` element and a
    one-line script flips the attribute to `all` for phone User-Agents, which
    is how a static document does a server-side check it no longer has. Placed
    after `CSS`, so it wins on source order; `TINY_CSS` rides along to stay
    last.
    """
    return "@media (max-width: 900px) {" + MOBILE_RULES + "}" + TINY_CSS


def _mobile_css() -> str:
    """`_mobile_css_body()` in its own style element."""
    return "<style>" + _mobile_css_body() + "</style>"


# --------------------------------------------------------------------- entry


def stylesheet() -> str:
    """The page stylesheet: base rules, the 640px phone block, small-phone type."""
    return CSS


def ua_mobile_rules() -> str:
    """The phone rules at 900px, bare CSS — see `_mobile_css_body`."""
    return _mobile_css_body()


def bar_script() -> str:
    """The mobile CTA bar's reveal script, in its `<script>` element."""
    return _BAR_JS


def source_script() -> str:
    """The CTA source-carrying script, in its `<script>` element (`_SRC_JS`)."""
    return _SRC_JS


def page_body() -> str:
    """The whole page as one element — every section, in order.

    Wrap the call in `render_language()`; `landing_static` does.
    """
    return (
        '<div class="ag-l">'
        + f'<a class="ag-l-skip" href="#ag-main">{esc(tr("landing.skip"))}</a>'
        + _top_bar()
        + '<main id="ag-main">'
        + _hero()
        + _brokers()
        + _gap()
        + _how()
        + _assistant()
        + _provenance()
        + _bento()
        + _depth_a()
        + _depth_b()
        + _trust()
        + _faq()
        + _final()
        + "</main>"
        + _footer()
        + _mobile_bar()
        + "</div>"
    )
