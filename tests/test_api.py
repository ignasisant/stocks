"""The read-only HTTP API: who gets in, whose book they get, and what it says.

The arithmetic these endpoints return is already covered by test_portfolio.py
and test_book_invariants.py, and duplicating it here would only test pandas
twice. What is tested here is everything the API layer adds on top: the token
gate, resolving an address to a directory, refusing one that has no book,
paging, and the serialization rules the schemas promise — a number that could
not be computed comes out `null`, and a partial price pass says so.

Nothing here touches the network. The loaders are cached, so every test that
feeds them data clears those caches first — otherwise one test's book answers
the next one's request.
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd
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


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def _cold_caches():
    """Every loader starts empty, and leaves empty.

    They are process-wide TTL memos keyed on (db path, mtime, base) — which is
    the right key in production and the wrong one across tests, where two books
    can land on the same tmp path within the same mtime resolution.
    """
    for fn in (
        loaders.ledger_state,
        loaders.held_closes,
        loaders.positions_table,
        loaders.history,
        loaders.quotes,
    ):
        fn.cache_clear()
    yield
    for fn in (
        loaders.ledger_state,
        loaders.held_closes,
        loaders.positions_table,
        loaders.history,
        loaders.quotes,
    ):
        fn.cache_clear()


@pytest.fixture
def account(monkeypatch, tmp_path):
    """A real account directory with a ledger and a watchlist in it."""
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text(
        "watchlist:\n"
        "  - ticker: AAPL\n"
        "    name: Apple\n"
        "    favorite: true\n"
        "    tags: [Tech]\n"
        "  - ticker: MSFT\n"
    )
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    ledger.add_many(
        [
            Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0),
            Transaction("2024-02-01", "MSFT", "buy", 5, 200.0, "EUR", 1.0),
            Transaction("2024-03-01", "AAPL", "sell", 4, 130.0, "EUR", 1.0),
        ],
        path=paths.db,
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


# --------------------------------------------------------------------- the gate

#: The route the gate tests knock on. Deliberately one a guest may *not* read:
#: `/v1/watchlist` used to serve here and is now guest-open, so knocking on it
#: with no credential answers 200 with the demo book and proves nothing about
#: the gate. Every claim below is about a caller who has presented nothing and
#: is asking for somebody's own data — so the route has to be somebody's own.
GATED = "/v1/search/recent"


def test_health_needs_no_token(client):
    """A liveness probe holds no credentials, so this one route is open."""
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_says_nothing_about_the_deployment(client, token):
    """Open routes leak nothing: a version and a boot time, and that is all."""
    assert set(client.get("/v1/health").json()) == {"status", "version", "booted"}


def test_an_unconfigured_api_refuses_rather_than_running_open(client, monkeypatch):
    """The failure mode of a missing secret must not be "no authentication"."""
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("stocks.api.security.configured_token", lambda: "")
    response = client.get(GATED, params={"account": EMAIL})
    assert response.status_code == 401


def test_a_deployment_with_no_token_still_offers_a_sign_in(client, monkeypatch):
    """No API token is an ordinary state — the token is only for headless jobs.

    It has to read as "sign in", not as a server error: 503 here is what put a
    raw failure message on an anonymous visitor's screen where the page means
    to show them a login button.
    """
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("stocks.api.security.configured_token", lambda: "")
    response = client.get(GATED, params={"account": EMAIL})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_missing_token_is_refused(client, token):
    response = client.get(GATED, params={"account": EMAIL})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_wrong_token_is_refused(client, token):
    response = client.get(
        GATED, params={"account": EMAIL}, headers={"Authorization": "Bearer x"}
    )
    assert response.status_code == 401


def test_a_guest_naming_an_account_is_refused_too(client, token):
    """The same refusal on the other side of the line: a route a guest *may*
    read still may not be asked about somebody. 403 rather than 401 because the
    caller is not missing a credential — it is asking a question no credential
    it could present would let it ask."""
    response = client.get("/v1/watchlist", params={"account": EMAIL})
    assert response.status_code == 403


def test_the_scheme_is_matched_case_insensitively(client, token, account):
    """Clients disagree about "Bearer"; the token itself is exact."""
    response = client.get(
        "/v1/watchlist", params={"account": EMAIL},
        headers={"Authorization": f"bearer {TOKEN}"},
    )
    assert response.status_code == 200


# ----------------------------------------------------------------- the account


def test_an_account_with_no_book_is_404_and_leaves_no_trace(
    client, token, monkeypatch, tmp_path
):
    """Reading an account must never call one into existence.

    The restore has to mkdir before it can pull from the bucket, so the naive
    version leaves a directory behind for every address anyone asks about — and
    the next real sign-in finds a book it did not make. Nothing came back, so
    nothing stays.
    """
    users = tmp_path / "users"
    real = accounts.paths_for
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: real(
            email, None, users_dir=users
        )
    )
    response = client.get(
        "/v1/watchlist", params={"account": "nobody@example.com"}, headers=AUTH
    )
    assert response.status_code == 404
    assert not users.exists() or not list(users.iterdir())


def test_an_account_that_is_not_an_address_is_refused(client, token):
    response = client.get("/v1/watchlist", params={"account": "../etc"}, headers=AUTH)
    assert response.status_code == 422


def test_the_account_parameter_is_required(client, token):
    assert client.get("/v1/watchlist", headers=AUTH).status_code == 422


# -------------------------------------------------------------------- the book


def test_the_watchlist_comes_back_as_stored(client, token, account):
    entries = client.get(
        "/v1/watchlist", params={"account": EMAIL}, headers=AUTH
    ).json()["entries"]
    assert [e["ticker"] for e in entries] == ["AAPL", "MSFT"]
    assert entries[0] == {
        "ticker": "AAPL",
        "name": "Apple",
        "favorite": True,
        "tags": ["Tech"],
        # No position typed in: null, not 0 — an empty cell, not "sold".
        "shares": None,
        "cost": None,
        "is_crypto": False,
    }


def test_a_coin_pair_says_it_is_one(client, token, account):
    """The comps table ranks on KPIs a coin has none of, so a client has to be
    able to leave them out without re-deriving it from the symbol's shape."""
    account.watchlist.write_text("watchlist:\n  - ticker: BTC-EUR\n")
    entries = client.get(
        "/v1/watchlist", params={"account": EMAIL}, headers=AUTH
    ).json()["entries"]
    assert entries[0]["is_crypto"] is True


