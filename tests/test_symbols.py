"""Worldwide symbol search — payload shaping and the failure contract.

Fixture payloads, no network: every test monkeypatches the module's get_json.
"""

import json
import time

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


def test_search_keeps_each_rows_quote_type(monkeypatch):
    """The match already says what the row is; the search box's label
    (asset_kind.cached) reads it from here instead of looking it up."""
    from stocks.data import funds

    serve(monkeypatch, MIPS)
    search_symbols("mips")
    assert funds.quote_type("MIPS.ST", fetch=False) == "EQUITY"
    # A row the search drops is not one it vouches for.
    assert funds.quote_type("MIPSX", fetch=False) is None


# ------------------------------------------------------ bare broker codes

def serve_by_query(monkeypatch, answers, spy=None):
    """Answer each search with the rows for its `q`, nothing for the rest."""
    from urllib.parse import parse_qs, urlparse

    def fake(url, **kw):
        query = parse_qs(urlparse(url).query).get("q", [""])[0]
        if spy is not None:
            spy.append(query)
        return {"quotes": answers.get(query, [])}

    monkeypatch.setattr(symbols, "get_json", fake)


def test_a_bare_eur_code_lands_on_its_xetra_line(monkeypatch):
    # The search for "SIE" ranks Siemens Energy first; only the exact code on
    # a EUR venue counts, and of those XETRA beats Frankfurt.
    serve_by_query(monkeypatch, {"SIE": [
        quote("ENR.DE", "SIEMENS ENERGY AG", exch="XETRA"),
        quote("SIE.F", "SIEMENS AG", exch="Frankfurt"),
        quote("SIE.DE", "SIEMENS AG", exch="XETRA"),
        quote("SIEGY", "Siemens AG ADR", exch="OTC"),
    ]})
    assert symbols.symbol_for_code("SIE", "EUR") == "SIE.DE"


def test_a_code_the_bare_search_never_lists_is_asked_by_name(monkeypatch):
    # Yahoo answers "BOY" with Boyd Gaming and La-Z-Boy; "BOY.DE" it knows.
    spy = []
    serve_by_query(monkeypatch, {
        "BOY": [quote("BYD", "Boyd Gaming"), quote("BOY.L", "Bodycote plc")],
        "BOY.DE": [quote("BOY.DE", "BANCO BILBAO VIZCAYA ARGENTARIA", exch="XETRA")],
    }, spy=spy)
    assert symbols.symbol_for_code("BOY", "EUR") == "BOY.DE"
    assert spy == ["BOY", "BOY.DE"]


def test_the_trade_currency_picks_the_venues(monkeypatch):
    serve_by_query(monkeypatch, {"BOY": [
        quote("BOY.DE", "BANCO BILBAO VIZCAYA ARGENTARIA", exch="XETRA"),
        quote("BOY.L", "Bodycote plc", exch="LSE"),
    ]})
    assert symbols.symbol_for_code("BOY", "GBP") == "BOY.L"


def test_a_currency_with_no_venues_is_never_searched(monkeypatch):
    # In USD a bare code already is the listing: nothing to look for.
    spy = []
    serve_by_query(monkeypatch, {}, spy=spy)
    assert symbols.symbol_for_code("ZZZQX", "USD") is None
    assert symbols.symbol_for_code("US81762P1021", "EUR") is None  # no ISINs
    assert spy == []


def test_a_resolved_code_is_cached_for_the_price_path(monkeypatch):
    spy = []
    serve_by_query(monkeypatch, {"SIE": [quote("SIE.DE", "SIEMENS AG")]}, spy=spy)
    assert symbols.symbol_for_code("SIE", "EUR") == "SIE.DE"
    assert symbols.symbol_for_code("SIE", "EUR") == "SIE.DE"
    assert spy == ["SIE"]
    assert json.loads(symbols.CODE_CACHE.read_text()) == {"SIE": "SIE.DE"}

    # A new process reads it back — and the price path has no currency to
    # search with, so the map is all it gets.
    monkeypatch.setattr(symbols, "_code_memo", None)
    assert symbols.code_symbol("sie") == "SIE.DE"


def test_a_miss_is_remembered_for_the_process_only(monkeypatch):
    spy = []
    serve_by_query(monkeypatch, {}, spy=spy)
    assert symbols.symbol_for_code("ZZZQX", "EUR") is None
    assert symbols.symbol_for_code("ZZZQX", "EUR") is None
    assert spy == ["ZZZQX", "ZZZQX.DE", "ZZZQX.PA", "ZZZQX.F"]
    assert not symbols.CODE_CACHE.exists()


def test_a_home_exchange_beats_a_german_regional_floor(monkeypatch):
    # Philips trades in Amsterdam; Frankfurt only mirrors it.
    serve_by_query(monkeypatch, {"PHIA": [
        quote("PHIA.F", "KONINKLIJKE PHILIPS", exch="Frankfurt"),
        quote("PHIA.AS", "KONINKLIJKE PHILIPS", exch="Amsterdam"),
    ]})
    assert symbols.symbol_for_code("PHIA", "EUR") == "PHIA.AS"


