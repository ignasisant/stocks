"""The demo book over HTTP: seeding one, removing it, and losing it.

What the book *is* — its rows, its prices, the two promises that make a
fabricated ledger safe inside an app that also files tax reports — belongs to
`stocks.portfolio.demo` and is tested in test_demo.py. What is tested here is
what the route adds:

* an empty account can fill every ledger-derived surface without handing over
  a real statement, and a client can see the rows afterwards;
* seeding is refused rather than silently ignored on a book that holds
  anything, because a second copy of the book is a doubled cost basis;
* the rows stay marked, and the first real import through `/v1/import/commit`
  still deletes them — the promise the whole feature rests on;
* a bearer token names nobody, and nobody may invite invented lots into
  somebody else's book.

The account reckons in USD, which is what every demo row is in: no rate is
ever looked up, so nothing here touches the network.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.portfolio import demo
from stocks.portfolio.ledger import Transaction, add_many, all_transactions

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

REAL = Transaction("2026-01-05", "AAPL", "buy", 1, 150.0, "USD", 1.0, "revolut Apple")


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def _cold_caches():
    """Ledger-derived loaders are process-wide memos keyed on (db, mtime, base),
    which two tmp books inside one mtime tick share. Swept off the module so a
    loader added later is not one this file forgets."""
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
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    # USD, the currency every demo row is in: a book that needs no conversion
    # needs no exchange rate, and so reaches no network.
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
    """A browser session for EMAIL — what a write needs, since a token cannot."""
    return sign_in(client, EMAIL)


# ------------------------------------------------------------------ seeding


def test_seeding_an_empty_book_writes_the_whole_demo_book(client, account, signed_in):
    response = signed_in.post("/v1/portfolio/demo")
    assert response.status_code == 200
    assert response.json() == {"active": True, "rows": len(demo.transactions())}

    rows = all_transactions(account.db)
    assert len(rows) == len(demo.transactions())
    assert all(demo.is_demo(t) for t in rows), "every row has to stay marked"


def test_the_seeded_book_is_there_to_be_read(client, account, signed_in):
    """The point of it: an account that has imported nothing can still see the
    ledger half of the app with something in it."""
    signed_in.post("/v1/portfolio/demo")
    body = client.get(
        "/v1/portfolio/transactions", params=WHO | {"limit": 1000}, headers=AUTH
    ).json()
    assert body["total"] == len(demo.transactions())
    assert {t["action"] for t in body["transactions"]} >= {
        "buy", "sell", "dividend", "fee"
    }
    assert {t["note"].split()[0] for t in body["transactions"]} == {demo.BROKER}


def test_seeding_twice_is_refused_rather_than_answered_with_zero(
    client, account, signed_in
):
    """A double click and a stale retry both arrive here, and a second copy of
    the book would be a doubled cost basis. "ok, 0 rows" would have the client
    show a book that was never written."""
    assert signed_in.post("/v1/portfolio/demo").status_code == 200
    second = signed_in.post("/v1/portfolio/demo")
    assert second.status_code == 409
    assert "demo" in second.json()["detail"]
    assert len(all_transactions(account.db)) == len(demo.transactions())


def test_a_book_with_real_rows_in_it_is_never_seeded(client, account, signed_in):
    """The offer is only ever made on the empty path; a route has to enforce
    what a page merely does not show."""
    add_many([REAL], account.db)
    response = signed_in.post("/v1/portfolio/demo")
    assert response.status_code == 409
    assert "transactions" in response.json()["detail"]
    assert len(all_transactions(account.db)) == 1


# ----------------------------------------------------------------- removing


def test_clearing_removes_the_demo_rows_and_only_those(client, account, signed_in):
    signed_in.post("/v1/portfolio/demo")
    add_many([REAL], account.db)

    response = signed_in.request("DELETE", "/v1/portfolio/demo")
    assert response.status_code == 200
    assert response.json() == {"active": False, "rows": len(demo.transactions())}
    assert [t.ticker for t in all_transactions(account.db)] == ["AAPL"]
    assert not demo.active(account.db)


def test_clearing_a_book_that_has_none_is_a_404(client, account, signed_in):
    assert signed_in.request("DELETE", "/v1/portfolio/demo").status_code == 404
    signed_in.post("/v1/portfolio/demo")
    assert signed_in.request("DELETE", "/v1/portfolio/demo").status_code == 200
    assert signed_in.request("DELETE", "/v1/portfolio/demo").status_code == 404


# ------------------------------------------------- what a real import does to it

LEDGER_CSV = """date,ticker,action,quantity,price,currency,fee,note
2026-01-02,AAPL,buy,10,100.00,USD,1.00,revolut Apple
"""


def test_the_first_real_import_takes_the_demo_book_with_it(
    client, account, signed_in
):
    """The promise the whole feature rests on: an invented cost basis must
    never end up mixed into a real one, whichever surface seeded it."""
    signed_in.post("/v1/portfolio/demo")
    assert demo.active(account.db)

    committed = signed_in.post(
        "/v1/import/commit",
        json={
            "platform": "generic",
            "filename": "ledger.csv",
            "content": base64.b64encode(LEDGER_CSV.encode()).decode(),
        },
    ).json()
    assert committed["imported"] == 1

    rows = all_transactions(account.db)
    assert not any(demo.is_demo(t) for t in rows)
    assert [(t.ticker, t.quantity) for t in rows] == [("AAPL", 10.0)]


def test_the_demo_rows_are_not_the_baseline_a_statement_is_checked_against(
    client, account, signed_in
):
    """They are about to be deleted, so a sell validated against them is
    validated against lots that will not exist a moment later.

    The demo book holds 30 AAPL. Nothing real does — so this sale is an
    oversell, and it has to be quarantined rather than let into a real book on
    the strength of shares nobody owns.
    """
    signed_in.post("/v1/portfolio/demo")
    sale = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2026-06-01,AAPL,sell,15,250.00,USD,1.00,revolut Apple\n"
    )
    preview = signed_in.post(
        "/v1/import/preview",
        json={
            "platform": "generic",
            "filename": "ledger.csv",
            "content": base64.b64encode(sale.encode()).decode(),
        },
    ).json()
    assert [r["ticker"] for r in preview["rejected"]] == ["AAPL"]
    assert preview["importable"] == []


# --------------------------------------------------------------------- gate


def test_a_token_can_neither_seed_nor_clear_the_demo_book(client, account):
    """No session fixture here on purpose: a request carrying both a cookie and
    a token is a session request, and the token would never be reached."""
    assert client.post(
        "/v1/portfolio/demo", params=WHO, headers=AUTH
    ).status_code == 403
    assert all_transactions(account.db) == []

    demo.seed(account.db)
    assert client.request(
        "DELETE", "/v1/portfolio/demo", params=WHO, headers=AUTH
    ).status_code == 403
    assert demo.active(account.db)
