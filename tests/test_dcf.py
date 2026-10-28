"""The DCF card: the formula, its refusals, and the route that serves it."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks.analysis import dcf
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.data.fundamentals import RawFundamentals

FIXTURE = (
    Path(__file__).parent.parent
    / "frontend/app/src/pages/ticker/dcf.fixture.json"
)


def test_hand_computed_case_to_1e9():
    # Written out term by term, independent of the loop in the module.
    f = 100.0
    flows = [f * 1.1**t for t in range(1, 6)]
    pv = sum(c / 1.1**t for t, c in enumerate(flows, start=1))
    terminal = flows[-1] * 1.02 / (0.10 - 0.02) / 1.1**5
    want = (pv + terminal - 50) / 10
    got = dcf.value_per_share(100, 0.10, 0.10, 0.02, 50, 10)
    assert got is not None
    assert abs(got - want) < 1e-9
    assert abs(got - 172.5) < 1e-9


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text())["cases"])
def test_shared_fixture(case):
    got = dcf.value_per_share(
        case["fcf"], case["growth"], case["wacc"], case["terminal"],
        case["net_debt"], case["shares"],
    )  # fmt: skip
    if case["value"] is None:
        assert got is None
    else:
        assert got is not None and abs(got - case["value"]) < 1e-9


def test_negative_or_zero_fcf_is_none():
    assert dcf.value_per_share(-1, 0.05, 0.09, 0.02, 0, 10) is None
    assert dcf.value_per_share(0, 0.05, 0.09, 0.02, 0, 10) is None


def test_terminal_at_or_above_wacc_is_refused():
    assert dcf.value_per_share(100, 0.05, 0.03, 0.03, 0, 10) is None
    assert dcf.value_per_share(100, 0.05, 0.03, 0.04, 0, 10) is None


def test_monotone_in_wacc_and_terminal():
    waccs = [dcf.value_per_share(100, 0.06, w, 0.025, 0, 10) for w in dcf.WACC_GRID]
    assert all(a > b for a, b in zip(waccs, waccs[1:], strict=False))
    gs = [dcf.value_per_share(100, 0.06, 0.09, g, 0, 10) for g in dcf.TERMINAL_GRID]
    assert all(a < b for a, b in zip(gs, gs[1:], strict=False))


def test_default_growth_is_clipped():
    assert dcf.default_growth({"fcf_cagr": 0.6}) == (0.15, "fcf_cagr")
    assert dcf.default_growth({"fcf_cagr": -0.2}) == (0.0, "fcf_cagr")
    assert dcf.default_growth({"revenue_cagr": 0.07}) == (0.07, "revenue_cagr")
    assert dcf.default_growth({}) == (dcf.GROWTH_FALLBACK, "fallback")


def _raw(**info) -> RawFundamentals:
    cols = [pd.Timestamp("2025-12-31")]
    return RawFundamentals(
        ticker="ACME",
        info={"currency": "USD", "financialCurrency": "USD", **info},
        income=pd.DataFrame(
            {cols[0]: [10.0, 0.2, 2.0]},
            index=["Diluted Average Shares", "Tax Rate For Calcs", "Interest Expense"],
        ),
        balance=pd.DataFrame({cols[0]: [30.0]}, index=["Net Debt"]),
    )


def _metrics(**over):
    base = {
        "ticker": "ACME", "currency": "USD", "quote_type": "EQUITY",
        "industry": "Software - Application", "price": 50.0, "fcf": 40.0,
        "fcf_cagr": 0.08,
    }  # fmt: skip
    return {**base, **over}


def test_compute_adds_back_after_tax_interest_and_nets_debt():
    out = dcf.compute(_raw(), _metrics())
    assert out.reason is None
    # 40 + 2 * (1 - 0.2): the cash the lenders were paid is the firm's.
    assert out.fcf == pytest.approx(41.6)
    assert out.net_debt == 30.0 and out.shares == 10.0
    want = dcf.value_per_share(41.6, 0.08, 0.09, 0.025, 30.0, 10.0)
    assert out.value == pytest.approx(want)
    assert out.upside == pytest.approx(want / 50 - 1)
    # The default cell is the grid's middle one.
    assert out.grid[2][2] == pytest.approx(out.value)


def test_pence_quote_values_in_pence():
    # A London line: GBP statements, price in GBp. The value must be pence too.
    pounds = dcf.compute(_raw(currency="GBP", financialCurrency="GBP"), _metrics())
    pence = dcf.compute(
        _raw(currency="GBp", financialCurrency="GBP"),
        _metrics(currency="GBp", price=5000.0),
    )
    assert pence.value == pytest.approx(pounds.value * 100)
    assert pence.upside == pytest.approx(pounds.upside)
    assert pence.grid[2][2] == pytest.approx(pence.value)


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"fcf": -3.0}, "negative_fcf"),
        ({"fcf": None}, "negative_fcf"),
        ({"industry": "Banks - Regional"}, "lens"),
        ({"industry": "REIT - Retail"}, "lens"),
        ({"industry": "Utilities - Regulated Electric"}, "lens"),
        ({"quote_type": "ETF"}, "not_equity"),
    ],
)
def test_refusals_give_a_reason_and_no_number(over, reason):
    out = dcf.compute(_raw(), _metrics(**over))
    assert out.reason == reason
    assert out.value is None and out.grid == []


def test_route(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "t")
    monkeypatch.setattr(loaders, "fundamentals", lambda t: _raw())
    monkeypatch.setattr(
        "stocks.api.routes.ticker.compute_metrics", lambda raw: _metrics()
    )
    res = TestClient(fastapi_app).get(
        "/v1/ticker/ACME/dcf", headers={"Authorization": "Bearer t"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["reason"] is None and body["value"] is not None
    assert len(body["grid"]) == 5 and len(body["grid"][0]) == 5
    assert body["waccs"][0] == 0.07 and body["terminals"][-1] == 0.035
