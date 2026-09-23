"""Who this request is, as the server sees it.

The first call a front end makes: it decides whether to paint a book or a
sign-in button, and it is the only way a client can learn its own address —
which it needs because every other account-scoped route may be asked with no
`?account=` at all when a session is present.

Deliberately thin. It reports the identity this request *proved*, not the
claims the cookie happens to carry, so nothing here can be mistaken for a
profile endpoint.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from stocks import session
from stocks.api.security import Who

router = APIRouter(tags=["identity"])


class Me(BaseModel):
    kind: Literal["session", "token", "guest"] = Field(
        description=(
            '"session" for a signed-in browser, "token" for a job, "guest" for '
            "an anonymous visitor reading the shared demo book."
        )
    )
    email: str | None = Field(
        default=None,
        description=(
            "The verified address this request is signed in as. Null for a "
            "token caller, which names nobody and must pass ?account= instead, "
            "and for a guest, which names nobody and may not."
        ),
    )
    sign_in: str | None = Field(
        default=None,
        description=(
            "Where to send somebody who wants an account, or null when this "
            "deployment has no identity provider configured. A front end needs "
            "this to know whether to draw a sign-in button at all."
        ),
    )


@router.get("/me", response_model=Me, summary="The caller's own identity")
def me(who: Who) -> Me:
    return Me(
        kind=who.kind,
        email=who.email,
        sign_in=session.LOGIN_PATH if session.sign_in_configured() else None,
    )