def test_transactions_are_newest_first_and_paged(client, token, account):
    body = client.get(
        "/v1/portfolio/transactions",
        params={"account": EMAIL, "limit": 2},
        headers=AUTH,
    ).json()
    assert body["total"] == 3, "total counts the ledger, not the page"
    assert [t["date"] for t in body["transactions"]] == ["2024-03-01", "2024-02-01"]

    second = client.get(
        "/v1/portfolio/transactions",
        params={"account": EMAIL, "limit": 2, "offset": 2},
        headers=AUTH,
    ).json()
    assert [t["date"] for t in second["transactions"]] == ["2024-01-02"]


def test_an_unpriced_position_reads_null_and_is_counted(
    client, token, account, monkeypatch
):
    """A price pass that missed a name must not print it as worth zero."""
    table = pd.DataFrame(
        {
            "shares": [6.0, 5.0],
            "ccy": ["EUR", "EUR"],
            "cost": [600.0, 1000.0],
            "value": [900.0, float("nan")],
            "pnl": [300.0, float("nan")],
            "pnl_pct": [0.5, float("nan")],
        },
        index=pd.Index(["AAPL", "MSFT"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    # Today's move is a basket read and a quote burst; offline here.
    monkeypatch.setattr(loaders, "basket_values", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(loaders, "quotes", lambda tickers: {})

    body = client.get(
        "/v1/portfolio/positions", params={"account": EMAIL}, headers=AUTH
    ).json()
    rows = {r["ticker"]: r for r in body["positions"]}
    assert body["unpriced"] == 1
    assert rows["MSFT"]["value"] is None
    assert rows["MSFT"]["weight"] is None
    # The unpriced row still stands in the denominator at its cost, so the
    # priced one is not handed its share: 900 / (900 + 1000).
    assert rows["AAPL"]["weight"] == pytest.approx(900 / 1900)


def test_a_share_price_is_reported_in_the_currency_it_trades_in(
    client, token, account, monkeypatch
):
    """Value is in the reporting currency; a share price is not.

    A US name quoted at $200 must not read "€100" because the book is kept in
    euros — no screen anywhere shows that number. Backed out of the value the
    price pass already fetched, so printing it costs no second quote.
    """
    table = pd.DataFrame(
        {
            "shares": [10.0],
            "ccy": ["USD"],
            "cost": [800.0],
            "value": [1000.0],  # EUR
            "pnl": [200.0],
            "pnl_pct": [0.25],
        },
        index=pd.Index(["AAPL"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    monkeypatch.setattr(loaders, "spot_rates", lambda ccys, base="EUR": {"USD": 0.5})
    monkeypatch.setattr(loaders, "basket_values", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(loaders, "quotes", lambda tickers: {})

    body = client.get(
        "/v1/portfolio/positions", params={"account": EMAIL}, headers=AUTH
    ).json()
    row = body["positions"][0]
    assert row["currency"] == "USD"
    assert row["price"] == pytest.approx(200.0)  # 1000 EUR / 10 shares / 0.5
    assert row["value"] == pytest.approx(1000.0)


def test_a_price_with_no_rate_to_convert_it_reads_null(
    client, token, account, monkeypatch
):
    """A pair that could not be fetched leaves the price out rather than
    printing the reporting-currency figure under a foreign symbol."""
    table = pd.DataFrame(
        {
            "shares": [10.0],
            "ccy": ["USD"],
            "cost": [800.0],
            "value": [1000.0],
            "pnl": [200.0],
            "pnl_pct": [0.25],
        },
        index=pd.Index(["AAPL"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    monkeypatch.setattr(loaders, "spot_rates", lambda ccys, base="EUR": {})
    monkeypatch.setattr(loaders, "basket_values", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(loaders, "quotes", lambda tickers: {})

    body = client.get(
        "/v1/portfolio/positions", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["positions"][0]["price"] is None


def test_the_summary_sums_the_same_rows_on_both_sides(
    client, token, account, monkeypatch
):
    """Cost over priced rows only — the whole basis against a partial value is
    how an intact book renders at -60%."""
    table = pd.DataFrame(
        {
            "shares": [6.0, 5.0],
            "ccy": ["EUR", "EUR"],
            "cost": [600.0, 1000.0],
            "value": [900.0, float("nan")],
            "pnl": [300.0, float("nan")],
            "pnl_pct": [0.5, float("nan")],
        },
        index=pd.Index(["AAPL", "MSFT"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)

    body = client.get(
        "/v1/portfolio/summary", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert (body["cost"], body["value"]) == (600.0, 900.0)
    assert body["pnl_pct"] == pytest.approx(0.5)
    assert (body["positions"], body["unpriced"]) == (2, 1)


def test_an_empty_book_summarises_to_zero_without_dividing(
    client, token, account, monkeypatch
):
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: pd.DataFrame())
    body = client.get(
        "/v1/portfolio/summary", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["pnl_pct"] is None, "no basis means no percentage, not a crash"
    assert body["positions"] == 0


def test_performance_reports_both_returns_and_what_it_could_not_price(
    client, token, account, monkeypatch
):
    index = pd.date_range("2024-01-02", periods=3, freq="D")
    hist = pd.DataFrame(
        {"injected": [100.0, 100.0, 100.0], "value": [100.0, 110.0, 121.0],
         "pnl_pct": [0.0, 0.1, 0.21]},
        index=index,
    )
    twr = pd.Series([0.1, 0.1], index=index[1:])
    monkeypatch.setattr(loaders, "history", lambda *a, **k: (hist, twr, ["ORGN"]))

    body = client.get(
        "/v1/portfolio/performance", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["twr_cumulative"] == pytest.approx(0.21)
    assert body["start"] == "2024-01-02" and body["end"] == "2024-01-04"
    assert body["missing"] == ["ORGN"], "names carried at cost are disclosed"
    assert body["base"] == "EUR"
    # Risk over the flow-adjusted path, which is the only series either reading
    # can be taken over: the book's own value jumps every time money goes in,
    # and a deposit is not a return. A steady +10% has neither dispersion nor a
    # drawdown, so both are 0 here — and null, never 0, when there is nothing
    # to measure.
    assert body["twr_volatility"] == pytest.approx(0.0)
    assert body["twr_max_drawdown"] == pytest.approx(0.0)
    assert body["dropped_days"] == []


def test_performance_names_the_days_it_threw_out(
    client, token, account, monkeypatch
):
    """A flow the value path cannot price is excluded, not absorbed.

    Left in, an unrecorded split reads as a one-day collapse and drags the
    compounded return with it. The day comes out — and the reader is told
    which one, because a figure quietly taken over less than it claims is the
    worse failure.
    """
    index = pd.date_range("2024-01-02", periods=3, freq="D")
    hist = pd.DataFrame(
        {"injected": [100.0, 100.0, 100.0], "value": [100.0, 110.0, 121.0],
         "pnl_pct": [0.0, 0.1, 0.21]},
        index=index,
    )
    twr = pd.Series([0.1, 0.1], index=index[1:])
    twr.attrs["dropped_days"] = [pd.Timestamp("2024-01-03")]
    monkeypatch.setattr(loaders, "history", lambda *a, **k: (hist, twr, []))

    body = client.get(
        "/v1/portfolio/performance", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["dropped_days"] == ["2024-01-03"]


def test_a_book_with_no_history_still_answers(client, token, account, monkeypatch):
    monkeypatch.setattr(
        loaders, "history",
        lambda *a, **k: (pd.DataFrame(), pd.Series(dtype=float), []),
    )
    body = client.get(
        "/v1/portfolio/performance", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["twr_cumulative"] is None and body["irr"] is None


# --------------------------------------------------------------- the currency


def test_the_base_defaults_to_the_accounts_preference(client, token, account):
    account.prefs.write_text(json.dumps({"currency": "USD"}))
    body = client.get(
        "/v1/portfolio/summary", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["base"] == "USD"


def test_an_explicit_base_wins(client, token, account):
    body = client.get(
        "/v1/portfolio/summary", params={"account": EMAIL, "base": "gbp"}, headers=AUTH
    ).json()
    assert body["base"] == "GBP"


def test_a_currency_the_app_cannot_reckon_in_is_refused(client, token, account):
    response = client.get(
        "/v1/portfolio/summary", params={"account": EMAIL, "base": "XYZ"}, headers=AUTH
    )
    assert response.status_code == 422


def test_unreadable_prefs_fall_back_to_eur(client, token, account):
    account.prefs.write_text("{ not json")
    body = client.get(
        "/v1/portfolio/summary", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert body["base"] == "EUR"


# ------------------------------------------------------------------- quotes


def test_quotes_separate_what_priced_from_what_did_not(client, token, monkeypatch):
    monkeypatch.setattr(
        loaders, "quotes",
        lambda tickers: {"AAPL": {"price": 190.0, "pct": 0.012, "session": None,
                                  "as_of": "2024-03-01"}},
    )
    body = client.get(
        "/v1/market/quotes", params={"tickers": "aapl,nosuch"}, headers=AUTH
    ).json()
    assert [q["ticker"] for q in body["quotes"]] == ["AAPL"]
    assert body["unavailable"] == ["NOSUCH"], "no quote is absent, never a zero"


def test_an_empty_ticker_list_is_refused(client, token):
    response = client.get("/v1/market/quotes", params={"tickers": " , "}, headers=AUTH)
    assert response.status_code == 422


def test_the_batch_is_bounded(client, token):
    many = ",".join(f"T{i}" for i in range(80))
    response = client.get("/v1/market/quotes", params={"tickers": many}, headers=AUTH)
    assert response.status_code == 422


# -------------------------------------------------------------- the API is read-only


# The one route allowed to write, and why: a recent-search list that never
# grows is worse than none, because the reader would see five names frozen at
# whatever the Streamlit page last stored. Written as an allowlist so adding a
# second write endpoint fails here and has to be argued for.
# Every route that changes something. The list is written out rather than
# derived so that adding a write is a deliberate edit to this file: the
# question "should this be writable over HTTP, by whom, and what happens if a
# client half-completes it" is not one to answer by accident.
WRITES = {
    ("/v1/search/recent", "post"),
    ("/v1/prefs", "patch"),
    # The investor profile, replaced whole. A write because it is what the
    # assistant's persona is built from — this is text that reaches the model's
    # system prompt, which is precisely why a token may not set it.
    ("/v1/profile", "put"),
    ("/v1/watchlist", "post"),
    ("/v1/watchlist/{ticker}", "patch"),
    ("/v1/watchlist/{ticker}", "delete"),
    ("/v1/watchlist/tags/{tag}", "patch"),
    ("/v1/watchlist/tags/{tag}", "delete"),
    ("/v1/import/commit", "post"),
    # A statement attached to a conversation. The preview writes no ledger rows
    # — but it files the assistant's note on the thread and, for an export no
    # parser owns, spends a model call, so it is a write like the commit that
    # follows it.
    ("/v1/chat/attachments", "post"),
    ("/v1/chat/attachments/commit", "post"),
    # A voice note. It writes nothing — not the audio, not a turn — but it
    # spends the operator's transcription key, which is exactly what a bearer
    # token must never do on somebody else's account.
    ("/v1/chat/voice", "post"),
    # The sector screen's written read. It spends a unit of the account's
    # allowance and stores the answer beside its prefs, so a token may not.
    ("/v1/sectors/{sector}/verdict", "post"),
    # The daily card, written. It spends a unit of the allowance and stores
    # the card beside the prefs — the sector read's twin, and refused to a
    # token for the same reason.
    ("/v1/daily", "post"),
    # Home's "Refresh prices". It writes nothing, but it drops process-wide
    # price caches — every account's downloads — so it is a pressed button,
    # and only a signed-in reader presses buttons.
    ("/v1/home/refresh", "post"),
    # The live rescan. It writes no file, but it spends a minute of Yahoo's
    # patience from this deployment's IP and one of the account's hourly
    # budget — a token naming somebody must not spend either in their name.
    ("/v1/sectors/{sector}/rescan", "post"),
    # The walkthrough. Each moves stored state — the marker, the spent
    # automatic opens, the cards on the guide's thread — so none is a token's.
    ("/v1/guide/start", "post"),
    ("/v1/guide/sync", "post"),
    ("/v1/guide/advance", "post"),
    ("/v1/guide/finish", "post"),
    ("/v1/import/last", "delete"),
    # Forgetting the last-import note. A write because it is stored state, and
    # because losing it loses the undo for a batch that is still in the ledger
    # — the rows survive, the offer to take them back out does not.
    ("/v1/import/record", "delete"),
    # The two repairs the Import page carries. Both write ledger rows — one
    # adds the split rows a statement never printed, the other restates a sale
    # as the transfer it was — and both are proposed from evidence first, so
    # the body names which of the proposals it accepts and never what they are.
    ("/v1/import/splits/apply", "post"),
    ("/v1/import/moves/apply", "post"),
    # The demo book: fabricated rows, in an app that also files tax reports.
    # Writable because an empty account can otherwise see none of the ledger
    # half of it, and safe only while every row stays marked `demo` and the
    # first real import clears them — which is why a token may not do this:
    # invented lots must only ever be invited in by the account itself.
    ("/v1/portfolio/demo", "post"),
    ("/v1/portfolio/demo", "delete"),
    # Changes nothing — it parses and validates and throws the answer away.
    # It is here because "every non-GET needs a session" is a rule that can be
    # checked, and "every non-GET except the ones that happen not to write" is
    # not.
    ("/v1/import/preview", "post"),
    ("/v1/watchlist/{ticker}/alerts", "put"),
    ("/v1/portfolio/transactions", "delete"),
    # The assistant. A turn is a write twice over: it appends the completed
    # pair to chat.json, and it spends the account's free allowance on the
    # operator's shared keys — which is the one a leaked token would be worth
    # stealing for.
    ("/v1/chat/messages", "post"),
    ("/v1/chat/conversations", "post"),
    ("/v1/chat/conversations/{cid}", "patch"),
    ("/v1/chat/conversations/{cid}", "delete"),
    ("/v1/chat/settings", "patch"),
    # Marking the what's-new modal as read. A write because that is exactly
    # what it is: the stamp is what stops the card interrupting this account
    # again, and a token that could set it would retire an announcement the
    # account never saw.
    ("/v1/onboarding/seen", "post"),
    # Linking a Telegram chat, and the two things done with a linked one. A
    # token could otherwise aim the bot at a chat id it named itself.
    ("/v1/notify/telegram", "post"),
    ("/v1/notify/telegram", "delete"),
    ("/v1/notify/telegram/test", "post"),
    # Feedback. A write because it stores a file against this account; there is
    # no anonymous variant, which is a real difference from the Streamlit page
    # and is stated where the button is drawn.
    ("/v1/feedback", "post"),
    # Erasing the account. The most destructive route here, and the clearest
    # case for the session-only rule: a token names any account it likes.
    ("/v1/account", "delete"),
    # A provider key of your own, which is what lifts the free chain's daily
    # cap. Stored encrypted; a token must not be able to plant or remove one.
    ("/v1/chat/keys/{provider}", "put"),
    ("/v1/chat/keys/{provider}", "delete"),
    # Reading the stored key back in full. A POST that writes nothing, and on
    # this list for the rule the list enforces: a token names nobody, and a
    # provider key is the one secret this API would otherwise hand to it.
    ("/v1/chat/keys/{provider}/reveal", "post"),
    # The bank consent, in three writes and a delete. None of them touches the
    # ledger — this is PSD2 account *information*, read-only at the bank — but
    # all four change stored state: the `state` that a redirect will be matched
    # against, the session that comes back from it, the balances cached against
    # the bank's own daily budget, and the consent closed at the far end. A
    # token is refused on every one of them, and on the reads too, because the
    # feature's gate is an allowlist of people and a token names nobody.
    ("/v1/bank/auth", "post"),
    ("/v1/bank/session", "post"),
    ("/v1/bank/connections/{session_id}/refresh", "post"),
    ("/v1/bank/connections/{session_id}", "delete"),
}


def test_the_writes_are_the_ones_we_meant_to_ship(client):
    """Everything else still goes through the app, so nothing here can leave a
    ledger in a state the UI did not produce."""
    writing = {
        (path, method)
        for path, item in fastapi_app.openapi()["paths"].items()
        for method in item
        if method != "get"
    }
    assert writing == WRITES


def test_no_write_will_answer_a_bearer_token(client, token, account):
    """A token names nobody and any holder can name any account. Reading under
    that rule is a decision already taken; writing under it is not the same bet,
    so every write refuses a token — and 403, not 401: the caller authenticated
    fine, it simply may not do this.
    """
    # A body that every write would accept if it got that far, so a 403 can
    # only be the gate and never a validation error on the way to it.
    body = {
        "ticker": "AAPL",
        "currency": "USD",
        "name": "Tech",
        "platform": "revolut",
        "filename": "statement.csv",
        "content": "",
        "alerts": [],
        "confirm": EMAIL,
    }
    for path, method in sorted(WRITES):
        url = path.replace("{ticker}", "AAPL").replace("{tag}", "Tech")
        # `request` rather than the per-verb helpers: DELETE carries a body on
        # the one route that demands a typed confirmation, and httpx's
        # `client.delete` will not send one.
        response = client.request(
            method.upper(),
            url,
            params={"account": EMAIL},
            headers=AUTH,
            json=body,
        )
        assert response.status_code == 403, f"{method} {path}"


def test_a_write_to_a_read_route_is_refused(client, token, account):
    assert client.post(
        "/v1/portfolio/transactions", params={"account": EMAIL}, headers=AUTH
    ).status_code == 405


def test_the_ledger_file_is_untouched_by_a_read(client, token, account):
    before = account.db.read_bytes()
    client.get("/v1/portfolio/transactions", params={"account": EMAIL}, headers=AUTH)
    assert account.db.read_bytes() == before


def test_reading_does_not_leave_a_sqlite_journal_behind(client, token, account):
    client.get("/v1/portfolio/transactions", params={"account": EMAIL}, headers=AUTH)
    assert not list(account.root.glob("*.db-journal"))
    with sqlite3.connect(account.db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 3
