"""Jurisdiction-neutral tax scaffolding shared by every country module.

The engine used to be one Spain-only module (`tax_es`). Two things are country
specific and everything else turned out not to be:

* **Which losses count this year.** Both jurisdictions we ship disallow a loss
  when the same security is bought back around the sale — Spain's art. 33.5.f
  "regla de los dos meses" and the US wash-sale rule (30 days either side).
  The mechanics are identical: block the loss in the sale year, re-integrate
  it as the replacement shares are themselves sold. Only the window differs,
  so `repurchases` takes the window as a predicate.
* **What the net is taxed at.** A flat progressive scale over one base (Spain)
  versus two buckets split by holding period, netted against each other, with
  the remainder deductible against ordinary income up to a cap (US).

So a jurisdiction is: a currency, a period summarizer, a bracket function and
a set of reporting-threshold flags. The web/CLI layers render whatever
`TaxPeriod.kpis()` and `.notes()` return, which is why adding a country does
not touch the tax tab.

Money is in the jurisdiction's own currency (`Jurisdiction.currency`) — the
ledger is replayed at that base, so a US filer's basis is USD at the trade
date, a Spanish filer's is EUR at the ECB rate. NOT tax advice; a planning aid.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import NamedTuple

from stocks.portfolio.positions import MATCH_FIFO, MATCH_LIFO, RealizedSale

# (sell_date, buy_date) -> True when that purchase blocks the sale's loss.
Window = Callable[[date, date], bool]


@dataclass(frozen=True)
class TaxSettings:
    """Per-filer knobs. Fields a jurisdiction doesn't use are ignored.

    `other_income` is other *taxable* ordinary income (after deductions) — the
    US brackets stack short-term gains on top of it, and we deliberately do not
    model the standard deduction: asking for a post-deduction figure is one
    input instead of five, and wrong by less.
    """

    filing_status: str = "single"  # US: single | mfj | mfs | hoh; DE: single | joint
    other_income: float = 0.0
    include_niit: bool = False  # US net investment income tax (3.8%)
    # DE: Kirchensteuer as a share of the tax itself (0.08 or 0.09), on top of
    # the flat rate and the solidarity surcharge.
    church_tax_rate: float = 0.0
    # Sub-national income tax as a flat marginal rate on the taxable gain, for
    # federations where the province/state tax is the larger half of the bill:
    # Canada reads it as the provincial rate. A flat rate is an approximation
    # of a progressive provincial scale, and asking for one marginal rate is
    # one input instead of thirteen tables.
    subnational_rate: float = 0.0
    # Tickers the caller has classified as funds, for regimes that treat fund
    # income differently (DE Teilfreistellung). None means "nobody checked" —
    # distinct from an empty set, which means "checked, holds none".
    fund_tickers: frozenset[str] | None = None


@dataclass(frozen=True)
class Kpi:
    """One headline figure: an i18n key, an amount, and a help key."""

    key: str
    value: float
    help_key: str


@dataclass(frozen=True)
class Note:
    """A localized sentence the UI appends under the KPIs."""

    key: str
    kwargs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportingFlag:
    """A reporting threshold (Modelo 720, FBAR, Form 8938…).

    `reportable` means the threshold is crossed, not that a filing is due —
    whether it applies depends on where the assets are actually held, which the
    ledger doesn't know. Hence a flag, not a verdict.
    """

    name: str  # "modelo_720", "fbar", "form_8938" — i18n key suffix
    total_value: float
    threshold: float
    reportable: bool
    # Plain-English sentence for the CLI, which has no catalog. The web page
    # localizes from `name` instead and ignores this.
    message: str = ""


@dataclass
class TaxPeriod:
    """One period's realized result. Subclassed per jurisdiction.

    `period` is an ISO prefix: "YYYY" for a full tax year (the only real
    taxable base) or "YYYY-MM" for a breakdown of when a result was booked.
    """

    jurisdiction: str
    currency: str
    year: int
    period: str = ""
    realized_gain: float = 0.0  # sum of gains from winning sales
    realized_loss: float = 0.0  # sum of |losses| from losing sales
    disallowed_loss: float = 0.0  # blocked this period by the repurchase rule
    # Losses blocked earlier (or this period) that become deductible now
    # because the replacement shares were sold in this period.
    recovered_loss: float = 0.0
    sales: list[RealizedSale] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.period = self.period or f"{self.year:04d}"

    # ---------------------------------------------------------- common maths
    @property
    def deductible_loss(self) -> float:
        return self.realized_loss - self.disallowed_loss

    @property
    def net_taxable(self) -> float:
        """Net taxable result (may be negative -> carryforward)."""
        return self.realized_gain - self.deductible_loss - self.recovered_loss

    @property
    def estimated_tax(self) -> float:  # overridden per jurisdiction
        return 0.0

    @property
    def carryforward_loss(self) -> float:
        """Unused net loss carried to later periods. 0 when the net is a gain."""
        return max(0.0, -self.net_taxable)

    # ------------------------------------------------------------ UI surface
    # Chart series are shared: gains up, deductible losses and recovered
    # deferrals down, net as the marker. Jurisdictions differ in the KPIs and
    # the wording, not in the shape of the period chart.
    def kpis(self) -> list[Kpi]:
        return [
            Kpi("net_taxable", self.net_taxable, "net_taxable_help"),
            Kpi("estimated_tax", self.estimated_tax, "estimated_tax_help"),
            Kpi(
                "carryforward_loss",
                self.carryforward_loss,
                "carryforward_loss_help",
            ),
        ]

    def notes(self) -> list[Note]:
        return []


@dataclass
class TaxTotal:
    """Several finished periods added up: a history, not a taxable base.

    Every jurisdiction here nets and taxes one year at a time — allowances
    reset, the brackets restart, and a loss only crosses a year boundary as a
    carryforward. Which is why this adds up each year's *own* figures instead
    of replaying the whole ledger as one long period: that would run five
    years of gains up a single progressive scale and invent a tax nobody owes.

    It carries no bracket maths of its own, so it renders wherever a
    `TaxPeriod` does (`kpis()`, `notes()`, `sales`) and computes nothing new.
    """

    jurisdiction: str
    currency: str
    # The tax years summed, in the order they were handed over.
    years: tuple[int, ...] = ()
    realized_gain: float = 0.0
    realized_loss: float = 0.0
    disallowed_loss: float = 0.0
    recovered_loss: float = 0.0
    sales: list[RealizedSale] = field(default_factory=list)
    # Each year's KPIs summed key by key — see `total_of`.
    totals: list[Kpi] = field(default_factory=list)

    @property
    def deductible_loss(self) -> float:
        return self.realized_loss - self.disallowed_loss

    def kpis(self) -> list[Kpi]:
        return self.totals

    def notes(self) -> list[Note]:
        """None: every note a jurisdiction writes is about one year."""
        return []


def total_of(periods: Iterable[TaxPeriod]) -> TaxTotal:
    """Add finished tax years together for an all-years view.

    The KPI tiles are summed by key — total net base, total estimated tax,
    total carryforward — taking each year's figure as that year's engine
    already computed it. A key only some years carry still lands, at the sum
    of the years that had it, in first-seen order.
    """
    items = list(periods)
    if not items:
        raise ValueError("total_of needs at least one period")
    first = items[0]
    out = TaxTotal(
        jurisdiction=first.jurisdiction,
        currency=first.currency,
        years=tuple(p.year for p in items),
    )
    summed: dict[str, Kpi] = {}
    for p in items:
        out.realized_gain += p.realized_gain
        out.realized_loss += p.realized_loss
        out.disallowed_loss += p.disallowed_loss
        out.recovered_loss += p.recovered_loss
        out.sales.extend(p.sales)
        for k in p.kpis():
            prev = summed.get(k.key)
            summed[k.key] = Kpi(
                k.key, (prev.value if prev else 0.0) + k.value, k.help_key
            )
    out.totals = list(summed.values())
    return out


# ------------------------------------------------------------------ helpers


def progressive_tax(base: float, brackets: list[tuple[float, float]]) -> float:
    """Tax on `base` under (upper_bound, marginal_rate) brackets. 0 if base<=0."""
    if base <= 0:
        return 0.0
    tax = 0.0
    lower = 0.0
    for upper, rate in brackets:
        if base <= lower:
            break
        tax += (min(base, upper) - lower) * rate
        lower = upper
    return tax


def shift_months(d: date, months: int) -> date:
    """d shifted by ±months, clamped to the target month's last valid day."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    # clamp day (e.g. 31 Jan -2mo has no 31 Nov)
    last = [31, 29 if year % 4 == 0 and (year % 100 or not year % 400) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(d.day, last))


