"""Which model answers: the account's remembered keys (BYOK), who may use
the free chain, and the order the providers are tried in.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from stocks import llm, obs
from stocks.secrets_env import secret

if TYPE_CHECKING:

    from stocks.llm import Provider


# Remembered-key lifetime, counted from the moment the key was entered and
# never pushed back by use: the settings card counts it down one day at a time,
# and re-entering the key is what starts a fresh 90 days. Expiry is not just a
# read check: prune_byok deletes the ciphertext, so dead keys stop sitting in
# prefs.json (and in the bucket mirror).
BYOK_TTL = 90 * 24 * 3600  # seconds since the key was entered
_BYOK_ORDER = ("anthropic", "openai", "gemini", "openrouter")

def byok_fields(pid: str) -> tuple[str, str, str]:
    """The three prefs keys holding one provider's remembered key."""
    return f"{pid}_key_enc", f"{pid}_key_saved_at", f"{pid}_key_first_at"


def _byok_entered(prefs: dict, pid: str) -> float | None:
    """When `pid`'s stored key was entered, or None when none is stored.

    `_key_first_at` is the entry time. Entries written before it existed carry
    only `_key_saved_at`, which stands in for it.
    """
    enc_k, saved_k, first_k = byok_fields(pid)
    if not prefs.get(enc_k):
        return None
    try:
        saved = float(prefs.get(saved_k, 0) or 0)
        return float(prefs.get(first_k, saved) or saved)
    except (TypeError, ValueError):
        return None


def byok_alive(prefs: dict, pid: str) -> bool:
    """True while `pid`'s stored key is younger than BYOK_TTL."""
    entered = _byok_entered(prefs, pid)
    return entered is not None and time.time() - entered <= BYOK_TTL


