"""The Pulse page's staged load: every reserved slot resolved, whatever dies.

The page reserves a skeleton for each block before it fetches anything and
fills each one as the source it waits on lands. That only works if every path
out of a slot ends in content or an explanation — an unresolved slot shimmers
forever, and it does so silently, which is exactly the kind of bug no exception
reports.

Each scenario below kills one source and asserts three things: no skeleton
survives the run, the four section headings are still there, and the blocks
that lost their source say which source it was. A dead source must cost its own
block's contents and nothing else.
"""

import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from yfinance.exceptions import YFRateLimitError

from stocks.analysis import sentiment as sm
from stocks.data import macro

PAGE = "src/stocks/web/app_pages/sentiment.py"
SKELETON_MARKER = "topstocks-sk"
# The four headings the reader navigates by: why, the trend snapshot, their own
# book, and the detail tabs. The hero is titled by its score, not a heading.
HEADINGS = ("ag-why", "ag-snapshot", "ag-book", "ag-detail")
# Six tabs, and the rotation one carries a second table under the first.
TABLES = 7

# Enough history for the trailing-year percentiles and the 200-session trend
# average the page asks for.
SESSIONS = 400


def _tape(seed: int) -> pd.Series:
    """A deterministic price path — a drift plus a wobble, never flat.

    Flat series would make every percentile a tie and every trend "unknown",
    which is not the shape this page is being tested against.
    """
    index = pd.bdate_range("2024-01-01", periods=SESSIONS)
    steps = np.sin(np.linspace(0, 12 + seed, SESSIONS)) / 200 + 0.0004
    return pd.Series(100 * np.cumprod(1 + steps), index=index, dtype=float)


def _fake_closes(tickers, period="1y"):
    return {t: _tape(i) for i, t in enumerate(tickers)}


def _fake_fred(sids, **_kw):
    return {sid: _tape(i) / 20 for i, sid in enumerate(sids)}


def _fake_inflation(*_a, **_kw):
    return pd.DataFrame(
        [
            {
                "area": area, "period": "2026-08", "headline": 3.0 + i * 0.2,
                "core": 2.4, "prior": 2.9, "six_months": 1.9, "momentum": 1.1,
                "path": [1.9 + j * 0.1 for j in range(14)],
            }
            for i, area in enumerate(macro.INFLATION_AREAS)
        ]
    )


@pytest.fixture
def page(monkeypatch):
    """Run the page against synthetic sources and hand back its rendered HTML.

    Every network source is stubbed by default and each test below breaks one
    of them, so the scenarios are deterministic and the suite stays offline —
    the thing under test is which slots get resolved, not what the market did.

    `st.cache_data` entries outlive a run inside one process, so the cache is
    cleared before each: without that a stubbed loader is never called and
    every scenario silently re-reads the first one's data.
    """
    monkeypatch.setattr("stocks.analysis.portfolio.load_closes", _fake_closes)
    monkeypatch.setattr("stocks.analysis.portfolio.load_meta", lambda t, **k: {})
    monkeypatch.setattr("stocks.data.macro.fred_many", _fake_fred)
    monkeypatch.setattr("stocks.data.macro.inflation", _fake_inflation)
    monkeypatch.setattr("stocks.data.funds.sector_weights", lambda t: {})

    def _run() -> tuple[AppTest, str]:
        st.cache_data.clear()
        at = AppTest.from_file(PAGE, default_timeout=120)
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        return at, "".join(str(el.body) for el in at.get("html"))

    return _run


def test_the_fixture_covers_every_symbol_the_page_asks_for():
    """A stub that misses a registry entry would fake a partial outage."""
    assert set(_fake_closes(sm.all_tickers())) == set(sm.all_tickers())


def _rows(markup: str) -> int:
    """Trend rows in the markup. Dimmed rows carry a second class, so they are
    counted separately rather than slipping past the exact-attribute match."""
    return markup.count('class="ag-trend-row"') + markup.count(
        'class="ag-trend-row ag-dim"'
    )


def _headings(markup: str) -> list[str]:
    return [anchor for anchor in HEADINGS if f'id="{anchor}"' in markup]


