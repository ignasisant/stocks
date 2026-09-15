"""Display names for holdings the ledger stores under a broker's label.

An ISIN or a local broker code prices correctly (fetch.resolve maps it through
watchlist.yaml `aliases`), but every *name* source keys on the Yahoo symbol —
so without the same resolution a real position renders as "US4131971040"
in the header, the tables and the sidebar.
"""

from __future__ import annotations

import json

import pytest

from stocks.data import edgar, fetch
from stocks.web import logos

FIXTURE = {
    "0": {
        "cik_str": 1802665,
        "ticker": "HRMY",
        "title": "Harmony Biosciences Holdings, Inc.",
    },
}

WATCHLIST = """\
watchlist:
  - ticker: HRMY
"""


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """SEC map from a fixture; the coin list and fund catalog say "not mine"."""
    cache = tmp_path / "edgar_tickers.json"
    cache.write_text(json.dumps(FIXTURE))
    monkeypatch.setattr(edgar, "TICKER_CACHE", cache)
    monkeypatch.setattr(edgar, "_CIK_MAP", None)
    monkeypatch.setattr(edgar, "_TITLE_MAP", None)
    monkeypatch.setattr(edgar, "_ROWS", None)
    monkeypatch.setattr("stocks.data.crypto.crypto_name", lambda t: None)
    monkeypatch.setattr("stocks.data.funds.fund_name", lambda t: None)
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {"US4131971040": "HRMY"})
    logos._company_name.clear()


def _watchlist(tmp_path, body: str = WATCHLIST) -> str:
    path = tmp_path / "watchlist.yaml"
    path.write_text(body)
    return str(path)


def test_isin_reads_as_the_company_it_identifies(tmp_path):
    assert (
        logos._company_name("US4131971040", _watchlist(tmp_path))
        == "Harmony Biosciences Holdings, Inc."
    )


def test_the_resolved_symbol_still_reads_the_same(tmp_path):
    assert (
        logos._company_name("HRMY", _watchlist(tmp_path))
        == "Harmony Biosciences Holdings, Inc."
    )


def test_a_name_set_on_the_broker_code_wins_over_the_sec_title(tmp_path):
    """Resolving must not reach past the account's own label for that entry."""
    body = "watchlist:\n  - ticker: US4131971040\n    name: Harmony (Revolut)\n"
    assert (
        logos._company_name("US4131971040", _watchlist(tmp_path, body))
        == "Harmony (Revolut)"
    )


def test_an_unknown_label_stays_nameless(tmp_path):
    assert logos._company_name("XX0000000000", _watchlist(tmp_path)) is None


# --------------------------------------------------------------- printed symbol


def test_a_cell_prints_the_resolved_symbol_and_links_the_stored_one(monkeypatch):
    """The ledger key travels in the href (the Ticker page matches positions
    against it); only the text the user reads is resolved."""
    from stocks.web import tables

    monkeypatch.setattr(tables, "logo", lambda t: None)
    monkeypatch.setattr(tables, "company_name", lambda t: None)
    cell = tables.ticker_cell("US4131971040")
    assert "<b>HRMY</b>" in cell
    assert "ticker=US4131971040" in cell
    assert ">US4131971040<" not in cell


def test_an_unmapped_label_prints_itself(monkeypatch):
    from stocks.web import tables

    monkeypatch.setattr(tables, "logo", lambda t: None)
    monkeypatch.setattr(tables, "company_name", lambda t: None)
    assert "<b>NVDA</b>" in tables.ticker_cell("NVDA")
