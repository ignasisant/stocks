"""SEC frames: aliases, one value per company, gap filling, TTL."""

from __future__ import annotations

import urllib.error
from datetime import date

import pytest

from stocks.data import edgar, frames

AAPL, NVDA, GOOGL = 320193, 1045810, 1652044


def row(cik, val, end="2025-09-27"):
    return {"cik": cik, "val": val, "end": end, "accn": "x", "entityName": "n"}


# Trimmed from live frames probes: Apple files only the contract-revenue tag,
# Alphabet files both (the larger total wins), Nvidia's year ends in January.
FRAMES = {
    "Revenues": [row(GOOGL, 402_836_000_000, "2025-12-31"),
                 row(NVDA, 215_938_000_000, "2026-01-25")],
    "RevenueFromContractWithCustomerExcludingAssessedTax": [
        row(AAPL, 416_161_000_000), row(GOOGL, 350_000_000_000, "2025-12-31"),
        row(99, 5.0)],
    "NetIncomeLoss": [row(AAPL, 112_010_000_000),
                      row(NVDA, 120_067_000_000, "2026-01-25"),
                      row(GOOGL, 132_170_000_000, "2025-12-31")],
    "NetCashProvidedByUsedInOperatingActivities": [row(AAPL, 111_482_000_000)],
    "PaymentsToAcquirePropertyPlantAndEquipment": [row(AAPL, 12_715_000_000)],
    "StockholdersEquity": [row(AAPL, 73_733_000_000),
                           row(NVDA, 157_293_000_000, "2026-01-25")],
    "EntityCommonStockSharesOutstanding": [row(AAPL, 14_776_353_000, "2026-04-17")],
}


def fake_get(url: str) -> dict:
    tag = url.split("/")[-3]
    if tag not in FRAMES:
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)  # type: ignore[arg-type]
    return {"data": FRAMES[tag]}


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(frames, "_get", fake_get)
    monkeypatch.setattr(frames.time, "sleep", lambda s: None)
    monkeypatch.setattr(frames, "MIN_POINTS", 2)
    monkeypatch.setattr(edgar, "_cik_map", lambda: {
        "AAPL": "0000320193", "NVDA": "0001045810", "GOOGL": "0001652044"})


def test_alias_and_max_rule(stub):
    revenue = next(c for c in frames.CONCEPTS if c.key == "revenue")
    values, points = frames._frame(revenue, "CY2025", None, 0)
    assert values[AAPL][0] == 416_161_000_000  # second alias only
    assert values[GOOGL][0] == 402_836_000_000  # the larger of two tags
    assert points == 3


def test_wanted_filter_and_404_is_empty(stub):
    capex = next(c for c in frames.CONCEPTS if c.key == "capex")
    values, _ = frames._frame(capex, "CY2025", {NVDA}, 0)
    assert values == {}  # the second tag 404s, no raise


def test_refresh_stores_known_ciks(stub):
    payload = frames.refresh(date(2026, 10, 28), pause=0)
    assert set(payload["rows"]) == {str(AAPL), str(NVDA), str(GOOGL)}
    assert payload["rows"][str(AAPL)]["shares"][0] == 14_776_353_000
    assert frames.load()["fetched"] == "2026-10-28"
    assert frames.figures("AAPL")["capex"] == 12_715_000_000


def test_year_falls_back_when_probe_is_thin(monkeypatch, stub):
    monkeypatch.setattr(frames, "MIN_POINTS", 3)

    def early_year(url):  # January: CY2025 has barely begun filling in
        if "CY2025.json" in url:
            return {"data": FRAMES["NetIncomeLoss"][:1]}
        return fake_get(url)

    monkeypatch.setattr(frames, "_get", early_year)
    payload = frames.refresh(date(2026, 1, 5), pause=0)
    assert payload["periods"]["net_income"] == "CY2024"


def test_fill_row_only_gaps_and_usd():
    f = {"revenue": 100.0, "net_income": 10.0, "equity": 50.0, "shares": 10.0,
         "op_cash_flow": 30.0, "capex": 10.0}
    filled = {"price": 20.0, "currency": "USD", "pe_ttm": 99.0}
    keys = frames.fill_row(filled, f)
    assert filled["pe_ttm"] == 99.0 and "pe_ttm" not in keys
    assert filled["market_cap"] == 200.0
    assert filled["fcf"] == 20.0 and filled["pb"] == 4.0 and filled["roe"] == 0.2
    assert frames.fill_row({"price": 20.0, "currency": "EUR"}, f) == []


def test_ensure_ttl_and_stale_fallback(stub, monkeypatch):
    frames.refresh(date(2026, 10, 1), pause=0)
    calls = []
    monkeypatch.setattr(frames, "_get", lambda u: calls.append(u) or fake_get(u))
    assert frames.ensure(date(2026, 10, 20))["fetched"] == "2026-10-01"
    assert calls == []

    def boom(url):
        raise ConnectionError("down")

    monkeypatch.setattr(frames, "_get", boom)
    assert frames.ensure(date(2026, 12, 1))["fetched"] == "2026-10-01"


def test_fill_gaps_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(frames, "ensure", boom)
    assert frames.fill_gaps([{"ticker": "AAPL"}]) == 0


def test_fill_gaps_counts(stub):
    payload = frames.refresh(date(2026, 10, 28), pause=0)
    rows = [{"ticker": "AAPL", "price": 200.0, "currency": "USD", "roe": None}]
    assert frames.fill_gaps(rows, payload) > 0
    assert rows[0]["roe"] == pytest.approx(112_010_000_000 / 73_733_000_000)
