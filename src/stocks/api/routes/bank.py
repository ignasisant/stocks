"""The bank connection, over HTTP: consent, balances, disconnect.

The flow this serves is a round trip through the user's bank, and the two
halves land in different places: the client asks for an authorisation URL,
the browser leaves for the bank, and what comes back is a fresh page load at
the registered redirect URL carrying `?code=&state=`. That return knows
nothing about the session that started it, which is why `state` is matched
against the account's own bank.json (see `stocks.bank.store`) rather than
against anything held in memory.

**A signed-in session only, on every route including the reads.** The rest of
this API lets a bearer token name an account and read it; this one cannot,
because the gate is an allowlist of *people* (`stocks.bank.access`) and a
token names nobody. A token caller therefore gets 403 here rather than the
availability it could not have satisfied anyway.

Failures the bank owns are given their own status codes, because the front end
says something different for each and none of them is a defect:

* **429** — the account's daily fetch budget at the bank is spent. Four reads
  a day is the common ceiling; nothing is wrong and nothing needs reconnecting.
* **409** — the consent is gone (revoked, or cut short by the ASPSP). The
  stored date is backdated so the card offers a reconnect from then on.
* **502** — the bank, or Enable Banking, failed. That one is a failure.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field

from stocks.accounts import UserPaths
from stocks.api import loaders
from stocks.api.deps import Account, Writer
from stocks.api.schemas import (
    BankAccount,
    BankAuth,
    BankChoice,
    BankConnection,
    BankState,
)
from stocks.api.security import Authed
from stocks.bank import access, enablebanking, store
from stocks.bank.enablebanking import BankError, ConsentError, RateLimited

router = APIRouter(prefix="/bank", tags=["bank"])

SessionId = Annotated[str, Path(min_length=1, max_length=128)]


class AuthBody(BaseModel):
    """Which bank to start a consent with."""

    model_config = {"extra": "forbid"}

    country: str = Field(min_length=2, max_length=2, description="ISO country code.")
    name: str = Field(
        min_length=1,
        max_length=200,
        description="ASPSP name, as `/bank/aspsps` gives it.",
    )


class ReturnBody(BaseModel):
    """What the bank sent back on the redirect."""

    model_config = {"extra": "forbid"}

    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=512)


def _email(caller: Authed) -> str:
    """The signed-in address, or 403. A token is refused here by design."""
    if caller.kind != "session" or not caller.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="the bank connection needs a signed-in session, not a token",
        )
    return caller.email


def _allowed(caller: Authed) -> str:
    """The address, having checked it may use the feature at all."""
    email = _email(caller)
    if not access.available(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="bank connections are not available on this account",
        )
    return email


def _origin(request: Request) -> str:
    """The scheme and host the browser is on, behind whatever proxy.

    `request.url` is what the ASGI server saw, which on Cloud Run is plain
    http against an internal host — and an http origin would derive a redirect
    URL Enable Banking refuses to register. The forwarded headers are what the
    load balancer knows and the browser agrees with.
    """
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
    host = host.split(",")[0].strip()
    if not host:
        return str(request.base_url)
    return f"{proto or request.url.scheme}://{host}"


def _refuse(exc: BankError) -> HTTPException:
    """The bank's own failure, as the status the front end branches on."""
    detail = exc.description or exc.code or f"bank error {exc.status}"
    if isinstance(exc, RateLimited):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)
    if isinstance(exc, ConsentError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


def _view(paths: UserPaths, *, email: str, request: Request) -> BankState:
    """Everything the page draws, in one answer."""
    if not access.available(email):
        # Not an error: the page has a written state for this, and a client
        # that cannot see the feature still has to be told so to render it.
        return BankState(available=False, redirect_url="", connections=[])
    return BankState(
        available=True,
        redirect_url=access.redirect_url(_origin(request)),
        connections=[
            BankConnection(
                session_id=conn.get("session_id", ""),
                name=conn.get("aspsp", {}).get("name", ""),
                country=conn.get("aspsp", {}).get("country", ""),
                valid_until=str(conn.get("valid_until") or ""),
                connected_at=str(conn.get("connected_at") or ""),
                expired=store.expired(conn),
                accounts=[_account(acc) for acc in conn.get("accounts", [])],
            )
            for conn in store.connections(paths.bank)
        ],
    )


def _account(acc: dict) -> BankAccount:
    """One account row, with its last read balance already picked.

    Which balance that is belongs to `store`: the Streamlit page shows the
    same one, and an account reading two different figures on two front ends
    would be worse than either figure alone.
    """
    snapshot = acc.get("snapshot") or {}
    money = store.balance_money(snapshot.get("balances") or [])
    return BankAccount(
        uid=str(acc.get("uid", "")),
        name=str(acc.get("name", "") or ""),
        masked_id=str(acc.get("masked_id", "") or ""),
        currency=str(acc.get("currency", "") or ""),
        product=str(acc.get("product", "") or ""),
        balance=None if money is None else money[0],
        balance_currency="" if money is None else money[1],
        fetched_at=snapshot.get("fetched_at") or None,
    )


@router.get("", response_model=BankState, summary="Connected banks and their balances")
def state(caller: Authed, paths: Account, request: Request) -> BankState:
    """What this account has connected, and whether it may connect anything.

    `available: false` is the ordinary answer for most accounts and not a
    failure — see `stocks.bank.access` for why the gate is an allowlist.
    """
    return _view(paths, email=_email(caller), request=request)


@router.get(
    "/aspsps",
    response_model=list[BankChoice],
    summary="Banks that can be connected in a country",
)
def aspsps(
    caller: Authed,
    country: Annotated[str, Query(min_length=2, max_length=2)] = "ES",
) -> list[BankChoice]:
    """Reference data, identical for every account and cached as such."""
    _allowed(caller)
    try:
        banks = loaders.aspsps(country.upper())
    except BankError as exc:
        raise _refuse(exc) from exc
    return [
        BankChoice(
            name=str(bank.get("name", "")),
            country=str(bank.get("country", "") or country.upper()),
            logo=str(bank.get("logo") or "") or None,
        )
        for bank in banks
        if bank.get("name")
    ]


@router.post("/auth", response_model=BankAuth, summary="Start a consent")
def authorise(
    caller: Authed, paths: Writer, body: AuthBody, request: Request
) -> BankAuth:
    """The URL to send the user to, and the `state` that will come back.

    The state is written to bank.json *before* the URL is handed over: the
    redirect can land before this response is even rendered on a slow client,
    and a round trip whose state was never stored is one that gets refused.
    """
    email = _allowed(caller)
    redirect = access.redirect_url(_origin(request))
    if not redirect:
        # https only, and there is nothing the client can do about it — the
        # page says so rather than offering a button that fails at the bank.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no https redirect URL is available on this host",
        )
    try:
        url, state_token = enablebanking.start_auth(
            name=body.name, country=body.country.upper(), redirect_url=redirect
        )
    except BankError as exc:
        raise _refuse(exc) from exc
    store.add_pending(
        paths.bank,
        state=state_token,
        email=email,
        aspsp={"name": body.name, "country": body.country.upper()},
    )
    return BankAuth(url=url, bank=body.name, state=state_token)


