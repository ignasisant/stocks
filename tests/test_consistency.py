"""`data.inconsistency`: every contradiction a book carries, said once to us.

The detectors already existed and each told the reader; what is tested here
is that each one also leaves the line we can count (`stocks logs stats
--event data.inconsistency --by kind`), once per account and finding, and
that the line carries the shape of the contradiction and nothing of the book.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import get_args

import pandas as pd
import pytest

from stocks import obs
from stocks.analysis.portfolio import _audit_twr, plausible_closes
from stocks.portfolio import consistency, corporate, doctor, positions
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.statement import ParseResult, check_consistency
from stocks.portfolio.validate import validate

# What would be the reader's book, not a contradiction's shape.
PRIVATE = {"price", "quantity", "amount", "held", "cost", "value", "fee"}


@pytest.fixture
def lines(monkeypatch) -> list[dict]:
    said: list[dict] = []

    def warn(name, **fields):
        if name == consistency.EVENT:
            said.append(fields)

    monkeypatch.setattr(obs, "warn", warn)
    return said


def same_currency(amount, currency, day):
    return amount


def test_a_contradiction_is_said_once_per_account(lines):
    with obs.context(user="a"):
        assert consistency.report("oversold", source="replay", ticker="AMZN", key="d")
        assert not consistency.report("oversold", source="replay", ticker="AMZN", key="d")
    with obs.context(user="b"):
        assert consistency.report("oversold", source="replay", ticker="AMZN", key="d")
    assert [line["kind"] for line in lines] == ["oversold", "oversold"]
    assert lines[0] == {"kind": "oversold", "source": "replay", "ticker": "AMZN"}


def test_a_broken_log_never_breaks_the_caller(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("sink down")

    monkeypatch.setattr(obs, "warn", boom)
    assert consistency.report("duplicate", source="doctor") is False


def test_the_missing_amazon_split_is_said_with_its_ratio_not_its_price(lines):
    book = [Transaction("2022-05-24", "AMZN", "buy", 1.0, 2050.0, "USD")]
    corporate.missing_splits(
        book,
        splits=lambda t: [("2022-06-06", 20.0)],
        close_on=lambda t, d: 104.10,
        source="page",
    )
    [line] = lines
    assert line["kind"] == "split_missing" and line["source"] == "page"
    assert (line["ticker"], line["split"], line["ratio"]) == ("AMZN", "2022-06-06", 20.0)
    assert line["off"] == pytest.approx(19.69, abs=0.01)
    assert not PRIVATE & set(line)


def test_a_replay_that_trips_on_a_sale_says_so_before_raising(lines):
    book = [
        Transaction("2025-01-02", "MSFT", "buy", 5, 400.0, "USD"),
        Transaction("2025-03-02", "MSFT", "sell", 10, 420.0, "USD"),
    ]
    with pytest.raises(ValueError, match="exceeds held"):
        positions.build(book, to_base=same_currency, base="USD")
    [line] = lines
    assert (line["kind"], line["source"], line["over"]) == ("oversold", "replay", 2.0)


@pytest.mark.parametrize("matching", ["average", "s104"])
def test_every_matching_rule_says_it(lines, matching):
    book = [
        Transaction("2025-01-02", "MSFT", "buy", 5, 400.0, "USD"),
        Transaction("2025-03-02", "MSFT", "sell", 10, 420.0, "USD"),
    ]
    with pytest.raises(ValueError):
        positions.build(book, to_base=same_currency, base="USD", matching=matching)
    assert [line["kind"] for line in lines] == ["oversold"]


def test_an_import_selling_what_the_book_never_had_is_said(lines):
    batch = ParseResult(
        transactions=[Transaction("2025-03-02", "AAPL", "sell", 3, 200.0, "USD")]
    )
    validate(batch, [], known={"AAPL"}, today=date(2026, 1, 1))
    [line] = lines
    assert (line["kind"], line["source"], line["ticker"]) == (
        "oversold",
        "import",
        "AAPL",
    )
    assert line["over"] is None  # nothing held at all


def test_a_re_export_overlapping_the_book_is_not_a_contradiction(lines):
    trade = Transaction("2025-03-02", "AAPL", "buy", 3, 200.0, "USD")
    validate(
        ParseResult(transactions=[trade]), [trade], known={"AAPL"}, today=date(2026, 1, 1)
    )
    assert lines == []


def test_a_total_that_disagrees_with_its_row_is_said(lines):
    with pytest.raises(ValueError, match="inconsistent"):
        check_consistency("buy", 10, 100.0, 1500.0, ticker="NVDA")
    [line] = lines
    assert (line["kind"], line["ticker"], line["action"]) == (
        "amount_mismatch",
        "NVDA",
        "buy",
    )
    assert line["off"] == pytest.approx(0.667, abs=0.001)
    assert not PRIVATE & set(line)


def test_the_doctor_says_each_finding_under_the_shared_name(lines):
    trade = Transaction("2025-03-03", "AAPL", "buy", 4, 170.0, "USD", 1, "revolut")
    rows = [replace(trade, id=1), replace(trade, id=2, price=170.4, note="ibkr")]
    doctor.scan(rows)
    [line] = lines
    assert (line["kind"], line["source"], line["rows"]) == ("duplicate", "doctor", 2)


def test_every_doctor_kind_has_a_logged_name():
    assert set(doctor._LOGGED) == set(doctor.KINDS)
    assert set(doctor._LOGGED.values()) <= set(consistency.KINDS)


def test_the_kinds_are_the_literal():
    assert consistency.KINDS == get_args(consistency.Kind)
    assert len(set(consistency.KINDS)) == len(consistency.KINDS)


# ------------------------------------------------------------ a quote's day move


def test_a_day_move_is_measured_from_the_close(lines):
    assert consistency.day_move(110.0, 100.0) == pytest.approx(0.10)
    # A biotech's trial day: big, real, and under the bar.
    assert consistency.day_move(250.0, 100.0) == pytest.approx(1.5)
    assert lines == []


def test_a_jump_no_session_produces_is_said_and_past_ten_times_dropped(lines):
    # Three times the close: said, still shown — one happens now and then.
    assert consistency.day_move(300.0, 100.0, ticker="ACME") == pytest.approx(2.0)
    # Pence against pounds: said, and not shown as a day.
    assert consistency.day_move(12.5, 1250.0, ticker="VOD.L") is None
    assert [(ln["kind"], ln["ticker"], ln["source"], ln["off"]) for ln in lines] == [
        ("quote_jump", "ACME", "feed", 3.0),
        ("quote_jump", "VOD.L", "feed", 0.01),
    ]
    assert not any(PRIVATE & set(ln) for ln in lines)


def test_a_day_move_needs_both_sides(lines):
    assert consistency.day_move(None, 100.0) is None
    assert consistency.day_move(100.0, None) is None
    assert consistency.day_move(100.0, 0.0) is None
    assert lines == []


# ------------------------------------------------- units, calendar, value path


def _closes(start: str, end: str, price: float, skip: tuple[str, ...] = ()):
    days = pd.bdate_range(start, end)
    days = days[~days.isin(pd.to_datetime(list(skip)))]
    return pd.Series(price, index=days)


def test_the_hundred_band_is_the_unit_slip():
    assert consistency.unit_slip(100.0) and consistency.unit_slip(0.01)
    assert consistency.unit_slip(0.0125)
    # A 20:1 split and a doubling small cap are not a unit.
    assert not consistency.unit_slip(20.0) and not consistency.unit_slip(2.0)
    assert not consistency.unit_slip(None) and not consistency.unit_slip(0.0)


def test_a_fill_in_pence_booked_as_pounds_is_said(lines):
    book = [
        Transaction("2025-03-03", "VOD.L", "buy", 100, 0.75, "GBP"),
        Transaction("2025-03-10", "VOD.L", "buy", 100, 0.75, "GBP"),
        Transaction("2025-03-17", "VOD.L", "buy", 100, 75.0, "GBP"),
    ]
    closes = {"VOD.L": _closes("2025-03-01", "2025-03-31", 0.75)}
    kept = plausible_closes(closes, book, {"VOD.L": ("GBP", 1.0)})
    assert "VOD.L" in kept
    [line] = lines
    assert (line["kind"], line["source"], line["ticker"]) == (
        "currency_off",
        "replay",
        "VOD.L",
    )
    assert (line["n"], line["first"]) == (1, "2025-03-17")
    assert not PRIVATE & set(line)


def test_a_series_in_minor_units_is_said_and_dropped(lines):
    book = [Transaction("2025-03-03", "VOD.L", "buy", 100, 0.75, "GBP")]
    closes = {"VOD.L": _closes("2025-03-01", "2025-03-31", 75.0)}
    assert plausible_closes(closes, book, {"VOD.L": ("GBP", 1.0)}) == {}
    [line] = lines
    assert (line["kind"], line["off"], line["n"]) == ("currency_off", 100.0, 1)


def test_a_trade_on_a_day_the_market_was_shut_is_said(lines):
    book = [
        Transaction("2025-12-19", "AAPL", "buy", 1, 200.0, "USD"),
        # Christmas, a weekday with no bar.
        Transaction("2025-12-25", "AAPL", "buy", 1, 200.0, "USD"),
        # A Friday after-hours fill stamped Saturday in UTC: Friday's bar.
        Transaction("2025-12-20", "AAPL", "buy", 1, 200.0, "USD"),
        # Before the series starts: history the feed lacks, not a holiday.
        Transaction("2025-11-27", "AAPL", "buy", 1, 200.0, "USD"),
    ]
    closes = {"AAPL": _closes("2025-12-01", "2025-12-31", 200.0, skip=("2025-12-25",))}
    plausible_closes(closes, book, {"AAPL": ("USD", 1.0)})
    [line] = lines
    assert (line["kind"], line["n"], line["first"]) == (
        "trade_off_calendar",
        1,
        "2025-12-25",
    )


def test_crypto_trades_any_day(lines):
    book = [Transaction("2025-12-25", "BTC-EUR", "buy", 0.1, 90000.0, "EUR")]
    days = pd.date_range("2025-12-01", "2025-12-31")
    closes = {"BTC-EUR": pd.Series(90000.0, index=days)}
    plausible_closes(closes, book, {"BTC-EUR": ("EUR", 1.0)})
    assert lines == []


def test_a_book_that_triples_in_a_day_is_said_once_with_its_worst_day(lines):
    days = pd.bdate_range("2025-03-03", periods=5)
    twr = pd.Series([0.01, 2.5, -0.02, 0.0], index=days[1:])
    twr.attrs["dropped_days"] = [days[0]]
    _audit_twr(twr)
    [line] = lines
    assert (line["kind"], line["source"], line["n"], line["dropped"]) == (
        "twr_jump",
        "replay",
        1,
        1,
    )
    assert (line["day"], line["off"]) == ("2025-03-05", 3.5)
    assert not PRIVATE & set(line)


def test_an_ordinary_value_path_says_nothing(lines):
    twr = pd.Series([0.01, -0.03, 0.02], index=pd.bdate_range("2025-03-03", periods=3))
    twr.attrs["dropped_days"] = []
    _audit_twr(twr)
    assert lines == []


def test_a_buy_a_hundred_off_its_close_is_a_unit_not_a_wrong_name(lines):
    book = [Transaction("2025-03-03", "BP.L", "buy", 10, 480.0, "GBP")]
    corporate.missing_splits(
        book,
        splits=lambda t: [("2025-06-02", 2.0)],
        close_on=lambda t, d: 4.80,
        source="page",
    )
    [line] = lines
    assert (line["kind"], line["off"]) == ("currency_off", 100.0)


def test_the_doctor_says_why_a_book_does_not_balance(lines):
    rows = [
        Transaction("2025-01-02", "NVDA", "buy", 10, 100.0, "USD", 0, "ibkr", id=1),
        Transaction("2025-03-02", "NVDA", "sell", 40, 30.0, "USD", 0, "ibkr", id=2),
    ]
    doctor.scan(rows)
    [line] = [ln for ln in lines if ln["source"] == "doctor"]
    assert (line["kind"], line["cause"]) == ("oversold", "split")
