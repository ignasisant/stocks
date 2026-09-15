"""Income a book is owed whether or not a statement ever said so.

Every test here is offline: the share timeline comes from the ledger and the
per-share history is handed in, so the only thing under test is the arithmetic
of entitlement — who held what the day before each ex-date.
"""

from __future__ import annotations

from datetime import date

import pytest

from stocks.data.dividends import DividendHistory
from stocks.portfolio import dividends as dv
from stocks.portfolio.ledger import Transaction

# Identity converter: 1 unit of anything is 1 unit of base, so the tests read
# as the shares × per-share arithmetic they are about.
SAME = lambda amount, ccy, day: amount  # noqa: E731
# A fixed rate, to prove the ex-date (not today) is what gets converted.
HALF = lambda amount, ccy, day: amount * (0.5 if ccy == "USD" else 1.0)  # noqa: E731


def tx(day, ticker, action, quantity=0.0, price=0.0, ccy="USD", tid=1):
    return Transaction(
        date=day, ticker=ticker, action=action, quantity=quantity,
        price=price, currency=ccy, id=tid,
    )


KO = DividendHistory(
    "KO",
    (("2024-03-14", 0.48), ("2024-06-13", 0.48), ("2025-03-14", 0.51)),
    "USD",
)


def test_shares_before_is_strict_the_buyer_on_the_ex_date_gets_nothing():
    book = [tx("2024-03-14", "KO", "buy", 100)]
    payments = dv.estimate_payments(book, {"KO": KO}, until="2025-12-31")
    # Bought ON the 14th: the March payment is the seller's, the June one ours.
    assert [(p.ex_date, p.shares) for p in payments] == [
        ("2024-06-13", 100.0),
        ("2025-03-14", 100.0),
    ]


def test_a_sale_stops_the_entitlement():
    book = [
        tx("2024-01-02", "KO", "buy", 100, tid=1),
        tx("2024-04-01", "KO", "sell", 60, tid=2),
        tx("2025-01-05", "KO", "sell", 40, tid=3),
    ]
    payments = dv.estimate_payments(book, {"KO": KO}, until="2025-12-31")
    assert [(p.ex_date, p.shares) for p in payments] == [
        ("2024-03-14", 100.0),
        ("2024-06-13", 40.0),
    ]
    assert payments[0].gross == pytest.approx(48.0)


def test_a_split_puts_both_sides_on_todays_shares():
    # Yahoo's per-share history is split-adjusted, so the ledger's quantities
    # have to be too: 10 shares bought before a 4:1 split are 40 today, and the
    # pre-split payment is quoted per post-split share.
    book = [
        tx("2024-01-02", "AAPL", "buy", 10, tid=1),
        tx("2024-05-01", "AAPL", "split", quantity=4, tid=2),
    ]
    history = DividendHistory("AAPL", (("2024-02-09", 0.06),), "USD")
    (payment,) = dv.estimate_payments(book, {"AAPL": history}, until="2024-12-31")
    assert payment.shares == 40.0
    assert payment.gross == pytest.approx(2.4)


def test_payments_after_until_belong_to_the_forecast():
    book = [tx("2023-01-02", "KO", "buy", 100)]
    payments = dv.estimate_payments(book, {"KO": KO}, until="2024-12-31")
    assert [p.ex_date for p in payments] == ["2024-03-14", "2024-06-13"]


def test_estimate_by_year_converts_at_the_ex_date_and_splits_by_ticker():
    book = [
        tx("2023-01-02", "KO", "buy", 100, tid=1),
        tx("2023-01-02", "SAN.MC", "buy", 200, ccy="EUR", tid=2),
    ]
    histories = {
        "KO": KO,
        "SAN.MC": DividendHistory("SAN.MC", (("2024-04-29", 0.10),), "EUR"),
    }
    payments = dv.estimate_payments(book, histories, until="2024-12-31")
    years = dv.estimate_by_year(payments, to_base=HALF)
    assert years[2024].by_ticker["KO"] == pytest.approx(48.0)  # 96 USD at 0.5
    assert years[2024].by_ticker["SAN.MC"] == pytest.approx(20.0)
    assert years[2024].gross == pytest.approx(68.0)


