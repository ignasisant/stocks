"""How the book has done: TWR and IRR, what moved it, its daily and
monthly path.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from stocks.analysis.monthly import window as book_window
from stocks.analysis.portfolio import (
    annualized_return,
    annualized_volatility,
    cumulative_returns,
    drawdown_span,
    flow_series,
    historical_var,
    max_drawdown,
    money_weighted_return,
)
from stocks.analysis.return_attribution import attribution as decompose
from stocks.api import loaders
from stocks.api.deps import Account, Base, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import Attribution, AttributionMover, Performance

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# The windows `/performance` measures the book's own path over — the same
# choices the risk card offers, so one selector drives both cards on the page.
# Counted back from today, as the page counts them, not from the series' last
# day: "the last year" of a book is the calendar's last year.
_PERFORMANCE_DAYS = {"6mo": 182, "1y": 365, "2y": 730, "5y": 1826}
_PERFORMANCE_WINDOWS = ("inception", *_PERFORMANCE_DAYS)
# A year of span, less a week: a "1y" window starts on the first trading day
# after today-365, so its path is a few days short of 365 and would read as
# young when it is the full year asked for.
_YEAR = pd.Timedelta(days=358)

# Windows the daily series is offered over, in calendar days — the union of the
# two range controls the app already has, under the same codes, so a client and
# a page open on two screens draw the same span: the Portfolio page's chart
# (1m/3m/6m/1y) and the Home sparkline's (1w/1m/6m/1y/2y/5y). "ytd" and "all"
# are spelled out below because neither is a fixed number of days.
_HISTORY_SPANS = {
    "1w": 7,
    "1m": 30,
    "3m": 91,
    "6m": 182,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}
_HISTORY_WINDOWS = (*_HISTORY_SPANS, "ytd", "all")


@router.get("/performance", response_model=Performance, summary="TWR and IRR")
def performance(
    account: Account,
    base: Base = None,
    window: Annotated[
        str,
        Query(description=f"One of {', '.join(_PERFORMANCE_WINDOWS)}."),
    ] = "inception",
) -> Performance:
    """How the book has done, both ways of asking.

    TWR strips flow timing out, so it measures the selection and is comparable
    against an index. IRR leaves flow timing in, so it measures what the money
    actually did. They answer different questions and routinely disagree —
    hence both, never one standing in for the other.

    `window` re-takes every figure from its start, as the page's window
    selector does: the TWR, its volatility and drawdown over the clipped path,
    and the IRR with the book's value on the first day as the buy-in
    (`money_weighted_return(start=)`). `injected` and `value` stay the latest
    levels — they are where the book stands, not a return over anything —
    and `injected_window` is that buy-in plus the money put in since, which
    is what `value` is read against over a window. Under a year of span the
    IRR and `twr_annualised` are cumulative, flagged by `irr_annualised` /
    `twr_is_annual`.
    """
    if window not in _PERFORMANCE_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"window must be one of {', '.join(_PERFORMANCE_WINDOWS)}",
        )
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    hist, twr, missing = loaders.history(db, mtime, ccy)
    if hist.empty:
        return Performance(base=ccy, window=window, missing=missing)

    # Read before the clip: a slice is not guaranteed to carry `attrs` along.
    dropped = tuple(twr.attrs.get("dropped_days", ()))
    start: pd.Timestamp | None = None
    if window in _PERFORMANCE_DAYS:
        start = pd.Timestamp(date.today()) - pd.Timedelta(days=_PERFORMANCE_DAYS[window])  # ty: ignore[invalid-assignment]  -- today minus days is never NaT
        # The window opens at the start day's close, as the Today chart and
        # `money_change` anchor it: that day's own return is the day before
        # the window, and counting it made a year one session longer.
        twr = twr[twr.index > start] if not twr.empty else twr
    cumulative = float((1 + twr).prod() - 1) if not twr.empty else float("nan")
    # Over the span the return was actually measured on, not the ledger's:
    # a book that sat empty for a year has no return for it, and dividing the
    # compounding by those months understates what the money that was in did.
    annualised = annualized_return(twr) if not twr.empty else float("nan")
    txs = loaders.ledger_state(db, mtime, ccy)[0]
    flows = flow_series(txs, base=ccy)
    shown = hist[hist.index >= start] if start is not None else hist
    if shown.empty:
        shown = hist
    # Same rule as the monthly table (`analysis.monthly`): a pace is only
    # quoted per year once there is a year of it. Inside the first year a
    # +8% over three months compounds to a headline nobody earned, so both
    # money-weighted and time-weighted read what they made over the span.
    spanned = pd.Timestamp(shown.index[-1]) - pd.Timestamp(shown.index[0])
    annual = spanned >= _YEAR
    irr = money_weighted_return(hist["value"], flows, start=start, annual=annual)
    if not annual and not twr.empty:
        annualised = cumulative
    # The window's buy-in, exactly as the IRR above takes it: the book's value
    # on the first day plus what went in after it. Since inception that is the
    # all-time net money in, which is what `injected` already says.
    value_path = hist["value"].dropna()
    if start is not None:
        clipped = value_path[value_path.index >= start]
        value_path = clipped if not clipped.empty else value_path
    if start is None or value_path.empty:
        buy_in = _num(hist["injected"].iloc[-1])
    else:
        t0 = value_path.index[0]
        later = flows[(flows.index > t0)] if not flows.empty else flows
        buy_in = _num(float(value_path.iloc[0]) + float(later.sum()))
    path = cumulative_returns(twr) + 1
    span = drawdown_span(path)

    return Performance(
        base=ccy,
        window=window,
        start=str(pd.Timestamp(shown.index[0]).date()),
        end=str(pd.Timestamp(hist.index[-1]).date()),
        injected=_num(hist["injected"].iloc[-1]),
        injected_window=buy_in,
        value=_num(loaders.book_value_today(db, mtime, ccy, hist)),
        twr_cumulative=_num(cumulative),
        twr_annualised=_num(annualised),
        twr_is_annual=annual,
        # Volatility and drawdown of the flow-adjusted path, which is the only
        # series either can be taken over honestly: the book's own value moves
        # every time money is added, and a deposit is not a return.
        twr_volatility=_num(annualized_volatility(twr)),
        twr_max_drawdown=_num(max_drawdown(path)),
        twr_var_95=_num(historical_var(twr)),
        twr_drawdown_peak=str(span[0].date()) if span else None,
        twr_drawdown_trough=str(span[1].date()) if span else None,
        twr_drawdown_peak_value=(_num(hist["value"].get(span[0])) if span else None),
        dropped_days=[
            str(pd.Timestamp(day).date())
            for day in dropped
            if start is None or pd.Timestamp(day) > start
        ],
        irr=_num(irr),
        irr_annualised=annual,
        missing=missing,
    )


@router.get("/attribution", response_model=Attribution, summary="What moved the book")
def attribution(
    account: Account,
    base: Base = None,
    window: Annotated[
        str,
        Query(description=f"One of {', '.join(_PERFORMANCE_WINDOWS)}."),
    ] = "inception",
) -> Attribution:
    """The window's change in value, split into bars that add up exactly.

    Start value, net contributions, price, currency, dividends, commissions,
    and an `other` bar that is zero unless something could not be placed. The
    window opens where `/performance` opens it, so the two cards describe the
    same days. Taken off the very frame `/performance` reads, with no fetch of
    its own.
    """
    if window not in _PERFORMANCE_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"window must be one of {', '.join(_PERFORMANCE_WINDOWS)}",
        )
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    hist, _, missing = loaders.history(db, mtime, ccy)
    if hist.empty:
        return Attribution(base=ccy, window=window, missing=missing)
    start = (
        pd.Timestamp(date.today()) - pd.Timedelta(days=_PERFORMANCE_DAYS[window])
        if window in _PERFORMANCE_DAYS
        else None
    )
    txs = loaders.ledger_state(db, mtime, ccy)[0]
    parts = decompose(hist, txs, start=start, base=ccy)  # ty: ignore[invalid-argument-type]
    if parts is None:
        return Attribution(base=ccy, window=window, missing=missing)
    ranked = sorted(parts.movers.items(), key=lambda kv: kv[1])
    return Attribution(
        base=ccy,
        window=window,
        start=parts.start,
        end=parts.end,
        start_value=_num(parts.start_value),
        contributions=_num(parts.contributions) or 0.0,
        price=_num(parts.price) or 0.0,
        fx=_num(parts.fx) or 0.0,
        dividends=_num(parts.dividends) or 0.0,
        fees=_num(parts.fees) or 0.0,
        other=_num(parts.other) or 0.0,
        end_value=_num(parts.end_value),
        contributors=[
            AttributionMover(ticker=t, amount=a)
            for t, a in reversed(ranked[-3:])
            if a > 0
        ],
        detractors=[AttributionMover(ticker=t, amount=a) for t, a in ranked[:3] if a < 0],
        missing=missing,
    )


# ------------------------------------------------------------- the daily path
# `/performance` is the last point of this series and three numbers taken over
# it. A chart needs the series itself, and the two lines it draws are not the
# same shape: money-in-versus-worth is a pair of levels in the reporting
# currency, while the cumulative return is an index that rebases at whatever
# window is on screen. Both come out of one `loaders.history` call — the same
# recipe (`analysis.portfolio.book_history`) the Portfolio page charts, so the
# page and a client cannot disagree about what the book did.


class HistoryPoint(BaseModel):
    """One day of the book. Every figure may be null, and null is not zero."""

    date: str
    injected: float | None = Field(
        description=(
            "Capital put in by this date, cumulative and net of what was taken "
            "out — the flat reference line the value is read against."
        )
    )
    value: float | None = Field(
        description=(
            "Mark-to-market worth of everything held that day. A held name "
            "with no usable close is carried at its cost rather than dropped, "
            "so this stays comparable to `injected`; `missing` names them."
        )
    )
    pnl_pct: float | None = Field(
        description="value/injected - 1. Null before anything was put in."
    )
    twr: float | None = Field(
        description=(
            "Cumulative time-weighted return since the start of THIS window, "
            "flow-adjusted, so deposits do not read as performance. Rebased by "
            "the window, so two windows give the same day two different values "
            "— that is the point of the line. Null on a day the return could "
            "not be taken (see `dropped_days`, and the book's first day, which "
            "has no prior close to measure against)."
        )
    )


class History(BaseModel):
    base: str
    window: str
    start: str | None = None
    end: str | None = None
    points: list[HistoryPoint] = []
    missing: list[str] = Field(
        default=[],
        description=(
            "Held names with no usable price series, carried at cost inside "
            "`value`. Disclose them: a total that quietly drops part of the "
            "book is a lie in smaller print."
        ),
    )
    dropped_days: list[str] = Field(
        default=[],
        description=(
            "Days whose return priced below -100% and were excluded from the "
            "TWR — an unrecorded split or corporate action, never a real loss. "
            "One such sample drags the whole cumulative line negative."
        ),
    )


@router.get("/history", response_model=History, summary="The book, day by day")
def history(
    account: Account,
    base: Base = None,
    window: Annotated[
        str,
        Query(description=f"One of {', '.join(_HISTORY_WINDOWS)}."),
    ] = "all",
    since: Annotated[
        date | None,
        Query(alias="from", description="Explicit range start, ISO. Excludes `window`."),
    ] = None,
    until: Annotated[
        date | None,
        Query(alias="to", description="Explicit range end, ISO. Excludes `window`."),
    ] = None,
) -> History:
    """Injected capital, market value and the TWR index, one point per day.

    The window is clipped here rather than by the client, because the TWR index
    has to be rebased to whatever is on screen — a client that fetched `all` and
    sliced it locally would draw a one-month chart starting at last year's
    cumulative return. The level lines (`injected`, `value`) are absolute and
    survive slicing; the index is not, which is why they travel together.

    `from`/`to` and `window` are mutually exclusive: a request that named both
    is refused rather than served the one this route happened to prefer.
    """
    explicit = since is not None or until is not None
    if explicit and window != "all":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="pass either window or from/to, not both",
        )
    if not explicit and window not in _HISTORY_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"window must be one of {', '.join(_HISTORY_WINDOWS)}",
        )
    if since is not None and until is not None and since > until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="from must not be later than to",
        )

    ccy = reporting_currency(account, base)
    db = str(account.db)
    hist, twr, missing = loaders.history(db, loaders.db_mtime(db), ccy)
    label = "custom" if explicit else window
    if hist.empty:
        return History(base=ccy, window=label, missing=missing)

    if explicit:
        if since is not None:
            hist = hist[hist.index >= pd.Timestamp(since)]
        if until is not None:
            hist = hist[hist.index <= pd.Timestamp(until)]
    elif window in _HISTORY_SPANS:
        # Counted back from the series' own last day rather than from today, so
        # a book whose newest close is stale still gets a full month of days
        # instead of a window that silently shortens whenever Yahoo goes quiet.
        hist = hist[
            hist.index >= hist.index.max() - pd.Timedelta(days=_HISTORY_SPANS[window])
        ]
    elif window == "ytd":
        hist = hist[hist.index >= pd.Timestamp(date.today().year, 1, 1)]
    if hist.empty:
        return History(base=ccy, window=label, missing=missing)

    # Rebased on the window, exactly as the page's cumulative-return chart does
    # it, then put back on the daily index: a day the TWR dropped reads null
    # here rather than repeating the day before it, which would draw a flat
    # stretch nobody measured.
    index = pd.Series(dtype=float)
    if not twr.empty:
        clipped = twr[twr.index >= hist.index[0]]
        if not clipped.empty:
            index = cumulative_returns(clipped).reindex(hist.index)

    return History(
        base=ccy,
        window=label,
        start=str(pd.Timestamp(hist.index[0]).date()),
        end=str(pd.Timestamp(hist.index[-1]).date()),
        points=[
            HistoryPoint(
                date=f"{day:%Y-%m-%d}",
                injected=_num(row["injected"]),
                value=_num(row["value"]),
                pnl_pct=_num(row["pnl_pct"]),
                twr=_num(index.get(day)) if not index.empty else None,
            )
            for day, row in hist.iterrows()
        ],
        missing=missing,
        dropped_days=[
            str(pd.Timestamp(day).date())
            for day in twr.attrs.get("dropped_days", ())
            if hist.index[0] <= pd.Timestamp(day) <= hist.index[-1]
        ],
    )


# ------------------------------------------------------------ month by month
# The Overview tab's card: the book's month-ends since the first trade, cropped
# to a window, and that window's bridge from the value it opened with to today's
# in euros. The rates are never rebased to the window — it is a zoom into the
# full chart, not a book opened on its first day (see `analysis.monthly`). The
# windows are Rendimiento real's plus the calendar year.

_MONTHLY_WINDOWS = ("inception", "ytd", "1y", "2y", "5y")


def _monthly_start(window: str) -> pd.Timestamp | None:
    """The day a window opens on: the last close of last year for `ytd`, the
    `/performance` offset for the rest, None for the book's whole life."""
    today = date.today()
    if window == "ytd":
        return pd.Timestamp(date(today.year - 1, 12, 31))  # ty: ignore[invalid-return-type]
    if window in _PERFORMANCE_DAYS:
        days = pd.Timedelta(days=_PERFORMANCE_DAYS[window])
        return pd.Timestamp(today) - days  # ty: ignore[invalid-return-type]
    return None


