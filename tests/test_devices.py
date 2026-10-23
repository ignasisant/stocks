"""The account's list of live sessions, and ending them from Profile."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts, devices, session
from stocks.api.app import app as fastapi_app
from stocks.web import oidc

EMAIL = "holder@example.com"
OTHER = "other@example.com"
CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
SAFARI_IOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    monkeypatch.setattr("stocks.storage.enabled", lambda: False)
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    users = tmp_path / "users"
    monkeypatch.setattr(
        accounts, "paths_for",
        lambda email, owner=None, users_dir=users: _paths(email, users),
    )
    devices.reset_for_tests()


def _paths(email: str, users):
    d = users / accounts.slug(email)
    d.mkdir(parents=True, exist_ok=True)
    (d / "watchlist.yaml").write_text("watchlist: []\n")
    return accounts.UserPaths(
        root=d, watchlist=d / "watchlist.yaml", db=d / "portfolio.db",
        last_import=d / "last_import.json", prefs=d / "prefs.json",
        chat=d / "chat.json", bank=d / "bank.json", action=d / "daily_action.json",
    )


def browser(email: str, ua: str) -> TestClient:
    client = TestClient(fastapi_app, headers={"User-Agent": ua})
    client.cookies.set(
        session.COOKIE,
        session.mint({"email": email, "email_verified": True, "name": "T"}),
    )
    return client


def sid_of(client: TestClient) -> str:
    return session.claims({session.COOKIE: client.cookies[session.COOKIE]})["sid"]


@pytest.fixture
def two(cookie_secret):
    return browser(EMAIL, CHROME_MAC), browser(EMAIL, SAFARI_IOS)


def test_user_agent_is_boiled_down_to_browser_and_system():
    assert devices.summarise(CHROME_MAC) == "Chrome · macOS"
    assert devices.summarise(SAFARI_IOS) == "Safari · iOS"
    assert devices.summarise("curl/8") == ""


def test_sign_in_records_the_session_by_hash(cookie_secret):
    cookie = session.mint({"email": EMAIL, "email_verified": True})
    oidc._record_device(cookie, EMAIL, CHROME_MAC)
    raw = accounts.paths_for(EMAIL).devices.read_text()
    sid = session.claims({session.COOKIE: cookie})["sid"]
    assert sid not in raw and cookie not in raw
    row = json.loads(raw)["sessions"][devices.sid_hash(sid)]
    assert row["device"] == "Chrome · macOS"
    assert "address" not in row and "ip" not in row


def test_the_list_marks_the_current_session(two):
    here, there = two
    here.get("/v1/me")  # any account route touches
    there.get("/v1/account/sessions")
    rows = here.get("/v1/account/sessions").json()["sessions"]
    assert sorted(r["device"] for r in rows) == ["Chrome · macOS", "Safari · iOS"]
    assert [r["device"] for r in rows if r["current"]] == ["Chrome · macOS"]


def test_last_seen_is_written_at_most_every_few_minutes(tmp_path):
    path = tmp_path / "devices.json"
    kw = dict(user_agent=CHROME_MAC, created=1000.0, expires=1e12)
    devices.touch(path, "sid1", now=1000.0, **kw)
    mtime = path.stat().st_mtime_ns
    devices.touch(path, "sid1", now=1000.0 + devices.SEEN_EVERY - 1, **kw)
    assert path.stat().st_mtime_ns == mtime
    devices.touch(path, "sid1", now=1000.0 + devices.SEEN_EVERY + 1, **kw)
    seen = json.loads(path.read_text())["sessions"][devices.sid_hash("sid1")]["seen"]
    assert seen == 1000.0 + devices.SEEN_EVERY + 1


def test_ending_a_session_stops_its_cookie_on_the_next_request(two):
    here, there = two
    here.get("/v1/account/sessions")
    there.get("/v1/account/sessions")
    target = devices.sid_hash(sid_of(there))
    assert here.delete(f"/v1/account/sessions/{target}").json() == {"ended": 1}
    assert there.get("/v1/account/sessions").status_code == 401
    rows = here.get("/v1/account/sessions").json()["sessions"]
    assert [r["current"] for r in rows] == [True]


def test_signing_out_everywhere_else_keeps_this_one(cookie_secret):
    a, b, c = (browser(EMAIL, CHROME_MAC) for _ in range(3))
    for client in (a, b, c):
        client.get("/v1/account/sessions")
    assert a.delete("/v1/account/sessions/others").json() == {"ended": 2}
    assert b.get("/v1/account/sessions").status_code == 401
    assert c.get("/v1/account/sessions").status_code == 401
    assert a.get("/v1/account/sessions").status_code == 200


def test_another_accounts_session_cannot_be_ended(cookie_secret):
    mine, theirs = browser(EMAIL, CHROME_MAC), browser(OTHER, CHROME_MAC)
    mine.get("/v1/account/sessions")
    theirs.get("/v1/account/sessions")
    victim = devices.sid_hash(sid_of(theirs))
    assert mine.delete(f"/v1/account/sessions/{victim}").status_code == 404
    assert theirs.get("/v1/account/sessions").status_code == 200


def test_a_guest_has_no_sessions(cookie_secret):
    client = TestClient(fastapi_app)
    assert client.get("/v1/account/sessions").status_code in (401, 403)
    assert client.delete("/v1/account/sessions/others").status_code in (401, 403)
