"""Linking a Telegram chat, and the two things you do with it afterwards.

The Streamlit Profile page owns a four-step dance — press Connect, get a
one-time code, press Start in Telegram, wait for the chat id to come back — and
none of it is Streamlit's: the code is a secret in prefs.json, the return trip
is the Actions chat job writing `telegram_chat_id` into the bucket, and the
waiting is polling a file. All of that is exactly as true for a front end that
is not Streamlit, which is why it is here rather than rebuilt beside it.

The code is session-scoped and random. That matters: an attacker sending
"/start <guess>" from their own Telegram can only ever match a code somebody
else's session generated, and never one derived from an address.
"""

from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stocks import accounts, storage
from stocks.api.deps import Account, Writer
from stocks.notify import telegram

router = APIRouter(prefix="/notify/telegram", tags=["notify"])

# How long a pending code stays matchable. The Streamlit page uses the same ten
# minutes, and the code is retired server-side when it lapses rather than left
# sitting in prefs for the next person who guesses it.
LINK_TTL = 600


class Link(BaseModel):
    """Where to send the reader, and what to type if the button is missing."""

    code: str
    deep_link: str
    bot: str = Field(description="The bot's @username, for the manual fallback.")
    expires_in: int = Field(description="Seconds the code stays matchable.")


class Telegram(BaseModel):
    configured: bool = Field(
        description="Whether this deployment has a bot at all. False is not an error."
    )
    linked: bool
    pending: bool = Field(
        description="A code was issued and has not been matched or lapsed yet."
    )
    # The outstanding code travels with the state, so a reader who switched
    # tabs mid-dance can be shown the same link again instead of being made to
    # start over. Null unless `pending`; it is this account's own secret and
    # this route is session-gated, which is the only reason it may be read back.
    code: str | None = None
    deep_link: str | None = None


def _restore(paths) -> dict:
    """This account's prefs, bucket first.

    The chat id is written by another process entirely — the Actions job that
    reads the bot's updates — so a local read is a stale read, and stale here
    means a reader watching a spinner that will never stop.
    """
    try:
        if storage.enabled():
            storage.restore(paths.prefs)
    except Exception:  # noqa: BLE001 — transient; the local copy still answers
        pass
    return accounts.load_prefs(paths.prefs)


def _state(prefs: dict) -> Telegram:
    try:
        issued = float(prefs.get("tg_link_ts") or 0)
    except (TypeError, ValueError):
        issued = 0.0
    code = str(prefs.get("tg_link_code") or "")
    pending = bool(code) and time.time() - issued <= LINK_TTL
    return Telegram(
        configured=telegram.configured(),
        linked=bool(prefs.get("telegram_chat_id")),
        pending=pending,
        code=code if pending else None,
        deep_link=telegram.deep_link(code) if pending else None,
    )


@router.get("", response_model=Telegram, summary="Is a chat linked yet")
def state(account: Account) -> Telegram:
    """Whether this account has Telegram, and whether it is mid-link.

    This is the polling endpoint: a client presses Connect, opens Telegram, and
    asks this until `linked` turns true.
    """
    return _state(_restore(account))


@router.post("", response_model=Link, summary="Start linking a chat")
def link(account: Writer) -> Link:
    """Issue a one-time code and hand back the deep link that carries it.

    The code goes into prefs.json (and so into the bucket) because the process
    that has to match it is not this one — the chat job reads "/start <code>"
    from the bot's updates and writes the chat id back the same way.
    """
    if not telegram.configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="telegram is not configured on this deployment",
        )
    code = secrets.token_urlsafe(12)
    accounts.update_prefs(
        account.prefs, {"tg_link_code": code, "tg_link_ts": int(time.time())}
    )
    return Link(
        code=code,
        deep_link=telegram.deep_link(code),
        bot=f"@{telegram.bot_username()}",
        expires_in=LINK_TTL,
    )


@router.post("/test", response_model=Telegram, summary="Send one test message")
def test(account: Writer) -> Telegram:
    """Prove the link works, from the account's own side.

    A write because it spends the bot on this account's behalf — and because
    "send a message to a chat id" is not something a bearer token should be
    able to aim at somebody else's chat.
    """
    prefs = _restore(account)
    chat_id = prefs.get("telegram_chat_id")
    if not chat_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no telegram chat is linked to this account",
        )
    try:
        telegram.send_message(str(chat_id), "✅ TopStocks")
    except Exception as exc:  # noqa: BLE001 — the reason is the answer here
        # The provider's own words and nothing else: the client already has a
        # sentence to frame this with, and prefixing it here made the reader
        # see the same thought twice.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc)[:200] or "telegram refused the message",
        ) from exc
    return _state(prefs)


@router.delete("", response_model=Telegram, summary="Disconnect")
def unlink(account: Writer) -> Telegram:
    """Stop every message. Only the chat id and any pending code are deleted.

    Not the toggles: a reader who disconnects and reconnects a month later
    should find the same three switches set the way they left them, and
    clearing them here would silently turn notifications on for everybody who
    ever unlinked.
    """
    stored = accounts.update_prefs(
        account.prefs,
        {"telegram_chat_id": None, "tg_link_code": None, "tg_link_ts": None},
    )
    return _state(stored)
