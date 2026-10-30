"""Web Push: tell a device the assistant's answer is ready, when nobody is looking.

A reader asks something, puts the phone away, and the answer is written on a
detached run (`api/runs.py`) that finishes whether or not anyone is reading.
This sends that device a notification — "Your answer is ready" — that opens
the thread.

No vendor and no dependency: the browser hands us a push service URL (Google's,
Mozilla's, Apple's) and two keys, and the protocol is two RFCs on top of
`cryptography`:

* RFC 8291 — the payload is encrypted to the browser's key (ECDH P-256 +
  HKDF + AES-128-GCM, `aes128gcm` content coding), so the push service carries
  bytes it cannot read;
* RFC 8292 — VAPID: each request carries an ES256 JWT signed with this app's
  key, so the service knows the sender is the one the subscription was made
  for. The public half goes to the browser at subscribe time.

The key is `[webpush] private_key` (or `WEBPUSH_PRIVATE_KEY`): a PEM, or the
raw 32-byte scalar in base64url. Without one, `configured()` is False and the
Profile offers nothing.

Subscriptions live in one JSON file per account (`UserPaths.push`, in
`accounts.USER_FILES`), one row per device keyed by a hash of its endpoint. A
push service answering 404/410 means the subscription is gone (app removed,
permission revoked) and the row goes with it.

Whether someone is looking is `seen`/`present`: an open, visible app posts a
heartbeat, and a finished answer skips the push while one is fresh. In memory
on purpose — the service runs one instance (`runs.py` relies on the same), and
losing it on a restart costs at most one notification nobody needed.

Nothing here raises into a request or a run: failures are warnings.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from stocks import atomic, obs, storage
from stocks.secrets_env import secret

FILE = "push.json"

# Devices per account; the oldest goes past it.
MAX_ROWS = 10
# A heartbeat this recent means the reader has the app on screen.
PRESENT_S = 45
# How long a push service keeps trying an offline device. An answer that
# arrives the next morning is noise; six hours covers a commute and a meeting.
TTL_S = 6 * 3600
TIMEOUT_S = 10

_lock = threading.Lock()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ------------------------------------------------------------------ the key


def _private_key() -> ec.EllipticCurvePrivateKey | None:
    raw = secret("WEBPUSH_PRIVATE_KEY", "webpush", "private_key")
    if not raw:
        return None
    try:
        if "BEGIN" in raw:
            # Secret Manager and env vars flatten newlines to "\n".
            pem = raw.replace("\\n", "\n").encode()
            key = serialization.load_pem_private_key(pem, password=None)
        else:
            key = ec.derive_private_key(
                int.from_bytes(_unb64(raw), "big"), ec.SECP256R1()
            )
    except (ValueError, TypeError) as exc:
        obs.error("push.key_unreadable", error_type=type(exc).__name__)
        return None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
        obs.error("push.key_wrong_curve")
        return None
    return key


def configured() -> bool:
    return _private_key() is not None


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def public_key() -> str | None:
    """The `applicationServerKey` a browser subscribes with, base64url."""
    key = _private_key()
    return _b64(_point(key.public_key())) if key else None


def generate_key() -> str:
    """A fresh private key in the raw form `[webpush] private_key` takes."""
    key = ec.generate_private_key(ec.SECP256R1())
    return _b64(key.private_numbers().private_value.to_bytes(32, "big"))


# --------------------------------------------------------- RFC 8291 / 8292


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            server: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """`payload` as an `aes128gcm` body only the subscribed browser can read.

    `salt` and `server` are for tests; each message gets fresh ones otherwise.
    """
    ua_point = _unb64(p256dh)
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_point)
    server = server or ec.generate_private_key(ec.SECP256R1())
    as_point = _point(server.public_key())
    salt = salt or os.urandom(16)

    shared = server.exchange(ec.ECDH(), ua_public)
    ikm = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=_unb64(auth),
        info=b"WebPush: info\x00" + ua_point + as_point,
    ).derive(shared)
    cek = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt,
        info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)
    # One record: the payload, then the 0x02 "last record" delimiter.
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    rs = 4096
    return salt + struct.pack("!IB", rs, len(as_point)) + as_point + body


def vapid_header(endpoint: str, subject: str,
                 key: ec.EllipticCurvePrivateKey, *, now: float | None = None) -> str:
    """The `Authorization` value for a push to `endpoint`."""
    now = time.time() if now is None else now
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(now) + 12 * 3600,
        "sub": subject,
    }
    signing = (
        _b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        + "."
        + _b64(json.dumps(claims, separators=(",", ":")).encode())
    )
    r, s = decode_dss_signature(key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = signing + "." + _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={_b64(_point(key.public_key()))}"


# ------------------------------------------------------------ subscriptions


def _row_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:24]


def _read(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        obs.error("push.store_unreadable", error_type=type(exc).__name__)
        return {}
    rows = data.get("subscriptions") if isinstance(data, dict) else None
    return {k: v for k, v in (rows or {}).items() if isinstance(v, dict)}


def _write(path: Path, rows: dict[str, dict]) -> None:
    newest = sorted(rows, key=lambda k: float(rows[k].get("created") or 0))[-MAX_ROWS:]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(path, {"subscriptions": {k: rows[k] for k in newest}}, indent=1)
    storage.persist(path)


def _valid_endpoint(endpoint: str) -> bool:
    # A push service is a public https origin; anything else would make this
    # server POST wherever a client pointed it.
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https" and bool(host) and "." in host
        and not host.endswith((".local", ".internal", ".localhost"))
        and not host.replace(".", "").isdigit() and ":" not in host
    )


def subscribe(path: Path, *, endpoint: str, p256dh: str, auth: str,
              origin: str, lang: str, now: float | None = None) -> bool:
    """Keep this device's subscription. False when it is not one we can use."""
    if not _valid_endpoint(endpoint):
        return False
    try:
        if len(_unb64(p256dh)) != 65 or len(_unb64(auth)) != 16:
            return False
    except (ValueError, TypeError):
        return False
    now = time.time() if now is None else now
    with _lock:
        rows = _read(path)
        key = _row_id(endpoint)
        rows[key] = {
            "endpoint": endpoint, "p256dh": p256dh, "auth": auth,
            "origin": origin, "lang": lang,
            "created": float((rows.get(key) or {}).get("created") or now),
        }
        _write(path, rows)
    return True


