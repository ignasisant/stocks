"""A chat answer shared by link: publish it, take it down, read it.

Publishing and taking down are the sharer's, under `/chat` like every other
write on their chat. Reading is anybody's — the link is sent to people with
no account — so it lives outside `/chat`, the one prefix a guest is shut out
of whole, at `GET /shares/{share_id}` (`api/guest.py`). The store and the cut
are `web/shares.py` and `chat/share_mask.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from stocks import session
from stocks.api.deps import Account, ShareWrite, Writer
from stocks.api.routes.chat.messages import ActivityOut, Source
from stocks.api.routes.chat.preferences import _prefs

router = APIRouter(prefix="/chat", tags=["chat"])
shared = APIRouter(prefix="/shares", tags=["chat"])


class ShareRequest(BaseModel):
    """`masked` hides the sharer's amounts (the default the sheet offers);
    `preview` answers what the link would show and publishes nothing."""

    model_config = {"extra": "forbid"}

    masked: bool = True
    preview: bool = False


class SharedAnswer(BaseModel):
    """One shared answer as its link shows it. `id` and `created` are "" on a
    preview; `by` is the sharer's first name, "" on a link made before it was
    kept; `mine` says the reader is the account that shared it."""

    id: str = ""
    question: str
    content: str
    web: list[Source] = []
    skills: list[str] = []
    activities: list[ActivityOut] = []
    masked: bool
    by: str = ""
    lang: str = ""
    created: str = ""
    mine: bool = False


def _out(share: dict, mine: bool) -> SharedAnswer:
    return SharedAnswer(
        id=str(share.get("id") or ""),
        question=str(share.get("question") or ""),
        content=str(share.get("content") or ""),
        web=[Source(**w) for w in share.get("web") or [] if isinstance(w, dict)],
        skills=[str(s) for s in share.get("skills") or []],
        activities=[ActivityOut(**a) for a in share.get("activities") or []
                    if isinstance(a, dict)],
        masked=share.get("masked") is True,
        by=str(share.get("by") or ""),
        lang=str(share.get("lang") or ""),
        created=str(share.get("created") or ""),
        mine=mine,
    )


@router.post(
    "/turns/{tid}/share",
    response_model=SharedAnswer,
    summary="Share an answer by link",
)
def share(
    tid: str, body: ShareRequest, paths: ShareWrite, request: Request
) -> SharedAnswer:
    """Publish one answer at `/?share=<id>`, or with `preview` show what that
    page would hold. The same answer shared the same way again is the same
    link. 404 for an id no thread holds."""
    from stocks.web import shares

    by = shares.sharer(session.claims(request.cookies))
    if body.preview:
        found = shares.preview(paths, tid, body.masked, by)
    else:
        lang = str(_prefs(paths).get("language") or "")
        found = shares.create(paths, tid, body.masked, lang, by)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no answer {tid}"
        )
    return _out(found, mine=True)


@router.delete(
    "/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Stop sharing an answer",
)
def unshare(share_id: str, paths: Writer) -> None:
    """Take down the link, and every other link its answer went out under.
    404 for a share that is gone or is not this account's: which of the two
    is not the caller's to learn."""
    from stocks.web import shares

    if not shares.revoke(paths, share_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no share {share_id}"
        )


@shared.get(
    "/{share_id}",
    response_model=SharedAnswer,
    summary="Read a shared answer",
)
def read(share_id: str, paths: Account) -> SharedAnswer:
    """The answer a link names, to anybody who has the link, guests included.
    404 once it is taken down."""
    from stocks.web import shares

    found = shares.load(share_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no share {share_id}"
        )
    return _out(found, mine=found.get("owner") == shares.owner_of(paths))
