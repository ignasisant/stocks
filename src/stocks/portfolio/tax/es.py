"""Spain — IRPF savings base (base del ahorro) on securities.

Scope: capital gains/losses on securities, plus the dividends that share the
base with them. NOT tax advice — a planning aid.
Key rules encoded:

* Progressive savings-base brackets (2023-2025 scale).
* FIFO matching lives in positions.py (art. 37 LIRPF).
* Art. 33.5.f "regla de los dos meses": a loss on listed securities is NOT
  deductible in the year if identical securities were (re)bought within the two
  months before or after the sale. The loss is deferred, not lost — it becomes
  computable as the replacement shares are later sold, which the shared
  `repurchases` machinery re-integrates. Only as many shares as were bought
  back are blocked: a partial buy-back defers that proportion of the loss.
* Losses offset gains within the savings base; any excess carries forward 4
  years (surfaced as a note, not auto-applied across years here).
* Dividends (rendimientos del capital mobiliario) join the same base, gross.
  The two halves net separately: a net capital loss offsets at most 25% of
  the year's dividends (art. 49.1 LIRPF), and the rest of it carries forward.
  Withholding is a credit against the tax, not a lower base — the Dividends
  tab reads it.
* Modelo 720 / foreign-asset reporting flag (> 50.000 EUR held abroad).
"""

from __future__ import annotations

from dataclasses import dataclass

from stocks.portfolio.positions import RealizedSale
from stocks.portfolio.tax.base import (
    Acquisitions,
    Note,
    ReportingFlag,
    TaxPeriod,
    TaxSettings,
    flag,
    months_window,
    open_period,
    progressive_tax,
    repurchases,
    sales_in,
    securities_only,
)

CODE = "ES"
CURRENCY = "EUR"
# The tax year is the calendar year here.
YEAR_START = (1, 1)

# Base del ahorro — marginal brackets (upper bound EUR, rate), by the first
# year each scale applied: 26% over 200k from 2021 (Ley 11/2020), 27/28% over
# 200k/300k from 2023 (Ley 31/2022), 30% over 300k from 2025 (Ley 7/2024).
SAVINGS_BRACKETS_BY_YEAR: dict[int, list[tuple[float, float]]] = {
    2016: [(6_000, 0.19), (50_000, 0.21), (float("inf"), 0.23)],
    2021: [(6_000, 0.19), (50_000, 0.21), (200_000, 0.23), (float("inf"), 0.26)],
    2023: [
        (6_000, 0.19),
        (50_000, 0.21),
        (200_000, 0.23),
        (300_000, 0.27),
        (float("inf"), 0.28),
    ],
    2025: [
        (6_000, 0.19),
        (50_000, 0.21),
        (200_000, 0.23),
        (300_000, 0.27),
        (float("inf"), 0.30),
    ],
}

MODELO_720_THRESHOLD_EUR = 50_000.0
CARRYFORWARD_YEARS = 4
# Share of the year's dividends a net capital loss may offset (art. 49.1 LIRPF).
CROSS_OFFSET = 0.25

# Two calendar months either side of the sale (art. 33.5.f).
WINDOW = months_window(2)
# Which assets it reaches: "valores o participaciones homogéneos", so not a
# crypto coin — sold at a loss, it can be bought straight back.
REACHES = securities_only


def brackets_for(year: int) -> list[tuple[float, float]]:
    """The savings scale in force in `year`: the latest one at or before it."""
    earlier = [y for y in SAVINGS_BRACKETS_BY_YEAR if y <= year]
    return SAVINGS_BRACKETS_BY_YEAR[
        max(earlier) if earlier else min(SAVINGS_BRACKETS_BY_YEAR)
    ]


def tax_on_savings_base(base: float, year: int) -> float:
    """Progressive IRPF tax on a positive savings-base amount (EUR) in `year`."""
    return progressive_tax(base, brackets_for(year))


