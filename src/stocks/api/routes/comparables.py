"""One KPI table across several tickers.

Its own route rather than a query on `/ticker/{s}/metrics`, because the
comparison is the thing: the medals rank names *against each other*, so they
only mean anything computed over the same set in one pass. Asking for each
ticker separately and joining on the client would produce a table with no
podium, or three podiums.

Rows are pre-formatted strings, not raw numbers. The app's comps table prints
`format_value` output with its units baked in, and a client re-deriving "14.2x"
from 14.2 is a second formatting rule for the same figure.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from stocks.analysis.fundamentals import (
    comp_medals,
    comparables_table,
    compute_metrics,
)
from stocks.api import loaders
from stocks.api.schemas import Comparables

router = APIRouter(tags=["comparables"])

# Each name is a fundamentals pull. Yahoo throttles shared cloud IPs hard, and
# the app's own comps table is picked by hand a few names at a time.
_MAX_TICKERS = 8


@router.get("/comparables", response_model=Comparables, summary="Cross-ticker KPIs")
def comparables(
    tickers: Annotated[
        str, Query(description="Comma-separated tickers, first is the subject.")
    ],
) -> Comparables:
    wanted: list[str] = []
    for raw in tickers.split(","):
        symbol = raw.strip().upper()
        # Order is the caller's — the subject leads and the peers follow — so
        # dedupe in place rather than through a set.
        if symbol and symbol not in wanted:
            wanted.append(symbol)
    if not wanted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="tickers must name at least one symbol",
        )
    if len(wanted) > _MAX_TICKERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"at most {_MAX_TICKERS} tickers per request",
        )

    rows = [compute_metrics(loaders.fundamentals(t)) for t in wanted]
    table = comparables_table(rows)
    return Comparables(
        tickers=wanted,
        labels=[str(label) for label in table.index],
        rows={str(col): [str(v) for v in table[col]] for col in table.columns},
        medals=comp_medals(rows),
    )
