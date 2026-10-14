"""Fundamentals tests — synthetic data, no network."""

import pandas as pd
import pytest

from stocks.analysis.fundamentals import (
    KPI_SOURCES,
    METRIC_ORDER,
    annual_financials,
    cagr,
    comp_medals,
    comp_scores,
    comparables_table,
    compute_metrics,
    format_value,
    quarterly_eps,
    sources_table,
    verdict,
    verdict_md,
)
from stocks.data.fundamentals import RawFundamentals

YEARS = ["2025", "2024", "2023", "2022", "2021"]  # newest-first like yfinance


def sample_raw() -> RawFundamentals:
    income = pd.DataFrame(
        {
            "Total Revenue": [400e9, 380e9, 365e9, 350e9, 300e9],
            "Net Income": [100e9, 95e9, 90e9, 85e9, 70e9],
            "EBIT": [120e9, 115e9, 110e9, 105e9, 90e9],
            "EBITDA": [130e9, 125e9, 120e9, 115e9, 100e9],
            "Tax Rate For Calcs": [0.15, 0.15, 0.16, 0.16, 0.14],
            "Diluted Average Shares": [15e9, 15.3e9, 15.6e9, 16e9, 16.5e9],
        },
        index=YEARS,
    ).T
    balance = pd.DataFrame(
        {"Invested Capital": [200e9] * 5, "Net Debt": [50e9] * 5}, index=YEARS
    ).T
    cashflow = pd.DataFrame(
        {"Free Cash Flow": [95e9, 90e9, 88e9, 82e9, 70e9]}, index=YEARS
    ).T
    info = {
        "currency": "USD",
        "currentPrice": 250.0,
        "marketCap": 3.8e12,
        "enterpriseValue": 3.85e12,
        "trailingPE": 38.0,
        "forwardPE": 33.0,
        "trailingPegRatio": 2.6,
        "priceToBook": 44.0,
        "enterpriseToEbitda": 29.6,
        "enterpriseToRevenue": 10.5,
        "returnOnEquity": 1.41,
        "grossMargins": 0.478,
        "operatingMargins": 0.322,
        "profitMargins": 0.271,
    }
    return RawFundamentals("TEST", info, income, balance, cashflow)


def test_an_acquirers_return_is_read_on_its_own_capital_too():
    raw = sample_raw()
    assert compute_metrics(raw)["roic_ex_goodwill"] is None  # no goodwill
    raw.balance.loc["Goodwill"] = [120e9] * 5
    raw.income.loc["Amortization Of Intangibles Income Statement"] = [10e9] * 5
    m = compute_metrics(raw)
    # (120e9 EBIT + 10e9 amortisation) * (1 - 0.15) / (200e9 - 120e9)
    assert m["roic_ex_goodwill"] == pytest.approx(130e9 * 0.85 / 80e9)
    assert m["roic"] == pytest.approx(0.51)


def test_cagr_basic():
    assert abs(cagr(100, 200, 4) - (2**0.25 - 1)) < 1e-9
    assert cagr(0, 100, 4) is None
    assert cagr(-5, 100, 4) is None
    assert cagr(100, 100, 0) is None


def test_compute_metrics_derived():
    m = compute_metrics(sample_raw())
    # ROIC = 120e9 * (1 - 0.15) / 200e9
    assert abs(m["roic"] - 0.51) < 1e-9
    # FCF yield = 95e9 / 3.8e12
    assert abs(m["fcf_yield"] - 0.025) < 1e-9
    # Net debt / EBITDA = 50 / 130
    assert abs(m["net_debt_ebitda"] - 50 / 130) < 1e-9
    # Cash conversion = 95 / 100
    assert abs(m["cash_conversion"] - 0.95) < 1e-9
    # Dilution: shares shrink 16.5e9 -> 15e9 over 4y => negative CAGR (buybacks)
    assert m["share_dilution"] < 0
    assert m["revenue_cagr"] > 0


def test_compute_metrics_carries_the_history_the_review_cautions_read():
    m = compute_metrics(sample_raw())
    assert abs(m["op_margin_median"] - 0.30) < 1e-9
    assert abs(m["op_margin_change"]) < 1e-9
    assert m["revenue_down_years"] == 0
    raw = sample_raw()
    raw.income.loc["Total Revenue"] = [400e9, 380e9, 390e9, 350e9, 300e9]
    assert compute_metrics(raw)["revenue_down_years"] == 1


