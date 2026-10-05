"""Per-account data files for the web app: prefs, the chat book, the watchlist.

Who the caller is gets decided elsewhere — the app's own Google OIDC flow
(stocks.web.oidc) mints a signed session cookie that `stocks.session` owns, and
the HTTP API (stocks.api.deps) resolves it to one account's `UserPaths`. This
module is what happens next: reading and writing the files under that account's
data dir, every write mirrored to the bucket through `_persist`.

Every account gets its own data under data/users/<slug>/ — watchlist.yaml,
portfolio.db, last_import.json, prefs.json — keyed by the verified OIDC
email. The optional [app].owner_email account maps to the repo-root files
instead (watchlist.yaml, data/portfolio.db), so the CLI — which is
single-user and always works on the root files — stays in sync with the
owner's web session. Broker-code aliases stay global (root watchlist.yaml):
they're reference data, not personal data.

Every function takes the account's path explicitly: there is no ambient
session to fall back on.
"""

from __future__ import annotations

import functools
import json
import threading
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from stocks import accounts, atomic, obs, storage
from stocks import watchlist as wl
from stocks.chat import memory
from stocks.config import PROJECT_ROOT, stat_key

RECENT_SEARCHES_MAX = accounts.RECENT_SEARCHES_MAX
DEFAULT_PREFS = accounts.DEFAULT_PREFS

# Account identity and per-account paths live in `stocks.accounts`, re-exported
# here because the callers that read an account's files — and their tests —
# reach for them through `auth.`.
USERS_DIR = accounts.USERS_DIR
GUEST_DIR = accounts.GUEST_DIR
STARTER_WATCHLIST = accounts.STARTER_WATCHLIST
UserPaths = accounts.UserPaths
slug = accounts.slug
_legacy_slug = accounts.legacy_slug
paths_for = accounts.paths_for
guest_paths = accounts.guest_paths
_USER_FILES = accounts.USER_FILES
_migrate_legacy = accounts.migrate_legacy


def _persist(path: Path) -> None:
    """Mirror to the bucket after a committed local write.

    A cloud failure must not fail the request — the local write has landed and
    the caller's answer is true — but it is logged: the local copy still
    vanishes on the next container restart.
    """
    try:
        storage.persist(path)
    except Exception as exc:
        obs.warn("storage.persist_failed", file=path.name,
                 error_type=type(exc).__name__)


def delete_account(paths: UserPaths) -> None:
    """Erase one account's data everywhere: bucket copies first, then disk.

    The GDPR-shaped promise on the legal page: everything under the account's
    data dir goes, cloud copies included. Bucket keys are enumerated (not just
    the fixed _USER_FILES) so nothing generated later survives. Bucket first
    and loudly: if the cloud delete fails the local copies stay too, so a
    retry still sees a consistent account instead of resurrecting the bucket
    from a half-deleted disk on the next write.

    Refuses the owner account (its "data dir" is the repo root — deleting it
    would take the CLI's own book and reference data with it) and the shared
    guest dir. Backup snapshots are immutable history and expire on their own
    schedule; the legal copy says so.
    """
    root = paths.root.resolve()
    if root in (PROJECT_ROOT.resolve(), GUEST_DIR.resolve()):
        raise ValueError("refusing to delete the owner or guest data")
    if USERS_DIR.resolve() not in root.parents:
        raise ValueError(f"not an account dir: {root}")

    # Connections first: whatever happens to the files below, nothing outside
    # this app keeps reading an account its owner asked to erase.
    from stocks.connector import store

    store.revoke_account(paths)

    if storage.enabled():
        prefix = root.relative_to(PROJECT_ROOT.resolve()).as_posix()
        for key in storage.list_keys(prefix + "/"):
            storage.delete_key(key)
    if root.exists():
        import shutil

        shutil.rmtree(root)


# ------------------------------------------------------------- preferences


@lru_cache(maxsize=64)
def _prefs_stored(path: Path, _key: tuple[int, int] | None) -> dict:
    """The stored half of `load_prefs`, memoized on the file's stat signature.

    Keyed like `config._yaml`: `save_prefs` changes the file, which changes the
    key, so there is no invalidation call to forget. Never handed out directly
    — `load_prefs` merges a fresh dict over the defaults, because its callers
    mutate what they get back and then save it.
    """
    if _key is None:
        return {}
    return accounts.stored_prefs(path)


