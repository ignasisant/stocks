"""One account's bank connections, on disk next to its ledger (bank.json).

Two things live here:

* `pending` — authorisations in flight. The bank redirect is a full page load,
  so the Streamlit session that started the round trip is gone by the time the
  user comes back: session_state cannot hold the `state` parameter. It is
  written here instead, tied to the email that started it and short-lived, and
  consumed exactly once on the way back. That is what stops a `state` observed
  (or invented) elsewhere from attaching someone else's consent to this book.
* `connections` — the sessions that survived: which bank, which accounts, and
  when the consent runs out. Plus the last fetch per account, because banks
  cap background fetches (commonly four a day) and the UI must not refetch on
  every rerun.

No secrets are stored: the session id is a handle that only works with our
signed JWT, and the account uid is opaque. The IBAN is kept because the user
needs to recognise which account they connected — masked on the way in.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from stocks import storage
from stocks.config import DATA_DIR

STATE_PATH = DATA_DIR / "bank.json"
VERSION = 1

# An authorisation the user abandoned must not sit around as a usable slot.
# 15 minutes is longer than any bank's own SCA timeout.
PENDING_TTL = 15 * 60
MAX_PENDING = 5  # cap on parallel attempts, oldest dropped first


def _blank() -> dict:
    return {"version": VERSION, "pending": {}, "connections": []}


def load(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return _blank()
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return _blank()
    if not isinstance(data, dict):
        return _blank()
    state = _blank()
    pending = data.get("pending")
    state["pending"] = pending if isinstance(pending, dict) else {}
    conns = data.get("connections")
    state["connections"] = conns if isinstance(conns, list) else []
    return state


def save(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
    storage.persist(path)


def _now() -> float:
    return time.time()


def _prune_pending(pending: dict, now: float) -> dict:
    live = {k: v for k, v in pending.items() if float(v.get("expires", 0)) > now}
    if len(live) <= MAX_PENDING:
        return live
    oldest = sorted(live.items(), key=lambda kv: float(kv[1].get("expires", 0)))
    return dict(oldest[-MAX_PENDING:])


def add_pending(
    path: Path, *, state: str, email: str, aspsp: dict, ttl: int = PENDING_TTL
) -> None:
    """Remember an authorisation we are about to send the user off to."""
    data = load(path)
    data["pending"][state] = {
        "email": email.strip().lower(),
        "aspsp": {"name": aspsp.get("name", ""), "country": aspsp.get("country", "")},
        "expires": _now() + ttl,
    }
    # Pruned after the insert, not before: pruning first would leave room for
    # the new entry and let the cap drift one higher on every attempt.
    data["pending"] = _prune_pending(data["pending"], _now())
    save(data, path)


def take_pending(path: Path, state: str, email: str) -> dict | None:
    """Consume a pending authorisation. None when it is unknown, expired or
    belongs to another account — the caller must then refuse the code."""
    data = load(path)
    entry = data["pending"].get(state)
    data["pending"] = _prune_pending(data["pending"], _now())
    data["pending"].pop(state, None)  # single use, valid or not
    save(data, path)
    if not entry:
        return None
    if float(entry.get("expires", 0)) <= _now():
        return None
    if str(entry.get("email", "")).strip().lower() != email.strip().lower():
        return None
    return entry


def _mask(account_id: str) -> str:
    """IBAN down to what identifies it to its owner: ES12 ···· 3456."""
    clean = "".join(str(account_id).split())
    if len(clean) <= 8:
        return clean
    return f"{clean[:4]} ···· {clean[-4:]}"


def _account_rows(session: dict) -> list[dict]:
    rows = []
    for acc in session.get("accounts") or []:
        if isinstance(acc, str):  # older payloads: bare uids
            rows.append({"uid": acc, "name": "", "masked_id": "", "currency": ""})
            continue
        identifier = (acc.get("account_id") or {}).get("iban") or (
            (acc.get("account_id") or {}).get("other") or {}
        ).get("identification", "")
        rows.append(
            {
                "uid": acc.get("uid", ""),
                "name": acc.get("name") or (acc.get("details") or ""),
                "masked_id": _mask(identifier or ""),
                "currency": acc.get("currency", ""),
                "product": acc.get("product", ""),
            }
        )
    return [r for r in rows if r["uid"]]


def add_connection(path: Path, session: dict, *, aspsp: dict | None = None) -> dict:
    """Store the outcome of create_session(). Re-authorising the same bank
    replaces the old entry rather than stacking a second one."""
    aspsp = session.get("aspsp") or aspsp or {}
    conn = {
        "session_id": session.get("session_id", ""),
        "aspsp": {"name": aspsp.get("name", ""), "country": aspsp.get("country", "")},
        "valid_until": (session.get("access") or {}).get("valid_until", ""),
        "connected_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "accounts": _account_rows(session),
    }
    data = load(path)
    data["connections"] = [
        c
        for c in data["connections"]
        if c.get("aspsp", {}).get("name") != conn["aspsp"]["name"]
        or c.get("aspsp", {}).get("country") != conn["aspsp"]["country"]
    ]
    data["connections"].append(conn)
    save(data, path)
    return conn


def connections(path: Path = STATE_PATH) -> list[dict]:
    return load(path)["connections"]


def find(path: Path, session_id: str) -> dict | None:
    for conn in connections(path):
        if conn.get("session_id") == session_id:
            return conn
    return None


def remove_connection(path: Path, session_id: str) -> bool:
    data = load(path)
    kept = [c for c in data["connections"] if c.get("session_id") != session_id]
    if len(kept) == len(data["connections"]):
        return False
    data["connections"] = kept
    save(data, path)
    return True


def expired(conn: dict, now: datetime | None = None) -> bool:
    """Whether the consent has run out. An unparseable or absent date reads as
    live: the API is the authority, and it will say so with a ConsentError."""
    raw = str(conn.get("valid_until", "") or "").strip()
    if not raw:
        return False
    try:
        until = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    return until <= (now or datetime.now(UTC))


def record_fetch(
    path: Path, session_id: str, account_uid: str, *, balances: list[dict]
) -> None:
    """Cache what an account last reported, with the time it was fetched —
    the fetch budget is the bank's, and it is small."""
    data = load(path)
    for conn in data["connections"]:
        if conn.get("session_id") != session_id:
            continue
        for acc in conn.get("accounts", []):
            if acc.get("uid") == account_uid:
                acc["snapshot"] = {
                    "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "balances": balances,
                }
                save(data, path)
                return