class MonthlyPoint(BaseModel):
    """The book on the last recorded day of one month inside the window,
    every figure since the first trade."""

    month: str = Field(description="ISO month, `YYYY-MM`.")
    date: str = Field(description="The day the figures were taken on.")
    value: float | None
    invested: float | None = Field(
        description="The injected total at this close: every buy so far less every sale."
    )
    gain: float | None = Field(description="value - invested.")
    money_weighted: float | None = Field(
        description=(
            "IRR from the first trade to this close, every buy and sale on its "
            "own date — once the book is a year old, annualised: the "
            "`/performance` `irr` as it stood then. In the book's first year, "
            "over the span as a whole and not annualised (see `annual`): "
            "annualising a few months exaggerates any result."
        )
    )
    time_weighted: float | None = Field(
        description=(
            "TWR from the first trade to this close: annualised once the book "
            "is a year old, compounded and not annualised before, like "
            "`money_weighted`."
        )
    )
    annual: bool = Field(
        default=True,
        description=(
            "Whether `money_weighted` and `time_weighted` are rates per year "
            "(false in the book's first year, when they are what the book made "
            "since the first trade). At a year the two readings meet."
        ),
    )
    month_return: float | None = Field(
        default=None,
        description=(
            "This month's own return, not since the first trade: the daily TWR "
            "compounded from the previous month's close (the first trade, for "
            "the first month) to this one, not annualised. There from the first "
            "month; a deposit mid-month does not move it."
        ),
    )


