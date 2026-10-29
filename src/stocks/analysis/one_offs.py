"""What the trailing year's earnings carry that will not recur.

A trailing P/E divides the price by four filed quarters, and a filed quarter
can hold a tax charge, a gain on a stake or a legal settlement as easily as
earnings. Meta's EPS ran 1.05 in 2025Q3 (a ~16 B$ deferred-tax charge) and
10.44 in 2026Q1 (a tax benefit); Alphabet booked ~99 B$ of gains on its
equity stakes in one quarter, half its trailing pretax income. The chat
called Meta's 20.9x "clean and recurring" (local review 2026-10-29), so the
quarters are read here and what stands out is named, with the multiple the
year would carry without it.

Three tests over the quarterly income statement, all relative to the
company's own quarters, so no sector threshold is needed:

- **tax**: a quarter whose tax is far off the usual rate (the median over
  the quarters on file) — a one-off charge or benefit;
- **non-operating**: pretax income well above or below operating income over
  the year — gains or losses on stakes, mostly;
- **drop**: a quarter's operating income well below the same quarter a year
  earlier — a charge inside operating costs, or a real fall the filing
  explains. Against the year-ago quarter, not the year's median, so a
  seasonal business (Apple's December, Booking's summer) is not flagged;
  with no year-ago quarter on file the test is skipped. Only drops: a quarter
  well above its year-ago one is growth far more often than a one-off (Nvidia
  doubled), and a one-off gain lands outside operations, where the second
  test catches it.

The adjusted multiple puts the year on operating income at the usual tax
rate. It is the reading without the items, not a verdict that they will not
recur: that is what the filing says, and the answer is told to check it.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

import pandas as pd

QUARTERS = 4  # the trailing year
TAX_GAP = 0.10  # off the usual rate by more than this: a one-off
NON_OPERATING_SHARE = 0.10  # of trailing pretax income
OPERATING_GAP = 0.25  # off the year-ago quarter by more than this


@dataclass(frozen=True)
class Flag:
    period: str  # "2025Q3", or "trailing" for the year as a whole
    kind: str  # tax | non_operating | drop
    text: str


@dataclass(frozen=True)
class OneOffs:
    flags: tuple[Flag, ...]
    usual_tax: float
    # Trailing net income over the same year on operating income at the
    # usual tax rate: the trailing P/E times this is the multiple without
    # the flagged items.
    scale: float | None
    # The same, with each dropped quarter at its year-ago level.
    scale_level: float | None

    def adjust(self, pe: float | None, which: str = "scale") -> float | None:
        factor = getattr(self, which)
        return pe * factor if pe is not None and factor else None


def _row(income: pd.DataFrame, *labels: str) -> pd.Series | None:
    label = next((lbl for lbl in labels if lbl in income.index), None)
    if label is None:
        return None
    return pd.to_numeric(income.loc[label], errors="coerce")


def _period(col) -> str:
    return f"{col.year}Q{col.quarter}" if hasattr(col, "quarter") else str(col)[:10]


def _year_ago(series: pd.Series, col) -> float | None:
    """The same quarter a year before `col`, when it is on file."""
    if not hasattr(col, "year"):
        return None
    for c, v in series.items():
        if (isinstance(c, pd.Timestamp) and c.year == col.year - 1
                and c.quarter == col.quarter and pd.notna(v)):
            return float(v)
    return None


def _b(value: float) -> str:
    return f"{value / 1e9:.1f}B"


def read(income: pd.DataFrame | None) -> OneOffs | None:
    """The trailing year's one-offs, or None when four full quarters are not
    on file. `income` is yfinance's quarterly statement, newest first."""
    if income is None or income.empty:
        return None
    pretax = _row(income, "Pretax Income")
    operating = _row(income, "Operating Income", "Total Operating Income As Reported")
    tax = _row(income, "Tax Provision")
    net = _row(income, "Net Income Common Stockholders", "Net Income")
    if pretax is None or operating is None or tax is None or net is None:
        return None
    frame = pd.DataFrame({"pretax": pretax, "operating": operating,
                          "tax": tax, "net": net}).dropna()
    if len(frame) < QUARTERS:
        return None
    rates = [t / p for p, t in zip(frame["pretax"], frame["tax"], strict=True)
             if p > 0]
    if not rates:
        return None
    usual = min(max(median(rates), 0.0), 0.5)
    year = frame.iloc[:QUARTERS]
    flags: list[Flag] = []

    for col, q in year.iterrows():
        if q.pretax > 0 and abs(q.tax / q.pretax - usual) > TAX_GAP:
            extra = q.tax - usual * q.pretax
            flags.append(Flag(_period(col), "tax",
                              f"tax {q.tax / q.pretax:.0%} of pretax income vs a "
                              f"usual {usual:.0%}: a one-off tax "
                              + (f"charge of about {_b(extra)}" if extra > 0 else
                                 f"benefit of about {_b(-extra)}")))

    pretax_y, operating_y = year["pretax"].sum(), year["operating"].sum()
    outside = pretax_y - operating_y
    if pretax_y > 0 and abs(outside) > NON_OPERATING_SHARE * pretax_y:
        biggest = max(year.iterrows(), key=lambda cq: abs(cq[1].pretax - cq[1].operating))
        flags.append(Flag("trailing", "non_operating",
                          f"{_b(outside)} of the year's {_b(pretax_y)} pretax income "
                          f"({outside / pretax_y:.0%}) is outside operations "
                          f"(gains or losses on stakes, interest, FX), "
                          f"{_b(biggest[1].pretax - biggest[1].operating)} of it in "
                          f"{_period(biggest[0])}"))

    levelled = []
    for col, q in year.iterrows():
        levelled.append(q.operating)
        before = _year_ago(operating, col)
        if before is None or before <= 0:
            continue
        gap = q.operating / before - 1
        if gap < -OPERATING_GAP:
            flags.append(Flag(_period(col), "drop",
                              f"operating income {_b(q.operating)} vs {_b(before)} "
                              f"a year earlier ({gap:+.0%}): a one-off charge or "
                              "a real fall"))
            levelled[-1] = before

    reported = year["net"].sum()
    clean = operating_y * (1 - usual)
    level = sum(levelled) * (1 - usual)
    has_level = any(f.kind == "drop" for f in flags)
    return OneOffs(
        flags=tuple(flags),
        usual_tax=usual,
        scale=reported / clean if reported > 0 and clean > 0 else None,
        scale_level=(reported / level if has_level and reported > 0 and level > 0
                     else None),
    )
