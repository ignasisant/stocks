"""The sector screen: what it shows before a scan exists, and after one does.

The page has three states worth pinning — no scan at all, a scan whose cohort
was too thin to rank, and a full one — and in every case the two slots it
reserves before fetching (the verdict, the table) must end up resolved. An
unresolved slot shimmers forever, silently, which no exception reports.

The verdict itself is `test_sector_ai.py`'s subject. Here it is stubbed out:
what matters on the page is that a sector with no podium clears the slot
instead of leaving it spinning, and that a signed-out reader still gets the
computed stand-in rather than nothing.
"""

import json

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stocks.analysis.sectors import SectorScan

PAGE = "src/stocks/web/app_pages/sector.py"
# An unresolved slot still shimmers. The empty card's ghost *preview* uses the
# same markup on purpose, so the scenarios that draw one check their slot a
# different way.
SKELETON_MARKER = "topstocks-sk"

_QUALITY = ("roe", "roic", "gross_margin", "op_margin", "net_margin", "fcf_yield")


def _text(at) -> str:
    """Every line of prose the page produced — headings included.

    st.subheader lands in `at.subheader`, not `at.markdown`, and a test that
    only reads the latter silently stops covering the section titles.
    """
    parts = [*at.markdown, *at.subheader, *at.title, *at.caption]
    return "".join(str(el.value) for el in parts)


def _metrics(tickers):
    return tuple(
        {"ticker": t, "quote_type": "EQUITY", "pe_ttm": 20.0 + i,
         **{k: 0.5 - i * 0.05 for k in _QUALITY}}
        for i, t in enumerate(tickers)
    )


def _scan(tickers=("AAPL", "MSFT", "NVDA", "ASML.AS"), podium=("AAPL", "MSFT", "NVDA")):
    return SectorScan(
        sector="Technology",
        as_of="2026-09-18",
        tickers=tuple(tickers),
        metrics=_metrics(tickers),
        scores={t: 0.9 - i * 0.1 for i, t in enumerate(tickers)},
        podium=tuple(podium),
    )


