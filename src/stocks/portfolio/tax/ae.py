"""United Arab Emirates — a personal securities portfolio is not taxed.

Scope: realized gains and losses on listed securities held by a UAE-resident
natural person in a personal capacity. NOT tax advice — a planning aid. What
there is to encode:

* **No personal income tax, no capital gains tax.** The UAE levies neither on
  individuals; there is no federal personal income tax law to be exempt from.
  A gain is taxed at **0%** whether it was booked after a week or a decade,
  and whatever its size. This module exists to say that with the user's own
  numbers in front of them, not to compute a bill.
* **Corporate tax stops short of a personal portfolio.** Federal Decree-Law
  47/2022 subjects a natural person to corporate tax only on *Business or
  Business Activity* conducted in the UAE (art. 11(6)), and Cabinet Decision
  49/2023 art. 2 puts **Personal Investment** income — investment in a
  personal capacity, not conducted through a licence and not requiring one —
  outside Business regardless of amount. The AED 1,000,000 threshold people
  remember from that decision measures *Business* turnover, which a personal
  portfolio does not generate. Run the same portfolio through a licensed
  entity and the 9% above AED 375,000 does apply — to that entity, which is a
  different filer and not what this module models. Hence a standing note
  rather than silence.
* **No loss relief, because there is nothing to relieve.** A carryforward
  exists to offset a future tax bill and there is none, so a losing year
  carries nothing: `carryforward_loss` is 0 here even when the year nets
  negative, rather than a figure implying a deduction that will never arrive.
* **No repurchase rule and no matching rule in law.** Nothing turns on which
  lot a sale takes, so the replay keeps FIFO as a bookkeeping convention. Any
  other rule would produce different — and equally untaxed — numbers.
* **No resident foreign-asset declaration.** There is no UAE Modelo 720 or
  FBAR. The UAE is a CRS *reporting* jurisdiction: its financial institutions
  report accounts held by residents of other countries, an obligation on the
  institution and not on you. The flag below therefore never fires, and says
  why instead of leaving the section blank.

Not modelled, because none of it touches a personal share portfolio: the 5%
VAT, the 15% domestic minimum top-up tax on large multinational groups (from
2025), free-zone qualifying income, and — the one worth naming out loud — any
tax still owed to a *previous* residence for the year you left it.
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

CODE = "AE"
CURRENCY = "AED"
# The tax year is the calendar year here — for the little it decides.
YEAR_START = (1, 1)

RATE = 0.0  # personal capital gains
# Corporate tax, for the note only: it applies to a licensed entity's profit,
# never to this ledger.
CORPORATE_RATE = 0.09
CORPORATE_THRESHOLD_AED = 375_000.0
# A natural person only enters corporate tax through Business turnover above
# this; Personal Investment income is excluded from Business at any amount
# (Cabinet Decision 49/2023, art. 2).
NATURAL_PERSON_TURNOVER_AED = 1_000_000.0

# Nothing to carry forward, since there is no tax for a loss to offset.
CARRYFORWARD_YEARS = 0


@dataclass
class AeTaxPeriod(TaxPeriod):
    """One calendar year of realized result, taxed at nothing."""

    @property
    def estimated_tax(self) -> float:
        return 0.0

    @property
    def carryforward_loss(self) -> float:
        """Always 0: a carryforward offsets future tax, and there is none.

        The base class would report the year's net loss here, which in every
        other jurisdiction is a future deduction. Reporting it for a UAE filer
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
        out: list[Note] = [Note("no_tax_note")]
        if self.net_taxable < 0:
            out.append(Note("no_carryforward_note"))
        out.append(Note("corporate_note"))
        return out


def fiscal_period(
    realized: list[RealizedSale],
    period: str,
    buy_dates: dict[str, list[str]],
    settings: TaxSettings | None = None,
) -> AeTaxPeriod:
    """Summarize an ISO date prefix ("YYYY" or "YYYY-MM").

    `buy_dates` is unused: with no tax there is no loss to disallow, so no
    repurchase can block anything. `settings` is unused too — there are no
    brackets for a filing status or other income to move.
    """
    out = open_period(AeTaxPeriod, CODE, CURRENCY, period)
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
    """One flag that cannot fire: the UAE asks residents to declare nothing.

    The threshold is infinite on purpose — it is the honest encoding of a
    threshold that does not exist, and it keeps `reportable` False for any
    book, however large, without a special case in the caller.
    """
    msg = (
        f"holdings abroad ~{total_foreign_value:,.0f} AED: the UAE has no "
        "foreign-asset declaration for residents. Your broker's country may "
        "still report the account under CRS, and a previous tax residence may "
        "still want a return for the year you left it."
    )
    return [flag("no_local_reporting", total_foreign_value, float("inf"), msg)]
