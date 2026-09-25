"""Account identity and per-account data paths, with no Streamlit in sight.

This is the half of `stocks.web.auth` that has nothing to do with a browser
session: given an email, where does that account's watchlist, ledger, prefs
and chat memory live, and how is a brand-new account seeded from the bucket.

It lives here rather than in `web/` because more than one runtime needs it and
only one of them is Streamlit:

* the web app (`stocks.web.auth`, which re-exports every name below and adds
  the OIDC gate and the session plumbing on top),
* the internal HTTP API (`stocks.api`), which authenticates with a bearer
  token and is handed an account address,
* headless jobs — the Telegram digest, the CLI — which have a prefs.json and
  no session at all.

Nothing here talks to a user. `restore_account` raises `StorageUnavailable`
instead of painting an error, and each caller decides what that means: the web
app stops the script with a message, the API answers 503.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from stocks import storage
from stocks.chat import memory
from stocks.config import DATA_DIR, PROJECT_ROOT, WATCHLIST_FILE
from stocks.secrets_env import secret

USERS_DIR = DATA_DIR / "users"
GUEST_DIR = USERS_DIR / "_guest"

# The files that make up one account, used by the legacy-dir migration and by
# the bucket restore. `memory.FILE` is the chat memory database.
USER_FILES = (
    "watchlist.yaml", "portfolio.db", "last_import.json", "prefs.json", "chat.json",
    "bank.json", "daily_action.json", "sector_verdict.json", memory.FILE,
)


class StorageUnavailable(RuntimeError):
    """The bucket could not be read, so this account's data is unknown.

    Deliberately fatal for the caller. Falling through to the seeding path
    would hand back an empty book whose next save overwrites the account's
    real cloud data — the outage has to fail closed.
    """


@dataclass(frozen=True)
class UserPaths:
    """Where one account's data lives."""

    root: Path
    watchlist: Path
    db: Path
    last_import: Path
    prefs: Path
    chat: Path
    bank: Path
    action: Path  # the dashboard's daily AI card (chat/daily.py)

    @property
    def verdicts(self) -> Path:
        """Per-sector AI reads of the screen (chat/sector_ai.py).

        Derived rather than stored: it is always the daily card's neighbour,
        and a field would be one more thing every caller that builds a
        UserPaths has to get right and can get wrong.
        """
        return self.action.with_name("sector_verdict.json")


def slug(email: str) -> str:
    """Filesystem-safe, collision-proof directory name for an account email.

    The readable base maps every non-alphanumeric run to "_", so distinct
    addresses can collide ("a.b@c.com" and "a@b.c.com" both give
    "a_b_c_com"). The digest suffix ties the directory to the exact address,
    so the second account to sign in can never land in the first one's data.
    """
    e = email.strip().lower()
    base = re.sub(r"[^a-z0-9]+", "_", e).strip("_")
    return f"{base}_{hashlib.sha256(e.encode()).hexdigest()[:8]}"


def legacy_slug(email: str) -> str:
    """slug() as it was before the digest suffix — kept only so existing
    account dirs (local or in the bucket) can be migrated on next login."""
    return re.sub(r"[^a-z0-9]+", "_", email.lower()).strip("_")


def configured_owner() -> str | None:
    """The account that maps to the repo-root files, if one is configured.

    `[app] owner_email`, read through `secrets_env` rather than `st.secrets`
    so the API and the cron jobs resolve the same owner the web app does
    without importing Streamlit.
    """
    return secret("APP_OWNER_EMAIL", "app", "owner_email").strip().lower() or None


