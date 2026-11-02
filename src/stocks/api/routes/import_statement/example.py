"""The example statement shipped beside the app."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from stocks.api.routes.import_statement.upload import _platform

router = APIRouter(prefix="/import", tags=["import"])


# Shipped beside the app (`web/assets/`), because a reader with no statement to
# hand has nothing to import and therefore nothing to look at.

_ASSETS = Path(__file__).resolve().parents[3] / "web" / "assets"

_SAMPLE_MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get(
    "/sample",
    response_class=Response,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "The example statement, as a file.",
        }
    },
    summary="An example statement",
)
def sample(
    platform: Annotated[
        str,
        Query(
            description=(
                "Platform key. `has_sample` on `/import/platforms` says which "
                "ship one; today only Revolut does."
            )
        ),
    ],
) -> Response:
    """The shipped example export, byte for byte.

    These bytes go back through `/import/preview` and `/import/commit` like any
    other upload — base64 in the JSON body, the same parse, the same
    validation, the same last-import record and the same undo. That is the
    whole point of shipping a real statement rather than a fabricated ledger: a
    separate "load the demo" route would be the one that drifts from the real
    one, and the reader would learn a flow they will never use again.

    404 both where the platform ships no example and where a trimmed deploy
    left the file out — the page says nothing rather than failing in that
    state, and a client should be able to do the same.

    When to offer it is the client's to get right, and the page's rule is
    worth copying: only to an account with nothing to lose. Committing someone
    else's trades into a real book is a trap rather than a tour, and nothing
    here can tell the two apart. For a reader who has not decided to import
    anything yet, `POST /v1/portfolio/demo` is the other answer.
    """
    chosen = _platform(platform)
    if not chosen.sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{chosen.label} ships no example statement",
        )
    path = _ASSETS / chosen.sample
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this deployment shipped without the example statement",
        )
    return Response(
        content=path.read_bytes(),
        media_type=_SAMPLE_MEDIA.get(
            path.suffix.lstrip(".").lower(), "application/octet-stream"
        ),
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )
