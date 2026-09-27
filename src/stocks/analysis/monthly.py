"""The book at every month's close: where it stood, and what the money earned.

`value / injected - 1` answers "how far above water am I" but not "how well did
my money do": €10k that sat in for two years and €10k that went in last week
count the same in it. The figure here weighs each euro by how long it was in —
a Modified Dietz return taken from the book's first day to each month's close,
which with no opening value reduces to the gain over the time-averaged capital:

    return(t) = (value(t) - injected(t)) / mean(injected over [start, t])

So a deposit moves the denominator by its amount *and* the share of the span
it was invested for, and a month where most of the money had just arrived does
not read as the older money's result. The TWR rides alongside, since inception
too, as the flow-free comparison: it scores the picks, this scores the account.
"""

from __future__ import annotations

import pandas as pd

from stocks.analysis.portfolio import cumulative_returns


def month_ends(hist: pd.DataFrame, twr: pd.Series) -> pd.DataFrame:
    """One row per calendar month: the book on its last recorded day.

    `hist` is `book_history`'s daily frame (injected, value). The average is
    taken over calendar days, forward-filled, so a weekend holds the capital
    that was in it rather than being skipped. The current month is included as
    it stands. `money_weighted` is NaN where the average capital is not
    positive — a book that took more out than it put in has no base to
    divide by, and a sign flip there would read as a result.
    """
    columns = ["injected", "value", "pnl", "money_weighted", "twr"]
    frame = hist[["injected", "value"]].dropna(subset=["injected"])
    if frame.empty:
        return pd.DataFrame(columns=columns)

    daily = frame.resample("D").last().ffill()
    capital = daily["injected"].expanding().mean()
    gain = daily["value"] - daily["injected"]
    money_weighted = (gain / capital).where(capital > 0)

    index = pd.Series(dtype=float)
    if not twr.empty:
        index = cumulative_returns(twr).reindex(daily.index).ffill()

    out = pd.DataFrame(
        {
            "injected": daily["injected"],
            "value": daily["value"],
            "pnl": gain,
            "money_weighted": money_weighted,
            "twr": index if not index.empty else float("nan"),
        }
    )
    return out.groupby(pd.DatetimeIndex(out.index).to_period("M")).tail(1)[columns]
