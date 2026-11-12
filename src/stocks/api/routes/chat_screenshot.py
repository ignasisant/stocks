"""A pasted screenshot, turned into the words it shows.

The composer's paste: the picture is read by a model that can see
(`chat/screenshot.py`) and the reading is handed back to the client, which
sends it beside the question on the path every turn takes
(`forwardedProps.screenshots`). This is that one step — reading and nothing
else, for the reason a voice note is transcribed before it is sent: the chat
is text from end to end, and a turn that carried a picture would be a second,
different turn.

**The picture never lands on disk**, here or anywhere: it is decoded, sent to
the model, and dropped. The thread stores what was read, and a screenshot of
somebody's brokerage account is the last thing this app should be
accumulating.

**The type is read off the bytes, not the request.** The body carries no
media type at all: the drawer re-encodes every paste to a JPEG, and a client
that sends something else is believed about it only as far as its first
bytes say.

**A refusal is a locale key, not a sentence**, as on the voice route:
`ReadFailed` carries the key the drawer already renders (`chat.shot_failed`,
`chat.shot_too_big`, …).

**`available()` decides whether a paste is taken.** An account with nothing
that can see answers 503 here and says so in `/chat/state`, so the composer
leaves a pasted picture alone rather than apologise for it.

**Every paste leaves a line in the log**, with the account on it and never
the picture or what it said:

* `shot.ok`: read, by which model, in how long (`chat/screenshot.py`), and
  `shot.failed` for each reader that was passed over on the way.
* `shot.refused`: this route said no, and why (`reason`). A warning when no
  reader could read it, which is the app's failure and not the paste's.
* `shot.client`: what only the browser saw (`POST /chat/screenshots/events`).
  The refusal the reader was shown (with `sent` false when the picture never
  left the browser), a picture pasted where nothing can see, a thumbnail
  taken back, a sent picture opened.
* `shot.used`: a question went out with readings beside it
  (`routes/chat/turns.py`).

`stocks logs shots` reads the four together.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from stocks import accounts, obs
from stocks.api.deps import Screenshot as ShotBudget
from stocks.api.routes.chat import session_keys
from stocks.api.routes.client_error import _browser
from stocks.api.security import Who
from stocks.chat import engine, screenshot
from stocks.web import ratelimit

router = APIRouter(prefix="/chat", tags=["chat"])

# Far past the cap, a body is refused before it is decoded at all; between
# the two it is decoded and told it is too big (413), which is the refusal
# the drawer can put into words.
_MAX_ENCODED = 4 * screenshot.MAX_BYTES

# An account's readings in a day, own key or not. The burst budget bounds a
# loop; this bounds the bill: nobody pastes this many pictures into a chat,
# and the keyless chain's vision quota is one pot for every account.
DAILY = 60
_DAY_S = 24 * 60 * 60

# What the browser reports of its own pastes, per client address and hour.
# A paste, a removal, a look: nobody does a hundred of them in an hour by hand.
EVENTS_PER_HOUR = 120
_HOUR_S = 3600

# Refusals that are the app's doing: a reader that was not there, or none that
# could read the picture. The rest are the paste's and logged as plain facts.
_OURS = frozenset({"unavailable", "failed"})


def _refused(code: int, detail: str, reason: str, *, size: int = 0,
             headers: dict[str, str] | None = None) -> HTTPException:
    """The refusal to raise, logged on its way out as one `shot.refused`."""
    obs.event("shot.refused",
              level=logging.WARNING if reason in _OURS else logging.INFO,
              reason=reason, status=code, bytes=size)
    return HTTPException(status_code=code, detail=detail, headers=headers)


class Picture(BaseModel):
    model_config = {"extra": "forbid"}

    image: str = Field(
        max_length=_MAX_ENCODED,
        description=(
            "The picture's bytes, base64-encoded: a JPEG, PNG or WebP of at "
            f"most {screenshot.MAX_BYTES // (1024 * 1024)} MB."
        ),
    )
    lang: str | None = Field(
        default=None,
        description=(
            "The language to describe the picture in. Text copied from it "
            "stays as written. Defaults to the account's."
        ),
    )
    via: Literal["paste", "pick", "drop"] = Field(
        default="paste",
        description=(
            "How the picture reached the composer: pasted, picked with the "
            "clip (a phone's camera or library included), or dropped on the "
            "conversation. Logged, nothing else."
        ),
    )


class Reading(BaseModel):
    text: str = Field(
        description=(
            "What the picture shows, as text. Send it back in a run's "
            "`forwardedProps.screenshots` to ask about it."
        ),
    )


@router.post("/screenshots", response_model=Reading,
             summary="Read a pasted screenshot")
def read(
    body: Picture,
    paths: ShotBudget,
    x_chat_provider: str | None = Header(default=None),
    x_chat_key: str | None = Header(default=None),
) -> Reading:
    """What a picture shows, in words. Writes nothing — not the picture, not a turn.

    A `Writer` even so: it spends a model call on the account's key or the
    operator's, which is exactly what a bearer token must never be able to do
    on somebody else's account.
    """
    prefs = accounts.load_prefs(paths.prefs)
    held = session_keys(x_chat_provider, x_chat_key)
    atts = engine.answerable(prefs, engine.chain(prefs, held))
    if not screenshot.available(atts):
        raise _refused(status.HTTP_503_SERVICE_UNAVAILABLE,
                       "chat.shot_unavailable", "unavailable")
    try:
        image = base64.b64decode(body.image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _refused(status.HTTP_422_UNPROCESSABLE_CONTENT,
                       "image must be base64", "not_base64") from exc
    if len(image) > screenshot.MAX_BYTES:
        raise _refused(status.HTTP_413_CONTENT_TOO_LARGE,
                       "chat.shot_too_big", "too_big", size=len(image))
    if screenshot.sniff(image) is None:
        raise _refused(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                       "chat.shot_unreadable", "unreadable", size=len(image))
    day = f"screenshot-day::{paths.root}"
    if not ratelimit.allow(day, max_events=DAILY, window_s=_DAY_S):
        raise _refused(
            status.HTTP_429_TOO_MANY_REQUESTS,
            # Its own key, not the burst's: "try again in 40,000 s" is not a
            # sentence, and tomorrow is.
            "chat.shot_day_limit", "day_limit", size=len(image),
            headers={"Retry-After": str(max(
                1, ratelimit.retry_after(day, window_s=_DAY_S)))},
        )

    lang = (body.lang or prefs.get("language") or "en").strip().lower()
    try:
        text = screenshot.read(image, atts, lang=lang, via=body.via)
    except screenshot.ReadFailed as failed:
        # 503 for a reader that was not there or did not answer — the picture
        # is not at fault and a second paste may well work — and 422 for what
        # the picture itself is guilty of. The body is the locale key either
        # way: the drawer already knows how to say it.
        down = failed.key in ("chat.shot_unavailable", "chat.shot_failed")
        raise _refused(
            status.HTTP_503_SERVICE_UNAVAILABLE
            if down
            else status.HTTP_422_UNPROCESSABLE_CONTENT,
            failed.key, failed.key.removeprefix("chat.shot_"), size=len(image),
        ) from failed
    return Reading(text=text)


class ShotEvent(BaseModel):
    """One thing the browser did with a pasted picture that no request shows."""

    model_config = {"extra": "forbid"}

    what: Literal["refused", "ignored", "removed", "opened"] = Field(
        description=(
            "`refused`: the composer showed a refusal for a paste. "
            "`ignored`: a picture was pasted where nothing can read one. "
            "`removed`: a thumbnail was taken back before the question went. "
            "`opened`: a sent picture was opened to look at."
        ),
    )
    why: str | None = Field(
        default=None, max_length=40, pattern=r"^chat\.[a-z_]+$",
        description="The locale key the composer showed, for a refusal.",
    )
    sent: bool | None = Field(
        default=None,
        description=(
            "For `refused`: whether the picture had been sent to be read. "
            "False is a refusal no other line in the log knows about."
        ),
    )
    read: bool | None = Field(
        default=None,
        description="For `removed`: whether its reading had already come back.",
    )


def _admitted(request: Request, who: Who) -> bool:
    """Logged, or quietly dropped: the same rule as `launch.admitted`."""
    if who.kind == "token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="a paste comes from a browser session, not a token",
        )
    key = f"shot-event::{ratelimit.client_ip(request)}"
    if ratelimit.allow(key, max_events=EVENTS_PER_HOUR, window_s=_HOUR_S):
        return True
    obs.warn_once("shot.client_throttled", key)
    return False


@router.post("/screenshots/events", status_code=status.HTTP_204_NO_CONTENT,
             summary="What the browser did with a pasted screenshot")
def seen(
    body: ShotEvent,
    logged: Annotated[bool, Depends(_admitted)],
    request: Request,
) -> None:
    """Log one `shot.client` event. Always 204 to a browser."""
    if not logged:
        return
    said: dict[str, Any] = {"what": body.what}
    if body.why:
        said["why"] = body.why.removeprefix("chat.").removeprefix("shot_")
    if body.sent is not None:
        said["sent"] = body.sent
    if body.read is not None:
        said["read"] = body.read
    obs.event("shot.client", **said, ua=_browser(request.headers.get("user-agent", "")))
