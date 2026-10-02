"""A buy-back blocks a loss only for as many shares as it bought.

Spain's two months, the US wash sale, Ireland's four weeks and Canada's
superficial loss all defer a loss when the same security is bought back around
the sale. None of them defers the whole loss when only part of it was bought
back: sell 100 at a loss, buy 10 back, and a tenth is deferred (US Treas. Reg.
1.1091-1(c); the proportion Spain's DGT applies to art. 33.5.f).

The engine used to know only *that* a buy-back happened, not how big it was,
so any repurchase inside the window deferred the entire loss. That errs on the
side of paying too much, which is why nothing flagged it — these tests pin the
proportional rule and the bookkeeping it needs: a replacement share blocks one
sold share and no other, a lot that left with the same disposal replaces
nothing, and a split between sale and buy-back is counted in like units.
"""

from __future__ import annotations

import pytest

from stocks.portfolio import tax
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.positions import RealizedSale, build
from stocks.portfolio.tax import us
from stocks.portfolio.tax.base import Acquisition, Split, months_window, repurchases

WINDOW = months_window(2)


def es_year(txs: list[Transaction], year: int):
    _, realized = build(txs, base="EUR", matching="fifo")
    return tax.get("es").fiscal_year(realized, year, tax.buy_dates(txs))


def buy(day: str, qty: float, price: float, ticker: str = "MSFT") -> Transaction:
    return Transaction(day, ticker, "buy", qty, price, "EUR", 0.0)


def sell(day: str, qty: float, price: float, ticker: str = "MSFT") -> Transaction:
    return Transaction(day, ticker, "sell", qty, price, "EUR", 0.0)


def test_a_partial_buy_back_defers_that_share_of_the_loss():
    """The ADBE case: 100 sold at a loss, 10 bought back, a tenth deferred."""
    ty = es_year(
        [
            buy("2024-01-02", 100, 50),
            sell("2025-03-03", 100, 40),
            buy("2025-03-20", 10, 41),
        ],
        2025,
    )
    assert ty.realized_loss == pytest.approx(1000)
    assert ty.disallowed_loss == pytest.approx(100)


def test_buying_back_as_many_or_more_defers_all_of_it():
    ty = es_year(
        [
            buy("2024-01-02", 10, 50),
            sell("2025-03-03", 10, 40),
            buy("2025-03-20", 25, 41),
        ],
        2025,
    )
    assert ty.disallowed_loss == pytest.approx(ty.realized_loss)


def test_the_buy_backs_inside_the_window_add_up():
    ty = es_year(
        [
            buy("2024-01-02", 10, 50),
            buy("2025-02-10", 3, 45),  # before the sale, inside two months
            sell("2025-03-03", 10, 40),  # FIFO: the 2024 lot, at a loss
            buy("2025-04-01", 4, 41),
            buy("2025-06-20", 5, 41),  # outside the window
        ],
        2025,
    )
    assert ty.disallowed_loss == pytest.approx(100 * 7 / 10)


def test_one_buy_back_is_not_spent_twice():
    """Two losses, one replacement big enough for one of them: the earlier sale
    claims it, the later one is deductible (1.1091-1(e))."""
    txs = [
        buy("2024-01-02", 10, 50),
        buy("2024-02-01", 10, 60),
        sell("2025-03-03", 10, 40),  # 2024-01 lot: -100
        sell("2025-03-17", 10, 40),  # 2024-02 lot: -200
        buy("2025-04-01", 10, 41),
    ]
    ty = es_year(txs, 2025)
    assert ty.realized_loss == pytest.approx(300)
    assert ty.disallowed_loss == pytest.approx(100)


def test_selling_the_replacement_frees_only_the_loss_it_blocked():
    txs = [
        buy("2024-01-02", 10, 50),
        buy("2024-02-01", 10, 60),
        sell("2025-03-03", 10, 40),
        sell("2025-03-17", 10, 40),
        buy("2025-04-01", 10, 41),
        sell("2026-05-04", 10, 45),
    ]
    assert es_year(txs, 2026).recovered_loss == pytest.approx(100)