@pytest.fixture
def page(monkeypatch, tmp_path):
    """Run the page against a stored scan of our choosing, offline.

    `st.cache_data` entries outlive a run inside one process, so the cache is
    cleared before each: without that the first scenario's scan is the only
    one any of them ever sees.
    """
    from stocks.analysis import sectors
    from stocks.web import auth

    state = {"scans": {}, "logged_in": False}

    monkeypatch.setattr(sectors, "load_scan", lambda **kw: dict(state["scans"]))
    monkeypatch.setattr(sectors.storage, "enabled", lambda: False)
    monkeypatch.setattr(auth, "is_logged_in", lambda: state["logged_in"])
    monkeypatch.setattr(auth, "load_verdicts", lambda *a, **kw: {})
    monkeypatch.setattr(auth, "load_prefs", lambda *a, **kw: {"language": "en"})
    monkeypatch.setattr(
        "stocks.web.portfolio_data.held_tickers", lambda db, mtime: []
    )
    monkeypatch.setattr("stocks.web.portfolio_data.db_mtime", lambda db: 0.0)

    paths = auth.paths_for("reader@example.com", users_dir=tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.prefs.write_text(json.dumps({"language": "en"}))
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(auth, "resolve_user", lambda: paths)

    def _run(scans=None, logged_in=False) -> tuple[AppTest, str]:
        state["scans"] = scans if scans is not None else {}
        state["logged_in"] = logged_in
        st.cache_data.clear()
        at = AppTest.from_file(PAGE, default_timeout=120)
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        return at, "".join(str(el.body) for el in at.get("html"))

    return _run


# ------------------------------------------------------------- nothing yet


def test_no_scan_offers_to_build_one(page):
    at, html = page()
    assert "No sector scan yet" in _text(at)
    # The way out is a button, not a link to another page: the thing that
    # fixes this lives here.
    assert any("Refresh this sector" in b.label for b in at.button)
    # Both slots resolved: the table's holds the card (whose ghost preview is
    # the only skeleton markup left), and the verdict's was cleared outright.
    assert "sk-table" in html and "ag-sv" not in html


def test_the_picker_offers_every_sector(page):
    at, _ = page()
    assert len(at.selectbox[0].options) == 11


def test_a_sector_with_no_scan_of_its_own_is_still_empty(page):
    at, _ = page({"Energy": _scan()})  # the picker defaults to Technology
    assert "No sector scan yet" in _text(at)


# ------------------------------------------------------------ a real cohort


def test_a_scanned_sector_shows_its_podium_and_its_table(page):
    at, html = page({"Technology": _scan()})
    assert SKELETON_MARKER not in html  # every reserved slot resolved
    assert "Best three on this screen" in _text(at)
    assert "The whole cohort" in _text(at)
    # Numbered badges, not emoji medals: 🥇 renders as an OS sticker that does
    # not belong in a flat dark palette, and the written read numbers the
    # places the same way.
    assert 'class="ag-pod-n ag-pod-1"' in html
    assert html.count('class="ag-pod-n"') == 2
    # Every ticker on screen is a link to its page — the project's rule.
    assert 'href="ticker?ticker=AAPL"' in html


def test_the_podium_comes_before_the_table(page):
    """The reason to open this page must not sit under seventeen rows.

    It did: both slots were reserved up front, so `_table.container()` filled
    a position above the podium that was created after it. Nothing caught that
    — presence assertions pass in any order.
    """
    _, html = page({"Technology": _scan()})
    podium = html.index("ag-pod-score")
    table = html.index("Download raw numbers") if "Download raw numbers" in html else -1
    assert podium < html.index("agr-row"), "the cohort rows precede the podium"
    if table > 0:
        assert podium < table


def test_the_podium_says_what_each_place_rests_on(page):
    """A rank with no figures under it asks to be taken on faith."""
    _, html = page({"Technology": _scan()})
    assert "ag-pod-why" in html
    assert "/100" in html  # the score, on one scale across the whole page


def test_the_cohort_names_the_etf_it_came_from(page):
    at, _ = page({"Technology": _scan()})
    assert "XLK" in _text(at) and "4 companies" in _text(at)


def test_the_podium_says_what_it_does_not_measure(page):
    """A medal invites "these are the best stocks"; the help text is the only
    thing standing between the reader and that reading."""
    at, _ = page({"Technology": _scan()})
    assert "relative to this cohort" in _text(at)
    assert "neither momentum nor what analysts expect" in _text(at)


def test_a_cohort_too_thin_to_rank_still_resolves_every_slot(page):
    at, html = page({"Technology": _scan(tickers=("AAPL", "MSFT"), podium=())})
    assert SKELETON_MARKER not in html
    assert "Too few companies" in _text(at)


def test_the_table_carries_the_screen_controls(page):
    at, _ = page({"Technology": _scan()})
    labels = [s.label for s in at.selectbox]
    assert "Rank by" in labels
    assert "of 4 companies pass" in _text(at)


def test_the_download_is_named_after_the_sector(page):
    page({"Technology": _scan()})  # the button exists; its file name is the point
    from stocks.analysis.sentiment import SECTOR_ETFS

    assert "Technology" in SECTOR_ETFS


# ---------------------------------------------------------------- the verdict


def test_a_signed_out_reader_still_gets_the_computed_read(page):
    at, html = page({"Technology": _scan()}, logged_in=False)
    assert "What the screen says" in _text(at)
    assert "leads the Technology screen" in html
    assert "Sign in" in html  # ...and is told what signing in would add


def test_the_verdict_never_takes_the_page_down(page, monkeypatch):
    """No paragraph is worth the podium and the table."""
    from stocks.web import sector_ui

    monkeypatch.setattr(sector_ui, "_render",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    at, html = page({"Technology": _scan()})
    assert SKELETON_MARKER not in html
    assert "Best three on this screen" in _text(at)
