"""What the book can fix by itself, or offer back, without the reader asking.

* A sale an import refused only for want of shares is kept (`portfolio.held`)
  and offered back once the book can carry it — a split or transfer written
  later is the usual reason — instead of being lost with the request.
* A book imported before that lost such sales for good; a split written after
  a broker's last import, on a name that broker still shows open, is the trace
  it left, and Import says which statement to upload again.
* Revolut crypto buys booked with the fee still in their coins are the app's
  own mistake, repaired once per book from the warm (`portfolio.heal`),
  journalled so the reader's Undo takes it back and is never overruled.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.data.dividends import DividendHistory
from stocks.portfolio import edits, heal, held, validate
from stocks.portfolio.ledger import Transaction, add_many, all_transactions

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

BUY = Transaction("2022-05-24", "AMZN", "buy", 1.0, 2050.0, "USD", 1.0,
                  "clicktrade Amazon")
SPLIT = Transaction("2022-06-06", "AMZN", "split", 20.0, 0.0, "USD", 0.0,
                    "20:1 split (Yahoo corporate action)")
SELL = Transaction("2024-12-31", "AMZN", "sell", 20.0, 220.0, "USD", 1.0,
                   "clicktrade Amazon")


def refused(*txs: Transaction) -> list[validate.Checked]:
    return [
        validate.Checked(
            tx=t, issues=[validate.Issue("error", "quantity", held.OVERSELL)]
        )
        for t in txs
    ]


# ------------------------------------------------------------- held sales
def test_a_refused_sale_is_kept_and_offered_once_the_split_lands(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([BUY], db)
    assert held.keep(refused(SELL), "clicktrade", db) == 1
    assert held.ready(db) == []  # one share cannot carry a sale of twenty
    add_many([SPLIT], db)
    [ready] = held.ready(db)
    assert (ready.tx.ticker, ready.tx.quantity) == ("AMZN", 20.0)
    assert held.take([ready.id], db) is not None


def test_a_sale_refused_twice_is_kept_once(tmp_path):
    db = tmp_path / "portfolio.db"
    held.keep(refused(SELL), "clicktrade", db)
    held.keep(refused(SELL), "clicktrade", db)
    assert len(held.held(db)) == 1


def test_a_row_refused_for_anything_else_is_not_kept(tmp_path):
    db = tmp_path / "portfolio.db"
    bad = validate.Checked(
        tx=SELL,
        issues=[
            validate.Issue("error", "quantity", held.OVERSELL),
            validate.Issue("error", "date", "validate.future_date"),
        ],
    )
    assert held.keep([bad], "clicktrade", db) == 0


def test_a_sale_the_book_has_by_now_leaves_the_shelf(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([BUY, SPLIT], db)
    held.keep(refused(SELL), "clicktrade", db)
    add_many([SELL], db)  # typed by hand, or uploaded again
    assert held.ready(db) == []
    assert held.held(db) == []


def test_two_sales_are_offered_only_as_far_as_the_position_reaches(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([BUY, SPLIT], db)
    second = Transaction("2025-01-10", "AMZN", "sell", 5.0, 230.0, "USD", 1.0,
                         "clicktrade Amazon")
    held.keep(refused(SELL, second), "clicktrade", db)
    assert [h.tx.date for h in held.ready(db)] == ["2024-12-31"]
    ids = [h.id for h in held.held(db)]
    assert held.take(ids, db) is None


# --------------------------------------------------------- re-upload hints
def test_a_split_written_after_a_brokers_import_names_that_statement(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([BUY], db)
    add_many([SPLIT], db)
    [hint] = held.reuploads(all_transactions(db), db)
    assert (hint.broker, hint.ticker, hint.split_date) == (
        "clicktrade", "AMZN", "2022-06-06"
    )


def test_importing_that_broker_again_retires_the_hint(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([BUY, SPLIT], db)
    held.seen_broker("clicktrade", db)
    assert held.reuploads(all_transactions(db), db) == []


def test_a_dismissed_hint_stays_dismissed(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([BUY], db)
    add_many([SPLIT], db)
    [hint] = held.reuploads(all_transactions(db), db)
    held.dismiss(hint.key, db)
    assert held.reuploads(all_transactions(db), db) == []


def test_a_position_that_broker_closed_names_nothing(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([BUY], db)
    add_many([SPLIT, SELL], db)
    assert held.reuploads(all_transactions(db), db) == []


# ------------------------------------------------------------ fee in coins
CHILLGUY = [
    Transaction("2025-05-08", "CHILLGUY-EUR", "buy", 9302.54766102, 0.05, "EUR", 4.94,
                "revolut crypto CHILLGUY"),
    Transaction("2025-05-10", "CHILLGUY-EUR", "sell", 9210.45243918, 0.07, "EUR", 6.15,
                "revolut crypto CHILLGUY"),
]


def test_the_fee_comes_out_of_the_coins_once(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many(CHILLGUY, db)
    done = heal.fee_in_coins(db)
    assert done is not None and done.source == "doctor"
    [buy] = [t for t in all_transactions(db) if t.action == "buy"]
    assert buy.quantity == pytest.approx(9210.45243918)
    assert [(k, c.id) for k, c in heal.recent(db)] == [("fee_in_coins", done.id)]
    assert heal.fee_in_coins(db) is None


def test_an_undone_repair_is_never_written_again(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many(CHILLGUY, db)
    done = heal.fee_in_coins(db)
    edits.undo(done.id, path=db)
    assert heal.fee_in_coins(db) is None
    assert heal.recent(db) == []
    [buy] = [t for t in all_transactions(db) if t.action == "buy"]
    assert buy.quantity == pytest.approx(9302.54766102)


def test_a_book_without_such_buys_is_left_unmarked(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([BUY], db)
    assert heal.fee_in_coins(db) is None
    add_many(CHILLGUY, db)  # an old export imported later
    assert heal.fee_in_coins(db) is not None


# ---------------------------------------------------------- net dividends
KO = DividendHistory("KO", (("2024-03-14", 0.48), ("2024-06-13", 0.48)), "USD")
KO_BUY = Transaction("2024-01-02", "KO", "buy", 100.0, 60.0, "USD", 0.0, "revolut")
KO_MARCH = Transaction("2024-04-01", "KO", "dividend", 0.0, 40.80, "USD", 0.0, "revolut")
KO_JUNE = Transaction("2024-07-01", "KO", "dividend", 0.0, 40.80, "USD", 0.0, "revolut")


def ko_history(names):
    return {"KO": KO} if "KO" in names else {}


def test_a_net_revolut_dividend_gets_its_withholding_back_once(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([KO_BUY, KO_MARCH], db)
    done = heal.net_dividends(db, ko_history)
    assert done is not None and done.source == "doctor"
    [div] = [t for t in all_transactions(db) if t.action == "dividend"]
    assert (div.price, div.fee) == (48.0, 7.2)
    assert [(k, c.id) for k, c in heal.recent(db)] == [("net_dividends", done.id)]
    assert heal.net_dividends(db, ko_history) is None
    add_many([KO_JUNE], db)  # next month's statement
    again = heal.net_dividends(db, ko_history)
    assert again is not None and len(again.changes) == 1


def test_an_undone_dividend_repair_is_never_written_again(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([KO_BUY, KO_MARCH], db)
    done = heal.net_dividends(db, ko_history)
    edits.undo(done.id, path=db)
    assert heal.net_dividends(db, ko_history) is None
    [div] = [t for t in all_transactions(db) if t.action == "dividend"]
    assert (div.price, div.fee) == (40.80, 0.0)


def test_a_dividend_history_cannot_explain_is_asked_about_again(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([KO_BUY, KO_MARCH], db)
    assert heal.net_dividends(db, lambda names: {}) is None  # Yahoo said nothing
    assert heal.net_dividends(db, ko_history) is not None


def test_other_brokers_dividends_are_not_touched(tmp_path):
    db = tmp_path / "portfolio.db"
    ibkr = Transaction("2024-04-01", "KO", "dividend", 0.0, 40.80, "USD", 0.0, "ibkr")
    add_many([KO_BUY, ibkr], db)
    assert heal.net_dividends(db, ko_history) is None


# --------------------------------------------------------------------- API
@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    from stocks.api.routes import import_statement
    from stocks.portfolio import diagnostics

    monkeypatch.setattr(import_statement, "_ticker_exists", lambda ticker: None)
    monkeypatch.setattr(import_statement, "_charted", lambda ticker, budget: None)
    monkeypatch.setattr(
        import_statement.symbols, "symbol_for_code", lambda code, currency, **_: None
    )
    monkeypatch.setattr(import_statement.fetch, "splits", lambda ticker: [])
    monkeypatch.setattr(import_statement.loaders, "quotes", lambda tickers: {})
    monkeypatch.setattr(import_statement.loaders, "display_symbol", lambda t: t)
    monkeypatch.setattr(import_statement, "_exists_memo", {})
    monkeypatch.setattr(diagnostics, "DIAGNOSTICS_DIR", tmp_path / "diagnostics")
    monkeypatch.setattr(diagnostics.storage, "persist", lambda path: None)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AMZN\n")
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
    return sign_in(client, EMAIL)


def row(t: Transaction) -> dict:
    return {k: getattr(t, k) for k in edits.FIELDS}


def test_a_commit_keeps_the_sale_it_refused_and_checkup_offers_it_back(
    client, account, signed_in
):
    payload = signed_in.post(
        "/v1/import/commit",
        json={"filename": "trades.csv", "rows": [row(BUY), row(SELL)],
              "broker": "clicktrade"},
    ).json()
    assert payload["imported"] == 1 and len(payload["rejected"]) == 1
    checkup = client.get("/v1/import/checkup", params=WHO, headers=AUTH).json()
    assert checkup["held"] == []

    add_many([SPLIT], account.db)
    checkup = client.get("/v1/import/checkup", params=WHO, headers=AUTH).json()
    [sale] = checkup["held"]
    assert (sale["ticker"], sale["quantity"], sale["broker"]) == (
        "AMZN", 20.0, "clicktrade"
    )
    # The split came after this broker's import: the statement is named too.
    assert [h["broker"] for h in checkup["reupload"]] == ["clicktrade"]

    applied = signed_in.post("/v1/import/held/apply", json={"ids": [sale["id"]]})
    assert applied.json()["applied"] == 1
    assert [t.action for t in all_transactions(account.db)] == ["buy", "split", "sell"]
    again = signed_in.post("/v1/import/held/apply", json={"ids": [sale["id"]]})
    assert again.status_code == 409


def test_a_token_may_read_the_checkup_but_not_apply_from_it(client, account):
    add_many([BUY, SPLIT], account.db)
    held.keep(refused(SELL), "clicktrade", account.db)
    [sale] = client.get("/v1/import/checkup", params=WHO, headers=AUTH).json()["held"]
    response = client.post(
        "/v1/import/held/apply", params=WHO, headers=AUTH, json={"ids": [sale["id"]]}
    )
    assert response.status_code == 403
    assert len(all_transactions(account.db)) == 2


def test_a_finding_is_fixed_from_a_scan_run_now_and_undone_by_its_change(
    client, account, signed_in
):
    twice = Transaction("2024-03-01", "AMZN", "buy", 2.0, 180.0, "USD", 1.0,
                        "revolut Amazon")
    add_many([twice, Transaction(**{**row(twice), "note": "ibkr Amazon"})], account.db)
    [finding] = signed_in.get("/v1/import/checkup").json()["findings"]
    assert finding["kind"] == "duplicate"
    done = signed_in.post("/v1/import/fix", json={"key": finding["key"]}).json()
    assert len(all_transactions(account.db)) == 1
    again = signed_in.post("/v1/import/fix", json={"key": finding["key"]})
    assert again.status_code == 409
    signed_in.delete(f"/v1/portfolio/changes/{done['change_id']}")
    assert len(all_transactions(account.db)) == 2


def test_the_checkup_lists_the_repair_the_app_made(client, account, signed_in):
    add_many(CHILLGUY, account.db)
    done = heal.fee_in_coins(account.db)
    [healed] = signed_in.get("/v1/import/checkup").json()["healed"]
    assert (healed["kind"], healed["change_id"], healed["rows"]) == (
        "fee_in_coins", done.id, 1
    )
    assert "CHILLGUY-EUR" in healed["summary"]


def test_dismissing_a_hint_is_a_write(client, account, signed_in):
    add_many([BUY], account.db)
    add_many([SPLIT], account.db)
    [hint] = signed_in.get("/v1/import/checkup").json()["reupload"]
    assert signed_in.post(
        "/v1/import/reupload/dismiss", json={"key": hint["key"]}
    ).status_code == 204
    assert signed_in.get("/v1/import/checkup").json()["reupload"] == []


# ------------------------------------------------------------ in the chat
def said(key: str, **kw) -> str:
    return key + json.dumps(kw, sort_keys=True, default=str)


def checked(db, ticker: str = ""):
    from stocks.chat import book
    from stocks.chat.tools import Action

    return book.draft(Action("check_book", ticker), db=db, translate=said,
                      today="2026-10-31")


def test_the_chat_check_offers_a_held_sale_and_approving_writes_it(
    tmp_path, monkeypatch
):
    from stocks.chat import book

    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    db = tmp_path / "portfolio.db"
    add_many([BUY], db)
    held.keep(refused(SELL), "clicktrade", db)
    add_many([SPLIT], db)
    drafted = checked(db, "AMZN")
    assert "chat.book_finding_held" in drafted.text
    assert drafted.book is not None
    assert drafted.book["summary"].startswith("chat.book_summary_held")
    book.apply({"book": drafted.book}, db=db, source="chat", translate=said)
    assert [t.action for t in all_transactions(db)] == ["buy", "split", "sell"]
    assert held.ready(db) == []
    assert held.held(db) == []  # off the shelf once the ledger has it
    assert checked(db).text.startswith("chat.book_healthy")


def test_the_chat_check_names_the_statement_to_upload_again(tmp_path):
    db = tmp_path / "portfolio.db"
    add_many([BUY], db)
    held.seen_broker("clicktrade", db)
    add_many([SPLIT], db)
    drafted = checked(db, "AMZN")
    assert "chat.book_finding_reupload" in drafted.text
    assert '"broker": "clicktrade"' in drafted.text
    assert drafted.book is None  # an upload, not an edit
    assert checked(db, "MSFT").text.startswith("chat.book_healthy")
