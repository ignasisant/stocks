"""Extra comparables on the Ticker page are picked, not typed.

The field used to be "comma-separated tickers": the symbol had to be known by
heart, and a typo simply produced an empty column. It now mounts the top bar's
live search a second time, so the same catalogs (watchlist, coins, funds, SEC
map, worldwide Yahoo) answer inside the comps card. These pin the parts that
made one component serve two very different hosts.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import streamlit as st

from stocks.web import search

PAGE = Path("src/stocks/web/app_pages/ticker.py").read_text()


def test_candidate_label_names_the_tier():
    watch = search.candidate_label({"ticker": "NVDA", "name": "Nvidia", "kind": "watch"})
    world = search.candidate_label(
        {"ticker": "MIPS.ST", "name": "MIPS AB · Stockholm", "kind": "world"}
    )
    assert watch == ":material/check_circle: **NVDA** — Nvidia"
    assert world == ":material/public: **MIPS.ST** — MIPS AB · Stockholm"


def test_candidate_label_survives_a_nameless_row():
    """The "raw" tier is a symbol no catalog knows, so it carries no name."""
    assert search.candidate_label({"ticker": "ZZQQ", "name": "", "kind": "raw"}) == (
        ":material/help: **ZZQQ**"
    )


def test_clear_picker_raises_the_flag_the_component_reads():
    """Dropping the session value alone loses the race with the frontend,
    which re-sends its stored query on the next rerun."""
    search.clear_picker("xpeerq_AAPL")
    assert st.session_state["xpeerq_AAPL_blur"] is True


def test_page_field_keeps_its_placeholder_on_a_phone():
    """The 44px magnifier state belongs to the top bar alone — a field in the
    page body has room, and a lone glyph there explains nothing."""
    js_css = inspect.getsource(search._live_search_component)
    assert ".lsi.lsc:not(:focus):placeholder-shown {" in js_css
    assert 'input.classList.toggle("lsc", !!(data && data.collapse))' in js_css


def test_only_a_field_with_results_registers_the_row_closer():
    """Both fields render on the Ticker page; a shared document-level listener
    would leave whichever mounted last closing the other one's dropdown."""
    js_css = inspect.getsource(search._live_search_component)
    assert 'const prop = "__lsRowCloser_" + rkey' in js_css
    assert "if (!rkey) return" in js_css


def test_comparables_no_longer_parse_a_comma_list():
    assert "extra.split(" not in PAGE
    assert "_extra_peers(ticker, peers)" in PAGE
