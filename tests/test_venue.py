"""Which listing a bare non-dollar broker code was traded on.

Pure: Yahoo is four callables a test hands over — does it quote the code,
which venues the search offers, what each closed on a day, and the dollar's
rate that day. `pick` is imported here, at module level, because the suite's
conftest keeps every import's codes as printed by replacing `venue.pick` for
the run of each test.
"""

from __future__ import annotations

import pytest

from stocks.portfolio import venue
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.venue import pick


def buy(ticker, price, currency="EUR", day="2025-03-03", qty=1.0):
    return Transaction(day, ticker, "buy", qty, price, currency, 0.0, "revolut")


def closes(table):
    """close(symbol, day) from {(symbol, day): close}; anything else None."""
    asked = []

    def close(symbol, day):
        asked.append((symbol, day))
        return table.get((symbol, day))

    close.asked = asked
    return close


def yes(code):
    return True


def offer(*symbols):
    return lambda code, currency: list(symbols)


def no_rate(currency, day):
    return None


def rate(value):
    """usd_rate at one dollar rate on every day; records what it was asked."""
    asked = []

    def usd_rate(currency, day):
        asked.append(currency)
        return value

    usd_rate.asked = asked
    return usd_rate


# ---------------------------------------------------------------- the pick


def test_a_euro_alv_is_allianz_when_the_price_says_so():
    rows = [buy("ALV", 248.6)]
    got = pick(
        ("ALV", "EUR"), rows, [],
        quoted=yes,
        candidates=offer("ALV.DE", "ALV.F"),
        close=closes({("ALV.DE", "2025-03-03"): 249.1}),
        usd_rate=no_rate,
    )
    assert got == "ALV.DE"


def test_the_price_tells_santander_from_sanofi():
    # The search offers Sanofi first; a 5-euro fill is not a 90-euro share.
    rows = [buy("SAN", 5.12)]
    close = closes({
        ("SAN.PA", "2025-03-03"): 91.4,
        ("SAN.MC", "2025-03-03"): 5.08,
    })
    got = pick(
        ("SAN", "EUR"), rows, [],
        quoted=yes, candidates=offer("SAN.PA", "SAN.DE", "SAN.MC"), close=close,
        usd_rate=no_rate,
    )
    assert got == "SAN.MC"
    assert ("SAN.PA", "2025-03-03") in close.asked


def test_the_first_venue_the_price_agrees_with_wins():
    rows = [buy("SAP", 180.0)]
    got = pick(
        ("SAP", "EUR"), rows, [],
        quoted=yes,
        candidates=offer("SAP.DE", "SAP.F"),
        close=closes({("SAP.DE", "2025-03-03"): 181.0, ("SAP.F", "2025-03-03"): 180.5}),
        usd_rate=no_rate,
    )
    assert got == "SAP.DE"


def test_every_sampled_day_has_to_agree():
    rows = [buy("ALV", 248.6, day="2025-03-03"), buy("ALV", 30.0, day="2025-04-01")]
    got = pick(
        ("ALV", "EUR"), rows, [],
        quoted=yes,
        candidates=offer("ALV.DE"),
        close=closes({
            ("ALV.DE", "2025-03-03"): 249.1,
            ("ALV.DE", "2025-04-01"): 260.0,
        }),
        usd_rate=no_rate,
    )
    assert got is None


def test_no_close_anywhere_keeps_the_code_as_printed():
    # Throttled, or the venue has no history that day: no evidence, no verdict.
    got = pick(
        ("ALV", "EUR"), [buy("ALV", 248.6)], [],
        quoted=yes, candidates=offer("ALV.DE", "ALV.F"), close=closes({}),
        usd_rate=no_rate,
    )
    assert got is None


def test_a_code_yahoo_does_not_quote_bare_is_not_searched_here():
    # That case is `symbols.symbol_for_code`'s (SIE -> SIE.DE), which caches.
    def never(code, currency):
        raise AssertionError("searched")

    got = pick(
        ("SIE", "EUR"), [buy("SIE", 180.0)], [],
        quoted=lambda code: False, candidates=never, close=closes({}),
        usd_rate=no_rate,
    )
    assert got is None


