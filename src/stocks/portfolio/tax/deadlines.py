"""The filing calendar each jurisdiction imposes on an investor.

The earnings calendar is where a reader already looks for dates that move
money, so the tax deadlines ride along on it: Modelo 720 and the renta in
Spain, the 1040 and FBAR in the US, Self Assessment in the UK. Each rule is a
(month, day) in the calendar year `offset` years after the tax year it closes
*opens* — the UK's 2025/26 opens 6 April 2025 and its online return is due
31 January 2027, two years on.

Only the dates a private investor with a brokerage account meets. Payroll,
VAT and company deadlines are somebody else's calendar.

Dates are statutory defaults, not the year's official calendar. Where the law
moves a deadline that lands on a weekend to the next working day, `ROLLS`
applies that; public holidays are not modelled, and a handful of deadlines
(France's by département, Switzerland's by canton) are only approximate and
say so through `approximate`, which the copy turns into "around".

Language-free on purpose: a deadline is a catalog stem (`es_renta`) and a
date; the client names it (`earnings.tax_es_renta`, `…_body`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from stocks.portfolio import tax

# How far ahead a deadline starts being announced — on the calendar's banner
# and once in the Telegram digest.
REMIND_DAYS = 30

# The window the calendar is sent: enough behind to page back a couple of
# months, enough ahead to page through the next year.
BEHIND_DAYS = 62
AHEAD_DAYS = 400


@dataclass(frozen=True)
class Rule:
    key: str  # catalog stem, without the jurisdiction prefix
    month: int
    day: int
    # Calendar years after the tax year opens. 1 is "the year after".
    offset: int = 1
    approximate: bool = False


@dataclass(frozen=True)
class Deadline:
    code: str
    key: str  # "<code>_<rule>", lower case — the catalog stem
    date: date
    tax_year: int  # the calendar year the tax year it concerns opens in
    year_label: str  # how the jurisdiction writes it: "2025", "2025/26"
    approximate: bool = False

    @property
    def id(self) -> str:
        """Stable identity across runs, for "already reminded" bookkeeping."""
        return f"{self.key}:{self.tax_year}"

    def days_until(self, today: date) -> int:
        return (self.date - today).days

    def due_soon(self, today: date, within: int = REMIND_DAYS) -> bool:
        return 0 <= self.days_until(today) <= within


RULES: dict[str, tuple[Rule, ...]] = {
    "ES": (
        # Informative returns on assets abroad: securities / crypto > 50.000 EUR.
        Rule("modelo_720", 3, 31),
        Rule("modelo_721", 3, 31),
        # The IRPF campaign closes 30 June; a split payment's second half is
        # charged on 5 November.
        Rule("renta", 6, 30),
        Rule("renta_second", 11, 5),
    ),
    "US": (
        Rule("estimated_q4", 1, 15),
        Rule("form_1040", 4, 15),
        Rule("fbar", 4, 15),
        Rule("extension", 10, 15),
        Rule("estimated_q1", 4, 15, offset=0),
        Rule("estimated_q2", 6, 15, offset=0),
        Rule("estimated_q3", 9, 15, offset=0),
    ),
    "UK": (
        Rule("payment_on_account", 7, 31),
        Rule("self_assessment", 1, 31, offset=2),
    ),
    "DE": (Rule("steuererklaerung", 7, 31),),
    "FR": (Rule("declaration", 5, 22, approximate=True),),
    "IT": (
        Rule("saldo", 6, 30),
        Rule("modello_730", 9, 30),
        Rule("redditi", 10, 31),
        Rule("acconto", 11, 30, offset=0),
    ),
    "IE": (
        Rule("cgt_initial", 12, 15, offset=0),
        Rule("cgt_later", 1, 31),
        Rule("form_11", 10, 31),
    ),
    "PT": (Rule("irs", 6, 30),),
    "CA": (Rule("t1", 4, 30),),
    "AU": (Rule("tax_return", 10, 31),),
    "CH": (Rule("declaration", 3, 31, approximate=True),),
    # No personal income tax, so no personal return.
    "AE": (),
}

# Jurisdictions whose law moves a deadline that falls on a Saturday or Sunday
# to the following Monday. HMRC's 31 January and Revenue's dates do not move.
ROLLS = frozenset({"ES", "US", "DE", "IT", "PT", "CA", "AU"})


def _rolled(code: str, day: date) -> date:
    if code not in ROLLS:
        return day
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def calendar(
    code: str | None,
    today: date,
    behind: int = BEHIND_DAYS,
    ahead: int = AHEAD_DAYS,
) -> list[Deadline]:
    """Deadlines from `behind` days ago to `ahead` days on, soonest first."""
    jurisdiction = tax.get(code)
    start, end = today - timedelta(days=behind), today + timedelta(days=ahead)
    out: list[Deadline] = []
    for year in range(start.year - 3, end.year + 1):
        for rule in RULES.get(jurisdiction.code, ()):
            when = _rolled(
                jurisdiction.code, date(year + rule.offset, rule.month, rule.day)
            )
            if start <= when <= end:
                out.append(
                    Deadline(
                        code=jurisdiction.code,
                        key=f"{jurisdiction.code.lower()}_{rule.key}",
                        date=when,
                        tax_year=year,
                        year_label=jurisdiction.year_label(year),
                        approximate=rule.approximate,
                    )
                )
    return sorted(out, key=lambda d: (d.date, d.key))


def due_soon(
    code: str | None, today: date, within: int = REMIND_DAYS
) -> list[Deadline]:
    """The deadlines landing in the next `within` days, today included."""
    return [
        d for d in calendar(code, today, behind=0, ahead=within)
        if d.due_soon(today, within)
    ]
