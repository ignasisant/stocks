"""Translated strings, for a front end that does its own lookups.

The same fragments the pages read (`web/locales/<lang>/*.json`), merged and
served flat. English underneath every response, exactly as `i18n.translate`
layers it: a key the translation is missing falls back to the source language
rather than rendering as a dotted key on screen.

Open, like `/health`. These are shipped files, identical for every visitor, and
the sign-in screen needs them before anyone is signed in.

A language nobody ships (a browser set to Italian) gets English, with `lang`
saying so. The front end asks for whatever the browser reports, and a 404 there
left it with no strings at all — every label rendered as its dotted key.

`async` on purpose, the one route here that is: it reads memoized files and
never blocks, and every label in the app waits on it. A sync route queues in
the threadpool behind whatever Yahoo is being slow about, and the page draws
`common.waiting_for` until a thread frees up.

Cacheable, which the rest of the API is not. A catalog is the same bytes for
everyone until a deploy edits a string, so it carries an `ETag` and is asked
for again with `If-None-Match` — a 304 and no body on every visit after the
first. Asked for under the current stamp (`?v=`, which the document hands the
front end — `web.i18n.version`), it is immutable for a year: a repeat visit
reads it from the browser's cache and sends nothing at all.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
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


IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "public, no-cache"


def etag(version: str, code: str, prefix: str | None) -> str:
    """The entity tag for one answer: the stamp, the language, the filter."""
    key = f"{version}|{code}|{prefix or ''}".encode()
    return f'"{hashlib.blake2b(key, digest_size=8).hexdigest()}"'


def _matches(if_none_match: str, tag: str) -> bool:
    """Whether the client's `If-None-Match` names `tag` (weak or strong)."""
    offered = (t.strip() for t in if_none_match.split(","))
    return any(t.removeprefix("W/") == tag for t in offered)


@router.get("/{lang}", response_model=Catalog, summary="One language's strings")
async def catalog(
    request: Request,
    response: Response,
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
    v: Annotated[
        str | None,
        Query(
            max_length=32,
            description=(
                "The catalog stamp the document handed out. When it is the "
                "current one the answer is immutable for a year; otherwise it "
                "is answered with an ETag and revalidated on every visit."
            ),
        ),
    ] = None,
) -> Catalog | Response:
    from stocks.web.i18n import DEFAULT_LANG, supported, version
    from stocks.web.i18n import catalog as strings_for

    code = supported(lang) or DEFAULT_LANG
    current = version()
    tag = etag(current, code, prefix)
    lease = IMMUTABLE if v == current else REVALIDATE
    if _matches(request.headers.get("if-none-match", ""), tag):
        return Response(
            status_code=304, headers={"ETag": tag, "Cache-Control": lease}
        )
    response.headers["ETag"] = tag
    response.headers["Cache-Control"] = lease
    # Source language underneath, mirroring i18n.translate's per-key fallback:
    # an untranslated key reads in English instead of showing as `ticker.price`.
    strings = {**strings_for(DEFAULT_LANG), **strings_for(code)}
    if prefix:
        wanted = tuple(f"{p.strip()}." for p in prefix.split(",") if p.strip())
        if wanted:
            strings = {k: s for k, s in strings.items() if k.startswith(wanted)}
    return Catalog(lang=code, strings=strings)
