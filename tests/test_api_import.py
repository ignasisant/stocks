"""Importing a broker statement over HTTP.

Parsing a given broker's export and deciding which rows are importable belong
to `stocks.portfolio` and are tested there, per broker. What is tested here is
the contract the two endpoints add:

* a preview writes nothing, whatever it says;
* a commit does not trust the preview — it re-parses and re-validates, because
  the ledger is shared and moves under both;
* a row that fails validation is quarantined and reported, never committed;
* an undo removes exactly the ids that commit inserted, and nothing near them;
* the file travels as base64 in a JSON body, which is what keeps the CSRF
  argument the same as every other write here.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.portfolio import ledger
from stocks.portfolio.ledger import Transaction, all_transactions

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

CLEAN = """date,ticker,action,quantity,price,currency,fee,note
2024-01-02,AAPL,buy,10,100.00,EUR,1.00,revolut Apple
2024-02-01,MSFT,buy,5,200.00,EUR,1.00,revolut Microsoft
"""

# A sale of shares the book never held: validation rejects it, and the buy
# beside it still has to get through.
OVERSELL = """date,ticker,action,quantity,price,currency,fee,note
2024-03-01,NVDA,buy,4,500.00,EUR,1.00,revolut Nvidia
2024-03-02,TSLA,sell,99,200.00,EUR,1.00,revolut Tesla
"""


def upload(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


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
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
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


def body(text: str = CLEAN, **extra) -> dict:
    return {
        "platform": "generic",
        "filename": "ledger.csv",
        "content": upload(text),
        **extra,
    }


# ------------------------------------------------------------------- registry


def test_the_platforms_say_what_they_accept(client, account):
    payload = client.get("/v1/import/platforms", params=WHO, headers=AUTH).json()
    keys = {p["key"] for p in payload["platforms"]}
    assert {"revolut", "generic"} <= keys
    generic = next(p for p in payload["platforms"] if p["key"] == "generic")
    assert "csv" in generic["file_types"]


# -------------------------------------------------------------------- preview


def test_a_preview_writes_no_rows(client, account, signed_in):
    """It reads the ledger to validate against it — which opens the database —
    but nothing it parsed ends up in there, and no import is recorded."""
    payload = signed_in.post("/v1/import/preview", json=body()).json()
    assert len(payload["importable"]) == 2
    assert all_transactions(account.db) == []
    assert not account.last_import.exists()


def test_a_preview_hands_back_a_digest_of_what_it_read(client, account, signed_in):
    payload = signed_in.post("/v1/import/preview", json=body()).json()
    assert payload["digest"] == hashlib.sha256(CLEAN.encode()).hexdigest()


def test_a_rejected_row_is_reported_and_kept_out_of_importable(
    client, account, signed_in
):
    """A bad export must not be able to corrupt a cost basis quietly."""
    payload = signed_in.post("/v1/import/preview", json=body(OVERSELL)).json()
    assert [row["ticker"] for row in payload["importable"]] == ["NVDA"]
    assert [row["ticker"] for row in payload["rejected"]] == ["TSLA"]
    assert payload["rejected"][0]["issues"][0]["severity"] == "error"


def test_a_statement_that_names_its_broker_needs_no_second_answer(
    client, account, signed_in
):
    payload = signed_in.post("/v1/import/preview", json=body()).json()
    assert payload["broker"] == "revolut"  # the note's first word
    assert payload["needs_broker"] is False


def test_a_file_with_the_wrong_columns_is_told_which_ones(client, account, signed_in):
    """Not a 422: the caller needs the reason, and "which columns are missing"
    is exactly the thing a status code cannot carry."""
    response = signed_in.post("/v1/import/preview", json=body("not,a,ledger\n1,2,3\n"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["importable"] == []
    assert "date" in payload["skipped"][0]["reason"]


def test_a_platform_nobody_ships_is_a_404_not_a_silent_fallback(
    client, account, signed_in
):
    """`platforms.by_key` falls back to the first platform, which is right for a
    stale selectbox and wrong here: it would answer "0 importable rows"."""
    response = signed_in.post("/v1/import/preview", json=body(platform="etrade"))
    assert response.status_code == 404


def test_content_that_is_not_base64_is_refused(client, account, signed_in):
    response = signed_in.post(
        "/v1/import/preview", json=body() | {"content": "not base64!!"}
    )
    assert response.status_code == 422


def test_an_oversized_statement_is_refused_before_it_is_parsed(
    client, account, signed_in
):
    huge = base64.b64encode(b"x" * (8 * 1024 * 1024 + 1)).decode()
    response = signed_in.post("/v1/import/preview", json=body() | {"content": huge})
    assert response.status_code == 413


# --------------------------------------------------------------------- commit


def test_a_commit_writes_the_importable_rows(client, account, signed_in):
    payload = signed_in.post("/v1/import/commit", json=body()).json()
    assert payload["imported"] == 2
    assert len(payload["tx_ids"]) == 2
    assert {t.ticker for t in all_transactions(account.db)} == {"AAPL", "MSFT"}


def test_a_commit_refuses_a_file_that_is_not_the_one_previewed(
    client, account, signed_in
):
    digest = signed_in.post("/v1/import/preview", json=body()).json()["digest"]
    response = signed_in.post(
        "/v1/import/commit", json=body(OVERSELL, expect=digest)
    )
    assert response.status_code == 409
    assert all_transactions(account.db) == []


def test_a_commit_leaves_the_rejected_rows_out_and_says_so(
    client, account, signed_in
):
    payload = signed_in.post("/v1/import/commit", json=body(OVERSELL)).json()
    assert payload["imported"] == 1
    assert [row["ticker"] for row in payload["rejected"]] == ["TSLA"]
    assert {t.ticker for t in all_transactions(account.db)} == {"NVDA"}


def test_a_commit_revalidates_instead_of_trusting_the_preview(
    client, account, signed_in
):
    """The ledger moves under both calls: rows that were fresh at preview time
    are duplicates once they have been committed once."""
    first = signed_in.post("/v1/import/commit", json=body()).json()
    assert first["imported"] == 2
    second = signed_in.post("/v1/import/commit", json=body()).json()
    # Committed again — duplicates are a warning, not an error, exactly as in
    # the app — but the second batch is flagged as such by validation.
    assert second["imported"] == 2
    assert len(all_transactions(account.db)) == 4


def test_a_statement_with_nothing_importable_is_refused(client, account, signed_in):
    only_bad = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-03-02,TSLA,sell,99,200.00,EUR,1.00,broker one\n"
    )
    response = signed_in.post("/v1/import/commit", json=body(only_bad))
    assert response.status_code == 422


def test_an_unattributed_batch_has_to_be_told_its_broker(client, account, signed_in):
    """The fees and custody views read the book by the note's first word; a
    batch committed without one is tedious to attribute afterwards."""
    unnamed = (
        "date,ticker,action,quantity,price,currency,fee\n"
        "2024-01-02,AAPL,buy,10,100.00,EUR,1.00\n"
    )
    assert signed_in.post("/v1/import/commit", json=body(unnamed)).status_code == 422
    payload = signed_in.post(
        "/v1/import/commit", json=body(unnamed, broker="clicktrade")
    ).json()
    assert payload["broker"] == "clicktrade"
    assert all_transactions(account.db)[0].note.split()[0] == "clicktrade"


def test_the_demo_book_does_not_survive_a_real_import(client, account, signed_in):
    """An invented cost basis must never end up mixed into a real one."""
    from stocks.portfolio import demo

    demo.seed(account.db)
    assert any(demo.is_demo(t) for t in all_transactions(account.db))
    signed_in.post("/v1/import/commit", json=body())
    assert not any(demo.is_demo(t) for t in all_transactions(account.db))


# ----------------------------------------------------------------------- undo


def test_the_last_import_is_remembered(client, account, signed_in):
    signed_in.post("/v1/import/commit", json=body())
    payload = client.get("/v1/import/last", params=WHO, headers=AUTH).json()
    assert payload["filename"] == "ledger.csv"
    assert payload["platform"] == "generic"
    assert payload["rows"] == 2


def test_the_record_says_how_much_of_the_batch_survived(client, account, signed_in):
    """Committed and still there are two counts, and they part company.

    A row deleted by hand after the commit leaves the record's own count
    unchanged, so an undo offered as "2 rows" would take one. The surviving
    rows ride along with the number: a count nobody can check from outside is
    a count nobody has to believe.
    """
    signed_in.post("/v1/import/commit", json=body())
    kept = all_transactions(account.db)
    ledger.delete_many([kept[0].id], account.db)

    payload = client.get("/v1/import/last", params=WHO, headers=AUTH).json()
    assert payload["rows"] == 2, "what the commit wrote does not change"
    assert payload["still_here"] == 1
    assert [row["ticker"] for row in payload["transactions"]] == [kept[1].ticker]


def test_an_undo_removes_that_batch_and_only_that_batch(client, account, signed_in):
    """By id, not by re-reading the file: anything broader would take somebody
    else's import with it."""
    ledger.add_many(
        [Transaction("2023-01-02", "OLD", "buy", 1, 10.0, "EUR", 0.0, note="manual")],
        path=account.db,
    )
    signed_in.post("/v1/import/commit", json=body())
    assert len(all_transactions(account.db)) == 3
    assert signed_in.delete("/v1/import/last").json()["rows"] == 2
    assert [t.ticker for t in all_transactions(account.db)] == ["OLD"]