def month_range(first: str, last: str) -> list[str]:
    """Every ISO month ("YYYY-MM") from `first` to `last`, inclusive.

    Quiet months included: a period breakdown that skipped them would
    compress the timeline.
    """
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out: list[str] = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def covers(period: str, sell_date: str, year_start: tuple[int, int] = (1, 1)) -> bool:
    """Whether `sell_date` falls in an ISO `period` under this tax calendar.

    `period` is "YYYY" for a tax year or "YYYY-MM" for one month of it, and
    `year_start` is the (month, day) the year opens on — (1, 1) nearly
    everywhere, (4, 6) in the UK, where "2025" means 6 April 2025 to 5 April
    2026. A calendar-year jurisdiction reduces to the prefix test this replaced.
    """
    if len(period) > 4:  # a month slice is a calendar month either way
        return sell_date.startswith(period)
    if year_start == (1, 1):
        return sell_date.startswith(period)
    year = int(period)
    month, day = year_start
    start = date(year, month, day)
    end = date(year + 1, month, day) - timedelta(days=1)
    return start <= date.fromisoformat(sell_date) <= end


def open_period[P: TaxPeriod](
    kind: type[P], code: str, currency: str, period: str, **extra
) -> P:
    """A jurisdiction's empty period, stamped with its code, currency and year.

    Every `fiscal_period` opens exactly this way and then diverges completely,
    so the stamp lives here and the divergence stays visible in each country
    module. `extra` carries the fields only some subclasses declare — the
    settings the report was run with, whether a fund list was supplied.
    """
    return kind(
        jurisdiction=code, currency=currency, year=int(period[:4]),
        period=period, **extra,
    )


