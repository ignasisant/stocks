"""One route so a reader can say what is wrong, from any screen.

The Streamlit app puts this button in the sidebar of every page, guests
included — a visitor who bounced knowing why is worth more than a login. That
reasoning does not change with the front end, so the capability follows it here
rather than being quietly dropped in the rebuild.

Stored, not sent anywhere: `web/feedback.py` writes a JSON file under
`data/feedback/` and mirrors it to the bucket. This router is the binding, and
it supplies the two things only a caller can know — who wrote it and in which
language — because neither is derivable without a Streamlit session.

The one unauthenticated write in the whole API, which is a thing to be careful
about rather than a thing to be sorry about: free text plus an image, from
anybody. Three properties keep that narrow. It never touches a book — the sink
is `data/feedback/`, not the writer's directory — so nothing a visitor sends
can change what another visitor reads. A token may not use it, so the route
cannot be a way to file against an account nobody can name. And an anonymous
submission is metered per client address, below, because a free-text endpoint
with no account behind it is a spam target by construction.
"""

from __future__ import annotations

import base64
import binascii
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from stocks import accounts, obs
from stocks.api.security import Who
from stocks.config import PROJECT_ROOT
from stocks.web import feedback as store
from stocks.web import ratelimit

router = APIRouter(tags=["feedback"])

# What an anonymous submission costs, per client address. Tighter than the
# signed-in cap in `web/feedback.py` (5/hour) and for a different reason: that
# one is there so somebody who is annoyed does not send the same thing nine
# times, this one is there because nothing else stands between this route and a
# script. `client_ip` is a speed bump, not an identity — see its docstring — so
# the number is small enough that clearing it by hand is not worth anyone's
# afternoon and large enough to send a bug, then the screenshot you forgot.
GUEST_MAX_PER_HOUR = 3
GUEST_WINDOW_S = 3600

# The screenshot the Streamlit composer offers. Decoded here so a client cannot
# push an arbitrary blob through as an image; the size ceiling is the same one
# `web/screenshot.py` applies before the page stores one.
MAX_SHOT = 2 * 1024 * 1024


class Feedback(BaseModel):
    model_config = {"extra": "forbid"}

    text: str = Field(min_length=1, max_length=store.MAX_CHARS)
    kind: str = Field(default="other", description=f"One of {store.KINDS}.")
    page: str = Field(default="", max_length=120)
    shot: str | None = Field(
        default=None,
        description="Optional base64 JPEG of the screen the writer was on.",
    )
    lang: str | None = None


class Sent(BaseModel):
    ok: bool = True


def sender(request: Request, who: Who) -> str:
    """Who this submission is from, or a refusal — as a dependency.

    A dependency rather than the first lines of the handler, and the reason is
    ordering: FastAPI solves dependencies before it validates the body, so this
    way a refusal is a refusal rather than a 422 about a field the caller was
    never going to be allowed to send. The rate limit belongs on the same side
    of that line — a flood should not get a 2MB base64 screenshot parsed before
    it is turned away.

    A **token** is refused exactly as it is on every other write: it names
    nobody and any holder can name any account, so a token that could file
    feedback could file it against somebody.

    A **guest** is allowed, which is the exception this route exists to make,
    and metered per client address because nothing else stands between it and a
    script. A guest is given no name rather than a wrong one.

    A **session** names itself. `paths_for` is a pure constructor — no mkdir, no
    bucket — so this costs a hash and touches nothing: filing feedback must not
    be what calls an account directory into existence.
    """
    if who.kind == "token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="writes require a signed-in session, not a token",
        )
    if who.kind == "guest":
        key = f"feedback_guest::{ratelimit.client_ip(request)}"
        if not ratelimit.allow(
            key, max_events=GUEST_MAX_PER_HOUR, window_s=GUEST_WINDOW_S
        ):
            wait = ratelimit.retry_after(key, window_s=GUEST_WINDOW_S)
            obs.warn("api.feedback_throttled", retry_after=wait)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many submissions from this address; try again later",
                headers={"Retry-After": str(max(1, wait))},
            )
        return "guest"
    assert who.email is not None  # a session always carries one
    root = accounts.paths_for(who.email, accounts.configured_owner()).root
    return "owner" if root == PROJECT_ROOT else root.name


#: The pseudonymous slug the logs already use, or "guest" — see above.
Sender = Annotated[str, Depends(sender)]


@router.post(
    "/feedback",
    response_model=Sent,
    status_code=status.HTTP_201_CREATED,
    summary="Tell us what is wrong",
)
def submit(body: Feedback, from_: Sender) -> Sent:
    """File one submission, signed in or not.

    Not `Writer`, which every other write in this API is declared against, and
    the exception is deliberate rather than an oversight: `Writer` refuses a
    guest, and the Streamlit app has always offered this button to anonymous
    visitors. A reader who bounced off the pitch telling us why is worth more
    than a login, and the rebuild does not get to quietly drop that. What it
    keeps of `Writer`'s rule is in `sender` above.

    No `Account` dependency either: feedback is filed by whoever is asking, so
    `?account=` has no meaning on this route and should not appear in its
    schema — and resolving one would bury the refusal above under a 404 about
    an address nobody asked about.
    """
    shot: bytes | None = None
    if body.shot:
        try:
            shot = base64.b64decode(body.shot, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="shot must be base64",
            ) from exc
        if len(shot) > MAX_SHOT:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"a screenshot may be at most {MAX_SHOT // 1024}kB",
            )
    store.submit(
        body.text,
        body.kind,
        page=body.page,
        shot=shot,
        # The same vocabulary `web/feedback._sender()` writes, so one reader of
        # `stocks feedback` sees one set of names whichever front end filed it.
        sender=from_,
        lang=body.lang or "",
    )
    return Sent()
