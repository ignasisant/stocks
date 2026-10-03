"""Per-account data: slugs, owner mapping, seeding and login stamps, prefs,
watchlist edits and account deletion."""

import re

import pytest
import yaml

from stocks import accounts, secrets_env, session
from stocks import watchlist as wl
from stocks.config import DATA_DIR, PROJECT_ROOT, load_watchlist
from stocks.web import auth
from stocks.web.auth import (
    DEFAULT_PREFS,
    _legacy_slug,
    all_tags,
    load_prefs,
    paths_for,
    save_prefs,
    set_tags,
    slug,
)


def restore(paths, legacy_root=None) -> bool:
    """`accounts.restore_account`, with the bucket push left out of it."""
    return accounts.restore_account(paths, legacy_root, persist=lambda _p: None)


def test_slug_is_filesystem_safe():
    s = slug("Jane.Doe+test@Gmail.com")
    assert s.startswith("jane_doe_test_gmail_com_")
    assert re.fullmatch(r"[a-z0-9_]+", s)
    assert slug("jane.doe+test@gmail.com") == s  # case/whitespace-insensitive
    assert slug("--a@b--").startswith("a_b_")


def test_slug_collision_proof():
    # Same readable base, different addresses -> different data dirs.
    assert slug("a.b@c.com") != slug("a@b.c.com")


def test_paths_for_regular_user(tmp_path):
    p = paths_for("jane@example.com", users_dir=tmp_path)
    assert p.root == tmp_path / slug("jane@example.com")
    assert p.watchlist == p.root / "watchlist.yaml"
    assert p.db == p.root / "portfolio.db"
    assert p.last_import == p.root / "last_import.json"
    assert p.prefs == p.root / "prefs.json"
    assert p.chat == p.root / "chat.json"


def test_paths_for_owner_maps_to_root_files(tmp_path):
    p = paths_for("Me@Example.com", owner_email="me@example.com", users_dir=tmp_path)
    assert p.root == PROJECT_ROOT
    assert p.watchlist == PROJECT_ROOT / "watchlist.yaml"
    assert p.db == DATA_DIR / "portfolio.db"
    # Non-owner emails still land in users_dir even when an owner is set.
    other = paths_for(
        "jane@example.com", owner_email="me@example.com", users_dir=tmp_path
    )
    assert other.root == tmp_path / slug("jane@example.com")


def test_restore_account_seeds_starter_watchlist(tmp_path):
    p = paths_for("jane@example.com", users_dir=tmp_path)
    restore(p)
    assert p.root.is_dir()
    holdings = load_watchlist(p.watchlist)
    assert holdings  # starter list is non-empty
    restore(p)  # idempotent — must not overwrite
    p.watchlist.write_text("watchlist:\n  - ticker: NVDA\n")
    restore(p)
    assert [h.ticker for h in load_watchlist(p.watchlist)] == ["NVDA"]


def test_starter_watchlist_is_a_spread_of_live_tickers_and_no_positions(tmp_path):
    """The seed exists so a first visit has data to rank, group and compare.

    The no-`shares` assertion is the important one: every figure the app draws
    for a seeded row is live market data, so nothing a brand-new account sees
    is ever a holding it does not own. A seeded `shares`/`cost` would turn the
    starter list into a fake portfolio in an app that also files tax reports.
    """
    p = tmp_path / "starter.yaml"
    p.write_text(auth.STARTER_WATCHLIST)
    holdings = load_watchlist(p)

    assert not any(h.is_position for h in holdings)
    assert not any(h.cost for h in holdings)

    tickers = [h.ticker for h in holdings]
    assert len(tickers) == len(set(tickers))
    # The sector screen's P/E table, the 52-week scan and the sentiment pass all
    # rank across the list; two rows gave them nothing to compare.
    assert len(tickers) >= 8
    assert all(h.name for h in holdings)  # names, or the tables read as codes

    assert any(h.favorite for h in holdings)  # the favorites expander opens
    assert any(h.tags for h in holdings)  # tag groups + earnings filter pills
    # Home's plain "Watchlist" group holds what is neither favorite nor
    # tagged; tagging every row would empty it and hide the ungrouped view.
    assert any(not h.favorite and not h.tags for h in holdings)

    assert any("-" in t for t in tickers)  # a crypto pair — the Crypto gating
    assert any("." in t for t in tickers)  # a non-US listing, for FX


def test_restore_account_reports_only_the_seeding_call(tmp_path):
    p = paths_for("jane@example.com", users_dir=tmp_path)
    assert restore(p) is True  # created the account
    assert restore(p) is False  # already there


