"""Switzerland — a private investor's capital gains are not taxed.

Scope: realized gains and losses on listed securities held as *private* movable
assets by a Swiss-resident individual. NOT tax advice — a planning aid. Rules
encoded:

* **Private capital gains are exempt.** Art. 16 para. 3 DBG (LIFD) puts gains
  on movable private assets outside taxable income, at federal, cantonal and
  communal level alike. **0%**, at any amount and any holding period.
* **Unless you are a professional securities dealer**, and that is the whole
  risk here, so it is a standing note rather than a footnote. Circular KS 36
  gives a safe harbour: hold each position **at least 6 months**, keep annual
  turnover under **5×** the portfolio's value, keep capital gains under **50%**
  of net income, use **no borrowed money**, and run **no speculative
  derivatives**. Meet all five and the exemption is not questioned. Fail even
  one and the authority looks at the whole picture; reclassified, every gain
  becomes ordinary income *and* attracts AHV/AVS social contributions, which
  is how a 0% bill turns into a combined rate above 40%.
* **A loss is symmetric.** If gains are not taxed, losses are not deductible —
  against anything, in any year. Nothing carries forward, so `carryforward_loss`
  is 0 here even when the year nets negative.
* **No matching rule in law**, since no figure it produces is taxable. The
  replay keeps FIFO as a bookkeeping convention.
* **Everything is still declared.** The Wertschriftenverzeichnis (état des
  titres) lists every security held worldwide at 31 December with its value
  and its gross dividends — not to tax the gain, but because the *value* feeds
  the cantonal wealth tax and the *dividends* are ordinary income. Hence a
  flag that reports at any value, like Italy's quadro RW.

Not modelled, and each one costs a Swiss filer real money this tab will not
show: the **cantonal and communal wealth tax** on year-end net assets (the
rate and the allowance are the canton's, so no number is quoted here), **income
tax on dividends** at ordinary rates, the **35% Verrechnungssteuer** withheld
on Swiss-source dividends and credited back only when correctly declared, and
Säule 3a / vested-benefits wrappers.
"""

from __future__ import annotations

from dataclasses import dataclass

from stocks.portfolio.positions import RealizedSale
from stocks.portfolio.tax.base import (
    Kpi,
    Note,
    ReportingFlag,
    TaxPeriod,
    TaxSettings,
    flag,
    open_period,
    sales_in,
)

CODE = "CH"
CURRENCY = "CHF"
# The tax year is the calendar year, and the Wertschriftenverzeichnis is
# valued on its last day.
YEAR_START = (1, 1)

RATE = 0.0  # private capital gains, art. 16 para. 3 DBG

# KS 36's safe harbour, as numbers rather than prose so the note and the tests
# read the same source.
DEALER_MIN_HOLD_MONTHS = 6
DEALER_MAX_TURNOVER_RATIO = 5.0
DEALER_MAX_GAIN_SHARE_OF_INCOME = 0.50

# Nothing carries: there is no tax for a loss to offset.
CARRYFORWARD_YEARS = 0


@dataclass
class ChTaxPeriod(TaxPeriod):
    """One calendar year of private gains, taxed at nothing."""

    @property
    def estimated_tax(self) -> float:
        return 0.0

    @property
    def carryforward_loss(self) -> float:
        """Always 0: an exempt gain has a non-deductible loss facing it.

        The base class would report the year's net loss, which everywhere else
        is a future deduction. Here it is simply gone, and saying otherwise
        would promise relief that does not exist.
        """
        return 0.0

    def kpis(self) -> list[Kpi]:
        """The net result and the zero. No carryforward tile — it never moves."""
        return [
            Kpi("net_taxable", self.net_taxable, "net_taxable_help"),
            Kpi("estimated_tax", self.estimated_tax, "estimated_tax_help"),
        ]

    def notes(self) -> list[Note]:
        out: list[Note] = [Note("exempt_note"), Note("dealer_note")]
        if self.net_taxable < 0:
            out.append(Note("no_relief_note"))
        out.append(Note("wealth_note"))
        return out


def fiscal_period(
    realized: list[RealizedSale],
    period: str,
    buy_dates: dict[str, list[str]],
    settings: TaxSettings | None = None,
) -> ChTaxPeriod:
    """Summarize an ISO date prefix ("YYYY" or "YYYY-MM").

    `buy_dates` is unused: with no tax there is no loss to disallow, so no
    repurchase can block anything. `settings` is unused too — there are no
    brackets for a filing status or other income to move.
    """
    out = open_period(ChTaxPeriod, CODE, CURRENCY, period)
    for s in sales_in(period, realized, YEAR_START):
        out.sales.append(s)
        if s.gain >= 0:
            out.realized_gain += s.gain
        else:
            out.realized_loss += -s.gain
    return out


def reporting_flags(
    total_foreign_value: float, settings: TaxSettings | None = None
) -> list[ReportingFlag]:
    """The Wertschriftenverzeichnis: declarable at any value, and why.

    Not a foreign-asset regime — a Swiss return lists securities wherever they
    are held. The threshold is 0 rather than infinite (which is how a country
    with no declaration at all is encoded) because this duty is real; it just
    has no amount to cross.
    """
    msg = (
        f"securities ~{total_foreign_value:,.0f} CHF: every holding goes in "
        "the Wertschriftenverzeichnis at its 31 December value, wherever it is "
        "held. The gain is exempt; that value still feeds the cantonal wealth "
        "tax and the dividends are still ordinary income."
    )
    return [flag("wertschriftenverzeichnis", total_foreign_value, 0.0, msg)]