def test_compute_metrics_rebuilds_the_ev_multiples_the_feed_left_out():
    raw = sample_raw()
    for key in ("enterpriseValue", "enterpriseToEbitda", "enterpriseToRevenue"):
        del raw.info[key]
    m = compute_metrics(raw)
    assert abs(m["ev"] - (3.8e12 + 50e9)) < 1
    assert abs(m["ev_ebitda"] - 3.85e12 / 130e9) < 1e-9
    assert abs(m["ev_sales"] - 3.85e12 / 400e9) < 1e-9
    # The feed's own figures win when it gave them.
    assert compute_metrics(sample_raw())["ev_ebitda"] == 29.6
    assert abs(m["ps"] - 3.8e12 / 400e9) < 1e-9


def test_a_dividend_is_covered_over_the_filed_years_not_one_dip():
    # Coca-Cola's 2024: a one-off tax deposit cut free cash flow under the
    # dividend for one year; four years of it covered the payout.
    raw = sample_raw()
    raw.cashflow.loc["Free Cash Flow"] = [20e9, 90e9, 88e9, 82e9, 70e9]
    raw.cashflow.loc["Stock Based Compensation"] = [5e9] * 5
    raw.cashflow.loc["Cash Dividends Paid"] = [-19e9, -19e9, -18e9, None, None]
    m = compute_metrics(raw)
    # Only the years with both rows: 56bn paid over (20+90+88 - 3*5)bn.
    assert abs(m["dividend_fcf"] - 56e9 / 183e9) < 1e-9
    raw.cashflow = raw.cashflow.drop("Cash Dividends Paid")
    assert compute_metrics(raw)["dividend_fcf"] is None


def test_compute_metrics_reads_the_dividend_in_the_quotes_own_unit():
    raw = sample_raw()
    raw.info.update(dividendRate=5.0, payoutRatio=0.4, dividendYield=2.0)
    raw.cashflow.loc["Cash Dividends Paid"] = [-19e9] * 5
    m = compute_metrics(raw)
    assert abs(m["dividend_yield"] - 0.02) < 1e-9
    assert m["payout_ratio"] == 0.4
    # Five filed years of 19bn paid over 95+90+88+82+70bn of free cash flow.
    assert abs(m["dividend_fcf"] - 95e9 / 425e9) < 1e-9
    # No percent: the rate over the price, then Yahoo's trailing yield; a
    # yield no payer has is the feed's.
    del raw.info["dividendYield"]
    assert abs(compute_metrics(raw)["dividend_yield"] - 5.0 / 250.0) < 1e-9
    del raw.info["dividendRate"]
    raw.info["trailingAnnualDividendYield"] = 0.031
    assert compute_metrics(raw)["dividend_yield"] == 0.031
    raw.info["trailingAnnualDividendYield"] = 0.9
    assert compute_metrics(raw)["dividend_yield"] is None


def test_an_adrs_yield_is_not_read_off_its_filing_currency():
    # TSM as Yahoo gives it: a trailing yield of TWD over a dollar price.
    raw = sample_raw()
    raw.info.update(
        currency="USD",
        financialCurrency="TWD",
        trailingAnnualDividendRate=26.0,
        trailingAnnualDividendYield=0.0585,
        dividendYield=0.85,
    )
    assert abs(compute_metrics(raw)["dividend_yield"] - 0.0085) < 1e-9
    del raw.info["dividendYield"]
    assert compute_metrics(raw)["dividend_yield"] is None


def test_a_line_quoted_in_pence_reads_its_yield_from_the_percent():
    # HSBA.L as Yahoo gives it: a dollar rate over a price in pence.
    raw = sample_raw()
    raw.info.update(
        currency="GBp",
        currentPrice=1441.2,
        dividendRate=0.56,
        trailingAnnualDividendYield=0.000525,
        dividendYield=3.99,
    )
    assert abs(compute_metrics(raw)["dividend_yield"] - 0.0399) < 1e-9


