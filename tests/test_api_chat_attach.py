"""A statement attached to a conversation, over HTTP.

What parsing, detection and validation do is tested where they live. What is
tested here is the pair of calls the drawer makes and the promises they carry:

* a preview writes nothing to the ledger, and says what committing it would;
* the rows the ledger already holds are held back rather than silently
  re-imported, and the preview is what offers them anyway;
* both calls leave the conversation saying what happened, so a client that
  reloads mid-import is not looking at a thread that never mentions the file;
* a commit refuses a batch with no broker, because the fees and custody views
  read the book by it, and refuses an action the ledger has no meaning for;
* the rows a commit sends back are validated again, so one that stopped
  validating since the preview is named and left out, never written;
* a file reads the same here as on the Import page, because it is the same read
  and the same validation;
* the demo book goes on the first real import — an invented cost basis must
  never mix into a real one;
* every one of these is a write, and a bearer token never gets one.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.api.routes.import_statement import _provider as _real_provider
from stocks.portfolio import demo, ledger
from stocks.portfolio.ledger import Transaction, all_transactions

# The real one, held before the suite's conftest swaps `venue.pick` out.
from stocks.portfolio.venue import pick as _real_pick

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

# A generic ledger export: one of the parsers owns it, so no model is asked.
CLEAN = """date,ticker,action,quantity,price,currency,fee,note
2024-01-02,AAPL,buy,10,100.00,EUR,1.00,revolut Apple
2024-02-01,MSFT,buy,5,200.00,EUR,1.00,revolut Microsoft
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
    paths.prefs.write_text(json.dumps({"currency": "EUR", "language": "en"}))
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


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No live lookup, no split lookup, no ISIN map and no diagnostics on disk:
    this file is about the HTTP surface, and the validation it borrows from the
    Import page asks Yahoo about every symbol it does not know."""
    monkeypatch.setattr(
        "stocks.api.routes.import_statement._ticker_exists", lambda t: True
    )
    monkeypatch.setattr(
        "stocks.api.routes.import_statement.symbols.symbol_for_code",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "stocks.api.routes.import_statement.symbols.symbol_for_isin",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("stocks.api.routes.import_statement._exists_memo", {})
    monkeypatch.setattr(
        "stocks.api.routes.import_statement._charted", lambda ticker, budget: None
    )
    monkeypatch.setattr("stocks.data.fetch.splits", lambda *a, **k: {})
    monkeypatch.setattr(
        "stocks.portfolio.diagnostics.DIAGNOSTICS_DIR", tmp_path / "diagnostics"
    )


def attach(text: str = CLEAN, **extra) -> dict:
    return {"filename": "ledger.csv", "content": upload(text), **extra}


def committed(preview: dict, **extra) -> dict:
    """The commit body a client builds out of a preview it was just shown."""
    return {
        "filename": preview["filename"],
        "platform": preview["platform"],
        "broker": preview["broker"] or "revolut",
        "rows": [dict(row) for row in preview["fresh"]],
        **extra,
    }


# ------------------------------------------------------------------ preview


def test_a_preview_says_what_it_would_write_and_writes_nothing(
    client, account, signed_in
):
    payload = signed_in.post("/v1/chat/attachments", json=attach()).json()
    assert [r["ticker"] for r in payload["fresh"]] == ["AAPL", "MSFT"]
    assert payload["platform"], "a file a parser owns is named, not guessed at"
    assert not all_transactions(account.db), "a preview is not an import"


def test_the_preview_files_a_note_on_the_thread(client, account, signed_in):
    """A client that reloads between the preview and the button finds the
    conversation saying a file arrived — the card is not a turn, the note is."""
    payload = signed_in.post("/v1/chat/attachments", json=attach()).json()
    assert payload["message"]["action"] == "import"
    assert "ledger.csv" in payload["message"]["content"]

    cid = payload["conversation"]
    thread = signed_in.get(f"/v1/chat/conversations/{cid}").json()
    assert thread["messages"][-1]["content"] == payload["message"]["content"]


def test_an_unknown_thread_is_refused_before_anything_is_read(
    client, account, signed_in
):
    response = signed_in.post(
        "/v1/chat/attachments", json=attach(conversation="nope")
    )
    assert response.status_code == 404


def test_rows_the_ledger_already_holds_are_held_back_not_re_imported(
    client, account, signed_in
):
    first = signed_in.post("/v1/chat/attachments", json=attach()).json()
    signed_in.post("/v1/chat/attachments/commit", json=committed(first))

    again = signed_in.post("/v1/chat/attachments", json=attach()).json()
    assert again["fresh"] == [], "the same export twice imports nothing by itself"
    assert [r["ticker"] for r in again["duplicates"]] == ["AAPL", "MSFT"]
    assert again["duplicates"][0]["why"], "a held-back row says why it was held"


def test_why_a_row_was_flagged_reads_in_the_account_language(
    client, account, signed_in, monkeypatch
):
    """The issue text is rendered on the server, where a language left
    unpassed falls back to English: a Spanish account read every warning of
    a Spanish-titled card in English."""
    monkeypatch.setattr(
        "stocks.api.routes.import_statement._ticker_exists", lambda t: None
    )
    account.prefs.write_text(json.dumps({"currency": "EUR", "language": "es"}))
    odd = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-01-02,ZZZQX,buy,10,100.00,EUR,1.00,revolut Something\n"
    )
    payload = signed_in.post("/v1/chat/attachments", json=attach(odd)).json()
    assert payload["flagged"][0]["why"].startswith("no reconocemos ZZZQX")


def test_a_file_no_parser_owns_is_answered_rather_than_failed(
    client, account, signed_in, monkeypatch
):
    """An account with nothing to ask — no key, no free chain — still gets an
    answer: the parsers read, the model is simply never reached."""
    from stocks.api.routes import import_statement

    monkeypatch.setattr(import_statement, "_provider", _real_provider)
    monkeypatch.setattr(
        "stocks.chat.engine.attempts", lambda prefs, held=None: []
    )
    payload = signed_in.post(
        "/v1/chat/attachments", json=attach("nothing,useful\n1,2\n")
    ).json()
    assert payload["fresh"] == []
    assert payload["skipped"], "the file is accounted for, not silently dropped"
    assert payload["needs_broker"] is False, "nothing to file needs no origin"


def test_a_preview_is_a_write_so_a_bearer_token_never_gets_one(client, account):
    response = client.post(
        "/v1/chat/attachments", params=WHO, headers=AUTH, json=attach()
    )
    assert response.status_code == 403


# ------------------------------------------------------------------- commit


def test_the_rows_land_in_the_ledger_stamped_with_their_broker(
    client, account, signed_in
):
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    payload = signed_in.post(
        "/v1/chat/attachments/commit", json=committed(preview, broker="revolut")
    ).json()

    rows = all_transactions(account.db)
    assert payload["imported"] == len(rows) == 2
    assert payload["total"] == 2
    assert all(tx.note.lower().startswith("revolut") for tx in rows)


def test_the_commit_files_its_receipt_and_the_undo_hint(client, account, signed_in):
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    payload = signed_in.post(
        "/v1/chat/attachments/commit", json=committed(preview)
    ).json()
    cid = preview["conversation"]
    thread = signed_in.get(f"/v1/chat/conversations/{cid}").json()
    assert thread["messages"][-1]["content"] == payload["message"]["content"]
    assert payload["message"]["action"] == "import"


def test_a_batch_with_no_broker_is_refused_rather_than_filed_anywhere(
    client, account, signed_in
):
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    response = signed_in.post(
        "/v1/chat/attachments/commit", json=committed(preview, broker="  ")
    )
    assert response.status_code == 422
    assert not all_transactions(account.db)


def test_an_action_the_ledger_has_no_meaning_for_is_refused(
    client, account, signed_in
):
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    body = committed(preview)
    body["rows"][0]["action"] = "teleport"
    response = signed_in.post("/v1/chat/attachments/commit", json=body)
    assert response.status_code == 422
    assert not all_transactions(account.db), "nothing lands from a refused batch"



def test_a_row_that_no_longer_validates_is_left_out_and_named(
    client, account, signed_in
):
    """The commit validates again: a sale the book does not cover is rejected
    on the way in, whatever the client says the preview showed."""
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    body = committed(preview)
    body["rows"].append({**body["rows"][0], "action": "sell", "quantity": 99,
                         "date": "2024-03-01"})
    payload = signed_in.post("/v1/chat/attachments/commit", json=body).json()
    assert payload["imported"] == 2
    assert [r["ticker"] for r in payload["rejected"]] == ["AAPL"]
    assert payload["rejected"][0]["why"], "a rejected row says why"
    assert "AAPL" in payload["message"]["content"], "and the turn says so"
    assert len(all_transactions(account.db)) == 2


def test_a_batch_nothing_of_which_validates_writes_nothing(
    client, account, signed_in
):
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    body = committed(preview)
    body["rows"] = [{**body["rows"][0], "action": "sell", "quantity": 99}]
    response = signed_in.post("/v1/chat/attachments/commit", json=body)
    assert response.status_code == 422
    assert not all_transactions(account.db)


def test_a_relabeled_batch_moves_the_books_rows_with_it(
    client, account, signed_in, monkeypatch
):
    """Revolut's euro ALV previews as ALV.DE; committing it moves the Allianz
    the book already held under "ALV" too, so the two are one position."""
    from stocks.api.routes import import_statement
    from stocks.portfolio import venue

    monkeypatch.setattr(venue, "pick", _real_pick)
    monkeypatch.setattr(
        import_statement.symbols,
        "listings_for_code",
        lambda code, currency, limit=6: ["ALV.DE"] if code == "ALV" else [],
    )
    # The commit sends ALV.DE back, so what proves the book's own "ALV" is
    # that row's price against ALV.DE's close on its day.
    closes = {
        ("ALV.DE", "2025-03-03"): 249.1,
        ("ALV.DE", "2025-01-02"): 241.0,
        ("ALV", "2025-03-03"): 95.0,
    }
    monkeypatch.setattr(
        import_statement.fetch, "close_on", lambda symbol, day: closes.get((symbol, day))
    )
    monkeypatch.setattr(import_statement.fx, "rate_on", lambda day, base, quote: 0.92)
    ledger.add_many(
        [
            Transaction(
                "2025-01-02", "ALV", "buy", 1, 240.0, "EUR", 0.0, note="revolut Allianz"
            )
        ],
        account.db,
    )
    allianz = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2025-03-03,ALV,buy,2,248.60,EUR,1.00,revolut Allianz\n"
    )

    preview = signed_in.post("/v1/chat/attachments", json=attach(allianz)).json()
    assert [r["ticker"] for r in preview["fresh"]] == ["ALV.DE"]
    signed_in.post("/v1/chat/attachments/commit", json=committed(preview))
    assert [t.ticker for t in all_transactions(account.db)] == ["ALV.DE", "ALV.DE"]


def test_a_file_reads_the_same_here_as_on_the_import_page(
    client, account, signed_in
):
    chat = signed_in.post("/v1/chat/attachments", json=attach()).json()
    page = signed_in.post(
        "/v1/import/preview",
        json={"filename": "ledger.csv", "content": upload(CLEAN)},
    ).json()
    assert chat["platform"] == page["platform"]
    assert [r["ticker"] for r in chat["fresh"]] == [
        r["ticker"] for r in page["importable"] if not r["duplicate"]
    ]

def test_the_first_real_import_takes_the_demo_book_with_it(
    client, account, signed_in
):
    demo.seed(account.db)
    assert demo.active(account.db)

    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    signed_in.post("/v1/chat/attachments/commit", json=committed(preview))

    rows = all_transactions(account.db)
    assert demo.without(rows) == rows, "an invented cost basis never mixes in"


def test_a_commit_is_a_write_so_a_bearer_token_never_gets_one(client, account):
    response = client.post(
        "/v1/chat/attachments/commit",
        params=WHO,
        headers=AUTH,
        json={
            "filename": "ledger.csv",
            "broker": "revolut",
            "rows": [
                {
                    "date": "2024-01-02",
                    "ticker": "AAPL",
                    "action": "buy",
                    "quantity": 1,
                    "price": 10,
                    "currency": "EUR",
                }
            ],
        },
    )
    assert response.status_code == 403


# ------------------------------------------------------------ column mapping

# No parser owns these headers, so the column mapper reads it.
FOREIGN = """When,What,Side,Units,Each,Money
02/01/2024,AAPL,Compra,10,100,EUR
05/02/2024,MSFT,Compra,5,200,EUR
"""


@pytest.fixture
def mapper(monkeypatch):
    """A column mapper that swaps quantity and price, as a weak model might,
    and a chain with one backend so the mapper is reached at all."""
    from stocks.portfolio import llm_map

    class Backend:
        id = "fake"
        needs_key = False

    asked: list[int] = []

    def wrong(provider, api_key, grid):
        asked.append(1)
        return {"header_row": 0,
                "columns": {"date": 0, "ticker": 1, "action": 2, "quantity": 4,
                            "price": 3, "amount": None, "currency": 5,
                            "fee": None, "note": None},
                "date_format": "%d/%m/%Y", "decimal": ".", "thousands": "",
                "action_map": {"compra": "buy"}, "asset_class": ""}

    monkeypatch.setattr(llm_map, "map_columns", wrong)
    monkeypatch.setattr(llm_map, "_resolve_symbols", lambda *a, **k: None)
    monkeypatch.setattr(
        "stocks.api.routes.import_statement._provider",
        lambda paths, held=None: (Backend(), "k"),
    )
    return asked


def test_a_mapped_export_shows_how_its_columns_were_read(
    client, account, signed_in, mapper
):
    from stocks.chat import a2ui

    payload = signed_in.post(
        "/v1/chat/attachments", json=attach(FOREIGN, filename="foreign.csv")
    ).json()
    read = [(r["quantity"], r["price"]) for r in payload["fresh"]]
    assert read == [(100, 10), (200, 5)]
    surface = payload["surface"]
    a2ui.check(surface)
    data = surface[-1]["updateDataModel"]["value"]["mapping"]
    assert data["columns"]["quantity"] == "4"
    pickers = surface[1]["updateComponents"]["components"]
    options = next(c for c in pickers if c["id"] == "c_quantity")["options"]
    # The file's own column names, with a sample — not bare indices.
    assert {"label": "Units · 10", "value": "3"} in options
    again = next(c for c in pickers if c["id"] == "again")
    assert again["action"]["event"]["name"] == "remap"


def test_a_corrected_mapping_is_read_again_with_no_model_call(
    client, account, signed_in, mapper
):
    first = signed_in.post(
        "/v1/chat/attachments", json=attach(FOREIGN, filename="foreign.csv")
    ).json()
    mapping = first["surface"][-1]["updateDataModel"]["value"]["mapping"]
    mapping["columns"].update({"quantity": "3", "price": "4"})
    mapper.clear()
    again = signed_in.post(
        "/v1/chat/attachments",
        json=attach(FOREIGN, filename="foreign.csv", mapping=mapping),
    ).json()
    assert mapper == []
    assert [(r["quantity"], r["price"]) for r in again["fresh"]] == [(10, 100), (5, 200)]
    assert again["surface"][-1]["updateDataModel"]["value"]["mapping"]["columns"][
        "quantity"] == "3"


def test_a_mapping_missing_a_required_column_reads_nothing(
    client, account, signed_in, mapper
):
    first = signed_in.post(
        "/v1/chat/attachments", json=attach(FOREIGN, filename="foreign.csv")
    ).json()
    mapping = first["surface"][-1]["updateDataModel"]["value"]["mapping"]
    mapping["columns"]["date"] = ""
    again = signed_in.post(
        "/v1/chat/attachments",
        json=attach(FOREIGN, filename="foreign.csv", mapping=mapping),
    ).json()
    assert again["fresh"] == [] and again["skipped"]


def test_a_file_a_parser_owns_has_no_mapping_to_show(client, account, signed_in):
    payload = signed_in.post("/v1/chat/attachments", json=attach()).json()
    assert payload["surface"] is None
