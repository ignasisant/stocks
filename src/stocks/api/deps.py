"""Turning a request into an account: which book, in which currency.

Which account depends on how the caller proved itself, and the difference is
the whole security model:

* **A session** names a verified address by itself. That address wins, and
  `?account=` may only repeat it — a signed-in browser must never be able to
  ask for somebody else's book by editing a query string.
* **A token** names nobody, so the caller has to say. Any token holder can
  therefore read every account, which is why the token is for the owner's own
  jobs and not for anyone else (see `api/security.py`).

Everything after that — the data directory, the bucket restore, the reporting
currency — is resolved from `stocks.accounts` and the account's own prefs.json,
the same way the web app resolves them.
"""

from __future__ import annotations

import json
import shutil
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

from stocks import accounts
from stocks.accounts import UserPaths
from stocks.api.security import Who
from stocks.config import CURRENCIES

# Enough of an address check to keep a path traversal or a stray blank out of
# `slug()`. Real validation happened at the OIDC login that created the dir —
# an address this API has never seen simply has no directory and 404s.
_MAX_EMAIL = 254


def _valid(address: str) -> str:
    if "@" not in address or "/" in address or "\\" in address:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="account must be an email address",
        )
    return address


def _resolve(email: str) -> UserPaths:
    paths = accounts.paths_for(email, accounts.configured_owner())
    existed = paths.root.exists()
    try:
        # seed=False: reading an account must not create one. Without it, a
        # token holder could call any address into existence by asking about it.
        accounts.restore_account(paths, seed=False)
    except accounts.StorageUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account storage unavailable",
        ) from exc
    if paths.db.exists() or paths.watchlist.exists():
        return paths
    # The restore had to mkdir before it could pull; nothing came back, so this
    # address has no book here. Leave no trace of the guess behind.
    if not existed and paths.root.is_dir() and not any(paths.root.iterdir()):
        shutil.rmtree(paths.root, ignore_errors=True)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="unknown account"
    )


def account(
    caller: Who,
    email: Annotated[
        str | None,
        Query(
            alias="account",
            max_length=_MAX_EMAIL,
            description=(
                "Account to read. Required for a token caller; for a signed-in "
                "one it may only repeat the session's own address."
            ),
        ),
    ] = None,
) -> UserPaths:
    """FastAPI dependency: this request's account paths, or 4xx/503."""
    asked = _valid(email.strip().lower()) if email else None

    # First, and deliberately first. This function used to end in a token
    # fall-through, so anything that was not a session took the branch that
    # reads `?account=` — which is the one branch a guest must never reach.
    if caller.kind == "guest":
        if asked:
            # 403 for the same reason a session gets one below: 404 would
            # answer a question this caller is not allowed to ask.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="a guest reads the shared demo book and nothing else",
            )
        # Not `_resolve`: there is no address to resolve, and the guest dir is
        # provisioned at boot (`api.guestbook`), never by a request. So a guest
        # request performs no filesystem side effect at all — no mkdir, no
        # bucket round trip, no directory called into existence by a guess.
        return accounts.guest_paths()

    if caller.kind == "session":
        assert caller.email is not None  # a session always carries one
        if asked and asked != caller.email:
            # Not a 404: saying "that account does not exist here" would answer
            # a question this caller is not allowed to ask in the first place.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="a session may only read its own account",
            )
        return _resolve(caller.email)

    if caller.kind == "token":
        if not asked:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="account is required when authenticating with a token",
            )
        return _resolve(asked)

    # Unreachable, and that is the point: the next kind added to `Caller` fails
    # here loudly instead of inheriting whichever branch happened to be last.
    # That is exactly how "guest" would otherwise have become a token caller.
    raise AssertionError(f"unhandled caller kind: {caller.kind!r}")


Account = Annotated[UserPaths, Depends(account)]


