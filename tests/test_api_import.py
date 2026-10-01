"""Importing a broker statement over HTTP.

Parsing a given broker's export and deciding which rows are importable belong
to `stocks.portfolio` and are tested there, per broker. What is tested here is
the contract the two endpoints add:

* a preview writes nothing, whatever it says;
* the model reads first and the parsers check it: the platform a request names
  is tried first and trusted no further, and the preview says who read it;
* a commit does not trust the preview — the rows it sends back, or the file
  read again, are validated again, because the ledger is shared and moves
  under both;
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
# The real one, held before the suite's conftest swaps `venue.pick` out for
# every test: the relabel tests below put it back.
from stocks.portfolio.venue import pick as _real_pick

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


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No Yahoo and no repo writes from the validation's live lookups.

    Validation now asks the market what the Streamlit page asks it — does an
    unfamiliar symbol trade, did an oversold ticker split — and files an
    anonymised diagnostic for every attempt. Neither belongs in a unit test:
    the lookups answer "could not check" and no splits unless a test says
    otherwise, the memo starts empty, and diagnostics land in tmp rather than
    in the checkout's data/imports.
    """
    from stocks.api.routes import import_statement
    from stocks.portfolio import diagnostics

    monkeypatch.setattr(import_statement, "_ticker_exists", lambda ticker: None)
    monkeypatch.setattr(
        import_statement.symbols, "symbol_for_code", lambda code, currency: None
    )
    monkeypatch.setattr(import_statement.fetch, "splits", lambda ticker: [])
    monkeypatch.setattr(import_statement, "_exists_memo", {})
    monkeypatch.setattr(diagnostics, "DIAGNOSTICS_DIR", tmp_path / "diagnostics")
    monkeypatch.setattr(diagnostics.storage, "persist", lambda path: None)


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


def test_a_branded_platform_carries_its_logo_and_a_generic_one_none(
    client, account, monkeypatch
):
    """The picker draws the brand mark beside the name, as Streamlit does; a
    platform with no brand site gets no image rather than a broken one."""
    from stocks.api import loaders

    monkeypatch.setattr(
        loaders, "brand_logo", lambda key: f"/app/static/logos/{key}.png"
        if key == "revolut" else None
    )
    payload = client.get("/v1/import/platforms", params=WHO, headers=AUTH).json()
    by_key = {p["key"]: p for p in payload["platforms"]}
    assert by_key["revolut"]["logo"] == "/app/static/logos/revolut.png"
    assert by_key["generic"]["logo"] is None


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
    client, account, signed_in, monkeypatch
):
    # The cap shrunk for the test: sending 50 MB of base64 through a test
    # client proves nothing a kilobyte does not.
    from stocks.api.routes import import_statement

    monkeypatch.setattr(import_statement, "MAX_BYTES", 1024)
    huge = base64.b64encode(b"x" * 1025).decode()
    response = signed_in.post("/v1/import/preview", json=body() | {"content": huge})
    assert response.status_code == 413


def test_the_cap_is_well_past_a_real_statement():
    """Not 8 MB any more: a decade of activity as a PDF runs to tens."""
    from stocks.api.routes import import_statement

    assert import_statement.MAX_BYTES >= 50 * 1024 * 1024


def test_a_statement_with_nothing_in_it_is_unreadable_not_empty(
    client, account, signed_in
):
    """No transaction and not even a skipped line: a file from the wrong
    platform or the wrong export. The page says "is this a … statement?", and
    a preview of zero rows would say nothing."""
    header_only = "date,ticker,action,quantity,price,currency,fee,note\n"
    response = signed_in.post("/v1/import/preview", json=body(header_only))
    assert response.status_code == 422
    assert "no transactions" in response.json()["detail"]


