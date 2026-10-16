"""The Today page: the day's market read every account shares, plus the
reader's own card (alerts, their book, news, insiders, comparisons).

Two layers with two lifetimes. The market read is written once a morning by
cron for everyone (`chat/today_market.py`); the personal card is the daily
card Home's teaser shows, written on open by `api/briefing.py`. `GET /today`
composes both and never fetches or spends; `POST /today` asks for the
personal card, sharing its job with `POST /daily` so the teaser and the page
can never start two generations for one reader.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from stocks import obs
from stocks.api import briefing, daily_card
from stocks.api.deps import Account, Writer
from stocks.api.schemas import BookCompare, DailyChartLine, MarketCard, TodayCard
from stocks.api.security import Who
from stocks.chat import daily, daily_book
from stocks.web.i18n import supported

router = APIRouter(tags=["glance"])

Lang = Annotated[
    str,
    Query(min_length=2, max_length=8, description="Language the page is read in."),
]


def _served(raw: dict | None, lang: str, stale: bool) -> None:
    """Log which read the page served, once per session, language and state
    per process: how often a reader meets a missing or stale market is the
    KPI of the cron, and a poll every second and a half must not flood it."""
    session = (raw or {}).get("session") or ""
    if not obs.first_sighting("today.market_served", (session, lang, stale, raw is None)):
        return
    built = (raw or {}).get("built_at")
    try:
        age_h = round((time.time() - float(built)) / 3600, 1) if built else None
    except (TypeError, ValueError):
        age_h = None
    obs.event("today.market_served", lang=lang, session=session, stale=stale,
              missing=raw is None, age_h=age_h)


def _market(lang: str) -> tuple[MarketCard | None, bool]:
    lang = supported(lang) or "en"
    raw, stale = briefing.market_day(lang)
    _served(raw, lang, stale)
    if raw is None:
        return None, stale
    try:
        card = MarketCard.model_validate(raw)
    except ValidationError as exc:
        # A file another build wrote in a shape this one does not read: the
        # page goes without the market part rather than failing whole.
        obs.warn("today.market_unreadable", error=str(exc)[:200])
        return None, stale
    return card, stale


@router.get("/today", response_model=TodayCard, summary="Today's page")
def today(account: Account, who: Who, lang: Lang = "en") -> TodayCard:
    """The market read and the stored personal card, as they stand.

    Never writes, never spends — this is what the page polls while
    `POST /today` has the personal card out. A guest gets the market read
    alone: the demo book has no card of its own.
    """
    _, day = briefing.now_day()
    market, stale = _market(lang)
    personal = None if who.kind == "guest" else daily_card.status(account, lang)
    return TodayCard(
        action_day=day.isoformat(),
        cutoff_hour=daily.CUTOFF_HOUR,
        market=market,
        market_stale=stale,
        personal=personal,
    )


@router.post("/today", response_model=TodayCard, summary="Have today's written")
def write_today(
    account: Writer,
    lang: Lang = "en",
    force: Annotated[
        bool,
        Query(description="Regenerate the personal card even when today's stands."),
    ] = False,
) -> TodayCard:
    """The page with the personal card asked for.

    Idempotent: a generation already out for this account — in any language,
    started here or by Home — is reported rather than replaced, unless
    `force`. Waits `briefing.GRACE_S` like `POST /daily`; past that the
    personal card is `pending` and `GET /today` is the poll.
    """
    _, day = briefing.now_day()
    market, stale = _market(lang)
    personal = daily_card.request(account, lang, force=force, patient=True)
    return TodayCard(
        action_day=day.isoformat(),
        cutoff_hour=daily.CUTOFF_HOUR,
        market=market,
        market_stale=stale,
        personal=personal,
    )


@router.get(
    "/today/book", response_model=BookCompare, summary="The book against an index"
)
def book_compare(
    account: Account,
    lang: Lang = "en",
    range: Annotated[  # noqa: A002 — the query's own name
        Literal["1m", "3m", "6m", "ytd", "1y", "2y", "5y", "max"],
        Query(description="The window drawn."),
    ] = "1m",
    index: Annotated[
        str,
        Query(max_length=16, description="One of the indexes the page offers."),
    ] = daily_book.INDEX_SYMBOL,
) -> BookCompare:
    """The Portfolio section's chart redrawn: today's basket and `index`, both
    as growth over `range`, the index in the reader's currency. The card
    carries the month against the S&P 500; this is every other pairing.

    Computed off the book's own download and one shared index request, never
    written. Not open to a guest (`guest.OPEN`): the demo book has no card.
    """
    if index not in daily_book.INDEXES:
        raise HTTPException(status_code=422, detail="unknown index")
    lines: list[dict] = []
    try:
        lines = briefing.book_compare(account, supported(lang) or "en", range, index)
    except Exception as exc:  # noqa: BLE001 — the card's own chart stays up
        obs.warn("today.book_compare_failed", index=index, range=range,
                 error_type=type(exc).__name__)
    chart = [DailyChartLine.model_validate(line) for line in lines]
    return BookCompare(range=range, index=index, chart=chart,
                       since=_late_start(chart, daily_book.window_days(range)))


# A window opening this many days after the asked one still reads as whole:
# weekends, holidays and the anchor's last close before it.
_LATE_DAYS = 7


def _late_start(chart: list[DailyChartLine], days: int) -> str | None:
    """The chart's first day when it opens well after the window does — the
    book is younger than the window, so the reader is told where it begins."""
    if not chart or not chart[0].dates:
        return None
    first = date.fromisoformat(chart[0].dates[0][:10])
    asked = date.today() - timedelta(days=days)
    return first.isoformat() if (first - asked).days > _LATE_DAYS else None
