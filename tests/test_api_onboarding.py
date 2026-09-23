"""The tour and "what's new" over HTTP.

What belongs in the registry at all is `CLAUDE.md`'s rule and
`tests/test_onboarding.py`'s job. What is tested here is the wire:

* the steps and the cards come from the same registry the Streamlit modal
  reads, so the two front ends cannot announce different things;
* copy is named, never sent — a payload carrying strings would be a second
  catalog, stale in whichever language the reader picked;
* `done` is `null` for a step that is nothing to switch on, because a tick
  beside a page would be a claim about nothing;
* the stamp is a write and refuses a token, which is the whole reason it is a
  POST and not a query parameter.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.web import onboarding

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

WATCHLIST = "watchlist:\n  - ticker: AAPL\n"


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text(WATCHLIST)
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    """A browser session for EMAIL — what a write needs, since a token cannot."""
    return sign_in(client, EMAIL)


# ------------------------------------------------------------------- reading


def test_the_steps_are_the_ones_the_modal_shows(client, account, signed_in):
    body = signed_in.get("/v1/onboarding").json()
    assert [s["id"] for s in body["steps"]] == [
        s.id for s in onboarding.visible_steps()
    ]


def test_copy_is_named_and_never_sent(client, account, signed_in):
    """Keys, not strings. The client has the catalog; a second copy on the wire
    would be stale in whichever language the reader actually picked."""
    body = signed_in.get("/v1/onboarding").json()
    step = body["steps"][0]
    assert step["title_key"] == f"tour.{step['id']}_title"
    assert step["body_key"] == f"tour.{step['id']}_body"
    assert not any(isinstance(v, str) and " " in v for v in step.values() if v)


def test_a_page_is_not_a_capability(client, account, signed_in):
    """`done` is null for a step with nothing to switch on — a tick beside
    "here is the Positions tab" would be a claim about nothing."""
    steps = {s["id"]: s for s in signed_in.get("/v1/onboarding").json()["steps"]}
    assert steps["positions"]["done"] is None
    assert steps["import"]["done"] is False  # nothing imported in this fixture


def test_the_step_carries_where_it_lands(client, account, signed_in):
    steps = {s["id"]: s for s in signed_in.get("/v1/onboarding").json()["steps"]}
    assert steps["import"]["path"] == "import_transactions"
    assert steps["tax"]["params"] == {"tab": "tax"}
    # The default page is served at the root, and says so rather than guessing.
    assert steps["welcome"]["path"] is None


def test_a_new_account_is_owed_every_card(client, account, signed_in):
    body = signed_in.get("/v1/onboarding").json()
    assert body["seen_version"] is None
    assert len(body["news"]) == len(onboarding.unseen_news({}))
    assert body["version"] == onboarding.CURRENT_VERSION


def test_the_capabilities_are_read_for_this_account_not_a_session(
    client, account, signed_in
):
    """There is no Streamlit session behind an API call. `login` is true because
    the dependency proved it, and `import` is answered off this account's own
    ledger rather than off whichever one a session happened to hold."""
    body = signed_in.get("/v1/onboarding").json()
    assert body["setup"] == {
        "login": True,
        "import": False,
        "ai": False,
        "telegram": False,
    }
    # The watchlist file exists and is not the seeded one, so this is true —
    # proof the predicate read the account's paths and not a missing session.
    assert body["explore"]["watchlist"] is True


# ------------------------------------------------------------------- writing


def test_the_stamp_catches_the_account_up(client, account, signed_in):
    body = signed_in.post("/v1/onboarding/seen", json={}).json()
    assert body["seen_version"] == onboarding.CURRENT_VERSION
    assert body["news"] == []
    stored = json.loads(account.prefs.read_text())
    assert stored[onboarding.PREF_SEEN_VERSION] == onboarding.CURRENT_VERSION


def test_finishing_the_tour_retires_it(client, account, signed_in):
    body = signed_in.post("/v1/onboarding/seen", json={"done": True}).json()
    assert body["tour_done"] is True
    assert json.loads(account.prefs.read_text())[onboarding.PREF_DONE] is True


def test_the_stamp_leaves_the_rest_of_the_settings_alone(
    client, account, signed_in
):
    account.prefs.write_text(json.dumps({"currency": "USD", "notify_digest": False}))
    signed_in.post("/v1/onboarding/seen", json={})
    stored = json.loads(account.prefs.read_text())
    assert stored["currency"] == "USD"
    assert stored["notify_digest"] is False


def test_a_token_cannot_mark_an_announcement_as_read(client, account):
    response = client.post(
        "/v1/onboarding/seen", params={"account": EMAIL}, headers=AUTH, json={}
    )
    assert response.status_code == 403
    assert onboarding.PREF_SEEN_VERSION not in json.loads(account.prefs.read_text())
