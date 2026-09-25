"""When the watchlist reports, and what happened last time.

One endpoint rather than two: the fetch that finds the next date already
carries the past quarters' columns, so splitting them would double the requests
to Yahoo to say the same thing twice.

The filter sets ship with it. A client could rebuild "portfolio" from
`/portfolio/positions` and "favorites" from `/watchlist`, but the tag groups
would still have to be re-derived and the empty ones dropped — three round
trips and a rule, for something one pass over the same watchlist already knows.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query

from stocks import obs
from stocks.api import loaders
from stocks.api.cache import ttl_cache
from stocks.api.deps import Account
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import (
    CalendarEvent,
    CalendarResult,
    ConsensusPeriod,
    EarningsCalendar,
    EarningsResultDetail,
    QuarterBreakdown,
    QuarterFigures,
    TaxDeadline,
)
from stocks.config import currency_symbol, load_watchlist
from stocks.data.crypto import is_crypto
from stocks.data.earnings import (
    EarningsResult,
    Quarter,
    fetch_quarters,
    fetch_statement_currency,
    match_quarter,
    pct_change,
    price_reaction,
    prior_quarter,
    year_ago,
)
from stocks.data.estimates import (
    CURRENT_FY,
    CURRENT_Q,
    NEXT_FY,
    NEXT_Q,
    QuarterOutlook,
    quarter_outlook,
)
from stocks.data.funds import is_fund
from stocks.portfolio.tax import deadlines
from stocks.portfolio.tax import prefs as tax_prefs

router = APIRouter(tags=["earnings"])

Symbol = Annotated[
    str, Path(min_length=1, max_length=32, description="Ticker, e.g. AAPL.")
]


def _result(result: EarningsResult) -> CalendarResult:
    return CalendarResult(
        ticker=result.ticker,
        date=result.date.isoformat(),
        eps_estimate=_num(result.eps_estimate),
        reported_eps=_num(result.reported_eps),
        surprise_pct=_num(result.surprise_pct),
        beat=result.beat,
    )


@router.get("/earnings", response_model=EarningsCalendar, summary="Reporting calendar")
def earnings(account: Account) -> EarningsCalendar:
    """The account's watchlist calendar: what is coming and what already printed.

    Coins and funds are dropped before the fetch — neither ever reports, and
    asking spends a request on Yahoo answering "no earnings dates found". They
    come back in `skipped` instead of vanishing, so a client showing a watchlist
    beside this does not have to explain the gap itself. Fund classification
    stays cache-only: a cold cache leaves a fund in the list rather than
    blocking the calendar on a lookup.
    """
    holdings = load_watchlist(account.watchlist)
    reporting = [
        h
        for h in holdings
        if not is_crypto(h.ticker) and not is_fund(h.ticker, fetch=False)
    ]
    covered = {h.ticker for h in reporting}
    skipped = [h.ticker for h in holdings if h.ticker not in covered]

    events, results = loaders.earnings_calendar(
        tuple(sorted(h.ticker for h in reporting))
    )

    # Portfolio = open ledger positions, plus any watchlist entry carrying
    # shares. The two disagree whenever a name was added by hand.
    db = str(account.db)
    held = set(loaders.held(db, loaders.db_mtime(db)))
    groups: dict[str, list[str]] = {}
    if portfolio := held | {h.ticker for h in reporting if h.is_position}:
        groups["portfolio"] = sorted(portfolio)
    if favorites := {h.ticker for h in reporting if h.favorite}:
        groups["favorites"] = sorted(favorites)
    tags: dict[str, set[str]] = {}
    for holding in reporting:
        for tag in holding.tags:
            tags.setdefault(tag, set()).add(holding.ticker)
    groups.update({tag: sorted(names) for tag, names in sorted(tags.items())})

    # The filing dates of wherever the account is taxed — resolved the way
    # `/portfolio/tax` resolves it, so both screens speak of the same country.
    code, _ = tax_prefs.resolve(tax_prefs.load(account.prefs))
    today = date.today()
    tax_deadlines = [
        TaxDeadline(
            key=d.key,
            date=d.date.isoformat(),
            days_until=d.days_until(today),
            year=d.year_label,
            approximate=d.approximate,
            remind=d.due_soon(today),
        )
        for d in deadlines.calendar(code, today)
    ]

    return EarningsCalendar(
        upcoming=[
            CalendarEvent(
                ticker=event.ticker,
                date=event.date.isoformat() if event.date else None,
                days_until=event.days_until,
            )
            for event in events
        ],
        results=[_result(result) for result in results],
        groups=groups,
        skipped=skipped,
        jurisdiction=code,
        tax_deadlines=tax_deadlines,
    )


# ------------------------------------------------------------ one past print
# What the Streamlit result dialog (`web.earnings_ui.render_result_body`)
# draws under its headline tiles, as data. Same functions, same windows, same
# caches' lifetimes: the dialog there caches `reaction` and `quarter_detail` for
# six hours, and so does this. The caches live here rather than in `loaders`
# because nothing else reads them — the result dialog is their only caller.

# Quarters the trend bars and detail tables show. yfinance publishes five
# quarters of the income statement, so a taller stack would draw empty rows.
TREND_QUARTERS = 5

# The per-period grid under the outlook, in the order the Streamlit expander
# lists it: the quarter in flight, the next, then both fiscal years.
OUTLOOK_PERIODS = (CURRENT_Q, NEXT_Q, CURRENT_FY, NEXT_FY)

_DETAIL_TTL = 6 * 3600.0


@ttl_cache(_DETAIL_TTL, max_entries=128)
def _reaction(ticker: str, iso: str) -> float | None:
    """% move across a print. `price_reaction` never raises — it answers None."""
    return price_reaction(ticker, date.fromisoformat(iso))


@ttl_cache(_DETAIL_TTL, max_entries=64)
def _statements(ticker: str) -> tuple[list[Quarter], str | None]:
    """(quarters newest-first, the currency they are filed in).

    A rate limit RE-RAISES out of `fetch_quarters` and so out of this cache
    without being stored — `ttl_cache` only keeps what returned — which is the
    point: a throttled minute must not answer "no statements" for six hours.
    """
    quarters = fetch_quarters(ticker)
    return quarters, fetch_statement_currency(ticker) if quarters else None


def _figures(quarters: list[Quarter], q: Quarter) -> QuarterFigures:
    back_y, back_q = year_ago(quarters, q), prior_quarter(quarters, q)
    return QuarterFigures(
        end=q.end.isoformat(),
        revenue=_num(q.revenue),
        gross_profit=_num(q.gross_profit),
        operating_income=_num(q.operating_income),
        net_income=_num(q.net_income),
        pretax_income=_num(q.pretax_income),
        tax_provision=_num(q.tax_provision),
        rnd=_num(q.rnd),
        diluted_eps=_num(q.diluted_eps),
        diluted_shares=_num(q.diluted_shares),
        gross_margin=_num(q.gross_margin),
        operating_margin=_num(q.operating_margin),
        net_margin=_num(q.net_margin),
        rnd_intensity=_num(q.rnd_intensity),
        tax_rate=_num(q.tax_rate),
        revenue_yoy=_num(pct_change(q.revenue, back_y.revenue if back_y else None)),
        revenue_qoq=_num(pct_change(q.revenue, back_q.revenue if back_q else None)),
    )


def _bps(current: float | None, previous: float | None) -> float | None:
    """Margin move in basis points (both inputs are fractions)."""
    if current is None or previous is None:
        return None
    return _num((current - previous) * 10_000)


def _breakdown(quarters: list[Quarter], q: Quarter) -> QuarterBreakdown:
    """The reported quarter and its comparisons, exactly as the tiles take them.

    TTM reads the LATEST four quarters, not the four ending at `q` — the
    Streamlit tile does, and for the print a reader opens most (the last one)
    the two are the same four.
    """
    prev_y = year_ago(quarters, q)
    last_four = [x.revenue for x in quarters[:4]]
    ttm = (
        sum(v for v in last_four if v is not None)
        if len(last_four) == 4 and all(v is not None for v in last_four)
        else None
    )
    return QuarterBreakdown(
        quarter=_figures(quarters, q),
        revenue_ttm=_num(ttm),
        net_income_yoy=_num(
            pct_change(q.net_income, prev_y.net_income if prev_y else None)
        ),
        shares_yoy=_num(
            pct_change(q.diluted_shares, prev_y.diluted_shares if prev_y else None)
        ),
        gross_margin_bps=_bps(q.gross_margin, prev_y.gross_margin if prev_y else None),
        operating_margin_bps=_bps(
            q.operating_margin, prev_y.operating_margin if prev_y else None
        ),
        net_margin_bps=_bps(q.net_margin, prev_y.net_margin if prev_y else None),
    )


def _consensus(view: QuarterOutlook) -> ConsensusPeriod:
    return ConsensusPeriod(
        period=view.period,
        eps_avg=_num(view.eps_avg),
        eps_low=_num(view.eps_low),
        eps_high=_num(view.eps_high),
        eps_growth=_num(view.eps_growth),
        eps_analysts=view.eps_analysts,
        rev_avg=_num(view.rev_avg),
        rev_low=_num(view.rev_low),
        rev_high=_num(view.rev_high),
        rev_growth=_num(view.rev_growth),
        rev_analysts=view.rev_analysts,
        currency=view.currency,
        currency_prefix=currency_symbol(view.currency),
    )


@router.get(
    "/earnings/{symbol}/result",
    response_model=EarningsResultDetail,
    summary="One past print, broken down",
)
def result_detail(
    symbol: Symbol,
    account: Account,
    day: Annotated[
        date, Query(alias="date", description="The report date, ISO (YYYY-MM-DD).")
    ],
) -> EarningsResultDetail:
    """Everything the result dialog shows for the print `symbol` made on `date`.

    The headline (the print itself, the per-ticker surprise record, the price
    reaction) always answers: those come from caches that degrade to empty
    rather than raise. The breakdown underneath is three more Yahoo payloads —
    the quarterly income statement, its filing currency, the estimates — and
    when those fail the response says `unavailable` instead of failing whole,
    because the Streamlit dialog does the same: a toast, and the tiles stay.

    Any ticker, not only the watchlist's: the Home screen opens this from its
    own past-earnings chips, and a print is public information.
    """
    ticker = symbol.strip().upper()
    iso = day.isoformat()
    _, reported = loaders.earnings(ticker)
    history = sorted(reported, key=lambda r: r.date, reverse=True)
    printed = next((r for r in history if r.date == day), None)

    detail = EarningsResultDetail(
        ticker=ticker,
        name=loaders.company_name(ticker, str(account.watchlist)) or "",
        logo=loaders.logo(ticker),
        date=iso,
        result=_result(printed) if printed else None,
        history=[_result(r) for r in history],
    )
    # A date the feed has no figures for gets the bare header, like the
    # Streamlit dialog's "no reported figures": nothing below it would be about
    # a print that exists.
    if printed is None:
        return detail

    detail.price_reaction = _num(_reaction(ticker, iso))
    try:
        quarters, currency = _statements(ticker)
        raw = loaders.estimates(ticker)
    except Exception as exc:  # noqa: BLE001 — the headline must survive this
        obs.warn(
            "api.earnings_detail_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        detail.unavailable = True
        return detail

    q = match_quarter(quarters, day) if quarters else None
    detail.quarter_state = "matched" if q else "pending" if quarters else "none"
    detail.currency = currency
    detail.currency_prefix = currency_symbol(currency)
    detail.trend = [_figures(quarters, x) for x in quarters[:TREND_QUARTERS]]
    if q is not None:
        detail.breakdown = _breakdown(quarters, q)
        if printed.reported_eps is not None and q.diluted_eps is not None:
            detail.eps_gaap_gap = _num(printed.reported_eps - q.diluted_eps)

    headline = quarter_outlook(raw, NEXT_Q)
    if not headline.empty:
        detail.outlook = _consensus(headline)
        detail.outlook_periods = [
            _consensus(view)
            for view in (quarter_outlook(raw, p) for p in OUTLOOK_PERIODS)
            if not view.empty
        ]
    return detail
