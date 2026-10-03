"""Who this request is, as the server sees it.

The first call a front end makes: it decides whether to paint a book or a
sign-in button, and it is the only way a client can learn its own address —
which it needs because every other account-scoped route may be asked with no
`?account=` at all when a session is present.

Deliberately thin. `kind` and `email` are the identity this request *proved*;
everything else is presentation for the Profile identity card — the name and
avatar Google put in the session's claims, where the account's files live, and
whether this is the owner's book — and is only ever filled for a session,
about that session's own account. A claim can decorate a card; it never
decides what a request may do (`security.visitor` does that from the
signature alone).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from stocks import accounts, session
from stocks.api.security import Who
from stocks.bank import access
from stocks.config import PROJECT_ROOT

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
    name: str | None = Field(
        default=None,
        description=(
            "The display name the identity provider gave, from the session's "
            "claims. Null when it gave none — the card falls back to the "
            "address."
        ),
    )
    picture: str | None = Field(
        default=None,
        description="The provider's avatar URL, from the claims; null for none.",
    )
    bank: bool = Field(
        default=False,
        description=(
            "Whether this account may use the bank connection. It is an "
            "allowlist that fails closed (`stocks.bank.access`), so for almost "
            "every caller this is false and the page is not theirs to reach. "
            "A front end reads it to decide whether the Bank entry belongs in "
            "its navigation — the page itself is gated by the API regardless, "
            "so this only spares a reader a door that opens onto a refusal."
        ),
    )
    owner: bool = Field(
        default=False,
        description=(
            "Whether this session is the deployment owner's, whose book is the "
            "repo-root files the CLI shares. The owner's is not an account "
            "that can be deleted (`DELETE /account` answers 403), so a client "
            "hides the control rather than offering a button that can only "
            "fail."
        ),
    )


def _claim(claims: dict | None, key: str) -> str | None:
    return str((claims or {}).get(key) or "").strip() or None


@router.get("/me", response_model=Me, summary="The caller's own identity")
def me(who: Who, request: Request) -> Me:
    signin = session.LOGIN_PATH if session.sign_in_configured() else None
    if who.kind != "session" or not who.email:
        return Me(kind=who.kind, email=who.email, sign_in=signin)
    claims = session.claims(request.cookies)
    # Where the account's files are, computed and never created, only to tell
    # the owner's book apart: this is the first call a client makes, and
    # resolving (let alone provisioning) an account belongs to the routes that
    # read one.
    try:
        root = accounts.paths_for(who.email, accounts.configured_owner()).root
    except Exception:  # noqa: BLE001 — the owner flag, not the identity
        root = None
    return Me(
        kind=who.kind,
        email=who.email,
        sign_in=signin,
        name=_claim(claims, "name"),
        picture=_claim(claims, "picture"),
        owner=root == PROJECT_ROOT,
        bank=access.available(who.email),
    )
