"""A first trade typed in the chat counts like a first real import.

The demo book is borrowed for looking: the first row the reader brings must
clear it, and the funnel's `import.committed` must mark it `first` — whether
it came as a statement or as "he comprado 10 NVDA a 120".
"""

from __future__ import annotations

from unittest import mock

from stocks.chat import book
from stocks.chat.tools import Action
from stocks.portfolio import demo
from stocks.portfolio.ledger import all_transactions

BUY = Action(
    "add_transaction",
    "NVDA",
    {"trade": "buy", "quantity": 10, "price": 120, "date": "2024-03-01"},
)


def _tr(key, **kw):
    return key


def _typed(db, act=BUY):
    drafted = book.draft(act, db=db, translate=_tr, today="2026-10-23")
    assert drafted.book is not None
    offer = {"book": drafted.book}
    with mock.patch.object(book.obs, "event") as event:
        book.apply(offer, db=db, source="chat", translate=_tr)
    return event


def test_the_first_typed_trade_clears_the_demo_and_is_the_first_import(tmp_path):
    db = tmp_path / "ledger.db"
    demo.seed(db)
    assert demo.active(db) and not demo.has_real(db)

    event = _typed(db)

    assert not demo.active(db)
    assert [t.ticker for t in all_transactions(db)] == ["NVDA"]
    event.assert_called_once()
    name, fields = event.call_args.args[0], event.call_args.kwargs
    assert name == "import.committed"
    assert fields["first"] is True and fields["n"] == 1 and fields["via"] == "chat-book"


def test_the_second_typed_trade_is_not_a_first(tmp_path):
    db = tmp_path / "ledger.db"
    demo.seed(db)
    _typed(db)

    second = Action(
        "add_transaction",
        "MSFT",
        {"trade": "buy", "quantity": 2, "price": 400, "date": "2024-04-01"},
    )
    event = _typed(db, second)

    assert event.call_args.kwargs["first"] is False
    assert {t.ticker for t in all_transactions(db)} == {"NVDA", "MSFT"}
