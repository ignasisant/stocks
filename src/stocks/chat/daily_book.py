"""The daily card's "Portfolio" section: the book against the index, computed.

The first thing a reader checks every morning is how the book did and how the
market did: today, this week, this month. Those figures are computed, never
written. The model is shown them (`facts["index"]` next to the book's own
`day` / `week` / `month`), may quote them in its headline and is audited
against them, but the section itself is drawn from the numbers here.

The book is set against the index on its own money (`portfolio.same_money`):
the index bought with what the book held where the window opens, then with
every euro put in and sold for every euro taken out, on the same days. How
much money was in, and when, decides what a return is worth — an index that
had all of today's money from the first day, or a time-weighted return that
ignores how much there was, credits the reader with gains made on money they
had not put in yet. The card's `week` / `month` facts (`money_change`,
`index_change`) and the chart read the same money, so the chart ends where
the month row says. The index is SPY in the reader's own currency
(`briefing.index_in_base`): a euro book measured against a dollar index
reports the currency's move as skill.

Headless like `daily`: the API's `briefing` is only reached lazily, for the
index conversion its market lines already make.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

INDEX_NAME = "S&P 500"
INDEX_SYMBOL = "SPY"
# (row, calendar days): the windows the facts use (`money_change`).
WINDOWS = (("day", 1), ("week", 7), ("month", 30))
CHART_DAYS = 30
BOOK = "@BOOK"

# What else the book can be laid against on the Today page: symbol -> (name,
# the currency it is quoted in). The world and the reader's own market beside
# the S&P, ETFs where the index itself has no clean Yahoo series. Each is
# converted into the reader's currency like SPY is, for the reason the module
# gives.
INDEXES: dict[str, tuple[str, str]] = {
    INDEX_SYMBOL: (INDEX_NAME, "USD"),
    "QQQ": ("Nasdaq 100", "USD"),
    "URTH": ("MSCI World", "USD"),
    "EEM": ("MSCI EM", "USD"),
    "^STOXX50E": ("Euro Stoxx 50", "EUR"),
    "^IBEX": ("IBEX 35", "EUR"),
}
# The windows the chart can be drawn over, in calendar days; "ytd" opens on
# the year's last close before January (`window_days`). A book younger than
# the window is drawn from its first trade, where its prices begin — which is
# all "max" asks: a century no book reaches back.
RANGES: dict[str, int] = {
    "1m": CHART_DAYS, "3m": 91, "6m": 182, "1y": 365, "2y": 730, "5y": 1826,
    "max": 36525,
}


def _naive(series: pd.Series) -> pd.Series:
    """`series` on naive dates, one value a day, oldest first."""
    from stocks.analysis import naive_dates

    out = series.dropna().copy()
    out.index = naive_dates(out.index)
    return out[~out.index.duplicated(keep="last")].sort_index()


def _start(index: pd.Index, days: int):
    """Where a window of `days` calendar days opens on `index`, anchored as
    `money_change` anchors it; None when `index` does not reach that far."""
    if len(index) < 2:
        return None
    if days <= 1:
        return index[-2]
    prior = index[np.asarray(index <= index[-1] - pd.Timedelta(days=days))]
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


def compare_series(
    closes: dict | None, currency: str, symbol: str
) -> tuple[pd.Series | None, str]:
    """(one of `INDEXES` in the reader's currency, the currency it is in).

    SPY reads through `index_series`, the card's own conversion. The rest are
    converted at the ECB's daily rate the book's positions are valued at; a
    rate that cannot be had leaves the index in its own currency, and says so.
    """
    if symbol == INDEX_SYMBOL:
        return index_series(closes, currency)
    raw = (closes or {}).get(symbol)
    if raw is None or raw.dropna().empty or symbol not in INDEXES:
        return None, ""
    series = _naive(raw)
    if len(series) < 2:
        return None, ""
    native = INDEXES[symbol][1]
    if native == currency:
        return series, currency
    from stocks.analysis.portfolio import fx_frame

    rate = fx_frame([native], series.index, currency).get(native)
    if rate is None:
        return series, native
    converted = (series * rate.reindex(series.index).ffill()).dropna()
    return (converted, currency) if len(converted) >= 2 else (series, native)


def window_days(span: str, today: pd.Timestamp | None = None) -> int:
    """Calendar days `span` reaches back: one of `RANGES`, or "ytd" — to
    the last close of the year before, so January's first session counts."""
    if span == "ytd":
        now = (today or pd.Timestamp.today()).normalize()
        return max(1, int((now - pd.Timestamp(year=now.year, month=1, day=1)).days) + 1)
    return RANGES.get(span, CHART_DAYS)


def index_facts(
    closes: dict | None, currency: str, hist: pd.DataFrame | None = None
) -> dict | None:
    """The index's day, week and month, as the card's facts carry them.

    With the book's `hist`, the week and month are what the book's own money
    would have made in the index (`index_change`), set beside the book's
    `money_change`; the day, which no deposit moves, is the index's close."""
    from stocks.analysis.portfolio import index_change

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
        if hist is not None and not hist.empty and days > 1:
            same = index_change(hist, series, days)
            moved = None if same is None else same[1]
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


def versus(
    hist: pd.DataFrame | None,
    closes: dict | None,
    currency: str,
    *,
    label: str = "",
    days: int = CHART_DAYS,
    index: str = INDEX_SYMBOL,
) -> list[dict]:
    """The book and `index` in money over `days`, in the shape the drawer's
    chart takes (`charts.series`).

    The book is what it was worth each day, the money put in by then beside
    it; the index is that same money in `index` (`same_money`): bought on the
    book's first day the index reaches (`opens`), then every deposit and sale
    on its own day, and only then cut to the window — a shorter window shows
    that stretch of the whole race, not a race restarted where it opens. The
    gap between the lines is what the reader's picks made or lost against the
    index since then, in euros. [] when it cannot be drawn."""
    from stocks.analysis.portfolio import same_money

    if hist is None or hist.empty or not {"value", "injected"} <= set(hist):
        return []
    value = _naive(hist["value"])
    injected = _naive(hist["injected"]).reindex(value.index, method="ffill")
    start = _start(value.index, days) or value.index[0]
    window = value.loc[start:]
    if len(window) < 2:
        return []
    book = _line(BOOK, currency, window, label)
    book["injected"] = [round(float(v), 2) for v in injected.loc[start:].to_numpy()]
    out = [book]
    series, unit = (
        index_series(closes, currency)
        if index == INDEX_SYMBOL
        else compare_series(closes, currency, index)
    )
    # Bought with euros only when the index is in them: dollars a euro book
    # never spent would make the gap the exchange rate's.
    if series is not None and unit == currency:
        # Bought from the book's first day the index reaches, then cut to the
        # window: a window is a stretch of the whole race, not a fresh start.
        opens = max(value.index[0], series.index[0])
        shadow = same_money(pd.DataFrame({"value": value, "injected": injected}),
                            series, opens)
        shadow = None if shadow is None else shadow.loc[start:]
        if shadow is not None and len(shadow) >= 2:
            line = _line(index, currency, shadow, INDEXES.get(index, (index, ""))[0])
            line["opens"] = opens.date().isoformat()
            out.append(line)
    return out


def _line(symbol: str, currency: str, series: pd.Series, label: str) -> dict:
    return {
        "symbol": symbol,
        "currency": currency,
        "dates": [pd.Timestamp(i).date().isoformat() for i in series.index],
        "values": [round(float(v), 2) for v in series.to_numpy()],
        # Money, not a price: the drawer's chart prints it as an amount.
        "money": True,
        "label": label,
    }
