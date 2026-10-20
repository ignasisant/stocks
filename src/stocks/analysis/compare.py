"""Several listings on one axis: how each moved over a window, in one currency.

The ticker page's comparison card asks "did this beat the index, its sector,
that rival?" — a question two price charts side by side cannot answer, because
each sits on its own scale and in its own money. Here every line is the same
thing: the total return (adjusted closes, so a dividend payer is not drawn
behind a grower for paying out) of one unit of the reader's currency put in on
the window's first day.

The axis is the subject's own sessions. Another listing is read at each of
those days as its last close on or before it: a US holiday leaves SPY flat for
a day under a European subject, and a coin's weekend has the shares carried
across it, rather than either line inventing a bar. A listing that starts
later than the window (a recent IPO) starts its line where its history does.

The review page asks the same question of a whole book at once, as one number
per name and window (`window_returns`): no axis to draw, only the two days a
return is measured between, read the same way.
"""

from __future__ import annotations

import pandas as pd

from stocks.analysis.history import WINDOW
from stocks.frames import midnight, midnights

# The window labels the card offers, in `analysis.history.PERIODS` spelling.
# Daily bars all: an intraday window would put a US session against a closed
# European one minute by minute.
RANGES: tuple[str, ...] = ("1m", "6m", "1y", "2y")

# The index every comparison opens with. One name is not a book: what it
# answers to is its sector and its rivals; the market is the one line that
# says whether all of them were worth holding. QQQ or EEM would be a second
# and third market line around a name that is neither (the search adds them).
INDICES: tuple[str, ...] = ("SPY",)

# The review map's trail steps back half a year at a time, so two years read
# as a path through four places rather than one line: a window's trail is its
# own first day and every step younger than it. 18m is a step, never a column.
TRAIL_STEPS: dict[str, pd.DateOffset] = {
    "6m": pd.DateOffset(months=6),
    "1y": pd.DateOffset(years=1),
    "18m": pd.DateOffset(months=18),
    "2y": pd.DateOffset(years=2),
}

# Rivals drawn when the card opens, beside the index and the sector's ETF:
# with the subject that is five lines, and the chips offer the rest.
OPENING_PEERS = 3

# Lines beside the subject. Past six the legend is longer than the chart is
# readable, and each one is a price download.
MAX_OTHERS = 6

# Related names offered as chips. Yahoo lists eight or more; past five they
# wrap the chips into a wall on a phone, and the search reaches the rest.
OFFERED_PEERS = 5


def day_index(index: pd.Index) -> pd.DatetimeIndex:
    """`index` as timezone-naive calendar days, one entry per day."""
    stamps = pd.DatetimeIndex(index)
    if stamps.tz is not None:
        stamps = stamps.tz_localize(None)
    return midnights(stamps)


def closes_by_day(closes: pd.Series) -> pd.Series:
    """`closes` keyed by calendar day, the day's last print kept."""
    s = closes.dropna()
    if s.empty:
        return s.astype(float)
    s = pd.Series(s.to_numpy(dtype=float), index=day_index(s.index))
    return s[~s.index.duplicated(keep="last")].sort_index()


def on_axis(closes: pd.Series, axis: pd.DatetimeIndex) -> pd.Series:
    """`closes` read at each day of `axis`: its last close on or before it.

    Nothing before the listing's first close — a line does not start before
    there is a price to start from.
    """
    s = closes_by_day(closes)
    if s.empty:
        return pd.Series(float("nan"), index=axis)
    joined = s.reindex(s.index.union(axis)).ffill()
    return joined.reindex(axis)


def rebased(values: pd.Series) -> list[float | None]:
    """Each value as a fraction gained since the series' first defined one."""
    defined = values.dropna()
    if defined.empty or not float(defined.iloc[0]):
        return [None] * len(values)
    first = float(defined.iloc[0])
    return [None if pd.isna(v) else float(v) / first - 1 for v in values]


