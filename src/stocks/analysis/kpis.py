"""What each key of `compute_metrics`' dict is: a price, a yield on the price,
an enterprise multiple, or the business itself; and where it comes from.

One table instead of a list per reader. `review.at_price` moves the priced
kinds and leaves the business; the quality legs read only `business()`, so a
price can reach quality only by being registered as business, which this file
says out loud. `fundamentals.missing_reasons` reads where a key comes from to
say why it is blank.

`VERSION` is the definition of the dict. A memo or a recorded score built
under one version is wrong under the next: `loaders.company` persists the
metrics under it, and `review.SCALE` (which names the score history file)
carries it. Bump it whenever a key is added or a figure is computed
differently; `tests/test_kpis.py` pins a fingerprint of the output on fixed
statements so a change that moves the numbers fails until it is bumped.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

#: 3: 2026-11-12 `cash_roc`, `loan_share`, `equity_share`, `property_share`,
#: an ADR's and a pence line's forward P/E, a collapsing trailing P/E blanked.
VERSION = 3

Kind = Literal["identity", "price", "yield", "enterprise", "business"]
Statement = Literal["income", "cashflow", "balance"]


@dataclass(frozen=True)
class Kpi:
    #: identity: who the row is. price: a price over something the filings
    #: fix, so it scales with the share price. yield: something over the
    #: price, so it moves against it. enterprise: over market cap plus net
    #: debt. business: no price in it at all.
    kind: Kind = "business"
    #: The statement it is computed from; empty there means "no statements".
    statement: Statement | None = None
    #: A rate over several years: blank with too few of them.
    series: bool = False
    #: Statements in one currency set against a price in another.
    converted: bool = False
    #: Over EBITDA: blank, not missing, when EBITDA is a loss.
    on_ebitda: bool = False


_B = Kpi()

KPIS: dict[str, Kpi] = {
    # identity
    "ticker": Kpi("identity"),
    "currency": Kpi("identity"),
    "industry": Kpi("identity"),
    "quote_type": Kpi("identity"),
    # price
    "price": Kpi("price"),
    "market_cap": Kpi("price"),
    "pe_ttm": Kpi("price"),
    "pe_ttm_reported": Kpi("price"),
    "pe_fwd": Kpi("price"),
    "peg": Kpi("price"),
    "pb": Kpi("price", converted=True),
    "ptbv": Kpi("price", statement="balance", converted=True),
    "ps": Kpi("price"),
    "turnover_usd": Kpi("price"),
    # yield
    "fcf_yield": Kpi("yield", statement="cashflow", converted=True),
    "owner_fcf_yield": Kpi("yield", statement="cashflow", converted=True),
    "dividend_yield": Kpi("yield"),
    # enterprise
    "ev": Kpi("enterprise"),
    "ev_ebitda": Kpi("enterprise", converted=True, on_ebitda=True),
    "ev_sales": Kpi("enterprise", converted=True),
    # business
    "accruals": _B,
    "cash_conversion": Kpi(statement="cashflow"),
    "cash_roc": _B,
    "cfo_ni": _B,
    "dividend_fcf": _B,
    "equity_share": _B,
    "fcf": _B,
    "fcf_cagr": Kpi(statement="cashflow", series=True),
    "fcf_ebitda": _B,
    "fcf_margin": _B,
    "goodwill_assets": _B,
    "goodwill_equity": _B,
    "gross_margin": _B,
    "insider_share": _B,
    "loan_share": _B,
    "moat": _B,
    "net_debt_ebitda": Kpi(statement="income", on_ebitda=True),
    "net_income_cagr": Kpi(statement="income", series=True),
    "net_margin": _B,
    "one_off_share": _B,
    "op_margin": _B,
    "op_margin_change": _B,
    "op_margin_median": _B,
    "payout_ratio": _B,
    "property_share": _B,
    "revenue": _B,
    "revenue_cagr": Kpi(statement="income", series=True),
    "revenue_down_years": _B,
    "revenue_growth": _B,
    "roe": _B,
    "roic": Kpi(statement="income"),
    "roic_ex_goodwill": Kpi(statement="income"),
    "rotce": Kpi(statement="balance"),
    "runway_years": _B,
    "sbc_fcf": _B,
    "sbc_revenue": _B,
    "share_dilution": Kpi(statement="income", series=True),
}

PRICED: tuple[str, ...] = tuple(k for k, v in KPIS.items() if v.kind == "price")
YIELDS: tuple[str, ...] = tuple(k for k, v in KPIS.items() if v.kind == "yield")
_ON_PRICE = frozenset({"price", "yield", "enterprise"})


def kpi(key: str) -> Kpi:
    """`key`'s entry; an unknown key reads as business (a stored row from
    another version must still score)."""
    return KPIS.get(key, _B)


class PriceInQuality(LookupError):
    """A quality leg asked for a figure with the share price in it.

    Not a KeyError, so `Mapping.get` and `in` raise it instead of reading it
    as absent: the mistake fails the first test that scores, not a review."""


class _Business(Mapping):
    __slots__ = ("_metrics",)

    def __init__(self, metrics: Mapping) -> None:
        self._metrics = metrics

    def __getitem__(self, key: str):
        if kpi(key).kind in _ON_PRICE:
            raise PriceInQuality(key)
        return self._metrics[key]

    def __iter__(self) -> Iterator[str]:
        return (k for k in self._metrics if kpi(k).kind not in _ON_PRICE)

    def __len__(self) -> int:
        return sum(1 for _ in self)


def business(metrics: Mapping) -> Mapping:
    """`metrics` without the share price: reading a price, a yield or an
    enterprise multiple through it raises `PriceInQuality`."""
    return _Business(metrics)
