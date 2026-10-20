"""Erasing an account, and taking its data away — the two promises the legal
page makes by name.

`web/auth.delete_account` is the whole of it — bucket copies first, then disk,
refusing the owner and guest directories — and it is deliberately not reopened
here. What this route adds is the part that belongs to a front end: an
irreversible action has to be *named* by the caller who wants it, not merely
requested, which is the same bar `DELETE /portfolio/transactions` sets for
emptying a ledger.

Deleting the data also ends every session of the address (`session.end_all`),
so a copy of the cookie cannot re-provision an empty account. The browser's
own cookie is still cleared by `/auth/logout`, where a client sends the reader
next.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from stocks import obs, session
from stocks.api.deps import Writer
from stocks.api.security import Authed

router = APIRouter(tags=["account"])


class Erase(BaseModel):
    model_config = {"extra": "forbid"}

    confirm: str = Field(
        description=(
            "The signed-in address, typed back. This erases the watchlist, the "
            "imported transactions, the preferences and the chat history, on "
            "disk and in the bucket, with no undo — so the request has to name "
            "the account it is erasing."
        )
    )


class Erased(BaseModel):
    ok: bool = True
    # What a client does next. Not a redirect: this response is JSON to a
    # fetch, and the sign-out has to be a real navigation for the browser to
    # accept the cleared cookie.
    sign_out: str = session.LOGOUT_PATH


@router.delete(
    "/account",
    response_model=Erased,
    summary="Erase this account's data",
)
def erase(caller: Authed, account: Writer, body: Erase) -> Erased:
    """Delete everything this account has here. There is no undo.

    A session only, like every write — and here the rule earns itself twice
    over: a bearer token names any account it likes, so a token that could call
    this would be one leaked secret away from erasing every book on the
    deployment.

    Backup snapshots are immutable history and expire on their own schedule.
    The legal page says so, and this route does not pretend otherwise.
    """
    from stocks.web import auth

    if body.confirm.strip().lower() != (caller.email or "").lower():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="confirm must be the signed-in address, exactly",
        )
    try:
        auth.delete_account(account)
    except ValueError as exc:
        # The owner or the shared guest directory. Neither is an account and
        # neither is this route's to remove.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001 — never half-delete silently
        obs.warn("account.delete_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="deletion failed and nothing was removed",
        ) from exc
    try:
        # The next request with this cookie would re-provision an empty
        # account; every copy of it, on any device, has to stop here.
        session.end_all(caller.email or "")
    except Exception as exc:  # noqa: BLE001 — the data is already gone
        obs.warn("account.revoke_failed", error_type=type(exc).__name__)
    obs.event("account.deleted", via="api")
    return Erased()


@router.get(
    "/account/export",
    response_class=Response,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Everything the account holds, one file each.",
        }
    },
    summary="Download this account's data",
)
def export(account: Writer) -> Response:
    """What this account holds, as one zip to keep or take elsewhere: the
    ledger as CSV in the reporting currency, the watchlist, the settings
    without their provider keys, the conversations, the memories and the
    decision journal (`web.exports.account_bundle`).

    A session only, like `erase`, and for the same reason: a bearer token
    names any account it likes, so a token that could download one could
    download every book on the deployment.
    """
    from stocks.api.deps import reporting_currency
    from stocks.web import exports

    body = exports.account_bundle(account, base=reporting_currency(account))
    obs.event("account.exported")
    return Response(
        content=body,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="aguait-account-{date.today():%Y-%m-%d}.zip"'
            )
        },
    )
