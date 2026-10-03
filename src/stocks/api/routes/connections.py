"""The apps a person let into their account through the MCP connector.

Profile lists them and offers "Revoke"; this is the read and the revoke. Both
are a session's only, like a write: the list names which assistants can read
the book, and a bearer token — which can name any account — has no business
asking that about somebody else, let alone ending it.

What a connection is lives in `connector/store.py`; nothing here sees a token
or a hash, only the row Profile draws.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field

from stocks.api.deps import Writer
from stocks.api.security import Authed

router = APIRouter(tags=["connections"])


class Connection(BaseModel):
    id: str
    client_name: str = Field(description="What the app called itself.")
    verified: bool = Field(
        description=(
            "True when the app identified itself by a metadata document at its "
            "own https address; false for a self-registered name, which anyone "
            "can choose."
        )
    )
    redirect_host: str = Field(description="Where the approval was sent back to.")
    created: datetime
    used: datetime = Field(description="The last time it was issued a token.")
    expires: datetime = Field(description="When it lapses unless used again.")


class Connections(BaseModel):
    url: str | None = Field(
        description=(
            "The MCP server address to add to Claude; null while the "
            "connector is not running on this deployment."
        )
    )
    connections: list[Connection]


def _when(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


@router.get("/connections", response_model=Connections,
            summary="Apps connected to this account")
def connections(caller: Authed, _account: Writer) -> Connections:
    from stocks.connector import store
    from stocks.connector.server import door

    assert caller.email is not None  # `Writer` let only a session through
    rows = store.ledger().grants_for(caller.email)
    return Connections(
        url=door.url,
        connections=[
            Connection(
                id=r["id"],
                client_name=r["client_name"] or r["redirect_host"],
                verified=r["client_kind"] == "cimd",
                redirect_host=r["redirect_host"],
                created=_when(r["created"]),
                used=_when(r["used"]),
                expires=_when(r["expires"]),
            )
            for r in rows
        ],
    )


@router.delete("/connections/{grant}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Revoke one connected app")
def revoke(
    caller: Authed,
    _account: Writer,
    grant: str = Path(max_length=64, pattern=r"^g_[0-9a-f]+$"),
) -> None:
    """End one connection now: its tokens stop working on their next call.

    404 for a connection that is not this account's, gone or never was — the
    same answer for all three, so the id of somebody else's connection is
    not something this can confirm.
    """
    from stocks.connector import store

    assert caller.email is not None
    if not store.ledger().revoke(grant, email=caller.email):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="no such connection")
