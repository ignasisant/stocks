"""The Import page's two repairs, its example statement and its import note.

What each repair *is* — which splits a ledger is missing, which departure and
arrival are one move of shares — belongs to `stocks.portfolio.corporate` and
`stocks.portfolio.transfers`, and is tested there and through the page in
test_split_repair.py and test_import_moves.py. What is tested here is the
contract the HTTP binding adds on top:

* a scan writes nothing, and a token may run one; every apply is a session's;
* an apply names *which* proposal it accepts and never what it is — the ratio,
  the rows and the dates come from a scan run inside the request, so a stale
  name is refused rather than written;
* the example statement comes back as the bytes it is, so it can go straight
  back through the ordinary preview and commit;
* dismissing the import note leaves the rows in the ledger, which is the only
  thing separating it from the undo.

Nothing here reaches the network. The split scan's two Yahoo lookups are
replaced with the answers Yahoo really gives for a real split, in the shapes
`corporate` declares for them; the moves fixture pairs on an ISIN its own note
carries, so the symbol lookup is never consulted — except in the one test that
is about that lookup, where it is replaced too.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.data import fetch
from stocks.portfolio import demo, platforms
from stocks.portfolio.ledger import Transaction, add_many, all_transactions

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

ASSETS = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web" / "assets"


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture
def account(monkeypatch, tmp_path):
    """An account directory whose ledger each test fills for itself."""
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AMZN\n  - ticker: ASML\n")
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


# ------------------------------------------------------------------- splits
# AMZN's 20-for-1 (2022-06-06) against a share bought a fortnight before it, and
# GOOGL's (2022-07-18) against two bought the same day. Both are real splits,
# and the closes are the ones that make the arithmetic the module actually does
# come out: a buy price ~20x the split-adjusted close of its own day is the
# evidence, and nothing else in the book says a split happened.

SPLITS = {
    "AMZN": [("1999-09-02", 2.0), ("2022-06-06", 20.0)],
    "GOOGL": [("2022-07-18", 20.0)],
    # A demo holding's split, so that a scan which forgot to leave the demo
    # book out would visibly propose one.
    "AAPL": [("2025-06-02", 4.0)],
}
CLOSES = {
    ("AMZN", "2022-05-24"): 104.10,
    ("GOOGL", "2022-05-24"): 110.00,
    ("AAPL", "2025-01-14"): 58.33,
}

PRE_SPLIT = [
    Transaction("2022-05-24", "AMZN", "buy", 1.0, 2050.0, "USD", 9.36,
                "revolut Amazon"),
    Transaction("2022-05-24", "GOOGL", "buy", 2.0, 2200.0, "USD", 1.0,
                "revolut Alphabet"),
]


@pytest.fixture
def yahoo(monkeypatch):
    """The two lookups `corporate.missing_splits` is handed, in their own shapes.

    `SplitLookup` is `ticker -> [(YYYY-MM-DD, ratio), …]` with Yahoo's ratios
    (20.0 for a 20-for-1) and `CloseLookup` is `(ticker, day) -> split-adjusted
    close or None`. Both are read off `stocks.data.fetch` at call time, which
    is what makes a route that never calls them fail here rather than pass.
    """
    monkeypatch.setattr(fetch, "splits", lambda ticker: list(SPLITS.get(ticker, [])))
    monkeypatch.setattr(
        fetch, "close_on", lambda ticker, day: CLOSES.get((ticker, day))
    )


def scan_splits(client):
    return client.get("/v1/import/splits/scan", params=WHO, headers=AUTH).json()


def test_a_scan_names_the_split_and_the_evidence_it_rests_on(
    client, account, yahoo
):
    """The proposal alone is not worth acting on: what makes it one is the
    pre-split buy price beside the close of its own day."""
    add_many(PRE_SPLIT, account.db)
    payload = scan_splits(client)
    amzn = payload["splits"][0]
    assert (amzn["ticker"], amzn["date"], amzn["ratio"]) == ("AMZN", "2022-06-06", 20.0)
    assert (amzn["held_before"], amzn["held_after"]) == (1.0, 20.0)
    assert (amzn["priced_at"], amzn["priced_on"]) == (2050.0, "2022-05-24")
    assert amzn["market_close"] == 104.10
    assert amzn["currency"] == "USD"
    # Oldest first, which is the order they would be applied in.
    assert [s["ticker"] for s in payload["splits"]] == ["AMZN", "GOOGL"]
    assert payload["throttled"] is False


def test_a_scan_writes_nothing(client, account, yahoo):
    add_many(PRE_SPLIT, account.db)
    scan_splits(client)
    assert [t.action for t in all_transactions(account.db)] == ["buy", "buy"]


def test_an_empty_book_is_scanned_without_asking_yahoo(client, account, monkeypatch):
    """A round-trip per holding is seconds; a book with no holdings is none."""
    asked: list[str] = []
    monkeypatch.setattr(fetch, "splits", lambda t: asked.append(t) or [])
    assert scan_splits(client)["splits"] == []
    assert asked == []


def test_the_demo_book_is_not_a_position_worth_repairing(client, account, yahoo):
    """Invented lots must not produce an invented corporate action — the demo
    rows are about to be deleted by the first real import."""
    demo.seed(account.db)
    add_many(PRE_SPLIT, account.db)
    assert any(t.ticker == "AAPL" for t in all_transactions(account.db))
    assert "AAPL" not in {s["ticker"] for s in scan_splits(client)["splits"]}


def test_a_scan_that_yahoo_would_not_answer_says_so(client, account, monkeypatch):
    """A throttled lookup answers with silence, so an empty list has to be able
    to mean "could not tell" rather than "nothing missing"."""
    add_many(PRE_SPLIT, account.db)
    monkeypatch.setattr(fetch, "splits", lambda ticker: [])
    fetch.trip_throttle()
    payload = scan_splits(client)
    assert payload["splits"] == [] and payload["throttled"] is True


def test_applying_writes_the_named_split_and_leaves_the_other_alone(
    client, account, signed_in, yahoo
):
    """A client that could only say "yes to everything" would be a worse offer
    than the page it replaces."""
    add_many(PRE_SPLIT, account.db)
    payload = signed_in.post(
        "/v1/import/splits/apply",
        json={"splits": [{"ticker": "GOOGL", "date": "2022-07-18"}]},
    ).json()
    assert payload["applied"] == 1
    assert payload["splits"][0]["ratio"] == 20.0

    written = [t for t in all_transactions(account.db) if t.action == "split"]
    assert [(t.ticker, t.date, t.quantity) for t in written] == [
        ("GOOGL", "2022-07-18", 20.0)
    ]
    assert written[0].id in payload["tx_ids"]
    # AMZN was not named, so AMZN is still missing its split.
    assert [s["ticker"] for s in scan_splits(client)["splits"]] == ["AMZN"]


def test_a_split_the_ledger_is_no_longer_missing_is_refused(
    client, account, signed_in, yahoo
):
    """Applying a remembered answer twice would square the share count."""
    body = {"splits": [{"ticker": "AMZN", "date": "2022-06-06"}]}
    add_many(PRE_SPLIT, account.db)
    assert signed_in.post("/v1/import/splits/apply", json=body).status_code == 200
    second = signed_in.post("/v1/import/splits/apply", json=body)
    assert second.status_code == 409
    assert len([t for t in all_transactions(account.db) if t.action == "split"]) == 1


def test_a_split_nobody_proposed_is_never_written(client, account, signed_in, yahoo):
    add_many(PRE_SPLIT, account.db)
    response = signed_in.post(
        "/v1/import/splits/apply",
        json={"splits": [{"ticker": "AMZN", "date": "2019-01-02"}]},
    )
    assert response.status_code == 409
    assert not [t for t in all_transactions(account.db) if t.action == "split"]


def test_the_ratio_is_not_the_clients_to_send(client, account, signed_in, yahoo):
    """The body names which split, never what it is: a client that could send a
    ratio could write a 1000-for-1 into somebody's cost basis."""
    add_many(PRE_SPLIT, account.db)
    response = signed_in.post(
        "/v1/import/splits/apply",
        json={"splits": [{"ticker": "AMZN", "date": "2022-06-06", "ratio": 1000}]},
    )
    assert response.status_code == 422
    assert not [t for t in all_transactions(account.db) if t.action == "split"]


