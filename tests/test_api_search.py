"""The search endpoint: whose list it searches, and what it refuses to do.

The ranking itself is `stocks.search` and is tested in test_search_tiers.py.
What is tested here is what the route adds: the account binding, the caches
(every network tier is stubbed — nothing here goes out), and the one write in
this API.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.portfolio import ledger
from stocks.portfolio.ledger import Transaction

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

# Captured before any test patches the module attributes: the autouse fixture
# below swaps the network tiers for stubs, so the real cached functions are
# only reachable through these.
_REAL_WORLD = loaders.world_matches
_CACHED = (
    loaders.held,
    loaders.sec_title,
    loaders.sec_matches,
    loaders.world_matches,
    loaders.coin_matches,
    loaders.fund_matches,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture
def signed_in(client, sign_in):
    """A browser session for EMAIL — what a write needs, since a token cannot."""
    return sign_in(client, EMAIL)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No tier reaches the network, and no entry survives into the next test."""
    for fn in _CACHED:
        fn.cache_clear()
    monkeypatch.setattr(loaders, "sec_matches", lambda q: [])
    monkeypatch.setattr(loaders, "world_matches", lambda q: [])
    monkeypatch.setattr(loaders, "sec_title", lambda t: None)
    yield
    for fn in _CACHED:
        fn.cache_clear()


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text(
        "watchlist:\n"
        "  - ticker: AAPL\n"
        "    name: Apple Inc.\n"
        "    favorite: true\n"
        "    tags: [Tech]\n"
        "  - ticker: MSFT\n"
        "    name: Microsoft Corp\n"
        "    tags: [Tech]\n"
    )
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    ledger.add_many(
        [Transaction("2024-01-02", "ORCL", "buy", 10, 100.0, "EUR", 1.0)], path=paths.db
    )
    monkeypatch.setattr(accounts, "USERS_DIR", users)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    return paths


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