@dataclass
class EsTaxPeriod(TaxPeriod):
    @property
    def gains_net(self) -> float:
        """The capital half of the base: gains less every deductible loss."""
        return self.realized_gain - self.deductible_loss - self.recovered_loss

    @property
    def cross_offset(self) -> float:
        """How much of a net capital loss the year's dividends absorb.

        A year only: the cap is on the ejercicio's dividends, and a month is a
        breakdown of when the result was booked, not a base of its own.
        """
        if len(self.period) > 4 or self.gains_net >= 0:
            return 0.0
        return min(-self.gains_net, CROSS_OFFSET * self.dividends)

    @property
    def net_taxable(self) -> float:
        """The savings base: capital result plus dividends.

        A year whose losses outrun its gains taxes the dividends less the
        quarter the loss may take, and the rest of the loss is the
        carryforward. With no dividends that year still reads as the negative
        net it always did — the same figure as the carryforward.
        """
        if self.cross_offset:
            return self.dividends - self.cross_offset
        return self.gains_net + self.dividends

    @property
    def carryforward_loss(self) -> float:
        if len(self.period) == 4:
            return max(0.0, -self.gains_net - self.cross_offset)
        return max(0.0, -self.net_taxable)

    @property
    def estimated_tax(self) -> float:
        return tax_on_savings_base(self.net_taxable, self.year)

    def notes(self) -> list[Note]:
        out: list[Note] = []
        if self.disallowed_loss:
            out.append(
                Note("deferred_note", {"deferred": f"{self.disallowed_loss:,.0f}"})
            )
        if self.recovered_loss:
            out.append(
                Note("recovered_note", {"recovered": f"{self.recovered_loss:,.0f}"})
            )
        if self.dividends:
            out.append(
                Note("dividends_note", {"dividends": f"{self.dividends:,.0f}"})
            )
        if self.cross_offset:
            out.append(
                Note("cross_offset_note", {"offset": f"{self.cross_offset:,.0f}"})
            )
        return out


def fiscal_period(
    realized: list[RealizedSale],
    period: str,
    buy_dates: Acquisitions,
    settings: TaxSettings | None = None,
) -> EsTaxPeriod:
    """Summarize an ISO date prefix ("YYYY" or "YYYY-MM") for the savings base.

    `buy_dates` maps ticker -> every acquisition in the ledger (see
    `tax.buy_dates`), used to apply the 2-month rule against replacement
    purchases in any year. The monthly slice is a breakdown, not a taxable
    base — IRPF nets the savings base over the whole ejercicio.
    """
    out = open_period(EsTaxPeriod, CODE, CURRENCY, period)
    blocks = repurchases(realized, buy_dates, WINDOW, REACHES)
    for s in sales_in(period, realized, YEAR_START):
        out.sales.append(s)
        gain = s.gain
        if gain >= 0:
            out.realized_gain += gain
            continue
        loss = -gain
        out.realized_loss += loss
        out.disallowed_loss += blocks.disallowed(s)
    out.recovered_loss = blocks.recovered(period)
    return out


def reporting_flags(
    total_foreign_value: float, settings: TaxSettings | None = None
) -> list[ReportingFlag]:
    """Modelo 720: the >50.000 EUR foreign-asset informative declaration.

    Applies to assets *held abroad* (e.g. via a non-Spanish broker/custodian).
    If your broker is Spanish-domiciled, securities are reported by the broker
    and 720 generally does not apply — hence a flag, not a verdict.
    """
    msg = (
        f"foreign holdings ~{total_foreign_value:,.0f} EUR "
        + (
            "≥ 50.000 EUR: Modelo 720 may apply if held via a non-Spanish broker."
            if total_foreign_value >= MODELO_720_THRESHOLD_EUR
            else "< 50.000 EUR threshold."
        )
    )
    return [
        flag("modelo_720", total_foreign_value, MODELO_720_THRESHOLD_EUR, msg)
    ]
