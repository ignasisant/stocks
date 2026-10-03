"""Hand edits over HTTP: plan, commit under the plan's token, undo, history.

What an edit *does* is `stocks.portfolio.edits` and tested in test_edits.py.
What is tested here is what the routes add: a plan writes nothing, a commit
needs the token back and a session behind it, the errors map to the status a
client can act on (409 plan again, 422 fix the edit, 404 no such change), and
the ledger listing narrows to the rows a person names.

The book is in euros and so is the account: no rate is looked up, so nothing
here touches the network.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.portfolio.ledger import Transaction, add, add_many, all_transactions

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

# The Grifols move nothing paired: DEGIRO's sale under the ISIN, IBKR's buy
# at the carried basis under the symbol.
BOOK = [
    Transaction("2024-03-01", "ES0171996087", "buy", 100, 8.0, "EUR", 2.0,
                "degiro GRIFOLS"),
    Transaction("2026-08-06", "ES0171996087", "sell", 100, 12.0, "EUR", 0.0,
                "degiro GRIFOLS"),
    Transaction("2026-08-20", "GRF.MC", "buy", 100, 8.02, "EUR", 0.0, "ibkr"),
]


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def _cold_caches():
    memos = [
        fn for fn in vars(loaders).values() if callable(fn) and hasattr(fn, "cache_clear")
    ]
    for fn in memos:
        fn.cache_clear()
    yield
    for fn in memos:
        fn.cache_clear()


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist: []\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    add_many(BOOK, paths.db)
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    return sign_in(client, EMAIL)


def ids(account):
    return [t.id for t in all_transactions(account.db)]


def repair(account):
    buy, sale, arrival = ids(account)
    return [
        {"op": "set_action", "ids": [sale], "action": "transfer_out"},
        {"op": "set_action", "ids": [arrival], "action": "transfer_in"},
        {"op": "relabel", "ids": [buy, sale], "to": "GRF.MC"},
    ]


def test_a_plan_shows_the_phantom_gain_going_and_writes_nothing(account, signed_in):
    before = all_transactions(account.db)
    response = signed_in.post("/v1/portfolio/changes/plan", json={"ops": repair(account)})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["token"]
    assert {c["kind"] for c in body["changes"]} == {"updated"}
    (effect,) = body["effects"]
    assert effect["realized_before"] == {"2026": pytest.approx(398.0)}
    assert effect["realized_after"] == {}
    assert all_transactions(account.db) == before


def test_commit_then_undo_round_trips_the_book(account, signed_in):
    before = all_transactions(account.db)
    ops = repair(account)
    planned = signed_in.post("/v1/portfolio/changes/plan", json={"ops": ops}).json()
    done = signed_in.post(
        "/v1/portfolio/changes",
        json={"ops": ops, "token": planned["token"], "summary": "Grifols move"},
    )
    assert done.status_code == 201
    change = done.json()
    assert change["source"] == "api" and change["summary"] == "Grifols move"
    assert {t.action for t in all_transactions(account.db)} == {
        "buy", "transfer_out", "transfer_in"
    }

    history = signed_in.get("/v1/portfolio/changes", params=WHO).json()["changes"]
    assert [c["id"] for c in history] == [change["id"]]

    undone = signed_in.request("DELETE", f"/v1/portfolio/changes/{change['id']}")
    assert undone.status_code == 200 and undone.json()["undone_at"]
    assert all_transactions(account.db) == before
    # Twice is a conflict, not a second undo.
    again = signed_in.request("DELETE", f"/v1/portfolio/changes/{change['id']}")
    assert again.status_code == 409


def test_a_book_that_moved_since_the_plan_is_a_409(account, signed_in):
    ops = repair(account)
    planned = signed_in.post("/v1/portfolio/changes/plan", json={"ops": ops}).json()
    add(Transaction("2026-09-01", "SAN.MC", "buy", 10, 4.0, "EUR"), account.db)
    response = signed_in.post(
        "/v1/portfolio/changes", json={"ops": ops, "token": planned["token"]}
    )
    assert response.status_code == 409
    assert "plan it again" in response.json()["detail"]
    assert "transfer_out" not in {t.action for t in all_transactions(account.db)}


def test_an_edit_that_breaks_the_book_plans_with_problems_and_will_not_commit(
    account, signed_in
):
    buy = ids(account)[0]
    ops = [{"op": "delete", "ids": [buy]}]
    planned = signed_in.post("/v1/portfolio/changes/plan", json={"ops": ops}).json()
    assert not planned["ok"] and "exceeds held" in planned["problems"][0]
    response = signed_in.post(
        "/v1/portfolio/changes", json={"ops": ops, "token": planned["token"]}
    )
    assert response.status_code == 422
    assert len(all_transactions(account.db)) == 3


def test_a_malformed_edit_is_a_422_that_says_why(account, signed_in):
    response = signed_in.post(
        "/v1/portfolio/changes/plan", json={"ops": [{"op": "delete", "ids": [999]}]}
    )
    assert response.status_code == 422
    assert "not in the book" in response.json()["detail"]
    empty = signed_in.post("/v1/portfolio/changes/plan", json={"ops": []})
    assert empty.status_code == 422


def test_undoing_a_change_that_never_was_is_a_404(account, signed_in):
    assert signed_in.request("DELETE", "/v1/portfolio/changes/42").status_code == 404


def test_a_token_reads_the_history_and_writes_nothing(client, account):
    assert client.get(
        "/v1/portfolio/changes", params=WHO, headers=AUTH
    ).json() == {"changes": []}
    response = client.post(
        "/v1/portfolio/changes/plan",
        params=WHO,
        headers=AUTH,
        json={"ops": [{"op": "delete", "ids": [ids(account)[0]]}]},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "query, expected",
    [
        ({"ticker": "GRF"}, ["GRF.MC"]),
        ({"broker": "degiro"}, ["ES0171996087", "ES0171996087"]),
        ({"action": "sell"}, ["ES0171996087"]),
        ({"from": "2026-01-01", "to": "2026-08-10"}, ["ES0171996087"]),
        ({}, ["GRF.MC", "ES0171996087", "ES0171996087"]),
    ],
)
def test_the_ledger_narrows_to_the_rows_a_person_names(client, account, query, expected):
    body = client.get(
        "/v1/portfolio/transactions", params=WHO | query, headers=AUTH
    ).json()
    assert [t["ticker"] for t in body["transactions"]] == expected
    assert body["total"] == len(expected)


def test_health_finds_the_move_and_its_fix_goes_through_the_same_two_steps(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(
        loaders, "display_symbol", {"ES0171996087": "GRF.MC"}.get
    )
    body = client.get("/v1/portfolio/health", params=WHO, headers=AUTH).json()
    [finding] = body["findings"]
    assert finding["kind"] == "transfer"
    assert finding["detail"]["phantom_gain"] == pytest.approx(398.0)

    planned = signed_in.post(
        "/v1/portfolio/changes/plan", json={"ops": finding["fix"]}
    ).json()
    done = signed_in.post(
        "/v1/portfolio/changes", json={"ops": finding["fix"], "token": planned["token"]}
    )
    assert done.status_code == 201
    after = client.get("/v1/portfolio/health", params=WHO, headers=AUTH).json()
    assert after == {"findings": []}
