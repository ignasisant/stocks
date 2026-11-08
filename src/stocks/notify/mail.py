"""Email through Resend — the weekly review's channel.

Web Push stays the app's channel for everything that is news (alerts, the
digest, a finished answer). Email carries one thing: the Friday review
(`notify/weekly_email.py`), which reaches an account that never installed the
app on a device.

Configured by `[resend] api_key` and `[resend] from` (or `RESEND_API_KEY` /
`RESEND_FROM`); without both, `configured()` is False and the job skips every
account rather than failing each one. The sender's domain has to be verified
in Resend (SPF/DKIM DNS records) — a manual step outside this code.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from stocks import obs
from stocks.secrets_env import secret

API_URL = "https://api.resend.com/emails"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
# 4xx answers that say this address will never take mail: the job stops
# writing to it rather than bouncing every Friday.
UNDELIVERABLE = (422,)


@dataclass(frozen=True)
class Sent:
    ok: bool
    id: str = ""
    status: int = 0
    error: str = ""

    @property
    def undeliverable(self) -> bool:
        return not self.ok and self.status in UNDELIVERABLE


def _key() -> str:
    return secret("RESEND_API_KEY", "resend", "api_key")


def sender() -> str:
    return secret("RESEND_FROM", "resend", "from")


def configured() -> bool:
    return bool(_key() and sender())


def send(
    to: str,
    subject: str,
    html: str,
    text: str,
    *,
    unsubscribe: str | None = None,
    idempotency_key: str | None = None,
    tag: str = "weekly",
) -> Sent:
    """Send one message. Never raises: the result says what happened.

    `unsubscribe` is the one-click URL (RFC 8058): mail clients show their own
    unsubscribe button from it, and POST to it without opening the page.
    `idempotency_key` makes a retried run send once (Resend keeps it 24 h).
    """
    key, origin = _key(), sender()
    if not key or not origin:
        return Sent(False, error="not configured")
    headers = {"Authorization": f"Bearer {key}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    body: dict = {
        "from": origin,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
        "tags": [{"name": "kind", "value": tag}],
    }
    if unsubscribe:
        body["headers"] = {
            "List-Unsubscribe": f"<{unsubscribe}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    try:
        resp = httpx.post(API_URL, json=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        obs.warn("email.fail", kind=tag, error_type=type(exc).__name__,
                 error=str(exc)[:200])
        return Sent(False, error=type(exc).__name__)
    if resp.status_code >= 300:
        detail = resp.text[:300]
        obs.warn("email.fail", kind=tag, status=resp.status_code, error=detail)
        return Sent(False, status=resp.status_code, error=detail)
    sent_id = str((resp.json() or {}).get("id") or "")
    obs.event("email.sent", kind=tag, id=sent_id)
    return Sent(True, id=sent_id, status=resp.status_code)