def test_a_label_the_book_already_uses_is_tried_first_and_proven_by_price():
    # ClickTrade booked ALV.DE; the Revolut "ALV" joins it without a search,
    # and without asking whether the bare line explains the fill too.
    prior = [buy("ALV.DE", 240.0, day="2025-01-02")]
    rows = [buy("ALV", 248.6)]

    def never(*a):
        raise AssertionError("asked Yahoo about the bare code")

    got = pick(
        ("ALV", "EUR"), rows, prior,
        quoted=never,
        candidates=offer(),
        close=closes({("ALV.DE", "2025-03-03"): 249.1}),
        usd_rate=never,
    )
    assert got == "ALV.DE"


def test_a_fill_the_book_already_holds_needs_no_price():
    # The same statement imported again while Yahoo is throttled: the fill
    # booked under ALV.DE is this one, to the share and the cent.
    prior = [buy("ALV.DE", 248.6, qty=2.0)]
    again = [buy("ALV", 248.6, qty=2.0)]
    got = pick(
        ("ALV", "EUR"), again, prior,
        quoted=yes, candidates=offer(), close=closes({}), usd_rate=no_rate,
    )
    assert got == "ALV.DE"
    other = [buy("ALV", 248.6, qty=3.0)]
    assert pick(
        ("ALV", "EUR"), other, prior,
        quoted=yes, candidates=offer(), close=closes({}), usd_rate=no_rate,
    ) is None


def test_a_label_the_book_uses_is_no_evidence_by_itself():
    # ClickTrade's SAN.PA is Sanofi; Revolut's 5-euro SAN is not.
    prior = [buy("SAN.PA", 90.0, day="2025-01-02")]
    rows = [buy("SAN", 5.12)]
    close = closes({
        ("SAN.PA", "2025-03-03"): 91.4,
        ("SAN.MC", "2025-03-03"): 5.08,
    })
    got = pick(
        ("SAN", "EUR"), rows, prior,
        quoted=yes, candidates=offer("SAN.PA", "SAN.MC"), close=close,
        usd_rate=no_rate,
    )
    assert got == "SAN.MC"
    assert close.asked.count(("SAN.PA", "2025-03-03")) == 1  # not asked twice


def test_the_books_own_bare_rows_move_only_onto_a_label_it_uses():
    # Nothing new in this statement for ALV: the search is not this import's
    # question, only whether the label the book already has fits.
    prior = [buy("ALV", 248.6), buy("ALV.DE", 240.0, day="2025-01-02")]
    rows = [buy("SAP", 180.0)]

    def never(*a):
        raise AssertionError("searched")

    assert pick(
        ("ALV", "EUR"), rows, prior,
        quoted=never, candidates=never, close=closes({}), usd_rate=never,
    ) is None


@pytest.mark.parametrize(("price", "currency"), [(4.5, "GBP"), (450.0, "GBX")])
def test_london_pence_and_pounds_both_agree(price, currency):
    # Yahoo quotes .L in pence; brokers book either unit.
    got = pick(
        ("BARC", currency), [buy("BARC", price, currency)], [],
        quoted=yes,
        candidates=offer("BARC.L"),
        close=closes({("BARC.L", "2025-03-03"): 452.0}),
        usd_rate=no_rate,
    )
    assert got == "BARC.L"


# ------------------------------------------- the bare line explains it too


def test_a_us_share_booked_in_euros_stays_on_its_us_line():
    # 190 USD at 0.92 is 174.80 EUR: the fill is Apple's own line, converted,
    # whatever thin Milan mirror happens to print the same.
    got = pick(
        ("AAPL", "EUR"), [buy("AAPL", 175.0)], [],
        quoted=yes,
        candidates=offer("AAPL.MI"),
        close=closes({
            ("AAPL.MI", "2025-03-03"): 176.0,
            ("AAPL", "2025-03-03"): 190.0,
        }),
        usd_rate=rate(0.92),
    )
    assert got is None


def test_an_adr_trading_one_to_one_keeps_the_bare_line():
    # Santander's SAN is its own ADR, one share each: same company either way.
    got = pick(
        ("SAN", "EUR"), [buy("SAN", 5.12)], [],
        quoted=yes,
        candidates=offer("SAN.PA", "SAN.MC"),
        close=closes({
            ("SAN.PA", "2025-03-03"): 91.4,
            ("SAN.MC", "2025-03-03"): 5.08,
            ("SAN", "2025-03-03"): 5.55,
        }),
        usd_rate=rate(0.92),
    )
    assert got is None


