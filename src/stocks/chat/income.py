"""What did my dividends pay, net? The ledger's dividend rows, summed per year.

"Dividendos netos y doble imposición deducible" is a question about rows the
reader imported: each dividend carries its gross and the tax withheld at
source (`portfolio/dividends.py`), and the Income tab sums them. Asked with no
such figures in front of it, the model answered "no tengo acceso a tu
información personal" and wrote a formula in raw LaTeX (local review
2026-10-29). So the years are summed here and ride on the question, as the
allocation's weights do (`chat/allocation.py`); Gemini, which has no tool
loop, gets them too.

Spain relieves foreign withholding through the double-taxation credit, capped
at the treaty rate; `DividendYear` already splits the creditable part from
the part only the source country can refund, and that split is quoted for a
Spanish filer. Elsewhere the figures go without it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from stocks import obs
from stocks.formatting import bound

# The years quoted: the current one and the last full one, newest first.
YEARS = 2
TOP_PAYERS = 5

_DIVIDEND_RE = re.compile(r"\bdividend|\bcupon|\bcoupon|\bpayout\b|\brentas?\b",
                          re.IGNORECASE)
# ... the reader's own, received, or what tax takes from them.
_MINE_RE = re.compile(
    r"\b(?:mi|mis|my)\b|\btengo\b|\bhe cobrado\b|\bcobr|\breceived\b|\bi got\b|"
    r"\bneto|\bnet\b|\bretenci|\bretenid|\bwithh[eo]ld|\bdoble imposicion\b|"
    r"\bdouble taxation\b|\bdeducib|\bdeduct|\bcredit\b|\bhacienda\b|\brenta\b",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(ch))


def wants(message: str) -> bool:
    """Whether the message asks about the reader's own dividend income."""
    text = _fold(message)
    return bool(_DIVIDEND_RE.search(text) and _MINE_RE.search(text))


@dataclass(frozen=True)
class Year:
    year: int
    gross: float
    withheld: float
    creditable: float
    reclaimable: float
    payments: int
    unreported: int  # foreign payments booked with no withholding at all
    payers: tuple[tuple[str, float], ...]  # (ticker, gross), largest first

    @property
    def net(self) -> float:
        return self.gross - self.withheld


@dataclass(frozen=True)
class Income:
    currency: str
    spanish: bool  # the double-taxation split applies
    years: tuple[Year, ...]

    def line(self, lang: str = "en") -> str:
        """The prompt's paragraph: each year's dividends, quoted."""
        n, p = bound(lang)

        def money(value: float) -> str:
            return f"{n(value, 2)} {self.currency}"

        rows = []
        for y in self.years:
            row = (f"- {y.year}: {y.payments} payments, gross {money(y.gross)}, "
                   f"withheld at source {money(y.withheld)}"
                   + (f" ({p(y.withheld / y.gross, 1)})" if y.gross else "")
                   + f", net received {money(y.net)}")
            if self.spanish:
                row += (f"; double-taxation credit (art. 80 LIRPF, capped at the "
                        f"15% treaty rate) {money(y.creditable)}, refundable "
                        f"only from the source country {money(y.reclaimable)}")
            if y.payers:
                row += "; largest payers " + ", ".join(
                    f"{t} {money(g)}" for t, g in y.payers)
            if y.unreported:
                row += (f"; {y.unreported} foreign payments were booked with no "
                        "withholding, which usually means the statement did not "
                        "report it, not that none was taken")
            rows.append(row)
        found = "\n".join(rows) if rows else "- no dividend booked in these years"
        return (
            "\n\n---\nThe reader's own dividends, from the payments in their "
            f"ledger (the Income tab's figures), in {self.currency} at each pay "
            "date's rate. The ledger records the tax withheld abroad; any "
            "withholding their own country takes on top is not in it. Answer "
            "from these figures, and say they come from what was imported:\n"
            + found
        )


def build(db: Path, prefs_path: Path | None, today: date | None = None) -> Income | None:
    """The reader's dividend years, or None without a ledger."""
    from stocks.portfolio import dividends, tax
    from stocks.portfolio.ledger import all_transactions
    from stocks.portfolio.tax import es
    from stocks.portfolio.tax import prefs as tax_prefs

    txs = all_transactions(db) if db.exists() else []
    if not txs:
        return None
    code, _how = tax_prefs.resolve(tax_prefs.load(prefs_path) if prefs_path else {})
    jur = tax.get(code)
    by_year = dividends.by_year(txs, base=jur.currency)
    this = (today or date.today()).year
    years = []
    for year in range(this, this - YEARS, -1):
        dy = by_year.get(year)
        if dy is None:
            continue
        years.append(Year(
            year=year, gross=dy.gross, withheld=dy.withheld,
            creditable=dy.creditable, reclaimable=dy.reclaimable,
            payments=len(dy.records),
            unreported=sum(1 for t in dy.records
                           if t.fee <= 0 and t.currency.upper() != jur.currency),
            payers=tuple(sorted(dy.by_ticker.items(), key=lambda tg: -tg[1])
                         [:TOP_PAYERS]),
        ))
    obs.event("chat.income", years=len(years))
    return Income(currency=jur.currency, spanish=jur.code == es.CODE,
                  years=tuple(years))
