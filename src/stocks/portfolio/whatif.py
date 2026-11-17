"""A sale that has not happened, run through the tax engine.

The ledger replayed under the jurisdiction's own matching rule and currency,
once as it is (`replay`) and once with one more sale today
(`Replay.scenario`): the difference is what the sale does to this tax year.
The Tax tab, the review, the crypto page and the chat all ask here, so they
quote one figure. What the chat makes of a message about selling is
`stocks.chat.whatif`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stocks.formatting import bound


@dataclass(frozen=True)
class Scenario:
    """One simulated sale and what it does to this tax year."""

    ticker: str
    held: float
    shares: float
    price: float  # per share, in `price_currency`
    price_currency: str
    proceeds: float  # in `currency`, the jurisdiction's
    gain: float  # realised by this sale alone, in `currency`
    tax_before: float  # this tax year's estimate without the sale
    tax_after: float  # and with it
    currency: str
    jurisdiction: str
    year: str  # as the jurisdiction writes it: "2026", "2026/27"
    blocked: float = 0.0  # of this sale's loss, deferred by the repurchase rule

    @property
    def extra_tax(self) -> float:
        return self.tax_after - self.tax_before

    def line(self, lang: str = "en") -> str:
        """The prompt's paragraph: figures only, and where they came from."""
        n, p = bound(lang)
        c = self.currency
        return (
            "\n\n---\nSale simulated by the app's own tax engine for this "
            f"message ({self.jurisdiction.upper()} rules, tax year {self.year}, "
            f"today's price {n(self.price, 2)} {self.price_currency}). Quote these "
            "figures rather than estimating your own, and say they are an "
            "estimate:\n"
            f"- selling {self.shares:g} of {self.held:g} {self.ticker} shares\n"
            f"- proceeds {n(self.proceeds, 2)} {c}\n"
            f"- realised gain on this sale {n(self.gain, 2, signed=True)} {c}\n"
            f"- estimated tax this year {n(self.tax_before, 2)} -> "
            f"{n(self.tax_after, 2)} {c} (change {n(self.extra_tax, 2, signed=True)} {c})"
        )


@dataclass(frozen=True)
class Replay:
    """The ledger replayed once under the account's jurisdiction, as it is:
    what every simulated sale is measured against. Built once per question,
    so a harvest weighing six losses replays the ledger seven times, not
    twelve, and loads it once."""

    code: str
    jurisdiction: Any  # tax.Jurisdiction
    transactions: tuple
    positions: tuple
    realized: tuple
    settings: Any  # TaxSettings
    year: int
    day: str
    before: Any  # TaxPeriod, this tax year without any sale
    # Booked dividends, where they share the base: they raise the bracket a
    # sale's gain lands in (Spain's base del ahorro).
    paid: tuple = ()

    @property
    def currency(self) -> str:
        return self.jurisdiction.currency

    @property
    def year_label(self) -> str:
        return self.jurisdiction.year_label(self.year)

    def held(self, symbol: str):
        """The open position in `symbol`, or None."""
        symbol = symbol.strip().upper()
        return next((p for p in self.positions
                     if p.ticker == symbol and p.quantity > 0), None)

    def after(self, sales: list[tuple[str, float, float, str]]):
        """(realized, this year's period) with `sales` — (ticker, shares,
        price, currency) — made today, on top of the ledger as it is."""
        from stocks.portfolio import tax
        from stocks.portfolio.ledger import Transaction
        from stocks.portfolio.positions import build

        jur = self.jurisdiction
        # Ids past the ledger's own: the replay orders a day's rows by id, and
        # one without sorted first, before a trade booked earlier today.
        last = max((t.id or 0 for t in self.transactions), default=0)
        txs = [*self.transactions, *(
            Transaction(date=self.day, ticker=ticker, action="sell", quantity=count,
                        price=price, currency=currency, id=last + n)
            for n, (ticker, count, price, currency) in enumerate(
                (s for s in sales if s[1] > 0), start=1)
        )]
        _, realized = build(txs, base=jur.currency, matching=jur.matching)
        return realized, jur.fiscal_year(realized, self.year, tax.buy_dates(txs),
                                         self.settings, self.paid)

    def scenario(self, symbol: str, shares: float, price: float,
                 currency: str = "") -> Scenario | None:
        """The sale of `shares` of `symbol` today at `price`, or None when
        nothing of it is held. Clamped to the holding."""
        held = self.held(symbol)
        if held is None:
            return None
        symbol = held.ticker
        count = max(0.0, min(float(shares), held.quantity))
        currency = currency or held.currency
        tax_before = self.before.estimated_tax
        if count <= 0:
            return Scenario(symbol, held.quantity, 0.0, price, currency, 0.0, 0.0,
                            tax_before, tax_before, self.currency, self.code,
                            self.year_label)
        realized, after = self.after([(symbol, count, price, currency)])
        # Today's sale replays last, so everything before it matched as it
        # did: the difference between the two replays is this sale's parcels.
        return Scenario(
            ticker=symbol, held=held.quantity, shares=count, price=price,
            price_currency=currency,
            proceeds=sum(s.proceeds for s in realized)
            - sum(s.proceeds for s in self.realized),
            gain=sum(s.gain for s in realized) - sum(s.gain for s in self.realized),
            tax_before=tax_before, tax_after=after.estimated_tax,
            currency=self.currency, jurisdiction=self.code, year=self.year_label,
            blocked=max(0.0, after.disallowed_loss - self.before.disallowed_loss),
        )


def replay(*, db: Path, prefs_path: Path, today: date | None = None) -> Replay | None:
    """The account's ledger replayed under its tax residence's matching rule
    and currency, or None without a ledger."""
    from stocks.portfolio import dividends, tax
    from stocks.portfolio.ledger import all_transactions
    from stocks.portfolio.positions import build
    from stocks.portfolio.tax import prefs as tax_prefs

    prefs = tax_prefs.load(prefs_path)
    code, _how = tax_prefs.resolve(prefs)
    jur = tax.get(code)
    txs = all_transactions(db) if db.exists() else []
    if not txs:
        return None
    positions, realized = build(txs, base=jur.currency, matching=jur.matching)
    day = (today or date.today()).isoformat()
    year = jur.tax_year_of(day)
    settings = tax_prefs.with_funds(tax_prefs.settings(prefs), tax.labels(txs))
    paid = (
        tuple(dividends.payments(txs, base=jur.currency))
        if jur.dividends_in_base
        else ()
    )
    return Replay(
        code=code, jurisdiction=jur, transactions=tuple(txs),
        positions=tuple(positions), realized=tuple(realized), settings=settings,
        year=year, day=day,
        before=jur.fiscal_year(realized, year, tax.buy_dates(txs), settings, paid),
        paid=paid,
    )