def sales_in(
    period: str,
    realized: list[RealizedSale],
    year_start: tuple[int, int] = (1, 1),
) -> Iterator[RealizedSale]:
    """The disposals `period` covers, in ledger order (see `covers`)."""
    return (s for s in realized if covers(period, s.sell_date, year_start))


def tax_year_of(sell_date: str, year_start: tuple[int, int] = (1, 1)) -> int:
    """Which tax year a disposal belongs to under this calendar.

    A UK disposal on 2 February 2026 belongs to the year that opened on 6
    April 2025 — bucketing it by its calendar year would put it in the wrong
    return, and the year selector reads these.
    """
    d = date.fromisoformat(sell_date)
    if year_start == (1, 1):
        return d.year
    month, day = year_start
    return d.year if (d.month, d.day) >= (month, day) else d.year - 1


def days_window(days: int) -> Window:
    """Calendar-day window: a buy within ±`days` of the sale blocks the loss."""

    def within(sell: date, buy: date) -> bool:
        return abs((buy - sell).days) <= days

    return within


def months_window(months: int) -> Window:
    """Calendar-month window: ±`months` around the sale, month-clamped."""

    def within(sell: date, buy: date) -> bool:
        return shift_months(sell, -months) <= buy <= shift_months(sell, months)

    return within


def days_after_window(days: int) -> Window:
    """Forward-only window: a buy in the `days` *after* the sale blocks it.

    Ireland's four-week rule (TCA 1997 s.581) looks only at a reacquisition
    after the disposal — buying more of the same share a fortnight *before*
    selling at a loss restricts nothing. Spain and the US look both ways, so
    they use the symmetric windows above.
    """

    def within(sell: date, buy: date) -> bool:
        return 0 < (buy - sell).days <= days

    return within


def window_end(sell: date, window: str) -> date | None:
    """The first day a repurchase no longer touches a loss sold on `sell`.

    `window` is the jurisdiction's label (`Jurisdiction.repurchase_window`):
    "2m" ends where `months_window(2)` does, "30d"/"28d" a day past their
    count. None for an empty or unknown label — no rule, no date.
    """
    if window == "2m":
        return shift_months(sell, 2) + timedelta(days=1)
    if window in ("30d", "28d"):
        return sell + timedelta(days=int(window[:-1]) + 1)
    return None