def test_a_symbol_the_market_quotes_carries_no_unknown_ticker_warning(
    client, account, signed_in, monkeypatch
):
    """The page's live lookup, on this surface too: without it the same
    statement read clean there and warned here."""
    from stocks.api.routes import import_statement

    unusual = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-01-02,ZZZQX.DE,buy,10,100.00,EUR,1.00,revolut Something\n"
    )

    def keys(payload):
        return [i["key"] for i in payload["importable"][0]["issues"]]

    blind = signed_in.post("/v1/import/preview", json=body(unusual)).json()
    assert "validate.unknown_ticker" in keys(blind)

    asked: list[str] = []
    monkeypatch.setattr(
        import_statement, "_ticker_exists", lambda t: asked.append(t) or True
    )
    seen = signed_in.post("/v1/import/preview", json=body(unusual)).json()
    assert "validate.unknown_ticker" not in keys(seen)
    signed_in.post("/v1/import/preview", json=body(unusual))
    assert asked == ["ZZZQX.DE"], "a definite answer is remembered"


def test_a_lookup_that_hangs_is_given_up_on(client, account, signed_in, monkeypatch):
    """A worker thread is not a spinner: past the budget the answer is "could
    not check", the warning stays, and the preview still comes back."""
    import time as clock

    from stocks.api.routes import import_statement

    monkeypatch.setattr(import_statement, "LOOKUP_BUDGET_S", 0.05)
    monkeypatch.setattr(
        import_statement, "_ticker_exists", lambda t: clock.sleep(1) or True
    )
    unusual = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-01-02,ZZZQX.DE,buy,10,100.00,EUR,1.00,revolut Something\n"
    )
    payload = signed_in.post("/v1/import/preview", json=body(unusual)).json()
    issues = [i["key"] for i in payload["importable"][0]["issues"]]
    assert "validate.unknown_ticker" in issues
    assert import_statement._exists_memo == {}, "a timeout is not remembered"
    assert payload["unlisted"] == [], "could not check is not a verdict"


def test_a_symbol_yahoo_says_it_does_not_list_is_named_in_the_preview(
    client, account, signed_in, monkeypatch
):
    """The rows go in, but hold at cost with no price: the reader has to hear
    which ones before committing, not find n/a on the portfolio later."""
    from stocks.api.routes import import_statement

    monkeypatch.setattr(import_statement, "_ticker_exists", lambda t: False)
    unusual = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-01-02,ZZZQX,buy,10,100.00,EUR,1.00,revolut Something\n"
        "2024-01-03,AAPL,buy,1,100.00,EUR,1.00,revolut Apple\n"
    )
    payload = signed_in.post("/v1/import/preview", json=body(unusual)).json()
    assert len(payload["importable"]) == 2
    assert payload["unlisted"] == ["ZZZQX"]


def test_a_code_the_book_already_holds_is_flagged_once_yahoo_disowns_it(
    client, account, signed_in, monkeypatch
):
    """A bare broker code in the ledger counts as known, so every later
    statement carrying it read clean while it sat unpriced. The price pass's
    verdict (`fetch.unlisted`) takes it back out of the known set — and is
    trusted without asking Yahoo a second time."""
    from stocks.api.routes import import_statement
    from stocks.data import fetch

    ledger.add_many(
        [Transaction("2024-01-02", "SAN", "buy", 10, 4.0, "EUR", 0.0, note="manual")],
        account.db,
    )
    asked: list[str] = []
    monkeypatch.setattr(
        import_statement, "_ticker_exists", lambda t: asked.append(t) or True
    )
    again = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-06-03,SAN,buy,5,4.50,EUR,1.00,revolut Santander\n"
    )

    before = signed_in.post("/v1/import/preview", json=body(again)).json()
    assert before["importable"][0]["issues"] == []
    assert before["unlisted"] == []

    fetch._unlisted.add("SAN")
    after = signed_in.post("/v1/import/preview", json=body(again)).json()
    warning = after["importable"][0]["issues"]
    assert [i["key"] for i in warning] == ["validate.unknown_ticker"]
    assert warning[0]["params"]["sources"].endswith("/yfinance")
    assert after["unlisted"] == ["SAN"]
    assert asked == [], "the download's verdict needs no second lookup"