def test_stamp_login_dates_a_signup_exactly(tmp_path):
    p = paths_for("jane@example.com", users_dir=tmp_path)
    seeded = restore(p)
    assert accounts.stamp_login(p, seeded=seeded) == "signup"
    prefs = load_prefs(p.prefs)
    assert prefs["first_seen"].startswith(prefs["last_seen"])  # ISO stamp, same day
    assert prefs["first_seen_estimated"] is False

    # Returning: first_seen is never restamped, and the account is not a
    # second signup.
    assert accounts.stamp_login(p, seeded=False) == "login"
    assert load_prefs(p.prefs)["first_seen"] == prefs["first_seen"]


def test_stamp_login_backfills_an_account_it_did_not_create(tmp_path):
    p = paths_for("jane@example.com", users_dir=tmp_path)
    restore(p)
    # No first_seen and nothing seeded this run -> the account predates the
    # bookkeeping: dated, flagged inexact, and NOT counted as a signup.
    assert accounts.stamp_login(p, seeded=False) == "login"
    prefs = load_prefs(p.prefs)
    assert prefs["first_seen"]
    assert prefs["first_seen_estimated"] is True


def test_stamp_login_leaves_prefs_untouched_within_the_day(tmp_path):
    p = paths_for("jane@example.com", users_dir=tmp_path)
    accounts.stamp_login(p, seeded=restore(p))
    before = p.prefs.read_text()
    accounts.stamp_login(p, seeded=False)  # same day: no write, so no bucket PUT
    assert p.prefs.read_text() == before


def test_stamp_login_keeps_the_rest_of_prefs(tmp_path):
    p = paths_for("jane@example.com", users_dir=tmp_path)
    restore(p)
    save_prefs({**DEFAULT_PREFS, "currency": "USD", "telegram_chat_id": 7}, p.prefs)
    accounts.stamp_login(p, seeded=False)
    prefs = load_prefs(p.prefs)
    assert prefs["currency"] == "USD"
    assert prefs["telegram_chat_id"] == 7


def test_restore_account_migrates_legacy_dir(tmp_path):
    email = "jane@example.com"
    p = paths_for(email, users_dir=tmp_path)
    legacy = tmp_path / _legacy_slug(email)
    legacy.mkdir(parents=True)
    (legacy / "watchlist.yaml").write_text("watchlist:\n  - ticker: NVDA\n")
    restore(p, legacy_root=legacy)
    assert not legacy.exists()  # renamed, not copied
    assert [h.ticker for h in load_watchlist(p.watchlist)] == ["NVDA"]
    # Idempotent: once the new dir exists the legacy path is ignored.
    legacy.mkdir()
    (legacy / "watchlist.yaml").write_text("watchlist:\n  - ticker: EVIL\n")
    restore(p, legacy_root=legacy)
    assert [h.ticker for h in load_watchlist(p.watchlist)] == ["NVDA"]


def test_the_shared_prefs_file_refuses_a_write_whoever_is_asking():
    """A guest never writes the shared prefs file.

    The guard is in the persistence layer rather than in each caller because
    the callers are the problem: a helper that saves a setting is easy to reach
    from a code path that never asked who is asking, which is how an anonymous
    visitor's searches once reached the next one's dropdown. A login check can
    be forgotten; this cannot.

    `accounts.GUEST_DIR` is already a fresh directory of this test's own —
    `conftest._own_guest_dir` gives every test one, so that nothing in the suite
    reads or writes the checkout's real `data/users/_guest`.
    """
    guest = accounts.guest_paths()

    with pytest.raises(accounts.GuestIsReadOnly):
        accounts.save_prefs(guest.prefs, {"currency": "USD"}, persist=lambda p: None)
    with pytest.raises(accounts.GuestIsReadOnly):
        accounts.push_recent_search(guest.prefs, "AAPL", persist=lambda p: None)

    assert not guest.prefs.exists()


def test_prefs_roundtrip_and_corrupt_fallback(tmp_path):
    path = tmp_path / "prefs.json"
    assert load_prefs(path) == DEFAULT_PREFS  # absent -> defaults
    save_prefs({"currency": "USD"}, path)
    assert load_prefs(path)["currency"] == "USD"
    path.write_text("{not json")
    assert load_prefs(path) == DEFAULT_PREFS


def test_toggle_favorite_creates_entry_and_flips(tmp_path):
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "aliases": {"RCF": "TEP.PA"},
                "watchlist": [
                    {"ticker": "NVDA", "alerts": [{"type": "drawdown", "pct": 15}]}
                ],
            }
        )
    )
    # Unlisted symbol: favoriting adds it to the watchlist.
    assert wl.toggle_favorite(path, "pltr") is True
    by_ticker = {h.ticker: h for h in load_watchlist(path)}
    assert by_ticker["PLTR"].favorite is True
    assert wl.toggle_favorite(path, "PLTR") is False
    assert not load_watchlist(path)[1].favorite
    # Neighbouring data untouched by the round-trips.
    raw = yaml.safe_load(path.read_text())
    assert raw["aliases"] == {"RCF": "TEP.PA"}
    assert raw["watchlist"][0]["alerts"] == [{"type": "drawdown", "pct": 15}]
    # Cleared flag is dropped from the YAML, not written as false.
    assert "favorite" not in raw["watchlist"][1]