def test_compute_metrics_missing_data():
    raw = RawFundamentals("EMPTY")
    m = compute_metrics(raw)
    for key in METRIC_ORDER:
        assert m.get(key) is None, key


def test_kpi_sources_cover_metric_order():
    assert set(METRIC_ORDER) == set(KPI_SOURCES)
    m = compute_metrics(sample_raw())
    for key in METRIC_ORDER:
        assert key in m, f"compute_metrics missing {key}"


def test_format_value():
    assert format_value("pe_ttm", None) == "n/a"
    assert format_value("pe_ttm", 38.0) == "38.0x"
    assert format_value("roic", 0.51) == "51.0%"
    assert format_value("market_cap", 3.8e12) == "3.80T"
    assert format_value("fcf", 95e9) == "95.00B"


def test_comparables_table_shape():
    m = compute_metrics(sample_raw())
    peer = dict(m, ticker="PEER")
    table = comparables_table([m, peer])
    assert list(table.columns) == ["TEST", "PEER"]
    assert len(table) == len(METRIC_ORDER)


def test_annual_financials_shape_and_order():
    cols = pd.to_datetime([f"{y}-12-31" for y in YEARS])  # yfinance: Timestamp cols
    income = pd.DataFrame(
        {
            "Total Revenue": [400e9, 380e9, 365e9, 350e9, 300e9],
            "Net Income": [100e9, 95e9, 90e9, 85e9, 70e9],
            "Diluted EPS": [6.6, 6.2, 5.8, 5.3, 4.2],
        },
        index=cols,
    ).T
    fin = annual_financials(RawFundamentals("TEST", income=income))
    assert list(fin.columns) == ["Revenue", "Net Income", "EPS"]
    assert list(fin.index) == [2021, 2022, 2023, 2024, 2025]  # oldest-first
    assert fin.loc[2021, "Revenue"] == 300e9
    assert fin.loc[2025, "EPS"] == 6.6


def test_annual_financials_empty():
    assert annual_financials(RawFundamentals("EMPTY")).empty


def test_quarterly_eps_shape_and_order():
    cols = pd.to_datetime(
        ["2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"]
    )  # yfinance: newest-first Timestamp cols
    income_q = pd.DataFrame(
        {
            "Total Revenue": [110e9, 105e9, 100e9, 95e9],
            "Diluted EPS": [1.8, 1.7, 1.6, 1.5],
        },
        index=cols,
    ).T
    eps = quarterly_eps(RawFundamentals("TEST", income_q=income_q))
    assert list(eps.columns) == ["EPS"]
    assert list(eps.index) == ["2024Q3", "2024Q4", "2025Q1", "2025Q2"]  # oldest-first
    assert eps.loc["2025Q2", "EPS"] == 1.8


def test_quarterly_eps_empty():
    assert quarterly_eps(RawFundamentals("EMPTY")).empty


def test_sources_table_levels():
    df = sources_table()
    assert set(df["Level"]) <= {"fact", "consensus", "derived"}
    assert len(df) == len(KPI_SOURCES)


def test_verdict_bands():
    # valuation multiples — lower is cheaper
    assert verdict("pe_ttm", 12) == ("cheap", "green")
    assert verdict("pe_ttm", 55) == ("very expensive", "red")
    assert verdict("peg", 0.8) == ("cheap", "green")
    # momentum — RSI oversold / neutral / overbought
    assert verdict("rsi", 22.0) == ("oversold", "green")
    assert verdict("rsi", 52.3) == ("neutral", "gray")
    assert verdict("rsi", 80) == ("overbought", "red")
    # quality (fractions) — higher is better
    assert verdict("roic", 0.30) == ("strong", "green")
    # leverage — negative is net cash
    assert verdict("net_debt_ebitda", -1.2) == ("net cash", "green")


def test_verdict_missing_and_nonnumeric():
    assert verdict("peg", None) is None
    assert verdict("rsi", float("nan")) is None  # NaN falls through every band
    assert verdict("roic", True) is None  # bools rejected
    assert verdict("unknown_key", 1.0) is None
    assert verdict_md("peg", None) == ""
    assert verdict_md("pe_ttm", 12) == ":green[cheap]"


