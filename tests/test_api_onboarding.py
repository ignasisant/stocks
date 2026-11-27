"""The tour and "what's new" over HTTP.

What belongs in the registry at all is `CLAUDE.md`'s rule and
`tests/test_onboarding.py`'s job. What is tested here is the wire:

* the steps and the cards come from the registry, so the tour and the
  walkthrough cannot announce different things;
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
def booked(monkeypatch):
    """The account has a book of its own, without writing one."""
    monkeypatch.setattr(onboarding, "_has_ledger", lambda prefs, paths: True)


#: Welcomed two months ago, and releases have shipped since.
STALE = {onboarding.PREF_SEEN_VERSION: "2026.09", onboarding.PREF_DONE: True}


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


def test_the_section_guide_is_marked_on_the_steps(client, account, signed_in):
    """The client draws the guide from the same list as every other stop, so
    which stops are in it has to come with them."""
    body = signed_in.get("/v1/onboarding").json()
    assert [s["id"] for s in body["steps"] if s["core"]] == [
        s.id for s in onboarding.visible_steps() if s.core
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
    # Home is the root path; a step that lands nowhere says so with null.
    assert steps["daily"]["path"] == ""
    assert steps["welcome"]["path"] is None


def test_a_new_account_is_dealt_no_news(client, account, signed_in):
    """Nothing is new to someone who has not seen what is old."""
    body = signed_in.get("/v1/onboarding").json()
    assert body["seen_version"] is None
    assert body["news"] == []
    assert body["version"] == onboarding.CURRENT_VERSION


def test_an_account_with_no_book_is_dealt_no_news_on_a_later_day(
    client, account, signed_in
):
    """The bug this guards: the welcome stamped the account on its first load,
    and every release after that opened "what's new" on its next visit."""
    account.prefs.write_text(json.dumps(STALE))
    assert onboarding.unseen_news(STALE)
    assert signed_in.get("/v1/onboarding").json()["news"] == []


def test_an_account_that_knows_the_app_is_dealt_what_shipped(
    client, account, signed_in, booked
):
    account.prefs.write_text(json.dumps(STALE))
    body = signed_in.get("/v1/onboarding").json()
    assert len(body["news"]) == len(onboarding.unseen_news(STALE))
    assert body["news"]


def test_an_account_from_before_the_guide_is_dealt_what_shipped(
    client, account, signed_in, booked
):
    """Every account older than the guide: a book, an old stamp and none of
    the newcomer's prefs. It is nobody's newcomer, and its news must not stop."""
    old = {onboarding.PREF_SEEN_VERSION: "2026.09"}
    account.prefs.write_text(json.dumps(old))
    body = signed_in.get("/v1/onboarding").json()
    assert len(body["news"]) == len(onboarding.unseen_news(old))
    assert body["news"]
    assert signed_in.get("/v1/prefs").json()["tour_offer"] is False


def test_the_capabilities_are_read_for_this_account_not_a_session(
    client, account, signed_in
):
    """There is no ambient session behind an API call. `login` is true because
    the dependency proved it, and `import` is answered off this account's own
    ledger rather than off whichever one a session happened to hold."""
    body = signed_in.get("/v1/onboarding").json()
    assert body["setup"] == {
        "login": True,
        "import": False,
        "ai": False,
        "notify": False,
        "plan": False,
    }
    # The watchlist file exists and is not the seeded one, so this is true —
    # proof the predicate read the account's paths and not a missing session.
    assert body["explore"]["watchlist"] is True


def test_a_guest_is_not_reported_as_signed_in(client):
    """The route is guest-open, and it used to hard-code `signed_in=True` — so
    an anonymous visitor read "Google sign-in ✓ Active" off the setup card."""
    body = client.get("/v1/onboarding").json()
    assert body["signed_in"] is False
    assert body["setup"]["login"] is False


def test_a_session_is_reported_as_signed_in(client, account, signed_in):
    assert signed_in.get("/v1/onboarding").json()["signed_in"] is True


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
    account.prefs.write_text(json.dumps({"currency": "USD", "notify_alerts": False}))
    signed_in.post("/v1/onboarding/seen", json={})
    stored = json.loads(account.prefs.read_text())
    assert stored["currency"] == "USD"
    assert stored["notify_alerts"] is False


def test_a_token_cannot_mark_an_announcement_as_read(client, account):
    response = client.post(
        "/v1/onboarding/seen", params={"account": EMAIL}, headers=AUTH, json={}
    )
    assert response.status_code == 403
    assert onboarding.PREF_SEEN_VERSION not in json.loads(account.prefs.read_text())


# ------------------------------------------------------------ first-visit tips


def test_a_page_tip_names_its_lines_and_its_lesson(client, account, signed_in):
    body = signed_in.get("/v1/onboarding/tips/portfolio", params={"lang": "es"}).json()
    assert body["page"] == "portfolio"
    assert body["lines"] == onboarding.TIPS["portfolio"].lines
    assert body["lesson"]["id"] == onboarding.TIPS["portfolio"].lesson
    assert body["lesson"]["title"] and body["lesson"]["minutes"] > 0


def test_a_page_with_no_lesson_says_so(client, account, signed_in):
    page = next(p for p, tip in onboarding.TIPS.items() if tip.lesson is None)
    assert signed_in.get(f"/v1/onboarding/tips/{page}").json()["lesson"] is None


def test_a_page_with_no_tip_is_not_found(client, account, signed_in):
    assert signed_in.get("/v1/onboarding/tips/nowhere").status_code == 404
    assert signed_in.post("/v1/onboarding/tips/nowhere", json={}).status_code == 404


def test_reading_a_tip_strikes_only_that_page(client, account, signed_in):
    onboarding.first_book(account.prefs)
    body = signed_in.post("/v1/onboarding/tips/today", json={}).json()
    assert body["page_tips"] == [p for p in onboarding.TIPS if p != "today"]
    prefs = signed_in.get("/v1/prefs").json()
    assert prefs["page_tips"] == body["page_tips"]
    assert prefs["tour_offer"] is True


def test_an_account_never_stamped_is_owed_nothing(client, account, signed_in):
    prefs = signed_in.get("/v1/prefs").json()
    assert prefs["tour_offer"] is False
    assert prefs["page_tips"] == []


def test_a_token_cannot_mark_a_tip_read(client, account):
    onboarding.first_book(account.prefs)
    response = client.post(
        "/v1/onboarding/tips/today", params={"account": EMAIL}, headers=AUTH, json={}
    )
    assert response.status_code == 403
    assert "today" in json.loads(account.prefs.read_text())[onboarding.PREF_TIPS]


def test_answering_the_guide_withdraws_the_home_offer(client, account, signed_in):
    """Finished, skipped or turned down. Reading a card and the welcome's own
    first load are neither: the offer stands through both."""
    onboarding.first_book(account.prefs)
    signed_in.post("/v1/onboarding/seen", json={})
    signed_in.post("/v1/onboarding/seen", json={"done": True})
    assert json.loads(account.prefs.read_text())[onboarding.PREF_OFFER] is True
    body = signed_in.post("/v1/onboarding/seen", json={"walked": True}).json()
    assert body["tour_done"] is True
    assert json.loads(account.prefs.read_text())[onboarding.PREF_OFFER] is False


def test_only_a_guide_walked_to_its_end_strikes_page_tips(client, account, signed_in):
    onboarding.first_book(account.prefs)
    signed_in.post("/v1/onboarding/seen", json={"walked": True})
    assert signed_in.get("/v1/prefs").json()["page_tips"] == list(onboarding.TIPS)
    body = signed_in.post("/v1/onboarding/seen", json={"finished": True}).json()
    assert body["tour_done"] is True
    shown = onboarding.guided_pages()
    assert signed_in.get("/v1/prefs").json()["page_tips"] == [
        page for page in onboarding.TIPS if page not in shown
    ]


def test_the_offer_cannot_be_withdrawn_without_the_stamp(client, account, signed_in):
    """It was a setting once, and "not now" left the account on its old stamp:
    the next visit dealt it every card it had been spared."""
    onboarding.first_book(account.prefs)
    assert signed_in.patch("/v1/prefs", json={"tour_offer": False}).status_code == 422
    assert signed_in.get("/v1/prefs").json()["tour_offer"] is True


def _walks_then_imports(session, account):
    session.post("/v1/onboarding/seen", json={"walked": True})
    # Releases ship between the walk and the import.
    accounts.update_prefs(account.prefs, {onboarding.PREF_SEEN_VERSION: "2026.09"})
    onboarding.first_book(account.prefs)


def _imports_then_answers(session, account):
    onboarding.first_book(account.prefs)
    session.post("/v1/onboarding/seen", json={"walked": True})


@pytest.mark.parametrize("leave", [_walks_then_imports, _imports_then_answers])
def test_no_way_out_of_being_new_leaves_a_backlog(
    client, account, signed_in, booked, leave
):
    """Whichever way an account stops being a newcomer, it leaves caught up:
    the cards it was spared while it was new do not fall on it afterwards."""
    account.prefs.write_text(json.dumps(STALE))
    leave(signed_in, account)
    body = signed_in.get("/v1/onboarding").json()
    assert body["news"] == []
    assert body["seen_version"] == onboarding.CURRENT_VERSION
    assert signed_in.get("/v1/prefs").json()["tour_offer"] is False


# -------------------------------------------------------------------- wizard


def test_the_wizard_reports_each_screen_with_a_closed_vocabulary(
    signed_in, account, monkeypatch
):
    from stocks import obs

    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(obs, "event", lambda name, **kw: seen.append((name, kw)))
    body = {"step": "residence", "action": "answered", "value": "es", "ms": 4200}
    assert signed_in.post("/v1/onboarding/wizard", json=body).status_code == 204
    assert seen == [("wizard.step", body)]


@pytest.mark.parametrize(
    "bad",
    [
        {"step": "nowhere", "action": "shown"},
        {"step": "ai", "action": "typed"},
        {"step": "notes", "action": "answered", "value": "Free Text"},
        {"step": "notes", "action": "answered", "value": "a" * 61},
        {"step": "ai", "action": "shown", "ms": -1},
        {"step": "ai", "action": "shown", "extra": 1},
    ],
)
def test_the_wizard_refuses_anything_that_could_carry_free_text(
    signed_in, account, monkeypatch, bad
):
    from stocks import obs

    monkeypatch.setattr(obs, "event", lambda *a, **k: pytest.fail("logged"))
    assert signed_in.post("/v1/onboarding/wizard", json=bad).status_code == 422
