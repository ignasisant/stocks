"""Tax jurisdictions: pick one, get a period summarizer and reporting flags.

    from stocks.portfolio import tax
    j = tax.get("US")
    period = j.fiscal_year(realized, 2025, buy_dates, tax.TaxSettings(...))
    period.estimated_tax, period.kpis(), j.reporting_flags(foreign_value)

The ledger must be replayed in the jurisdiction's own currency *and* under its
own share-identification rule — `j.currency` and `j.matching` feed
`positions.build(txs, base=…, matching=…)`, so a US filer's basis is USD at the
trade date, a Canadian's is an averaged CAD cost base and an Italian's is LIFO.
`j.year_start` moves the year boundary where it is not 1 January (6 April in
the UK, 1 July in Australia).

Adding a country means one module here plus its `portfolio.<code>_*` catalog
keys; nothing in the web or CLI layer branches on the code.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from stocks.portfolio.positions import POOLED_MODES, RealizedSale
from stocks.portfolio.tax import ae, au, ca, ch, de, es, fr, ie, it, pt, uk, us
from stocks.portfolio.tax.base import (
    Acquisition,
    Acquisitions,
    Kpi,
    Note,
    ReportingFlag,
    Split,
    TaxPeriod,
    TaxSettings,
    TaxTotal,
    month_range,
    tax_year_of,
    total_of,
)

__all__ = [
    "Acquisition",
    "Acquisitions",
    "DEFAULT_CODE",
    "JURISDICTIONS",
    "Jurisdiction",
    "Kpi",
    "Note",
    "ReportingFlag",
    "Split",
    "TaxPeriod",
    "TaxSettings",
    "TaxTotal",
    "buy_dates",
    "codes",
    "get",
    "labels",
    "month_range",
    "normalize",
    "total_of",
]

PeriodFn = Callable[
    [list[RealizedSale], str, Acquisitions, TaxSettings | None], TaxPeriod
]
FlagsFn = Callable[[float, TaxSettings | None], list[ReportingFlag]]


@dataclass(frozen=True)
class Jurisdiction:
    """One country's tax treatment of realized securities gains."""

    code: str
    currency: str
    _period: PeriodFn
    _flags: FlagsFn
    # Years a net loss may be carried forward; None means indefinitely.
    carryforward_years: int | None
    # (month, day) the tax year opens on: 6 April in the UK, 1 July in
    # Australia, 1 January everywhere else.
    year_start: tuple[int, int] = (1, 1)
    # Share-identification rule for the replay (positions.build(matching=…)).
    matching: str = "fifo"
    # How long a repurchase blocks the loss on a sale, as a bare token — "2m"
    # (Spain's two months), "30d" (the US wash sale, Canada's superficial
    # loss), "28d" (Ireland). Empty where no such rule exists, or where the
    # matching mode already absorbs it (the UK's 30-day rule lives in the s.104
    # replay). Language-free on purpose: the callers that show it — the daily
    # action card's harvest line — localize it themselves. The window the
    # replay actually applies is each module's WINDOW; this is its label.
    repurchase_window: str = ""
    # Filing statuses the brackets distinguish; empty when the country's rate
    # scale doesn't care (Spain's savings base doesn't).
    filing_statuses: tuple[str, ...] = ()
    # Which TaxSettings fields this jurisdiction actually reads, in the order
    # the Profile page should offer them. Spain's savings base reads none of
    # them, so that account sees no bracket inputs at all.
    settings_fields: tuple[str, ...] = ()
    # How the jurisdiction writes a tax year, when "2025" is not how.
    _year_label: Callable[[int], str] | None = None
    # Holding-period test, when the rate depends on one. Spain taxes a gain
    # the same after a week or a decade and leaves this unset; the US splits
    # short from long term at a year, Australia discounts gains past twelve
    # months and Portugal aggregates anything under 365 days.
    _long_term: Callable[[str, str], bool] | None = None

    @property
    def splits_holding_period(self) -> bool:
        """True when short- and long-term results are taxed differently."""
        return self._long_term is not None

    def is_long_term(self, buy_date: str, sell_date: str) -> bool:
        """Whether that lot's gain is long-term here. False where it can't be."""
        return bool(self._long_term and self._long_term(buy_date, sell_date))

    @property
    def summary(self) -> str:
        """What these rules tax, in one line: its module docstring's first.

        Each country module opens with that sentence ("Spain — IRPF savings
        base (base del ahorro) on securities.", "Switzerland — a private
        investor's capital gains are not taxed."), so it is the one place the
        headline is written, and the assistant quotes it rather than
        reciting a tax system from memory.
        """
        module = sys.modules.get(self._period.__module__)
        doc = ((module.__doc__ if module else None) or "").strip()
        return doc.splitlines()[0] if doc else self.code

    @property
    def pools_shares(self) -> bool:
        """True when a sale's cost can be an average rather than a lot's own."""
        return self.matching in POOLED_MODES

    def tax_year_of(self, sell_date: str) -> int:
        """The tax year a disposal belongs to (6 April boundaries included)."""
        return tax_year_of(sell_date, self.year_start)

    def year_label(self, year: int) -> str:
        """How this jurisdiction writes that year — "2025", or "2025/26"."""
        return self._year_label(year) if self._year_label else str(year)

    def fiscal_period(
        self,
        realized: list[RealizedSale],
        period: str,
        buy_dates: Acquisitions,
        settings: TaxSettings | None = None,
    ) -> TaxPeriod:
        """Summarize an ISO period prefix: "YYYY" (a real base) or "YYYY-MM"."""
        return self._period(realized, period, buy_dates, settings)

    def fiscal_year(
        self,
        realized: list[RealizedSale],
        year: int,
        buy_dates: Acquisitions,
        settings: TaxSettings | None = None,
    ) -> TaxPeriod:
        return self.fiscal_period(realized, f"{year:04d}", buy_dates, settings)

    def reporting_flags(
        self, total_foreign_value: float, settings: TaxSettings | None = None
    ) -> list[ReportingFlag]:
        """Foreign-asset reporting thresholds crossed by `total_foreign_value`."""
        return self._flags(total_foreign_value, settings)


