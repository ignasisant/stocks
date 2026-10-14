"""Errors the browser hit, filed into the production log.

A JavaScript error never reaches the server on its own: an exception in a
render, a promise nobody awaited, a handler that threw. Before this route the
only trace was a reader who bothered to write in, so a screen that went blank
for everybody on one phone could go unseen for a week. The shell
(`shell/errors.ts`) posts each one here and this route writes it as one
`client.error` event, next to whatever the server logged for the same account.

Fire and forget, like the import's `/client-failure`: a 204 whatever happens,
because a reader whose page just broke must not also see a failed report.

Open to guests, as feedback is, because a guest's screen breaks the same way.
Tokens are refused: they are API clients with no browser behind them. Every
caller is metered per client address, quietly — a page stuck in a render loop
throws hundreds of times a second, and one line says as much as a thousand.

What is kept is the error, not the reader's data. The message is masked (an
email, a long number) and URLs lose their query, so `?account=` or a search
term never lands in the log; the stack keeps its `file:line:col`, which is
the bundle's coordinates and nobody's business.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.api.security import Who
from stocks.web import ratelimit

router = APIRouter(tags=["client"])

# Per client address and hour. Generous enough for a bad afternoon on one
# screen (the shell itself sends at most a handful per page load), low enough
# that a loop or a script fills nothing.
MAX_PER_HOUR = 30
WINDOW_S = 3600

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# Four digits or more, or any decimal: an amount, a quantity, an account
# number. "Minified React error #185" keeps its code.
_NUMBER = re.compile(r"\d+[.,]\d+|\d{4,}")
_QUERY = re.compile(r"(https?://[^\s?#)]+|/[\w./-]+)[?#][^\s):]*")


def scrub(text: str) -> str:
    """Mask what could be a reader's data in an error message or stack."""
    text = _QUERY.sub(lambda m: m.group(1), text)
    text = _EMAIL.sub("<email>", text)
    return text


def scrub_message(text: str) -> str:
    """`scrub`, plus numbers — a message carries values, a stack only offsets."""
    return _NUMBER.sub(lambda m: re.sub(r"\d", "9", m.group(0)), scrub(text))


class ClientError(BaseModel):
    model_config = {"extra": "forbid"}

    kind: Literal["error", "rejection", "render"] = "error"
    name: str = Field(default="Error", max_length=64)
    message: str = Field(default="", max_length=500)
    # The screen, as feedback names it: `ticker?symbol=AAPL&tab=fees`.
    where: str = Field(default="", max_length=120)
    # The top frame, `file:line:col` in the bundle.
    src: str = Field(default="", max_length=300)
    stack: str = Field(default="", max_length=4000)
    # React's component stack, for an error a render threw.
    component: str = Field(default="", max_length=2000)


def admitted(request: Request, who: Who) -> bool:
    """Whether this report is logged, or a refusal — as a dependency.

    A dependency so a token is refused before its body is validated (a 403,
    not a 422 about a field it was never going to be allowed to send), and so a
    flood is metered before anything is parsed. Over the limit is `False`, not
    a 429: the page that sent it cannot do anything useful with one.
    """
    if who.kind == "token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="browser errors come from a browser session, not a token",
        )
    key = f"client_error::{ratelimit.client_ip(request)}"
    if ratelimit.allow(key, max_events=MAX_PER_HOUR, window_s=WINDOW_S):
        return True
    obs.warn_once("client.error_throttled", key)
    return False


@router.post(
    "/client-error",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="An error the browser hit",
)
def client_error(
    body: ClientError,
    logged: Annotated[bool, Depends(admitted)],
    request: Request,
) -> None:
    """Log one browser error as `client.error`. Always 204 to a browser."""
    if not logged:
        return
    stack = "\n".join(
        part for part in (scrub(body.stack), scrub(body.component)) if part
    )
    obs.warn(
        "client.error",
        # `name` and `message` are LogRecord's own attributes, which `extra`
        # may not overwrite: the exception's are logged as `exc` and `error`.
        kind=body.kind,
        exc=body.name,
        error=scrub_message(body.message),
        where=scrub(body.where),
        src=scrub(body.src),
        ua=_browser(request.headers.get("user-agent", "")),
        stack_trace=stack or None,
    )


def _browser(ua: str) -> str:
    """Family and platform, not the full string: enough to group by."""
    family = next(
        (name for token, name in (
            ("Edg/", "edge"), ("OPR/", "opera"), ("SamsungBrowser", "samsung"),
            ("Firefox/", "firefox"), ("CriOS", "chrome"), ("Chrome/", "chrome"),
            ("Safari/", "safari"),
        ) if token in ua),
        "other",
    )
    platform = next(
        (name for token, name in (
            ("iPhone", "ios"), ("iPad", "ios"), ("Android", "android"),
            ("Mac OS X", "mac"), ("Windows", "windows"), ("Linux", "linux"),
        ) if token in ua),
        "other",
    )
    return f"{family}/{platform}"
