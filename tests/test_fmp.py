"""Financial Modeling Prep fallback client (stocks.data.fmp).

Nothing here touches the network — `get_json` is replaced. Pinned here so a
future FMP migration (like the one that retired `api/v3/` on 2025-08-31 and
left this client 402/403-ing silently for over a year, unit-tested by no one)
gets caught at the URL, not discovered a year later on a live ticker.
"""

from __future__ import annotations

import urllib.error

from stocks.data import fmp


def test_no_key_never_makes_a_request(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    called = []
    monkeypatch.setattr(fmp, "get_json", lambda url: called.append(url) or [])
    df = fmp.diluted_eps_facts("AAPL")
    assert df.empty and list(df.columns) == ["end", "filed", "eps", "kind"]
    assert called == []


def test_the_request_hits_the_current_stable_endpoint_within_the_free_cap(
    monkeypatch,
):
    """The legacy `api/v3/income-statement/{ticker}` path 403s unconditionally
    now, and `limit=40` 402s even on the current one — a free key's own
    ceiling is 5 quarters, key or no key, US ticker or not."""
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    seen = []
    monkeypatch.setattr(fmp, "get_json", lambda url: seen.append(url) or [])
    fmp.diluted_eps_facts("AAPL")
    assert len(seen) == 1
    url = seen[0]
    assert url.startswith("https://financialmodelingprep.com/stable/income-statement")
    assert "symbol=AAPL" in url
    assert "limit=5" in url
    assert "apikey=test-key" in url


def test_a_row_is_shaped_end_filed_eps_kind_from_the_stable_fields(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(
        fmp,
        "get_json",
        lambda url: [
            {
                "date": "2026-06-27",
                "filingDate": "2026-07-31",
                "eps": 2.04,
                "epsDiluted": 2.03,
            },
        ],
    )
    df = fmp.diluted_eps_facts("AAPL")
    assert list(df.columns) == ["end", "filed", "eps", "kind"]
    row = df.iloc[0]
    # Diluted first — same figure `edgar.diluted_eps_facts` reports, and the
    # one the P/E reconstruction is meant to divide the price by.
    assert row["eps"] == 2.03
    assert row["filed"] == "2026-07-31"
    assert row["kind"] == "Q"


def test_a_row_missing_epsdiluted_falls_back_to_the_basic_figure(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(
        fmp,
        "get_json",
        lambda url: [{"date": "2026-06-27", "filingDate": "2026-07-31", "eps": 2.10}],
    )
    df = fmp.diluted_eps_facts("AAPL")
    assert df.iloc[0]["eps"] == 2.10


def test_a_row_with_neither_date_nor_eps_is_dropped_not_crashed_on(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(
        fmp,
        "get_json",
        lambda url: [{"date": None, "eps": 2.0}, {"date": "2026-06-27", "eps": None}],
    )
    assert fmp.diluted_eps_facts("AAPL").empty


def test_a_paid_plan_s_402_or_a_retired_endpoint_s_403_degrades_to_empty(
    monkeypatch,
):
    """The free plan's own gates — a foreign symbol (KRX, an OTC ADR) 402s,
    a stale endpoint 403s — must read as "no data", not as a crash the P/E
    card has no story for."""
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    for code in (402, 403):
        def boom(url, code=code):
            raise urllib.error.HTTPError(url, code, "blocked", None, None)

        monkeypatch.setattr(fmp, "get_json", boom)
        assert fmp.diluted_eps_facts("005930.KS").empty


def test_a_non_list_body_is_not_mistaken_for_rows(monkeypatch):
    """FMP's error responses are a `dict` (an `Error Message` key), not a
    `list` — the shape a real payload always is."""
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    monkeypatch.setattr(fmp, "get_json", lambda url: {"Error Message": "blocked"})
    assert fmp.diluted_eps_facts("AAPL").empty
