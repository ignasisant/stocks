"""Ledger edits asked for in the chat: proposed, approved, journalled, undone.

The classifier is stubbed to hear a given `Action` (what it can parse is
pinned at the end); everything after it is real — `chat/book.py` finds the
rows and plans the edit, the engine files the proposal, the approval commits
it through `stocks.portfolio.edits` under the plan's token, and the undo takes
it back through the same journal the portfolio API uses.

The Grifols book of test_api_edits.py: DEGIRO's sale under the ISIN, IBKR's
buy at the carried basis under the symbol — a move nothing paired. Labels
resolve through a dict, so nothing here touches the network.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.chat import book, engine, tools
from stocks.chat.tools import Action
from stocks.portfolio import edits
from stocks.portfolio.ledger import Transaction, add, add_many, all_transactions
from stocks.web import auth

EMAIL = "holder@example.com"
PREFS = {"currency": "EUR", "chat_skills_mode": "off"}

BOOK = [
    Transaction("2024-03-01", "ES0171996087", "buy", 100, 8.0, "EUR", 2.0,
                "degiro GRIFOLS"),
    Transaction("2026-08-06", "ES0171996087", "sell", 100, 12.0, "EUR", 0.0,
                "degiro GRIFOLS"),
    Transaction("2026-08-20", "GRF.MC", "buy", 100, 8.02, "EUR", 0.0, "ibkr"),
]
SYMBOLS = {"ES0171996087": "GRF.MC", "GRF": "GRF.MC"}
MOVE = Action("mark_transfer", "GRF.MC", {"broker": "degiro", "to_broker": "ibkr"})


class Provider:
    """Answers anything; a book action must never get as far as asking it."""

    needs_key = False
    domain = None
    id = "fake"
    label = "Fake"
    models = ("fake-1",)
    default_model = "fake-1"

    def stream(self, api_key, model, system, messages):
        yield "Model answer."

    def complete(self, api_key, model, system, messages):
        return "Model answer."

    def available(self):
        return True


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(book, "resolver", lambda: lambda s: SYMBOLS.get(s, s))
    monkeypatch.setattr(engine, "attempts", lambda prefs: [(Provider(), "k", "fake-1")])
    monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])


@pytest.fixture
def hears(monkeypatch):
    """Make the classifier hear `act` in the next message, and only that one."""

    def install(act):
        heard = iter([act])
        monkeypatch.setattr(tools, "maybe_action", lambda text: True)
        monkeypatch.setattr(tools, "detect", lambda *a, **k: next(heard, None))

    return install


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist: []\n")
    paths.prefs.write_text(json.dumps(PREFS))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    add_many(BOOK, paths.db)
    return paths


@pytest.fixture
def signed_in(sign_in):
    return sign_in(TestClient(fastapi_app), EMAIL)


def actions(account) -> list[str]:
    return [t.action for t in all_transactions(account.db)]


# ------------------------------------------------------------- the drawer


def run(message=None, resume=None) -> dict:
    body: dict = {
        "threadId": "", "runId": "run-1", "state": {}, "tools": [],
        "forwardedProps": {"lang": "en"},
        "messages": ([{"id": "m1", "role": "user", "content": message}]
                     if message is not None else []),
    }
    if resume is not None:
        body["resume"] = resume
    return body


def events(body: str) -> list[dict]:
    return [json.loads(b.strip()[len("data: "):]) for b in body.split("\n\n")
            if b.strip() and not b.strip().startswith(":")]


def ask(signed_in, hears, act) -> tuple[list[dict], dict]:
    hears(act)
    stream = events(signed_in.post("/v1/chat/runs", json=run("arregla grifols")).text)
    (end,) = [e for e in stream if e["type"] in ("RUN_FINISHED", "RUN_ERROR")]
    return stream, end


def answer(signed_in, pid, approved=True) -> list[dict]:
    entry = {"interruptId": pid, "status": "resolved",
             "payload": {"approved": approved}}
    return events(signed_in.post("/v1/chat/runs", json=run(resume=[entry])).text)


def test_a_move_is_proposed_with_its_impact_and_nothing_is_written(
    account, signed_in, hears
):
    before = all_transactions(account.db)
    stream, end = ask(signed_in, hears, MOVE)
    assert end["type"] == "RUN_FINISHED"
    assert end["outcome"]["interrupts"][0]["reason"] == "confirm_action"
    offer = end["result"]["proposal"]
    assert offer["kind"] == "mark_transfer" and offer["state"] == "pending"
    assert offer["book"]["token"] and offer["book"]["ops"]
    assert offer["book"]["impact"]["realized"] == {"2026": {"EUR": -398.0}}
    text = "".join(e["delta"] for e in stream if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "-398.00 EUR" in text
    # A diff surface, never the watchlist form: a planned edit is not edited.
    (shown,) = [e for e in stream if e["type"] == "ACTIVITY_SNAPSHOT"]
    assert shown["messageId"] == f"diff_{offer['id']}"
    labels = [c.get("label") for m in shown["content"]["messages"]
              for c in m.get("updateComponents", {}).get("components", [])]
    assert "Realized gain 2026" in labels
    assert all_transactions(account.db) == before


def test_approved_it_is_journalled_and_undo_puts_the_book_back(
    account, signed_in, hears
):
    before = all_transactions(account.db)
    _, end = ask(signed_in, hears, MOVE)
    pid = end["result"]["proposal"]["id"]

    done = answer(signed_in, pid)
    assert done[-1]["type"] == "RUN_FINISHED"
    assert done[-1]["result"]["proposal"]["state"] == "done"
    assert set(actions(account)) == {"buy", "transfer_out", "transfer_in"}
    (change,) = edits.history(account.db)
    assert change.source == "chat"
    assert done[-1]["result"]["proposal"]["book"]["change"] == change.id

    undone = signed_in.post(f"/v1/chat/proposals/{pid}/undo")
    assert undone.status_code == 200
    assert undone.json()["proposal"]["state"] == "undone"
    assert all_transactions(account.db) == before
    # The thread says so, under the turn that still says it was done.
    last = auth.load_chat(account.chat)[-1]
    assert last["action"] == "undo_change"
    assert signed_in.post(f"/v1/chat/proposals/{pid}/undo").status_code == 409
    assert signed_in.post("/v1/chat/proposals/nope/undo").status_code == 404


def test_a_book_that_moved_since_the_proposal_refuses_it(account, signed_in, hears):
    _, end = ask(signed_in, hears, MOVE)
    pid = end["result"]["proposal"]["id"]
    add(Transaction("2026-09-01", "SAN.MC", "buy", 10, 4.0, "EUR"), account.db)
    stream = answer(signed_in, pid)
    assert stream[-1]["type"] == "RUN_ERROR"
    assert stream[-1]["code"] == "chat.book_stale"
    assert "transfer_out" not in actions(account)
    assert edits.history(account.db) == []


def test_cancelled_nothing_changes(account, signed_in, hears):
    before = all_transactions(account.db)
    _, end = ask(signed_in, hears, MOVE)
    stream = answer(signed_in, end["result"]["proposal"]["id"], approved=False)
    assert stream[-1]["result"]["proposal"]["state"] == "cancelled"
    assert all_transactions(account.db) == before


def test_a_watchlist_proposal_has_nothing_to_undo(account, signed_in, hears):
    _, end = ask(signed_in, hears, Action("favorite", "AAPL", {}))
    pid = end["result"]["proposal"]["id"]
    answer(signed_in, pid)
    assert signed_in.post(f"/v1/chat/proposals/{pid}/undo").status_code == 409


def test_a_listing_asks_nothing(account, signed_in, hears):
    stream, end = ask(signed_in, hears, Action("show_transactions", "GRF.MC",
                                               {"broker": "degiro"}))
    assert "proposal" not in end["result"]
    text = "".join(e["delta"] for e in stream if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert text.startswith("2 recorded trades:")


# -------------------------------------------------------------- Telegram


def bot(account, message: str) -> engine.Reply:
    return engine.answer(prefs=dict(PREFS), prefs_path=account.prefs,
                         chat_path=account.chat, watchlist=account.watchlist,
                         db=account.db, message=message, lang="es")


def test_on_telegram_a_ledger_edit_waits_for_a_typed_yes(account, hears):
    """The bot acts on watchlist requests at once; the book it only touches
    once the reader writes "sí" under the question."""
    hears(Action("delete_transactions", "GRF.MC", {"broker": "ibkr"}))
    asked = bot(account, "borra la compra de grifols en ibkr")
    assert asked.proposal and asked.proposal["state"] == "pending"
    assert asked.text.endswith("Responde «sí» para aplicarlo o «no» para dejarlo.")
    assert len(all_transactions(account.db)) == 3

    done = bot(account, "sí")
    assert done.proposal and done.proposal["state"] == "done"
    assert [t.note for t in all_transactions(account.db)] == ["degiro GRIFOLS"] * 2
    (change,) = edits.history(account.db)
    assert change.source == "telegram"


def test_on_telegram_a_no_leaves_the_book_alone(account, hears):
    hears(Action("delete_transactions", "GRF.MC", {"broker": "ibkr"}))
    bot(account, "borra la compra de grifols en ibkr")
    said = bot(account, "no")
    assert said.proposal and said.proposal["state"] == "cancelled"
    assert len(all_transactions(account.db)) == 3


# ------------------------------------------------------------- the reading


def test_the_classifier_reply_is_read_into_selectors():
    act = tools.parse_action(json.dumps({
        "action": "edit_transaction", "ticker": "grf", "broker": "DeGiro",
        "date": "2026-08-06", "ids": ["#2", 2, "x"], "new_price": "12,5",
        "currency": "eur", "since": "ayer",
    }))
    assert act == Action("edit_transaction", "GRF", {
        "broker": "degiro", "date": "2026-08-06", "ids": [2],
        "new_price": 12.5, "currency": "EUR",
    })


def test_a_ledger_tool_that_needs_a_company_refuses_a_reply_without_one():
    assert tools.parse_action('{"action": "rename_security", "to": "GRF.MC"}') is None
    assert tools.parse_action('{"action": "undo_change"}') == Action(
        "undo_change", "", {})


# ------------------------------------------------------------- closing


# Revolut booked the fee inside the coins bought, so a sale of everything
# left 1% behind — the CAT-EUR leftover a reader asked the chat to remove.
DUST = [
    Transaction("2025-05-10", "CAT-EUR", "buy", 44471331.2889, 1.1243198382163106e-05,
                "EUR", 4.95, "revolut crypto CAT"),
    Transaction("2026-06-18", "CAT-EUR", "sell", 44031065.1091,
                1.1326094400949036e-06, "EUR", 0.0, "revolut crypto CAT"),
]


def _translate(key, **kw):
    from stocks.web.i18n import translate

    return translate(key, "en", **kw)


def test_closing_a_revolut_leftover_takes_the_fee_coins_off_the_buy(tmp_path):
    # The CAT-EUR case: the 440,266 coins left are the ones the 4.95 € fee
    # took, booked into the buy by an older import. Fixing the buy also takes
    # the fee out of the cost twice over; booking a sale would invent one.
    db = tmp_path / "book.db"
    add_many(DUST, db)
    drafted = book.draft(Action("close_position", "CAT-EUR", {}), db=db,
                         translate=_translate, resolve=lambda s: s)
    (op,) = drafted.book["ops"]
    assert op["op"] == "update"
    assert op["fields"]["quantity"] == DUST[1].quantity
    assert op["fields"]["note"] == "revolut crypto CAT net"
    impact = drafted.book["impact"]
    assert impact["positions"] == [1, 0]
    assert impact["held"][0]["after"] == 0


def test_closing_books_the_leftover_as_sold_on_the_emptying_sale(tmp_path):
    db = tmp_path / "book.db"
    add_many([replace(t, note="kraken CAT") for t in DUST], db)
    drafted = book.draft(Action("close_position", "CAT-EUR", {}), db=db,
                         translate=_translate, resolve=lambda s: s)
    (op,) = drafted.book["ops"]
    row = op["row"]
    assert row["action"] == "sell" and row["date"] == "2026-06-18"
    assert row["quantity"] == pytest.approx(440266.1798, abs=1e-3)
    assert row["price"] == DUST[1].price and row["note"] == "kraken CAT"
    impact = drafted.book["impact"]
    assert impact["positions"] == [1, 0]
    assert impact["held"][0]["after"] == 0


def test_closing_asks_for_a_price_when_no_sale_emptied_it(tmp_path):
    db = tmp_path / "book.db"
    add_many(DUST[:1], db)
    drafted = book.draft(Action("close_position", "CAT-EUR", {}), db=db,
                         translate=_translate, resolve=lambda s: s)
    assert drafted.book is None and "price" in drafted.text


def test_closing_what_the_book_no_longer_holds_proposes_nothing(tmp_path):
    db = tmp_path / "book.db"
    add_many([*DUST, Transaction("2026-06-18", "CAT-EUR", "sell", 440266.1798,
                                 1e-6, "EUR", 0.0, "revolut crypto CAT")], db)
    drafted = book.draft(Action("close_position", "CAT-EUR", {}), db=db,
                         translate=_translate, resolve=lambda s: s)
    assert drafted.book is None and "no CAT-EUR" in drafted.text


def test_closing_finds_the_pair_under_its_bare_symbol(tmp_path):
    # "ciérrala" said CAT, the book says CAT-EUR (and the other way round).
    db = tmp_path / "book.db"
    add_many([replace(t, note="kraken CAT") for t in DUST], db)
    for said in ("CAT", "CAT-EUR"):
        drafted = book.draft(Action("close_position", said, {}), db=db,
                             translate=_translate, resolve=lambda s: s)
        assert drafted.book is not None, said


def test_closing_an_unknown_symbol_lists_the_closest_held(tmp_path):
    db = tmp_path / "book.db"
    add_many([*BOOK[:1], Transaction("2026-08-20", "CATX", "buy", 3, 5.0,
                                     "EUR", 0.0, "ibkr")], db)
    drafted = book.draft(Action("close_position", "CATT", {}), db=db,
                         translate=_translate, resolve=lambda s: s)
    assert drafted.book is None
    assert "CATX" in drafted.text and "nothing to close" not in drafted.text


def test_close_wording_reaches_the_action_classifier():
    assert tools.maybe_action("ya no tengo CAT, ciérrala")
    assert tools.maybe_action("I sold all my CAT, close it")


def test_a_bare_symbol_does_not_select_the_coin_when_the_stock_is_held():
    stock = Transaction("2026-08-20", "CAT", "buy", 2, 300.0, "USD", 0.0, "ibkr")
    coin = Transaction("2026-08-21", "CAT-EUR", "buy", 100, 0.01, "EUR", 0.0,
                       "kraken CAT")
    picked = edits.select([stock, coin], edits.Selector(ticker="CAT"))
    assert [t.ticker for t in picked] == ["CAT"]
    picked = edits.select([coin], edits.Selector(ticker="CAT"))
    assert [t.ticker for t in picked] == ["CAT-EUR"]


def test_close_price_questions_do_not_wake_the_action_classifier():
    assert not tools.maybe_action("what was NVDA's close price yesterday?")
