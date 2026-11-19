"""The app opened from a Home Screen, filed into the production log.

An installed app announces itself nowhere: the manifest opens it on
`/?installed=1`, but that request is the HTML shell, which carries no account.
So the shell (`shell/install.ts`), when it boots standalone, posts here once
per launch, and the request middleware stamps the account on the
`app.launch` line like on any other event. Then

    stocks logs installs

lists the accounts that have the app on a device, with the device and when
they last opened it.

The same app also files `app.viewport_stuck` here (`/viewport-stuck`): its
window left short by iOS after a keyboard, and whether the shell cured it.

Fire and forget, like `/vitals`: a 204 whatever happens. Open to guests, who
can install the app before they sign in; they log as `guest`. Tokens are
refused: there is no Home Screen behind one. Metered per client address.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from stocks import obs, ratelimit
from stocks.api.routes.client_error import _browser
from stocks.api.security import Who

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


# A stuck window is reported at most once a minute per app (`shell/viewport.ts`);
# more than this per address is not a phone.
STUCK_PER_HOUR = 60

_Px = Annotated[int, Field(ge=0, le=10_000)]


class ViewportStuck(BaseModel):
    """The Home Screen app's window, short after a keyboard went down.

    iOS 26 can leave the box `position: fixed` is laid out against a
    keyboard's height short once the keyboard has gone (WebKit 297779): the
    tab bar floats over the page until the app is killed. The shell measures
    the window when a keyboard goes down, tries to make WebKit measure it
    again, and sends both readings here, so the log says which size was
    stuck and whether the cure took.
    """

    model_config = {"extra": "forbid"}

    # Before the cure: `innerHeight`, `visualViewport.height` / `.offsetTop`,
    # `documentElement.clientHeight`, and the height of a probe fixed to every
    # edge — the box the tab bar is actually laid out against.
    inner: _Px
    vv: _Px
    top: _Px
    client: _Px
    fixed: _Px
    # The tallest `innerHeight` seen at this width and orientation, the
    # screen's height, and the shortest `innerHeight` while a field had the
    # focus (0 when none was seen): whether iOS shrank the window for the
    # keyboard at all.
    tallest: _Px
    screen: _Px
    typing: _Px
    # After it, and whether it was tried (a launch stops after a few misses).
    after_inner: _Px
    after_vv: _Px
    after_top: _Px
    after_fixed: _Px
    tried: bool
    healed: bool


def stuck_admitted(request: Request, who: Who) -> bool:
    """Logged, or quietly dropped — the same rule as `admitted`."""
    if who.kind == "token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="a window's size comes from a browser session, not a token",
        )
    key = f"viewport::{ratelimit.client_ip(request)}"
    if ratelimit.allow(key, max_events=STUCK_PER_HOUR, window_s=WINDOW_S):
        return True
    obs.warn_once("app.viewport_stuck_throttled", key)
    return False


@router.post(
    "/viewport-stuck",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="The Home Screen app's window stayed short after a keyboard",
)
def viewport_stuck(
    body: ViewportStuck,
    logged: Annotated[bool, Depends(stuck_admitted)],
    request: Request,
) -> None:
    """Log one `app.viewport_stuck` event. Always 204 to a browser."""
    if not logged:
        return
    obs.event(
        "app.viewport_stuck",
        **body.model_dump(),
        ua=_browser(request.headers.get("user-agent", "")),
    )
