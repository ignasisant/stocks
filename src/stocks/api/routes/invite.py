"""The account's invite link: the app's address with a source token that
names this account's code, so a signup it brings is counted for it
(`accounts.invite_code`). No reward rides on it; it is a link and a count.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from stocks import accounts, obs
from stocks.api.deps import Writer

router = APIRouter(tags=["account"])


class Invite(BaseModel):
    code: str
    #: Site-relative; the client puts its own origin in front.
    path: str


@router.post("/invite", response_model=Invite, summary="This account's invite link")
def invite(paths: Writer) -> Invite:
    """The link to send, made on the first call and the same on every one
    after. A POST because the first call writes the code."""
    code = accounts.invite_code(paths)
    obs.event("invite.asked", code=code)
    return Invite(code=code, path=f"/?src={accounts.INVITE_PREFIX}{code}")
