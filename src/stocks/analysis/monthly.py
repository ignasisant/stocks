"""The book month by month since its first trade, and one window of it in euros.

`value / injected - 1` answers "how far above water am I" but not "how well did
my money do": €10k that sat in for two years and €10k that went in last week
count the same in it. So the rates here count each buy and sale from the exact
day it happened: at each month's close, the IRR from the book's first day to
that close, beside the annualised TWR — what the money earned given when it
went in, and what the picks earned whatever the timing.

Those rates are always since the first trade. A window does not rebase them:
it crops the months, as zooming into the full chart would. Re-taking them from
the window's first day read as if the book had been opened then — the old
money's run gone, and a calendar year that opened in a dip drawn below zero
for an account that was well above it. Neither is drawn before the book is a
year old: annualising a few months turns +7% into +278%, and de-annualising
the IRR back over them credits a late deposit's gain to money that was not in
yet — the reason GIPS forbids both.

What a window does take from its own first day is euros, because "what did
this year do" has an answer there that adds up to the cent: the value the
window opened with, plus what was bought, less what was sold, plus the gain,
is today's value. The ledger only sees trades, so a sale is money leaving even
when the cash stays at the broker, and a rotation is a sale and a buy.
`timing` puts the window's timing into euros too: today's value against what
the same opening value and the same trades would be worth had every euro grown
at the picks' steady pace over the window. Positive, the money arrived at good
moments; negative, the big deposits came before the falls.

The since-inception Modified Dietz this module first drew (gain over average
capital) is why the rates are an IRR: on a book that grew from €4k to €113k in
its last two years the average capital was €32k, and a dip on fresh money read
as +132% to 0% and back.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stocks.analysis.portfolio import annualized_return, money_weighted_return

_YEAR = pd.Timedelta(days=365)
_NAN = float("nan")


@dataclass(frozen=True)
class Window:
    """A window's euros, and the book's month-end rows inside it."""

    start: pd.Timestamp
    end: pd.Timestamp
    opening: float
    bought: float
    sold: float
    closing: float
    timing: float
    months: pd.DataFrame

    @property
    def contributed(self) -> float:
        return self.bought - self.sold

    @property
    def gain(self) -> float:
        return self.closing - self.opening - self.contributed


def window(
    hist: pd.DataFrame,
    twr: pd.Series,
    flows: pd.Series,
    start: pd.Timestamp | None = None,
) -> Window | None:
    """The book from `start` (None: its first day) to its last recorded one.

    `hist` is `book_history`'s daily frame (injected, value), `twr` its daily
    time-weighted returns and `flows` the `flow_series` — buys +, sales −, each
    on its own date. A `start` on or before the first day is the whole life of
    the book, opening at nothing with every trade inside it. Otherwise the
    window opens on the first recorded close on or after `start`, and its
    trades are the ones after that close (`money_weighted_return`'s
    convention).

    `months` is `month_ends` cropped to the window: since-inception figures,
    only the months after the window opens. None when nothing is priced.
    """
    value = hist["value"].dropna()
    if value.empty:
        return None
    first, end = value.index[0], value.index[-1]
    whole = start is None or start <= first
    t0 = first if whole else value.index[value.index >= start][0]
    opening = 0.0 if whole else float(value.loc[t0])
    if flows.empty:
        inside = flows
    elif whole:
        inside = flows[flows.index <= end]
    else:
        inside = flows[(flows.index > t0) & (flows.index <= end)]
    after = twr[twr.index > t0] if not twr.empty else twr

    months = month_ends(hist, twr, flows)
    if not whole:
        months = months[months.index > t0]
    closing = float(value.iloc[-1])
    return Window(
        start=t0,
        end=end,
        opening=opening,
        bought=float(inside[inside > 0].sum()) if not inside.empty else 0.0,
        sold=float(-inside[inside < 0].sum()) if not inside.empty else 0.0,
        closing=closing,
        timing=_timing(after, inside, opening, t0, end, closing),
        months=months,
    )


def month_ends(hist: pd.DataFrame, twr: pd.Series, flows: pd.Series) -> pd.DataFrame:
    """One row per calendar month since the first trade, on its last day.

    Levels are forward-filled over calendar days, so a month ending on a
    weekend holds Friday's book: `value`, `invested` — every buy so far less
    every sale, the injected total — and `gain` between them. `money_weighted`
    is the IRR from the first day to the close and `time_weighted` the
    annualised TWR over the same span; both NaN until the book is a year old.
    The current month is included as it stands.
    """
    columns = ["value", "invested", "gain", "money_weighted", "time_weighted"]
    value = hist["value"].dropna()
    if value.empty:
        return pd.DataFrame(columns=columns)
    first = value.index[0]

    daily = hist[["value"]].resample("D").last().ffill()
    daily = daily[daily.index >= first]
    closes = daily.groupby(pd.DatetimeIndex(daily.index).to_period("M")).tail(1)
    rows = []
    for close, level in closes["value"].items():
        invested = float(flows[flows.index <= close].sum()) if not flows.empty else 0.0
        if close - first < _YEAR:
            money = picks = _NAN
        else:
            money = money_weighted_return(value[value.index <= close], flows)
            run = twr[twr.index <= close] if not twr.empty else twr
            picks = annualized_return(run) if not run.empty else _NAN
        rows.append(
            {
                "value": level,
                "invested": invested,
                "gain": level - invested,
                "money_weighted": money,
                "time_weighted": picks,
            }
        )
    return pd.DataFrame(rows, index=closes.index, columns=columns)


def _timing(
    after: pd.Series,
    inside: pd.Series,
    opening: float,
    t0: pd.Timestamp,
    end: pd.Timestamp,
    closing: float,
) -> float:
    """Today's value less what it would be had every euro grown at the picks'
    steady pace: the opening value by the window's whole TWR growth, and each
    trade by that growth's share for the days it had left."""
    days = (end - t0).days
    if after.empty or days <= 0:
        return _NAN
    growth = float((1 + after).prod())
    if growth <= 0:
        return _NAN
    steady = opening * growth + sum(
        f * growth ** ((end - pd.Timestamp(day)).days / days)  # ty: ignore[invalid-argument-type]
        for day, f in inside.items()
    )
    return closing - steady
