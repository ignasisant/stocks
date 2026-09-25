"""Do the other seven React pages still say what their Streamlit pages say?

`test_ticker_parity` asks this of one page, in detail, because Ticker was the
page the migration was measured on. This asks it of the rest, and it exists
because of what that measurement found: with 8/8 sections "ported", the React
ticker page said **75 fewer strings** than the Streamlit one. Section titles
are not what a page says — a card can be present and still be missing its
basket, its percentile selector and half its columns.

So the unit here is the string, not the section. For every page, every
`tr("…")` the Streamlit page prints is either said by the React page, or
written down as a decision with a reason. There are two ways to write it down,
and the difference is the whole point of keeping them apart:

* `waived` — the React page deliberately does not say this, and never will.
  The shell says it instead, a hand-drawn chart does not need a Plotly
  hovertemplate, a written state replaced a toast.
* `pending` — the React page *should* say this and does not. A real gap, named,
  with what it would take. These are findings, not exemptions: the list is
  meant to shrink, and nothing but this file records them.

A key in neither fails the test, which is what stops the two front ends from
drifting quietly — they can only drift deliberately.

Parsed rather than imported, because the other side is TypeScript. The React
scan is deliberately loose: any key-shaped literal counts, wherever it sits in
the page's directory or the shell. A false pass here costs one missed string; a
false failure would train somebody to silence the test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from stocks.api.app import app as fastapi_app

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend" / "app" / "src"
APP_PAGES = REPO / "src" / "stocks" / "web" / "app_pages"

pytestmark = pytest.mark.skipif(
    not FRONTEND.exists(), reason="frontend sources not checked out"
)


@dataclass(frozen=True)
class Page:
    """One screen, on both sides of the migration."""

    #: The Streamlit page this one replaces, under `web/app_pages/`.
    streamlit: str
    #: Said by the shell or said differently on purpose — never coming back.
    waived: dict[str, str] = field(default_factory=dict)
    #: Missing, and it matters. The value says what is absent, not why it is
    #: fine, because it is not fine.
    pending: dict[str, str] = field(default_factory=dict)


# Four pages hand-draw the chart the Streamlit page draws with Plotly, and a
# hovertemplate is the one string a hand-drawn tooltip does not need.
_HOVER = (
    "a Plotly hovertemplate; the SVG chart's tooltip makes the same claim about "
    "the same figure"
)

PAGES: dict[str, Page] = {
    "home": Page(
        streamlit="home.py",
        waived={
            "home.spark_hover_tmpl": _HOVER,
            "earnings.dialog_title": (
                "the earnings chip opens the ticker's own page instead of a "
                "result dialog — the figures behind it are per-ticker and that "
                "page already shows all of them (Earnings.tsx)"
            ),
        },
    ),
    "portfolio": Page(
        streamlit="portfolio.py",
        waived={
            "portfolio.hist_hover_tmpl": _HOVER,
            "portfolio.hover_correlation": _HOVER,
            "portfolio.hover_portfolio_twr": _HOVER,
            "portfolio.hover_current_basket": _HOVER,
            "portfolio.report_failed": (
                "same: a risk report that did not build is a failed query, and "
                "the shell already has a screen for one"
            ),
            "portfolio.all_columns": (
                "an expander over a second, wider copy of the table above it. "
                "The React table is the wide one — every column that expander "
                "held is already on screen and sortable, so a fold over it "
                "would hide nothing and reveal nothing"
            ),
            "portfolio.all_columns_realized": "…the same, over the realized rows",
            "portfolio.demo_seeded_toast": (
                "no toast: the banner that replaces the offer is the "
                "acknowledgement, and it stays for as long as the claim is true"
            ),
        },
    ),
    "sentiment": Page(
        streamlit="sentiment.py",
        waived={
        },
    ),
    "sector": Page(
        streamlit="sector.py",
        waived={
        },
    ),
    "earnings": Page(streamlit="earnings.py"),
    "import": Page(
        streamlit="import_transactions.py",
        waived={
            "import.paste_blocked": (
                "names a Streamlit failure: a browser that drops the "
                "`_streamlit_xsrf` cookie 403s on /_stcore/upload_file and the "
                "page is handed 'no file'. The React uploader POSTs to "
                "`/api/v1`, where that failure mode does not exist"
            ),
        },
    ),
    # Nothing waived and nothing pending: the page is small, and the React one
    # says every string the Streamlit one does — including the toast, which is
    # a line on the page here because there is no rerun to drop it.
    "bank": Page(streamlit="bank.py"),
    "profile": Page(
        streamlit="profile.py",
        waived={
            "profile.currency_set": (
                "no toast: every control writes itself and shows its new state, "
                "which is the acknowledgement the strip beside the tabs promises"
            ),
            "profile.iv_saved": "…same",
            "profile.tax_set": "…same",
            "profile.delete_done": (
                "the React flow redirects to `/auth/logout` the moment the "
                "DELETE lands — there is no page left to congratulate anyone "
                "on, and the Streamlit page's own comment says it copied the "
                "shape from it"
            ),
        },
    ),
}


def _sources(*roots: Path) -> list[Path]:
    """Every TypeScript source under these roots, tests excluded.

    A test builds catalogs of its own and asserts on keys that are *meant* not
    to exist — a missing string has to fall back to its key, and something has
    to prove it does. Counting those would make this file fail for the one file
    whose job is that proof.
    """
    return [
        path
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.suffix in {".ts", ".tsx"}
        and "__tests__" not in path.parts
        and not path.name.endswith((".test.ts", ".test.tsx"))
    ]


def _react_text(slug: str) -> str:
    """The page's own directory plus the shell.

    The shell is included because a string it prints for this page — the nav,
    the sign-in screen, an error banner, the tour — is still a string this page
    says. `src/chat/` rides along for the same reason: the drawer is mounted
    over every page.
    """
    roots = [FRONTEND / "pages" / slug, FRONTEND / "shell", FRONTEND / "chat"]
    return "\n".join(path.read_text() for path in _sources(*roots))


def _said(slug: str) -> set[str]:
    """Keys the React page names, literally or as the stem of a family.

    Both sides build some keys out of a value: `tr("profile.iv_risk_" + risk)`
    over here, `` t(`profile.iv_risk_${profile.risk}`) `` over there. Each is
    recorded as its stem, and two stems match when they are the same string.

    Matching stems by `startswith` instead would be a false pass waiting to
    happen — `` t(`profile.iv_${group}_${option}`) `` yields the stem
    `profile.iv_`, which swallows `profile.iv_saved` and `profile.iv_persona_help`
    and every other key on that page beginning that way. Whether each option in
    a family has a string is `test_frontend_i18n_keys`' question, not this
    file's; this file only asks whether the family is drawn at all.
    """
    text = _react_text(slug)
    return set(re.findall(r'"([a-z][a-z0-9_]*\.[a-z0-9_.]+)"', text)) | set(
        re.findall(r"t\(`([a-z][\w.]*?)\$", text)
    )


def _app_keys(page: Page) -> set[str]:
    """Every string the Streamlit page prints, a built family counting as its
    stem — `tr("profile.iv_risk_" + …)` is `profile.iv_risk_`, which is what the
    React side records for the same call."""
    source = (APP_PAGES / page.streamlit).read_text()
    return set(re.findall(r'tr\(\s*"([\w.]+)"', source))


@pytest.mark.parametrize("slug", sorted(PAGES))
def test_the_streamlit_page_still_has_strings_to_compare(slug: str):
    """A page rewritten into a shape this regex cannot read would otherwise
    pass by saying nothing at all."""
    assert len(_app_keys(PAGES[slug])) > 15, (
        f"{PAGES[slug].streamlit} prints almost nothing through `tr(...)` — "
        "the page's shape changed and this harness is no longer reading it"
    )


@pytest.mark.parametrize("slug", sorted(PAGES))
def test_every_string_the_app_prints_is_said_or_written_down(slug: str):
    page = PAGES[slug]
    app_keys = _app_keys(page)
    known = _said(slug) | set(page.waived) | set(page.pending)
    unsaid = sorted(key for key in app_keys if key not in known)
    assert not unsaid, (
        f"the Streamlit {slug} page prints these and the React one does not: "
        f"{unsaid}. Say them, or write each into `waived` (a decision) or "
        "`pending` (a gap) with a reason."
    )


@pytest.mark.parametrize("slug", sorted(PAGES))
def test_every_waiver_and_gap_carries_a_reason(slug: str):
    page = PAGES[slug]
    blank = sorted(
        key
        for key, reason in (page.waived | page.pending).items()
        if not reason.strip()
    )
    assert not blank, f"{slug}: written down with no reason: {blank}"


@pytest.mark.parametrize("slug", sorted(PAGES))
def test_nothing_is_written_down_twice(slug: str):
    """A key cannot be both a decision and a gap."""
    page = PAGES[slug]
    both = sorted(set(page.waived) & set(page.pending))
    assert not both, f"{slug}: in both `waived` and `pending`: {both}"


@pytest.mark.parametrize("slug", sorted(PAGES))
def test_the_lists_do_not_rot(slug: str):
    """Two ways a written-down key goes stale, both of which hide real drift.

    A key the Streamlit page no longer prints keeps a dead entry alive, and the
    next reader trusts it. A key the React page *now says* keeps a gap on the
    books after somebody closed it — and a `pending` list that never shrinks is
    one nobody believes.
    """
    page = PAGES[slug]
    app_keys = _app_keys(page)
    written = page.waived | page.pending
    gone = sorted(key for key in written if key not in app_keys)
    assert not gone, (
        f"{slug}: written down but the Streamlit page no longer prints them: "
        f"{gone}. Delete the entries."
    )
    said = _said(slug)
    closed = sorted(key for key in written if key in said)
    assert not closed, (
        f"{slug}: written down and the React page says them anyway: {closed}. "
        "Delete the entries — they are done."
    )


# ------------------------------------------------------- the client still fits


@pytest.mark.parametrize("slug", sorted(PAGES))
def test_every_endpoint_the_page_calls_exists_on_the_server(slug: str):
    """TypeScript checks the shape a call expects and nothing at all about the
    path it asks for, so a route renamed underneath a page fails at runtime,
    on that page, for that reader."""
    # Call sites only, rather than every path-shaped literal in the file: this
    # scan reads the chat drawer too, and `src/chat/markdown.tsx` is full of
    # regular expressions that begin with a slash.
    text = _react_text(slug).replace("${at(ticker)}", "/ticker/{p}")
    called = set()
    for raw in re.findall(r"\b(?:get|send)\s*(?:<[^(]*>)?\(\s*[`\"](/[^`\"]+)", text):
        # `${encodeURIComponent(ticker)}` and friends are one path parameter.
        called.add(re.sub(r"\$\{[^}]*\}", "{p}", raw))
    served = {
        re.sub(r"\{[^}]*\}", "{p}", path.removeprefix("/v1"))
        for path in fastapi_app.openapi()["paths"]
    }
    # A path that is the *prefix* of a real route is a builder, not a call —
    # `/ticker/{p}` is where every one of that page's calls starts. Failing on
    # it would only teach somebody to stop scanning that file.
    unknown = sorted(
        path
        for path in called
        if path not in served
        and not any(route.startswith(f"{path}/") for route in served)
    )
    assert not unknown, f"the {slug} page calls paths the API does not serve: {unknown}"
