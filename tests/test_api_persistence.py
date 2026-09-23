"""Every write reaches the bucket, not just the local disk.

The container's filesystem is ephemeral: a write that lands locally and is
never mirrored is a change the reader watches disappear on the next restart,
with nothing having failed anywhere. `stocks.storage.persist` is what closes
that gap, and it is called deep inside the domain — which is right, and which
also means a new route can forget it by using a primitive that does not.

So this file does not check any particular call site. It runs each write the
API offers and asserts that the file it changed was handed to `persist`, which
is the property that actually matters and the one a future route will break.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app

EMAIL = "holder@example.com"

LEDGER_CSV = """date,ticker,action,quantity,price,currency,fee,note
2024-01-02,AAPL,buy,10,100.00,EUR,1.00,revolut Apple
"""


@pytest.fixture
def persisted(monkeypatch) -> list[str]:
    """Every path handed to the bucket, in order."""
    seen: list[str] = []
    monkeypatch.setattr("stocks.storage.persist", lambda path: seen.append(str(path)))
    monkeypatch.setattr("stocks.storage.restore", lambda path: False)
    return seen


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n    tags: [Tech]\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    return paths


@pytest.fixture
def client(sign_in) -> TestClient:
    return sign_in(TestClient(fastapi_app), EMAIL)


def upload() -> dict:
    return {
        "platform": "generic",
        "filename": "ledger.csv",
        "content": base64.b64encode(LEDGER_CSV.encode()).decode(),
    }


def test_a_settings_change_is_mirrored(client, account, persisted):
    assert client.patch("/v1/prefs", json={"currency": "USD"}).status_code == 200
    assert str(account.prefs) in persisted


def test_a_recorded_search_is_mirrored(client, account, persisted):
    client.post("/v1/search/recent", json={"ticker": "NVDA"})
    assert str(account.prefs) in persisted


def test_adding_a_ticker_is_mirrored(client, account, persisted):
    client.post("/v1/watchlist", json={"ticker": "MSFT"})
    assert str(account.watchlist) in persisted


def test_editing_a_ticker_is_mirrored(client, account, persisted):
    client.patch("/v1/watchlist/AAPL", json={"favorite": True})
    assert str(account.watchlist) in persisted


def test_removing_a_ticker_is_mirrored(client, account, persisted):
    client.delete("/v1/watchlist/AAPL")
    assert str(account.watchlist) in persisted


def test_replacing_alert_rules_is_mirrored(client, account, persisted):
    client.put(
        "/v1/watchlist/AAPL/alerts", json={"alerts": [{"type": "above", "price": 250}]}
    )
    assert str(account.watchlist) in persisted


def test_renaming_a_tag_group_is_mirrored(client, account, persisted):
    client.patch("/v1/watchlist/tags/Tech", json={"name": "Software"})
    assert str(account.watchlist) in persisted


def test_ungrouping_is_mirrored(client, account, persisted):
    client.delete("/v1/watchlist/tags/Tech")
    assert str(account.watchlist) in persisted


def test_a_commit_mirrors_both_the_ledger_and_its_receipt(
    client, account, persisted
):
    """Two files change, and an undo needs the second one as much as the first:
    a ledger that came back without its import record cannot be undone."""
    assert client.post("/v1/import/commit", json=upload()).status_code == 200
    assert str(account.db) in persisted
    assert str(account.last_import) in persisted


def test_an_undo_is_mirrored(client, account, persisted):
    client.post("/v1/import/commit", json=upload())
    persisted.clear()
    client.delete("/v1/import/last")
    assert str(account.db) in persisted
    assert str(account.last_import) in persisted


def test_a_wipe_is_mirrored(client, account, persisted):
    """The one write nobody can redo locally, so the one that must not be the
    only copy that knows."""
    client.post("/v1/import/commit", json=upload())
    persisted.clear()
    client.request("DELETE", "/v1/portfolio/transactions", json={"confirm": EMAIL})
    assert str(account.db) in persisted


def test_a_preview_mirrors_nothing(client, account, persisted):
    """It changes nothing, so it should not be waking the bucket either."""
    assert client.post("/v1/import/preview", json=upload()).status_code == 200
    assert persisted == []
