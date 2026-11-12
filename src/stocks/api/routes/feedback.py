"""One route so a reader can say what is wrong, from any screen.

Open to guests too — a visitor who bounced knowing why is worth more than a
login.

Stored, not sent anywhere: `web/feedback.py` writes a JSON file under
`data/feedback/` and mirrors it to the bucket. This router is the binding, and
it supplies the two things only a caller can know — who wrote it and in which
language.

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
from stocks.accounts import UserPaths
from stocks.api.deps import Writer
from stocks.api.security import Who
from stocks.config import PROJECT_ROOT
from stocks.web import feedback as store
from stocks.web import ratelimit

router = APIRouter(tags=["feedback"])

# What an anonymous submission costs, per client address — there because
# nothing else stands between this route and a script. `client_ip` is a speed
# bump, not an identity — see its docstring — so the number is small enough
# that clearing it by hand is not worth anyone's afternoon and large enough to
# send a bug, then the screenshot you forgot.
GUEST_MAX_PER_HOUR = 3
GUEST_WINDOW_S = 3600

# The screenshot the composer offers. Decoded here so a client cannot push an
# arbitrary blob through as an image.
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
    return _slug(accounts.paths_for(who.email, accounts.configured_owner()))


def _slug(paths: UserPaths) -> str:
    return "owner" if paths.root == PROJECT_ROOT else paths.root.name


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
    guest, and this button has always been offered to anonymous visitors. A
    reader who bounced off the pitch telling us why is worth more than a
    login. What it
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
        # The composer only ever sends a JPEG (`shell/screenshot.ts`); anything
        # else is a file somebody wants stored and later opened by the operator.
        if not shot.startswith(b"\xff\xd8\xff"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="shot must be a JPEG",
            )
    store.submit(
        body.text,
        body.kind,
        page=body.page,
        shot=shot,
        sender=from_,
        lang=body.lang or "",
    )
    return Sent()


class AppRating(BaseModel):
    model_config = {"extra": "forbid"}

    stars: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=store.MAX_CHARS)
    page: str = Field(default="", max_length=120)
    lang: str | None = None


@router.post(
    "/feedback/rating",
    response_model=Sent,
    status_code=status.HTTP_201_CREATED,
    summary="Score the app, with an optional comment",
)
def rate_app(body: AppRating, from_: Sender) -> Sent:
    """The answer to the one-time rating prompt (`shell/RatePrompt`).

    Signed-in only: unlike `/feedback` it is not in `guest.OPEN_WRITES`, since
    the shell never asks a guest and a score from nobody in particular is
    noise. `sender` still refuses a token.
    """
    store.rate_app(
        body.stars, body.text, page=body.page, sender=from_, lang=body.lang or ""
    )
    return Sent()


# ------------------------------------------------------------------ replies

# The answers this account has been shown (`feedback_replies_seen`, a pref);
# the newest are kept, enough for every answer one reader will ever be given.
SEEN_KEY = "feedback_replies_seen"
SEEN_MAX = 50


class FeedbackReply(BaseModel):
    id: str
    about: str = Field(description="When the answered submission was sent (UTC stamp).")
    kind: str
    text: str


class RepliesSeen(BaseModel):
    model_config = {"extra": "forbid"}

    ids: list[str] = Field(min_length=1, max_length=SEEN_MAX)


@router.get(
    "/feedback/replies",
    response_model=list[FeedbackReply],
    summary="Answers to what this account reported, not yet shown",
)
def replies(paths: Writer) -> list[FeedbackReply]:
    """What the operator answered (`stocks feedback-reply`), minus what the
    reader has already been shown. Signed-in only: a guest's submission has no
    account to be answered in, and a token names nobody to show it to."""
    seen = set(accounts.stored_prefs(paths.prefs).get(SEEN_KEY) or [])
    return [
        FeedbackReply(
            id=r["id"], about=str(r.get("about", "")), kind=str(r.get("kind", "")),
            text=str(r.get("text", "")),
        )
        for r in store.replies_for(_slug(paths))
        if r.get("id") and r["id"] not in seen
    ]


@router.post(
    "/feedback/replies/seen",
    response_model=Sent,
    summary="Mark answers as shown",
)
def replies_seen(body: RepliesSeen, paths: Writer) -> Sent:
    """Stamped when shown, not when dismissed — like the rating prompt: an
    answer the reader closed, scrolled past or reloaded over has been given."""
    with accounts.prefs_lock(paths.prefs):
        held = [str(i) for i in accounts.stored_prefs(paths.prefs).get(SEEN_KEY) or []]
        fresh = [i for i in body.ids if i not in held]
        if fresh:
            accounts.update_prefs(paths.prefs, {SEEN_KEY: (held + fresh)[-SEEN_MAX:]})
    obs.event("feedback.reply_seen", count=len(body.ids))
    return Sent()