def test_every_slot_resolves_when_all_sources_answer(page):
    at, markup = page()
    assert SKELETON_MARKER not in markup
    assert _headings(markup) == list(HEADINGS)
    # Six tabs, each holding its own table, and every row on the page shares
    # the one layout.
    assert len(at.get("tab")) == 6
    assert markup.count('class="ag-trend-head"') == TABLES
    assert _rows(markup) > 40
    # The composite explains itself: one bar per input, and the pin on the
    # 0-100 meter it is scored against.
    assert markup.count('class="ag-comp-row"') == len(sm.COMPONENT_KEYS)
    assert 'class="ag-meter-pin"' in markup
    # Every row says what it is on hover. The names here are jargon — VIX,
    # 2s10s, RSP over SPY — so a registry entry shipped without tip copy is a
    # row the reader cannot read, and that is what this count catches.
    assert markup.count('class="ag-trend-i"') == _rows(markup)


def test_a_throttled_price_host_names_the_source_it_lost(page, monkeypatch):
    """Yahoo throttles datacenter IPs routinely; most of the page needs it."""
    def _throttled(*_a, **_kw):
        raise YFRateLimitError

    monkeypatch.setattr("stocks.analysis.portfolio.load_closes", _throttled)
    at, markup = page()
    assert SKELETON_MARKER not in markup
    # The page keeps its shape and says which host is down, not merely that
    # something is: a Yahoo throttle clears in a minute, a FRED outage does not.
    assert _headings(markup) == list(HEADINGS)
    assert "Yahoo Finance" in markup
    assert markup.count('class="ag-down"') >= 4
    # Rates come from FRED and are untouched by a price outage.
    assert _rows(markup) >= len(macro.INFLATION_AREAS)


def test_dead_fred_costs_only_the_rates_tab(page, monkeypatch):
    def _dead(*_a, **_kw):
        raise OSError("fred unreachable")

    monkeypatch.setattr("stocks.data.macro.fred_many", _dead)
    at, markup = page()
    assert SKELETON_MARKER not in markup
    assert _headings(markup) == list(HEADINGS)
    # The composite survives: its credit leg falls back to the ETF proxy, so
    # the score is still quoted and only the rates tab is empty.
    assert 'class="ag-meter-pin"' in markup
    assert _rows(markup) > 25


def test_dead_eurostat_costs_only_the_inflation_tab(page, monkeypatch):
    def _dead(*_a, **_kw):
        raise OSError("eurostat unreachable")

    monkeypatch.setattr("stocks.data.macro.inflation", _dead)
    at, markup = page()
    assert SKELETON_MARKER not in markup
    assert _headings(markup) == list(HEADINGS)
    assert _rows(markup) > 35


def test_an_empty_price_result_also_resolves_the_slots(page, monkeypatch):
    """The third failure path: a fetch that raises nothing and returns nothing.

    Neither except branch sees this one, and it is what a symbol list that
    Yahoo answers with empty frames produces.
    """
    monkeypatch.setattr("stocks.analysis.portfolio.load_closes", lambda *a, **k: {})
    _at, markup = page()
    assert SKELETON_MARKER not in markup
    assert _headings(markup) == list(HEADINGS)


def test_an_anonymous_visitor_is_invited_rather_than_shown_a_zero(page):
    """The personal half has no honest empty state, so it asks for the import.

    A beta of 1.00 and a dollar share of 0% are what an empty book would
    average to, and printing them would be a lie the reader cannot see.
    """
    _at, markup = page()
    assert 'class="ag-invite"' in markup
    # No invented figures where the reader's own numbers would be.
    assert 'class="ag-bk-tile"' not in markup


def test_a_signed_in_account_with_no_positions_gets_the_import_path(
    page, monkeypatch, tmp_path
):
    monkeypatch.setattr("stocks.web.auth.is_logged_in", lambda: True)
    monkeypatch.setattr(
        "stocks.web.portfolio_data.ledger_state",
        lambda *_a, **_k: (pd.DataFrame(), []),
    )
    monkeypatch.setattr("stocks.web.portfolio_data.db_mtime", lambda _db: 0.0)
    monkeypatch.setattr(
        "stocks.web.auth.user_paths",
        lambda: type("P", (), {"db": tmp_path / "stocks.db"})(),
    )
    _at, markup = page()
    assert SKELETON_MARKER not in markup
    assert 'class="ag-invite"' in markup