class Acquisition(NamedTuple):
    """`quantity` shares of a security bought on `date` (ISO), in that day's
    units — a later split is applied here, from the `Split` rows beside it."""

    date: str
    quantity: float


class Split(NamedTuple):
    """An N:1 forward split on `date`: `ratio` new shares for each old one.

    A `RealizedSale` counts shares in the units of its sell date and a purchase
    in those of its buy date, so comparing a sale with its buy-back across a
    split needs the ratio in between.
    """

    date: str
    ratio: float


# Ticker -> what the repurchase rules read about it: every acquisition, plus
# the splits that rescale them. A bare ISO date is an acquisition of unknown
# size, which blocks a loss in full.
Acquisitions = Mapping[str, Sequence[str | Acquisition | Split]]

# RealizedSale.matched values that name one lot's own purchase. A pooled
# holding carries its earliest acquisition instead, which is no lot at all.
_OWN_LOT = (MATCH_FIFO, MATCH_LIFO)


@dataclass
class _Block:
    """Part of a loss sale that one repurchase blocks."""

    sale: RealizedSale
    units: float  # the sale's size, in the book's current units
    dates: frozenset[str]  # acquisitions whose later sale frees it
    left: float  # blocked shares not yet freed, current units


@dataclass
class Repurchases:
    """Which losses a buy-back blocks, share by share, and when each comes back.

    A repurchase blocks a loss only for as many shares as it bought: selling
    100 at a loss and buying 10 back defers a tenth of the loss, not all of it
    (US Treas. Reg. 1.1091-1(c); the same proportion Spain's DGT applies to
    art. 33.5.f). Built once per book by `repurchases`, then read per period.
    """

    # id(sale) -> the share of its loss a repurchase blocks, 0..1.
    blocked: dict[int, float] = field(default_factory=dict)
    # (blocked sale, sell date of the replacement that freed it, loss freed).
    freed: list[tuple[RealizedSale, str, float]] = field(default_factory=list)

    def disallowed(self, sale: RealizedSale) -> float:
        """The part of this sale's loss the repurchase rule blocks."""
        if sale.gain >= 0:
            return 0.0
        return -sale.gain * self.blocked.get(id(sale), 0.0)

    def recovered(
        self,
        period: str,
        blocked_filter: Callable[[RealizedSale], bool] | None = None,
    ) -> float:
        """Blocked losses that unlock in `period` because the replacement sold.

        A loss blocked by a repurchase becomes computable as the replacement
        shares are transmitted (ES art. 33.5.f second leg; in the US the same
        economics arrive via the basis bump on the replacement lot).

        `blocked_filter` restricts which blocked sales are counted — the US
        module passes it twice to recover short- and long-term losses
        separately, since a recovered loss keeps the character of the loss
        that was blocked.
        """
        return sum(
            loss
            for sale, when, loss in self.freed
            if when.startswith(period)
            and (blocked_filter is None or blocked_filter(sale))
        )


def repurchases(
    realized: list[RealizedSale], buy_dates: Acquisitions, within: Window
) -> Repurchases:
    """Match every loss in the book against the buy-backs that block it.

    A replacement is homogeneous / substantially-identical shares acquired
    *after* the sold lot and inside the window — a genuine new position, not
    the sold lot's own purchase nor an older parcel. Same ticker stands in for
    both "homogéneas" (ES) and "substantially identical" (US); options,
    converts and cross-listings are not chased.

    Loss sales are taken in date order and each claims the replacement shares
    in order of acquisition, earliest first; a share that has blocked one sold
    share blocks no other (1.1091-1(e)). Shares of a lot sold on the same day
    as the loss left with that disposal, so they replace nothing it sold. Each
    replacement share later sold frees one blocked share's loss, pro rata.

    Matching is over the whole book, not one period: which shares a December
    sale may claim depends on what an October sale already took.
    """
    out = Repurchases()
    by_ticker: dict[str, list[RealizedSale]] = defaultdict(list)
    for s in realized:
        by_ticker[s.ticker].append(s)
    for ticker, sales in by_ticker.items():
        if any(s.gain < 0 for s in sales):
            _match(sales, buy_dates.get(ticker, ()), within, out)
    return out