def test_a_partial_block_comes_back_as_its_own_shares_are_sold():
    txs = [
        buy("2024-01-02", 100, 50),
        sell("2025-03-03", 100, 40),  # -1000, 10 shares' worth deferred
        buy("2025-03-20", 10, 41),
        sell("2026-02-02", 4, 45),
        sell("2027-02-01", 6, 45),
    ]
    assert es_year(txs, 2026).recovered_loss == pytest.approx(40)
    assert es_year(txs, 2027).recovered_loss == pytest.approx(60)


def test_a_lot_sold_in_the_same_disposal_replaces_nothing():
    """Bought twice, sold all at once: the second lot is newer than the first
    and inside the window, but it went out with the sale — nothing was bought
    back, so nothing is deferred."""
    ty = es_year(
        [
            buy("2025-01-02", 10, 100),
            buy("2025-02-03", 10, 100),
            sell("2025-02-17", 20, 60),
        ],
        2025,
    )
    assert ty.realized_loss == pytest.approx(800)
    assert ty.disallowed_loss == pytest.approx(0)


def test_only_what_stays_of_that_lot_is_a_buy_back():
    txs = [
        buy("2025-01-02", 10, 100),
        buy("2025-02-03", 15, 100),
        sell("2025-02-17", 20, 60),  # both lots, 5 of the February one stay
    ]
    ty = es_year(txs, 2025)
    assert ty.realized_loss == pytest.approx(800)
    assert ty.disallowed_loss == pytest.approx(400 * 5 / 10)  # on the January lot


def test_a_buy_back_before_a_split_counts_in_the_sale_s_units():
    """1 share bought before a 10:1 split is 10 of the shares sold after it —
    counted raw it would defer a tenth of what it should."""
    txs = [
        buy("2024-01-02", 10, 100),
        buy("2024-05-20", 1, 100),
        Transaction("2024-06-10", "MSFT", "split", 10, 0.0, "EUR", 0.0),
        sell("2024-07-01", 100, 6),  # FIFO: the January lot, -400
    ]
    ty = es_year(txs, 2024)
    assert ty.realized_loss == pytest.approx(400)
    assert ty.disallowed_loss == pytest.approx(40)


def test_a_buy_back_after_a_split_counts_in_the_sale_s_units():
    txs = [
        buy("2024-01-02", 10, 100),
        sell("2024-05-02", 5, 60),  # -200, before the split
        Transaction("2024-06-10", "MSFT", "split", 10, 0.0, "EUR", 0.0),
        buy("2024-06-20", 10, 6),  # 1 pre-split share's worth
    ]
    ty = es_year(txs, 2024)
    assert ty.disallowed_loss == pytest.approx(200 / 5)


def test_a_bare_date_is_a_buy_back_of_unknown_size_and_blocks_it_all():
    """What a hand-built map of dates alone means: the old all-or-nothing rule."""
    s = RealizedSale("MSFT", "2024-01-02", "2025-03-03", 100, 5000, 4000, "EUR")
    assert repurchases([s], {"MSFT": ["2025-03-20"]}, WINDOW).disallowed(s) == 1000
    sized = {"MSFT": [Acquisition("2025-03-20", 10)]}
    assert repurchases([s], sized, WINDOW).disallowed(s) == pytest.approx(100)


def test_a_split_entry_is_no_acquisition():
    s = RealizedSale("MSFT", "2024-01-02", "2025-03-03", 10, 500, 400, "EUR")
    split_only = {"MSFT": [Split("2025-03-20", 2)]}
    assert repurchases([s], split_only, WINDOW).disallowed(s) == 0