@router.post("/session", response_model=BankState, summary="Finish a consent")
def finish(
    caller: Authed, paths: Writer, body: ReturnBody, request: Request
) -> BankState:
    """Exchange the bank's code for a session, and store what it consented to.

    A `state` this account did not start is a 404 and the code is dropped: it
    may well be real, but nothing proves this account began the round trip,
    and attaching somebody else's consent to this book is the one outcome
    worth refusing a valid code over.
    """
    email = _allowed(caller)
    pending = store.take_pending(paths.bank, body.state, email)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="that authorisation could not be matched to this account",
        )
    try:
        session = enablebanking.create_session(body.code)
    except BankError as exc:
        raise _refuse(exc) from exc
    store.add_connection(paths.bank, session, aspsp=pending["aspsp"])
    return _view(paths, email=email, request=request)


@router.post(
    "/connections/{session_id}/refresh",
    response_model=BankState,
    summary="Read the balances again",
)
def refresh(
    caller: Authed, paths: Writer, session_id: SessionId, request: Request
) -> BankState:
    """Fetch every account on one connection, on demand.

    Never on a page load: the budget is the bank's and it is small, so the
    stored snapshot is what the page draws and this is the button behind it.
    """
    email = _allowed(caller)
    conn = store.find(paths.bank, session_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown connection"
        )
    try:
        for acc in conn.get("accounts", []):
            store.record_fetch(
                paths.bank,
                session_id,
                acc["uid"],
                balances=enablebanking.balances(acc["uid"]),
            )
    except ConsentError as exc:
        # Dead before its stated date. Recorded, so the card offers a
        # reconnect from now on instead of a button that cannot work.
        store.mark_expired(paths.bank, session_id)
        raise _refuse(exc) from exc
    except BankError as exc:
        raise _refuse(exc) from exc
    return _view(paths, email=email, request=request)


@router.delete(
    "/connections/{session_id}",
    response_model=BankState,
    summary="Disconnect a bank",
)
def disconnect(
    caller: Authed, paths: Writer, session_id: SessionId, request: Request
) -> BankState:
    """Close the session at the bank and forget it here.

    The local removal happens either way: a session left open at the bank
    expires on its own, and the user asked for it gone *here* — an API that
    failed at the far end and kept the card on screen would be answering a
    different question than the one asked.
    """
    email = _allowed(caller)
    if store.find(paths.bank, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown connection"
        )
    try:
        enablebanking.delete_session(session_id)
    except BankError:
        pass
    store.remove_connection(paths.bank, session_id)
    return _view(paths, email=email, request=request)