def reporting_currency(paths: UserPaths, override: str | None = None) -> str:
    """The currency to reckon this account's money in.

    `?base=` wins when given, then the account's own preference, then EUR.
    Money is computed *in* the reporting currency (each leg at its own
    trade-date rate) rather than converted afterwards, so this has to be
    settled before the ledger is replayed, not after.
    """
    if override:
        code = override.strip().upper()
        if code not in CURRENCIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"base must be one of {', '.join(CURRENCIES)}",
            )
        return code
    if paths.root == accounts.GUEST_DIR:
        # Same reasoning as `GET /prefs`: one file serves every anonymous
        # visitor, so nothing in it is this reader's preference. EUR is what a
        # brand-new account gets, and `?base=` above is how a guest changes the
        # question for the length of one request.
        return "EUR"
    try:
        stored = json.loads(paths.prefs.read_text()).get("currency")
    except (OSError, json.JSONDecodeError, AttributeError):
        stored = None
    code = str(stored or "EUR").upper()
    return code if code in CURRENCIES else "EUR"


Base = Annotated[
    str | None,
    Query(description="Reporting currency; defaults to the account's preference."),
]


def writer(caller: Who, paths: Account) -> UserPaths:
    """FastAPI dependency: the account a write may land in, or 403.

    A session only. A bearer token names nobody — it says which account it
    wants and any holder can name any account — so a token that could write
    would be one leaked secret away from editing every book on the deployment.
    Reading under that rule is a decision already taken (see `api/security.py`);
    writing under it is not the same bet, and this is where the two part.

    The account itself still resolves through `account()`, so `?account=` keeps
    the one meaning it has for a session: it may repeat the signed-in address
    and nothing else.
    """
    if caller.kind == "guest":
        # Unreachable over HTTP: the one write a guest may reach is
        # `POST /v1/feedback`, which is declared against `Account` rather than
        # this and writes `data/feedback/` rather than a book. Every other write
        # is refused by the gate before this runs. Written anyway, because
        # `Writer` is what the whole write surface is declared against, and "the
        # API never writes the guest directory" must not depend on a list
        # staying right.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="sign in to change anything",
        )
    if caller.kind != "session":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="writes require a signed-in session, not a token",
        )
    # A session reaches `_resolve(email)` -> `paths_for(slug(email))`, and
    # `slug()` appends a sha256 prefix, so no address can produce "_guest".
    # Asserted rather than assumed: this line is what would catch the day that
    # stops being true.
    assert paths.root != accounts.GUEST_DIR, "a session resolved to the guest dir"
    return paths


Writer = Annotated[UserPaths, Depends(writer)]


# ------------------------------------------------------------ chat bursts


def _burst(scope: str):
    """A `Writer` that also spends one event of this account's burst budget.

    The daily free cap is not enough on its own: an account with its own key
    has no cap at all, and every turn fans out into routing, searches and a
    model call — so a runaway client (or a pasted loop) has to hit a wall
    before the providers do. Keyed exactly as the Streamlit composer keys it
    (`chat::<data dir>`), so the two front ends share one budget rather than
    granting each reader twice as much through two doors.

    A dependency, not a check inside the handler: a refusal written in a body
    runs after body validation, and a turn is a streaming response whose status
    is fixed the moment it starts. This answers 429 before either.
    """
    from stocks.web import ratelimit

    def spend(paths: Writer) -> UserPaths:
        key = f"{scope}::{paths.root}"
        if not ratelimit.allow(key):
            wait = ratelimit.retry_after(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                # The key the drawer already renders; the seconds ride in the
                # standard header rather than in a sentence.
                detail="chat.rate_limited",
                headers={"Retry-After": str(max(1, wait))},
            )
        return paths

    return spend


# One question: typed, attached or regenerated — the three ways a turn starts.
ChatTurn = Annotated[UserPaths, Depends(_burst("chat"))]
# A voice note is its own budget. It spends the operator's transcription key
# rather than a turn, and counting it against `chat` would halve the allowance
# of everyone who speaks their questions: the note *and* the message it becomes.
VoiceNote = Annotated[UserPaths, Depends(_burst("voice"))]
