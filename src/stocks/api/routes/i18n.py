"""Translated strings, for a front end that does its own lookups.

The same fragments the pages read (`web/locales/<lang>/*.json`), merged and
served flat. English underneath every response, exactly as `i18n.translate`
layers it: a key the translation is missing falls back to the source language
rather than rendering as a dotted key on screen.

Open, like `/health`. These are shipped files, identical for every visitor, and
the sign-in screen needs them before anyone is signed in.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/i18n", tags=["i18n"])


class Catalog(BaseModel):
    lang: str
    strings: dict[str, str] = Field(
        description=(
            "Dotted key to string, e.g. `ticker.price`. Values may carry "
            "`{placeholder}` slots the client fills in."
        )
    )


@router.get("/{lang}", response_model=Catalog, summary="One language's strings")
def catalog(
    lang: Annotated[str, Path(min_length=2, max_length=8)],
    prefix: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated key prefixes to return, e.g. `ticker,common`. "
                "Omit for the whole catalog (~2300 keys)."
            )
        ),
    ] = None,
) -> Catalog:
    from stocks.web.i18n import DEFAULT_LANG, supported
    from stocks.web.i18n import catalog as strings_for

    code = supported(lang)
    if code is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no catalog for {lang!r}"
        )
    # Source language underneath, mirroring i18n.translate's per-key fallback:
    # an untranslated key reads in English instead of showing as `ticker.price`.
    strings = {**strings_for(DEFAULT_LANG), **strings_for(code)}
    if prefix:
        wanted = tuple(f"{p.strip()}." for p in prefix.split(",") if p.strip())
        if wanted:
            strings = {k: v for k, v in strings.items() if k.startswith(wanted)}
    return Catalog(lang=code, strings=strings)
