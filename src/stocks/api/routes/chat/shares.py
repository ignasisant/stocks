"""A chat answer or a list of tickers shared by link: publish it, take it
down, read it.

Publishing an answer, listing and taking down are the sharer's, under `/chat`
like everything else of their chat. Reading is anybody's — the link is sent to
people with no account — so it lives outside `/chat`, the one prefix a guest
is shut out of whole, at `GET /shares/{share_id}` (`api/guest.py`). A list has
no answer behind it, so it is published at `POST /shares` and followed at
`POST /shares/{share_id}/follow`, both a session's. The store and the cut are
`web/shares.py` and `chat/share_mask.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

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
    """One shared answer or list as its link shows it. `id` and `created` are
    "" on a preview; `by` is the sharer's first name, "" on a link made before
    it was kept; `mine` says the reader is the account that shared it. A
    list (`kind` "watchlist") has `title` and `tickers` and no question."""

    id: str = ""
    kind: str = "answer"
    question: str = ""
    content: str = ""
    title: str = ""
    tickers: list[str] = []
    web: list[Source] = []
    skills: list[str] = []
    activities: list[ActivityOut] = []
    masked: bool
    by: str = ""
    lang: str = ""
    created: str = ""
    mine: bool = False


def _out(share: dict, mine: bool) -> SharedAnswer:
    from stocks.web import shares

    return SharedAnswer(
        id=str(share.get("id") or ""),
        kind=shares.kind_of(share),
        title=str(share.get("title") or ""),
        tickers=[str(t) for t in share.get("tickers") or []],
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


class ListedShare(BaseModel):
    """One link the account has up, as Profile lists it. `question` is the
    stored one, masked when the link is; a list's is its title or symbols."""

    id: str
    kind: str = "answer"
    answer_id: str
    question: str
    masked: bool
    created: str


@router.get(
    "/shares",
    response_model=list[ListedShare],
    summary="List the answers shared by link",
)
def listed(paths: Account) -> list[ListedShare]:
    """Every link this account has up, newest first."""
    from stocks.web import shares

    return [ListedShare(**row) for row in shares.listed(paths)]


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


class ListRequest(BaseModel):
    """A list to publish: the symbols in the sharer's order and the name it
    goes under. `preview` answers what the link would show and publishes
    nothing."""

    model_config = {"extra": "forbid"}

    tickers: list[str] = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    preview: bool = False


@shared.post("", response_model=SharedAnswer, summary="Share a list of tickers")
def share_list(body: ListRequest, paths: ShareWrite, request: Request) -> SharedAnswer:
    """Publish a list at `/?share=<id>`: the symbols and the title, nothing
    else of the watchlist they came from. The same list under the same title
    again is the same link. 422 when none of them is a symbol."""
    from stocks.web import shares

    by = shares.sharer(session.claims(request.cookies))
    if body.preview:
        cut = shares.list_snapshot(body.tickers, body.title)
        found = {**cut, "by": by} if cut["tickers"] else None
    else:
        lang = str(_prefs(paths).get("language") or "")
        found = shares.create_list(paths, body.tickers, body.title, lang, by)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="no symbol in the list",
        )
    return _out(found, mine=True)


class Followed(BaseModel):
    """The symbols following the list added; the rest were already there."""

    added: list[str]


@shared.post(
    "/{share_id}/follow",
    response_model=Followed,
    summary="Follow a shared list",
)
def follow(share_id: str, paths: Writer) -> Followed:
    """Put every symbol of a shared list on the reader's watchlist, grouped
    under its title. 404 for a link that is gone or is not a list."""
    from stocks.web import shares

    found = shares.load(share_id)
    if found is None or shares.kind_of(found) != "watchlist":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no list {share_id}"
        )
    return Followed(added=shares.follow(paths, found))