def test_undoing_twice_is_a_404_rather_than_a_second_deletion(
    client, account, signed_in
):
    signed_in.post("/v1/import/commit", json=body())
    assert signed_in.delete("/v1/import/last").status_code == 200
    assert signed_in.delete("/v1/import/last").status_code == 404


def test_an_account_that_never_imported_has_nothing_to_show(client, account):
    payload = client.get("/v1/import/last", params=WHO, headers=AUTH).json()
    assert payload["filename"] is None and payload["rows"] == 0


# ----------------------------------------------------------------------- gate


def test_a_token_can_neither_preview_nor_commit(client, account):
    for url in ("/v1/import/preview", "/v1/import/commit"):
        response = client.post(url, params=WHO, headers=AUTH, json=body())
        assert response.status_code == 403, url
    assert all_transactions(account.db) == []


# ---------------------------------------------------------------- starting over


def wipe(client, **body):
    """`client.delete` will not send a body; this route requires one."""
    return client.request("DELETE", "/v1/portfolio/transactions", json=body)


def test_a_wipe_has_to_name_the_book_it_is_emptying(client, account, signed_in):
    """There is no undo and no backup, so a client must not be able to do this
    by accident — a stray boolean on an unrelated request is exactly how that
    happens."""
    signed_in.post("/v1/import/commit", json=body())
    assert wipe(signed_in, confirm="someone@else.com").status_code == 422
    assert wipe(signed_in).status_code == 422
    assert len(all_transactions(account.db)) == 2