def paths_for(
    email: str, owner_email: str | None = None, users_dir: Path = USERS_DIR
) -> UserPaths:
    """Resolve an account's data paths.

    The owner account maps to the repo-root watchlist and data/portfolio.db
    so the single-user CLI and the owner's web session share one book; every
    other account lives under data/users/<slug>/.
    """
    if owner_email and email.strip().lower() == owner_email.strip().lower():
        return UserPaths(
            root=PROJECT_ROOT,
            watchlist=WATCHLIST_FILE,
            db=DATA_DIR / "portfolio.db",
            last_import=DATA_DIR / "last_import.json",
            prefs=DATA_DIR / "prefs.json",
            chat=DATA_DIR / "chat.json",
            bank=DATA_DIR / "bank.json",
            action=DATA_DIR / "daily_action.json",
        )
    d = users_dir / slug(email)
    return UserPaths(
        root=d,
        watchlist=d / "watchlist.yaml",
        db=d / "portfolio.db",
        last_import=d / "last_import.json",
        prefs=d / "prefs.json",
        chat=d / "chat.json",
        bank=d / "bank.json",
        action=d / "daily_action.json",
    )


def guest_paths() -> UserPaths:
    """The anonymous visitors' shared data dir.

    Read-only through the UI: every write path (favorites, tags, watchlist
    editor, imports, prefs) sits behind require_login()/is_logged_in(), so
    guests only ever read the starter watchlist and the demo ledger
    seed_guest_demo() puts here — one book, identical for every visitor,
    which is what makes sharing one dir safe.
    """
    return UserPaths(
        root=GUEST_DIR,
        watchlist=GUEST_DIR / "watchlist.yaml",
        db=GUEST_DIR / "portfolio.db",
        last_import=GUEST_DIR / "last_import.json",
        prefs=GUEST_DIR / "prefs.json",
        chat=GUEST_DIR / "chat.json",
        bank=GUEST_DIR / "bank.json",
        action=GUEST_DIR / "daily_action.json",
    )


def migrate_legacy(paths: UserPaths, legacy_root: Path) -> None:
    """Move an account dir named with the pre-digest slug to its new name.

    Runs once per account: a no-op as soon as paths.root exists. Covers both
    a dir still on local disk and one that only survives in the bucket (an
    ephemeral host after a redeploy) — bucket objects are re-keyed to the new
    dir so the next boot restores from there directly.
    """
    if paths.root.exists() or legacy_root == paths.root:
        return
    if not legacy_root.exists() and storage.enabled():
        # restore() only writes (and creates the dir) when the key exists,
        # so after this loop legacy_root exists iff the bucket had the account.
        for name in USER_FILES:
            storage.restore(legacy_root / name)
    if not legacy_root.exists():
        return
    legacy_root.rename(paths.root)
    # A failed push must abort (restore_account fails closed) before the old
    # key is deleted, or the bucket could end up holding neither copy.
    for name in USER_FILES:
        storage.persist(paths.root / name)  # push under the new key
        storage.persist(legacy_root / name)  # gone locally -> delete old key


def restore_account(
    paths: UserPaths,
    legacy_root: Path | None = None,
    persist: Callable[[Path], None] = storage.persist,
    seed: bool = True,
) -> bool:
    """Create the account's folder and seed a starter watchlist if it is new.

    Returns True when this call seeded a brand-new account — the one moment a
    signup can be dated exactly, which `auth.mark_login()` records.

    With [storage] configured, the account's files are pulled from the bucket
    first (once per process), so an ephemeral redeploy starts from the
    persisted copies instead of re-seeding. `legacy_root` is the account's
    pre-digest-slug dir; when it still exists (locally or in the bucket) it is
    renamed and re-keyed before anything is restored or seeded.

    Raises `StorageUnavailable` when the bucket round trip fails — see the
    exception's own note for why that must not be swallowed here. Pushing the
    freshly seeded watchlist is the one write that may fail harmlessly (the
    local copy is already good), so it goes through `persist`: the web app
    hands in a wrapper that toasts instead of raising.

    `seed=False` restores and stops there. Reading an account is not the same
    act as creating one, and the API reads: without this, a bearer token could
    call an address into existence by asking about it.
    """
    try:
        if legacy_root is not None:
            migrate_legacy(paths, legacy_root)
        paths.root.mkdir(parents=True, exist_ok=True)
        storage.restore_once(
            paths.root,
            (
                paths.watchlist,
                paths.db,
                paths.last_import,
                paths.prefs,
                paths.chat,
                paths.bank,
                paths.action,
                memory.path_for(paths.root),
            ),
        )
    except Exception as exc:
        raise StorageUnavailable(str(exc)) from exc
    if not seed or paths.watchlist.exists():
        return False
    paths.watchlist.write_text(STARTER_WATCHLIST)
    persist(paths.watchlist)
    return True


