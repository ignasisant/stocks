"""Who let which app read their book: the connector's grants and clients.

A *grant* is one "Allow" on the consent screen — one account, one client, one
refresh-token lineage. Everything an MCP client holds hangs off it: the access
token it sends with each tool call, the refresh token it trades for the next
one, and the line on Profile's connector card that revokes them both. Revoking
is always the whole grant; a client that lost one token has lost the session.

Two JSON files under `data/mcp/`, global rather than per account because a
bearer token arrives before anybody knows whose it is — the token *is* the
lookup key. Nothing in them is a credential at rest: every token and every
client secret is stored as its sha256, so a copy of the files (a backup, a
bucket listing, a support paste) cannot be replayed. The tokens are 256 random
bits, so an unsalted hash is not something anyone brute-forces back.

Single container, like the rest of the storage model (`web/ratelimit.py`,
`storage.py`): the process holds the indexes, the bucket is restored once on
first touch, and every write lands on disk and is mirrored at once. A mirror
that fails is a warning, not a refusal — the grant still works on this
instance, and the worst a restart can do is ask the user to connect again,
which is cheaper than refusing them now.

Refresh tokens rotate on every use and the spent ones are remembered: a spent
token presented again means two parties hold the lineage, and the only safe
answer is to end the grant for both (OAuth 2.0 Security BCP §4.14). No grace
window — a client that lost the response to its own refresh reconnects.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR

if TYPE_CHECKING:
    from stocks.accounts import UserPaths

DIR = DATA_DIR / "mcp"

SCOPE = "topstocks.read"
#: Editing the book, the watchlist and the memory. Never granted by default:
#: the consent screen asks for it with a box of its own, left unticked.
WRITE_SCOPE = "topstocks.write"
SCOPES = (SCOPE, WRITE_SCOPE)
ACCESS_PREFIX = "tsat_"
REFRESH_PREFIX = "tsrt_"

ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400  # sliding: each rotation starts a new month...
GRANT_MAX_AGE = 180 * 86400  # ...up to half a year after the "Allow"

SPENT_KEEP = 16  # rotated-out refresh hashes kept per grant for reuse detection
CLIENT_CAP = 5000  # registered (DCR) clients, the open door's ceiling
CLIENT_IDLE = 7 * 86400  # a registration nobody ever completed is pruned


def _now() -> int:
    return int(time.time())


def digest(token: str) -> str:
    """What the files keep instead of a token or secret."""
    return hashlib.sha256(token.encode()).hexdigest()


def _norm(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class Issued:
    """A fresh token pair, the only time either exists in clear."""

    grant: str
    access: str
    refresh: str
    expires_in: int
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class Holder:
    """What a live token stands for."""

    grant: str
    email: str
    client_id: str
    scopes: tuple[str, ...]
    expires_at: int


class Ledger:
    """The two files and their in-memory indexes, behind one lock."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.grants_file = directory / "grants.json"
        self.clients_file = directory / "clients.json"
        self._lock = threading.RLock()
        self._loaded = False
        self._grants: dict[str, dict] = {}
        self._clients: dict[str, dict] = {}
        self._by_access: dict[str, str] = {}
        self._by_refresh: dict[str, str] = {}
        self._by_spent: dict[str, str] = {}

    # ---------------------------------------------------------------- disk

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            storage.restore_once(self.dir, (self.grants_file, self.clients_file))
        except Exception as exc:  # noqa: BLE001 — start from disk, say so
            obs.warn("mcp.store_restore_failed", error_type=type(exc).__name__)
        self._grants = self._read(self.grants_file)
        self._clients = self._read(self.clients_file)
        self._reindex()
        self._loaded = True

    @staticmethod
    def _read(path: Path) -> dict[str, dict]:
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            # Unreadable means every connection reconnects, which is the cost
            # of a fresh start, not of a breach — so start fresh and say so.
            obs.error("mcp.store_unreadable", file=path.name,
                      error_type=type(exc).__name__)
            return {}
        return data if isinstance(data, dict) else {}

    def _reindex(self) -> None:
        self._by_access, self._by_refresh, self._by_spent = {}, {}, {}
        for gid, g in self._grants.items():
            for h in g.get("access", {}):
                self._by_access[h] = gid
            if g.get("refresh"):
                self._by_refresh[g["refresh"]["hash"]] = gid
            for h in g.get("spent", []):
                self._by_spent[h] = gid

    def _write(self, path: Path, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        atomic.write_json(path, data, indent=1, sort_keys=True)
        try:
            storage.persist(path)
        except Exception as exc:  # noqa: BLE001 — see the module docstring
            obs.warn("mcp.store_persist_failed", file=path.name,
                     error_type=type(exc).__name__)

    def _save_grants(self) -> None:
        self._write(self.grants_file, self._grants)

    def _save_clients(self) -> None:
        self._write(self.clients_file, self._clients)

    # -------------------------------------------------------------- grants

    def _mint(self, g: dict, now: int) -> tuple[str, str]:
        access = ACCESS_PREFIX + secrets.token_urlsafe(32)
        refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
        live = {h: exp for h, exp in g.get("access", {}).items() if exp > now}
        live[digest(access)] = now + ACCESS_TTL
        g["access"] = live
        g["refresh"] = {
            "hash": digest(refresh),
            "expires": min(now + REFRESH_TTL, g["created"] + GRANT_MAX_AGE),
        }
        g["used"] = now
        return access, refresh

    def issue(self, *, email: str, client_id: str, client_name: str,
              client_kind: str, redirect_host: str,
              scopes: tuple[str, ...] = (SCOPE,)) -> Issued:
        """A new grant: the code exchange after the user said "Allow".

        `scopes` is what the consent screen granted; reading always comes
        with it, and anything unknown is dropped rather than stored.
        """
        granted = (SCOPE, *(s for s in SCOPES if s != SCOPE and s in scopes))
        now = _now()
        with self._lock:
            self._load()
            gid = "g_" + secrets.token_hex(8)
            g = {
                "email": _norm(email),
                "client_id": client_id,
                "client_name": client_name[:80],
                "client_kind": client_kind,
                "redirect_host": redirect_host[:120],
                "scopes": list(granted),
                "created": now,
                "spent": [],
            }
            access, refresh = self._mint(g, now)
            self._grants[gid] = g
            self._reindex()
            self._save_grants()
        obs.event("mcp.grant", grant=gid, client_kind=client_kind,
                  write=WRITE_SCOPE in granted)
        return Issued(gid, access, refresh, ACCESS_TTL, granted)

    def holder(self, access: str) -> Holder | None:
        """Who an access token speaks for, or None. Reads only memory."""
        if not access.startswith(ACCESS_PREFIX):
            return None
        h = digest(access)
        with self._lock:
            self._load()
            gid = self._by_access.get(h)
            g = self._grants.get(gid) if gid else None
            if gid is None or g is None:
                return None
            expires = g["access"].get(h, 0)
        if expires <= _now():
            return None
        return Holder(gid, g["email"], g["client_id"], tuple(g["scopes"]), expires)

    def refresh_holder(self, refresh: str) -> Holder | None:
        """Who a refresh token speaks for — and the reuse alarm.

        A spent token revokes its grant on sight: the legitimate holder already
        rotated past it, so whoever is presenting it now copied it.
        """
        if not refresh.startswith(REFRESH_PREFIX):
            return None
        h = digest(refresh)
        with self._lock:
            self._load()
            spent = self._by_spent.get(h)
            if spent is not None:
                self._drop(spent)
                obs.warn("mcp.refresh_reuse", grant=spent)
                return None
            gid = self._by_refresh.get(h)
            g = self._grants.get(gid) if gid else None
            if gid is None or g is None:
                return None
            expires = g["refresh"]["expires"]
        return Holder(gid, g["email"], g["client_id"], tuple(g["scopes"]), expires)

    def rotate(self, refresh: str) -> Issued | None:
        """Trade the current refresh token for a new pair; the old one is spent."""
        h = digest(refresh)
        now = _now()
        with self._lock:
            self._load()
            gid = self._by_refresh.get(h)
            g = self._grants.get(gid) if gid else None
            if gid is None or g is None or g["refresh"]["expires"] <= now:
                return None
            g["spent"] = ([*g.get("spent", []), h])[-SPENT_KEEP:]
            access, new = self._mint(g, now)
            self._reindex()
            self._save_grants()
        return Issued(gid, access, new, ACCESS_TTL, tuple(g["scopes"]))

    def _drop(self, gid: str) -> bool:
        if self._grants.pop(gid, None) is None:
            return False
        self._reindex()
        self._save_grants()
        return True

    def revoke_token(self, token: str) -> None:
        """RFC 7009: either token of a grant ends the whole grant."""
        h = digest(token)
        with self._lock:
            self._load()
            gid = self._by_access.get(h) or self._by_refresh.get(h)
            if gid and self._drop(gid):
                obs.event("mcp.revoke", grant=gid, via="client")

    def revoke(self, gid: str, *, email: str, via: str = "profile") -> bool:
        """Profile's "Revoke": only the grant's own account may end it."""
        with self._lock:
            self._load()
            g = self._grants.get(gid)
            if g is None or g["email"] != _norm(email):
                return False
            self._drop(gid)
        obs.event("mcp.revoke", grant=gid, via=via)
        return True

    def revoke_where(self, owns: Callable[[str], bool]) -> int:
        """Every grant whose account email `owns` claims — account deletion."""
        with self._lock:
            self._load()
            gone = [gid for gid, g in self._grants.items() if owns(g["email"])]
            for gid in gone:
                self._grants.pop(gid)
            if gone:
                self._reindex()
                self._save_grants()
        return len(gone)

    def grants_for(self, email: str) -> list[dict]:
        """One account's live connections, newest first, without any hashes."""
        target, now = _norm(email), _now()
        with self._lock:
            self._load()
            rows = [
                {
                    "id": gid,
                    "client_name": g["client_name"],
                    "client_kind": g["client_kind"],
                    "redirect_host": g["redirect_host"],
                    "created": g["created"],
                    "used": g.get("used", g["created"]),
                    "expires": g["refresh"]["expires"],
                    "write": WRITE_SCOPE in g.get("scopes", ()),
                }
                for gid, g in self._grants.items()
                if g["email"] == target and g["refresh"]["expires"] > now
            ]
        return sorted(rows, key=lambda r: r["created"], reverse=True)

    def prune(self) -> None:
        """Forget grants past their last refresh and idle registrations."""
        now = _now()
        with self._lock:
            self._load()
            dead = [gid for gid, g in self._grants.items()
                    if g["refresh"]["expires"] <= now]
            for gid in dead:
                self._grants.pop(gid)
            if dead:
                self._reindex()
                self._save_grants()
            if self._prune_clients(now):
                self._save_clients()

    # ------------------------------------------------------------- clients

    def _prune_clients(self, now: int) -> bool:
        held = {g["client_id"] for g in self._grants.values()}
        idle = [cid for cid, c in self._clients.items()
                if cid not in held and c["created"] + CLIENT_IDLE <= now]
        for cid in idle:
            self._clients.pop(cid)
        return bool(idle)

    def client(self, client_id: str) -> dict | None:
        """A registered client's stored record (secret as its hash)."""
        with self._lock:
            self._load()
            c = self._clients.get(client_id)
            return dict(c) if c else None

    def register(self, client_id: str, record: dict) -> bool:
        """Keep one DCR registration; False when the door is full."""
        now = _now()
        with self._lock:
            self._load()
            if len(self._clients) >= CLIENT_CAP:
                self._prune_clients(now)
            if len(self._clients) >= CLIENT_CAP:
                obs.warn("mcp.client_cap", clients=len(self._clients))
                return False
            self._clients[client_id] = {**record, "created": now}
            self._save_clients()
        return True


_ledger: Ledger | None = None
_ledger_lock = threading.Lock()


def ledger() -> Ledger:
    """The process's ledger, over `DIR` as it is the first time it is asked."""
    global _ledger
    with _ledger_lock:
        if _ledger is None:
            _ledger = Ledger(DIR)
        return _ledger


def revoke_account(paths: UserPaths) -> int:
    """Account deletion's hook: end every connection the account made.

    Matched by data dir rather than by address, because that is what deletion
    is handed — and it is the same identity: an account's directory is named
    `slug(email)`, a hash-suffixed name no other address produces.
    """
    from stocks import accounts

    name = paths.root.name
    n = ledger().revoke_where(lambda email: accounts.slug(email) == name)
    if n:
        obs.event("mcp.revoke", grants=n, via="account_deleted")
    return n
