"""What the daily card slot shows, shared by `GET/POST /daily` and `/today`.

The card's machinery lives in `api/briefing.py` (facts, the job, its side
effects); this is the read side every route answers from — the stored card,
the job in flight, and whether either still stands — plus the one write both
routes make, asking for today's card. One module, so Home's teaser and the
Today page can never disagree about which card is current or start two
generations for one reader.
"""

from __future__ import annotations

import pandas as pd
from pydantic import ValidationError

from stocks.api import briefing, loaders
from stocks.api.schemas import (
    DailyBook,
    DailyCard,
    DailyItem,
    DailySection,
    TodaySection,
)
from stocks.chat import daily, daily_routines


def stored(account) -> daily.DailyAction | None:
    return daily.DailyAction.from_dict(
        loaders.stored_action(str(account.action), loaders.file_mtime(account.action))
    )


def empty(day) -> DailyCard:
    return DailyCard(
        action_day=day.isoformat(), cutoff_hour=daily.CUTOFF_HOUR, fresh=False
    )


def answer(action: daily.DailyAction, day, *, fresh: bool, pending=False) -> DailyCard:
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
        items=[
            DailyItem(**item, section=daily.section_of(item)) for item in action.items
        ],
        upgradable=fresh and not pending and daily.wants_upgrade(action),
        analysed=[k for k, v in action.analysis.items() if v],
        thread=action.thread or None,
        book=_book(action.book),
        sections=[sec for sec in map(_section, action.sections) if sec],
        brief=action.brief if action.brief in daily.BRIEF_STATES else "",
        today=[sec for sec in map(_today, action.today) if sec],
        shape=action.shape,
    )


# The sections read off the stored card, so whatever JSON is on disk: one that
# does not fit drops its section (or its chart), never the whole card.


def _book(raw: dict) -> DailyBook | None:
    try:
        return DailyBook(**raw) if raw else None
    except ValidationError:
        return None


def _section(raw: dict) -> DailySection | None:
    lines = [DailyItem(**ln, section=daily.WATCH) for ln in raw.get("lines") or []]
    try:
        return DailySection.model_validate({**raw, "lines": lines})
    except ValidationError:
        try:
            return DailySection.model_validate({**raw, "lines": lines, "chart": None})
        except ValidationError:
            return None


def _today(raw: dict) -> TodaySection | None:
    try:
        return TodaySection.model_validate(raw)
    except ValidationError:
        return None


def status(account, lang: str) -> DailyCard:
    """What the card slot shows now, from the stored card and the job.

    A generation out wins: a forced one has taken the old card away (the
    reader just dismissed it) and answers with no headline; an automatic one
    answers with the computed stand-in. Then a stored card that stands. Then a
    finished job for this key that stored nothing — the model gave no answer —
    whose computed card is today's, and so fresh. Last, whatever is stored,
    marked as the older card it is.
    """
    _, day = briefing.now_day()
    key = key_now(account, day, lang)
    job = briefing.job_for(account, key)
    card = stored(account)
    if job is not None and not job.done:
        if job.computed is None:
            out = empty(day)
            out.pending = True
            return out
        return answer(job.computed, day, fresh=True, pending=True)
    if card is not None and stands(card, day, lang, key):
        return answer(card, day, fresh=True)
    if job is not None:
        # Done, and nothing fresh on disk: the model gave nothing back (or the
        # save failed) — its own card if it has one, else the stand-in.
        fallback = job.action or job.computed
        if fallback is not None:
            return answer(fallback, day, fresh=True)
    if card is None:
        return empty(day)
    return answer(card, day, fresh=False)


def request(account, lang: str, *, force: bool, patient: bool = False) -> DailyCard:
    """Today's card, written if it has to be — `POST /daily`'s body.

    In order: a generation already out is reported, not doubled; a stored card
    that still stands comes back and spends nothing; a key already tried today
    comes back as the computed card rather than trying the same dead provider
    again. Only then are the facts built and one generation started.

    `patient` is `POST /today`'s stricter guard: any generation still out for
    this account is reported, whatever language or session it was started
    for, so the page and its Home teaser cannot abandon each other's job.
    `force` outranks both.
    """
    from stocks.web import auth

    _, day = briefing.now_day()
    key = key_now(account, day, lang)
    job = briefing.job_for(account, key)
    card = stored(account)
    if not force:
        if job is not None or (patient and briefing.running(account) is not None):
            # In flight: report it. Done: this key was tried today — the card
            # it left (stored, or the computed stand-in) is the answer.
            return status(account, lang)
        if stands(card, day, lang, key) and not daily.wants_upgrade(card):
            # A computed stand-in that stands still gets a few more tries at
            # a written briefing a day (`daily.wants_upgrade`); anything else
            # that stands costs nothing.
            return status(account, lang)

    prefs = auth.load_prefs(account.prefs)
    facts = briefing.build_facts(account, prefs, day, card)
    if facts is None:
        # Neither a position nor a watchlist entry: nothing to brief on.
        return empty(day)
    briefing.start(account, prefs, facts, lang, day, card, key=key, forced=force)
    return status(account, lang)


def key_now(account, day, lang: str) -> tuple:
    """`briefing.key_for` this account now: its last session and the wording
    of its brief."""
    from stocks.web import auth

    try:
        prefs = auth.load_prefs(account.prefs)
        sig = daily_routines.signature(daily_routines.load(prefs, account.chat))
    except Exception:  # noqa: BLE001 — read as no brief
        sig = ""
    return briefing.key_for(day, lang, last_session(account), sig)


def stands(card, day, lang: str, key: tuple) -> bool:
    """`daily.is_fresh`, and written for the brief the reader has now: one
    saved, reworded or dropped since — here, in the chat or by switching
    memory off — rewrites the card. So is a card with no book shape: it was
    written before the Today page's sections existed, and would leave that
    page without them until tomorrow."""
    return daily.is_fresh(card, day, lang, key[2] or None) and (
        card.brief_sig == key[3]) and bool(card.shape)


def last_session(account) -> str | None:
    """The newest close date across this account's holdings, ISO, or None.

    A card is stale the moment a session it does not quote has closed, and the
    calendar cannot see that. Read off the book's own shared price download, so
    it costs nothing a portfolio read has not already paid for.
    """
    db = str(account.db)
    closes = loaders.held_closes(db, loaders.db_mtime(db))
    latest = [s.index[-1] for s in closes.values() if not s.empty]
    return str(pd.Timestamp(max(latest)).date()) if latest else None
