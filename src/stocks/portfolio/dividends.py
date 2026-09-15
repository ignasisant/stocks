"""Dividend income + foreign withholding, valued at the pay-date rate.

Ledger convention for a dividend row: action='dividend', price = GROSS dividend
total in native ccy, fee = tax withheld at source in native ccy. Net = price-fee.

For a Spanish resident, dividends join the savings base (taxed with capital
gains). Foreign withholding is relieved via the double-taxation credit, capped
at the treaty rate (~15% for most Spain treaties); withholding above the cap is
reclaimable from the source country, not creditable in Spain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from datetime import timedelta as _timedelta
from math import prod

from stocks.data.dividends import DividendHistory
from stocks.data.fx import ToBase, converter, prefetch
from stocks.portfolio.ledger import Transaction

# Spain double-taxation treaty cap on dividend withholding (creditable ceiling).
TREATY_WHT_CAP = 0.15


@dataclass
class DividendYear:
    year: int
    gross: float = 0.0
    withheld: float = 0.0
    records: list[Transaction] = field(default_factory=list)
    # Gross per ticker, same `base` as `gross` — what the reconciliation
    # against the estimate needs: a book where one name's dividends import
    # cleanly and another's never appear has no year-level answer.
    by_ticker: dict[str, float] = field(default_factory=dict)

    @property
    def net(self) -> float:
        return self.gross - self.withheld

    @property
    def creditable(self) -> float:
        """Foreign tax creditable in Spain (capped at the treaty rate)."""
        return min(self.withheld, TREATY_WHT_CAP * self.gross)

    @property
    def reclaimable(self) -> float:
        """Withholding above the treaty cap — reclaim from the source country."""
        return max(0.0, self.withheld - self.creditable)


def by_year(
    transactions: list[Transaction],
    to_base: ToBase | None = None,
    base: str = "EUR",
) -> dict[int, DividendYear]:
    """Aggregate dividends into per-calendar-year summaries in `base`."""
    dividends = [t for t in transactions if t.action == "dividend"]
    if to_base is None:
        prefetch((t.date, t.currency) for t in dividends)
        to_base = converter(base)
    years: dict[int, DividendYear] = {}
    for tx in dividends:
        yr = int(tx.date[:4])
        dy = years.setdefault(yr, DividendYear(year=yr))
        gross = to_base(tx.price, tx.currency, tx.date)
        dy.gross += gross
        dy.withheld += to_base(tx.fee, tx.currency, tx.date)
        dy.records.append(tx)
        dy.by_ticker[tx.ticker] = dy.by_ticker.get(tx.ticker, 0.0) + gross
    return years


# ----------------------------------------------------------------- estimation
# A dividend is owed to whoever holds the share the day before it goes ex —
# the broker's statement has no say in it. So the ledger's own share timeline
# plus Yahoo's per-share history is enough to answer both halves of "what does
# this book pay": what it HAS been paid (even where the import never carried a
# dividend row) and, on today's holdings, what the next twelve months look
# like if nothing is sold.
#
# Two footings have to agree for `per_share * shares` to be cash: Yahoo's
# series is split-adjusted (AAPL's 2016 payments read 0.13, not 0.52), so the
# share timeline here is adjusted the same way — a trade's quantity scaled by
# every split that came after it, the split row itself not a step. This is
# analysis.portfolio.shares_frame's rule, without pandas or a daily index.
#
# These are estimates and the UI must say so. They are GROSS, before any
# withholding (unknowable per ticker without the broker's statement), they use
# the ex-date rather than the pay date (entitlement is set on the ex-date; the
# cash lands weeks later, at a slightly different FX rate), and they assume a
# dividend announced for holders was actually received. None of it belongs in
# a tax figure — `by_year` above, fed by the ledger, is what files.


@dataclass(frozen=True)
class EstimatedPayment:
    """One dividend the ledger's shares were entitled to, priced from history."""

    ticker: str
    ex_date: str
    per_share: float  # split-adjusted, in `currency`
    shares: float  # held the day before the ex-date, in today's shares
    currency: str

    @property
    def gross(self) -> float:
        """Gross payment in `currency`, before any withholding."""
        return self.per_share * self.shares