def test_a_code_yahoo_disowns_but_its_search_places_imports_clean(
    client, account, signed_in, monkeypatch
):
    """Revolut prints Siemens as "SIE"; Yahoo quotes no bare SIE but lists
    SIE.DE. The search is asked on the trade currency's venues, and a hit
    makes the row known — no warning, not named as unpriced — and teaches the
    price path the symbol."""
    from stocks.api.routes import import_statement
    from stocks.data import fetch, symbols

    asked: list[tuple[str, str]] = []

    def search(code, currency):
        asked.append((code, currency))
        return {"SIE": "SIE.DE"}.get(code)

    monkeypatch.setattr(import_statement, "_ticker_exists", lambda t: False)
    monkeypatch.setattr(import_statement.symbols, "symbol_for_code", search)
    statement = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-01-02,SIE,buy,2,150.00,EUR,1.00,revolut Siemens\n"
        "2024-01-03,ZZZQX,buy,10,100.00,EUR,1.00,revolut Something\n"
    )
    payload = signed_in.post("/v1/import/preview", json=body(statement)).json()
    issues = {row["ticker"]: row["issues"] for row in payload["importable"]}
    assert issues["SIE"] == []
    assert payload["unlisted"] == ["ZZZQX"]
    assert sorted(asked) == [("SIE", "EUR"), ("ZZZQX", "EUR")]

    # What the search learned, the price path reads (the fake stood in for the
    # write the real one makes).
    symbols._code_memo = {"SIE": "SIE.DE"}
    assert fetch.resolve("SIE") == "SIE.DE"


def test_a_search_that_runs_out_of_time_is_not_a_verdict(
    client, account, signed_in, monkeypatch
):
    """Yahoo said no to the bare code and the venue search did not answer in
    time: "could not check", not "will import unpriced"."""
    import threading

    from stocks.api.routes import import_statement

    released = threading.Event()
    monkeypatch.setattr(import_statement, "LOOKUP_BUDGET_S", 0.3)
    monkeypatch.setattr(import_statement, "_ticker_exists", lambda t: False)
    monkeypatch.setattr(
        import_statement.symbols,
        "symbol_for_code",
        lambda code, currency: released.wait(5) and None,
    )
    statement = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-01-02,SIE,buy,2,150.00,EUR,1.00,revolut Siemens\n"
    )
    try:
        payload = signed_in.post("/v1/import/preview", json=body(statement)).json()
    finally:
        released.set()
    assert payload["unlisted"] == []


# A euro "ALV" is Allianz; the bare ALV Yahoo quotes is Autoliv, in dollars.
ALLIANZ = (
    "date,ticker,action,quantity,price,currency,fee,note\n"
    "2025-03-03,ALV,buy,2,248.60,EUR,1.00,revolut Allianz\n"
)


@pytest.fixture
def venues(monkeypatch):
    """The relabel's Yahoo: it quotes every code bare, offers ALV.DE and ALV.F
    for ALV, closed ALV.DE at 249.10 and Autoliv at 95 USD on the fill's day,
    and the dollar buys 0.92 of anything. Returns the closes, to empty."""
    from stocks.api.routes import import_statement
    from stocks.portfolio import venue

    closes = {("ALV.DE", "2025-03-03"): 249.1, ("ALV", "2025-03-03"): 95.0}
    monkeypatch.setattr(venue, "pick", _real_pick)
    monkeypatch.setattr(import_statement, "_ticker_exists", lambda t: True)
    monkeypatch.setattr(
        import_statement.symbols,
        "listings_for_code",
        lambda code, currency, limit=6: ["ALV.DE", "ALV.F"] if code == "ALV" else [],
    )
    monkeypatch.setattr(
        import_statement.fetch, "close_on", lambda symbol, day: closes.get((symbol, day))
    )
    monkeypatch.setattr(import_statement.fx, "rate_on", lambda day, base, quote: 0.92)
    return closes


