"""The line a code was traded on, picked by the reader when no search placed it."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.api.deps import Writer
from stocks.api.routes.import_statement.lookups import (
    _UNANSWERED,
    LOOKUP_BUDGET_S,
    _charted,
    _close,
    _ticker_exists,
    _within,
)
from stocks.data import fetch, symbols
from stocks.jsonsafe import num as _num
from stocks.portfolio import (
    venue,
)

router = APIRouter(prefix="/import", tags=["import"])


# A code the search could not place anywhere imports unpriced, held at cost
# (`ImportPreview.unlisted`). The reader usually knows the security, though:
# they name it ("Merlin"), are shown the lines that name finds on the code's
# currency's venues, each priced on the days their fills were, and pick one.
# The pick is the code's answer in `CODE_CACHE`, which is one map for every
# account, so it is held to what a search answer would be: a real line on
# those venues that closed near the fills, for a code nothing answers yet.

VENUES_BUDGET_S = 10.0  # every option's closes, together
_VENUE_WORKERS = 6


class VenueFill(BaseModel):
    """One trade of the code, as the preview showed it."""

    model_config = {"extra": "forbid"}

    date: str = Field(min_length=10, max_length=32, description="YYYY-MM-DD…")
    price: float = Field(gt=0, description="Per share, in the code's currency.")


class VenueAsk(BaseModel):
    model_config = {"extra": "forbid"}

    code: str = Field(
        min_length=1, max_length=32, description="As the statement prints it."
    )
    currency: str = Field(min_length=3, max_length=4)
    fills: list[VenueFill] = Field(
        min_length=1,
        max_length=500,
        description="The preview's trades of the code; its latest two days count.",
    )
    query: str = Field(
        default="",
        max_length=80,
        description="The security's name as the reader puts it; the code when empty.",
    )


class VenueOption(BaseModel):
    symbol: str
    name: str
    exchange: str
    close: float | None = Field(
        description="Its close on `VenueOptions.day`; null when Yahoo could not say."
    )
    agrees: bool | None = Field(
        description=(
            "Closed near the fills on every sampled day; null when no sampled day "
            "has a close. Only a true one can be picked."
        )
    )


class VenueOptions(BaseModel):
    code: str
    currency: str
    day: str = Field(description="The latest fill's day, the one `close` is on.")
    price: float = Field(description="The fill on `day`.")
    options: list[VenueOption] = Field(default_factory=list)
    throttled: bool = Field(
        default=False,
        description="Yahoo was refusing this host, so a null `close` is not a verdict.",
    )


class VenuePick(VenueAsk):
    symbol: str = Field(min_length=1, max_length=32)


class VenuePicked(BaseModel):
    code: str
    symbol: str


def _venue_key(code: str) -> str:
    return code.strip().upper()


def _option(line: tuple[str, str, str], sampled, currency: str) -> VenueOption:
    symbol, name, exchange = line
    return VenueOption(
        symbol=symbol,
        name=name,
        exchange=exchange,
        close=_num(_close(symbol, sampled[0][0])),
        agrees=venue.agrees(symbol, sampled, currency, _close),
    )


@router.post("/venues", response_model=VenueOptions, summary="Lines a code could be")
def venues(account: Writer, body: Annotated[VenueAsk, ...]) -> VenueOptions:
    """The lines `query` finds on the code's currency's venues, each priced on
    the days the code was traded.

    A POST because the fills travel in the body; it writes nothing. Every
    option's closes are asked at once within `VENUES_BUDGET_S`, and one still
    out then comes back unpriced rather than holding the others.
    """
    del account  # a session, like every other non-GET here
    sampled = venue.latest((fill.date, fill.price) for fill in body.fills)
    currency = body.currency.strip().upper()
    lines = symbols.lines_for(body.query.strip() or body.code, currency)
    options: list[VenueOption] = []
    if lines:
        pool = ThreadPoolExecutor(max_workers=min(len(lines), _VENUE_WORKERS))
        try:
            asked = [pool.submit(_option, line, sampled, currency) for line in lines]
            wait(asked, timeout=VENUES_BUDGET_S)
            for line, future in zip(lines, asked, strict=True):
                done = future.done() and not future.exception()
                options.append(
                    future.result()
                    if done
                    else VenueOption(
                        symbol=line[0],
                        name=line[1],
                        exchange=line[2],
                        close=None,
                        agrees=None,
                    )
                )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    return VenueOptions(
        code=_venue_key(body.code),
        currency=currency,
        day=sampled[0][0],
        price=sampled[0][1],
        options=options,
        throttled=fetch.throttle_remaining() > 0,
    )


@router.post("/venue", response_model=VenuePicked, summary="The line a code is")
def venue_pick(account: Writer, body: Annotated[VenuePick, ...]) -> VenuePicked:
    """Remember `symbol` as the code's line, for every price lookup after.

    Checked here, not believed, because the map is every account's: the code
    has to be one nothing prices — no alias, no map answer, no bare quote, and
    a search that still cannot place it — and the symbol a line of the code's
    currency's venues that closed near the fills on the days they were made
    (`venue.agrees`, priced now). Anything else is a 409 and nothing is
    written; a Yahoo that could not be asked is a 503, to try again.
    """
    del account  # a session, like every other non-GET here
    code = _venue_key(body.code)
    symbol = body.symbol.strip().upper()
    currency = body.currency.strip().upper()

    def refuse(detail: str, kind: int = status.HTTP_409_CONFLICT):
        return HTTPException(status_code=kind, detail=detail)

    held = fetch.resolve(code)
    if held != code:
        raise refuse(f"{code} is already priced as {held}")
    if not fetch.unlisted({code}):
        quoted = _within(lambda: _ticker_exists(code), LOOKUP_BUDGET_S, None, ticker=code)
        if quoted is None:
            quoted = _charted(code, LOOKUP_BUDGET_S)
        if quoted is None:
            raise refuse("Yahoo could not be asked", status.HTTP_503_SERVICE_UNAVAILABLE)
        if quoted:
            raise refuse(f"Yahoo quotes {code} as it is")
    found = _within(
        lambda: symbols.symbol_for_code(code, currency),
        LOOKUP_BUDGET_S,
        _UNANSWERED,
        ticker=code,
    )
    if found is _UNANSWERED:
        raise refuse("Yahoo could not be asked", status.HTTP_503_SERVICE_UNAVAILABLE)
    if found:
        raise refuse(f"{code} is priced as {found} now")
    if not symbols.on_venues(symbol, currency):
        raise refuse(f"{symbol} is not a {currency} line")
    sampled = venue.latest((fill.date, fill.price) for fill in body.fills)
    if venue.agrees(symbol, sampled, currency, _close) is not True:
        raise refuse(f"{symbol} did not close near {code}'s fills")
    symbols.remember_code(code, symbol)
    fetch.relisted(code)
    obs.event("import.venue_picked", code=code, symbol=symbol)
    return VenuePicked(code=code, symbol=symbol)
