"""The design tokens, as data.

`web/ds.py` is the single source of truth for every colour, radius and type
step in this app, and it already renders them two ways: as `--ag-*` custom
properties for CSS, and as Python constants. The React shell needs the third
rendering — the same map as JSON — so its JavaScript picks chart colours from
the same place the Python does.

Open, like `/health`: these are shipped constants, and the landing already
publishes every one of them inline in a public HTML document.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/design", tags=["design"])


class Tokens(BaseModel):
    tokens: dict[str, str] = Field(
        description=(
            "Token name (without the `--ag-` prefix) to value. The CSS custom "
            "properties carry the same names, so `--ag-border` and "
            "`tokens.border` are the same thing."
        )
    )


@router.get("/tokens", response_model=Tokens, summary="Design-system tokens")
def design_tokens() -> Tokens:
    from stocks.web.ds import tokens

    return Tokens(tokens=tokens())