def test_applying_nothing_at_all_is_refused(client, account, signed_in, yahoo):
    add_many(PRE_SPLIT, account.db)
    assert signed_in.post(
        "/v1/import/splits/apply", json={"splits": []}
    ).status_code == 422


def test_a_token_may_scan_for_splits_but_not_apply_one(client, account, yahoo):
    add_many(PRE_SPLIT, account.db)
    assert client.get(
        "/v1/import/splits/scan", params=WHO, headers=AUTH
    ).status_code == 200
    response = client.post(
        "/v1/import/splits/apply",
        params=WHO,
        headers=AUTH,
        json={"splits": [{"ticker": "AMZN", "date": "2022-06-06"}]},
    )
    assert response.status_code == 403
    assert not [t for t in all_transactions(account.db) if t.action == "split"]


# -------------------------------------------------------------------- moves
# One share of ASML: bought at DEGIRO (which books under the ISIN), moved to
# IBKR (which books under the symbol and reports the basis it came with). The
# same book test_import_moves.py drives the page with.

BOUGHT = Transaction("2025-07-18", "NL0010273215", "buy", 1, 633.9, "EUR", 4.9,
                     "degiro ASML HOLDING N.V.")
SOLD = Transaction("2026-08-06", "NL0010273215", "sell", 1, 1465.8, "EUR", 0,
                   "degiro ASML HOLDING N.V.")