def find(client, q, **params):
    response = client.get("/v1/search", params={"q": q, **WHO, **params}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()["matches"]


# ------------------------------------------------------------------ the gate


def test_search_answers_a_guest_from_the_demo_book_and_not_from_an_account(
    client, account
):
    """It reads *a* watchlist and *a* ledger, and which one is the whole claim.

    Guest mode inverted the status code but not the invariant: with no
    credential the subject is the shared demo directory, and asking it to be
    somebody else's is refused. The box has to work on the demo pages — it is
    how a visitor reaches a ticker at all — so leaving it behind the gate would
    have cost the funnel its only navigation."""
    assert client.get("/v1/search", params={"q": "AAPL"}).status_code == 200
    refused = client.get("/v1/search", params={"q": "AAPL", "account": EMAIL})
    assert refused.status_code == 403


def test_a_token_has_to_name_the_account_it_is_searching(client, account, token):
    """The token names nobody, so "search" without an address has no subject."""
    response = client.get("/v1/search", params={"q": "AAPL"}, headers=AUTH)
    assert response.status_code == 422


# --------------------------------------------------------------- the account


def test_it_searches_the_callers_own_list(client, account, token):
    """Tag groups included — "tech" is how its owner refers to those two.

    Filtered to the own-list tier on purpose: the fund catalog is a local file
    and answers "tech" with a pile of sector ETFs, which is correct and is the
    next tier down.
    """
    own = [m["ticker"] for m in find(client, "tech") if m["kind"] == "watch"]
    assert own == ["AAPL", "MSFT"]


def test_a_starred_row_says_so_and_a_held_one_says_held(client, account, token):
    starred = next(m for m in find(client, "AAPL") if m["ticker"] == "AAPL")
    held = next(m for m in find(client, "ORCL") if m["ticker"] == "ORCL")
    plain = next(m for m in find(client, "MSFT") if m["ticker"] == "MSFT")
    assert (starred["mark"], held["mark"], plain["mark"]) == ("favorite", "held", "")


def test_an_open_position_is_searchable_even_off_the_watchlist(client, account, token):
    """Imported activity has to be reachable, or a book is browsable only
    through the pages that already list it."""
    assert "ORCL" in [m["ticker"] for m in find(client, "ORCL")]


def test_an_empty_query_answers_nothing_rather_than_the_whole_list(
    client, account, token
):
    assert find(client, "  ") == []


def test_the_query_comes_back_normalised(client, account, token):
    body = client.get("/v1/search", params={"q": " aapl ", **WHO}, headers=AUTH).json()
    assert body["query"] == "AAPL"


# ----------------------------------------------------------------- the tiers


def test_every_tier_is_reported_by_name(client, account, token, monkeypatch):
    """A client draws the tiers apart — a Yahoo guess and an own holding must
    not arrive looking the same."""
    monkeypatch.setattr(loaders, "sec_matches", lambda q: [("AMZN", "Amazon.com Inc")])
    monkeypatch.setattr(
        loaders, "world_matches", lambda q: [("AIR.PA", "Airbus SE", "Paris")]
    )
    kinds = {m["ticker"]: m["kind"] for m in find(client, "A")}
    assert kinds["AAPL"] == "watch"
    assert kinds["AMZN"] == "sec"
    assert kinds["AIR.PA"] == "world"


def test_a_worldwide_row_carries_its_venue(client, account, token, monkeypatch):
    monkeypatch.setattr(
        loaders, "world_matches", lambda q: [("MIPS.ST", "Mips AB", "Stockholm")]
    )
    row = next(m for m in find(client, "MIPS") if m["kind"] == "world")
    assert row["exchange"] == "Stockholm"


def test_an_unknown_symbol_comes_back_as_an_analyze_offer(client, account, token):
    rows = find(client, "ZZQQ")
    assert [(m["ticker"], m["kind"]) for m in rows] == [("ZZQQ", "analyze")]


def test_a_dead_tier_degrades_the_search_instead_of_failing_it(
    client, account, token, monkeypatch
):
    """Yahoo throttles this deployment's egress IP routinely. A keystroke must
    still answer with the tiers that did work."""

    def boom(_q):
        raise RuntimeError("Yahoo said no")

    _REAL_WORLD.cache_clear()
    monkeypatch.setattr("stocks.data.symbols.search_symbols", boom)
    monkeypatch.setattr(loaders, "world_matches", _REAL_WORLD)
    assert [m["ticker"] for m in find(client, "AAPL") if m["kind"] == "watch"] == [
        "AAPL"
    ]


def test_limit_is_honoured(client, account, token, monkeypatch):
    monkeypatch.setattr(
        loaders, "sec_matches", lambda q: [(f"T{i}", f"Thing {i}") for i in range(6)]
    )
    assert len(find(client, "T", limit=3)) == 3


# --------------------------------------------------------------- the recents


def test_recents_start_empty_and_grow_by_one_post(client, account, token, signed_in):
    assert client.get("/v1/search/recent", params=WHO, headers=AUTH).json() == {
        "tickers": []
    }
    response = client.post(
        "/v1/search/recent", params=WHO, headers=AUTH, json={"ticker": "aapl"}
    )
    assert response.status_code == 200
    assert response.json()["tickers"] == ["AAPL"]
    assert client.get("/v1/search/recent", params=WHO, headers=AUTH).json() == {
        "tickers": ["AAPL"]
    }


def test_a_repeat_moves_to_the_front_rather_than_duplicating(
    client, account, token, signed_in
):
    for ticker in ("AAPL", "MSFT", "AAPL"):
        client.post(
            "/v1/search/recent", params=WHO, headers=AUTH, json={"ticker": ticker}
        )
    assert client.get("/v1/search/recent", params=WHO, headers=AUTH).json()[
        "tickers"
    ] == ["AAPL", "MSFT"]


def test_the_list_is_capped(client, account, token, signed_in):
    for i in range(accounts.RECENT_SEARCHES_MAX + 3):
        client.post(
            "/v1/search/recent", params=WHO, headers=AUTH, json={"ticker": f"T{i}"}
        )
    tickers = client.get("/v1/search/recent", params=WHO, headers=AUTH).json()["tickers"]
    assert len(tickers) == accounts.RECENT_SEARCHES_MAX


def test_recording_a_search_leaves_every_other_preference_alone(
    client, account, token, signed_in
):
    """It is a read-modify-write over the whole file: rewriting only this key
    would drop whatever a concurrent app run had just saved."""
    client.post("/v1/search/recent", params=WHO, headers=AUTH, json={"ticker": "AAPL"})
    assert json.loads(account.prefs.read_text())["currency"] == "EUR"


def test_recents_are_per_account(client, account, token, signed_in):
    """They come out of that account's prefs.json, not a process-wide list."""
    client.post("/v1/search/recent", params=WHO, headers=AUTH, json={"ticker": "AAPL"})
    assert accounts.load_recent_searches(account.prefs) == ["AAPL"]


def test_a_token_cannot_plant_entries_in_somebody_else_history(
    client, account, token
):
    """The rule the whole write gate exists for: a bearer token names nobody and
    any holder can name any account, so one leaked secret must not be able to
    edit a stranger's data — not even a search history."""
    response = client.post(
        "/v1/search/recent", params=WHO, headers=AUTH, json={"ticker": "AAPL"}
    )
    assert response.status_code == 403
    assert accounts.load_recent_searches(account.prefs) == []
