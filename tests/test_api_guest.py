"""What an anonymous visitor gets, and what they cannot touch.

The landing's call to action has always dropped somebody into a demo book
without an account, and `api/guest.py` is that same surface restated where the
API can enforce it. Two claims are worth a file of their own.

**Serving a guest writes nothing.** Every anonymous visitor reads one shared
directory, so a single stray write is not one person's bug — it is one person's
tickers appearing in the next person's screen. That has happened once already
(`web.auth.push_recent_search`, fixed with `accounts.writable`), and it happened
because the write was somewhere nobody thought to look. So the test here is not
a list of places to check: it walks `guest.OPEN` and asserts the directory did
not move. A guest route added next year is covered without anyone adding a test.

**A guest is never given a name.** Not by `?account=`, not by a token, not by a
cookie whose address nobody verified. Everything a guest reads is the demo book
or a shipped table, and everything it writes — one route, feedback — lands
outside every book on the deployment.

The walk runs with Yahoo's circuit breaker tripped, so no route here reaches the
network: the handlers degrade exactly as they do on a throttled deployment, and
what is being asserted is about the filesystem, not about the answers.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import guest, guestbook
from stocks.api.app import app as fastapi_app
from stocks.data import fetch
from stocks.portfolio import demo

TOKEN = "s3cret-token"


@pytest.fixture(autouse=True)
def _fresh_limiter():
    """Empty the process-wide burst limiter around every test here.

    `web.ratelimit` keys an anonymous sender on its client address, and every
    test in this file is the same address ("unknown", there being no socket
    behind a TestClient). Without this the first file to send three
    submissions would 429 the rest of the suite, in test order.
    """
    from stocks.web import ratelimit

    ratelimit._events.clear()
    yield
    ratelimit._events.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture
def book(monkeypatch):
    """The guest directory as boot leaves it: a watchlist and the demo ledger.

    `accounts.GUEST_DIR` is already a fresh tmp dir for every test (see
    `conftest._own_guest_dir`); this is the part `api.guestbook.provision()`
    does, with the bucket taken out of it.
    """
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    paths = accounts.guest_paths()
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n  - ticker: MSFT\n")
    demo.seed(paths.db)
    return paths


@pytest.fixture
def offline(_no_yahoo_cooldown):
    """No route in this file goes to Yahoo.

    Declared to depend on the autouse fixture that *clears* the breaker, so
    this runs after it rather than being undone by it.
    """
    fetch.trip_throttle()
    yield
    fetch.clear_throttle()


def _snapshot(root) -> dict[str, tuple[float, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _url(path: str) -> str:
    import re

    return re.sub(r"\{[^}]*\}", "AAPL", path)


# ------------------------------------------------------- the one that matters


def test_serving_a_guest_writes_nothing_into_the_shared_directory(
    client, book, offline
):
    """Walk every route a guest may reach and prove the directory did not move.

    Derived from `guest.OPEN` rather than from a list written here, which is the
    whole point: this covers the route somebody adds next year, and it is the
    property `push_recent_search` needed and did not have.

    Content and mtime both, because the failure that hurts is a rewrite with the
    same size — five recent searches replaced by five others.
    """
    before = _snapshot(accounts.GUEST_DIR)
    assert before, "nothing to protect — the fixture did not seed a book"
    for path, method in sorted(guest.OPEN):
        body = {"text": "a note", "kind": "bug"} if method == "POST" else None
        client.request(method, _url(path), json=body)
    assert _snapshot(accounts.GUEST_DIR) == before


def test_no_guest_route_calls_an_account_directory_into_existence(
    client, book, offline, monkeypatch, tmp_path
):
    """The sibling claim, one level up. `deps.account()` returns
    `guest_paths()` directly rather than going through `_resolve`, so nothing a
    guest asks can mkdir, pull the bucket, or leave a directory behind for an
    address somebody guessed."""
    users = tmp_path / "users"
    users.mkdir()
    monkeypatch.setattr(accounts, "paths_for", lambda *a, **k: pytest.fail(
        "a guest request resolved an account"
    ))
    for path, method in sorted(guest.OPEN):
        body = {"text": "a note", "kind": "bug"} if method == "POST" else None
        client.request(method, _url(path), json=body)
    assert list(users.iterdir()) == []


# ------------------------------------------------------------- who is asking


def test_me_names_nobody(client):
    body = client.get("/v1/me").json()
    assert body["kind"] == "guest"
    assert body["email"] is None


def test_a_guest_may_not_name_an_account(client, book):
    """The `?account=` door, shut from the guest side. 403 rather than 404: a
    404 would answer whether that address has a book here, which is a question
    an anonymous caller does not get to ask."""
    response = client.get("/v1/watchlist", params={"account": "someone@example.com"})
    assert response.status_code == 403


def test_a_guest_cookie_nobody_verified_is_still_a_guest(client, book, cookie_secret):
    """Google will hand over an unverified address. Presenting one must buy
    exactly what presenting nothing buys — not a book, and not a name."""
    from stocks import session

    client.cookies.set(
        session.COOKIE,
        session.mint({"email": "someone@example.com", "email_verified": False}),
    )
    assert client.get("/v1/me").json()["email"] is None


# ------------------------------------------------ the shared file stays shared


def test_prefs_answers_the_defaults_and_does_not_read_the_shared_file(client, book):
    """One prefs.json serves every visitor, so nothing in it is this reader's
    preference. A settings screen nobody can change must not differ between two
    people looking at it."""
    accounts.guest_paths().prefs.write_text(
        json.dumps({"currency": "USD", "language": "es", "notify_alerts": True})
    )
    body = client.get("/v1/prefs").json()
    assert body["currency"] == "EUR"
    assert body["language"] is None
    assert body["notify_alerts"] is False


def test_money_is_reckoned_in_euros_whatever_the_shared_file_says(book):
    """`deps.reporting_currency` reads `paths.prefs` directly, bypassing
    `/prefs` — so the rule above has to be stated twice or the money routes
    would quietly honour a currency somebody else left there."""
    from stocks.api import deps

    accounts.guest_paths().prefs.write_text(json.dumps({"currency": "USD"}))
    assert deps.reporting_currency(accounts.guest_paths()) == "EUR"


def test_a_guest_can_still_change_the_currency_for_one_request(book):
    """`?base=` keeps working, so the switcher on the demo Portfolio functions.
    It just does not persist, which is the difference between a question and a
    preference."""
    from stocks.api import deps

    assert deps.reporting_currency(accounts.guest_paths(), "USD") == "USD"


# ------------------------------------------------------------ the demo book


def test_the_demo_book_is_what_a_guest_reads(client, book, offline):
    """Not an empty state: the landing promises a portfolio to look at, and the
    positions route is what has to deliver it."""
    response = client.get("/v1/portfolio/transactions")
    assert response.status_code == 200
    assert response.json()["transactions"]


def test_a_second_boot_does_not_stack_a_second_demo_book(monkeypatch, book):
    """`provision()` runs on every start, and an ephemeral redeploy restarts
    often. A cost basis that doubled on restart would be a demo nobody trusts."""
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    rows = len(demo.transactions())
    guestbook.provision()
    guestbook.provision()
    import sqlite3

    with sqlite3.connect(book.db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == rows


def test_a_bucket_outage_costs_the_demo_book_and_not_the_boot(monkeypatch):
    """Provisioning never raises. A guest with no demo book sees the empty state
    the pages already draw; a deployment that will not start serves nobody."""
    def explode(*a, **k):
        raise accounts.StorageUnavailable("the bucket is away")

    monkeypatch.setattr(accounts, "restore_account", explode)
    guestbook.provision()  # must not raise


# ----------------------------------------------------------------- the writes


@pytest.mark.parametrize(
    "method,path",
    [
        ("PATCH", "/v1/prefs"),
        ("POST", "/v1/watchlist"),
        ("POST", "/v1/search/recent"),
        ("POST", "/v1/onboarding/seen"),
    ],
)
def test_a_write_is_refused_with_the_header_that_offers_a_sign_in(
    client, book, method, path
):
    """401 rather than 403, deliberately: the shell maps 401 to "not signed in"
    and draws a sign-in button, which is the correct thing to show somebody who
    just tried to star a ticker. 403 would render as an error about a right they
    could have had for free."""
    response = client.request(method, path, json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "path",
    ["/v1/chat/state", "/v1/import/last", "/v1/daily", "/v1/profile"],
)
def test_the_routes_a_guest_has_no_business_reading_stay_shut(client, book, path):
    """Each absent from `guest.OPEN` for its own reason, written beside it
    there: somebody's keys, somebody's imports, somebody's generated briefing,
    somebody's assistant."""
    assert client.get(path).status_code == 401


