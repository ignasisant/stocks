"""Editing the watchlist over HTTP.

The edits themselves live in `stocks.watchlist`, shared with the pages, so a
change made here and the same change made in the app leave the file in the same
state — alert rules, the alias map and every other entry preserved either way.

What this module decides is the HTTP shape on top of them:

* **POST creates or updates.** Naming a ticker is enough to list it, which is
  how the app has always behaved: favouriting a held-only symbol adds it. So
  POST is an upsert and carries whatever fields the caller has.
* **PATCH and DELETE need it to exist.** Over HTTP a 404 is worth more than the
  convenience: a client that PATCHes a typo should hear about the typo, not
  silently create a watchlist entry for `AAPl`.
* **A session only**, like every write here — see `api/deps.writer`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Path, status
from pydantic import BaseModel, Field

from stocks import watchlist as wl
from stocks.api.deps import Account, Writer
from stocks.api.schemas import AlertRule, Alerts, TagEdit, Tags, WatchlistEntry
from stocks.config import ALERT_TYPES, load_watchlist
from stocks.data.crypto import is_crypto

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

Symbol = Annotated[str, Path(min_length=1, max_length=32)]
Tag = Annotated[str, Path(min_length=1, max_length=64)]


class EntryBody(BaseModel):
    """The fields a caller may set on one entry.

    All optional, and only the ones actually sent are applied — `shares: 0`
    clears a holding while leaving the cost basis alone, which is a different
    request from not mentioning shares at all.
    """

    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, description="Display label; '' clears it.")
    favorite: bool | None = None
    tags: list[str] | None = Field(
        default=None, description="Replaces the whole list; [] removes them all."
    )
    shares: float | None = Field(
        default=None,
        description=(
            "Held quantity, for a book with no imported ledger. 0 clears it; an "
            "imported ledger wins over this either way."
        ),
    )
    cost: float | None = Field(default=None, description="Average cost; 0 clears it.")


class NewEntry(EntryBody):
    ticker: str = Field(min_length=1, max_length=32)


class AlertsBody(BaseModel):
    model_config = {"extra": "forbid"}

    alerts: list[AlertRule] = Field(
        default_factory=list, description="The whole set; [] clears every rule."
    )



def _entry(path, ticker: str) -> WatchlistEntry | None:
    symbol = ticker.strip().upper()
    for holding in load_watchlist(path):
        if holding.ticker.upper() == symbol:
            return WatchlistEntry(
                ticker=holding.ticker,
                name=holding.name,
                favorite=holding.favorite,
                tags=list(holding.tags),
                is_crypto=is_crypto(holding.ticker),
            )
    return None


def _apply(path, ticker: str, body: EntryBody) -> None:
    """Write the fields the caller actually sent, and only those."""
    sent = body.model_dump(exclude_unset=True)
    if "name" in sent:
        wl.set_name(path, ticker, sent["name"] or "")
    if "favorite" in sent:
        wl.set_favorite(path, ticker, bool(sent["favorite"]))
    if "tags" in sent:
        wl.set_tags(path, ticker, sent["tags"] or [])
    if "shares" in sent or "cost" in sent:
        wl.set_position(path, ticker, sent.get("shares"), sent.get("cost"))


# ----------------------------------------------------------------- tag groups
# A group is not an object anywhere — it is the same tag repeated on several
# holdings. These two routes exist because editing it any other way means the
# client rewriting every member's tag list and getting the de-duplication right.


@router.get("/tags", response_model=Tags, summary="Every tag in use")
def tags(account: Account) -> Tags:
    return Tags(tags=wl.all_tags(account.watchlist))


@router.patch("/tags/{tag}", response_model=TagEdit, summary="Rename a group")
def rename(
    account: Writer,
    tag: Tag,
    name: Annotated[str, Body(embed=True, min_length=1, max_length=64)],
) -> TagEdit:
    """Rename a group across every holding that carries it.

    Renaming onto an existing group merges the two, which is de-duplicated per
    holding rather than refused: a reader consolidating "semis" into "tech"
    means the merge.
    """
    return TagEdit(
        tag=name.strip(), holdings=wl.rename_tag(account.watchlist, tag, name)
    )


@router.delete("/tags/{tag}", response_model=TagEdit, summary="Ungroup")
def ungroup(account: Writer, tag: Tag) -> TagEdit:
    """Drop a group, keeping its members on the watchlist.

    Ungrouping is not un-following: the tickers stay listed, they just stop
    being a group.
    """
    return TagEdit(tag=tag, holdings=wl.delete_tag(account.watchlist, tag))


# ------------------------------------------------- examples for a declared focus


class Suggestion(BaseModel):
    """One example security for an area the account says it follows."""

    ticker: str
    name: str = ""
    tags: list[str] = []


class Suggestions(BaseModel):
    suggestions: list[Suggestion] = Field(
        default_factory=list,
        description=(
            "Examples to look at, not recommendations. Empty for an account "
            "that declared no focus, and it shrinks as it is taken up: "
            "anything already on the list is filtered out, so the offer "
            "disappears once there is nothing left to add."
        ),
    )


@router.get(
    "/suggestions", response_model=Suggestions, summary="Examples for your focus"
)
def suggestions(account: Account) -> Suggestions:
    """Example tickers for the focus areas the investor profile declares.

    Served rather than held by a client for the reason every table here is:
    a list of securities frozen into a bundle goes stale, and a stale list of
    company names shipped next to a portfolio starts reading as advice. The
    catalog lives with the profile that selects from it (`web/auth`), and the
    page that offers them adds them through `POST /watchlist` like any other
    entry.
    """
    from stocks import accounts
    from stocks.web import auth

    prefs = accounts.load_prefs(account.prefs)
    rows = auth.focus_suggestions(auth.load_profile(prefs), account.watchlist)
    return Suggestions(
        suggestions=[
            Suggestion(
                ticker=str(row.get("ticker") or ""),
                name=str(row.get("name") or ""),
                tags=[str(tag) for tag in (row.get("tags") or [])],
            )
            for row in rows
        ]
    )


@router.post("", response_model=WatchlistEntry, summary="Add or update one")
def add(account: Writer, body: NewEntry) -> WatchlistEntry:
    """List a ticker, or update it if it is already listed.

    An upsert rather than a 409 on a repeat: "follow this symbol" is the
    request, and a client that cannot know whether the app already listed it
    should not have to ask first.
    """
    ticker = body.ticker.strip().upper()
    wl.add_entry(account.watchlist, ticker)
    _apply(account.watchlist, ticker, body)
    entry = _entry(account.watchlist, ticker)
    assert entry is not None  # it was just written
    return entry


@router.patch("/{ticker}", response_model=WatchlistEntry, summary="Change one")
def edit(account: Writer, ticker: Symbol, body: EntryBody) -> WatchlistEntry:
    """Apply the sent fields to a listed ticker.

    404 when it is not listed. In the app, tagging an unlisted symbol adds it —
    that is a person pointing at something on screen. A PATCH is a client naming
    a string, and the string is as likely to be a typo as an intention.
    """
    if _entry(account.watchlist, ticker) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{ticker.upper()} is not on this watchlist",
        )
    _apply(account.watchlist, ticker, body)
    entry = _entry(account.watchlist, ticker)
    assert entry is not None
    return entry


@router.delete(
    "/{ticker}", status_code=status.HTTP_204_NO_CONTENT, summary="Stop following one"
)
def drop(account: Writer, ticker: Symbol) -> None:
    """Remove a ticker, its tags and its alert rules.

    404 rather than a silent 204 when it was not there: the two outcomes look
    identical to a client otherwise, and one of them means the request did
    nothing it was meant to.
    """
    if not wl.remove_entry(account.watchlist, ticker):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{ticker.upper()} is not on this watchlist",
        )


# --------------------------------------------------------------------- alerts
# A sub-resource rather than a field on the entry: the rules are replaced as a
# set (they carry no ids of their own, so there is nothing to PATCH), and a
# client editing a label should not have to resend them to avoid losing them.


def _alerts(path, ticker: str) -> list[AlertRule]:
    symbol = ticker.strip().upper()
    for holding in load_watchlist(path):
        if holding.ticker.upper() == symbol:
            return [
                AlertRule(
                    type=alert.type,
                    price=alert.price,
                    pct=alert.pct,
                    level=alert.level,
                    window=alert.window,
                )
                for alert in holding.alerts
            ]
    return []


@router.get("/{ticker}/alerts", response_model=Alerts, summary="One ticker's rules")
def alerts(account: Account, ticker: Symbol) -> Alerts:
    if _entry(account.watchlist, ticker) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{ticker.upper()} is not on this watchlist",
        )
    symbol = ticker.strip().upper()
    return Alerts(ticker=symbol, alerts=_alerts(account.watchlist, symbol))


@router.put("/{ticker}/alerts", response_model=Alerts, summary="Replace them")
def set_alerts(account: Writer, ticker: Symbol, body: AlertsBody) -> Alerts:
    """Replace a ticker's whole rule set; an empty list clears it.

    A PUT and not a PATCH because that is what the underlying edit is: the rules
    have no identity of their own, so "change the second one" is not a request
    anything here could honour. Send the set you want.
    """
    if _entry(account.watchlist, ticker) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{ticker.upper()} is not on this watchlist",
        )
    unknown = sorted({a.type for a in body.alerts} - ALERT_TYPES)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown alert type(s): {', '.join(unknown)}",
        )
    wl.set_alerts(
        account.watchlist,
        ticker,
        [rule.model_dump(exclude_none=True) for rule in body.alerts],
    )
    symbol = ticker.strip().upper()
    return Alerts(ticker=symbol, alerts=_alerts(account.watchlist, symbol))