class Monthly(BaseModel):
    base: str
    window: str = "inception"
    start: str | None = Field(
        default=None, description="The close the window opens on."
    )
    end: str | None = None
    opening: float | None = Field(
        default=None, description="The value the window opened with; 0 since inception."
    )
    bought: float | None = Field(default=None, description="Buys inside the window.")
    sold: float | None = Field(
        default=None, description="Sale proceeds inside the window."
    )
    contributed: float | None = Field(default=None, description="bought - sold.")
    gain: float | None = Field(
        default=None, description="closing - opening - contributed."
    )
    closing: float | None = None
    timing: float | None = Field(
        default=None,
        description=(
            "Euros the timing of the trades added (+) or cost (−): `closing` "
            "less what the opening value and the same trades would be worth "
            "had all of it grown at the window's steady TWR pace."
        ),
    )
    months: list[MonthlyPoint] = []
    missing: list[str] = Field(
        default=[],
        description="Held names with no price series, carried at cost in `value`.",
    )


@router.get(
    "/monthly",
    response_model=Monthly,
    summary="The book over a window, month by month",
)
def monthly(account: Account, base: Base = None, window: str = "inception") -> Monthly:
    """The window's bridge in euros, and the book's month-ends inside it.

    Off the same `loaders.history` frame and ledger flows as `/history` and
    `/performance`, so the last point here is the book — and the IRR — those
    two describe today since inception.
    """
    if window not in _MONTHLY_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"window must be one of {', '.join(_MONTHLY_WINDOWS)}",
        )
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    hist, twr, missing = loaders.history(db, mtime, ccy)
    if hist.empty:
        return Monthly(base=ccy, window=window, missing=missing)
    flows = flow_series(loaders.ledger_state(db, mtime, ccy)[0], base=ccy)
    book = book_window(hist, twr, flows, _monthly_start(window))
    if book is None:
        return Monthly(base=ccy, window=window, missing=missing)
    return Monthly(
        base=ccy,
        window=window,
        start=f"{book.start:%Y-%m-%d}",
        end=f"{book.end:%Y-%m-%d}",
        opening=_num(book.opening),
        bought=_num(book.bought),
        sold=_num(book.sold),
        contributed=_num(book.contributed),
        gain=_num(book.gain),
        closing=_num(book.closing),
        timing=_num(book.timing),
        months=[
            MonthlyPoint(
                month=f"{day:%Y-%m}",
                date=f"{day:%Y-%m-%d}",
                value=_num(row["value"]),
                invested=_num(row["invested"]),
                gain=_num(row["gain"]),
                money_weighted=_num(row["money_weighted"]),
                time_weighted=_num(row["time_weighted"]),
                annual=bool(row["annual"]),
                month_return=_num(row["month_return"]),
            )
            for day, row in book.months.iterrows()
        ],
        missing=missing,
    )