def load_prefs(path: Path) -> dict:
    """This account's preferences, defaults filled in.

    Read on nearly every request by a dozen callers (the language resolver,
    the setup card, the tour, the chat), so the file read and parse are
    memoized while the merge stays per-call: the result is mutable and callers
    edit it in place before `save_prefs` — which, the dict being an
    `accounts.LoadedPrefs`, writes back only what they edited.
    """
    return accounts.LoadedPrefs(
        {**DEFAULT_PREFS, **_prefs_stored(path, stat_key(path))}
    )


def save_prefs(prefs: dict, path: Path) -> None:
    accounts.save_prefs(path, prefs, persist=_persist)


# ------------------------------------------------------ daily action card


def load_action(path: Path) -> dict:
    """The stored daily-action card as a raw dict ({} when there is none).

    Shaped like load_prefs: unreadable or corrupt reads as "nothing stored",
    which sends the dashboard down the regenerate path instead of an error.
    """
    try:
        out = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


def save_action(card: dict, path: Path) -> None:
    """Store today's card, mirrored to the bucket like every other user file.

    Worth the round trip for one small JSON: the card costs an LLM call, and
    Cloud Run recycles the container on idle — without the mirror every cold
    start would spend another unit of the free allowance on a card the account
    already has.
    """
    atomic.write_json(path, card, indent=2)
    _persist(path)


# ------------------------------------------------------ sector verdicts


def load_verdicts(path: Path) -> dict:
    """The stored per-sector AI reads, keyed by sector name ({} when none).

    Same contract as load_action: unreadable or corrupt reads as "nothing
    stored", which sends the page down the regenerate path, not an error page.
    """
    try:
        out = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


def save_verdicts(verdicts: dict, path: Path) -> None:
    """Store every sector's verdict, mirrored to the bucket.

    One file rather than one per sector: eleven of them at a few hundred bytes
    each is still one small JSON, and one bucket key is one round trip instead
    of eleven. A verdict costs a unit of the account's daily allowance, so
    losing the file to a container recycle would charge the reader twice for
    the same paragraph.
    """
    atomic.write_json(path, verdicts, indent=2)
    _persist(path)

# ------------------------------------------------------- investor profile
# Who the assistant is advising, stated by the user (not hard-coded). Stored
# under prefs["investor_profile"] as stable enum keys (locale-independent, so
# the English system prompt stays stable whatever the UI language) plus a free
# notes field. The chat engine reads it to build the assistant persona; empty
# -> it falls back to its historical default line.

# Both tuples are the order the controls draw in, and both run low to high in
# the same direction: a row of chips only reads as a scale when its two halves
# agree on which end is "more".
PROFILE_RISK = ("conservative", "balanced", "aggressive", "very_aggressive")
PROFILE_HORIZON = ("under_1y", "1_3y", "3_5y", "5y_plus")
PROFILE_FOCUS = ("tech", "em", "crypto", "dividends_value")
PROFILE_CONSTRAINTS = ("spain_tax", "us_tax", "eur", "no_leverage", "esg")

# Example tickers per declared focus, offered on the Profile page to an
# account whose watchlist does not have them yet (see focus_suggestions).
#
# Keyed on `focus` — a stated interest — and deliberately NOT on `risk`. A
# list assembled from someone's risk tolerance is a recommendation however it
# is worded, and this app is not in that business; a list assembled from "you
# said you follow emerging markets" is a shortcut for typing eight symbols,
# which is all it is meant to be. The seed already covers each area thinly, so
# these widen rather than replace, and nothing is ever removed.
#
# Tags are the English labels the starter watchlist uses, so an appended row
# lands in the same dashboard group as the seeded ones rather than starting a
# near-duplicate group.
FOCUS_EXAMPLES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "tech": (
        ("GOOGL", "Alphabet", "Tech"),
        ("AMD", "AMD", "Tech"),
        ("NOW", "ServiceNow", "Tech"),
    ),
    "em": (
        ("BABA", "Alibaba", "Emerging markets"),
        ("INFY", "Infosys", "Emerging markets"),
        ("NU", "Nu Holdings", "Emerging markets"),
    ),
    "crypto": (
        ("ETH-EUR", "Ethereum", "Crypto"),
        ("SOL-EUR", "Solana", "Crypto"),
        ("COIN", "Coinbase", "Crypto"),
    ),
    "dividends_value": (
        ("KO", "Coca-Cola", "Dividends"),
        ("PG", "Procter & Gamble", "Dividends"),
        ("ENB", "Enbridge", "Dividends"),
    ),
}

