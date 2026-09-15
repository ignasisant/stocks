"""Enable Banking API client — account information (AIS) only.

Auth is unusual and worth stating once: there is no client secret and no token
endpoint. The application registers a public key in the Enable Banking control
panel and gets an application id back; every request carries a JWT that *we*
sign with the matching private key, with the application id as the `kid`
header. Nothing is exchanged with them beforehand, so a valid key is the whole
credential — treat the PEM like a password (Secret Manager on the deploy,
[enable_banking] private_key in secrets.toml locally).

Consent flow, one bank at a time:

    aspsps("ES")                   -> the banks we can offer
    start_auth(...)                -> (url, state); the user authenticates there
    <bank redirects to /bank?code=…&state=…>
    create_session(code)           -> session_id + the accounts consented to
    balances(uid) / transactions(uid, date_from)

The session lasts as long as the consent the user granted at their bank
(`access.valid_until`, capped by the ASPSP — typically 90 days). After that
every account call fails and the user has to re-authorise: that case is raised
as ConsentError so the UI can offer a reconnect instead of an error page.

Fetching is rate limited at the *bank* end, commonly four background fetches
per account per day, so callers cache and refresh on demand — never per rerun.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from stocks.secrets_env import secret

API = "https://api.enablebanking.com"
ISSUER = "enablebanking.com"
AUDIENCE = "api.enablebanking.com"

# Max the API accepts is 86400s; an hour is plenty and keeps a leaked token's
# window short. Signing is cheap, but not free per request — hence the cache.
TOKEN_TTL = 3600
_TOKEN_SKEW = 60  # re-sign this long before expiry

# What we ask the bank for. Most ASPSPs allow up to 180 days and cap anything
# longer themselves, so asking for the maximum is free and halves how often
# the user has to re-authenticate. An upper bound, never a promise: a session
# can still die early (revoked at the bank, SCA policy) — see ConsentError.
DEFAULT_CONSENT_DAYS = 180

# Pagination guard: continuation keys are the bank's, and a buggy one that
# never changes would loop forever.
MAX_PAGES = 20

_token: tuple[str, float] | None = None  # (jwt, expires_at)


class BankError(Exception):
    """An API call failed. `code`/`status` carry Enable Banking's own error."""

    def __init__(self, status: int, code: str = "", description: str = ""):
        self.status = status
        self.code = code
        self.description = description
        super().__init__(f"{status} {code}: {description}".strip(" :"))


class ConsentError(BankError):
    """The session is gone: consent expired, revoked, or denied by the user.

    Distinct from BankError because it is not a failure to report — it is the
    normal end of a consent, and the only fix is re-authorising.
    """


class RateLimited(BankError):
    """The bank's own fetch budget is spent, not ours.

    Most ASPSPs allow four data fetches per account per day while the user is
    not present at their bank. Nothing is wrong and nothing needs reconnecting
    — the answer is to come back later, so the UI must say that rather than
    show a failure.
    """


def application_id() -> str:
    return secret("EB_APPLICATION_ID", "enable_banking", "application_id")


def private_key() -> str:
    """The registered key, PEM. Env vars can't hold real newlines in every
    deploy path, so an escaped "\\n" form is accepted and normalised."""
    pem = secret("EB_PRIVATE_KEY", "enable_banking", "private_key")
    return pem.replace("\\n", "\n").strip()


def configured() -> bool:
    return bool(application_id() and private_key())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _sign(app_id: str, pem: str, now: int) -> str:
    header = {"typ": "JWT", "alg": "RS256", "kid": app_id}
    claims = {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + TOKEN_TTL}
    signing_input = ".".join(
        _b64(json.dumps(p, separators=(",", ":")).encode()) for p in (header, claims)
    ).encode()
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    # The `alg` above is RS256, so only an RSA key can sign this. Saying so is
    # not ceremony: a PEM is pasted in by hand, and an EC key would otherwise
    # die on an AttributeError deep in `sign` instead of naming the problem.
    if not isinstance(key, rsa.RSAPrivateKey):
        raise BankError(0, "bad_key", "Enable Banking private key must be RSA")
    sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode()}.{_b64(sig)}"


def token() -> str:
    """A signed JWT, reused until it is about to expire."""
    global _token
    now = int(time.time())
    if _token and _token[1] - _TOKEN_SKEW > now:
        return _token[0]
    app_id, pem = application_id(), private_key()
    if not (app_id and pem):
        raise BankError(0, "not_configured", "Enable Banking credentials are missing")
    jwt = _sign(app_id, pem, now)
    _token = (jwt, now + TOKEN_TTL)
    return jwt


def reset_token() -> None:
    """Drop the cached JWT — for tests and for a credential change."""
    global _token
    _token = None


