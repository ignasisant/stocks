"""Login gate and per-user data resolution for the web app.

Authentication is the app's own Google OIDC flow (stocks.web.oidc), configured
in .streamlit/secrets.toml under [auth] — see the README "Login (web app)"
section for the required keys. The session it mints is a signed cookie that
`stocks.session` owns and that both front ends read: these pages off
`st.context.cookies`, the React shell off the API. Nothing here calls st.login
or reads st.user, so the identity a page renders and the identity `/api/v1`
resolves cannot disagree.

Browsing is public: app.py calls resolve_user() before building the
navigation, which maps anonymous visitors to a shared read-only guest dir
(data/users/_guest/) seeded with the starter watchlist and the demo ledger.
Login is required only where personal data is read or written — the Import
and Profile pages call require_login() at the top, the Portfolio page calls
require_login_or_demo() (own book signed in, demo book as a guest), and
mutating widgets (favorites, tags, watchlist editor) check is_logged_in().

Every account gets its own data under data/users/<slug>/ — watchlist.yaml,
portfolio.db, last_import.json, prefs.json — keyed by the verified OIDC
email. The optional [app].owner_email account maps to the repo-root files
instead (watchlist.yaml, data/portfolio.db), so the CLI — which is
single-user and always works on the root files — stays in sync with the
owner's web session. Broker-code aliases stay global (root watchlist.yaml):
they're reference data, not personal data.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import streamlit as st

from stocks import accounts, session, storage
from stocks import watchlist as wl
from stocks.chat import memory
from stocks.config import (
    CURRENCIES,
    PROJECT_ROOT,
    stat_key,
    yaml_dump,
    yaml_load,
)
from stocks.portfolio import demo
from stocks.web import css
from stocks.web.i18n import t as tr

RECENT_SEARCHES_MAX = accounts.RECENT_SEARCHES_MAX
DEFAULT_PREFS = accounts.DEFAULT_PREFS

# Account identity and per-account paths live in `stocks.accounts`, which has
# no Streamlit in it, so the HTTP API (stocks.api) and the headless jobs can
# resolve the same directories a browser session does without importing a UI
# framework. Re-exported here because every call site in web/ — and every test
# — reaches for them through `auth.`.
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
    """Mirror to the bucket after a committed local write. Cloud failure
    must not crash the interaction — but surface it: the local copy is
    fine now and still vanishes on the next container restart."""
    try:
        storage.persist(path)
    except Exception:
        st.toast(tr("common.sync_failed"), icon=":material/cloud_off:")


def ensure_user_data(paths: UserPaths, legacy_root: Path | None = None) -> bool:
    """`accounts.restore_account` plus this app's answer to a bucket outage.

    Returns True when this call seeded a brand-new account — the one moment a
    signup can be dated exactly, which mark_login() records.

    The work itself (legacy-dir migration, bucket pull, starter watchlist) is
    in `stocks.accounts`, shared with the API and the cron jobs. What stays
    here is the only Streamlit-shaped part of it: a restore failure fails
    closed, and for a browser session that means saying so and halting the
    script — falling through would show an empty book whose next save
    overwrites the account's real cloud data. The seeded watchlist's push goes
    through `_persist`, so a cloud blip there is a toast and not a dead page.
    """
    try:
        return accounts.restore_account(paths, legacy_root, persist=_persist)
    except accounts.StorageUnavailable:
        st.error(tr("common.storage_restore_failed"), icon=":material/cloud_off:")
        st.stop()


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

    if storage.enabled():
        prefix = root.relative_to(PROJECT_ROOT.resolve()).as_posix()
        for key in storage.list_keys(prefix + "/"):
            storage.delete_key(key)
    if root.exists():
        import shutil

        shutil.rmtree(root)


def _jar() -> dict[str, str]:
    """This session's cookies, or {} when there is no browser to have any.

    Streamlit hands back the cookies from the request that opened the
    websocket. That is not a limitation here: the session cookie only ever
    changes on a redirect, and a redirect is a full document navigation that
    starts a new session — so what a page reads is always current. (st.user had
    exactly the same property; it was bound at connect too.)

    No cookies at all means no browser — AppTest, bare mode — not a blocked
    one, the same reading `import_transactions` makes of the XSRF cookie.
    """
    try:
        return dict(st.context.cookies)
    except Exception:
        return {}


@lru_cache(maxsize=32)
def _verified_claims(ours: str, legacy: str, secret: str) -> dict:
    """Verify once per distinct cookie: is_logged_in() is called per row.

    `secret` is not used — it is in the signature so a rotated (or, in a test,
    a monkeypatched) key is a different cache entry rather than a stale hit.
    The result is shared by every caller, so nobody may mutate it.
    """
    del secret
    return session.claims({session.COOKIE: ours, session.LEGACY_COOKIE: legacy}) or {}


def current_claims() -> dict:
    """The identity claims this session carries, or {} for a guest."""
    jar = _jar()
    return _verified_claims(
        jar.get(session.COOKIE, ""),
        jar.get(session.LEGACY_COOKIE, ""),
        session.signing_secret(),
    )


def is_logged_in() -> bool:
    """True when an authenticated identity with a verified email is present.

    All personal data is keyed to the email claim, so an unverified address
    must never resolve to a data dir — an IdP that skips verification would
    otherwise let anyone claim someone else's account. Google always sends
    email_verified=true for its accounts.

    This has to keep agreeing with `stocks.session.signed_in_email`, which is
    what the API answers with; both now read the same cookie through the same
    verifier, so agreeing is structural rather than a thing to remember.
    """
    claims = current_claims()
    return bool(session.verified(claims.get("email_verified")) and claims.get("email"))


def current_email() -> str:
    """The signed-in account's email, or "" for a guest. One accessor so
    callers (and tests) never have to reach into the cookie themselves.

    Lower-cased, because the mint lower-cases: the API keys directories off
    this string and the two must name the same account."""
    return str(current_claims().get("email") or "").strip()


def current_name() -> str:
    """The display name Google gave, falling back to the address."""
    return str(current_claims().get("name") or "").strip() or current_email()


def current_picture() -> str:
    """The Google avatar URL, or "" when the identity carries none."""
    return str(current_claims().get("picture") or "").strip()


# ------------------------------------------------------- login accounting
# Cloud Logging keeps 30 days, so "how many accounts exist" is not a question
# the logs can answer — anyone who signed up and never came back has aged out
# of them. Each account's own prefs.json carries the two dates that can, and
# `stocks users` reads them straight out of the bucket. telemetry.bind_run
# turns the same verdict into auth.signup/auth.login events, so a signup is
# also visible in place on the log timeline.


def mark_login(paths: UserPaths, *, seeded: bool = False, email: str = "") -> str:
    """Stamp this account's first/last login; return "signup" or "login".

    The bookkeeping itself is `accounts.stamp_login`, shared with the OIDC
    callback and the API so a React sign-in and a Streamlit one date an account
    the same way. What stays here is the Streamlit-shaped part: the bucket push
    goes through `_persist`, so a cloud blip is a toast and not a dead page.
    """
    return accounts.stamp_login(paths, seeded=seeded, email=email, persist=_persist)


def resolve_user() -> UserPaths:
    """Resolve the session's data paths without gating; call before the nav.

    Logged-in accounts get their own dir (owner → repo-root files); anonymous
    visitors get the shared guest dir so the public pages can render. Stores
    the paths in session state for the page modules.
    """
    legacy = None
    logged_in = is_logged_in()
    email = ""
    if logged_in:
        email = current_email()
        owner = str(st.secrets.get("app", {}).get("owner_email", "")).strip() or None
        paths = paths_for(email, owner)
        if paths.root != PROJECT_ROOT:  # owner uses repo-root files, no slug
            legacy = USERS_DIR / _legacy_slug(email)
    else:
        paths = guest_paths()
    seeded = ensure_user_data(paths, legacy_root=legacy)
    # Streamlit reruns this on every interaction; the guard keeps the stamp
    # (and its prefs read) to the first run under a given identity, and a
    # sign-out clears it so a later sign-in is evaluated again.
    if not logged_in:
        st.session_state.pop("_login_marked", None)
        st.session_state["_login_kind"] = ""
    elif st.session_state.get("_login_marked") != email:
        st.session_state["_login_marked"] = email
        st.session_state["_login_kind"] = mark_login(paths, seeded=seeded,
                                                     email=email)
    st.session_state["user_paths"] = paths
    return paths


def auth_configured() -> bool:
    """Whether an IdP is configured ([auth] in secrets).

    Membership on st.secrets *raises* when there is no secrets file at all —
    a fresh clone, a CI checkout — so every caller needs this guard, not a
    bare `in`.
    """
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def _partially_signed_in() -> bool:
    """An OIDC identity that is present but not usable: no email claim, or an
    unverified one. is_logged_in() says False for both, and they must not be
    quietly downgraded to a guest session — require_login() names them."""
    return bool(current_claims()) and not is_logged_in()


def seed_guest_demo(paths: UserPaths) -> None:
    """Put the demo book in the guest ledger, so the app can be tried without
    an account.

    Everything on the Portfolio page derives from a ledger, so the page the
    app is *about* used to be a login screen for anyone who had not signed in
    yet. The demo book (stocks.portfolio.demo) answers that: invented trades
    on roughly the real closes, every row stamped `demo`, under a banner that
    says whose they are.

    The guest dir is shared by every anonymous visitor, which is precisely why
    this is the only thing ever written there: no import, no clear button, no
    prefs writes — the demo book is identical for everyone, so one shared copy
    is the same page for all of them. seed() is a no-op on a ledger that holds
    anything, so concurrent guests cannot stack a second copy, and a failure
    here is not worth a crash: the page falls back to its empty state.
    """
    if st.session_state.get("_guest_demo_seeded"):
        return
    try:
        demo.seed(paths.db)
    except Exception:
        pass
    st.session_state["_guest_demo_seeded"] = True


def require_login_or_demo() -> UserPaths:
    """The Portfolio page's gate: this account's own book, or the demo one.

    A signed-in visitor goes through require_login() unchanged. An anonymous
    one is not stopped: they get the shared guest dir with the demo book in
    it (seed_guest_demo), because "look at it before you hand over a real
    statement" is worth more than a login screen on the app's main page. The
    page tells them whose numbers those are, and every write it offers stays
    behind is_logged_in().
    """
    if is_logged_in() or _partially_signed_in():
        return require_login()
    # app.py resolves the session's paths before the nav; standalone runs
    # (AppTest, a direct page run) have not, so fall back to resolving here.
    paths = st.session_state.get("user_paths") or resolve_user()
    seed_guest_demo(paths)
    return paths


def _log_out_button() -> None:
    """The sign-out control, as a link rather than a callback.

    Signing out is a navigation to `/auth/logout`: the server clears the cookie
    and redirects, and the new document is what the pages read their identity
    from. A callback could not do it — `st.context.cookies` is bound at connect,
    so clearing without a fresh document would leave the page believing it is
    still signed in.
    """
    st.link_button(tr("common.log_out"), session.LOGOUT_PATH, icon=":material/logout:")


def require_login() -> UserPaths:
    """Auth gate for pages that write personal data (Import, Profile) —
    public pages never call it, and the Portfolio page goes through
    require_login_or_demo() so a guest reads the demo book instead.

    Renders the sign-in screen (or setup help while [auth] secrets are
    missing) and st.stop()s until an authenticated identity with an email is
    present. On success, seeds the account's data dir and stores its paths in
    session state for the page modules.
    """
    if "auth" not in st.secrets:
        st.error(tr("auth.not_configured"), icon=":material/lock:")
        st.markdown(tr("auth.setup_help"))
        st.stop()

    claims = current_claims()
    if not claims:
        _login_screen()
        st.stop()

    if not str(claims.get("email") or "").strip():
        st.error(tr("auth.no_email"))
        _log_out_button()
        st.stop()

    # Must mirror is_logged_in(): without this branch an unverified identity
    # would silently fall through resolve_user() onto the guest paths.
    if not session.verified(claims.get("email_verified")):
        st.error(tr("auth.email_unverified"))
        _log_out_button()
        st.stop()

    return resolve_user()


# Google's "G" mark isn't in Material Symbols, so it's drawn onto the sign-in
# button as a CSS ::before tile (white rounded square, brand-guideline style).
# Angle brackets are %-encoded: the URI is interpolated into _LOGIN_CSS, and
# DOMPurify silently drops a whole style block whose text contains a raw "<".
_GOOGLE_G_SVG = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'%3E"
    "%3Cpath fill='%234285F4' d='M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94"
    "c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z'/%3E"
    "%3Cpath fill='%2334A853' d='M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6"
    "c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19"
    "C6.51 42.62 14.62 48 24 48z'/%3E"
    "%3Cpath fill='%23FBBC05' d='M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59"
    "s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78"
    "l7.97-6.19z'/%3E"
    "%3Cpath fill='%23EA4335' d='M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85"
    "C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19"
    "C12.43 13.72 17.74 9.5 24 9.5z'/%3E"
    "%3C/svg%3E"
)

_LOGIN_CSS = f"""\
<style>
[class*="st-key-google_signin"] :is(button, a)::before {{
    content: "";
    flex: 0 0 auto;
    width: 1.25rem;
    height: 1.25rem;
    margin-right: 0.4rem;
    border-radius: var(--ag-radius-xs);
    /* Brand exception, not a DS neutral: Google's sign-in guidelines require
       the "G" on pure white. Declared as widgets.BRAND_GOOGLE_TILE and read
       here through the custom property — this module can't import widgets
       (widgets imports auth), and app.py emits the tokens long before the
       login gate renders. */
    background-color: var(--ag-brand-google-tile, #fff);
    background-image: url("{_GOOGLE_G_SVG}");
    background-repeat: no-repeat;
    background-position: center;
    background-size: 0.85rem;
}}
</style>
"""


def _login_screen() -> None:
    css.inject(_LOGIN_CSS)
    st.space("xlarge")
    with st.container(horizontal_alignment="center"):
        with st.container(border=True, width=420, horizontal_alignment="center"):
            st.space("xsmall")
            st.image(
                str(Path(__file__).parent / "assets" / "topstocks-logo.svg"),
                width=200,
            )
            st.caption(
                tr("auth.tagline"),
                text_alignment="center",
            )
            st.space("xsmall")
            st.markdown(
                tr("auth.signin_prompt"),
                text_alignment="center",
            )
            st.link_button(
                tr("common.sign_in_google"),
                session.LOGIN_PATH,
                type="primary",
                key="google_signin",
                width="stretch",
            )
            st.caption(
                tr("auth.browsing_public"),
                text_alignment="center",
            )
            st.space("xsmall")


# ---------------------------------------------------------------- accessors
# Set by resolve_user() in app.py (guest paths when anonymous); pages run
# after it via st.navigation.


def user_paths() -> UserPaths:
    return st.session_state["user_paths"]


def watchlist_path() -> Path:
    return user_paths().watchlist


def db_path() -> Path:
    return user_paths().db


def chat_path() -> Path:
    return user_paths().chat


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


def load_prefs(path: Path | None = None) -> dict:
    """This account's preferences, defaults filled in.

    Read on nearly every rerun by a dozen callers (the language resolver, the
    setup card, the tour, the chat panel), so the file read and parse are
    memoized while the merge stays per-call: the result is mutable and callers
    edit it in place before `save_prefs`.
    """
    p = path or user_paths().prefs
    return {**DEFAULT_PREFS, **_prefs_stored(p, stat_key(p))}


def save_prefs(prefs: dict, path: Path | None = None) -> None:
    p = path or user_paths().prefs
    accounts.save_prefs(p, prefs, persist=_persist)


# ------------------------------------------------------ daily action card


def load_action(path: Path | None = None) -> dict:
    """The stored daily-action card as a raw dict ({} when there is none).

    Shaped like load_prefs: unreadable or corrupt reads as "nothing stored",
    which sends the dashboard down the regenerate path instead of an error.
    """
    p = path or user_paths().action
    try:
        out = json.loads(p.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


def save_action(card: dict, path: Path | None = None) -> None:
    """Store today's card, mirrored to the bucket like every other user file.

    Worth the round trip for one small JSON: the card costs an LLM call, and
    Cloud Run recycles the container on idle — without the mirror every cold
    start would spend another unit of the free allowance on a card the account
    already has.
    """
    p = path or user_paths().action
    p.write_text(json.dumps(card, indent=2))
    _persist(p)


# ------------------------------------------------------ sector verdicts


def load_verdicts(path: Path | None = None) -> dict:
    """The stored per-sector AI reads, keyed by sector name ({} when none).

    Same contract as load_action: unreadable or corrupt reads as "nothing
    stored", which sends the page down the regenerate path, not an error page.
    """
    p = path or user_paths().verdicts
    try:
        out = json.loads(p.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


def save_verdicts(verdicts: dict, path: Path | None = None) -> None:
    """Store every sector's verdict, mirrored to the bucket.

    One file rather than one per sector: eleven of them at a few hundred bytes
    each is still one small JSON, and one bucket key is one round trip instead
    of eleven. A verdict costs a unit of the account's daily allowance, so
    losing the file to a container recycle would charge the reader twice for
    the same paragraph.
    """
    p = path or user_paths().verdicts
    p.write_text(json.dumps(verdicts, indent=2))
    _persist(p)


# ------------------------------------------------------- recent searches
# The top-bar search remembers the last few tickers the user clicked to
# explore, so refocusing the empty field can offer them again (survives
# reload — stored in prefs like every other per-user setting).


def load_recent_searches(prefs: dict | None = None) -> list[str]:
    p = prefs if prefs is not None else load_prefs()
    val = p.get("recent_searches", [])
    if not isinstance(val, list):
        return []
    return [str(t) for t in val][:RECENT_SEARCHES_MAX]


def push_recent_search(ticker: str) -> None:
    """Move `ticker` to the front of the recent list, deduped, capped.

    Signed-in accounts only. The top bar draws for everybody, so without this
    guard an anonymous visitor's searches were written into the shared guest
    dir's prefs.json — and read back out of it in the next anonymous visitor's
    dropdown, on a file that is also mirrored to the bucket. A guest's recent
    list lives nowhere, which is the same bargain the tour and the dismissed
    banners already make (see `onboarding._save`).
    """
    t = ticker.strip().upper()
    if not t or not is_logged_in():
        return
    prefs = load_prefs()
    rest = [x for x in load_recent_searches(prefs) if x != t]
    prefs["recent_searches"] = [t, *rest][:RECENT_SEARCHES_MAX]
    save_prefs(prefs)


# ------------------------------------------------------- investor profile
# Who the assistant is advising, stated by the user (not hard-coded). Stored
# under prefs["investor_profile"] as stable enum keys (locale-independent, so
# the English system prompt stays stable whatever the UI language) plus a free
# notes field. chat_core reads it to build the assistant persona; empty ->
# chat_core falls back to its historical default line.

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


def load_profile(prefs: dict | None = None) -> dict:
    """The account's investor profile, defaults filled in for missing fields.

    `set` is True once the user has saved the form at least once; callers use
    it to tell a real (possibly minimal) profile from the mere defaults.
    """
    prefs = prefs if prefs is not None else load_prefs()
    stored = prefs.get("investor_profile") or {}
    return {**_PROFILE_DEFAULTS, **stored, "set": bool(stored.get("set"))}


def profile_is_set(prefs: dict | None = None) -> bool:
    prefs = prefs if prefs is not None else load_prefs()
    return bool((prefs.get("investor_profile") or {}).get("set"))


def save_profile(profile: dict) -> None:
    prefs = load_prefs()
    prefs["investor_profile"] = {**profile, "set": True}
    save_prefs(prefs)


def render_profile_form(key_prefix: str, *, cell=None) -> dict:
    """Draw the investor-profile widgets and return the collected values.

    Shared by the Profile page and the first-login dialog, in two layouts from
    one implementation. `cell` is a callable `(field_id, label, help) ->
    container` naming where a field's control goes: the Profile page hands
    back a setting row (label and explanation in the left gutter, control on
    the right), so the widgets draw with their own labels collapsed. Left at
    None — the first-login dialog, which is too narrow for a 260px label
    gutter — each widget draws its own label and the fields stack.

    Does not persist: the Profile page autosaves on a real difference, the
    dialog has its own Save button. Both call save_profile().
    """
    cur = load_profile()

    def _slot(field: str, label: str, help_text: str = ""):
        """Where one field draws, and whether it carries its own label.

        In a setting row the explanation is already printed under the label,
        so the widget collapses both; stacked in the dialog it keeps its label
        and the explanation rides in the tooltip.
        """
        if cell is None:
            return st, {"help": help_text}
        return cell(field, label, help_text), {"label_visibility": "collapsed"}

    # The two scales are segmented controls rather than radios: a row of chips
    # reads as one axis, and it is the control the Preferences tab already
    # uses. required=True keeps a selection at all times — clicking the active
    # chip off would otherwise hand back None, a state this profile has no
    # meaning for.
    _risk_at, _risk_kw = _slot("risk", tr("profile.iv_risk"), tr("profile.iv_risk_help"))
    risk = _risk_at.segmented_control(
        tr("profile.iv_risk"),
        PROFILE_RISK,
        default=cur["risk"] if cur["risk"] in PROFILE_RISK else _PROFILE_DEFAULTS["risk"],
        required=True,
        format_func=lambda k: tr(f"profile.iv_risk_{k}"),
        key=f"{key_prefix}_risk",
        **_risk_kw,
    )
    _hz_at, _hz_kw = _slot(
        "horizon", tr("profile.iv_horizon"), tr("profile.iv_horizon_help")
    )
    horizon = _hz_at.segmented_control(
        tr("profile.iv_horizon"),
        PROFILE_HORIZON,
        default=cur["horizon"]
        if cur["horizon"] in PROFILE_HORIZON
        else _PROFILE_DEFAULTS["horizon"],
        required=True,
        format_func=lambda k: tr(f"profile.iv_horizon_{k}"),
        key=f"{key_prefix}_horizon",
        **_hz_kw,
    )
    _focus_at, _focus_kw = _slot(
        "focus", tr("profile.iv_focus"), tr("profile.iv_focus_help")
    )
    focus = _focus_at.multiselect(
        tr("profile.iv_focus"),
        PROFILE_FOCUS,
        default=[f for f in cur["focus"] if f in PROFILE_FOCUS],
        format_func=lambda k: tr(f"profile.iv_focus_{k}"),
        placeholder=tr("profile.iv_pick_ph"),
        key=f"{key_prefix}_focus",
        **_focus_kw,
    )
    _cons_at, _cons_kw = _slot(
        "constraints", tr("profile.iv_constraints"), tr("profile.iv_constraints_help")
    )
    constraints = _cons_at.multiselect(
        tr("profile.iv_constraints"),
        PROFILE_CONSTRAINTS,
        default=[c for c in cur["constraints"] if c in PROFILE_CONSTRAINTS],
        format_func=lambda k: tr(f"profile.iv_constraints_{k}"),
        placeholder=tr("profile.iv_pick_ph"),
        key=f"{key_prefix}_constraints",
        **_cons_kw,
    )
    _notes_at, _notes_kw = _slot(
        "notes", tr("profile.iv_notes"), tr("profile.iv_notes_help")
    )
    notes = _notes_at.text_area(
        tr("profile.iv_notes"),
        value=cur["notes"],
        placeholder=tr("profile.iv_notes_ph"),
        key=f"{key_prefix}_notes",
        **_notes_kw,
    )
    # Both lists come back in click order. Normalising them to the option
    # order makes an untouched form compare equal to what is stored, which is
    # what lets the Profile page autosave on a difference without writing (and
    # toasting) on every rerun.
    return {
        "risk": risk,
        "horizon": horizon,
        "focus": [f for f in PROFILE_FOCUS if f in focus],
        "constraints": [c for c in PROFILE_CONSTRAINTS if c in constraints],
        "notes": notes.strip(),
    }


def maybe_prompt_profile() -> bool:
    """First load per session: pop the investor-profile setup dialog.

    Fires once per session for a signed-in account that hasn't saved a profile
    yet; "Skip for now" just closes it (the session flag stops it re-popping),
    so it nudges again next session until the profile is filled or the user
    completes it from the Profile page. No-op otherwise.

    Returns whether the dialog was opened — app.py stands the page down while
    it is up, because a modal is a full-screen tap blocker and the page
    rendering behind it takes the presses meant for Skip with it.
    """
    if "auth" not in st.secrets or not is_logged_in():
        return False
    if profile_is_set() or st.session_state.get("_profile_prompt_seen"):
        return False
    st.session_state["_profile_prompt_seen"] = True
    # Built at call time (not @st.dialog) so the title resolves in the run's
    # active language rather than freezing at import — same as the login modal.
    st.dialog(tr("profile.iv_dialog_title"))(_profile_dialog_body)()
    return True


def _profile_dialog_body() -> None:
    st.markdown(tr("profile.iv_dialog_intro"))
    profile = render_profile_form("iv_dialog")
    save_col, skip_col = st.columns(2)
    if save_col.button(
        tr("profile.iv_save"), type="primary", key="iv_dialog_save", width="stretch"
    ):
        save_profile(profile)
        st.rerun()  # close the modal; profile_is_set() now True -> never re-pops
    if skip_col.button(tr("profile.iv_skip"), key="iv_dialog_skip", width="stretch"):
        st.rerun()  # close; the seen-flag keeps it shut for the rest of the session


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
_TITLE_MAX = 80


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


def load_book(path: Path | None = None) -> dict:
    """Every conversation for the account, in the current shape.

    Never writes — a turn that fails must leave chat.json untouched (and
    absent when it never existed). A v1 file (the bare list of turns the
    single-thread assistant wrote) migrates to one conversation; anything
    missing or corrupt yields a fresh empty book.
    """
    p = path or user_paths().chat
    try:
        data = json.loads(p.read_text())
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


def _pruned(book: dict) -> dict:
    """The book capped at MAX_CONVERSATIONS, dropping least-recently-used
    threads first and never the active one."""
    convs = book["conversations"]
    if len(convs) <= MAX_CONVERSATIONS:
        return book
    ranked = sorted(convs, key=lambda c: c.get("updated") or "", reverse=True)
    keep = [c for c in ranked if c["id"] == book["active"]][:1]
    keep += [c for c in ranked if c["id"] != book["active"]][
        : MAX_CONVERSATIONS - len(keep)
    ]
    order = {c["id"]: i for i, c in enumerate(convs)}
    return {**book, "conversations": sorted(keep, key=lambda c: order[c["id"]])}


def save_book(book: dict, path: Path | None = None) -> None:
    p = path or user_paths().chat
    p.write_text(json.dumps(_pruned(book), indent=2))
    _persist(p)


def _active(book: dict) -> dict:
    """The active conversation — load_book guarantees one exists."""
    for c in book["conversations"]:
        if c["id"] == book["active"]:
            return c
    return book["conversations"][0]


def load_chat(path: Path | None = None) -> list[dict]:
    """The active conversation's turns (the historical single-thread API)."""
    return _active(load_book(path))["messages"]


def memory_path(path: Path | None = None) -> Path:
    """The account's long-term chat index, beside its chat history."""
    return (path or user_paths().chat).parent / memory.FILE


def save_chat(history: list[dict], path: Path | None = None) -> None:
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


def list_conversations(path: Path | None = None) -> list[dict]:
    """Conversation metadata (no message bodies), most recently used first."""
    book = load_book(path)
    metas = [
        {
            "id": c["id"], "title": c["title"], "title_auto": c["title_auto"],
            "created": c["created"], "updated": c["updated"],
            "messages": len(c["messages"]), "active": c["id"] == book["active"],
        }
        for c in book["conversations"]
    ]
    return sorted(metas, key=lambda m: m["updated"], reverse=True)


def active_conversation(path: Path | None = None) -> dict:
    """Metadata of the conversation the next turn will land in."""
    c = _active(load_book(path))
    return {k: v for k, v in c.items() if k != "messages"}


def new_conversation(path: Path | None = None, title: str = "") -> str:
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


def set_active_conversation(cid: str, path: Path | None = None) -> None:
    book = load_book(path)
    if any(c["id"] == cid for c in book["conversations"]):
        book["active"] = cid
        save_book(book, path)


def rename_conversation(cid: str, title: str, path: Path | None = None) -> None:
    """User-set title — pins it, so auto-titling never overwrites it again."""
    book = load_book(path)
    for c in book["conversations"]:
        if c["id"] == cid:
            c["title"] = title.strip()[:_TITLE_MAX]
            c["title_auto"] = False
            save_book(book, path)
            return


def autotitle_conversation(cid: str, title: str, path: Path | None = None) -> None:
    """Title derived from the opening exchange; a no-op on a renamed thread."""
    book = load_book(path)
    for c in book["conversations"]:
        if c["id"] == cid and c.get("title_auto", True):
            c["title"] = title.strip()[:_TITLE_MAX]
            save_book(book, path)
            return


def delete_conversation(cid: str, path: Path | None = None) -> None:
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


def reporting_currency() -> str:
    """The currency the app reckons in for this account.

    Not a display setting any more: the ledger is replayed *in* this currency
    (every leg at its own trade-date rate), so the figures are computed in it
    rather than converted afterwards. The tax tab is the one exception — it
    follows the tax residence, which is a legal fact rather than a preference.
    """
    ccy = str(load_prefs().get("currency", "EUR")).upper()
    return ccy if ccy in CURRENCIES else "EUR"


# ---------------------------------------------------------------- watchlist


def focus_suggestions(
    profile: dict | None = None, path: Path | None = None
) -> list[dict]:
    """Example rows for the account's declared focus that it does not have yet.

    Returns `save_watchlist_entries` rows, in `FOCUS_EXAMPLES` order, with
    everything already on the watchlist filtered out — so the offer shrinks as
    it is taken up and disappears once there is nothing left to add. Empty
    whenever no focus is declared, which is what keeps this off the page for
    an account that skipped the profile.
    """
    from stocks.config import load_watchlist  # local: same reason as all_tags

    p = profile if profile is not None else load_profile()
    have = {h.ticker.upper() for h in load_watchlist(path or watchlist_path())}
    out: list[dict] = []
    for area in p.get("focus") or []:
        for ticker, name, tag in FOCUS_EXAMPLES.get(area, ()):
            if ticker.upper() in have:
                continue
            have.add(ticker.upper())  # a ticker in two areas is offered once
            out.append({"ticker": ticker, "name": name, "tags": [tag]})
    return out


def save_watchlist_entries(entries: list[dict], path: Path | None = None) -> None:
    """Rewrite the watchlist from the profile editor's rows.

    The editor covers ticker/name/favorite/shares/cost/tags; per-ticker alert
    rules and the top-level aliases map are YAML-only, so they're carried
    over untouched for tickers that survive the edit. Rows without a "tags"
    key keep their existing tags too (rows with one — even an empty list —
    set them). Rows without a ticker are dropped; tickers are upper-cased
    and de-duplicated (first row wins).
    """
    p = path or watchlist_path()
    raw = yaml_load(p.read_text()) if p.exists() else {}
    old_alerts = {
        str(item.get("ticker", "")).upper(): item.get("alerts")
        for item in (raw.get("watchlist") or [])
        if item.get("alerts")
    }
    old_tags = {
        str(item.get("ticker", "")).upper(): item.get("tags")
        for item in (raw.get("watchlist") or [])
        if item.get("tags")
    }

    items: list[dict] = []
    seen: set[str] = set()
    for e in entries:
        ticker = str(e.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        item: dict = {"ticker": ticker}
        name = str(e.get("name") or "").strip()
        if name:
            item["name"] = name
        if e.get("favorite"):
            item["favorite"] = True
        shares = e.get("shares")
        if shares:
            item["shares"] = float(shares)
        cost = e.get("cost")
        if cost:
            item["cost"] = float(cost)
        tags = e.get("tags")
        if tags is not None:
            clean = _clean_tags(tags)
            if clean:
                item["tags"] = clean
        elif ticker in old_tags:
            item["tags"] = old_tags[ticker]
        if ticker in old_alerts:
            item["alerts"] = old_alerts[ticker]
        items.append(item)

    raw["watchlist"] = items
    p.write_text(yaml_dump(raw))
    _persist(p)


# ------------------------------------------------------- favorites and tags
# Bindings over `stocks.watchlist`, which holds the edits themselves with no
# Streamlit in it so the HTTP API can make the same ones. Everything here adds
# the two things a page needs and a headless caller does not: the session's own
# watchlist path, and `_persist`, which turns a bucket outage into a toast
# instead of an exception.

_clean_tags = wl.clean_tags


def _update_entry(ticker: str, mutate, path: Path | None = None) -> dict:
    return wl.update_entry(path or watchlist_path(), ticker, mutate, persist=_persist)


def toggle_favorite(ticker: str, path: Path | None = None) -> bool:
    """Flip a ticker's favorite flag; returns the new state."""
    return wl.toggle_favorite(path or watchlist_path(), ticker, persist=_persist)


def set_favorite(ticker: str, value: bool, path: Path | None = None) -> None:
    """Set (not flip) a ticker's favorite flag."""
    wl.set_favorite(path or watchlist_path(), ticker, value, persist=_persist)


def set_tags(ticker: str, tags: list[str], path: Path | None = None) -> list[str]:
    """Replace a ticker's tags; an empty list removes the key entirely."""
    return wl.set_tags(path or watchlist_path(), ticker, tags, persist=_persist)


def set_name(ticker: str, name: str, path: Path | None = None) -> None:
    """Set (or clear, with an empty string) a ticker's display label."""
    wl.set_name(path or watchlist_path(), ticker, name, persist=_persist)


def rename_tag(old: str, new: str, path: Path | None = None) -> int:
    """Rename a tag group across every holding that carries it."""
    return wl.rename_tag(path or watchlist_path(), old, new, persist=_persist)


def delete_tag(tag: str, path: Path | None = None) -> int:
    """Drop a tag group, keeping its members on the watchlist."""
    return wl.delete_tag(path or watchlist_path(), tag, persist=_persist)


def set_alerts(ticker: str, alerts: list[dict], path: Path | None = None) -> None:
    """Replace a ticker's alert rules; an empty list removes the key entirely."""
    wl.set_alerts(path or watchlist_path(), ticker, alerts, persist=_persist)


def add_entry(ticker: str, name: str = "", path: Path | None = None) -> None:
    """Put a ticker on the watchlist (a no-op when it is already there)."""
    wl.add_entry(path or watchlist_path(), ticker, name, persist=_persist)


def remove_entry(ticker: str, path: Path | None = None) -> None:
    """Drop a ticker from the watchlist, alerts and tags with it."""
    wl.remove_entry(path or watchlist_path(), ticker, persist=_persist)


def set_position(ticker: str, shares: float | None = None,
                 cost: float | None = None, path: Path | None = None) -> None:
    """Set a ticker's held quantity and/or average cost."""
    wl.set_position(path or watchlist_path(), ticker, shares, cost, persist=_persist)


def all_tags(path: Path | None = None) -> list[str]:
    """Every tag used on this account's watchlist, sorted case-insensitively."""
    return wl.all_tags(path or watchlist_path())
