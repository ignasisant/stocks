"""The daily card's "Portfolio" section: the book against the index, computed.

The first thing a reader checks every morning is how the book did and how the
market did: today, this week, this month. Those figures are computed, never
written. The model is shown them (`facts["index"]` next to the book's own
`day` / `week` / `month`), may quote them in its headline and is audited
against them, but the section itself is drawn from the numbers here.

The book is the fixed basket (`loaders.basket_values`): today's shares priced
back over the window, so a deposit inside the month is not a gain. It is the
frame and the anchoring (`basket_change`) the KPI row and the card's `day` /
`week` / `month` facts already use, so the chart ends where the month row
says. The index is SPY in the reader's own currency
(`briefing.index_in_base`): a euro book measured against a dollar index
reports the currency's move as skill.

Headless like `daily`: the API's `briefing` is only reached lazily, for the
index conversion its market lines already make.
"""

from __future__ import annotations

import pandas as pd

INDEX_NAME = "S&P 500"
INDEX_SYMBOL = "SPY"
# (row, calendar days): `basket_change`'s windows, which the facts use.
WINDOWS = (("day", 1), ("week", 7), ("month", 30))
CHART_DAYS = 30
BOOK = "@BOOK"


def _naive(series: pd.Series) -> pd.Series:
    """`series` on naive dates, one value a day, oldest first."""
    from stocks.analysis import naive_dates

    out = series.dropna().copy()
    out.index = naive_dates(out.index)
    return out[~out.index.duplicated(keep="last")].sort_index()


def _start(index: pd.Index, days: int):
    """Where a window of `days` calendar days opens on `index`, anchored as
    `basket_change` anchors it; None when `index` does not reach that far."""
    if len(index) < 2:
        return None
    if days <= 1:
        return index[-2]
    prior = index[index <= index[-1] - pd.Timedelta(days=days)]
    return prior[-1] if len(prior) else None


def change(series: pd.Series, days: int) -> float | None:
    """The change of `series` over ~`days` calendar days, as a fraction."""
    start = _start(series.index, days)
    if start is None:
        return None
    first = float(series.loc[start])
    return float(series.iloc[-1]) / first - 1 if first else None


def index_series(closes: dict | None, currency: str) -> tuple[pd.Series | None, str]:
    """(SPY's closes in the reader's currency, the currency they are in).
    Only the euro pair is downloaded, so another base reads the index in its
    own dollars."""
    from stocks.api.briefing import index_in_base

    series = index_in_base(closes or {}, currency)
    if series is None or len(series) < 2:
        return None, ""
    return _naive(series), currency if currency == "EUR" else "USD"


def index_facts(closes: dict | None, currency: str) -> dict | None:
    """The index's day, week and month, as the card's facts carry them."""
    series, unit = index_series(closes, currency)
    if series is None:
        return None
    out: dict = {
        "name": INDEX_NAME,
        "symbol": INDEX_SYMBOL,
        "currency": unit,
        "as_of": series.index[-1].date().isoformat(),
    }
    for label, days in WINDOWS:
        moved = change(series, days)
        out[f"{label}_pct"] = None if moved is None else round(moved * 100, 2)
    return out


def rows(facts: dict) -> list[dict]:
    """The section's rows: {window, pct, amount, index_pct}, one a window
    the book has a figure for. A watchlist-only account has none: the
    section is about the reader's book, and the index alone is not it."""
    index = (facts or {}).get("index") or {}
    out = []
    for label, _days in WINDOWS:
        own = (facts or {}).get(label) or {}
        theirs = index.get(f"{label}_pct")
        if own.get("pct") is None:
            continue
        out.append({
            "window": label,
            "pct": own.get("pct"),
            "amount": own.get("amount"),
            "index_pct": theirs,
        })
    return out


def section(facts: dict) -> dict:
    """The section as a card stores it, chart aside: {} with nothing to show.

    Only with the index in the facts: the section is the book *against* it,
    and the book's own figures alone are the KPI row above the card. A card
    built without it (one stored before the section existed, a failed
    download) has none.
    """
    index = (facts or {}).get("index") or {}
    found = rows(facts) if index else []
    if not found:
        return {}
    return {
        "index": index.get("name") or INDEX_NAME,
        "currency": str((facts or {}).get("currency") or ""),
        "rows": found,
    }


def chart(
    hist: pd.DataFrame | None,
    closes: dict | None,
    currency: str,
    *,
    label: str = "",
    days: int = CHART_DAYS,
) -> list[dict]:
    """The month drawn: the book and the index as growth from the window's
    first day, in the shape the drawer's chart takes (`charts.series`).

    The book is summed over the names priced at both ends of the window, as
    `basket_change` sums it, so its last point is the month row's figure.
    [] when the basket does not reach back that far.
    """
    if hist is None or len(hist) < 2:
        return []
    frame = hist.copy()
    frame.index = pd.DatetimeIndex(frame.index)
    start = _start(frame.index, days)
    if start is None:
        start = frame.index[0]
    window = frame.loc[start:]
    both = window.loc[start].notna() & window.iloc[-1].notna()
    values = window.loc[:, both].ffill().sum(axis=1)
    first = float(values.iloc[0]) if len(values) else 0.0
    if len(values) < 2 or first <= 0:
        return []
    out = [_line(BOOK, currency, values / first * 100, label)]
    series, unit = index_series(closes, currency)
    if series is not None:
        before = series.index[series.index <= values.index[0]]
        since = series[series.index >= (before[-1] if len(before) else values.index[0])]
        if len(since) >= 2:
            out.append(_line(INDEX_SYMBOL, unit, since / float(since.iloc[0]) * 100,
                             INDEX_NAME))
    return out


def _line(symbol: str, currency: str, series: pd.Series, label: str) -> dict:
    return {
        "symbol": symbol,
        "currency": currency,
        "dates": [pd.Timestamp(i).date().isoformat() for i in series.index],
        "values": [round(float(v), 4) for v in series.to_numpy()],
        # Growth from the window's first day, not a price: the drawer's chart
        # prints its change alone.
        "index": True,
        "label": label,
    }