ARRIVED = Transaction("2026-09-14", "ASML", "transfer_in", 1, 633.9, "EUR", 0,
                      "ibkr snapshot NL0010273215")


@pytest.fixture
def moved(account):
    """A book that reports a gain nobody made. Ids are 1, 2, 3 in that order."""
    add_many([BOUGHT, SOLD, ARRIVED], account.db)
    return account


def scan_moves(client):
    return client.get("/v1/import/moves/scan", params=WHO, headers=AUTH).json()


def test_the_scan_says_what_makes_it_a_candidate(client, moved):
    """The phantom gain, the two brokers, the two dates, and the basis that
    arrived against the price it was booked at — which is the evidence."""
    move = scan_moves(client)["moves"][0]
    assert (move["ticker_out"], move["ticker_in"]) == ("NL0010273215", "ASML")
    assert (move["broker_out"], move["broker_in"]) == ("degiro", "ibkr")
    assert (move["date_out"], move["date_in"]) == ("2026-08-06", "2026-09-14")
    assert move["quantity"] == 1.0
    assert move["booked_at"] == 1465.8
    assert move["basis_out"] == pytest.approx(638.8)
    assert move["basis_in"] == 633.9
    assert move["phantom_gain"] == pytest.approx(827.0)
    assert move["currency"] == "EUR"
    assert move["rekey"] is True, "accepting has to unify the two labels"
    assert (move["out_ids"], move["in_id"]) == ([2], 3)


def test_a_scan_of_the_ledger_writes_nothing(client, moved):
    before = [(t.id, t.action, t.ticker) for t in all_transactions(moved.db)]
    scan_moves(client)
    assert [(t.id, t.action, t.ticker) for t in all_transactions(moved.db)] == before


def test_a_book_with_nothing_to_repair_proposes_nothing(client, account):
    add_many([BOUGHT], account.db)
    assert scan_moves(client)["moves"] == []


def test_accepting_retires_the_gain_nobody_made(client, moved, signed_in):
    payload = signed_in.post(
        "/v1/import/moves/apply", json={"moves": [{"out_ids": [2], "in_id": 3}]}
    ).json()
    assert payload["applied"] == 1

    rows = all_transactions(moved.db)
    assert {t.action for t in rows} == {"buy", "transfer_out", "transfer_in"}
    # Both brokers' labels are now one, so the replay can see the shares never
    # left the book.
    assert {t.ticker for t in rows} == {"ASML"}


def test_rows_that_are_not_a_move_are_refused(client, moved, signed_in):
    """Named by the ids the scan gave, and checked against a fresh proposal —
    the purchase is not a departure and never was."""
    response = signed_in.post(
        "/v1/import/moves/apply", json={"moves": [{"out_ids": [1], "in_id": 3}]}
    )
    assert response.status_code == 409
    assert {t.action for t in all_transactions(moved.db)} == {
        "buy", "sell", "transfer_in"
    }


def test_the_lookup_that_joins_two_brokers_labels_is_wired_in(
    client, account, monkeypatch
):
    """A departure under the ISIN and an arrival under the symbol, with nothing
    in either note to link them: the pair only exists if the route hands
    `transfers.propose` the app's ISIN -> symbol lookup.

    Both halves patch that lookup — the unresolvable one because an ISIN the
    aliases do not cover is exactly what sends the real one to Yahoo, and a
    test must not depend on a network that may or may not answer.
    """
    add_many(
        [
            BOUGHT,
            SOLD,
            Transaction("2026-09-14", "ASML", "transfer_in", 1, 633.9, "EUR", 0,
                        "ibkr snapshot"),
        ],
        account.db,
    )
    monkeypatch.setattr(loaders, "display_symbol", lambda ticker: ticker)
    assert scan_moves(client)["moves"] == [], "nothing resolved, so no pair"

    monkeypatch.setattr(
        loaders,
        "display_symbol",
        lambda ticker: "ASML" if ticker == "NL0010273215" else ticker,
    )
    move = scan_moves(client)["moves"][0]
    assert (move["ticker_out"], move["ticker_in"]) == ("NL0010273215", "ASML")


def test_a_token_may_scan_for_moves_but_not_accept_one(client, moved):
    assert client.get(
        "/v1/import/moves/scan", params=WHO, headers=AUTH
    ).status_code == 200
    response = client.post(
        "/v1/import/moves/apply",
        params=WHO,
        headers=AUTH,
        json={"moves": [{"out_ids": [2], "in_id": 3}]},
    )
    assert response.status_code == 403
    assert {t.action for t in all_transactions(moved.db)} == {
        "buy", "sell", "transfer_in"
    }


# ------------------------------------------------------- the example statement