JURISDICTIONS: dict[str, Jurisdiction] = {
    es.CODE: Jurisdiction(
        code=es.CODE,
        currency=es.CURRENCY,
        _period=es.fiscal_period,
        _flags=es.reporting_flags,
        carryforward_years=es.CARRYFORWARD_YEARS,
        repurchase_window="2m",
    ),
    us.CODE: Jurisdiction(
        code=us.CODE,
        currency=us.CURRENCY,
        _period=us.fiscal_period,
        _flags=us.reporting_flags,
        carryforward_years=None,  # indefinite (IRC 1212(b))
        filing_statuses=us.FILING_STATUSES,
        settings_fields=("filing_status", "other_income", "include_niit"),
        _long_term=us.is_long_term,
        repurchase_window="30d",
    ),
    uk.CODE: Jurisdiction(
        code=uk.CODE,
        currency=uk.CURRENCY,
        _period=uk.fiscal_period,
        _flags=uk.reporting_flags,
        carryforward_years=None,  # indefinite, once claimed
        year_start=uk.YEAR_START,
        matching="s104",
        settings_fields=("other_income",),
        _year_label=uk.year_label,
    ),
    de.CODE: Jurisdiction(
        code=de.CODE,
        currency=de.CURRENCY,
        _period=de.fiscal_period,
        _flags=de.reporting_flags,
        carryforward_years=None,  # indefinite, but the two circles stay apart
        filing_statuses=de.FILING_STATUSES,
        settings_fields=("filing_status", "church_tax_rate"),
    ),
    fr.CODE: Jurisdiction(
        code=fr.CODE,
        currency=fr.CURRENCY,
        _period=fr.fiscal_period,
        _flags=fr.reporting_flags,
        carryforward_years=fr.CARRYFORWARD_YEARS,
        matching="average",  # prix moyen pondéré (art. 150-0 D, 3)
    ),
    it.CODE: Jurisdiction(
        code=it.CODE,
        currency=it.CURRENCY,
        _period=it.fiscal_period,
        _flags=it.reporting_flags,
        carryforward_years=it.CARRYFORWARD_YEARS,
        matching="lifo",  # art. 67 c. 1-bis TUIR
    ),
    ie.CODE: Jurisdiction(
        code=ie.CODE,
        currency=ie.CURRENCY,
        _period=ie.fiscal_period,
        _flags=ie.reporting_flags,
        carryforward_years=None,  # indefinite, against chargeable gains
        repurchase_window="28d",
    ),
    pt.CODE: Jurisdiction(
        code=pt.CODE,
        currency=pt.CURRENCY,
        _period=pt.fiscal_period,
        _flags=pt.reporting_flags,
        carryforward_years=pt.CARRYFORWARD_YEARS,
        settings_fields=("other_income",),
        _long_term=pt.is_long_term,
    ),
    ca.CODE: Jurisdiction(
        code=ca.CODE,
        currency=ca.CURRENCY,
        _period=ca.fiscal_period,
        _flags=ca.reporting_flags,
        carryforward_years=None,  # indefinite, capital gains only
        matching="average",  # adjusted cost base (ITA s.47)
        settings_fields=("other_income", "subnational_rate"),
        repurchase_window="30d",
    ),
    au.CODE: Jurisdiction(
        code=au.CODE,
        currency=au.CURRENCY,
        _period=au.fiscal_period,
        _flags=au.reporting_flags,
        carryforward_years=None,  # indefinite, capital gains only
        year_start=au.YEAR_START,
        settings_fields=("other_income",),
        _year_label=au.year_label,
        _long_term=au.is_long_term,
    ),
    ae.CODE: Jurisdiction(
        code=ae.CODE,
        currency=ae.CURRENCY,
        _period=ae.fiscal_period,
        _flags=ae.reporting_flags,
        # Nothing carries: a carryforward offsets future tax and there is none.
        carryforward_years=ae.CARRYFORWARD_YEARS,
        # No statutory rule — FIFO is a bookkeeping convention here, and every
        # figure it produces is untaxed either way.
        matching="fifo",
    ),
    ch.CODE: Jurisdiction(
        code=ch.CODE,
        currency=ch.CURRENCY,
        _period=ch.fiscal_period,
        _flags=ch.reporting_flags,
        # Nothing carries: an exempt gain faces a non-deductible loss.
        carryforward_years=ch.CARRYFORWARD_YEARS,
        # No statutory rule — FIFO is a bookkeeping convention here.
        matching="fifo",
    ),
}