@pytest.mark.parametrize(("code", "currency", "wanted"), [
    ("BT.A", "GBP", "BT-A.L"),     # LSE share class after a dot
    ("VOLV B", "SEK", "VOLV-B.ST"),  # Nordic share class after a space
    ("BRK.B", "USD", "BRK-B"),     # US class: Yahoo spells it with a dash
    ("700", "HKD", "0700.HK"),     # HK codes are four digits on Yahoo
])
def test_a_code_is_spelled_the_way_yahoo_spells_it(monkeypatch, code, currency, wanted):
    # The search is asked for Yahoo's spelling, not the broker's.
    serve_by_query(monkeypatch, {wanted.split(".")[0]: [quote(wanted, "Some Co")]})
    assert symbols.symbol_for_code(code, currency) == wanted
    assert symbols.code_symbol(code) == wanted  # cached under the ledger label


@pytest.mark.parametrize(("code", "currency", "wanted"), [
    ("LLOY", "GBX", "LLOY.L"),        # pence are still London
    ("005930", "KRW", "005930.KS"),
    ("PETR4", "BRL", "PETR4.SA"),
    ("D05", "SGD", "D05.SI"),
])
def test_every_quoted_currency_has_venues(monkeypatch, code, currency, wanted):
    serve_by_query(monkeypatch, {code: [quote(wanted, "Some Co")]})
    assert symbols.symbol_for_code(code, currency) == wanted


def test_a_two_letter_code_is_still_searched(monkeypatch):
    # The search box ignores queries under three letters; a broker code of
    # two (BP, 5) is a whole ticker, not a prefix.
    serve_by_query(monkeypatch, {"BP": [quote("BP.L", "BP PLC", exch="LSE")]})
    assert symbols.symbol_for_code("BP", "GBP") == "BP.L"


def test_a_plain_usd_code_is_never_searched(monkeypatch):
    spy = []
    serve_by_query(monkeypatch, {}, spy=spy)
    assert symbols.symbol_for_code("AAPL", "USD") is None
    assert spy == []


def test_a_miss_while_throttled_is_not_a_miss(monkeypatch):
    serve_by_query(monkeypatch, {})
    monkeypatch.setattr(symbols, "_blocked_until", time.monotonic() + 60)
    assert symbols.symbol_for_code("SIE", "EUR") is None
    assert "SIE" not in symbols._code_misses


# ------------------------------------- a code Yahoo quotes, in another currency


def test_the_listings_put_the_searchs_own_venues_first(monkeypatch):
    # Yahoo ranks "SAN" to Sanofi and lists Santander nowhere; Madrid still
    # has to be on the list, by name, for the price to decide.
    serve_by_query(monkeypatch, {"SAN": [
        quote("SAN", "Santander ADR", exch="NYSE"),
        quote("SAN.PA", "SANOFI", exch="Paris"),
        quote("SAN.L", "Santander plc", exch="LSE"),
    ]})
    found = symbols.listings_for_code("SAN", "EUR", limit=6)
    assert found[0] == "SAN.PA"
    assert "SAN.MC" in found
    assert "SAN" not in found and "SAN.L" not in found  # not euro lines
    assert len(found) == 6


def test_a_listing_search_is_never_the_price_paths_answer(monkeypatch):
    # The dollar rows of "ALV" are still Autoliv: nothing global is written.
    spy = []
    serve_by_query(monkeypatch, {"ALV": [quote("ALV.DE", "ALLIANZ SE")]}, spy=spy)
    assert symbols.listings_for_code("ALV", "EUR")[0] == "ALV.DE"
    assert symbols.listings_for_code("alv", "eur")[0] == "ALV.DE"
    assert spy == ["ALV"]  # remembered per (code, currency)
    assert not symbols.CODE_CACHE.exists()
    assert symbols.code_symbol("ALV") is None


def test_a_listing_search_while_throttled_is_asked_again(monkeypatch):
    spy = []
    serve_by_query(monkeypatch, {}, spy=spy)
    monkeypatch.setattr(symbols, "_blocked_until", time.monotonic() + 60)
    symbols.listings_for_code("ALV", "EUR")
    symbols.listings_for_code("ALV", "EUR")
    assert ("ALV", "EUR") not in symbols._listings_memo


def test_a_currency_with_no_venues_has_no_listings(monkeypatch):
    spy = []
    serve_by_query(monkeypatch, {}, spy=spy)
    assert symbols.listings_for_code("AAPL", "USD") == []
    assert symbols.listings_for_code("US81762P1021", "EUR") == []
    assert symbols.venue_symbols("700", "HKD") == ["0700.HK"]
    assert spy == []


def test_resolve_reads_the_codes_the_search_placed(monkeypatch):
    from stocks.data import fetch

    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {"RCF": "TEP.PA"})
    monkeypatch.setattr(symbols, "_code_memo", {"SIE": "SIE.DE", "RCF": "RCF.DE"})
    assert fetch.resolve("sie") == "SIE.DE"
    assert fetch.resolve("RCF") == "TEP.PA"  # the hand-written alias wins
    assert fetch.resolve("AAPL") == "AAPL"
