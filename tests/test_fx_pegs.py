"""Currencies the ECB does not quote, reached through a fixed peg.

The UAE dirham is the reason this exists: frankfurter answers 404 for a base
it has no series for, so without the peg a UAE filer's ledger could not be
replayed at all. No network — every fetch is stubbed.
"""

import pytest

from stocks.data import fx

AED_PER_USD = 3.6725


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Frankfurter stands in as a fixed USD/EUR world, and never sees AED."""
    asked: list[tuple[str, str]] = []

    def _rate_on(day, base, quote):
        asked.append((base, quote))
        rates = {("USD", "EUR"): 0.90, ("EUR", "USD"): 1 / 0.90}
        assert (base, quote) in rates, f"asked for an unquoted pair: {base}/{quote}"
        return rates[(base, quote)]

    monkeypatch.setattr(fx, "_cache", dict)
    monkeypatch.setattr(fx, "_save_cache", lambda cache: None)
    monkeypatch.setattr(
        fx, "_fetch", lambda url, quote: (_rate_on(None, *_pair(url)), "2025-06-02")
    )
    monkeypatch.setattr(fx, "_SPOT_CACHE", {})
    return asked


def _pair(url: str) -> tuple[str, str]:
    """(base, quote) out of a frankfurter URL."""
    base = url.split("base=")[1].split("&")[0]
    return base, url.split("symbols=")[1]


# --- the peg table ---

def test_the_dirham_is_pegged_to_the_dollar():
    assert fx.PEGS["AED"] == ("USD", AED_PER_USD)


def test_a_quoted_currency_resolves_to_itself():
    assert fx._peg("EUR") == ("EUR", 1.0)


# --- rate_on ---

def test_a_pegged_base_converts_through_its_anchor(no_network):
    # 1 AED buys 1/3.6725 USD, which buys 0.90 EUR of that.
    assert fx.rate_on("2025-06-02", "AED", "EUR") == pytest.approx(0.90 / AED_PER_USD)
    assert no_network == [("USD", "EUR")]  # the dirham was never asked for


def test_a_pegged_quote_converts_through_its_anchor(no_network):
    assert fx.rate_on("2025-06-02", "EUR", "AED") == pytest.approx(
        1 / 0.90 * AED_PER_USD
    )


def test_the_peg_itself_needs_no_request(no_network):
    assert fx.rate_on("2025-06-02", "USD", "AED") == pytest.approx(AED_PER_USD)
    assert fx.rate_on("2025-06-02", "AED", "USD") == pytest.approx(1 / AED_PER_USD)
    assert no_network == []  # both legs are the same anchor: nothing to fetch


def test_a_pegged_currency_against_itself_is_one(no_network):
    assert fx.rate_on("2025-06-02", "AED", "AED") == 1.0
    assert no_network == []


def test_the_round_trip_comes_back(no_network):
    there = fx.rate_on("2025-06-02", "AED", "EUR")
    back = fx.rate_on("2025-06-02", "EUR", "AED")
    assert there * back == pytest.approx(1.0)


# --- to_base, the entry point every replay uses ---

def test_a_ledger_amount_converts_into_dirhams(no_network):
    # A 1,000 USD trade is 3,672.50 AED at the peg, whatever the day.
    assert fx.to_base(1_000, "USD", "2025-06-02", "AED") == pytest.approx(3_672.5)


def test_an_unquoted_base_no_longer_breaks_the_replay(no_network):
    # This is the regression: to_base(..., base="AED") used to reach
    # frankfurter with a base it has no series for.
    assert fx.to_base(100, "EUR", "2025-06-02", "AED") == pytest.approx(
        100 / 0.90 * AED_PER_USD
    )


# --- rates_range, which prefetch uses ---

def test_a_range_scales_every_day_by_the_parity(monkeypatch):
    monkeypatch.setattr(
        fx, "get_json",
        lambda url, timeout=30: {
            "rates": {"2025-06-02": {"EUR": 0.90}, "2025-06-03": {"EUR": 0.92}}
        },
    )
    got = fx.rates_range("2025-06-02", "2025-06-03", "AED", "EUR")
    assert got == {
        "2025-06-02": pytest.approx(0.90 / AED_PER_USD),
        "2025-06-03": pytest.approx(0.92 / AED_PER_USD),
    }


# --- spot ---

def test_spot_carries_the_anchor_s_as_of_date(no_network):
    rate, as_of = fx.spot("AED", "EUR")
    assert rate == pytest.approx(0.90 / AED_PER_USD)
    assert as_of == "2025-06-02"
