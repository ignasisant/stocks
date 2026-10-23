"""One error shape for every 4xx and 5xx this API answers.

```json
{"error": {"code": "not_found", "message": "unknown account"},
 "detail": "unknown account", "reason": "rate_limited"}
```

`error` is the contract a third party codes against: `code` is a stable,
machine-readable slug (one per status family, never a sentence) and `message`
is for a human or a log. `detail` (and `reason`, when an upstream refusal has
one) stay at the top level because the shell's fetch helpers read exactly
those (`shell/api.ts`, `chat/api.ts`); they are the legacy spelling of the
same facts and are not going anywhere until a `/v2`.

Installed as exception handlers on the app, so a route keeps raising
`HTTPException` and nothing per route has to remember the envelope. That also
covers the answers no route raises: an unknown path, a wrong method, a body
that fails validation, an unhandled bug.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

#: status -> stable code. Anything not listed falls back to its family.
CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "unavailable",
}


def code_for(status: int) -> str:
    if status in CODES:
        return CODES[status]
    return "client_error" if status < 500 else "server_error"


def body(
    status: int, message: str, *, detail: Any = None, reason: str | None = None
) -> dict[str, Any]:
    """The envelope. `detail` defaults to the message, as FastAPI's own does."""
    out: dict[str, Any] = {
        "error": {"code": code_for(status), "message": message},
        "detail": message if detail is None else detail,
    }
    if reason:
        out["reason"] = reason
    return out


def respond(
    status: int,
    message: str,
    *,
    detail: Any = None,
    reason: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        body(status, message, detail=detail, reason=reason),
        status_code=status,
        headers=headers,
    )


def _http(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return respond(
        exc.status_code, message, detail=exc.detail, headers=exc.headers
    )


def _invalid(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)
    # `detail` keeps FastAPI's list of {loc, msg, type}: it is the useful part
    # of a 422, and the message is the first problem in a line.
    problems = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
    first = problems[0] if problems else {}
    where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
    message = (
        f"{where}: {first['msg']}" if where and "msg" in first else "invalid request"
    )
    return respond(422, message, detail=problems)


def _crashed(request: Request, exc: Exception) -> JSONResponse:
    # Never the exception text: it can carry a path or a query.
    return respond(500, "internal error")


def install(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(RequestValidationError, _invalid)
    app.add_exception_handler(Exception, _crashed)
