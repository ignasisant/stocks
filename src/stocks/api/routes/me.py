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
            "address, as the Streamlit one does."
        ),
    )
    picture: str | None = Field(
        default=None,
        description="The provider's avatar URL, from the claims; null for none.",
    )
    data_dir: str | None = Field(
        default=None,
        description=(
            'The tail of this account\'s data folder — "users/<account>" — '
            "the chip on the identity card. The tail and not the path because "
            "the identifying part is the last segment, and the whole path "
            "pushes the card's buttons onto a second line."
        ),
    )
    data_dir_full: str | None = Field(
        default=None,
        description=(
            "The full folder, for the chip's tooltip. Sent only to the "
            "session that owns it: it names this host's filesystem, which is "
            "the account's own business and nobody else's."
        ),
    )
    owner: bool = Field(
        default=False,
        description=(
            "Whether this session is the deployment owner's, whose book is the "
            "repo-root files the CLI shares. The owner's is not an account "
            "that can be deleted (`DELETE /account` answers 403), so a client "
            "hides the control rather than offering a button that can only "
            "fail — the Streamlit page's `paths.root == PROJECT_ROOT` rule."
        ),
    )


def _short_path(path) -> str:
    """".../users/<account>" — `app_pages.profile._short_path`, same rule."""
    parts = str(path).split("/")
    return "/".join(parts[-2:]) if len(parts) > 3 else str(path)


def _claim(claims: dict | None, key: str) -> str | None:
    return str((claims or {}).get(key) or "").strip() or None


@router.get("/me", response_model=Me, summary="The caller's own identity")
def me(who: Who, request: Request) -> Me:
    signin = session.LOGIN_PATH if session.sign_in_configured() else None
    if who.kind != "session" or not who.email:
        return Me(kind=who.kind, email=who.email, sign_in=signin)
    claims = session.claims(request.cookies)
    # Where the account's files are, computed and never created: this is the
    # first call a client makes, and resolving (let alone provisioning) an
    # account belongs to the routes that read one. A folder that does not
    # exist yet is still the folder the account will live in.
    try:
        root = accounts.paths_for(who.email, accounts.configured_owner()).root
    except Exception:  # noqa: BLE001 — a card decoration, not the identity
        root = None
    return Me(
        kind=who.kind,
        email=who.email,
        sign_in=signin,
        name=_claim(claims, "name"),
        picture=_claim(claims, "picture"),
        data_dir=_short_path(root) if root is not None else None,
        data_dir_full=str(root) if root is not None else None,
        owner=root == PROJECT_ROOT,
    )