# --------------------------------------------------------------- balances
# Banks report several balances per account — booked, available, on-hold,
# forward-dated. The order below is what a person means by "how much is in
# the account", and it lives here rather than in a page because both front
# ends have to pick the same one or the same account reads two figures.
BALANCE_PREFERENCE = ("CLBD", "ITAV", "CLAV", "XPCD", "OTHR")


def pick_balance(balances: list[dict]) -> dict | None:
    """The one balance to show, or None when the bank reported none."""
    for wanted in BALANCE_PREFERENCE:
        for entry in balances:
            if str(entry.get("balance_type", "")).upper() == wanted:
                return entry
    return balances[0] if balances else None


def balance_money(balances: list[dict]) -> tuple[float, str] | None:
    """`(amount, currency)` of that balance, or None when it will not parse.

    An unreadable amount is None rather than 0.0: a zero on screen is a claim
    about somebody's money, and "we could not read it" is not that claim.
    """
    entry = pick_balance(balances)
    if not entry:
        return None
    money = entry.get("balance_amount") or {}
    try:
        amount = float(money.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return None
    return amount, str(money.get("currency", "") or "")


# A consent can die before the date the bank stated — revoked at the bank, or
# cut short by the ASPSP. The date is what both front ends read to decide
# whether to offer a refresh, so the way to record that is to backdate it.
DEAD = "1970-01-01T00:00:00Z"


def mark_expired(path: Path, session_id: str) -> None:
    """Record a consent the API just refused, so the card offers a reconnect
    instead of a button that cannot work."""
    data = load(path)
    for conn in data["connections"]:
        if conn.get("session_id") == session_id:
            conn["valid_until"] = DEAD
    save(data, path)