def decrypt_byok(prefs: dict, pid: str) -> str:
    """The user's stored key for `pid`, or '' (missing / expired / bad token)."""
    try:
        from cryptography.fernet import Fernet

        enc_key = secret("CHAT_ENC_KEY", "chat", "enc_key")
        enc_k, _, _ = byok_fields(pid)
        if not enc_key or not byok_alive(prefs, pid):
            return ""
        return Fernet(enc_key).decrypt(prefs[enc_k].encode()).decode()
    except Exception as exc:
        obs.warn("chat.engine.decrypt_failed", pid=pid,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return ""


def save_byok(prefs: dict, pid: str, api_key: str) -> bool:
    """Encrypt one provider key into `prefs`. False when nothing can encrypt it.

    The caller saves prefs; this only mutates the dict, so a surface that has
    other edits in flight writes the file once. A fresh entry restarts the
    90 days, because re-entering a key is the user saying it is current.

    False means the deployment has no `[chat] enc_key`, and the honest thing is
    to say so: storing a provider key in plaintext beside a portfolio is not a
    degraded mode, it is a different promise.
    """
    from cryptography.fernet import Fernet

    enc_key = secret("CHAT_ENC_KEY", "chat", "enc_key")
    if not enc_key or not api_key.strip():
        return False
    enc_k, saved_k, first_k = byok_fields(pid)
    now = int(time.time())
    prefs[enc_k] = Fernet(enc_key).encrypt(api_key.strip().encode()).decode()
    prefs[saved_k] = now
    prefs[first_k] = now
    return True


def can_store_keys() -> bool:
    """Whether this deployment can encrypt a provider key at all.

    Asked before the reader types one, so a settings screen can offer "this
    session only" as the choice it is rather than as the apology a 503 would
    make of it — `save_byok` refuses without the secret, and a form that only
    learned that on submit would have asked for a key it could not keep.
    """
    return bool(secret("CHAT_ENC_KEY", "chat", "enc_key"))


def forget_byok(prefs: dict, pid: str) -> bool:
    """Drop one provider's stored key. True when there was one to drop.

    The ciphertext is deleted, not just the timestamps: a key the user asked to
    be forgotten must stop existing, including in the bucket mirror.
    """
    changed = False
    for field in byok_fields(pid):
        if prefs.pop(field, None) is not None:
            changed = True
    return changed


def byok_days_left(prefs: dict, pid: str) -> int | None:
    """Days before this stored key expires, or None when none is stored. One
    less each day after the key was entered; use does not move it."""
    entered = _byok_entered(prefs, pid)
    if entered is None:
        return None
    left = BYOK_TTL - (time.time() - entered)
    # Rounded up, not down: a key entered a second ago has 90 days, and
    # floor() would tell its owner 89 on the day they typed it in.
    return max(0, math.ceil(left / 86400))


def prune_byok(prefs: dict) -> bool:
    """Delete every expired stored key, ciphertext included. True when changed.

    Expiry has to remove the token, not merely refuse to read it: otherwise an
    abandoned account keeps a decryptable provider key in prefs.json and in the
    bucket forever. Mutates `prefs` in place — the caller saves.
    """
    changed = False
    for enc_k in [k for k in list(prefs) if k.endswith("_key_enc")]:
        pid = enc_k[: -len("_key_enc")]
        if byok_alive(prefs, pid):
            continue
        for field in byok_fields(pid):
            changed = prefs.pop(field, None) is not None or changed
    return changed


# Who may spend the operator's keyless chain. The per-account and global caps
# bound what one account and one day cost; neither bounds how many accounts
# there are, and a Google sign-in is free to obtain in bulk. Fourteen throwaway
# accounts exhaust FREE_GLOBAL_DAILY_CAP, which is not only a bill — it is the
# real users seeing "free tier exhausted" for the rest of the day.
#
#   open        anyone signed in, on the full allowance from the first minute
#   trial       the default: anyone signed in, but an account younger than
#               FREE_MIN_ACCOUNT_HOURS spends against FREE_TRIAL_CAP instead of
#               the full one. A new user can try the assistant the moment they
#               sign up, and a day of farming buys an attacker a handful of
#               messages per throwaway account rather than a full pot
#   established the hard wall: no free chain at all until the account has been
#               around a day. Costs an attacker a day of waiting per account,
#               and costs every honest new user their first session
#   allowlist   only the addresses in [free_llm] allowed_emails
#
# BYOK is untouched under every policy: a user with their own key pays their
# own bill and needs no permission from anyone.
FREE_ELIGIBILITY = "trial"
FREE_MIN_ACCOUNT_HOURS = 24


def free_policy() -> str:
    got = secret("FREE_LLM_ELIGIBILITY", "free_llm", "eligibility").lower()
    valid = ("open", "trial", "established", "allowlist")
    return got if got in valid else FREE_ELIGIBILITY


def free_allowlist() -> set[str]:
    raw = secret("FREE_LLM_ALLOWED_EMAILS", "free_llm", "allowed_emails")
    return {e.strip().lower() for e in raw.replace(";", ",").split(",") if e.strip()}


def _min_account_hours() -> float:
    try:
        return float(secret("FREE_LLM_MIN_ACCOUNT_HOURS", "free_llm",
                            "min_account_hours") or FREE_MIN_ACCOUNT_HOURS)
    except (TypeError, ValueError):
        return FREE_MIN_ACCOUNT_HOURS


def account_age_hours(prefs: dict) -> float | None:
    """Hours since this account first signed in, or None when it is unknown.

    Unknown covers accounts that predate the bookkeeping (first_seen backfilled
    with first_seen_estimated) — those are old by definition, so callers read
    None as "established", never as "brand new"."""
    if prefs.get("first_seen_estimated"):
        return None
    stamp = prefs.get("first_seen")
    if not stamp:
        return None
    try:
        first = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if first.tzinfo is None:
        first = first.replace(tzinfo=UTC)
    return (datetime.now(UTC) - first).total_seconds() / 3600


def free_eligible(prefs: dict) -> bool:
    """Whether this account may use the operator-funded chain.

    Reads the account's own prefs, so it works identically in the panel and in
    a headless job — no session, no request, no email lookup.
    """
    policy = free_policy()
    if policy in ("open", "trial"):
        # Both let a signed-in account through; under "trial" a young one is
        # held to the smaller cap instead (see free_daily_cap).
        return True
    if policy == "allowlist":
        allowed = free_allowlist()
        # An allowlist nobody is on would lock out the operator too, which is
        # a misconfiguration, not a policy — treat an empty list as "not set".
        if not allowed:
            return True
        return str(prefs.get("email") or "").strip().lower() in allowed
    age = account_age_hours(prefs)
    return age is None or age >= _min_account_hours()


def in_free_trial(prefs: dict) -> bool:
    """Whether this account is still on the reduced new-account allowance.

    Only under the "trial" policy, and only while the account is demonstrably
    young: an unknown age reads as established here for the same reason it does
    in free_eligible — the accounts with no usable stamp are the old ones.
    """
    if free_policy() != "trial":
        return False
    age = account_age_hours(prefs)
    return age is not None and age < _min_account_hours()


def attempts(prefs: dict, session_keys: dict[str, str] | None = None,
             ) -> list[tuple[Provider, str, str]]:
    """(provider, api_key, model) candidates in resolution order.

    First the user's preferred provider, then the BYOK order — each only with
    a usable key — then the operator's keyless free chain, for the
    accounts free_eligible() lets near it (first of all when it is the one
    preferred). The model is the user's saved pref
    or '' (callers substitute the provider default).

    `session_keys` are keys the caller holds for this one request and nothing
    longer — the drawer's "this session only" key, which travels in a
    request header (api/routes/chat/preferences.py). One wins
    over a stored key for the same provider, because it is the one the reader
    typed most recently. They are an argument, never a prefs entry: every
    path that spends a turn saves `prefs` afterwards, and a key smuggled into
    that dict would be written to disk in the clear by the first free unit it
    charged — the exact promise a session-only key exists to keep.
    """

    held = session_keys or {}
    seen = []
    preferred = prefs.get("llm_provider")
    for pid in dict.fromkeys([preferred, *held, *_BYOK_ORDER]):
        if not pid or pid == "free" or pid not in llm.PROVIDERS:
            continue
        key = (held.get(pid) or "").strip() or decrypt_byok(prefs, pid)
        if key:
            provider = llm.PROVIDERS[pid]
            seen.append((provider, key, prefs.get(f"{pid}_model") or ""))
    free = llm.PROVIDERS["free"]
    if free.available() and free_eligible(prefs):
        # Picked on purpose ("Try with TopStocks AI" after a refusal, or the
        # settings list): it answers first, and the keys stay behind it for a
        # day its allowance runs out. Last of all otherwise, because the pot
        # is shared and a reader with a key pays their own way.
        if preferred == "free":
            seen.insert(0, (free, "", ""))
        else:
            seen.append((free, "", ""))
    return seen


def chain(prefs: dict, session_keys: dict[str, str] | None = None,
          ) -> list[tuple[Provider, str, str]]:
    """`attempts`, called the way it has always been called when nothing is
    held for the session.

    The one-argument call is the contract a dozen tests and both front ends
    were written against — they stub `attempts(prefs)` to put a fake backend
    at the head of the chain — so the second argument is only passed when
    there is something in it.
    """
    return attempts(prefs, session_keys) if session_keys else attempts(prefs)


def note_free_fallback(surface: str, prefs: dict,
                       atts: list[tuple[Provider, str, str]],
                       missed: list[str]) -> None:
    """Log `llm.byok_to_free` when the free chain served a reader who holds a
    key of their own — the answer they pay for went to the shared pot instead.

    `missed` is "<provider>:<why>" per own key tried first and lost (an error
    type, or `rejected` when the caller threw its reply away); empty means the
    key was never asked, as when `answerable` put a key refused minutes ago
    behind the free chain. Not logged for a reader who picked the free chain:
    that is a choice, not a fallback. Counted with
    `stocks logs stats --event llm.byok_to_free --by surface` (or `--by why`).
    """
    if prefs.get("llm_provider") == "free":
        return
    own = list(dict.fromkeys(p.id for p, _k, _m in atts if p.id != "free"))
    if not own:
        return
    obs.warn("llm.byok_to_free", surface=surface, own=",".join(own),
             why=",".join(missed) or "behind")