@dataclass
class EstimatedYear:
    """Per-calendar-year estimated gross, in the reporting currency."""

    year: int
    gross: float = 0.0
    by_ticker: dict[str, float] = field(default_factory=dict)
    payments: list[EstimatedPayment] = field(default_factory=list)


@dataclass(frozen=True)
class ForwardIncome:
    """What one holding pays over the next year at its trailing-12m rate."""

    ticker: str
    shares: float
    per_share: float  # summed over the trailing 12 months
    payments: int  # how many went ex in those 12 months (4 = quarterly)
    currency: str
    last_ex: str | None = None

    @property
    def gross(self) -> float:
        return self.per_share * self.shares


def share_timeline(transactions: list[Transaction]) -> dict[str, list[tuple[str, float]]]:
    """Per ticker, [(date, shares held after that date's trades), …] in order.

    Quantities are in *today's* shares: every trade is scaled by the splits
    recorded after it, so the series lines up with split-adjusted per-share
    history. Dates are the ledger's own; there is no daily fill.
    """
    txs = sorted(transactions, key=lambda t: (t.date, t.id or 0))
    splits: dict[str, list[tuple[str, float]]] = {}
    for t in txs:
        if t.action == "split" and t.quantity > 0:
            splits.setdefault(t.ticker, []).append((t.date, t.quantity))

    def adjusted(t: Transaction) -> float:
        return t.quantity * prod(
            ratio for day, ratio in splits.get(t.ticker, ()) if day > t.date
        )

    held: dict[str, float] = {}
    timeline: dict[str, list[tuple[str, float]]] = {}
    for t in txs:
        if t.action == "buy":
            held[t.ticker] = held.get(t.ticker, 0.0) + adjusted(t)
        elif t.action == "sell":
            held[t.ticker] = max(0.0, held.get(t.ticker, 0.0) - adjusted(t))
        else:
            continue
        series = timeline.setdefault(t.ticker, [])
        if series and series[-1][0] == t.date:
            series[-1] = (t.date, held[t.ticker])
        else:
            series.append((t.date, held[t.ticker]))
    return timeline


def shares_before(
    timeline: dict[str, list[tuple[str, float]]], ticker: str, day: str
) -> float:
    """Shares held at the close of the day before `day` — the entitled amount.

    Strictly before: a share bought *on* the ex-date carries no right to that
    payment, and one sold on it was already gone at the previous close.
    """
    total = 0.0
    for when, qty in timeline.get(ticker, ()):
        if when >= day:
            break
        total = qty
    return total


def estimate_payments(
    transactions: list[Transaction],
    histories: dict[str, DividendHistory],
    until: str | None = None,
    since: str | None = None,
) -> list[EstimatedPayment]:
    """Every past payment the book's shares were entitled to, oldest first.

    `histories` maps ticker -> stocks.data.dividends.DividendHistory (anything
    with `.payments` and `.currency` does). Payments after `until` (default
    today) are the forecast's business, not this one's; `since` trims the
    front. Pure — no network, no clock beyond the `until` default.
    """
    from datetime import date as _date

    until = until or _date.today().isoformat()
    timeline = share_timeline(transactions)
    ledger_ccy: dict[str, str] = {}
    for t in sorted(transactions, key=lambda t: (t.date, t.id or 0)):
        if t.action in ("buy", "sell"):
            ledger_ccy[t.ticker] = t.currency
    out: list[EstimatedPayment] = []
    for ticker, history in histories.items():
        currency = history.currency or ledger_ccy.get(ticker)
        if not currency:
            continue
        for ex_date, per_share in history.payments:
            if ex_date > until or (since and ex_date < since):
                continue
            shares = shares_before(timeline, ticker, ex_date)
            if shares <= 0 or per_share <= 0:
                continue
            out.append(
                EstimatedPayment(ticker, ex_date, per_share, shares, currency)
            )
    return sorted(out, key=lambda p: (p.ex_date, p.ticker))