# What an account that never opened the form pre-selects. The middle of the
# risk scale rather than one end: this is a guess about someone we know
# nothing about, and the form is the place to correct it.
_PROFILE_DEFAULTS = {
    "risk": "balanced",
    "horizon": "5y_plus",
    "focus": [],
    "constraints": [],
    "notes": "",
}


def load_profile(prefs: dict) -> dict:
    """The account's investor profile, defaults filled in for missing fields.

    `set` is True once the user has saved the form at least once; callers use
    it to tell a real (possibly minimal) profile from the mere defaults.
    """
    stored = prefs.get("investor_profile") or {}
    return {**_PROFILE_DEFAULTS, **stored, "set": bool(stored.get("set"))}


def profile_is_set(prefs: dict) -> bool:
    return bool((prefs.get("investor_profile") or {}).get("set"))


# ------------------------------------------------------------- chat threads
# The assistant keeps several conversations per account — each with an id, a
# title and timestamps, one of them active — persisted like prefs so they
# survive a reload, a new session or an ephemeral redeploy, and mirrored to
# the bucket.
#
# All of them live in a single chat.json ({"version", "active",
# "conversations"}) rather than one file per thread: the whole per-account
# sync path (_USER_FILES, storage.restore_once, _persist) is built on a fixed
# tuple of paths, so a directory of threads would need its own bucket keying
# and orphan cleanup for nothing the user can see.
#
# load_chat/save_chat keep their original list-of-turns signature and act on
# the active conversation, so the Telegram bot and the headless engine never
# had to learn about threads.

CHAT_VERSION = 2
MAX_CONVERSATIONS = 50  # oldest by last use pruned first; never the active one
# Home's daily cards are filed as threads of their own (save_card_thread), one
# a day. The ones nobody wrote in are kept on a budget of their own: a month of
# cards must not push the reader's conversations out of MAX_CONVERSATIONS.
MAX_CARD_THREADS = 30
_TITLE_MAX = 80

# Every write is a read-modify-write of the whole book, and since the daily
# card files its thread from a background job, two can now overlap inside one
# process: a card filed while a chat turn is being saved. One lock for all of
# them. Re-entrant only so a writer may call another without deadlocking.
_book_lock = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _book_lock:
            return fn(*args, **kwargs)

    return wrapper


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _blank_conversation(title: str = "") -> dict:
    now = _now()
    return {
        "id": f"c_{uuid.uuid4().hex[:8]}",
        "title": title,
        # False once the user renames it, so auto-titling stops overwriting.
        "title_auto": True,
        "created": now,
        "updated": now,
        "messages": [],
    }


def _empty_book() -> dict:
    conv = _blank_conversation()
    return {"version": CHAT_VERSION, "active": conv["id"], "conversations": [conv]}


def load_book(path: Path) -> dict:
    """Every conversation for the account, in the current shape.

    Never writes — a turn that fails must leave chat.json untouched (and
    absent when it never existed). A v1 file (the bare list of turns the
    single-thread assistant wrote) migrates to one conversation; anything
    missing or corrupt yields a fresh empty book.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        data = None

    if isinstance(data, list):  # v1: one unnamed thread
        conv = _blank_conversation()
        conv["messages"] = [m for m in data if isinstance(m, dict)]
        return {"version": CHAT_VERSION, "active": conv["id"],
                "conversations": [conv]}
    if not isinstance(data, dict):
        return _empty_book()

    convs = [
        c for c in (data.get("conversations") or [])
        if isinstance(c, dict) and c.get("id")
    ]
    for c in convs:  # tolerate records written by an older/partial writer
        c.setdefault("title", "")
        c.setdefault("title_auto", True)
        c.setdefault("created", _now())
        c.setdefault("updated", c["created"])
        c["messages"] = [m for m in (c.get("messages") or []) if isinstance(m, dict)]
    if not convs:
        return _empty_book()

    active = data.get("active")
    if active not in {c["id"] for c in convs}:
        active = convs[0]["id"]
    return {"version": CHAT_VERSION, "active": active, "conversations": convs}


def _unread_card(conv: dict) -> bool:
    """A daily card's thread the reader never wrote in. Once they have, it is
    a conversation like any other, and is kept like one."""
    return bool(conv.get("daily")) and not any(
        m.get("role") == "user" for m in conv["messages"]
    )


def _pruned(book: dict) -> dict:
    """The book capped at MAX_CONVERSATIONS, dropping least-recently-used
    threads first and never the active one — and the cards nobody answered
    capped apart, at MAX_CARD_THREADS."""
    convs = book["conversations"]

    def card(c: dict) -> bool:
        return _unread_card(c) and c["id"] != book["active"]

    cards = [c for c in convs if card(c)]
    talk = [c for c in convs if not card(c)]
    if len(cards) <= MAX_CARD_THREADS and len(talk) <= MAX_CONVERSATIONS:
        return book

    def newest(group: list[dict], n: int) -> list[dict]:
        return sorted(group, key=lambda c: c.get("updated") or "", reverse=True)[:n]

    active = [c for c in talk if c["id"] == book["active"]][:1]
    others = [c for c in talk if c["id"] != book["active"]]
    keep = {
        c["id"]
        for c in active
        + newest(others, MAX_CONVERSATIONS - len(active))
        + newest(cards, MAX_CARD_THREADS)
    }
    return {**book, "conversations": [c for c in convs if c["id"] in keep]}


def save_book(book: dict, path: Path) -> None:
    atomic.write_json(path, _pruned(book), indent=2)
    _persist(path)


def _active(book: dict) -> dict:
    """The active conversation — load_book guarantees one exists."""
    for c in book["conversations"]:
        if c["id"] == book["active"]:
            return c
    return book["conversations"][0]


def load_chat(path: Path) -> list[dict]:
    """The active conversation's turns (the historical single-thread API)."""
    return _active(load_book(path))["messages"]


