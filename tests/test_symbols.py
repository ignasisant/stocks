"""Worldwide symbol search — payload shaping and the failure contract.

Fixture payloads, no network: every test monkeypatches the module's get_json.
"""

import json

import pytest

from stocks.data import symbols
from stocks.data.symbols import search_symbols


def quote(sym, short, *, long=None, exch="", qtype="EQUITY"):
    return {
        "symbol": sym,
        "shortname": short,
        "longname": long,
        "exchDisp": exch,
        "quoteType": qtype,
    }


# Every venue Yahoo quotes Mips AB on, spelled the way each one prints it.
MIPS = [
    quote("MIPS.ST", "Mips AB", long="Mips AB (publ)", exch="Stockholm"),
    quote("MPZAF", "MIPS AB", long="Mips AB (publ)", exch="OTC Markets"),
    quote("7M1.F", "Mips AB                       N", long="Mips AB (publ)",
          exch="Frankfurt"),
    quote("SE0009216278.SG", "MIPS AB O.N.", exch="Stuttgart"),
    quote("0RNQ.IL", "MIPS AB MIPS ORD SHS", long="Mips AB (publ)", exch="London"),
    quote("MIPSX", "MassMutual Premier Inflation-Pr", exch="NASDAQ",
          qtype="MUTUALFUND"),
]


@pytest.fixture(autouse=True)
def reset_cooldown(monkeypatch):
    """Each test starts un-throttled — the cooldown is module state."""
    monkeypatch.setattr(symbols, "_blocked_until", 0.0)


def serve(monkeypatch, quotes, spy=None):
    def fake(url, **kw):
        if spy is not None:
            spy.append(url)
        return {"quotes": quotes}

    monkeypatch.setattr(symbols, "get_json", fake)


def test_collapses_every_venue_of_one_issuer(monkeypatch):
    serve(monkeypatch, MIPS)
    # Yahoo's own ranking puts the primary listing first, and that is the line
    # worth keeping: deepest history, native currency.
    assert search_symbols("mips") == [("MIPS.ST", "Mips AB (publ)", "Stockholm")]


def test_skips_non_tradable_quote_types(monkeypatch):
    serve(monkeypatch, [MIPS[-1]])  # the mutual fund alone
    assert search_symbols("mips") == []


def test_prefers_longname_and_cleans_padding(monkeypatch):
    serve(monkeypatch, [MIPS[2]])  # Frankfurt line, column-padded shortname
    assert search_symbols("mips") == [("7M1.F", "Mips AB (publ)", "Frankfurt")]


def test_falls_back_to_shortname_when_longname_missing(monkeypatch):
    serve(monkeypatch, [quote("NVDX", "T-Rex 2X Long NVIDIA", exch="BATS")])
    assert search_symbols("nvidia") == [("NVDX", "T-Rex 2X Long NVIDIA", "BATS")]


def test_short_prefix_does_not_swallow_a_different_issuer(monkeypatch):
    # "ASML" is under the dedup floor, so it must not absorb "ASML Group".
    serve(monkeypatch, [
        quote("1ASML.MI", "ASML", exch="Milan"),
        quote("ASMLG", "ASML Group", exch="NASDAQ"),
    ])
    assert [t for t, _, _ in search_symbols("asml")] == ["1ASML.MI", "ASMLG"]


def test_honours_limit(monkeypatch):
    serve(monkeypatch, [
        quote(f"T{i}", f"Company Number {i}", exch="NYSE") for i in range(10)
    ])
    assert len(search_symbols("company", limit=3)) == 3


def test_query_below_min_length_never_calls_out(monkeypatch):
    spy = []
    serve(monkeypatch, MIPS, spy=spy)
    assert search_symbols("mi") == []
    assert spy == []


def test_failure_is_empty_then_silent(monkeypatch):
    """A rejection degrades the picker instead of raising, and stops retrying.

    Yahoo throttles by IP; hammering it once per keystroke after the first 429
    only deepens the block, so the cooldown must hold off the next call.
    """
    calls = []

    def boom(url, **kw):
        calls.append(url)
        raise OSError("429")

    monkeypatch.setattr(symbols, "get_json", boom)
    assert search_symbols("mips") == []
    assert search_symbols("mips") == []
    assert len(calls) == 1


# ------------------------------------------------------------------ ISINs


@pytest.fixture
def isin_cache(tmp_path, monkeypatch):
    """Fresh disk cache and per-process memos for the ISIN resolver."""
    path = tmp_path / "isin_symbols.json"
    monkeypatch.setattr(symbols, "ISIN_CACHE", path)
    monkeypatch.setattr(symbols, "_isin_memo", None)
    monkeypatch.setattr(symbols, "_isin_misses", set())
    return path


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("US81762P1021", True),
        ("us81762p1021", True),  # a ledger label arrives upper-cased, but still
        ("NL0010273215", True),
        ("NOW", False),
        ("BRK-B", False),
        ("US81762P102", False),  # eleven characters
        ("", False),
    ],
)
def test_is_isin(label, expected):
    assert symbols.is_isin(label) is expected


def test_isin_resolves_and_caches_to_disk(monkeypatch, isin_cache):
    spy = []
    serve(monkeypatch, [quote("NOW", "ServiceNow, Inc.", exch="NYSE")], spy=spy)
    assert symbols.symbol_for_isin("US81762P1021") == "NOW"
    assert symbols.symbol_for_isin("US81762P1021") == "NOW"
    assert len(spy) == 1  # the second read came off the cache
    assert json.loads(isin_cache.read_text()) == {"US81762P1021": "NOW"}


def test_isin_cache_survives_a_new_process(monkeypatch, isin_cache):
    isin_cache.write_text(json.dumps({"US81762P1021": "NOW"}))
    spy = []
    serve(monkeypatch, [], spy=spy)
    assert symbols.symbol_for_isin("US81762P1021") == "NOW"
    assert spy == []


def test_us_isin_prefers_the_bare_us_listing(monkeypatch, isin_cache):
    # Yahoo answers a US ISIN with whatever venue ranks first, often a German
    # line ("9PDA.SG"); the home listing is the one the app can price.
    serve(monkeypatch, [
        quote("9PDA.SG", "PDD Holdings Inc. (ADRs)", exch="Stuttgart"),
        quote("PDD", "PDD Holdings Inc", exch="NASDAQ"),
    ])
    assert symbols.symbol_for_isin("US7223041028") == "PDD"


def test_foreign_isin_keeps_its_local_venue(monkeypatch, isin_cache):
    serve(monkeypatch, [quote("ASML.AS", "ASML Holding N.V.", exch="Amsterdam")])
    assert symbols.symbol_for_isin("NL0010273215") == "ASML.AS"


def test_unresolved_isin_is_none_and_not_cached_to_disk(monkeypatch, isin_cache):
    spy = []
    serve(monkeypatch, [], spy=spy)
    assert symbols.symbol_for_isin("XX0000000000") is None
    assert symbols.symbol_for_isin("XX0000000000") is None
    assert len(spy) == 1  # the miss is remembered for the process…
    assert not isin_cache.exists()  # …but never written down: Yahoo may be down


def test_non_isin_never_calls_out(monkeypatch, isin_cache):
    spy = []
    serve(monkeypatch, MIPS, spy=spy)
    assert symbols.symbol_for_isin("NOW") is None
    assert spy == []
