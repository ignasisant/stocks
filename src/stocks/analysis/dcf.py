"""A plain discounted-cash-flow value for a company, and the maths behind it.

What it is, and is not. Free cash flow to the *firm* (Yahoo's operating cash
flow less capex, with the after-tax interest the filer paid added back, since
that cash belongs to the lenders), grown for five years at one rate, then a
Gordon terminal value, all discounted at one WACC; the net debt on the last
balance sheet comes off and the diluted share count divides. Every input is
visible and editable on the card, and the card says it is an illustration of
the assumptions, not a price target.

It refuses rather than guesses: no positive trailing FCF, a business judged on
another lens (banks, insurers, REITs and utilities do not have an FCF that
means "cash the owners could take"), a currency it cannot convert or no share
count each give `reason`, never a number. The clients mirror `value_per_share`
(`frontend/app/src/pages/ticker/dcfmath.ts`) against the shared fixture
`dcf.fixture.json`, so an edit made on the page and the server's own grid agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stocks.analysis import fundamentals as fnd
from stocks.analysis import review
from stocks.analysis.listing import quote_unit
from stocks.data.fundamentals import RawFundamentals

YEARS = 5
#: The growth band the default is clipped to: a trailing CAGR over a few
#: years is a memory, and extrapolating a 60 % one for five years is a claim.
GROWTH_MIN, GROWTH_MAX = 0.0, 0.15
#: With no usable history the default is a quiet one, not a blank.
GROWTH_FALLBACK = 0.03
WACC = 0.09
TERMINAL = 0.025
WACC_GRID = (0.07, 0.08, 0.09, 0.10, 0.11)
TERMINAL_GRID = (0.015, 0.02, 0.025, 0.03, 0.035)
#: Tax rate on the interest add-back when the filing gives none.
TAX_FALLBACK = 0.21


def value_per_share(
    fcf: float,
    growth: float,
    wacc: float,
    terminal: float,
    net_debt: float,
    shares: float,
    years: int = YEARS,
) -> float | None:
    """Equity value per share, or None when the maths has no answer.

    `fcf` is the base year's; years 1..`years` grow at `growth`, the terminal
    value is `fcf_N * (1 + g) / (wacc - g)` at year N, all discounted at `wacc`.
    None for a non-positive base or share count, and for `terminal >= wacc`
    (the series then does not converge: a refused cell, not a huge number).
    """
    if fcf <= 0 or shares <= 0 or wacc <= 0 or terminal >= wacc or growth <= -1:
        return None
    pv = 0.0
    flow = fcf
    for year in range(1, years + 1):
        flow *= 1 + growth
        pv += flow / (1 + wacc) ** year
    pv += flow * (1 + terminal) / (wacc - terminal) / (1 + wacc) ** years
    return (pv - net_debt) / shares


def default_growth(metrics: dict) -> tuple[float, str]:
    """The explicit-period growth to start from and where it came from.

    The trailing FCF CAGR, else the sales CAGR, clipped to 0-15 %: a business
    whose cash flow shrank is not modelled as shrinking forever, and one that
    doubled is not modelled as doubling for five more years.
    """
    for key in ("fcf_cagr", "revenue_cagr"):
        value = metrics.get(key)
        if isinstance(value, int | float) and value == value:
            return min(max(float(value), GROWTH_MIN), GROWTH_MAX), key
    return GROWTH_FALLBACK, "fallback"


@dataclass
class Dcf:
    ticker: str
    reason: str | None = None
    currency: str | None = None
    price: float | None = None
    fcf: float | None = None
    net_debt: float | None = None
    shares: float | None = None
    growth: float | None = None
    growth_source: str | None = None
    wacc: float = WACC
    terminal: float = TERMINAL
    value: float | None = None
    upside: float | None = None
    waccs: tuple[float, ...] = WACC_GRID
    terminals: tuple[float, ...] = TERMINAL_GRID
    grid: list[list[float | None]] = field(default_factory=list)


def _firm_cash_flow(raw: RawFundamentals, fcf: float) -> float:
    """Yahoo's FCF is after interest; the firm's is before it, taxed."""
    interest = fnd._latest(raw.income, "Interest Expense")
    if interest is None or interest <= 0:
        return fcf
    tax = fnd._latest(raw.income, "Tax Rate For Calcs")
    if tax is None or not 0 <= tax < 1:
        tax = TAX_FALLBACK
    return fcf + interest * (1 - tax)


def compute(raw: RawFundamentals, metrics: dict) -> Dcf:
    """The card for one company: its default value and its sensitivity grid."""
    out = Dcf(ticker=raw.ticker, currency=metrics.get("currency"))
    price = metrics.get("price")
    out.price = float(price) if price else None
    if str(metrics.get("quote_type") or "EQUITY").upper() != "EQUITY":
        out.reason = "not_equity"
        return out
    if review.lens(metrics) != review.STANDARD:
        out.reason = "lens"
        return out
    fcf = metrics.get("fcf")
    if not isinstance(fcf, int | float) or fcf <= 0:
        out.reason = "negative_fcf"
        return out
    shares = fnd._latest(raw.income, "Diluted Average Shares")
    net_debt = fnd.latest_net_debt(raw)
    rate = fnd._statement_fx(raw.info)
    if not shares or shares <= 0 or net_debt is None or not rate or not out.price:
        out.reason = "no_data"
        return out
    # Quote currency throughout, so the value sits against the price. The
    # statement rate stops at the major unit (GBP filings against a GBp line
    # read 1.0), so a pence quote takes the hundredfold here: Tesco's value
    # per share came out in pounds beside a price in pence, at -99 %.
    rate /= quote_unit(raw.info.get("currency"))[1]
    out.fcf = _firm_cash_flow(raw, float(fcf)) * rate
    out.net_debt = float(net_debt) * rate
    out.shares = float(shares)
    out.growth, out.growth_source = default_growth(metrics)
    out.value = value_per_share(
        out.fcf, out.growth, out.wacc, out.terminal, out.net_debt, out.shares
    )
    if out.value is not None:
        out.upside = out.value / out.price - 1
    out.grid = [
        [
            value_per_share(out.fcf, out.growth, w, g, out.net_debt, out.shares)
            for g in out.terminals
        ]
        for w in out.waccs
    ]
    return out