def memory_path(path: Path) -> Path:
    """The account's long-term chat index, beside its chat history."""
    return path.parent / memory.FILE


@_locked
def save_chat(history: list[dict], path: Path) -> None:
    """Replace the active conversation's turns and stamp it as just used.

    Indexing rides along here rather than at the two call sites: every turn
    that reaches disk is a turn the assistant may need to recall later, and
    both surfaces (the panel and the Telegram bot) already come through this
    one function. It is idempotent and best-effort — a failed index costs a
    worse search, never a lost message."""
    book = load_book(path)
    conv = _active(book)
    conv["messages"] = list(history)
    conv["updated"] = _now()
    save_book(book, path)
    index = memory_path(path)
    if memory.remember(index, history, conv["id"]):
        _persist(index)  # only when it actually grew — most saves add nothing


def list_conversations(path: Path) -> list[dict]:
    """Conversation metadata (no message bodies), most recently used first.
    `daily` is the card day of a daily card's thread, "" for any other."""
    book = load_book(path)
    metas = [
        {
            "id": c["id"], "title": c["title"], "title_auto": c["title_auto"],
            "created": c["created"], "updated": c["updated"],
            "messages": len(c["messages"]), "active": c["id"] == book["active"],
            "daily": str(c.get("daily") or ""),
        }
        for c in book["conversations"]
    ]
    return sorted(metas, key=lambda m: m["updated"], reverse=True)


def active_conversation(path: Path) -> dict:
    """Metadata of the conversation the next turn will land in."""
    c = _active(load_book(path))
    return {k: v for k, v in c.items() if k != "messages"}


@_locked
def new_conversation(path: Path, title: str = "") -> str:
    """Start (and activate) an empty conversation; returns its id.

    An active conversation that is still empty is reused, so pressing New
    repeatedly can't stack blank threads."""
    book = load_book(path)
    conv = _active(book)
    if conv["messages"]:
        conv = _blank_conversation(title)
        book["conversations"].append(conv)
    elif title:
        conv["title"] = title[:_TITLE_MAX]
    book["active"] = conv["id"]
    save_book(book, path)
    return conv["id"]


@_locked
def set_active_conversation(cid: str, path: Path) -> None:
    book = load_book(path)
    if any(c["id"] == cid for c in book["conversations"]):
        book["active"] = cid
        save_book(book, path)


@_locked
def rename_conversation(cid: str, title: str, path: Path) -> None:
    """User-set title — pins it, so auto-titling never overwrites it again."""
    book = load_book(path)
    for c in book["conversations"]:
        if c["id"] == cid:
            c["title"] = title.strip()[:_TITLE_MAX]
            c["title_auto"] = False
            save_book(book, path)
            return


@_locked
def autotitle_conversation(cid: str, title: str, path: Path) -> None:
    """Title derived from the opening exchange; a no-op on a renamed thread."""
    book = load_book(path)
    for c in book["conversations"]:
        if c["id"] == cid and c.get("title_auto", True):
            c["title"] = title.strip()[:_TITLE_MAX]
            save_book(book, path)
            return