def provision(
    email: str,
    owner: str | None = None,
    persist: Callable[[Path], None] = storage.persist,
) -> tuple[UserPaths, bool]:
    """Create (or restore) the account a *verified* sign-in names.

    Returns `(paths, seeded)` — `seeded` is `restore_account`'s verdict, which
    `stamp_login` turns into an exact signup date.

    The one door through which an account comes into existence, shared by the
    Streamlit session (`web.auth.resolve_user`), the OIDC callback and the API's
    signed-in path. Only ever call it with an address a verified identity
    carries: a bearer token or a `?account=` guess must never reach it, which is
    why the API's read path calls `restore_account(seed=False)` instead.

    `USERS_DIR` is read at call time rather than bound as `paths_for`'s default,
    so a test that points it at a temporary directory really does keep every
    provisioned account out of the checkout's `data/users/`.
    """
    paths = paths_for(email, owner, users_dir=USERS_DIR)
    # The owner's book is the repo-root files — no slug, so nothing to migrate.
    legacy = None if paths.root == PROJECT_ROOT else USERS_DIR / legacy_slug(email)
    seeded = restore_account(paths, legacy, persist=persist, seed=True)
    return paths, seeded


def stamp_login(
    paths: UserPaths,
    *,
    seeded: bool = False,
    email: str = "",
    source: str = "",
    persist: Callable[[Path], None] | None = None,
) -> str:
    """Stamp this account's first/last login; return "signup" or "login".

    Cloud Logging keeps 30 days, so "how many accounts exist" is not a question
    the logs can answer — the account's own prefs.json carries the two dates
    that can, and `stocks users` reads them straight out of the bucket.

    `seeded` is `restore_account`'s verdict: True only when this run created the
    account's dir, so only then is the stamp an exact signup date. An account
    that predates this bookkeeping gets first_seen backfilled to now with
    first_seen_estimated=True and counts as a plain login — the roster never
    claims a precision it doesn't have.

    prefs.json is mirrored to the bucket on every save, so this writes at most
    once per account per day: a PUT on each sign-in would cost more than the
    metric is worth, and last_seen is only ever read at day granularity.

    `source` is the campaign token the sign-in arrived with (`web.attribution`),
    written once, on the signup itself, and never rewritten: the question it
    answers is "where did this account come from", and a later visit through a
    different link does not change that. Logs are kept 30 days and an account
    is kept for as long as it exists, so this is the only durable half.

    Headless on purpose: `web.auth.mark_login` (Streamlit), the OIDC callback
    and the API all stamp through here, so the three cannot disagree about what
    a signup is.
    """
    from datetime import UTC, datetime

    prefs = load_prefs(paths.prefs)
    now = datetime.now(UTC)
    today = now.date().isoformat()
    kind = "login"
    changed = False
    # The address, written into the account's own file so headless jobs can
    # identify it — the Telegram bot has a prefs.json and no session. The
    # free-chain allowlist (engine.free_eligible) is the caller that needs it.
    if email and prefs.get("email") != email:
        prefs["email"] = email
        changed = True
    if not prefs.get("first_seen"):
        prefs["first_seen"] = now.isoformat(timespec="seconds")
        prefs["first_seen_estimated"] = not seeded
        kind = "signup" if seeded else "login"
        if source and not prefs.get("first_source"):
            prefs["first_source"] = source
        changed = True
    if prefs.get("last_seen") != today:
        prefs["last_seen"] = today
        changed = True
    if changed:
        save_prefs(paths.prefs, prefs, persist)
    return kind