def _raise(exc: urllib.error.HTTPError, *, session_scoped: bool) -> BankError:
    try:
        body = json.loads(exc.read() or b"{}")
    except (json.JSONDecodeError, OSError):
        body = {}
    code = str(body.get("error_code", "") or "")
    description = str(body.get("error_description", "") or exc.reason or "")
    if exc.code == 429 or "RATE_LIMIT" in code.upper():
        return RateLimited(exc.code, code, description)
    # 401 on a session-scoped call is the consent, not our key: the same JWT
    # just worked to reach the endpoint. 403 is the bank refusing the consent
    # outright (revoked, or data sharing denied).
    consent = session_scoped and exc.code in (401, 403)
    cls = ConsentError if consent else BankError
    return cls(exc.code, code, description)


def _call(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    session_scoped: bool = False,
    timeout: float = 30,
) -> dict:
    url = API + path
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token()}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp) if resp.status != 204 else {}
    except urllib.error.HTTPError as exc:
        raise _raise(exc, session_scoped=session_scoped) from None
    except urllib.error.URLError as exc:
        raise BankError(0, "network", str(exc.reason)) from None


# ------------------------------------------------------------------ banks


def aspsps(country: str = "ES", psu_type: str = "personal") -> list[dict]:
    """The banks available for a country, as {name, country, logo, beta, …}."""
    found = _call("GET", "/aspsps", params={"country": country.upper()})
    return [
        a
        for a in found.get("aspsps", [])
        if not a.get("psu_types") or psu_type in a["psu_types"]
    ]


# ------------------------------------------------------- consent + session


def consent_valid_until(days: int = DEFAULT_CONSENT_DAYS) -> str:
    """`access.valid_until` for a consent starting now, in the API's format."""
    return (
        (datetime.now(UTC) + timedelta(days=days))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def start_auth(
    *,
    name: str,
    country: str,
    redirect_url: str,
    state: str | None = None,
    psu_type: str = "personal",
    valid_until: str | None = None,
    language: str | None = None,
) -> tuple[str, str]:
    """Begin authorisation. Returns (bank url to send the user to, state).

    `state` comes back on the redirect untouched; it is how the callback
    proves the round trip belongs to the account that started it, so it must
    be unguessable and single-use (see bank.store).
    """
    state = state or uuid.uuid4().hex
    body = {
        "access": {"valid_until": valid_until or consent_valid_until()},
        "aspsp": {"name": name, "country": country.upper()},
        "state": state,
        "redirect_url": redirect_url,
        "psu_type": psu_type,
    }
    if language:
        body["language"] = language
    return _call("POST", "/auth", body=body)["url"], state


def create_session(code: str) -> dict:
    """Exchange the redirect's `code` for a session: session_id + accounts."""
    return _call("POST", "/sessions", body={"code": code})


def delete_session(session_id: str) -> None:
    """Close a session at the bank. Already-gone sessions are not an error —
    the user asked for it disconnected, and it is."""
    try:
        _call("DELETE", f"/sessions/{session_id}", session_scoped=True)
    except BankError as exc:
        if exc.status not in (401, 403, 404):
            raise


# ---------------------------------------------------------------- accounts


def balances(account_uid: str) -> list[dict]:
    got = _call("GET", f"/accounts/{account_uid}/balances", session_scoped=True)
    return got.get("balances", [])


def transactions(
    account_uid: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    """Booked+pending transactions for one account, following continuations.

    Dates are YYYY-MM-DD; how far back a bank goes is its own policy (often
    90 days, sometimes 24 months).
    """
    out: list[dict] = []
    continuation = None
    for _ in range(max_pages):
        page = _call(
            "GET",
            f"/accounts/{account_uid}/transactions",
            params={
                "date_from": date_from,
                "date_to": date_to,
                "continuation_key": continuation,
            },
            session_scoped=True,
        )
        out += page.get("transactions", [])
        nxt = page.get("continuation_key")
        if not nxt or nxt == continuation:
            break
        continuation = nxt
    return out


# ------------------------------------------------------------- shaping


def amount(tx: dict) -> float:
    """Signed amount in account currency: credits positive, debits negative.

    The API reports magnitude in `transaction_amount` and direction in
    `credit_debit_indicator` ("CRDT"/"DBIT"), so a caller that ignored the
    indicator would read every withdrawal as money coming in.
    """
    try:
        value = float(tx.get("transaction_amount", {}).get("amount", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    debit = str(tx.get("credit_debit_indicator", "")).upper().startswith("DBIT")
    return -abs(value) if debit else abs(value)


def counterparty(tx: dict) -> str:
    """Who the money went to or came from, best effort across ASPSPs."""
    debit = amount(tx) < 0
    first, second = ("creditor", "debtor") if debit else ("debtor", "creditor")
    for field in (first, second):
        name = str((tx.get(field) or {}).get("name", "") or "").strip()
        if name:
            return name
    remittance = tx.get("remittance_information") or []
    if isinstance(remittance, str):
        remittance = [remittance]
    return " ".join(str(r).strip() for r in remittance if r).strip()


def tx_date(tx: dict) -> str:
    """The date to file a transaction under: booking, else value, else txn."""
    for field in ("booking_date", "value_date", "transaction_date"):
        value = str(tx.get(field, "") or "").strip()
        if value:
            return value[:10]
    return ""