def test_the_sample_comes_back_as_the_file_it_is(client, account):
    response = client.get("/v1/import/sample", params={"platform": "revolut"})
    assert response.status_code == 401, "the router's gate applies to it too"

    response = client.get(
        "/v1/import/sample", params={"platform": "revolut"}, headers=AUTH
    )
    assert response.status_code == 200
    assert response.content == (ASSETS / platforms.by_key("revolut").sample).read_bytes()
    assert response.headers["content-type"].startswith("text/csv")
    assert platforms.by_key("revolut").sample in response.headers["content-disposition"]


def test_the_sample_names_no_book_and_so_needs_no_account(client):
    """It is a file shipped with the app, not anybody's data — a token holder
    asking for it has no account to name."""
    assert client.get(
        "/v1/import/sample", params={"platform": "revolut"}, headers=AUTH
    ).status_code == 200


def test_a_platform_that_ships_no_example_is_a_404(client):
    response = client.get(
        "/v1/import/sample", params={"platform": "generic"}, headers=AUTH
    )
    assert response.status_code == 404


def test_a_deployment_without_the_file_is_a_404_rather_than_a_500(
    client, monkeypatch, tmp_path
):
    """A trimmed deploy: the page says nothing rather than failing, and a
    client has to be able to do the same."""
    monkeypatch.setattr(
        "stocks.api.routes.import_statement._ASSETS", tmp_path / "gone"
    )
    response = client.get(
        "/v1/import/sample", params={"platform": "revolut"}, headers=AUTH
    )
    assert response.status_code == 404


def test_the_sample_goes_through_the_ordinary_preview_and_commit(
    client, account, signed_in
):
    """The whole point of shipping a real statement: no separate demo path to
    drift from the real one, and the ordinary undo takes it back out."""
    raw = client.get(
        "/v1/import/sample", params={"platform": "revolut"}, headers=AUTH
    ).content
    body = {
        "platform": "revolut",
        "filename": platforms.by_key("revolut").sample,
        "content": base64.b64encode(raw).decode(),
    }

    preview = signed_in.post("/v1/import/preview", json=body).json()
    assert preview["rejected"] == [], "a sample that errors is worse than none"
    assert preview["broker"] == "revolut"
    assert all_transactions(account.db) == []

    committed = signed_in.post(
        "/v1/import/commit", json=body | {"expect": preview["digest"]}
    ).json()
    assert committed["imported"] == len(preview["importable"])
    assert len(all_transactions(account.db)) == committed["imported"]

    assert signed_in.delete("/v1/import/last").json()["rows"] == committed["imported"]
    assert all_transactions(account.db) == []


# ---------------------------------------------------------- the import record

CLEAN = """date,ticker,action,quantity,price,currency,fee,note
2024-01-02,AMZN,buy,10,100.00,EUR,1.00,revolut Amazon
2024-02-01,ASML,buy,5,200.00,EUR,1.00,revolut ASML
"""


def commit(client) -> dict:
    return client.post(
        "/v1/import/commit",
        json={
            "platform": "generic",
            "filename": "ledger.csv",
            "content": base64.b64encode(CLEAN.encode()).decode(),
        },
    ).json()


def test_dismissing_the_record_keeps_every_row(client, account, signed_in):
    """The difference from the undo is the ledger: this forgets the note and
    nothing else."""
    commit(signed_in)
    payload = signed_in.delete("/v1/import/record")
    assert payload.status_code == 200
    assert payload.json()["rows"] == 2, "what it left behind, not what it removed"
    assert payload.json()["filename"] == "ledger.csv"
    assert len(all_transactions(account.db)) == 2
    assert client.get("/v1/import/last", params=WHO, headers=AUTH).json()["rows"] == 0


def test_the_undo_and_the_dismissal_are_not_the_same_button(
    client, account, signed_in
):
    commit(signed_in)
    signed_in.delete("/v1/import/record")
    assert len(all_transactions(account.db)) == 2

    commit(signed_in)
    signed_in.delete("/v1/import/last")
    assert len(all_transactions(account.db)) == 2, "the second batch, and only it"


def test_dismissing_what_is_not_there_is_a_404(client, account, signed_in):
    assert signed_in.delete("/v1/import/record").status_code == 404
    commit(signed_in)
    assert signed_in.delete("/v1/import/record").status_code == 200
    assert signed_in.delete("/v1/import/record").status_code == 404


def test_a_token_cannot_dismiss_a_record(client, account, signed_in):
    commit(signed_in)
    bare = TestClient(fastapi_app)  # no session cookie: the token is reached
    assert bare.request(
        "DELETE", "/v1/import/record", params=WHO, headers=AUTH
    ).status_code == 403
    assert client.get(
        "/v1/import/last", params=WHO, headers=AUTH
    ).json()["rows"] == 2