# A starter watchlist wide enough that every list-shaped page has something to
# show on a brand-new account: the sector screen's P/E table, the earnings calendar,
# the 52-week extremes scan, the sentiment pass, the daily AI card. Two US
# mega-caps gave all of them one row and nothing to compare. The tags seed the
# dashboard's group expanders and the earnings filter pills; the untagged rows
# keep the plain "Watchlist" group populated too.
# ------------------------------------------------------------------ preferences
# Every per-account setting lives in one prefs.json, read and written by path
# so the ASGI worker can serve them without a Streamlit session to resolve.
# `web.auth` binds these to the session's own path and memoizes the read; the
# defaults and the file format live here so both runtimes agree on them.

DEFAULT_PREFS: dict = {  # language None = auto (browser)
    "currency": "EUR",
    "language": None,
    "recent_searches": [],  # tickers clicked from the top-bar search, newest first
    # Registration accounting, stamped by mark_login(). first_seen is the
    # signup moment (ISO, UTC); last_seen is a date, rewritten once a day.
    "first_seen": None,
    "last_seen": None,
    # Where the account came from, if its signup link said so (web.attribution).
    "first_source": None,
    "first_seen_estimated": False,
    # The signed-in address, for the jobs that have a prefs.json and no
    # session (and for the free-chain allowlist). None until the next login.
    "email": None,
    # Telegram notifications: chat_id is set by the Profile linking flow; the
    # toggles only take effect once it is. The cron (notify/fanout.py) reads
    # these headless straight from prefs.json.
    "telegram_chat_id": None,
    "notify_digest": True,
    # Absent here for a while, and read as `.get("notify_weekly", True)` by both
    # the Profile toggle and the cron — so the review was delivered while a
    # plain `.get()` on a loaded prefs dict answered None. Two truths about one
    # switch; this is the one the senders already assume.
    "notify_weekly": True,
    "notify_alerts": True,
    # Tax residence drives which jurisdiction's rules the Realized & tax tab
    # applies and which currency the ledger is replayed in (see
    # stocks.portfolio.tax). None = auto, resolved from the browser region.
    # The rest are bracket inputs only some jurisdictions read.
    "tax_residence": None,
    "tax_filing_status": "single",
    "tax_other_income": 0.0,
    "tax_niit": False,
    "tax_subnational_rate": 0.0,
    # Whether the assistant drawer was open when the tab was last rendered, so
    # a reload puts the reader back in the conversation instead of behind the
    # launcher icon. Written by chat_core.render_side_panel.
    "chat_panel_open": False,
}