def estimate_by_year(
    payments: list[EstimatedPayment],
    to_base: ToBase | None = None,
    base: str = "EUR",
) -> dict[int, EstimatedYear]:
    """Aggregate estimated payments per calendar year, valued at the ex-date."""
    if to_base is None:
        prefetch((p.ex_date, p.currency) for p in payments)
        to_base = converter(base)
    years: dict[int, EstimatedYear] = {}
    for p in payments:
        yr = int(p.ex_date[:4])
        ey = years.setdefault(yr, EstimatedYear(year=yr))
        gross = to_base(p.gross, p.currency, p.ex_date)
        ey.gross += gross
        ey.by_ticker[p.ticker] = ey.by_ticker.get(p.ticker, 0.0) + gross
        ey.payments.append(p)
    return years


def unrecorded_by_year(
    imported: dict[int, DividendYear],
    estimated: dict[int, EstimatedYear],
) -> dict[int, float]:
    """Per year, the estimated income the ledger never recorded, in `base`.

    Compared per (year, ticker), not per year: a book whose Revolut dividends
    import cleanly while its ClickTrade ones don't has no honest year-level
    answer. A ticker the ledger booked *more* on than the estimate (a special
    dividend Yahoo lists late, a pay-date FX swing) contributes 0, never a
    negative that would mask another ticker's real gap.
    """
    gaps: dict[int, float] = {}
    for yr, ey in estimated.items():
        booked = imported.get(yr)
        seen = booked.by_ticker if booked else {}
        gap = sum(
            max(0.0, amount - seen.get(ticker, 0.0))
            for ticker, amount in ey.by_ticker.items()
        )
        if gap > 0:
            gaps[yr] = gap
    return gaps


def forward_income(
    transactions: list[Transaction],
    histories: dict[str, DividendHistory],
    ref: str | None = None,
    days: int = 365,
) -> list[ForwardIncome]:
    """Next twelve months on today's holdings, at each name's trailing rate.

    The rate is what the ticker actually paid per share over the `days` before
    `ref` — a payer that raised its dividend mid-year is therefore understated
    and one that cut it overstated, which is the honest version of a forecast
    built from announcements nobody has made yet. Holdings are as of `ref`, so
    the answer means "if nothing is bought or sold". Biggest payer first.
    """
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    ref = ref or _date.today().isoformat()
    window_start = (
        _date.fromisoformat(ref) - _timedelta(days=days)
    ).isoformat()
    timeline = share_timeline(transactions)
    ledger_ccy: dict[str, str] = {}
    for t in sorted(transactions, key=lambda t: (t.date, t.id or 0)):
        if t.action in ("buy", "sell"):
            ledger_ccy[t.ticker] = t.currency
    out: list[ForwardIncome] = []
    for ticker, history in histories.items():
        # Shares held *through* ref, so today's book: shares_before takes the
        # day after, since a buy dated today still counts as held.
        shares = shares_before(timeline, ticker, _bump(ref))
        if shares <= 0:
            continue
        window = [
            (day, amount)
            for day, amount in history.payments
            if window_start < day <= ref
        ]
        if not window:
            continue
        currency = history.currency or ledger_ccy.get(ticker)
        if not currency:
            continue
        out.append(
            ForwardIncome(
                ticker=ticker,
                shares=shares,
                per_share=sum(a for _, a in window),
                payments=len(window),
                currency=currency,
                last_ex=max(day for day, _ in window),
            )
        )
    return sorted(out, key=lambda f: -f.gross)


def _bump(day: str) -> str:
    """The day after `day` — makes `shares_before` inclusive of `day` itself."""
    return (_date.fromisoformat(day) + _timedelta(days=1)).isoformat()


def forward_totals(
    forward: list[ForwardIncome],
    to_base: ToBase | None = None,
    base: str = "EUR",
    ref: str | None = None,
) -> dict[str, float]:
    """Each holding's next-year income in `base`, converted at today's rate.

    Spot, not a trade-date rate: this is money that hasn't been paid yet, so
    the only rate anyone can honestly put on it is the current one.
    """
    ref = ref or _date.today().isoformat()
    if to_base is None:
        prefetch((ref, f.currency) for f in forward)
        to_base = converter(base)
    return {f.ticker: to_base(f.gross, f.currency, ref) for f in forward}