def test_set_tags_and_all_tags(tmp_path):
    path = tmp_path / "watchlist.yaml"
    path.write_text(yaml.safe_dump({"watchlist": [{"ticker": "NVDA"}]}))
    assert set_tags("NVDA", ["semis", " AI ", "ai"], path) == ["semis", "AI"]
    assert set_tags("baba", ["EM"], path) == ["EM"]  # unlisted -> entry created
    assert all_tags(path) == ["AI", "EM", "semis"]  # case-insensitive sort
    assert set_tags("NVDA", [], path) == []  # clearing removes the key
    raw = yaml.safe_load(path.read_text())
    assert "tags" not in raw["watchlist"][0]
    assert all_tags(path) == ["EM"]


# ------------------------------------------------------------ account deletion


def _deletion_sandbox(monkeypatch, tmp_path):
    """auth's world rooted at tmp_path, with a dict standing in for the bucket."""
    from stocks.web import auth

    users = tmp_path / "data" / "users"
    monkeypatch.setattr(auth, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(auth, "USERS_DIR", users)
    monkeypatch.setattr(auth, "GUEST_DIR", users / "_guest")

    bucket: dict[str, bytes] = {}
    monkeypatch.setattr(auth.storage, "enabled", lambda: True)
    monkeypatch.setattr(
        auth.storage,
        "list_keys",
        lambda prefix="": sorted(k for k in bucket if k.startswith(prefix)),
    )
    monkeypatch.setattr(auth.storage, "delete_key", bucket.pop)
    return auth, users, bucket


def test_delete_account_erases_disk_and_bucket(monkeypatch, tmp_path):
    auth, users, bucket = _deletion_sandbox(monkeypatch, tmp_path)
    p = paths_for("jane@example.com", users_dir=users)
    p.root.mkdir(parents=True)
    p.watchlist.write_text("watchlist: []")
    p.prefs.write_text("{}")
    me = f"data/users/{slug('jane@example.com')}"
    other = f"data/users/{slug('bob@example.com')}"
    bucket.update({
        f"{me}/watchlist.yaml": b"x",
        f"{me}/portfolio.db": b"x",
        f"{other}/watchlist.yaml": b"bob",
        "watchlist.yaml": b"root",
    })

    auth.delete_account(p)

    assert not p.root.exists()
    # Only this account's keys are gone; the neighbour and the root survive.
    assert sorted(bucket) == [f"{other}/watchlist.yaml", "watchlist.yaml"]


def test_delete_account_ends_its_connections_and_no_one_elses(monkeypatch, tmp_path):
    """An app the owner let in must not keep reading after the erase."""
    from stocks.connector import store

    auth, users, _ = _deletion_sandbox(monkeypatch, tmp_path)
    p = paths_for("jane@example.com", users_dir=users)
    p.root.mkdir(parents=True)
    for email in ("jane@example.com", "bob@example.com"):
        store.ledger().issue(email=email, client_id="c", client_name="Claude",
                             client_kind="cimd", redirect_host="claude.ai")

    auth.delete_account(p)

    assert store.ledger().grants_for("jane@example.com") == []
    assert len(store.ledger().grants_for("bob@example.com")) == 1


def test_delete_account_refuses_owner_and_guest(monkeypatch, tmp_path):
    import pytest

    auth, users, _ = _deletion_sandbox(monkeypatch, tmp_path)
    owner = paths_for("me@x.com", owner_email="me@x.com", users_dir=users)
    with pytest.raises(ValueError):
        auth.delete_account(owner)
    guest = auth.guest_paths()
    with pytest.raises(ValueError):
        auth.delete_account(guest)
    # Nor anything outside the users dir, whatever it is named.
    stray = type(guest)(**{**guest.__dict__, "root": tmp_path / "elsewhere"})
    with pytest.raises(ValueError):
        auth.delete_account(stray)



def test_a_checkout_with_no_secrets_reads_as_signed_out(monkeypatch, tmp_path):
    """A fresh clone or a CI checkout has no secrets file at all. Every request
    asks who is signed in, so the read must degrade to the one answer that is
    true without an IdP configured — nobody — instead of raising."""
    for name in ("AUTH_COOKIE_SECRET", "AUTH_CLIENT_ID", "AUTH_CLIENT_SECRET",
                 "AUTH_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(secrets_env, "SECRETS_FILE", tmp_path / "absent.toml")

    assert session.sign_in_configured() is False
    assert session.signed_in_email({session.COOKIE: "anything"}) is None