@_locked
def delete_conversation(cid: str, path: Path) -> None:
    """Drop a conversation. Deleting the active one falls back to the most
    recently used survivor — or a fresh empty thread when it was the last."""
    book = load_book(path)
    kept = [c for c in book["conversations"] if c["id"] != cid]
    if len(kept) == len(book["conversations"]):
        return
    if not kept:
        kept = [_blank_conversation()]
    if book["active"] == cid:
        book["active"] = max(kept, key=lambda c: c["updated"])["id"]
    book["conversations"] = kept
    save_book(book, path)
    # A deleted conversation must not keep answering questions through the
    # memory index.
    index = memory_path(path)
    if memory.forget(index, cid):
        _persist(index)


@_locked
def save_card_thread(day: str, title: str, text: str, path: Path) -> str:
    """File a daily card in the chat as a thread of its own; returns its id.

    One thread per card day, titled once ("Daily action · 3 Oct") and never
    made active: the card is written in the background, and a reader halfway
    through a conversation must not find it carrying on somewhere else.
    Opening it is the card's "Ask" button, and the reader then asks with the
    card in the thread above the question.

    A card rewritten the same day (the computed stand-in, then the model's)
    replaces its turn while nobody has answered it, and lands after the
    reader's turns when somebody has — the thread is what the reader was
    told, in order. Indexed like any turn, which is how the chat and the
    Telegram bot can recall what a card said."""
    book = load_book(path)
    conv = next((c for c in book["conversations"] if c.get("daily") == day), None)
    if conv is None:
        conv = _blank_conversation(title[:_TITLE_MAX])
        conv["title_auto"] = False
        conv["daily"] = day
        book["conversations"].append(conv)
    turn = {"role": "assistant", "content": text, "daily": day}
    msgs = conv["messages"]
    if msgs and msgs[-1].get("daily") == day:
        if msgs[-1].get("content") == text:
            return conv["id"]  # the same card again: nothing to file
        msgs[-1] = turn
    else:
        msgs.append(turn)
    conv["updated"] = _now()
    save_book(book, path)
    index = memory_path(path)
    if memory.remember(index, msgs, conv["id"]):
        _persist(index)
    return conv["id"]


# ---------------------------------------------------------------- watchlist


def focus_suggestions(profile: dict, path: Path) -> list[dict]:
    """Example rows for the account's declared focus that it does not have yet.

    Returns watchlist rows ({ticker, name, tags}), in `FOCUS_EXAMPLES` order, with
    everything already on the watchlist filtered out — so the offer shrinks as
    it is taken up and disappears once there is nothing left to add. Empty
    whenever no focus is declared, which is what keeps this off the page for
    an account that skipped the profile.
    """
    from stocks.config import load_watchlist

    have = {h.ticker.upper() for h in load_watchlist(path)}
    out: list[dict] = []
    for area in profile.get("focus") or []:
        for ticker, name, tag in FOCUS_EXAMPLES.get(area, ()):
            if ticker.upper() in have:
                continue
            have.add(ticker.upper())  # a ticker in two areas is offered once
            out.append({"ticker": ticker, "name": name, "tags": [tag]})
    return out


# ------------------------------------------------------- favorites and tags
# Bindings over `stocks.watchlist`, which holds the edits themselves. Each adds
# `_persist`, so a bucket outage is a logged warning instead of an exception
# out of a write that already landed.


def set_favorite(ticker: str, value: bool, path: Path) -> None:
    """Set (not flip) a ticker's favorite flag."""
    wl.set_favorite(path, ticker, value, persist=_persist)


def set_tags(ticker: str, tags: list[str], path: Path) -> list[str]:
    """Replace a ticker's tags; an empty list removes the key entirely."""
    return wl.set_tags(path, ticker, tags, persist=_persist)


def set_alerts(ticker: str, alerts: list[dict], path: Path) -> None:
    """Replace a ticker's alert rules; an empty list removes the key entirely."""
    wl.set_alerts(path, ticker, alerts, persist=_persist)


def add_entry(ticker: str, name: str, path: Path) -> None:
    """Put a ticker on the watchlist (a no-op when it is already there)."""
    wl.add_entry(path, ticker, name, persist=_persist)


def remove_entry(ticker: str, path: Path) -> None:
    """Drop a ticker from the watchlist, alerts and tags with it."""
    wl.remove_entry(path, ticker, persist=_persist)


def set_position(ticker: str, shares: float | None, cost: float | None,
                 path: Path) -> None:
    """Set a ticker's held quantity and/or average cost."""
    wl.set_position(path, ticker, shares, cost, persist=_persist)


def all_tags(path: Path) -> list[str]:
    """Every tag used on this account's watchlist, sorted case-insensitively."""
    return wl.all_tags(path)
