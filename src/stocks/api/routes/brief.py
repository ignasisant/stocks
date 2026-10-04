"""The reader's brief for the daily card, edited from the card it shapes.

The brief is what the card tells this reader every morning, in their own
words, one line per thing ("what moved in my book", "this week's events",
"my companies' insiders", "review my kill criteria"). The card answers it
line by line, a section each, in place of the default sections
(`chat/daily.py`).

It is kept as a memory of kind "routine" (`chat/learnings.py`), so the chat
files one when asked ("cada mañana dime…") and the memory screen lists it.
An account that saved several before the brief existed reads them here as
one text, a line each, and the first save folds them into one.

Each save is planned there and then (`routine_plan.ensure`): a model turns
the words into the fetches the card will make — which indices, whose
results, which symbols, which of events, insiders and exits — and the answer
says what it understood, before the first card is written. No model, and the
keyword rules stand in for that save (and the card asks again the next day).
The plan is a list of fetches and nothing more: the vocabulary is closed and
checked in `routine_plan`.

Reads are `Account` (a guest reads an empty brief), writes `RoutineSave`: a
session, and a burst budget of their own, since every save may call a model.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from stocks import accounts
from stocks.accounts import UserPaths
from stocks.api.deps import Account, RoutineSave
from stocks.chat import daily_routines, engine, learnings, market, routine_plan

router = APIRouter(prefix="/daily/brief", tags=["home"])


class BriefPlan(BaseModel):
    """What the card fetches to answer the brief.

    `markets` are group codes (`routine_plan.MARKETS`) and `topics` source
    codes (`routine_plan.TOPICS`), both named by the client in the reader's
    language; `symbols` the instruments quoted besides, the brief's own
    tickers first. All empty means the card answers from the reader's own
    book. `by` says whether a model planned it or the keyword rules stood in.
    """

    markets: list[str]
    earnings: Literal["book", "named", "large"] | None
    symbols: list[str]
    topics: list[str]
    by: Literal["model", "rules"]


class Brief(BaseModel):
    text: str = Field(description="The brief, one line per thing; empty with none.")
    plan: BriefPlan | None = None
    # Memory off (`PATCH /chat/settings`): the brief is kept but the card
    # reads none of it, and the editor has to say so.
    enabled: bool
    max_chars: int = learnings.MAX_ROUTINE_CHARS
    max_lines: int = learnings.MAX_ROUTINE_LINES


class BriefText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=learnings.MAX_ROUTINE_CHARS)


def _kept(paths: UserPaths) -> list[learnings.Learning]:
    return [i for i in learnings.load(paths.learnings) if i.kind == "routine"]


def _scope(earnings: str) -> Literal["book", "named", "large"] | None:
    """`Recipe.earnings` is one of `routine_plan.SCOPES` or empty; this says
    which in a type the checker can follow."""
    match earnings:
        case "book" | "named" | "large":
            return earnings
    return None


def _plan(paths: UserPaths, items: list[learnings.Learning]) -> BriefPlan | None:
    if not items:
        return None
    recipe = routine_plan.current(items[0])
    for item in items[1:]:
        recipe = recipe.widened(routine_plan.current(item))
    own = [t for i in items for t in i.tickers]
    known = market.watchlist_names(paths.watchlist)
    return BriefPlan(
        markets=list(recipe.markets),
        earnings=_scope(recipe.earnings),
        symbols=daily_routines.symbols(
            list(dict.fromkeys((*own, *recipe.symbols))), known),
        topics=list(recipe.topics),
        by="model" if all(routine_plan.current(i).by == "model" for i in items)
        else "rules",
    )


def _out(paths: UserPaths, items: list[learnings.Learning]) -> Brief:
    prefs = accounts.load_prefs(paths.prefs)
    return Brief(text="\n".join(i.text for i in items), plan=_plan(paths, items),
                 enabled=engine.memory_on(prefs))


def _tickers(paths: UserPaths, text: str) -> list[str]:
    """The symbols the words name (`daily_routines.symbols`)."""
    known = market.watchlist_names(paths.watchlist)
    return daily_routines.symbols(
        market.mentioned(text, known, lookup=lambda _name: ""), known)


@router.get("", response_model=Brief, summary="The daily card's brief")
def brief(paths: Account) -> Brief:
    """The brief as one text — an account's older routines a line each."""
    return _out(paths, _kept(paths))


@router.put("", response_model=Brief, summary="Write the daily card's brief")
def save(body: BriefText, paths: RoutineSave) -> Brief:
    """Save the brief, planned now. The card is rewritten for it on the next
    load (`glance._key`). 409 when the memory has no room for it."""
    from stocks.api import briefing

    text, tickers = body.text, _tickers(paths, body.text)
    kept = _kept(paths)
    try:
        if kept:
            item = learnings.edit(paths.learnings, kept[0].id, text=text,
                                  tickers=tickers)
            for extra in kept[1:]:
                learnings.drop(paths.learnings, extra.id)
        else:
            item, _new = learnings.add(paths.learnings, text, kind="routine",
                                       tickers=tickers)
            if item.kind != "routine":
                item = learnings.edit(paths.learnings, item.id, kind="routine") or item
    except learnings.Full as exc:
        # An i18n key, rendered by the editor as it is.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="home.brief_memory_full") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail=str(exc)) from exc
    if item is None:  # gone meanwhile
        return _out(paths, _kept(paths))
    prefs = accounts.load_prefs(paths.prefs)
    item = routine_plan.ensure(prefs, paths.chat, [item], date.today(),
                               spend_free=engine.spend_free_quota)[0]
    briefing._save_counters(paths, prefs)
    return _out(paths, [item])


@router.delete("", status_code=status.HTTP_204_NO_CONTENT,
               summary="Drop the brief: back to the default card")
def drop(paths: RoutineSave) -> None:
    for item in _kept(paths):
        learnings.drop(paths.learnings, item.id)