def test_a_euro_code_yahoo_quotes_in_dollars_previews_under_its_venue(
    client, account, signed_in, venues
):
    payload = signed_in.post("/v1/import/preview", json=body(ALLIANZ)).json()
    [row] = payload["importable"]
    assert (row["ticker"], row["issues"]) == ("ALV.DE", [])
    assert payload["unlisted"] == []
    assert all_transactions(account.db) == [], "a preview still writes nothing"


def test_a_venue_no_price_confirms_leaves_the_code_as_printed(
    client, account, signed_in, venues
):
    venues.clear()  # throttled, or no history that day
    payload = signed_in.post("/v1/import/preview", json=body(ALLIANZ)).json()
    assert [row["ticker"] for row in payload["importable"]] == ["ALV"]


def test_a_commit_moves_the_books_euro_rows_and_leaves_the_dollar_ones(
    client, account, signed_in, venues
):
    """The Allianz bought before the fix joins the new row: one position, not
    an Allianz priced as Autoliv beside it. Autoliv stays Autoliv."""
    ledger.add_many(
        [
            Transaction("2025-01-02", "ALV", "buy", 1, 240.0, "EUR", 0.0, note="revolut Allianz"),
            Transaction("2025-01-02", "ALV", "buy", 3, 90.0, "USD", 0.0, note="revolut Autoliv"),
        ],
        account.db,
    )
    payload = signed_in.post("/v1/import/commit", json=body(ALLIANZ)).json()
    assert payload["imported"] == 1
    assert sorted((t.ticker, t.currency) for t in all_transactions(account.db)) == [
        ("ALV", "USD"),
        ("ALV.DE", "EUR"),
        ("ALV.DE", "EUR"),
    ]


def test_a_statement_imported_again_finds_its_rows_under_the_venue(
    client, account, signed_in, venues
):
    signed_in.post("/v1/import/commit", json=body(ALLIANZ))
    venues.clear()  # and Yahoo has started throttling since
    again = signed_in.post("/v1/import/preview", json=body(ALLIANZ)).json()
    assert again["duplicates"] == 1
    assert [row["ticker"] for row in again["importable"]] == ["ALV.DE"]


def test_a_refused_commit_leaves_the_books_codes_alone(
    client, account, signed_in, venues
):
    """Nothing written, nothing moved: the relabel waits for an import that
    lands."""
    ledger.add_many(
        [Transaction("2025-01-02", "ALV", "buy", 1, 240.0, "EUR", 0.0, note="revolut Allianz")],
        account.db,
    )
    oversold = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2025-03-03,ALV,sell,50,248.60,EUR,1.00,revolut Allianz\n"
    )
    response = signed_in.post("/v1/import/commit", json=body(oversold))
    assert response.status_code == 422
    assert [t.ticker for t in all_transactions(account.db)] == ["ALV"]


def test_an_oversold_ticker_is_rescued_by_the_split_the_file_never_printed(
    client, account, signed_in, monkeypatch
):
    """A statement of trades alone: 1 share bought, 20 sold after a 20:1. The
    page adds the split row instead of rejecting the sell, and so does this."""
    from stocks.api.routes import import_statement

    monkeypatch.setattr(
        import_statement.fetch, "splits", lambda t: [("2024-02-01", 20.0)]
    )
    split_hidden = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-01-02,AAPL,buy,1,2000.00,USD,0,revolut Apple\n"
        "2024-03-01,AAPL,sell,20,110.00,USD,0,revolut Apple\n"
    )
    payload = signed_in.post("/v1/import/preview", json=body(split_hidden)).json()
    assert payload["rejected"] == []
    assert "split" in [row["action"] for row in payload["importable"]]


