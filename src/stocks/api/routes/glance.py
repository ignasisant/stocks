"""The dashboard's opening: the briefing, the movers, the 52-week edges.

Three small reads rather than one "home" blob, because they are three different
facts with three different lifetimes — a briefing is written once a day, movers
change every few minutes, and an extreme changes on a close. A client that wants
all three asks for all three; one that only shows movers does not pay for a
model's prose. The one write here, `POST /daily`, is what asks for that prose;
the machinery behind it is `api/briefing.py`.

The rest of that page is already here: the KPI row is `/portfolio/summary` and
`/portfolio/performance`, the transactions strip is `/portfolio/transactions`,
the calendar is `/earnings`, the groups are `/watchlist` with their closes at
`/home/closes`.
"""

from __future__ import annotations

from typing import Annotated

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from stocks.analysis.portfolio import (
    basket_change,
    day_change,
    market_active,
    market_live,
    ticker_changes,
    ticker_day_changes,
    us_market_open,
)
from stocks.api import briefing, home, loaders
from stocks.api.deps import Account, Base, Writer, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import DailyCard, Extreme, Extremes, Mover, Movers
from stocks.chat import daily

router = APIRouter(tags=["glance"])

# The windows the dashboard offers, in calendar days. Named so "week" means the
# same five days here as it does on the page.
WINDOWS = {"day": 1, "week": 7, "month": 30}

# How many names each side of a movers card shows. More than this and it stops
# being a glance.
SHOWN = 6

# How close to an extreme still counts as being at it — `api/home.py` owns the
# number, because the daily card's 52-week line reads the same scan.
EDGE_BAND = home.EDGE_BAND

Lang = Annotated[
    str,
    Query(
        min_length=2,
        max_length=8,
        description="Language the card is judged, and written, in.",
    ),
]


@router.get("/daily", response_model=DailyCard, summary="Today's briefing")
def card(account: Account, lang: Lang = "en") -> DailyCard:
    """The card on screen right now, and whether a better one is coming.

    Freshness is not just the date. The card is prose, so a reader who switched
    the app to Spanish should not be left with yesterday's English briefing; and
    a card written before the open quotes the previous close, so once the next
    session lands its every figure is a day behind while the calendar date has
    not moved yet. Both are checked here.

    Never writes, never spends: this is what a client polls while `POST /daily`
    has a generation out, and it reports that generation — `pending` while it
    runs, and the computed card when the model gave nothing back.
    """
    return _status(account, lang)


@router.post("/daily", response_model=DailyCard, summary="Have today's written")
def write_card(
    account: Writer,
    lang: Lang = "en",
    force: Annotated[
        bool,
        Query(
            description=(
                "Regenerate: write a new card even when today's stands, and "
                "abandon one already being written."
            )
        ),
    ] = False,
) -> DailyCard:
    """Today's card, written if it has to be — `daily_ui._resolve`, over HTTP.

    In order: a generation already out is reported, not doubled; a stored card
    that still stands comes back and spends nothing; a key already tried today
    comes back as the computed card rather than trying the same dead provider
    again. Only then are the facts built and one generation started, and the
    request waits `briefing.GRACE_S` for it — past that the answer is `pending`
    with the computed card in hand, and `GET /daily` is the poll.

    `force` is the Regenerate button: it outranks all of the above. A session
    only — the generation spends this account's free allowance and writes
    daily_action.json, neither of which a bearer token may do.
    """
    from stocks.web import auth

    _, day = briefing.now_day()
    key = briefing.key_for(day, lang, _last_session(account))
    job = briefing.job_for(account, key)
    stored = _stored(account)
    if not force:
        if job is not None:
            # In flight: report it. Done: this key was tried today — the card
            # it left (stored, or the computed stand-in) is the answer.
            return _status(account, lang)
        if daily.is_fresh(stored, day, lang, key[2] or None):
            return _status(account, lang)

    prefs = auth.load_prefs(account.prefs)
    facts = briefing.build_facts(account, prefs, day, stored)
    if facts is None:
        # Neither a position nor a watchlist entry: nothing to brief on, and
        # the Streamlit page clears the slot for exactly this account.
        return _empty(day)
    briefing.start(account, prefs, facts, lang, day, stored, key=key, forced=force)
    return _status(account, lang)


def _stored(account) -> daily.DailyAction | None:
    return daily.DailyAction.from_dict(
        loaders.stored_action(str(account.action), loaders.file_mtime(account.action))
    )


def _empty(day) -> DailyCard:
    return DailyCard(
        action_day=day.isoformat(), cutoff_hour=daily.CUTOFF_HOUR, fresh=False
    )


def _answer(action: daily.DailyAction, day, *, fresh: bool, pending=False) -> DailyCard:
    return DailyCard(
        day=action.day,
        headline=action.headline,
        bullets=list(action.bullets),
        focus=list(action.focus),
        as_of=action.as_of or None,
        lang=action.lang,
        source=action.source,
        action_day=day.isoformat(),
        cutoff_hour=daily.CUTOFF_HOUR,
        fresh=fresh,
        generated=action.generated or None,
        pending=pending,
    )


def _status(account, lang: str) -> DailyCard:
    """What the card slot shows now, from the stored card and the job.

    A generation out wins: a forced one has taken the old card away (the
    reader just dismissed it) and answers with no headline; an automatic one
    answers with the computed stand-in. Then a stored card that stands. Then a
    finished job for this key that stored nothing — the model gave no answer —
    whose computed card is today's, and so fresh. Last, whatever is stored,
    marked as the older card it is.
    """
    _, day = briefing.now_day()
    session = _last_session(account)
    job = briefing.job_for(account, briefing.key_for(day, lang, session))
    stored = _stored(account)
    if job is not None and not job.done:
        if job.computed is None:
            answer = _empty(day)
            answer.pending = True
            return answer
        return _answer(job.computed, day, fresh=True, pending=True)
    if stored is not None and daily.is_fresh(stored, day, lang, session):
        return _answer(stored, day, fresh=True)
    if job is not None:
        # Done, and nothing fresh on disk: the model gave nothing back (or the
        # save failed) — its own card if it has one, else the stand-in.
        fallback = job.action or job.computed
        if fallback is not None:
            return _answer(fallback, day, fresh=True)
    if stored is None:
        return _empty(day)
    return _answer(stored, day, fresh=False)


