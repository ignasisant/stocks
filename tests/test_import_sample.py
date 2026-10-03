"""The shipped example statement.

A brand-new account has nothing to import, so every ledger-derived surface —
positions, P/L, risk, dividends, fees, tax — is empty until it does. The
example statement is how that account can see those surfaces working without
inventing a ledger: it is a real broker statement in the repo, parsed by the
real parser, validated and committed through the same `/import` routes as
any upload, and undone by the ordinary "clear last import".

What must not break: the file parses clean (a sample that errors is worse than
no sample) and it fills every one of those surfaces.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from stocks.portfolio import platforms
from stocks.portfolio.validate import validate

ASSETS = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web" / "assets"
REVOLUT = platforms.by_key("revolut")


# ------------------------------------------------------------------- the file


def test_exactly_one_platform_ships_a_sample():
    """One sample, on the platform whose columns the parser's tests pin.

    A sample has to track a real broker's export layout; every extra one is
    another layout to keep true, and a sample that has rotted teaches the
    reader that the importer is broken.
    """
    with_sample = [p for p in platforms.PLATFORMS if p.sample]
    assert [p.key for p in with_sample] == ["revolut"]
    assert (ASSETS / REVOLUT.sample).is_file()


@pytest.fixture
def parsed():
    return REVOLUT.parse(REVOLUT.sample, (ASSETS / REVOLUT.sample).read_bytes())


def test_the_sample_parses_and_validates_without_a_single_rejection(parsed):
    checked = validate(parsed, [], known=set(), lookup=lambda t: True)
    assert len(checked.importable) == len(parsed.transactions)
    assert "0 rejected" in checked.summary
    assert "0 with warnings" in checked.summary


def test_the_sample_fills_every_surface_a_new_account_finds_empty(parsed):
    """One statement, and the whole ledger half of the app has content."""
    kinds = Counter(t.action for t in parsed.transactions)
    assert kinds["buy"] and kinds["sell"] and kinds["dividend"]  # positions,
    # realised gains + the tax report, and the dividends tab
    assert any(t.fee for t in parsed.transactions)  # the fees tab

    held: Counter[str] = Counter()
    for t in parsed.transactions:
        if t.action == "buy":
            held[t.ticker] += t.quantity
        elif t.action == "sell":
            held[t.ticker] -= t.quantity
    assert sum(1 for q in held.values() if q > 0) >= 4  # a basket to weigh
    assert any(q == 0 for q in held.values())  # a closed position to realise
    assert min(held.values()) >= 0, "an oversell would be rejected on import"

    years = {t.date[:4] for t in parsed.transactions if t.action == "sell"}
    assert len(years) > 1  # more than one tax year on the Realized tab
    span = {t.date[:4] for t in parsed.transactions}
    assert len(span) >= 3  # enough history for the return chart to have shape


def test_the_sample_keeps_a_skipped_row_to_show_what_is_not_imported(parsed):
    """The preview's honesty is a feature, so the sample demonstrates it."""
    assert parsed.skipped
    assert all(s.get("reason") for s in parsed.skipped)


def test_the_sample_is_attributed_to_the_broker_it_came_from(parsed):
    # fees.broker_of reads the note's first word; an unstamped batch lands
    # under whatever its notes happened to start with.
    assert {t.note.split()[0] for t in parsed.transactions} == {"revolut"}