def test_a_bare_line_that_is_another_company_holds_nothing_back():
    # Autoliv at 95 USD is 87 EUR; the 248.60 fill was Allianz.
    usd_rate = rate(0.92)
    got = pick(
        ("ALV", "EUR"), [buy("ALV", 248.6)], [],
        quoted=yes,
        candidates=offer("ALV.DE"),
        close=closes({
            ("ALV.DE", "2025-03-03"): 249.1,
            ("ALV", "2025-03-03"): 95.0,
        }),
        usd_rate=usd_rate,
    )
    assert got == "ALV.DE"
    assert usd_rate.asked == ["EUR"]


@pytest.mark.parametrize(
    ("bare", "usd_rate"),
    [(190.0, no_rate), (None, rate(0.92))],
    ids=["no-rate", "no-dollar-close"],
)
def test_a_bare_line_that_cannot_be_priced_holds_nothing_back(bare, usd_rate):
    # Unknown is not "explains it": the venue's own price already did.
    table = {("AAPL.MI", "2025-03-03"): 176.0}
    if bare is not None:
        table[("AAPL", "2025-03-03")] = bare
    got = pick(
        ("AAPL", "EUR"), [buy("AAPL", 175.0)], [],
        quoted=yes, candidates=offer("AAPL.MI"), close=closes(table),
        usd_rate=usd_rate,
    )
    assert got == "AAPL.MI"


def test_a_pence_fill_asks_for_the_pound():
    # Frankfurter publishes GBP, not GBX; `agrees` already scales by 100.
    usd_rate = rate(0.79)
    got = pick(
        ("BARC", "GBX"), [buy("BARC", 450.0, "GBX")], [],
        quoted=yes,
        candidates=offer("BARC.L"),
        close=closes({
            ("BARC.L", "2025-03-03"): 452.0,
            ("BARC", "2025-03-03"): 5.70,  # 4.50 GBP: the ADR, one share each
        }),
        usd_rate=usd_rate,
    )
    assert got is None
    assert usd_rate.asked == ["GBP"]


# ------------------------------------------------------- what is worth asking


def test_only_bare_non_dollar_codes_are_asked_about():
    rows = [
        buy("ALV", 248.6),
        buy("AAPL", 190.0, "USD"),
        buy("ALV.DE", 249.0),
        buy("BTC-EUR", 60_000.0),
        buy("DE0008404005", 248.6),
        buy("ALV", 95.0, "USD"),
        buy("ALV", 249.0, day="2025-03-04"),
    ]
    assert venue.keys(rows, []) == [("ALV", "EUR")]


def test_the_books_bare_codes_are_asked_about_only_when_a_label_claims_them():
    prior = [
        buy("ALV", 248.6),
        buy("SAP", 180.0),
        buy("SAP.DE", 181.0),
        buy("ASML", 600.0, "USD"),
    ]
    assert venue.keys([buy("NOVO", 100.0, "DKK")], prior) == [
        ("NOVO", "DKK"),
        ("SAP", "EUR"),
    ]


# ----------------------------------------------------------- moving the rows


def test_relabeled_moves_one_currency_and_leaves_the_other():
    rows = [buy("ALV", 248.6), buy("ALV", 95.0, "USD")]
    moved = venue.relabeled(rows, {("ALV", "EUR"): "ALV.DE"})
    assert [(t.ticker, t.currency) for t in moved] == [("ALV.DE", "EUR"), ("ALV", "USD")]
    assert rows[0].ticker == "ALV"  # copies, not the caller's rows


def test_a_statements_split_rows_follow_their_trades():
    skipped = [
        {"type": "STOCK SPLIT", "ticker": "alv", "currency": ""},
        {"type": "STOCK SPLIT", "ticker": "ALV", "currency": "USD"},
        {"type": "DIVIDEND", "ticker": "ALV", "currency": "EUR"},
    ]
    venue.relabel_skipped(skipped, {("ALV", "EUR"): "ALV.DE"})
    assert [s["ticker"] for s in skipped] == ["ALV.DE", "ALV", "ALV"]