def test_every_preview_files_an_anonymised_diagnostic(
    client, account, signed_in, monkeypatch
):
    """What the page records — the parse failure, the empty file and the full
    outcome — tagged with the door the file came through."""
    from stocks.portfolio import diagnostics

    filed: list[dict] = []
    real = diagnostics.report

    def spy(*args, **kwargs):
        filed.append({"n": len(args), **kwargs})
        return real(*args, **kwargs)

    monkeypatch.setattr(diagnostics, "report", spy)
    signed_in.post("/v1/import/preview", json=body())
    signed_in.post("/v1/import/preview", json=body(surface="paste"))
    header_only = "date,ticker,action,quantity,price,currency,fee,note\n"
    signed_in.post("/v1/import/preview", json=body(header_only))
    assert [f["surface"] for f in filed] == ["import", "paste", "import"]
    assert filed[0]["n"] == 5, "the parse and the validation both travel"


def test_a_commit_of_a_previewed_file_is_not_counted_twice(
    client, account, signed_in, monkeypatch
):
    """`expect` means its preview already filed this upload. A blind commit is
    the one attempt nothing else would record."""
    from stocks.portfolio import diagnostics

    filed: list[str] = []
    monkeypatch.setattr(
        diagnostics, "report", lambda *a, **k: filed.append(k["surface"]) or {}
    )
    digest = signed_in.post("/v1/import/preview", json=body()).json()["digest"]
    assert filed == ["import"]
    signed_in.post("/v1/import/commit", json=body(expect=digest))
    assert filed == ["import"]
    signed_in.post("/v1/import/commit", json=body(OVERSELL))
    assert filed == ["import", "import"]


def test_the_surface_is_one_of_the_two_doors(client, account, signed_in):
    response = signed_in.post("/v1/import/preview", json=body(surface="email"))
    assert response.status_code == 422


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



def rows_of(preview: dict) -> list[dict]:
    """The commit's `rows`, as a client builds them from the preview."""
    keep = ("date", "ticker", "action", "quantity", "price", "currency", "fee", "note")
    return [{k: row[k] for k in keep} for row in preview["importable"]]


def test_the_previewed_rows_are_written_without_the_file(client, account, signed_in):
    preview = signed_in.post("/v1/import/preview", json=body()).json()
    payload = signed_in.post(
        "/v1/import/commit",
        json={"filename": "ledger.csv", "rows": rows_of(preview),
              "platform": preview["platform"]},
    ).json()
    assert payload["imported"] == 2
    assert payload["platform"] == "generic"
    assert {t.ticker for t in all_transactions(account.db)} == {"AAPL", "MSFT"}


def test_the_rows_sent_back_are_validated_against_the_ledger_as_it_is_now(
    client, account, signed_in
):
    """A row the preview called clean can be an oversell by the time it comes
    back — here the buy it leaned on was never sent — and it is left out and
    named, not written."""
    preview = signed_in.post("/v1/import/preview", json=body()).json()
    sell = {**rows_of(preview)[0], "action": "sell", "date": "2024-03-01"}
    payload = signed_in.post(
        "/v1/import/commit",
        json={"filename": "ledger.csv", "rows": [rows_of(preview)[1], sell]},
    ).json()
    assert payload["imported"] == 1
    assert [row["ticker"] for row in payload["rejected"]] == ["AAPL"]
    assert {t.ticker for t in all_transactions(account.db)} == {"MSFT"}


def test_a_row_sent_back_with_an_action_the_ledger_does_not_know_is_refused(
    client, account, signed_in
):
    preview = signed_in.post("/v1/import/preview", json=body()).json()
    rows = rows_of(preview)
    rows[0]["action"] = "teleport"
    response = signed_in.post(
        "/v1/import/commit", json={"filename": "ledger.csv", "rows": rows}
    )
    assert response.status_code == 422
    assert all_transactions(account.db) == []


def test_rows_sent_back_are_never_read_again(client, account, signed_in, monkeypatch):
    from stocks.api.routes import import_statement

    preview = signed_in.post("/v1/import/preview", json=body()).json()

    def never(*a, **k):
        raise AssertionError("a commit with rows reads no file")

    monkeypatch.setattr(import_statement, "_read", never)
    response = signed_in.post(
        "/v1/import/commit",
        json={"filename": "ledger.csv", "rows": rows_of(preview)},
    )
    assert response.status_code == 200


