"""Linking a Telegram chat, and the two things you do with it afterwards.

Linking is a four-step dance — press Connect, get a one-time code, press Start
in Telegram, wait for the chat id to come back. The code is a secret in
prefs.json, and the waiting is polling this route. The return trip has two
roads: with the webhook Worker deployed, the Actions chat job matches
"/start <code>" and writes `telegram_chat_id` into the bucket; without it
(no webhook set, Telegram keeps the updates for getUpdates) this route reads
the bot's recent updates itself on each poll and completes the link here.
Each road is a no-op while the other is live — getUpdates answers 409, read
as nothing, whenever a webhook is set.

The code is session-scoped and random. That matters: an attacker sending
"/start <guess>" from their own Telegram can only ever match a code somebody
else's session generated, and never one derived from an address.
"""

from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stocks import accounts, obs, storage
from stocks.api.deps import Account, Writer
from stocks.notify import telegram

router = APIRouter(prefix="/notify/telegram", tags=["notify"])

# How long a pending code stays matchable: ten minutes, and the code is retired
# server-side when it lapses rather than left sitting in prefs for the next
# person who guesses it.
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
    username: str | None = Field(
        default=None,
        description=(
            "The linked chat's Telegram @handle, without the @, as the link "
            "job recorded it — what the Profile prints beside "
            '"connected" so a reader with two accounts can tell which one '
            "gets the messages. Null when not linked, or when the chat has no "
            "public username (Telegram does not require one)."
        ),
    )


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
        username=(
            str(prefs.get("telegram_username") or "").lstrip("@") or None
            if prefs.get("telegram_chat_id")
            else None
        ),
    )


def _complete_from_updates(account, prefs: dict) -> dict:
    """Finish a pending link from the bot's own updates, when nothing else will.

    Without the webhook Worker no job ever reads "/start <code>", and the
    reader watches a spinner that cannot stop. getUpdates is read without an
    offset, so nothing is consumed: two readers linking at once still each
    find their own message, and the Worker road, once deployed, sees the
    same updates. Any failure leaves the state as it was for the next poll.
    """
    code = str(prefs.get("tg_link_code") or "")
    if not code or prefs.get("telegram_chat_id") or not telegram.configured():
        return prefs
    chat = None
    with obs.swallow("telegram.link_poll"):
        chat = telegram.match_start(telegram.get_updates(), code)
    if not chat:
        return prefs
    stored = accounts.update_prefs(
        account.prefs,
        {
            "telegram_chat_id": chat["id"],
            "telegram_username": chat.get("username") or "",
            "telegram_linked_at": int(time.time()),
            "tg_link_code": None,
            "tg_link_ts": None,
        },
    )
    obs.event("telegram.linked", via="poll")
    from stocks.web.i18n import translate

    with obs.swallow("telegram.link_welcome"):
        telegram.send_message(
            translate("notify.tg_linked_alerts", prefs.get("language") or "en"),
            chat["id"],
            parse_mode=None,
        )
    return stored


@router.get("", response_model=Telegram, summary="Is a chat linked yet")
def state(account: Account) -> Telegram:
    """Whether this account has Telegram, and whether it is mid-link.

    This is the polling endpoint: a client presses Connect, opens Telegram, and
    asks this until `linked` turns true. While a code is pending each poll
    also looks for its "/start" in the bot's updates.
    """
    prefs = _restore(account)
    if _state(prefs).pending:
        prefs = _complete_from_updates(account, prefs)
    return _state(prefs)


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
        telegram.send_message("✅ TopStocks", str(chat_id), parse_mode=None)
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
    """Stop every message. Only the chat identity and any pending code go.

    The identity is the chat id with the handle and link time recorded beside
    it, so the next link does not come back printing the previous chat's
    @username.

    Not the toggles: a reader who disconnects and reconnects a month later
    should find the same three switches set the way they left them, and
    clearing them here would silently turn notifications on for everybody who
    ever unlinked.
    """
    stored = accounts.update_prefs(
        account.prefs,
        {
            "telegram_chat_id": None,
            "telegram_username": None,
            "telegram_linked_at": None,
            "tg_link_code": None,
            "tg_link_ts": None,
        },
    )
    return _state(stored)