def _peer(ticker: str, better: float) -> dict:
    """Synthetic metrics dict; `better` in [0,1] scales every KPI so higher
    `better` wins on all fronts (cheaper multiples, stronger quality/growth)."""
    return {
        "ticker": ticker,
        # lower-better: shrink as `better` grows
        "pe_ttm": 40 - 25 * better,
        "peg": 3 - 2 * better,
        "pb": 10 - 8 * better,
        "ev_ebitda": 30 - 20 * better,
        "net_debt_ebitda": 3 - 4 * better,
        # higher-better: grow with `better`
        "roic": 0.05 + 0.25 * better,
        "fcf_yield": 0.01 + 0.05 * better,
        "revenue_cagr": 0.02 + 0.2 * better,
    }


def test_comp_scores_orders_by_dominance():
    rows = [_peer("BEST", 1.0), _peer("MID", 0.5), _peer("WORST", 0.0)]
    scores = comp_scores(rows)
    assert scores["BEST"] > scores["MID"] > scores["WORST"]
    assert scores["BEST"] == 1.0 and scores["WORST"] == 0.0


def test_comp_scores_skips_sparse_and_nonnumeric():
    rows = [
        _peer("A", 1.0),
        _peer("B", 0.0),
        # only two rankable KPIs -> below _RANK_MIN_METRICS, no score
        {"ticker": "SPARSE", "pe_ttm": 10, "roic": 0.4},
        # non-numeric / NaN / bool values never rank
        {"ticker": "JUNK", "pe_ttm": "n/a", "roic": float("nan"), "peg": True},
    ]
    scores = comp_scores(rows)
    assert set(scores) == {"A", "B"}


def test_comp_medals_podium():
    rows = [_peer(t, x) for t, x in
            [("G", 1.0), ("S", 0.75), ("B", 0.5), ("D", 0.0)]]
    assert comp_medals(rows) == {"G": "🥇", "S": "🥈", "B": "🥉"}
    # fewer than 3 qualifying tickers -> no podium at all
    assert comp_medals(rows[:2]) == {}


def _filed_in(currency: str) -> RawFundamentals:
    """`sample_raw` filed in another currency than it quotes in (an ADR)."""
    raw = sample_raw()
    raw.info["financialCurrency"] = currency
    raw.balance.loc["Stockholders Equity"] = [500e9] * 5
    return raw


def test_an_adr_is_valued_in_one_currency(monkeypatch):
    from stocks.analysis import fundamentals as fm

    monkeypatch.setattr(fm.fx, "spot", lambda base, quote: (0.15, "2026-10-09"))
    m = compute_metrics(_filed_in("DKK"))
    # Statements in DKK, cap in USD: both sides in USD before dividing.
    assert abs(m["fcf_yield"] - 95e9 * 0.15 / 3.8e12) < 1e-12
    ev = 3.8e12 + 50e9 * 0.15
    assert abs(m["ev_ebitda"] - ev / (130e9 * 0.15)) < 1e-9
    assert abs(m["ev_sales"] - ev / (400e9 * 0.15)) < 1e-9
    assert abs(m["pb"] - 3.8e12 / (500e9 * 0.15)) < 1e-9


def test_a_currency_the_ecb_lacks_falls_back_to_the_quoted_pair(monkeypatch):
    from stocks.analysis import fundamentals as fm

    def no_ecb(base, quote):
        raise ValueError("TWD")

    monkeypatch.setattr(fm.fx, "spot", no_ecb)
    monkeypatch.setattr(fm.fetch, "info", lambda symbol: {"regularMarketPrice": 0.031})
    m = compute_metrics(_filed_in("TWD"))
    assert abs(m["fcf_yield"] - 95e9 * 0.031 / 3.8e12) < 1e-12


def test_no_rate_at_all_blanks_the_mixed_ratios(monkeypatch):
    from stocks.analysis import fundamentals as fm

    def nothing(*args):
        raise ValueError("offline")

    monkeypatch.setattr(fm.fx, "spot", nothing)
    monkeypatch.setattr(fm.fetch, "info", nothing)
    m = compute_metrics(_filed_in("TWD"))
    # Yahoo's own figures mix currencies; blank beats wrong.
    assert m["fcf_yield"] is None
    assert m["ev_ebitda"] is None and m["pb"] is None