@dataclass(frozen=True)
class OpenWindow:
    """A loss sale whose repurchase window is still open on some ticker."""

    ticker: str
    sold: date
    # The first day buying the security back no longer blocks the loss.
    clears: date
    # What a buy-back before `clears` would still block: the sale's loss less
    # the part an earlier repurchase already took.
    loss: float


def open_windows(
    realized: list[RealizedSale],
    buy_dates: Acquisitions,
    within: Window,
    window: str,
    today: date,
) -> list[OpenWindow]:
    """Every loss sale whose window clears today or later, soonest first.

    Parcels sold the same day are one sale: a broker fill split over three
    lots is one decision to the reader. A loss a repurchase has already
    blocked in full is left out — its window closing changes nothing, the
    loss now waits on the replacement shares being sold — and one blocked in
    part carries only the part still exposed.
    """
    blocks = repurchases(realized, buy_dates, within)
    exposed: dict[tuple[str, str], float] = defaultdict(float)
    for s in realized:
        if s.gain < 0:
            exposed[s.ticker, s.sell_date[:10]] += -s.gain - blocks.disallowed(s)
    out: list[OpenWindow] = []
    for (ticker, sold), loss in exposed.items():
        if loss <= 1e-6:
            continue
        sell = date.fromisoformat(sold)
        clears = window_end(sell, window)
        if clears is not None and clears >= today:
            out.append(OpenWindow(ticker, sell, clears, loss))
    return sorted(out, key=lambda w: (w.clears, w.ticker))


def _match(
    sales: list[RealizedSale],
    entries: Sequence[str | Acquisition | Split],
    within: Window,
    out: Repurchases,
) -> None:
    """`repurchases` for one security."""
    splits = [e for e in entries if isinstance(e, Split) and e.ratio > 0]

    def units(quantity: float, on: str) -> float:
        """Shares held on `on`, in the book's current units."""
        for sp in splits:
            if sp.date > on:
                quantity *= sp.ratio
        return quantity

    size: dict[str, float] = defaultdict(float)
    for e in entries:
        if isinstance(e, Split):
            continue
        if isinstance(e, str):
            size[e] = math.inf
        else:
            size[e.date] += units(e.quantity, e.date)
    gone: dict[tuple[str, str], float] = defaultdict(float)
    for r in sales:
        if r.matched in _OWN_LOT:
            gone[r.buy_date, r.sell_date] += units(r.quantity, r.sell_date)

    used: dict[str, float] = defaultdict(float)
    blocks: list[_Block] = []
    losses = sorted(
        (s for s in sales if s.gain < 0 and s.quantity > 0),
        key=lambda s: s.sell_date,
    )
    for s in losses:
        sell = date.fromisoformat(s.sell_date)
        lot_buy = date.fromisoformat(s.buy_date)
        want = units(s.quantity, s.sell_date)
        blocked = 0.0
        unsized: list[str] = []
        for d in sorted(size):
            b = date.fromisoformat(d)
            if b <= lot_buy or not within(sell, b):
                continue
            if size[d] == math.inf:
                unsized.append(d)
                continue
            take = min(want - blocked, size[d] - gone[d, s.sell_date] - used[d])
            if take > 1e-9:
                used[d] += take
                blocked += take
                blocks.append(_Block(s, want, frozenset((d,)), take))
        if unsized and want - blocked > 1e-9:
            blocks.append(_Block(s, want, frozenset(unsized), want - blocked))
            blocked = want
        if blocked > 0:
            out.blocked[id(s)] = min(1.0, blocked / want)

    for r in sorted(sales, key=lambda r: r.sell_date):
        budget = units(r.quantity, r.sell_date)
        for blk in blocks:
            if budget <= 1e-12:
                break
            if (
                blk.left <= 1e-12
                or r.buy_date not in blk.dates
                or blk.sale.sell_date >= r.sell_date
            ):
                continue
            freed = min(blk.left, budget)
            blk.left -= freed
            budget -= freed
            out.freed.append((blk.sale, r.sell_date, freed / blk.units * -blk.sale.gain))


def flag(
    name: str, total: float, threshold: float, message: str = ""
) -> ReportingFlag:
    return ReportingFlag(name, total, threshold, total >= threshold, message)