def lines(
    closes: dict[str, pd.Series],
    rates: dict[str, pd.Series | None],
    axis: pd.DatetimeIndex,
) -> dict[str, list[float | None]]:
    """{ticker: cumulative return per axis day} in one currency.

    `rates[ticker]` turns that listing's closes into the reader's currency,
    already on `axis`; None means it is quoted in it. A ticker with no closes
    is left out rather than drawn flat.
    """
    out: dict[str, list[float | None]] = {}
    for ticker, series in closes.items():
        values = on_axis(series, axis)
        if values.isna().all():
            continue
        rate = rates.get(ticker)
        if rate is not None:
            values = values * rate.reindex(axis).ffill().bfill()
        points = rebased(values)
        if any(p is not None for p in points):
            out[ticker] = points
    return out


def rates_into(
    base: str, axis: pd.DatetimeIndex, quoted: dict[str, str | None]
) -> tuple[dict[str, pd.Series | None], set[str]]:
    """({name: daily rate of its currency into `base`}, names with none).

    A listing's minor unit (GBp) only rescales its closes, which a return
    does not see. A bare US symbol the profile memo has not met is quoted in
    dollars (`listing._lookup` asks Yahoo only for the names that can differ);
    anything else unknown is left off rather than measured in the wrong money.
    """
    from stocks.analysis.listing import quote_unit
    from stocks.analysis.portfolio import fx_frame
    from stocks.data.crypto import is_crypto

    isos: dict[str, str] = {}
    unpriced: set[str] = set()
    for name, code in quoted.items():
        iso = quote_unit(code)[0]
        if iso is None and "." not in name and not is_crypto(name):
            iso = "USD"
        if iso is None:
            unpriced.add(name)
        else:
            isos[name] = iso
    foreign = {iso for iso in isos.values() if iso != base}
    table = fx_frame(foreign, axis, base) if foreign else {}
    rates: dict[str, pd.Series | None] = {}
    for name, iso in isos.items():
        if iso == base:
            rates[name] = None
        elif iso in table:
            rates[name] = table[iso]
        else:
            unpriced.add(name)
    return rates, unpriced


def window_days(
    anchor: pd.Timestamp,
    sessions: pd.DatetimeIndex | None = None,
    spans: dict[str, pd.DateOffset] | None = None,
) -> dict[str, pd.Timestamp]:
    """{window: the day it opens on} for every range in `RANGES` (or each of
    `spans`), back from `anchor` — calendar months and years, as the price
    chart cuts them.

    Given `sessions` (the index's days), each opens on the first of them on or
    after that day, which is where `history.shape` starts a chart: a column and
    a chart over the same window then measure from the same close.
    """
    day = midnight(anchor)
    out: dict[str, pd.Timestamp] = {}
    for label, span in (spans or {label: WINDOW[label] for label in RANGES}).items():
        start = day - span
        if sessions is not None:
            later = sessions[sessions >= start]
            if len(later):
                start = midnight(later[0])
        out[label] = start
    return out


def window_axis(
    anchor: pd.Timestamp, days: dict[str, pd.Timestamp] | None = None
) -> pd.DatetimeIndex:
    """The only days `window_returns` reads: each window's first and `anchor`."""
    day = midnight(anchor)
    opens = days if days is not None else window_days(day)
    return pd.DatetimeIndex(sorted({*opens.values(), day}))


def window_returns(
    closes: pd.Series,
    rate: pd.Series | None,
    anchor: pd.Timestamp,
    days: dict[str, pd.Timestamp] | None = None,
) -> dict[str, float | None]:
    """{window: total return in the reader's money from its first day to
    `anchor`}, a fraction, or None where the listing has no price that far
    back. `days` are `window_days`' answer; by the calendar when omitted.

    Every name is read at the same two days — its last close on or before
    each — so a European close and a US one measured on one page cover the
    same stretch, and the gap between two of them is a gap in performance,
    not in calendars.
    """
    day = midnight(anchor)
    opens = days if days is not None else window_days(day)
    axis = window_axis(day, opens)
    values = on_axis(closes, axis)
    if rate is not None:
        values = values * rate.reindex(axis).ffill().bfill()
    end = values.get(day)
    out: dict[str, float | None] = {}
    for label, start in opens.items():
        first = values.get(start)
        defined = not (pd.isna(end) or pd.isna(first)) and float(first) != 0
        out[label] = float(end) / float(first) - 1 if defined else None
    return out
