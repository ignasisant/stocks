"""The bank connection over HTTP: who may use it, and what the bank's own
failures look like to a client.

The client itself is stubbed everywhere — no request leaves the process — so
what is covered here is the part the route owns: the allowlist gate on every
verb including the reads, the `state` round trip that a page load cannot hold
in memory, and the three different answers a failed fetch has to produce
(spent budget, dead consent, real failure), because the page says something
different for each and only one of them is a defect.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.bank import enablebanking, store
from stocks.bank.enablebanking import BankError, ConsentError, RateLimited

TOKEN = "s3cret-token"
EMAIL = "owner@example.com"
STRANGER = "someone@else.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}
# The proxy headers a browser's request arrives with on the deploy; without
# them the route sees plain http and refuses to derive a redirect URL.
PROXIED = {"x-forwarded-proto": "https", "host": "topstocks.app"}

SESSION = {
    "session_id": "sid-1",
    "aspsp": {"name": "Bank A", "country": "ES"},
    "access": {"valid_until": "2099-12-01T00:00:00Z"},
    "accounts": [
        {
            "uid": "acc-1",
            "name": "Cuenta corriente",
            "account_id": {"iban": "ES9121000418450200051332"},
            "currency": "EUR",
        }
    ],
}

BALANCES = [
    {"balance_type": "ITAV", "balance_amount": {"amount": "10.00", "currency": "EUR"}},
    {"balance_type": "CLBD", "balance_amount": {"amount": "1234.56", "currency": "EUR"}},
]


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def _cold_caches():
    """The bank list is cached across accounts; a stub must not leak between
    tests any more than a real answer would."""
    loaders.aspsps.cache_clear()
    yield
    loaders.aspsps.cache_clear()


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture(autouse=True)
def allowed(monkeypatch):
    """Credentials configured and this account on the allowlist."""
    monkeypatch.setattr(enablebanking, "configured", lambda: True)
    monkeypatch.setenv("EB_ALLOWED_EMAILS", EMAIL)
    monkeypatch.setenv("EB_REDIRECT_URL", "")
    monkeypatch.setenv("APP_OWNER_EMAIL", "")


@pytest.fixture
def signed_in(client, sign_in):
    """A browser session for EMAIL — the only kind of caller this route takes."""
    session = sign_in(client, EMAIL)
    session.headers.update(PROXIED)
    return session


@pytest.fixture
def connected(account, monkeypatch):
    """One bank already connected, with nothing read from it yet."""
    store.add_connection(account.bank, SESSION)
    return account


# ------------------------------------------------------------------- the gate


def test_a_token_is_refused_even_for_reading(client, account):
    """Every other route lets a token name an account and read it. This one
    cannot: the gate is an allowlist of people and a token names nobody."""
    response = client.get("/v1/bank", params=WHO, headers=AUTH)
    assert response.status_code == 403


def test_an_account_outside_the_allowlist_is_told_so_rather_than_refused(
    client, sign_in, account, monkeypatch
):
    """`available: false` is the ordinary answer, and the page has a written
    state for it — a 403 would leave the shell rendering an error instead."""
    monkeypatch.setenv("EB_ALLOWED_EMAILS", "")
    payload = sign_in(client, EMAIL).get("/v1/bank", headers=PROXIED).json()
    assert payload["available"] is False
    assert payload["connections"] == []


def test_an_account_outside_the_allowlist_cannot_start_a_consent(
    client, sign_in, account, monkeypatch
):
    monkeypatch.setenv("EB_ALLOWED_EMAILS", "")
    response = sign_in(client, EMAIL).post(
        "/v1/bank/auth", json={"country": "ES", "name": "Bank A"}, headers=PROXIED
    )
    assert response.status_code == 403


def test_a_connection_is_never_shown_to_an_account_that_may_not_see_it(
    client, sign_in, connected, monkeypatch
):
    """The file is on disk either way; the gate decides whether it is read."""
    monkeypatch.setenv("EB_ALLOWED_EMAILS", "")
    payload = sign_in(client, EMAIL).get("/v1/bank", headers=PROXIED).json()
    assert payload["connections"] == []


# ------------------------------------------------------------- the round trip


def test_starting_a_consent_stores_the_state_before_handing_over_the_url(
    signed_in, account, monkeypatch
):
    """The redirect can land before this response is even rendered, so a state
    written afterwards would be a round trip that gets refused on return."""
    seen: dict = {}

    def _start(*, name, country, redirect_url):
        seen.update(name=name, country=country, redirect_url=redirect_url)
        return "https://bank.example/auth?x=1", "st-1"

    monkeypatch.setattr(enablebanking, "start_auth", _start)

    payload = signed_in.post(
        "/v1/bank/auth", json={"country": "es", "name": "Bank A"}
    ).json()

    assert payload["url"] == "https://bank.example/auth?x=1"
    assert payload["state"] == "st-1"
    # Derived from the proxy's headers: the ASGI server itself sees http.
    assert seen["redirect_url"] == "https://topstocks.app/next/bank"
    assert seen["country"] == "ES"
    assert "st-1" in store.load(account.bank)["pending"]


def test_a_host_without_https_cannot_offer_a_consent(signed_in, account):
    """Banks only redirect to https, so a local dev server has no flow to
    start — said once here rather than failing halfway through it."""
    response = signed_in.post(
        "/v1/bank/auth",
        json={"country": "ES", "name": "Bank A"},
        headers={"x-forwarded-proto": "http"},
    )
    assert response.status_code == 409


def test_the_redirect_completes_the_connection(signed_in, account, monkeypatch):
    monkeypatch.setattr(
        enablebanking, "start_auth", lambda **k: ("https://bank.example/a", "st-1")
    )
    monkeypatch.setattr(enablebanking, "create_session", lambda code: SESSION)
    signed_in.post("/v1/bank/auth", json={"country": "ES", "name": "Bank A"})

    payload = signed_in.post(
        "/v1/bank/session", json={"code": "c-1", "state": "st-1"}
    ).json()

    assert payload["connections"][0]["name"] == "Bank A"
    assert payload["connections"][0]["expired"] is False
    assert payload["connections"][0]["accounts"][0]["masked_id"] == "ES91 ···· 1332"
    # Balances are not read on connect: the budget is the bank's and small.
    assert payload["connections"][0]["accounts"][0]["balance"] is None


def test_a_state_this_account_did_not_start_is_refused(signed_in, account, monkeypatch):
    """The code may well be real. Nothing proves this account began the round
    trip, and attaching somebody else's consent to this book is the outcome
    worth refusing a valid code over."""
    called: list[str] = []
    monkeypatch.setattr(
        enablebanking, "create_session", lambda code: called.append(code) or SESSION
    )
    response = signed_in.post(
        "/v1/bank/session", json={"code": "c-1", "state": "never-issued"}
    )
    assert response.status_code == 404
    assert called == []


def test_a_state_issued_to_another_account_is_refused(
    signed_in, account, sign_in, client, monkeypatch
):
    store.add_pending(
        account.bank, state="st-1", email=STRANGER, aspsp={"name": "B", "country": "ES"}
    )
    monkeypatch.setattr(enablebanking, "create_session", lambda code: SESSION)
    response = signed_in.post(
        "/v1/bank/session", json={"code": "c-1", "state": "st-1"}
    )
    assert response.status_code == 404


# ----------------------------------------------------------------- balances


def test_refreshing_stores_what_the_bank_reported(signed_in, connected, monkeypatch):
    monkeypatch.setattr(enablebanking, "balances", lambda uid: BALANCES)

    payload = signed_in.post("/v1/bank/connections/sid-1/refresh").json()

    account = payload["connections"][0]["accounts"][0]
    # Booked wins over available: one figure, the same one on both front ends.
    assert account["balance"] == pytest.approx(1234.56)
    assert account["balance_currency"] == "EUR"
    assert account["fetched_at"]


def test_a_spent_fetch_budget_is_its_own_status(signed_in, connected, monkeypatch):
    """Nothing is wrong and nothing needs reconnecting — the answer is to come
    back tomorrow, which is not what a 502 would tell the page to say."""

    def _boom(uid):
        raise RateLimited(429, "RATE_LIMITED", "too many")

    monkeypatch.setattr(enablebanking, "balances", _boom)
    response = signed_in.post("/v1/bank/connections/sid-1/refresh")
    assert response.status_code == 429


def test_a_dead_consent_is_recorded_as_well_as_reported(
    signed_in, connected, monkeypatch
):
    """Otherwise the card keeps offering a refresh that cannot work: the bank
    ended the consent before the date it originally stated."""

    def _boom(uid):
        raise ConsentError(401, "UNAUTHORIZED", "session expired")

    monkeypatch.setattr(enablebanking, "balances", _boom)
    response = signed_in.post("/v1/bank/connections/sid-1/refresh")
    assert response.status_code == 409
    assert store.expired(store.find(connected.bank, "sid-1")) is True


def test_a_broken_bank_is_a_failure_and_says_which(signed_in, connected, monkeypatch):
    def _boom(uid):
        raise BankError(500, "SERVER_ERROR", "the bank is down")

    monkeypatch.setattr(enablebanking, "balances", _boom)
    response = signed_in.post("/v1/bank/connections/sid-1/refresh")
    assert response.status_code == 502
    assert "the bank is down" in response.text


def test_an_unknown_connection_is_not_found(signed_in, connected):
    assert signed_in.post("/v1/bank/connections/nope/refresh").status_code == 404


# --------------------------------------------------------------- disconnect


def test_disconnecting_forgets_it_here_even_when_the_bank_refuses(
    signed_in, connected, monkeypatch
):
    """A session left open at the bank expires on its own, and the user asked
    for it gone *here*."""

    def _boom(session_id):
        raise BankError(500, "SERVER_ERROR", "nope")

    monkeypatch.setattr(enablebanking, "delete_session", _boom)
    payload = signed_in.delete("/v1/bank/connections/sid-1").json()
    assert payload["connections"] == []
    assert store.connections(connected.bank) == []


def test_disconnecting_something_that_is_not_there_is_not_found(signed_in, connected):
    assert signed_in.delete("/v1/bank/connections/nope").status_code == 404


# ------------------------------------------------------------------- the list


def test_the_bank_list_is_offered_as_choices(signed_in, account, monkeypatch):
    monkeypatch.setattr(
        enablebanking,
        "aspsps",
        lambda country, psu_type="personal": [
            {"name": "Bank A", "country": country, "logo": "https://l/a.png"},
            {"name": "", "country": country},  # nameless entries are not choices
        ],
    )
    payload = signed_in.get("/v1/bank/aspsps", params={"country": "PT"}).json()
    assert payload == [{"name": "Bank A", "country": "PT", "logo": "https://l/a.png"}]


def test_a_failing_bank_list_is_a_bad_gateway(signed_in, account, monkeypatch):
    def _boom(country, psu_type="personal"):
        raise BankError(503, "UNAVAILABLE", "upstream down")

    monkeypatch.setattr(enablebanking, "aspsps", _boom)
    assert signed_in.get("/v1/bank/aspsps").status_code == 502