def test_price_to_sales_reads_the_last_four_quarters(monkeypatch):
    from stocks.analysis import fundamentals as fm

    # Nebius, Oct 2026: 530M filed for 2025, 1.36B over the last four
    # quarters. The filed year made it 89x sales and "pre-revenue".
    raw = sample_raw()
    raw.info["totalRevenue"] = 1.9e12
    assert abs(compute_metrics(raw)["ps"] - 2.0) < 1e-9
    # An ADR's trailing sales are filed in its own currency too.
    monkeypatch.setattr(fm.fx, "spot", lambda base, quote: (0.15, "2026-10-09"))
    raw = _filed_in("DKK")
    raw.info["totalRevenue"] = 1.9e12
    assert abs(compute_metrics(raw)["ps"] - 3.8e12 / (1.9e12 * 0.15)) < 1e-9


def test_no_revenue_has_no_margins_and_a_runway():
    raw = sample_raw()
    raw.income.loc["Total Revenue"] = [0.0] * 5
    raw.cashflow.loc["Free Cash Flow"] = [-2e9] * 5
    raw.info["totalCash"] = 6e9
    m = compute_metrics(raw)
    # Yahoo reads a 0 margin for a company with no sales; that is not a margin.
    assert m["op_margin"] is None and m["gross_margin"] is None
    assert m["fcf_margin"] is None
    assert abs(m["runway_years"] - 3.0) < 1e-9


def test_float_is_measured_against_ebitda():
    raw = sample_raw()
    raw.cashflow.loc["Free Cash Flow"] = [390e9] * 5
    m = compute_metrics(raw)
    assert abs(m["fcf_ebitda"] - 3.0) < 1e-9
    assert m["runway_years"] is None


def test_share_based_pay_comes_off_the_owners_cash_flow():
    raw = sample_raw()
    raw.cashflow.loc["Stock Based Compensation"] = [45e9] * 5
    m = compute_metrics(raw)
    # The KPI stays the feed's; the owner's yield is net of the pay.
    assert abs(m["fcf_yield"] - 95e9 / 3.8e12) < 1e-12
    assert abs(m["owner_fcf_yield"] - 50e9 / 3.8e12) < 1e-12
    assert abs(m["sbc_fcf"] - 45 / 95) < 1e-12
    assert abs(m["fcf_margin"] - 50 / 400) < 1e-12
    assert abs(m["fcf_ebitda"] - 50 / 130) < 1e-12


def test_net_debt_over_a_loss_is_no_multiple():
    raw = sample_raw()
    raw.income.loc["EBITDA"] = [-1e9] * 5
    raw.balance.loc["Net Debt"] = [-2.5e9] * 5
    assert compute_metrics(raw)["net_debt_ebitda"] is None


def test_a_dividend_the_feed_got_wrong_is_logged_not_kept(monkeypatch):
    from stocks.analysis import fundamentals

    seen = []
    monkeypatch.setattr(
        fundamentals.consistency, "report", lambda kind, **f: seen.append((kind, f))
    )
    raw = sample_raw()
    raw.info.update(dividendYield=51.4, payoutRatio=0.4)
    assert compute_metrics(raw)["dividend_yield"] is None
    [(kind, fields)] = seen
    assert kind == "feed_dividend" and fields["field"] == "yield"
    assert fields["value"] == 0.514 and fields["ticker"] == raw.ticker


def test_statements_in_a_currency_nothing_converts_are_logged(monkeypatch):
    from stocks.analysis import fundamentals

    seen = []
    monkeypatch.setattr(
        fundamentals.consistency, "report", lambda kind, **f: seen.append((kind, f))
    )
    monkeypatch.setattr(fundamentals, "_statement_fx", lambda info: None)
    raw = sample_raw()
    raw.info.update(currency="USD", financialCurrency="XYZ")
    assert compute_metrics(raw)["fcf_yield"] is None
    assert ("feed_currency", {"source": "feed", "ticker": raw.ticker,
            "filed": "XYZ", "quoted": "USD"}) in seen
