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

import pytest

from stocks import obs
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