def test_the_wash_sale_is_pro_rata_too_and_keeps_its_character():
    realized = [
        RealizedSale("AAPL", "2025-01-02", "2025-03-03", 100, 5000, 4000, "USD"),
        RealizedSale("AAPL", "2025-03-20", "2025-09-02", 25, 1000, 1100, "USD"),
    ]
    period = us.fiscal_period(
        realized,
        "2025",
        {"AAPL": [Acquisition("2025-01-02", 100), Acquisition("2025-03-20", 25)]},
    )
    assert period.short_disallowed == pytest.approx(250)
    assert period.long_disallowed == 0
    assert period.short_recovered == pytest.approx(250)


def test_ireland_and_canada_defer_the_same_proportion():
    loss = RealizedSale("X", "2024-01-02", "2025-03-03", 100, 5000, 4000, "EUR")
    buys = {"X": [Acquisition("2024-01-02", 100), Acquisition("2025-03-10", 20)]}
    assert tax.get("ie").fiscal_year([loss], 2025, buys).disallowed_loss == pytest.approx(
        200
    )
    ca_loss = RealizedSale(
        "X", "2024-01-02", "2025-03-03", 100, 5000, 4000, "CAD", "average"
    )
    assert tax.get("ca").fiscal_year(
        [ca_loss], 2025, buys
    ).disallowed_loss == pytest.approx(200)


# ---------------------------------------------------------------- open windows
# The forward half the calendar draws: which loss sales a buy-back would still
# block, and the first day it no longer would.


def es_windows(txs: list[Transaction], today: str):
    from datetime import date

    _, realized = build(txs, base="EUR", matching="fifo")
    return tax.get("es").open_windows(
        realized, tax.buy_dates(txs), date.fromisoformat(today)
    )


def test_window_end_is_the_first_day_past_each_rule():
    from datetime import date

    from stocks.portfolio.tax.base import window_end

    sold = date(2025, 12, 31)
    assert window_end(sold, "2m") == date(2026, 3, 1)  # 28 Feb is still inside
    assert window_end(sold, "30d") == date(2026, 1, 31)
    assert window_end(sold, "28d") == date(2026, 1, 29)
    assert window_end(sold, "") is None and window_end(sold, "6w") is None


def test_an_open_window_carries_the_loss_a_buy_back_would_block():
    (window,) = es_windows(
        [buy("2024-01-02", 10, 50), sell("2025-03-03", 10, 40)], "2025-03-20"
    )
    assert window.ticker == "MSFT" and str(window.sold) == "2025-03-03"
    assert str(window.clears) == "2025-05-04"
    assert window.loss == pytest.approx(100)


def test_parcels_sold_the_same_day_are_one_window():
    (window,) = es_windows(
        [
            buy("2024-01-02", 5, 50),
            buy("2024-06-03", 5, 60),
            sell("2025-03-03", 10, 40),
        ],
        "2025-03-20",
    )
    assert window.loss == pytest.approx(150)


def test_a_partial_buy_back_leaves_only_the_rest_exposed():
    (window,) = es_windows(
        [
            buy("2024-01-02", 100, 50),
            sell("2025-03-03", 100, 40),
            buy("2025-03-20", 10, 41),
        ],
        "2025-03-25",
    )
    assert window.loss == pytest.approx(900)


def test_a_closed_window_a_full_buy_back_and_a_gain_mark_nothing():
    closed = [buy("2024-01-02", 10, 50), sell("2025-03-03", 10, 40)]
    assert es_windows(closed, "2025-05-05") == []
    blocked = closed + [buy("2025-03-10", 10, 41)]
    assert es_windows(blocked, "2025-03-20") == []
    gain = [buy("2024-01-02", 10, 50), sell("2025-03-03", 10, 60)]
    assert es_windows(gain, "2025-03-20") == []


def test_a_country_without_the_rule_has_no_windows():
    from datetime import date

    txs = [buy("2024-01-02", 10, 50), sell("2025-03-03", 10, 40)]
    _, realized = build(txs, base="EUR", matching="fifo")
    for code in ("de", "uk"):
        assert tax.get(code).open_windows(
            realized, tax.buy_dates(txs), date(2025, 3, 20)
        ) == []