# -------------------------------------------------------------- who reads it


class _Backend:
    id = "fake"
    needs_key = False


@pytest.fixture
def model(monkeypatch):
    """A model that reads every file as the one NVDA buy, and counts its calls.

    Patched where `autodetect` calls it, with a provider in front so it is
    reached at all (conftest keeps every other test on the parsers alone).
    """
    from stocks.api.routes import import_statement
    from stocks.portfolio import autodetect, llm_map
    from stocks.portfolio.statement import ParseResult

    calls: list[str] = []

    def extract(filename, data, provider, api_key, mapping=None):
        calls.append(filename)
        return llm_map.Extraction(
            ParseResult(transactions=[Transaction(
                date="2024-03-01", ticker="NVDA", action="buy", quantity=4,
                price=500.0, currency="EUR", fee=1.0, note="revolut Nvidia",
            )]),
            kind=llm_map.KIND_TRADES,
        )

    monkeypatch.setattr(autodetect.llm_map, "extract", extract)
    monkeypatch.setattr(
        import_statement, "_provider", lambda paths, held=None: (_Backend(), "k")
    )
    return calls


def test_the_preview_says_which_parser_read_the_file(client, account, signed_in):
    payload = signed_in.post("/v1/import/preview", json=body()).json()
    assert payload["platform"] == "generic"
    assert payload["label"]
    assert payload["kind"] == "trades"
    assert payload["unavailable"] is False


def test_a_named_platform_is_tried_first_and_trusted_no_further(
    client, account, signed_in
):
    """The page preselects a platform; a generic ledger uploaded under Revolut
    is still read, by the parser that owns it, and the answer says so."""
    payload = signed_in.post(
        "/v1/import/preview", json=body(platform="revolut")
    ).json()
    assert payload["platform"] == "generic"
    assert len(payload["importable"]) == 2


@pytest.mark.parametrize("named", ["", "llm"])
def test_naming_no_platform_still_reads_the_file(client, account, signed_in, named):
    payload = signed_in.post("/v1/import/preview", json=body(platform=named)).json()
    assert payload["platform"] == "generic"
    assert len(payload["importable"]) == 2


def test_the_model_reads_a_file_no_parser_owns(client, account, signed_in, model):
    foreign = "When,What,Units,Each\n01/03/2024,NVDA,4,500\n"
    payload = signed_in.post(
        "/v1/import/preview", json=body(foreign, filename="extracto.csv")
    ).json()
    assert payload["platform"] == "llm"
    assert payload["label"] == ""
    assert [r["ticker"] for r in payload["importable"]] == ["NVDA"]
    assert model == ["extracto.csv"]


def test_a_parser_that_reads_as_much_as_the_model_wins(
    client, account, signed_in, model
):
    """The model found one row, the parser two: the parser's read is kept, and
    a tie would go to the parser as well — it is exact where a model is only
    likely."""
    payload = signed_in.post("/v1/import/preview", json=body()).json()
    assert payload["platform"] == "generic"
    assert [r["ticker"] for r in payload["importable"]] == ["AAPL", "MSFT"]
    assert model == ["ledger.csv"], "the model was asked first all the same"


def test_a_commit_of_the_previewed_file_does_not_ask_the_model_twice(
    client, account, signed_in, model
):
    foreign = "When,What,Units,Each\n01/03/2024,NVDA,4,500\n"
    preview = signed_in.post(
        "/v1/import/preview", json=body(foreign, filename="extracto.csv")
    ).json()
    payload = signed_in.post(
        "/v1/import/commit",
        json=body(foreign, filename="extracto.csv", expect=preview["digest"]),
    ).json()
    assert payload["platform"] == "llm"
    assert payload["imported"] == 1
    assert len(model) == 1, "the preview's read is remembered for the commit"

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
