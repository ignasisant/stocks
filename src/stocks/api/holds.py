"""The route a CPU hold calls: this process, through its own front end.

The mechanism — what is held, for how long, and the token — is
`stocks.cpu_hold`; this is its one HTTP adapter, mounted outside the gate.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Response, status

from stocks import cpu_hold

router = APIRouter(include_in_schema=False)


@router.post("/hold", name="cpu_hold", status_code=status.HTTP_204_NO_CONTENT)
async def hold(x_hold: str = Header(default="")) -> Response:
    """Stay open while a refresh runs — this process calling itself. 404 for
    anything but its own token."""
    if not cpu_hold.mine(x_hold):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await cpu_hold.settled()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
