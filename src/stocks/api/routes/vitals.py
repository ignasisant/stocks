"""What the page felt like to the reader, filed into the production log.

The server's own timing says how long a route took; it cannot say when the
reader first saw a figure, whether a tap answered at once, or whether the
page jumped under them. The browser measures those (the Core Web Vitals:
LCP, INP, CLS, and the TTFB they sit on), and the shell (`shell/vitals.ts`)
posts the page's final values here once, as the reader leaves it. Each
becomes one `client.vital` event, so

    stocks logs stats --event client.vital --by metric

reads p50/p95 per metric off the same log everything else is in, and
`--by where` splits them per page.

Fire and forget, like `/client-error`: a 204 whatever happens, and nothing a
reader could notice. Open to guests, because a guest's first paint is the
one the pitch is judged by. Tokens are refused: there is no browser behind
one. Metered per client address, quietly.

What is kept is a handful of numbers and the page's name with its query
stripped — `ticker?symbol=` would otherwise land in the log beside the
reader's address.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.api.routes.client_error import _browser
from stocks.api.security import Who
from stocks.web import ratelimit

router = APIRouter(tags=["client"])

# Per client address and hour: a report per page view, and a reader does not
# open more pages than this in an hour — a script does.
MAX_PER_HOUR = 120
WINDOW_S = 3600

Metric = Literal["LCP", "INP", "CLS", "TTFB", "FCP"]


class Vital(BaseModel):
    model_config = {"extra": "forbid"}

    name: Metric
    # Milliseconds for the timings; a unitless score for CLS.
    value: float = Field(ge=0, le=600_000)
    rating: Literal["good", "needs-improvement", "poor"]


class Vitals(BaseModel):
    model_config = {"extra": "forbid"}

    metrics: list[Vital] = Field(max_length=8)
    # The page, as the shell names it: `ticker`, `home`. Never its query.
    where: str = Field(default="", max_length=40, pattern=r"^[\w-]*$")
    # How the page was arrived at: a fresh visit, a reload, back/forward.
    nav: Literal["navigate", "reload", "back_forward", "prerender", ""] = ""
    # Whether the first paint drew figures kept from the last visit.
    kept: bool = False


def admitted(request: Request, who: Who) -> bool:
    """Logged, or quietly dropped — the same rule as `client_error.admitted`."""
    if who.kind == "token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="page timings come from a browser session, not a token",
        )
    key = f"vitals::{ratelimit.client_ip(request)}"
    if ratelimit.allow(key, max_events=MAX_PER_HOUR, window_s=WINDOW_S):
        return True
    obs.warn_once("client.vital_throttled", key)
    return False


@router.post(
    "/vitals",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="How a page felt to the reader",
)
def vitals(
    body: Vitals,
    logged: Annotated[bool, Depends(admitted)],
    request: Request,
) -> None:
    """Log each metric as one `client.vital` event. Always 204 to a browser."""
    if not logged:
        return
    ua = _browser(request.headers.get("user-agent", ""))
    for m in body.metrics:
        fields: dict[str, Any] = {
            "metric": m.name,
            "rating": m.rating,
            "where": body.where or "home",
            "nav": body.nav or "navigate",
            "kept": body.kept,
            "ua": ua,
        }
        # `duration_ms` is what `logs stats` takes percentiles of; CLS is a
        # score, not a time, and goes out under its own name.
        if m.name == "CLS":
            fields["score"] = round(m.value, 4)
        else:
            fields["duration_ms"] = round(m.value)
        obs.event("client.vital", **fields)