def test_history_currency_wins_over_the_trade_currency():
    # A broker that books a US trade in the account's currency doesn't change
    # what the dividend is declared in.
    book = [tx("2023-01-02", "KO", "buy", 100, ccy="EUR")]
    (payment,) = dv.estimate_payments(
        book, {"KO": DividendHistory("KO", (("2024-03-14", 0.48),), "USD")},
        until="2024-12-31",
    )
    assert payment.currency == "USD"
    # …and with no metadata, the ledger's own currency is the fallback.
    (fallback,) = dv.estimate_payments(
        book, {"KO": DividendHistory("KO", (("2024-03-14", 0.48),), None)},
        until="2024-12-31",
    )
    assert fallback.currency == "EUR"


def test_unrecorded_compares_per_ticker_not_per_year():
    book = [
        tx("2023-01-02", "KO", "buy", 100, tid=1),
        tx("2023-01-02", "PG", "buy", 100, tid=2),
        # Only KO's dividend was ever imported — and generously.
        tx("2024-03-20", "KO", "dividend", price=60.0, tid=3),
    ]
    histories = {
        "KO": DividendHistory("KO", (("2024-03-14", 0.48),), "USD"),
        "PG": DividendHistory("PG", (("2024-04-18", 1.00),), "USD"),
    }
    imported = dv.by_year(book, to_base=SAME)
    estimated = dv.estimate_by_year(
        dv.estimate_payments(book, histories, until="2024-12-31"), to_base=SAME
    )
    # KO's 12 of surplus must not cancel PG's missing 100.
    assert dv.unrecorded_by_year(imported, estimated) == {2024: pytest.approx(100.0)}


def test_forward_income_is_the_trailing_year_on_todays_shares():
    book = [
        tx("2023-01-02", "KO", "buy", 100, tid=1),
        tx("2026-01-05", "SOLD", "buy", 50, tid=2),
        tx("2026-02-05", "SOLD", "sell", 50, tid=3),
    ]
    histories = {
        "KO": DividendHistory(
            "KO",
            (
                ("2025-06-13", 0.51),   # outside the window
                ("2025-09-12", 0.51),
                ("2025-12-12", 0.51),
                ("2026-03-13", 0.53),
                ("2026-06-12", 0.53),
            ),
            "USD",
        ),
        "SOLD": DividendHistory("SOLD", (("2026-05-01", 2.00),), "USD"),
    }
    forward = dv.forward_income(book, histories, ref="2026-09-01")
    assert [f.ticker for f in forward] == ["KO"]  # nothing held, nothing owed
    (ko,) = forward
    assert ko.payments == 4
    assert ko.per_share == pytest.approx(2.08)
    assert ko.gross == pytest.approx(208.0)
    assert ko.last_ex == "2026-06-12"
    assert dv.forward_totals(forward, to_base=HALF, ref="2026-09-01") == {
        "KO": pytest.approx(104.0)
    }


def test_shares_bought_today_still_count_as_held():
    book = [tx("2026-09-01", "KO", "buy", 10)]
    forward = dv.forward_income(
        book, {"KO": DividendHistory("KO", (("2026-06-12", 0.53),), "USD")},
        ref="2026-09-01",
    )
    assert forward and forward[0].shares == 10.0


def test_trailing_window_helpers_match_the_estimate():
    ref = date(2026, 9, 1)
    history = DividendHistory(
        "KO", (("2025-08-30", 0.51), ("2025-09-12", 0.51), ("2026-06-12", 0.53)), "USD"
    )
    assert history.trailing(ref) == pytest.approx(1.04)  # the 2025-08-30 one is out
    assert history.trailing_count(ref) == 2


def test_no_history_means_no_estimate_rather_than_a_zero_row():
    book = [tx("2023-01-02", "BRK-B", "buy", 10)]
    assert dv.estimate_payments(book, {}, until="2026-01-01") == []
    assert dv.forward_income(book, {}, ref="2026-01-01") == []
