"""Fetch raw fundamentals (snapshot + annual statements) via yfinance.

yfinance is the *loading* source (free, no key). It is NOT the verification
source — see stocks.analysis.fundamentals.KPI_SOURCES for where each KPI
should be cross-checked (SEC EDGAR primary for US filers).

Every request here goes through `data.fetch`: the shared `.info` memo, and the
circuit breaker in front of it. This module used to call yfinance raw — fine
for one ticker page, ruinous for a screen, and a sector scan is two hundred
companies at roughly five requests each.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

from stocks.data import fetch


@dataclass
class RawFundamentals:
    """One ticker's raw fundamental data, annual statements newest-first."""

    ticker: str
    info: dict = field(default_factory=dict)
    income: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow: pd.DataFrame = field(default_factory=pd.DataFrame)
    income_q: pd.DataFrame = field(default_factory=pd.DataFrame)


def fetch_fundamentals(ticker: str) -> RawFundamentals:
    """Download snapshot info + annual + quarterly statements for one ticker.

    Raises `YFRateLimitError` when the host is cooling off, without touching
    the network — callers already degrade on it (`analysis.screener` turns it
    into an all-n/a row rather than aborting a whole screen).

    `.info` comes from `fetch.info`, which memoizes it for 120s and records the
    facts that never move — sector, country, currency, quoteType — in the
    on-disk profile memo. That side effect is why a sector scan classifies
    every company it touches for free.
    """
    symbol = fetch.resolve(ticker)
    blob = fetch.retry(lambda: fetch.info(symbol))
    t = yf.Ticker(symbol)

    def statements():
        # One ladder for the four frames, not four. yfinance memoizes each one
        # on the Ticker instance, so a retry after a 429 on the last frame
        # re-requests that frame alone.
        return (t.financials, t.quarterly_financials, t.balance_sheet, t.cashflow)

    income, income_q, balance, cashflow = fetch.retry(statements)
    return RawFundamentals(
        # What the caller asked for, not what Yahoo calls it: an alias resolves
        # for the request, but `report.gather` and the comps table read these
        # rows back by the symbol they passed in.
        ticker=ticker.upper(),
        info=blob or {},
        income=income,
        income_q=income_q,
        balance=balance,
        cashflow=cashflow,
    )