def _last_session(account) -> str | None:
    """The newest close date across this account's holdings, ISO, or None.

    A card is stale the moment a session it does not quote has closed, and the
    calendar cannot see that. Read off the book's own shared price download, so
    it costs nothing a portfolio read has not already paid for.
    """
    db = str(account.db)
    closes = loaders.held_closes(db, loaders.db_mtime(db))
    latest = [s.index[-1] for s in closes.values() if not s.empty]
    return str(pd.Timestamp(max(latest)).date()) if latest else None


@router.get("/movers", response_model=Movers, summary="What moved")
def movers(
    account: Account,
    window: Annotated[str, Query(description="day | week | month.")] = "day",
    base: Base = None,
) -> Movers:
    """The book's best and worst names over one window, and the book itself.

    The book's move comes back as both money and a percentage, because a tile
    that shows only the percentage twice is showing one thing twice: `amount`
    is what moved, `basket` is what that was worth relatively. The currency
    matters to both — the basket is valued in the reporting currency, so a
    position's move includes its FX move, which is how the book is judged.

    Measured on a basket held at today's quantities (`loaders.basket_values`),
    never on the book's own value history: that one carries deposits and
    imports, and a €12k book that took €38k on a Monday would read "+316% this
    week" with the market flat.

    The day window is the one that cannot be read off closes alone. Outside a
    regular session the newest daily bar is stale or flat, and the basket then
    reports a book that never moved — so the names whose own exchange is shut
    are re-read from `session_quotes`: the live pre/after-hours move while
    there is one, the last completed session afterwards. `as_of` says which
    session that was, and `unpriced` how much of the book is missing from all
    of it.
    """
    if window not in WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"window must be one of {', '.join(WINDOWS)}",
        )
    days = WINDOWS[window]
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    ccy = reporting_currency(account, base)
    held = loaders.ledger_state(db, mtime, ccy)[1]
    frame = loaders.basket_values(db, mtime, ccy).dropna(how="all")
    answer = Movers(
        window=window,
        base=ccy,
        positions=len(held),
        unpriced=len([p for p in held if p.ticker not in frame.columns]),
    )
    if frame.empty:
        return answer

    quotes: dict[str, dict] | None = None
    if days <= 1 and not us_market_open():
        # Only the names actually outside their own session: a Paris listing
        # is live at 10:00 CET with New York hours away, and crypto never
        # shuts. Costs one quote burst, cached, and only while the US is shut.
        off = tuple(t for t in frame.columns if not market_live(str(t)))
        quotes = loaders.quotes(off) if off else {}

    if days <= 1:
        changes = ticker_day_changes(frame, quotes)
        whole = day_change(frame, quotes)
    else:
        changes = ticker_changes(frame, days)
        whole = basket_change(frame, days)
    changes = changes.dropna().sort_values(ascending=False)

    def mover(ticker, pct) -> Mover:
        # Only today's figure can be a stale close — `home.py` dims the day
        # column alone, for names whose market is not active right now.
        live = market_active(str(ticker)) if days <= 1 else None
        return Mover(ticker=str(ticker), pct=float(pct), active=live)

    answer.gainers = [mover(t, v) for t, v in changes[changes > 0].head(SHOWN).items()]
    answer.losers = [
        mover(t, v) for t, v in changes[changes < 0].tail(SHOWN).sort_values().items()
    ]
    if whole:
        answer.amount, answer.basket = _num(whole[0]), _num(whole[1])
    answer.as_of = _as_of(frame, quotes)
    return answer


def _as_of(frame: pd.DataFrame, quotes: dict[str, dict] | None) -> str | None:
    """Which session the figures are from: the quotes' own, else the last bar.

    The quotes agree with each other in practice (they are one burst against
    one clock) but not necessarily with the bars, and the newest of the two is
    the one a reader is looking at.
    """
    stamps = {q["as_of"] for q in (quotes or {}).values() if q.get("as_of")}
    if stamps:
        return max(stamps)
    return str(pd.Timestamp(frame.index[-1]).date()) if len(frame.index) else None


@router.get("/extremes", response_model=Extremes, summary="At a 52-week edge")
def extremes(account: Account) -> Extremes:
    """Held and favourite names sitting within 2% of a 52-week high or low.

    `home.py`'s scope, not the whole watchlist: the book's own positions —
    whether or not they are on the list — plus the starred names, crypto left
    out (`home.extremes_scope`). A guest holds nothing, so theirs is the shared
    list's favourites. The year of closes is the page's one bulk download
    (`home.closes_tuple`), the same entry the watchlist rows read.

    `distance` is null at or beyond the edge, which is a different fact from
    being 0% away from it; `scanned: 0` means there was nothing to look at.
    """
    entries = home.holdings(account)
    owned = home.held(account)
    scope = home.extremes_scope(entries, owned)
    if not scope:
        return Extremes(scanned=0)
    year = home.year_closes(home.closes_tuple(entries, owned))
    return Extremes(
        scanned=len(scope),
        extremes=[
            Extreme(ticker=ticker, price=price, edge=edge, distance=distance)
            for ticker, price, edge, distance in home.scan_extremes(scope, year)
        ],
    )
