"""Golden tests: the lens KPIs against what each company's 10-K says.

One fixed US filer and one fiscal year per lens (see
`fixtures/edgar_10k_golden.json`, which carries the accession number, XBRL tag
and period of every figure so anyone can re-check it on SEC EDGAR). The 10-K
figures are fed to `compute_metrics` in the shape the feed hands them over
(yfinance-style statement frames, newest column first) and each KPI is asserted
against a number worked out by hand from the filing. Nothing here touches the
network: the only non-10-K input is a round share price, marked `assumed`.

Also pinned: the peer band's median and the 3-sigma outlier flag on a small
fixed peer set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from stocks.analysis import fundamentals as fnd
from stocks.analysis.review import FINANCIAL, REAL_ESTATE, STANDARD, UTILITY, lens
from stocks.data.fundamentals import RawFundamentals

FIXTURE = Path(__file__).parent / "fixtures" / "edgar_10k_golden.json"
LENSES = json.loads(FIXTURE.read_text())["lenses"]
TIGHT = 1e-9  # relative: the expected values below are exact arithmetic


def v(lens_name: str, fact: str) -> float:
    return float(LENSES[lens_name]["facts"][fact]["value"])


def frame(rows: dict[str, list[float | None]], years: list[str]) -> pd.DataFrame:
    """A yfinance-shaped statement: one row per label, columns newest-first."""
    return pd.DataFrame(rows, index=pd.to_datetime(years)).T


def raw_for(lens_name: str, **statements: pd.DataFrame) -> RawFundamentals:
    spec = LENSES[lens_name]
    price = spec["facts"]["price"]["value"]
    cap = v(lens_name, "cover_shares") * price
    return RawFundamentals(
        ticker=spec["ticker"],
        info={
            "currency": "USD",
            "financialCurrency": "USD",
            "currentPrice": price,
            "marketCap": cap,
            "industry": spec["industry"],
        },
        **statements,
    )


def approx(x: float) -> object:
    return pytest.approx(x, rel=TIGHT)


# ------------------------------------------------------------------ standard


@pytest.fixture(scope="module")
def msft() -> dict:
    ni = [v("standard", f"net_income_{y}") for y in (2024, 2023, 2022)]
    cfo = [v("standard", f"cfo_{y}") for y in (2024, 2023, 2022)]
    shares = [v("standard", f"diluted_shares_{y}") for y in (2024, 2023, 2022)]
    years = ["2024-06-30", "2023-06-30", "2022-06-30"]
    fcf = v("standard", "cfo_2024") - v("standard", "capex_2024")
    raw = raw_for(
        "standard",
        income=frame(
            {
                "Total Revenue": [v("standard", "revenue_2024"), None, None],
                "Net Income": ni,
                "Diluted Average Shares": shares,
            },
            years,
        ),
        cashflow=frame(
            {
                "Operating Cash Flow": cfo,
                "Free Cash Flow": [fcf, None, None],
                "Stock Based Compensation": [v("standard", "sbc_2024"), None, None],
            },
            years,
        ),
        balance=frame(
            {"Total Assets": [v("standard", "total_assets_2024"), None, None]}, years
        ),
    )
    return fnd.compute_metrics(raw)


def test_standard_lens_is_the_default(msft):
    assert lens(msft) == STANDARD
    assert fnd.fundamental_tiles(STANDARD) is fnd.FUNDAMENTAL_TILES


def test_standard_free_cash_flow_kpis_match_the_10k(msft):
    # FCF = 118,548 - 44,477 = 74,071 ($M); market cap = 7,433,038,381 x $400
    assert msft["fcf"] == approx(74_071e6)
    assert msft["fcf_yield"] == approx(0.024912759830938373)
    # owner's FCF takes the 10,734 of stock pay back off: 63,337
    assert msft["owner_fcf_yield"] == approx(0.021302526891929956)
    assert msft["fcf_margin"] == approx(0.2583896998229453)  # 63,337 / 245,122
    assert msft["sbc_fcf"] == approx(0.14491501397307988)  # 10,734 / 74,071
    assert msft["cash_conversion"] == approx(0.8404170826903876)  # 74,071 / 88,136


def test_standard_sales_multiple_share_count_and_cash_quality(msft):
    assert msft["ps"] == approx(12.129532854660129)  # cap / 245,122
    # diluted shares 7,540 -> 7,472 -> 7,469 over two years
    assert msft["share_dilution"] == approx(-0.004719358986291833)
    assert msft["accruals"] == approx(-0.05937953346883707)  # (88,136-118,548)/512,163
    # three years: (118,548+87,582+89,035) / (88,136+72,361+72,738)
    assert msft["cfo_ni"] == approx(1.2655261860355436)


# ----------------------------------------------------------------- financial


def bank_raw(*, tangible_row: bool) -> RawFundamentals:
    f = lambda k: v("financial", k)  # noqa: E731
    years = ["2022-12-31", "2021-12-31", "2020-12-31"]
    equity, pref = f("equity_2022"), f("preferred_2022")
    intang = f("goodwill_2022") + f("intangibles_2022")
    balance = {
        "Stockholders Equity": [equity, None, None],
        "Common Stock Equity": [equity - pref, None, None],
        "Goodwill And Other Intangible Assets": [intang, None, None],
    }
    if tangible_row:
        balance["Tangible Book Value"] = [equity - pref - intang, None, None]
    return raw_for(
        "financial",
        income=frame(
            {
                "Net Income": [f("net_income_2022"), None, None],
                "Net Income Common Stockholders": [
                    f("net_income_2022") - f("preferred_dividends_2022"),
                    None,
                    None,
                ],
                "Diluted Average Shares": [
                    f("diluted_shares_2022"),
                    f("diluted_shares_2021"),
                    f("diluted_shares_2020"),
                ],
            },
            years,
        ),
        balance=frame(balance, years),
    )


@pytest.mark.parametrize("tangible_row", [True, False], ids=["feed-tbv", "rebuilt-tbv"])
def test_bank_price_to_tangible_book_and_rotce_match_the_10k(tangible_row):
    m = fnd.compute_metrics(bank_raw(tangible_row=tangible_row))
    assert lens(m) == FINANCIAL
    # Tangible COMMON equity: 3,137,228 - 145,452 preferred - 654,952 goodwill
    # - 386 intangibles = 2,336,438 ($k). Cap = 64,360,313 x $100.
    assert m["ptbv"] == approx(2.7546338914193313)
    # earnings to common: 579,150 - 6,675 preferred dividends = 572,475
    assert m["rotce"] == approx(0.24502041141258618)
    assert m["share_dilution"] == approx(0.011964839031965102)


def test_bank_grid_reads_book_and_return_not_ebitda():
    keys = [t.key for t in fnd.fundamental_tiles(FINANCIAL)]
    assert "ptbv" in keys and "rotce" in keys
    assert "ev_ebitda" not in keys and "fcf_yield" not in keys


# --------------------------------------------------------------- real estate


@pytest.fixture(scope="module")
def reit() -> dict:
    f = lambda k: v("real_estate", k)  # noqa: E731
    ebitda = (
        f("net_income_2023")
        + f("interest_expense_2023")
        + f("income_tax_2023")
        + f("depreciation_amortization_2023")
    )
    years = ["2023-12-31", "2022-12-31"]
    raw = raw_for(
        "real_estate",
        income=frame(
            {
                "EBITDA": [ebitda, None],
                "Net Income": [f("net_income_2023"), None],
                "Diluted Average Shares": [
                    f("diluted_shares_2023"),
                    f("diluted_shares_2022"),
                ],
            },
            years,
        ),
        balance=frame(
            {"Net Debt": [f("notes_payable_2023") - f("cash_2023"), None]}, years
        ),
        cashflow=frame(
            {
                "Operating Cash Flow": [f("cfo_2023"), f("cfo_2022")],
                "Free Cash Flow": [f("cfo_2023"), f("cfo_2022")],  # no capex line
                "Cash Dividends Paid": [
                    -f("dividends_paid_2023"),
                    -f("dividends_paid_2022"),
                ],
            },
            years,
        ),
    )
    raw.info["dividendRate"] = f("dividend_per_share_2023")
    return fnd.compute_metrics(raw)


def test_reit_leverage_yield_and_cover_match_the_10k(reit):
    assert lens(reit) == REAL_ESTATE
    # EBITDA 872,309 + 730,423 + 52,021 + 1,895,177 = 3,549,930 ($k);
    # net debt 18,602,319 - 232,923 = 18,369,396
    assert reit["net_debt_ebitda"] == approx(5.174579780446375)
    assert reit["dividend_yield"] == approx(0.05547272727272728)  # 3.051 / $55
    # dividends over two years of operating cash: 3,925,224 / 5,522,625
    assert reit["dividend_fcf"] == approx(0.710753310246486)
    assert reit["share_dilution"] == approx(0.13205734905199606)


def test_reit_payout_is_not_read_through_free_cash_flow_or_roic(reit):
    ranked = fnd._rankable(reit)
    assert ranked["fcf_yield"] is None and ranked["roic"] is None
    assert [t.key for t in fnd.fundamental_tiles(REAL_ESTATE)][3:6] == [
        "ev_ebitda",
        "dividend_yield",
        "payout_ratio",
    ]


# ------------------------------------------------------------------- utility


@pytest.fixture(scope="module")
def utility() -> dict:
    f = lambda k: v("utility", k)  # noqa: E731
    years = ["2023-12-31", "2022-12-31"]
    ebitda = f("operating_income_2023") + f("depreciation_amortization_2023")
    fcf = f("cfo_2023") - f("utility_capex_2023")
    raw = raw_for(
        "utility",
        income=frame(
            {
                "EBITDA": [ebitda, None],
                "Diluted Average Shares": [
                    f("diluted_shares_2023"),
                    f("diluted_shares_2022"),
                ],
            },
            years,
        ),
        balance=frame(
            {
                "Net Debt": [f("long_term_debt_2023") - f("cash_2023"), None],
                "Cash Cash Equivalents And Short Term Investments": [
                    f("cash_2023"),
                    None,
                ],
            },
            years,
        ),
        cashflow=frame(
            {
                "Free Cash Flow": [fcf, None],
                "Cash Dividends Paid": [-f("dividends_paid_2023"), None],
            },
            years,
        ),
    )
    return fnd.compute_metrics(raw)


def test_utility_leverage_and_free_cash_flow_match_the_10k(utility):
    assert lens(utility) == UTILITY
    # EBITDA 3,196 + 2,031 = 5,227; net debt 22,240 - 1,189 = 21,051 ($M)
    assert utility["net_debt_ebitda"] == approx(4.027357949110389)
    # FCF 2,156 - 4,353 = -2,197; cap = 345,510,031 x $90
    assert utility["fcf"] == approx(-2_197e6)
    assert utility["fcf_yield"] == approx(-0.07065239478129974)
    assert utility["runway_years"] == approx(0.5411925352753755)  # 1,189 / 2,197
    assert utility["share_dilution"] == approx(-0.01826869027543565)


def test_utility_dividend_is_not_covered_by_a_negative_fcf(utility):
    # a regulated network funds its build with debt: no cover ratio, and the
    # lens blanks the FCF yield so it is not ranked against it
    assert utility["dividend_fcf"] is None
    assert fnd._rankable(utility)["fcf_yield"] is None


# ------------------------------------------------ peer median and 3-sigma flag


def peers(pe: list[float], subject: float = 15.0) -> list[dict]:
    rows = [{"ticker": "SUBJ", "pe_ttm": subject}]
    rows += [{"ticker": f"P{i}", "pe_ttm": x} for i, x in enumerate(pe)]
    return rows


def test_peer_band_is_the_rivals_quartiles_without_the_subject():
    band = fnd.peer_band(peers([10, 12, 14, 16, 18], subject=999.0), ["pe_ttm"])
    # inclusive quartiles of 10,12,14,16,18: 12 / 14 / 16; the subject is not in it
    assert band["pe_ttm"] == (12.0, 14.0, 16.0)


def test_peer_band_needs_three_rivals():
    assert fnd.peer_band(peers([10, 12]), ["pe_ttm"]) == {}


def test_outlier_flag_is_three_robust_sigmas_from_the_others():
    rows = [{"ticker": f"P{i}", "pe_ttm": x} for i, x in enumerate([10, 12, 14, 16, 18])]
    # others of the 40: median 14, MAD 2 -> 1.4826 x 2 = 2.97, under the floor of
    # half the median (7): 3 x 7 = 21 and |40 - 14| = 26 flags
    assert fnd.comp_outliers(rows + [{"ticker": "WILD", "pe_ttm": 40.0}]) == {
        "WILD": ["pe_ttm"]
    }
    # 30 is 16 away, inside 21: no flag
    assert fnd.comp_outliers(rows + [{"ticker": "OK", "pe_ttm": 30.0}]) == {}


def test_a_bank_is_not_judged_on_ev_ebitda_in_the_peer_band():
    banks = [
        {"ticker": f"B{i}", "industry": "Banks - Regional", "ev_ebitda": x}
        for i, x in enumerate([5.0, 6.0, 7.0, 8.0])
    ]
    rows = [{"ticker": "SUBJ", "ev_ebitda": 9.0}] + banks
    assert fnd.peer_band(rows, ["ev_ebitda"]) == {}  # lens blanks all four
