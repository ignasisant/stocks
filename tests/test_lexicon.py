"""Dates and action words in the language the export was downloaded in.

These two lookups are what decides whether a statement imports at all, and
both used to be English-only: `3 abr 2025` and `Compra` are the reason a
whole Spanish export came back as "no parser recognised this file".
"""

import pytest

from stocks.portfolio import lexicon


@pytest.mark.parametrize("cell,expected", [
    ("2025-03-04T09:12:00.000Z", "2025-03-04"),  # ISO timestamp
    ("2025-3-4", "2025-03-04"),
    ("2025/06/01", "2025-06-01"),                # four-digit head is the year
    ("3 feb 2025 09:21:06", "2025-02-03"),       # es, and en by coincidence
    ("26 ene 2026 10:44:36", "2026-01-26"),      # es only
    ("3 abr 2025 19:55:12", "2025-04-03"),
    ("4 ago 2025 08:14:19", "2025-08-04"),
    ("7 dic 2025 07:59:55", "2025-12-07"),
    ("1 sept 2025 08:25:34", "2025-09-01"),
    ("1 març 2026", "2026-03-01"),               # ca, accented
    ("5 out 2025", "2025-10-05"),                # pt
    ("2 mai 2025", "2025-05-02"),                # fr
    ("3 de febrero de 2025", "2025-02-03"),
    ("Jan 5, 2025, 2:31:41 PM", "2025-01-05"),   # month first, 12-hour clock
    ("lun, 3 feb 2025", "2025-02-03"),           # weekday is decoration
    ("31.12.2025", "2025-12-31"),
    ("13/12/2025 10:00", "2025-12-13"),          # day > 12 settles the order
    ("12/31/2025", "2025-12-31"),                # so does month > 12
    ("03/04/24", "2024-04-03"),                  # ambiguous: day first
])
def test_dates_in_every_shape_a_broker_prints(cell, expected):
    assert lexicon.iso_date(cell) == expected


def test_ambiguous_numeric_date_can_be_read_month_first():
    assert lexicon.iso_date("03/04/24", dayfirst=False) == "2024-03-04"


@pytest.mark.parametrize("cell", ["", "   ", "n/a", "AAPL", "45 feb 2025",
                                  "2025-13-40"])
def test_a_cell_that_is_not_a_date_is_refused(cell):
    assert lexicon.readable_date(cell) is None
    with pytest.raises(lexicon.DateUnreadable):
        lexicon.iso_date(cell)


@pytest.mark.parametrize("cell,action", [
    ("Buy", "buy"),
    ("BUY - MARKET", "buy"),
    ("Compra", "buy"),
    ("YOU BOUGHT PROSHARES ULTRAPRO QQQ (TQQQ)", "buy"),
    ("Achat", "buy"),
    ("Kauf", "buy"),
    ("Venta", "sell"),
    ("SELL - STOP", "sell"),
    ("Venda", "sell"),
    ("Verkauf", "sell"),
    ("Dividendo", "dividend"),
    ("Comisión", "fee"),          # accents are stripped before matching
    ("Stock split", "split"),
])
def test_the_words_a_type_column_uses(cell, action):
    assert lexicon.action_of(cell) == action


@pytest.mark.parametrize("cell", [
    "", "Traspaso", "Staking", "Recompensa de staking", "Cash top-up",
    "Wholesale account",  # "sale" inside a word is not a sale
])
def test_a_type_this_module_has_nothing_to_say_about(cell):
    assert lexicon.action_of(cell) is None