# -------------------------------------------------------------- the exception


def test_a_guest_may_say_what_is_wrong(client, book, monkeypatch, tmp_path):
    """The one unauthenticated write, and the reason it is one: a reader who
    bounced off the pitch telling us why is worth more than a login."""
    from stocks.web import feedback as store

    monkeypatch.setattr(store, "FEEDBACK_DIR", tmp_path / "feedback")
    monkeypatch.setattr(store.storage, "persist", lambda *a, **k: None)
    response = client.post("/v1/feedback", json={"text": "the chart is empty"})
    assert response.status_code == 201
    written = list((tmp_path / "feedback").glob("*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text())["user"] == "guest"


def test_a_guests_feedback_lands_outside_every_book(client, book, monkeypatch, tmp_path):
    """The property that makes the exception safe. It is a write, but not into
    anything anybody reads as data — so no visitor can change what the next one
    sees."""
    from stocks.web import feedback as store

    monkeypatch.setattr(store, "FEEDBACK_DIR", tmp_path / "feedback")
    monkeypatch.setattr(store.storage, "persist", lambda *a, **k: None)
    before = _snapshot(accounts.GUEST_DIR)
    client.post("/v1/feedback", json={"text": "still empty"})
    assert _snapshot(accounts.GUEST_DIR) == before


def test_an_anonymous_sender_is_metered_by_address(client, book, monkeypatch, tmp_path):
    """Nothing else stands between this route and a script: no account, no
    quota, no cost to the sender. The cap is per client address, which is a
    speed bump rather than an identity — and a speed bump is what an
    unauthenticated free-text endpoint needs to not be a spam sink."""
    from stocks.api.routes import feedback as route
    from stocks.web import feedback as store

    monkeypatch.setattr(store, "FEEDBACK_DIR", tmp_path / "feedback")
    monkeypatch.setattr(store.storage, "persist", lambda *a, **k: None)
    sent = [
        client.post("/v1/feedback", json={"text": f"note {n}"}).status_code
        for n in range(route.GUEST_MAX_PER_HOUR + 1)
    ]
    assert sent[:-1] == [201] * route.GUEST_MAX_PER_HOUR
    assert sent[-1] == 429


def test_a_token_may_not_file_feedback(client, book, monkeypatch):
    """It names nobody and any holder can name any account, so a token that
    could write would be one leaked secret away from filing against somebody."""
    monkeypatch.setenv("API_TOKEN", TOKEN)
    response = client.post(
        "/v1/feedback",
        json={"text": "from a job"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 403


# ------------------------------------------------------------ the shared cache


def test_a_name_one_account_invented_never_renders_for_a_guest(monkeypatch):
    """The one cached value whose *subject* is shared while its *content* is
    account-private.

    Every other loader derives from a file and is keyed on that file's path, so
    a guest's `GUEST_DIR/portfolio.db` cannot collide with any `slug()`-derived
    account's — the paths differ, so the entries differ, and nothing has to
    check who is asking. `company_name` is the exception worth pinning: its
    ticker is the same ticker for everybody, and the `watchlist` argument beside
    it looks redundant until you notice it is the only thing keeping a custom
    name off a stranger's screen. It is reachable by a guest through three
    allowlisted routes; optimise the argument away and one account's label
    renders on the demo pages.
    """
    from stocks import identity
    from stocks.api import loaders

    loaders.company_name.cache_clear()
    monkeypatch.setattr(
        identity, "company_name", lambda ticker, watchlist: f"{ticker} per {watchlist}"
    )
    mine = loaders.company_name("AAPL", "/data/users/abc123/watchlist.yaml")
    theirs = loaders.company_name("AAPL", "/data/users/_guest/watchlist.yaml")
    assert mine != theirs
    loaders.company_name.cache_clear()


def test_a_guests_derived_state_cannot_collide_with_an_accounts(book):
    """Stated as a property of the paths rather than of any one loader, because
    that is what makes it hold for the loaders nobody has written yet: a guest
    reads `GUEST_DIR/...` and `slug()` prefixes every account directory with a
    sha256, so no address can produce the string "_guest"."""
    from stocks import accounts

    slugs = {accounts.slug(f"person{n}@example.com") for n in range(200)}
    assert accounts.GUEST_DIR.name not in slugs
    assert accounts.guest_paths().db != accounts.paths_for("a@example.com", None).db
