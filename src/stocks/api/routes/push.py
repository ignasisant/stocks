"""This device's Web Push subscription, and the heartbeat that holds pushes back.

The browser does the subscribing (`Notification.requestPermission` +
`pushManager.subscribe`) with the key `GET /push` hands it; these routes keep
the result (`notify/webpush.py`). A finished answer pushes to every device
kept here — unless `POST /push/presence` says the app is on screen somewhere.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from stocks.api.deps import Account, Writer
from stocks.notify import webpush

router = APIRouter(prefix="/push", tags=["notify"])


class Push(BaseModel):
    configured: bool = Field(
        description="Whether this deployment can push at all. False is not an error."
    )
    key: str | None = Field(
        default=None,
        description="The VAPID public key, base64url: the applicationServerKey.",
    )
    subscribed: bool = Field(
        default=False, description="Whether `endpoint` (when given) is kept here."
    )


class Keys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class Subscription(BaseModel):
    """`PushSubscription.toJSON()`, plus the language to write in."""

    endpoint: str = Field(max_length=1000)
    keys: Keys
    lang: Literal["en", "es"] = "en"


class Endpoint(BaseModel):
    endpoint: str = Field(max_length=1000)


class Presence(BaseModel):
    client: str = Field(min_length=1, max_length=64)
    visible: bool


def _subject(request: Request) -> str:
    """Who sends: the VAPID `sub`, an https origin push services can reach."""
    from stocks.web.server import public_origin

    origin = public_origin() or request.headers.get("origin", "")
    return origin if origin.startswith("https://") else "mailto:push@topstocks.invalid"


@router.get("", response_model=Push)
def state(paths: Account, endpoint: str = "") -> Push:
    key = webpush.public_key()
    return Push(
        configured=key is not None,
        key=key,
        subscribed=bool(endpoint) and webpush.subscribed(paths.push, endpoint),
    )


@router.post("/subscription", response_model=Push)
def subscribe(body: Subscription, paths: Writer, request: Request) -> Push:
    if not webpush.configured():
        raise HTTPException(status.HTTP_409_CONFLICT, "Push is not configured here.")
    if not webpush.subscribe(
        paths.push, endpoint=body.endpoint, p256dh=body.keys.p256dh,
        auth=body.keys.auth, origin=_subject(request), lang=body.lang,
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Not a usable subscription."
        )
    return Push(configured=True, key=webpush.public_key(), subscribed=True)


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(body: Endpoint, paths: Writer) -> None:
    webpush.unsubscribe(paths.push, body.endpoint)


@router.post("/test", status_code=status.HTTP_204_NO_CONTENT)
def test(body: Endpoint, paths: Writer, request: Request) -> None:
    """A notification to this device now: the Profile's "Send a test"."""
    from stocks.web.i18n import translate

    row = webpush.row(paths.push, body.endpoint)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This device is not subscribed.")
    lang = row.get("lang") or "en"
    sent = webpush.send(paths.push, row, {
        "title": translate("notify.push_test_title", lang),
        "body": translate("notify.push_test_body", lang),
        "url": "/profile?tab=notify",
        "tag": "test",
    })
    if not 200 <= sent < 300:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"The push service said {sent}.")


@router.post("/presence", status_code=status.HTTP_204_NO_CONTENT)
def presence(body: Presence, paths: Writer) -> None:
    webpush.seen(str(paths.chat), body.client, body.visible)
