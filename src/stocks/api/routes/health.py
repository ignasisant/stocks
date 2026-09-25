"""Liveness, and nothing else.

Unauthenticated on purpose: this is what an uptime check and a container probe
call, and they hold no token. It therefore says nothing an anonymous caller
should not hear — no account, no configuration, no dependency status. The app's
own probes (`/livez`, `/healthz`) are separate and answer for the whole server;
this one answers for the API mount specifically, which is how a deploy tells
"the API is not wired up" apart from "the API is refusing you".
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

from stocks.api.schemas import Health

router = APIRouter(tags=["health"])

_BOOTED = datetime.now(UTC).isoformat(timespec="seconds")


def _version() -> str:
    try:
        return version("stocks")
    except PackageNotFoundError:  # pragma: no cover — an editable install always has it
        return "unknown"


@router.get("/health", response_model=Health, summary="Liveness of the API mount")
def health() -> Health:
    return Health(version=_version(), booted=_BOOTED)