def stored_prefs(prefs: Path) -> dict:
    """The stored half of a prefs file — no defaults merged in.

    Anything unreadable reads as {}. A corrupt settings file must not stop an
    account being served: it means "nothing was expressed", which is where a
    brand-new account starts anyway.
    """
    try:
        stored = json.loads(prefs.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return stored if isinstance(stored, dict) else {}


def load_prefs(prefs: Path) -> dict:
    """This account's preferences with the defaults filled in.

    A fresh dict every call: callers mutate what they get back and hand it to
    `save_prefs`, so sharing one would let one caller's half-made edit surface
    in another's.
    """
    return {**DEFAULT_PREFS, **stored_prefs(prefs)}


class GuestIsReadOnly(RuntimeError):
    """A write was aimed at the shared guest directory."""


def writable(path: Path) -> Path:
    """`path`, unless it sits inside the shared guest dir.

    One directory serves every anonymous visitor on the deployment, so a write
    there is a write into everybody's session at once — and prefs.json is where
    exactly that has already happened once (`web.auth.push_recent_search` wrote
    a guest's searches into the file the next guest reads).

    The guard lives here rather than in every caller because the callers *are*
    the problem: a helper that saves a setting is easy to reach from a code path
    that never asked who is asking, and "every write path sits behind a login
    check" is a rule people have to remember. This one they cannot forget.

    Provisioning is exempt by construction rather than by a flag — it writes the
    watchlist through `restore_account` and the ledger through `demo.seed`,
    neither of which comes through here.
    """
    resolved = path.resolve()
    if GUEST_DIR.resolve() in (resolved, *resolved.parents):
        raise GuestIsReadOnly(f"the guest directory is read-only: {path}")
    return path


def save_prefs(
    prefs: Path, values: dict, persist: Callable[[Path], None] | None = None
) -> None:
    """Write the whole prefs file, then mirror it to the bucket."""
    writable(prefs).write_text(json.dumps(values, indent=2))
    (persist or storage.persist)(prefs)


def update_prefs(
    prefs: Path, changes: dict, persist: Callable[[Path], None] | None = None
) -> dict:
    """Merge `changes` into the stored file and write it back. Returns the whole.

    Read-modify-write over the file rather than a write of the changed keys
    alone, because the file is the unit the app stores: rewriting one key would
    drop whatever a concurrent Streamlit run had just saved beside it. The read
    happens here, immediately before the write, to keep that window as short as
    this design allows — two writers racing is still last-write-wins, which is
    what a settings screen has always been.
    """
    stored = stored_prefs(prefs)
    stored.update(changes)
    save_prefs(prefs, stored, persist)
    return {**DEFAULT_PREFS, **stored}


# ------------------------------------------------------------ recent searches
# The last few tickers this account opened from the search box. Stored in
# prefs.json like every other per-account setting, and read here by path so
# the ASGI worker can serve them without a Streamlit session to resolve.

RECENT_SEARCHES_MAX = 5


def load_recent_searches(prefs: Path) -> list[str]:
    """The account's recent tickers, newest first; [] for anything unreadable.

    A corrupt or missing prefs file reads as "no history", which is the same
    thing the search box shows a brand-new account.
    """
    try:
        stored = json.loads(prefs.read_text()).get("recent_searches", [])
    except Exception:
        return []
    if not isinstance(stored, list):
        return []
    return [str(t) for t in stored][:RECENT_SEARCHES_MAX]


def push_recent_search(
    prefs: Path, ticker: str, persist: Callable[[Path], None] | None = None
) -> list[str]:
    """Move `ticker` to the front of the recent list, deduped and capped.

    Read-modify-write over the whole prefs file, because that is the unit the
    app stores: rewriting only this key would drop every setting a concurrent
    Streamlit run had just saved. Returns the new list.
    """
    t = ticker.strip().upper()
    if not t:
        return load_recent_searches(prefs)
    try:
        stored = json.loads(prefs.read_text())
    except Exception:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    rest = [x for x in load_recent_searches(prefs) if x != t]
    recent = [t, *rest][:RECENT_SEARCHES_MAX]
    stored["recent_searches"] = recent
    # Not through save_prefs, so the guard has to be stated again here. This is
    # the exact shape of the bug it exists for: a helper that writes prefs,
    # reached from a path that never asked who is asking.
    writable(prefs).write_text(json.dumps(stored, indent=2))
    (persist or storage.persist)(prefs)
    return recent


STARTER_WATCHLIST = """\
# Personal watchlist — managed from the Profile page.
#
# These are examples to explore with, not holdings: replace them with the
# tickers you actually follow. Nothing here counts as a position.
#
# Per-entry fields:
#   favorite: true   -> pinned to top of the dashboard + quick-access buttons
#   tags: [Tech]     -> groups the dashboard expanders and the earnings filters
#   shares: 12       -> makes it a real position (portfolio weights by value)
#   cost: 145.30     -> average buy price/share, for unrealised P/L
watchlist:
  - ticker: AAPL
    name: Apple
    favorite: true
    tags: [Tech]
  - ticker: MSFT
    name: Microsoft
    tags: [Tech]
  - ticker: NVDA
    name: Nvidia
    favorite: true
    tags: [Tech]
  - ticker: ASML
    name: ASML Holding
    tags: [Europe]
  - ticker: NVO
    name: Novo Nordisk
    tags: [Europe]
  - ticker: ITX.MC
    name: Inditex
    tags: [Europe]
  - ticker: TSM
    name: Taiwan Semiconductor
  - ticker: JPM
    name: JPMorgan Chase
  - ticker: XOM
    name: Exxon Mobil
  - ticker: BTC-EUR
    name: Bitcoin
"""
