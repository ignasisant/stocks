"""Dating a holdings snapshot: the days a position's price was on the board.

A portfolio report lists what is held and what it cost, never when it was
bought, and a ledger row needs a date. The reader types (or keeps) the price
paid, and this answers with the stretches of sessions whose range held it
(`portfolio.buy_dates`) — the day to pick is theirs, the evidence is ours.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.api.cache import ttl_cache
from stocks.api.deps import Writer
from stocks.data import fetch, profiles, symbols
from stocks.portfolio import buy_dates

router = APIRouter(prefix="/import", tags=["import"])

# A listing's whole history is one download per symbol; the reader retypes the
# price a few times, and every retype reads the same bars.
_BARS_TTL = 1800.0

# The form's own cap (`dating.ts` MAX_PRICE): past it a price is a typo.
_MAX_PRICE = 1e9


class BuyRun(BaseModel):
    start: str = Field(description="First session of the stretch, YYYY-MM-DD.")
    end: str = Field(description="Its last session.")
    day: str = Field(description="The session whose close sat nearest the price.")
    close: float = Field(description="That session's close, split-adjusted.")
    sessions: int


class BuyDates(BaseModel):
    """Where a price paid sits in a listing's history."""

    symbol: str = Field(description="The Yahoo line the bars are from.")
    currency: str = Field(
        default="",
        description="What the bars are quoted in. Empty when Yahoo never said.",
    )
    first: str = Field(default="", description="The oldest session in the bars.")
    runs: list[BuyRun] = Field(
        default_factory=list,
        description=(
            "Stretches whose low-high range held the price, newest first. "
            "Empty: the listing never traded there (another currency, or "
            "a price that predates the history)."
        ),
    )


def _symbol(ticker: str, isin: str, currency: str) -> str:
    """The line to price: the ISIN's when the file printed one, then a bare
    code's home venue in its currency, else the ticker as given."""
    if isin and (hit := symbols.symbol_for_isin(isin)):
        return hit
    if symbols.is_isin(ticker):
        return symbols.symbol_for_isin(ticker) or ticker
    ccy = currency.upper()
    if ccy and ccy != "USD" and "." not in ticker:
        with obs.swallow("import.buy_dates.code", ticker=ticker):
            if hit := symbols.symbol_for_code(ticker, ccy):
                return hit
    return ticker


@ttl_cache(_BARS_TTL, max_entries=32)
def _bars(symbol: str):
    # Dividend-unadjusted, as a fill was: the bars a broker's price compares to.
    return fetch.fetch_many([symbol], period="max", auto_adjust=False).get(symbol)


def _currency(symbol: str) -> str:
    if ccy := (profiles.known(symbol) or {}).get("currency"):
        return str(ccy).upper()
    with obs.swallow("import.buy_dates.currency", ticker=symbol):
        return str(fetch.info(symbol).get("currency") or "").upper()
    return ""


@router.get(
    "/buy-dates",
    response_model=BuyDates,
    summary="The days a holding could have been bought at a price",
)
def buy_dates_for(
    account: Writer,
    ticker: Annotated[str, Query(min_length=1, max_length=32)],
    # A finite share price: inf would match every session, a total pasted in
    # the field none.
    price: Annotated[float, Query(gt=0, le=_MAX_PRICE, allow_inf_nan=False)],
    isin: Annotated[str, Query(pattern=r"^([A-Za-z0-9]{12})?$")] = "",
    currency: Annotated[str, Query(pattern=r"^([A-Za-z]{3})?$")] = "",
) -> BuyDates:
    del account  # signed-in only; nothing here is the account's
    symbol = _symbol(ticker.strip().upper(), isin.strip().upper(), currency)
    try:
        bars = _bars(symbol)
    except Exception as exc:  # noqa: BLE001 — Yahoo down is "try again", not a 500
        obs.warn(
            "import.buy_dates.bars_failed", ticker=symbol, error_type=type(exc).__name__
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="prices are unavailable right now",
        ) from exc
    if bars is None or bars.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no price history for {symbol}",
        )
    found = buy_dates.runs(bars, price)
    obs.event("import.buy_dates", ticker=symbol, runs=len(found))
    return BuyDates(
        symbol=symbol,
        currency=_currency(symbol),
        first=bars.index[0].date().isoformat(),
        runs=[BuyRun(**run) for run in found],
    )
