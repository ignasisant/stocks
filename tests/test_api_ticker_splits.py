"""The Ticker page repairs a split the book is missing, by itself and undoably.

A statement prints one AMZN bought at $2050 before the 2022 20-for-1, and the
page then shows a $378 average against a $250 share and a 33% loss on a
position that roughly doubled. The evidence is the page's own: the buy price
against the split-adjusted close of its day. What is tested here is the
binding the page leans on:

* `GET /ticker/{symbol}/splits` names the gap with its evidence, writes
  nothing, and costs no Yahoo round trip for a name the book never bought;
* `POST` writes the named days as one journalled edit, so
  `DELETE /portfolio/changes/{id}` takes it back — and once taken back the
  scan marks it `declined`, which is what keeps the page from writing it again
  on the next visit;
* a day the scan does not propose is a 409, and a token cannot write.

Yahoo is replaced with the answers it gives for the real split.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.data import fetch
from stocks.portfolio.ledger import Transaction, add_many, all_transactions

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

SPLITS = {"AMZN": [("1999-09-02", 2.0), ("2022-06-06", 20.0)]}
CLOSES = {("AMZN", "2022-05-24"): 104.10}

BOOK = [
    Transaction("2022-05-24", "AMZN", "buy", 1.0, 2050.0, "USD", 0.0, "clicktrade"),
    Transaction("2026-02-18", "AMZN", "buy", 9.72545587, 205.65, "USD", 0.0, "revolut"),
]


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
    paths.watchlist.write_text("watchlist:\n  - ticker: AMZN\n")
    paths.prefs.write_text(json.dumps({"currency": "USD"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    return sign_in(client, EMAIL)


@pytest.fixture
def yahoo(monkeypatch):
    asked: list[str] = []

    def splits(ticker):
        asked.append(ticker)
        return list(SPLITS.get(ticker, []))

    monkeypatch.setattr(fetch, "splits", splits)
    monkeypatch.setattr(fetch, "close_on", lambda ticker, day: CLOSES.get((ticker, day)))
    return asked


def scan(client, ticker="AMZN"):
    return client.get(f"/v1/ticker/{ticker}/splits", params=WHO, headers=AUTH).json()


def split_rows(account):
    return [t for t in all_transactions(account.db) if t.action == "split"]


def test_the_scan_names_the_split_with_its_evidence_and_writes_nothing(
    client, account, yahoo
):
    add_many(BOOK, account.db)
    payload = scan(client)
    assert payload["ticker"] == "AMZN"
    [gap] = payload["splits"]
    assert (gap["date"], gap["ratio"]) == ("2022-06-06", 20.0)
    assert gap["held_before"] == 1.0 and gap["held_after"] == 20.0
    assert (gap["priced_at"], gap["priced_on"]) == (2050.0, "2022-05-24")
    assert gap["declined"] is False
    assert not split_rows(account)


def test_a_name_the_book_never_bought_asks_yahoo_nothing(client, account, yahoo):
    add_many(BOOK, account.db)
    assert scan(client, "MSFT")["splits"] == []
    assert yahoo == []


def test_a_book_that_already_has_the_split_is_clean(client, account, yahoo):
    add_many(
        [*BOOK, Transaction("2022-06-06", "AMZN", "split", 20.0, 0.0, "USD")],
        account.db,
    )
    assert scan(client)["splits"] == []


def test_applying_writes_the_split_and_fixes_the_position(
    client, account, signed_in, yahoo
):
    add_many(BOOK, account.db)
    response = signed_in.post("/v1/ticker/AMZN/splits", json={"dates": ["2022-06-06"]})
    assert response.status_code == 201
    payload = response.json()
    assert payload["change_id"] > 0
    assert [(t.ticker, t.date, t.quantity) for t in split_rows(account)] == [
        ("AMZN", "2022-06-06", 20.0)
    ]
    position = client.get("/v1/ticker/AMZN/position", params=WHO, headers=AUTH).json()
    assert position["shares"] == pytest.approx(29.72545587)
    assert position["avg_cost_native"] == pytest.approx(4050.0 / 29.72545587, rel=1e-3)
    assert scan(client)["splits"] == []


def test_an_undone_repair_is_declined_and_stays_proposable(
    client, account, signed_in, yahoo
):
    """The page repairs on its own only what the reader has not refused."""
    add_many(BOOK, account.db)
    applied = signed_in.post(
        "/v1/ticker/AMZN/splits", json={"dates": ["2022-06-06"]}
    ).json()
    undo = signed_in.delete(f"/v1/portfolio/changes/{applied['change_id']}")
    assert undo.status_code == 200
    assert not split_rows(account)
    [gap] = scan(client)["splits"]
    assert gap["declined"] is True
    # …and the reader may still change their mind by hand.
    again = signed_in.post("/v1/ticker/AMZN/splits", json={"dates": ["2022-06-06"]})
    assert again.status_code == 201


def test_a_split_nobody_proposed_is_refused(client, account, signed_in, yahoo):
    add_many(BOOK, account.db)
    response = signed_in.post("/v1/ticker/AMZN/splits", json={"dates": ["1999-09-02"]})
    assert response.status_code == 409
    assert not split_rows(account)


def test_writing_it_twice_is_refused(client, account, signed_in, yahoo):
    add_many(BOOK, account.db)
    body = {"dates": ["2022-06-06"]}
    assert signed_in.post("/v1/ticker/AMZN/splits", json=body).status_code == 201
    assert signed_in.post("/v1/ticker/AMZN/splits", json=body).status_code == 409
    assert len(split_rows(account)) == 1


def test_a_token_cannot_write(client, account, yahoo):
    add_many(BOOK, account.db)
    response = client.post(
        "/v1/ticker/AMZN/splits",
        params=WHO,
        headers=AUTH,
        json={"dates": ["2022-06-06"]},
    )
    assert response.status_code == 403
    assert not split_rows(account)
