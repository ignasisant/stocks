"""Does the React Ticker page still say what the Streamlit one says?

Step 3 of the migration is one page rebuilt on `/api/v1`, kept side by side
with the original behind `?legacy=1`. The thing that decides whether it was
worth it is not how it looks in a screenshot — two renderers will never agree
pixel for pixel, and a diff of those is noise. It is whether the two front ends
make the same claims, in the same words, about the same company.

Three questions, all answerable without a browser:

1. Every string the React page prints exists in the catalog. Inventing a key is
   the failure that looks fine in English (the key falls through to itself) and
   ships a dotted slug to a Spanish reader.
2. Every section the Streamlit page renders is either ported or waived, in
   writing, with a reason. Adding a section to `app_pages/ticker.py` therefore
   fails this test until somebody decides about it — which is the whole point
   of a parity harness, as opposed to a parity memory.
3. Every endpoint the client calls exists on the server. A typed client cannot
   catch a path that was renamed underneath it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stocks.api.app import app as fastapi_app
from stocks.config import ALERT_TYPES
from stocks.web.i18n import catalog

REPO = Path(__file__).resolve().parents[1]
# The rebuilt page lives inside the app shell (`frontend/app`), which owns the
# routing, the session and the translations; the page owns `pages/ticker/`. The
# scan covers both, because a string the shell prints for this page — the menu,
# the sign-in screen, an error banner — is still a string this page says.
FRONTEND = REPO / "frontend" / "app" / "src"
TICKER_PAGE = FRONTEND / "pages" / "ticker"
# Every path this page can reach the network through: the shell's client and
# the page's own list of calls. A page reaching past those two is a rule the
# shell's README already forbids, not something this test has to discover.
CLIENTS = (FRONTEND / "shell" / "api.ts", TICKER_PAGE / "data.ts")
PAGE = REPO / "src" / "stocks" / "web" / "app_pages" / "ticker.py"

pytestmark = pytest.mark.skipif(
    not FRONTEND.exists(), reason="frontend sources not checked out"
)

# `t("some.key")`, but not `get("ticker")` — a word character before the `t`
# means it is the tail of another identifier.
_LITERAL = re.compile(r'(?<![\w.])t\(\s*"([a-z][\w]*\.[\w.]+)"')

# `` t(`ticker.period_${label}`) ``: the prefix is fixed, the suffix comes from
# a set declared in the source. Declared here as well, so a new member of one of
# those sets has to be added in both places — which is exactly when its string
# needs writing.
_TEMPLATES = {
    "ticker.period_": ("1d", "1w", "1m", "3m", "6m", "1y", "2y", "5y"),
    "ticker.session_": ("pre", "post"),
    "ticker.view_": ("annual", "quarterly"),
    # These two are read off the domain rather than typed out: the alert types
    # are `config.ALERT_TYPES` and the page offers whatever the API serves from
    # it, so a type added there has to arrive here with its string already
    # written — in both languages — or this fails on the next run.
    "widgets.alert_t_": tuple(sorted(ALERT_TYPES)),
    # The number a rule asks for, whose label is the `field` the API names.
    "widgets.alert_": ("price", "pct", "level"),
    "portfolio.broker_": ("manual", "unknown"),
    # The drawer's width presets, which are `chat/width.ts`'s three keys and
    # the same three `web/chat_core._WIDTHS` names.
    "chat.width_": ("compact", "wide", "full"),
}

# Sections the Streamlit page renders that the React one deliberately does not,
# and why. A waiver is a decision, so each one carries its reason in the value.
WAIVED: dict[str, str] = {}

# The same, one string at a time. A section can be "ported" and still say less
# than the original — that is how the React page went live with a KPI grid of
# English labels, a fund card missing its basket, and an insider block showing
# the count of buyers where the app shows the count of buys. Every string the
# app prints has to be printed here too, or be written down as a decision.
WAIVED_STRINGS: dict[str, str] = {
    "ticker.ai_analyze": "the assistant is the app shell's, not this page's",
    "ticker.ai_analyze_help": "…and so is its tooltip",
    # Both of these are strings the *Plotly* page needs and a hand-drawn chart
    # does not. The claim each one makes is still made — which is what this
    # test is for — just not in those words.
    "ticker.eps_hover_reported": (
        "a Plotly hovertemplate; the SVG chart's tooltip pushes `k_reported` "
        "as its own line, which is the same claim about the same figure"
    ),
    "ticker.history_failed": (
        "the shell's `Loaded` renders every failed section alike — "
        "`common.data_unavailable` or `common.failed`, plus a retry this page "
        "never offered"
    ),
}


def _sources() -> list[Path]:
    """The page's own sources.

    Tests are excluded on purpose: they build catalogs of their own and assert
    on keys that are *meant* not to exist (a missing string must fall back to
    the key, and something has to check that). Counting those here would make
    this test fail for the one file whose job is to prove the fallback works.
    """
    return [
        path
        for path in sorted(FRONTEND.rglob("*"))
        if path.suffix in {".ts", ".tsx"}
        and "__tests__" not in path.parts
        and not path.name.endswith((".test.ts", ".test.tsx"))
    ]


def _frontend_text() -> str:
    return "\n".join(path.read_text() for path in _sources())


def _keys_used() -> set[str]:
    text = _frontend_text()
    keys = set(_LITERAL.findall(text))
    for prefix, suffixes in _TEMPLATES.items():
        if f"t(`{prefix}$" in text:
            keys |= {f"{prefix}{suffix}" for suffix in suffixes}
    return keys


# ------------------------------------------------------- 1. the strings exist


def test_every_string_the_react_page_prints_is_a_real_key():
    """A key that does not exist falls through to itself, so it reads fine in
    English and ships "ticker.moat_caption" to a Spanish reader."""
    strings = catalog("en")
    missing = sorted(key for key in _keys_used() if key not in strings)
    assert not missing, f"no such key in locales/en: {missing}"


def test_the_templated_keys_cover_every_option_the_page_offers():
    """The range pills and the view toggle build their key from a value. Each
    value needs a string, and a missing one only shows on that one click."""
    strings = catalog("en")
    text = _frontend_text()
    for prefix, suffixes in _TEMPLATES.items():
        if f"t(`{prefix}$" not in text:
            continue
        absent = [s for s in suffixes if f"{prefix}{s}" not in strings]
        assert not absent, f"{prefix}* has no string for {absent}"


def test_the_kpi_grid_names_strings_that_exist_in_both_languages():
    """The one set of labels neither front end holds.

    `FUNDAMENTAL_TILES` names an i18n key per tile and the API passes the name
    through, so nothing in `frontend/` mentions `ticker.kpi_roic` and the scan
    above cannot see it. A tile added with no string still renders — it falls
    back to `KpiSource.label`, which is English — so this is the only thing
    standing between a new tile and a Spanish reader seeing "Net debt/EBITDA".
    """
    from stocks.analysis.fundamentals import FUNDAMENTAL_TILES

    for lang in ("en", "es"):
        strings = catalog(lang)
        missing = sorted(
            key
            for tile in FUNDAMENTAL_TILES
            for key in (tile.label, tile.help)
            if key and key not in strings
        )
        assert not missing, (
            f"the KPI grid asks for strings locales/{lang} does not have: {missing}"
        )


def test_the_spanish_catalog_answers_everything_the_page_asks_for():
    """en/es parity is covered generally by test_i18n_parity; this is the same
    claim narrowed to the keys this page actually reaches for, so a gap names
    the page that will show it."""
    spanish = catalog("es")
    missing = sorted(key for key in _keys_used() if key not in spanish)
    assert not missing, f"untranslated on the React ticker page: {missing}"


def test_every_string_the_app_prints_is_printed_here_or_waived():
    """Section titles are not what a page says — this is.

    The scan is deliberately loose on the React side: any key-shaped literal
    counts, wherever it sits, because a tile's label can be an entry in an
    array that is translated a line later. Being loose is the point — a false
    pass here costs nothing, while a false failure would train somebody to
    silence the test.
    """
    app_keys = set(re.findall(r'tr\(\s*"([\w.]+)"', PAGE.read_text()))
    # The KPI grid's labels are named by the domain and travel as key names in
    # the payload, so neither front end mentions them in its own source. They
    # have their own test above; counting them here would only fail it.
    app_keys -= {
        key for tile in _grid_tiles() for key in (tile.label, tile.help) if key
    }
    text = _frontend_text()
    said = set(re.findall(r'"((?:ticker|widgets|common|kpi|portfolio)\.[\w.]+)"', text))
    # `` t(`ticker.period_${x}`) `` covers every key with that prefix.
    for prefix in re.findall(r"t\(`([\w.]+?)\$", text):
        said |= {key for key in app_keys if key.startswith(prefix)}

    unsaid = sorted(key for key in app_keys if key not in said | set(WAIVED_STRINGS))
    assert not unsaid, (
        "the Streamlit page prints these and the React one does not: "
        f"{unsaid}. Print them, or add each to WAIVED_STRINGS with a reason."
    )


def test_a_string_waiver_carries_a_reason():
    assert all(reason.strip() for reason in WAIVED_STRINGS.values())


def _grid_tiles():
    from stocks.analysis.fundamentals import FUNDAMENTAL_TILES

    return FUNDAMENTAL_TILES


# ------------------------------------------------------ 2. the sections match


def test_every_section_of_the_streamlit_page_is_ported_or_waived():
    """The harness that survives the next feature.

    A new `st.subheader(tr(...))` on the Streamlit page fails this until it is
    either built in React or written into WAIVED with a reason — so the two
    cannot drift quietly, only deliberately.
    """
    source = PAGE.read_text()
    titles = set(re.findall(r'st\.(?:subheader|expander)\(tr\("([\w.]+)"\)', source))
    assert titles, "no section titles found — the page's shape changed"
    used = _keys_used()
    unported = sorted(key for key in titles if key not in used and key not in WAIVED)
    assert not unported, (
        "the Streamlit ticker page renders these sections and the React one "
        f"does not: {unported}. Port them, or add them to WAIVED with a reason."
    )


def test_a_waiver_carries_a_reason():
    assert all(reason.strip() for reason in WAIVED.values())


# --------------------------------------------------------- 3. the client fits


def test_every_endpoint_the_client_calls_exists_on_the_server():
    """The client is hand-written against the OpenAPI schema. TypeScript checks
    the shape it expects and nothing at all about the path it asks for."""
    text = "\n".join(path.read_text() for path in CLIENTS if path.exists())
    # `at(ticker)` is the page's own shorthand for this company's route; every
    # call it makes is built on it, so it has to expand before the generic
    # placeholder rule below turns the whole prefix into one parameter.
    text = text.replace("${at(ticker)}", "/ticker/{p}")
    called = set()
    for raw in re.findall(r'`(/[^`]*)`', text) + re.findall(r'"(/[a-z][^"]*)"', text):
        # `${encodeURIComponent(ticker)}` and friends are one path parameter.
        path = re.sub(r"\$\{[^}]*\}", "{p}", raw)
        if path.startswith("/api") or "${" in path:
            continue
        called.add(path)
    served = {
        re.sub(r"\{[^}]*\}", "{p}", path.removeprefix("/v1"))
        for path in fastapi_app.openapi()["paths"]
    }
    # A path that is the *prefix* of a real route is a builder, not a call:
    # `at(ticker)` is defined as "/ticker/<symbol>" and every call appends to
    # it. Failing on it would only teach somebody to stop scanning that file.
    unknown = sorted(
        path
        for path in called
        if path not in served
        and not any(route.startswith(f"{path}/") for route in served)
    )
    assert not unknown, f"the client calls paths the API does not serve: {unknown}"