def test_a_confirmed_wipe_empties_the_book_and_says_how_much(
    client, account, signed_in
):
    signed_in.post("/v1/import/commit", json=body())
    response = wipe(signed_in, confirm=EMAIL)
    assert response.status_code == 200
    assert response.json()["removed"] == 2
    assert all_transactions(account.db) == []


def test_a_wipe_drops_the_undo_it_can_no_longer_honour(client, account, signed_in):
    """The record points at ids that no longer exist; offering to undo a batch
    inside a book that is gone would be a lie."""
    signed_in.post("/v1/import/commit", json=body())
    wipe(signed_in, confirm=EMAIL)
    assert client.get("/v1/import/last", params=WHO, headers=AUTH).json()["rows"] == 0
    assert signed_in.delete("/v1/import/last").status_code == 404


def test_a_token_cannot_wipe_a_book(client, account):
    """No session fixture here on purpose: `signed_in` sets its cookie on this
    same client, and a request carrying both is a session request — the token
    would never be reached."""
    ledger.add_many(
        [Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0)],
        path=account.db,
    )
    response = client.request(
        "DELETE",
        "/v1/portfolio/transactions",
        params=WHO,
        headers=AUTH,
        json={"confirm": EMAIL},
    )
    assert response.status_code == 403
    assert len(all_transactions(account.db)) == 1


# ------------------------------------------------- replacing a book, not adding to it
# The page's "wipe first" checkbox. Two calls — empty the book, then commit —
# are not the same thing: a commit that fails after the wipe leaves an empty
# ledger and no undo, which is the one outcome nobody can recover from.

REPLACEMENT = """date,ticker,action,quantity,price,currency,fee,note
2024-04-01,NVDA,buy,3,500.00,EUR,1.00,revolut Nvidia
"""


def test_a_wipe_on_a_commit_has_to_name_the_book_it_replaces(
    client, account, signed_in
):
    """The same confirmation `DELETE /v1/portfolio/transactions` demands: one
    rule for destroying a book, not two."""
    signed_in.post("/v1/import/commit", json=body())
    assert signed_in.post(
        "/v1/import/commit", json=body(REPLACEMENT, wipe=True)
    ).status_code == 422
    assert signed_in.post(
        "/v1/import/commit",
        json=body(REPLACEMENT, wipe=True, wipe_confirm="someone@else.com"),
    ).status_code == 422
    assert len(all_transactions(account.db)) == 2


def test_a_confirmed_wipe_replaces_the_book_in_one_call(client, account, signed_in):
    signed_in.post("/v1/import/commit", json=body())
    payload = signed_in.post(
        "/v1/import/commit", json=body(REPLACEMENT, wipe=True, wipe_confirm=EMAIL)
    ).json()
    assert payload["imported"] == 1
    assert [t.ticker for t in all_transactions(account.db)] == ["NVDA"]

    record = client.get("/v1/import/last", params=WHO, headers=AUTH).json()
    assert record["wiped"] is True, "the record has to say the book was replaced"
    assert record["rows"] == 1


def test_a_wipe_that_imports_nothing_destroys_nothing(client, account, signed_in):
    """The whole reason the option lives on this route: everything is parsed,
    validated and found worth writing before a single row is deleted."""
    signed_in.post("/v1/import/commit", json=body())
    unimportable = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-03-02,TSLA,sell,99,200.00,EUR,1.00,revolut Tesla\n"
    )
    response = signed_in.post(
        "/v1/import/commit", json=body(unimportable, wipe=True, wipe_confirm=EMAIL)
    )
    assert response.status_code == 422
    assert len(all_transactions(account.db)) == 2


def test_a_wipe_is_previewed_against_the_ledger_it_will_leave_behind(
    client, account, signed_in
):
    """Otherwise every row of a clean re-import comes back flagged as a
    duplicate of one that is on its way out."""
    signed_in.post("/v1/import/commit", json=body())
    assert signed_in.post("/v1/import/preview", json=body()).json()["duplicates"] == 2
    replacing = signed_in.post("/v1/import/preview", json=body(wipe=True)).json()
    assert replacing["duplicates"] == 0
    assert len(replacing["importable"]) == 2
    assert len(all_transactions(account.db)) == 2, "a preview still writes nothing"