# Spain stays the default: this app was built for a Spanish filer, and an
# unset preference must not silently re-tax an existing book under other rules.
DEFAULT_CODE = es.CODE


def codes() -> tuple[str, ...]:
    return tuple(JURISDICTIONS)


def normalize(code: str | None) -> str:
    """A supported jurisdiction code, or the default. Accepts 'es', 'US-CA'."""
    if not code:
        return DEFAULT_CODE
    head = str(code).replace("_", "-").split("-")[0].upper()
    return head if head in JURISDICTIONS else DEFAULT_CODE


def get(code: str | None = None) -> Jurisdiction:
    return JURISDICTIONS[normalize(code)]


def labels(transactions) -> list[str]:
    """Every security in the ledger, under the label a RealizedSale carries.

    Same reason as `buy_dates`: anything matched against a sale's ticker — the
    fund classification the German partial exemption needs, for one — has to be
    keyed the way the replay keys it, not the way the broker wrote it.
    """
    from stocks.portfolio import transfers

    return sorted({tx.ticker for tx in transfers.relabel(list(transactions))})


def buy_dates(transactions) -> dict[str, list[Acquisition | Split]]:
    """Acquisitions per security, for the repurchase rules.

    Every jurisdiction that blocks a loss on a quick buy-back looks its window
    up here — Spain's two months, the US wash sale, Ireland's four weeks,
    Canada's superficial loss — as `buy_dates.get(sale.ticker)`.

    Which is exactly why this may not be built by hand from the raw ledger.
    `positions.build` relabels before replaying (`transfers.normalize`), so a
    RealizedSale carries the *unified* label, while a book fed by two brokers
    spells the same security two ways: DEGIRO exports have no ticker column and
    book under the ISIN, IBKR uses the symbol. Key the acquisitions the raw way
    and the lookup misses — the repurchase is invisible, the rule never fires,
    and a disallowed loss is reported as deductible. That is an
    under-declaration, and nothing in the output says it happened.

    The same holds for which rows are acquisitions. The replay opens a lot for
    a `transfer_in` no departure accounts for — an IBKR snapshot of shares the
    book never held — dated the day they arrived, and a sale of that lot
    carries that date as its `buy_date`. Leave the arrival out here and a loss
    sold at one broker and bought straight back at the other is deductible in
    full, while the replay itself says the shares were acquired inside the
    window. A matched pair is still no acquisition: it drops out of both.

    So: normalize first, with the same function the replay used.

    Each acquisition carries its size, because a buy-back blocks a loss only
    for as many shares as it bought, and the splits ride along in ledger order:
    a sale counts shares in its own day's units, a purchase in its own.
    """
    from collections import defaultdict

    from stocks.portfolio import transfers

    out: dict[str, list[Acquisition | Split]] = defaultdict(list)
    rows = transfers.normalize(list(transactions))
    for tx in sorted(rows, key=lambda t: (t.date, t.id or 0)):
        if tx.action == "buy":
            out[tx.ticker].append(Acquisition(tx.date, tx.quantity))
        elif tx.action == "split":
            out[tx.ticker].append(Split(tx.date, tx.quantity))
    return dict(out)
