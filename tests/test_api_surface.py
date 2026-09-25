"""Shape invariants for the whole API, not for any one route.

The routes are growing under more than one pair of hands, and the two mistakes
that matter here are both invisible in a diff that looks right: an endpoint
declared on the open router instead of the gated one, and a path parameter that
lets a caller name a file. Neither fails a unit test of the handler — the
handler is fine. What is wrong is where it was hung.

So this asks the running application, rather than reading the source: for every
path the schema advertises, is an anonymous caller turned away — or served as a
guest? Which of the three tiers a route sits in is a decision made in a named
place, never a side effect of where a router happened to be declared: `PUBLIC`
below, `api.guest.OPEN`, or neither, which is the default and is closed.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from stocks import session
from stocks.api import guest
from stocks.api.app import app as fastapi_app

# Open on purpose, each for a reason that does not generalise:
#   /health   — a liveness probe carries no credentials and the answer names
#               nothing about the deployment.
#   /design/tokens and /i18n/{lang} — shipped files the landing already serves
#               as plain HTML, and a sign-in screen needs both before anyone is
#               signed in.
PUBLIC = {"/v1/health", "/v1/design/tokens", "/v1/i18n/{lang}"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def _no_token(monkeypatch):
    """No bearer token configured and no session — a bare anonymous caller."""
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("stocks.api.security.configured_token", lambda: "")


def _paths() -> list[tuple[str, str]]:
    return [
        (path, method)
        for path, item in fastapi_app.openapi()["paths"].items()
        for method in item
    ]


def test_every_route_that_is_not_explicitly_open_turns_an_anonymous_caller_away():
    """The one that catches a route hung on the open router by accident.

    A book, a ledger, a tax position: none of it may answer without a caller,
    and "I forgot which router I was on" is exactly the kind of mistake that
    reviews well. The guest surface is an exception to *who* may read, not to
    this: a route reaches it only by being written into `api.guest.OPEN`.
    """
    client = TestClient(fastapi_app)
    leaked = []
    for path, method in _paths():
        if path in PUBLIC or (path, method.upper()) in guest.OPEN:
            continue
        # A value for every path parameter. What it is does not matter: the
        # gate runs before the handler ever looks at it.
        url = re.sub(r"\{[^}]*\}", "AAPL", path)
        response = client.request(method, url)
        if response.status_code not in (401, 403, 405):
            leaked.append((method.upper(), path, response.status_code))
    assert not leaked, f"answered without a caller: {leaked}"


def test_the_open_routes_are_open():
    """The other half of the claim: a sign-in screen has to be able to paint."""
    client = TestClient(fastapi_app)
    for path in PUBLIC:
        url = re.sub(r"\{[^}]*\}", "en", path)
        assert client.get(url).status_code == 200, path


# An address, not any "@" — the catalog is full of price templates that read
# "10 sh @ 120.50", and a test that cannot tell those apart is a test nobody
# will trust the next time it fires.
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")


def test_an_open_route_names_nobody():
    client = TestClient(fastapi_app)
    for path in PUBLIC:
        url = re.sub(r"\{[^}]*\}", "en", path)
        found = _EMAIL.findall(client.get(url).text)
        assert not found, f"{path} answers with something address-shaped: {found}"


def test_an_open_route_answers_the_same_thing_to_everybody():
    """The sharper half of the claim. Whatever sits outside the gate must not
    vary by caller — a route that does belongs inside it, however harmless its
    body reads.

    Scoped to PUBLIC on purpose, and it must stay that way: a *guest* route
    emphatically does not answer the same thing to everybody, because a
    signed-in caller gets their own book from the same path. That difference is
    precisely what separates the two tiers, so widening this over `guest.OPEN`
    would not be a stricter test — it would be a different and false claim."""
    client = TestClient(fastapi_app)
    for path in PUBLIC:
        url = re.sub(r"\{[^}]*\}", "en", path)
        anonymous = client.get(url)
        # Set on a client of its own: per-request cookies are deprecated, and
        # leaking this one into the next case would make the comparison a
        # comparison of two identical callers.
        signed = TestClient(fastapi_app, cookies={session.COOKIE: "whatever"})
        carrying = signed.get(url, headers={"Authorization": "Bearer whatever"})
        assert anonymous.status_code == carrying.status_code == 200, path
        if path == "/v1/health":
            continue  # a boot timestamp moves on its own
        assert anonymous.text == carrying.text, f"{path} varies by caller"


def test_the_public_list_is_not_silently_growing():
    """Pinned, so widening the open surface is a decision in this file rather
    than a side effect of where a router happened to be declared."""
    assert len(PUBLIC) == 3


def test_the_guest_list_is_not_silently_growing():
    """Pinned like PUBLIC, and for the same reason: widening what an anonymous
    visitor may read should be a decision somebody made in `api/guest.py`, not
    a line that rode in on a feature branch."""
    # 43: `GET /sectors/{sector}/verdict` — the computed stand-in, which is
    # what the Streamlit card has always shown a visitor with no account.
    # 45: `GET /movers` and `GET /extremes` — cards the guest's Home and
    # Portfolio already drew, over the shared demo book and watchlist.
    # 46: `GET /earnings/{symbol}/result` — the dialog a past calendar chip
    # opens, which the guest calendar already offered in Streamlit.
    # 47: `GET /home/closes` — the guest Home's watchlist rows, last close and
    # day %, which Streamlit has always drawn over the shared list.
    assert len(guest.OPEN) == 47


def test_every_route_a_guest_may_read_is_a_read():
    """One exception, named in `guest.OPEN_WRITES` and argued for there."""
    assert {entry for entry in guest.OPEN if entry[1] != "GET"} == guest.OPEN_WRITES


def test_every_route_a_guest_may_read_is_a_route_that_exists():
    """The cost of keying the list on path strings: a rename does not open the
    wrong thing, it silently *closes* a page the shell needs, and the schema is
    the only place that knows. The app checks this at import too — this is the
    test that says so out loud."""
    assert guest.OPEN <= {(path, method.upper()) for path, method in _paths()}


def _takes_an_account(path: str, method: str) -> bool:
    """Whether the schema says this route reads `?account=`.

    Asked of the schema rather than of a hand-kept list, because the whole point
    is to catch the route that grew the parameter without anyone thinking about
    guests.
    """
    item = fastapi_app.openapi()["paths"][path][method.lower()]
    return any(
        parameter["name"] == "account" and parameter["in"] == "query"
        for parameter in item.get("parameters", ())
    )


def test_a_guest_may_not_ask_a_guest_route_about_an_account():
    """Every account-scoped route inherits `?account=` from one Query in
    `deps`, so there is exactly one place this can go wrong — and a guest that
    could name an account would read somebody's real book from the demo pages.

    Only the routes that declare the parameter: a reference table takes no
    account and is right to ignore an unknown query string, so demanding a
    refusal from it would pin behaviour nobody wants.
    """
    client = TestClient(fastapi_app)
    asked = 0
    for path, method in sorted(guest.OPEN):
        if not _takes_an_account(path, method):
            continue
        asked += 1
        url = re.sub(r"\{[^}]*\}", "AAPL", path)
        response = client.request(method, url, params={"account": "mine@example.com"})
        assert response.status_code == 403, f"{method} {path} answered about an account"
    # The guard on the guard: a rename that emptied this loop would otherwise
    # leave a green test asserting nothing at all. A floor rather than a pinned
    # count, because the exact number moves whenever a route gains or loses the
    # parameter for its own reasons, and it is the sweep that matters.
    assert asked > 15, f"only {asked} guest routes take an account — has deps changed?"
