"""The app opened from a Home Screen, filed into the production log.

An installed app announces itself nowhere: the manifest opens it on
`/?installed=1`, but that request is the HTML shell, which carries no account.
So the shell (`shell/install.ts`), when it boots standalone, posts here once
per launch, and the request middleware stamps the account on the
`app.launch` line like on any other event. Then

    stocks logs installs

lists the accounts that have the app on a device, with the device and when
they last opened it.

Fire and forget, like `/vitals`: a 204 whatever happens. Open to guests, who
can install the app before they sign in; they log as `guest`. Tokens are
refused: there is no Home Screen behind one. Metered per client address.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from stocks import obs
from stocks.api.routes.client_error import _browser
from stocks.api.security import Who
from stocks.web import ratelimit

router = APIRouter(tags=["client"])

# Per client address and hour: an app is not cold-started more often than
# this by hand.
MAX_PER_HOUR = 30
WINDOW_S = 3600


class Launch(BaseModel):
    model_config = {"extra": "forbid"}

    # What the shell knows and the user agent does not say: an iPad reports a
    # Mac, which the shell tells apart by its touchscreen.
    device: Literal["ios", "android", "desktop", "other"] = "other"


def admitted(request: Request, who: Who) -> bool:
    """Logged, or quietly dropped — the same rule as `vitals.admitted`."""
    if who.kind == "token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="an app launch comes from a browser session, not a token",
        )
    key = f"launch::{ratelimit.client_ip(request)}"
    if ratelimit.allow(key, max_events=MAX_PER_HOUR, window_s=WINDOW_S):
        return True
    obs.warn_once("app.launch_throttled", key)
    return False


@router.post(
    "/launch",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="The app was opened from a Home Screen",
)
def launch(
    body: Launch,
    logged: Annotated[bool, Depends(admitted)],
    request: Request,
) -> None:
    """Log one `app.launch` event. Always 204 to a browser."""
    if not logged:
        return
    obs.event(
        "app.launch",
        device=body.device,
        ua=_browser(request.headers.get("user-agent", "")),
    )