def unsubscribe(path: Path, endpoint: str) -> bool:
    with _lock:
        rows = _read(path)
        if rows.pop(_row_id(endpoint), None) is None:
            return False
        _write(path, rows)
    return True


def subscribed(path: Path, endpoint: str) -> bool:
    return _row_id(endpoint) in _read(path)


def row(path: Path, endpoint: str) -> dict | None:
    return _read(path).get(_row_id(endpoint))


def _drop(path: Path, endpoint: str) -> None:
    with obs.swallow("push.drop"):
        unsubscribe(path, endpoint)


# ------------------------------------------------------------------ sending


def _post(endpoint: str, body: bytes, headers: dict[str, str]) -> int:
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def send(path: Path, row: dict, message: dict, *, topic: str = "") -> int:
    """Push `message` (the service worker's JSON) to one device; the status.

    A 404/410 drops the row: the subscription is gone for good.
    """
    key = _private_key()
    if key is None:
        return 0
    body = encrypt(json.dumps(message).encode(), row["p256dh"], row["auth"])
    headers = {
        "Authorization": vapid_header(row["endpoint"], row.get("origin") or "", key),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL_S),
        "Urgency": "normal",
    }
    if topic:
        # A newer push on the same topic replaces one still queued.
        headers["Topic"] = re.sub(r"[^A-Za-z0-9_-]", "", topic)[:32]
    status = _post(row["endpoint"], body, headers)
    if status in (404, 410):
        _drop(path, row["endpoint"])
    host = urlsplit(row["endpoint"]).hostname or ""
    if status >= 300:
        obs.warn("push.rejected", status=status, service=host)
    else:
        obs.event("push.sent", service=host)
    return status


# ----------------------------------------------------------------- presence

# owner -> client id -> (visible, wall clock of the beat)
_seen: dict[str, dict[str, tuple[bool, float]]] = {}


def seen(owner: str, client: str, visible: bool, *, now: float | None = None) -> None:
    """A client of `owner` says whether it has the app on screen."""
    now = time.time() if now is None else now
    with _lock:
        mine = _seen.setdefault(owner, {})
        mine[client[:64]] = (visible, now)
        for cid, (_v, at) in list(mine.items()):
            if now - at > PRESENT_S:
                del mine[cid]


def present(owner: str, *, now: float | None = None) -> bool:
    """Whether some client of `owner` had the app on screen just now."""
    now = time.time() if now is None else now
    with _lock:
        return any(v and now - at <= PRESENT_S for v, at in _seen.get(owner, {}).values())


def _snippet(text: str, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def answer_ready(path: Path, owner: str, *, thread: str, question: str) -> int:
    """After a run: push "your answer is ready" unless the reader is looking."""
    if not configured() or present(owner):
        return 0
    from stocks.web.i18n import translate

    took = 0
    for row in list(_read(path).values()):
        lang = row.get("lang") or "en"
        message = {
            "title": translate("notify.push_answer_title", lang),
            "body": _snippet(question),
            "url": f"/?thread={quote(thread, safe='')}",
            "tag": f"answer-{thread}",
        }
        with obs.swallow("push.send"):
            took += 200 <= send(path, row, message, topic=thread) < 300
    return took
