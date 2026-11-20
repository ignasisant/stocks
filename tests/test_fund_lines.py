"""A fund's NAV line found by price, for an ISIN Yahoo's search misses.

Yahoo answers "LU0270904781" (Pictet-Security P EUR) with nothing, or only
with the German floor quotes; the NAV line 0P00006SZ0.F is there under the
fund's name. Fixture rows and prices are the live answers, probed 2026-11-19
and trimmed; no network.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from yfinance.exceptions import YFRateLimitError

from stocks import loaders
from stocks.data import fund_lines, openfigi, profiles, spark, symbols
from stocks.data.openfigi import OPEN_END, Listing, Security
from stocks.data.spark import Mark

NOW = 1_795_100_000.0
DAY = 86400.0


def quote(sym, name, qtype="MUTUALFUND"):
    return {"symbol": sym, "longname": name, "shortname": name, "quoteType": qtype}


def fund(isin, name, floors, kind=OPEN_END):
    listings = tuple(Listing("GF", s.split(".")[0], s) for s in floors)
    return Security(isin, name, "Mutual Fund", "BBG000000000", listings, type=kind)


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(symbols, "_blocked_until", 0.0)
    monkeypatch.setattr(symbols, "ISIN_CACHE", tmp_path / "isin_symbols.json")
    monkeypatch.setattr(symbols, "_isin_memo", None)
    monkeypatch.setattr(symbols, "_isin_misses", set())
    monkeypatch.setattr(symbols, "_isin_names", {})
    monkeypatch.setattr(symbols, "_floor_rechecked", set())
    monkeypatch.setattr(symbols, "_isin_retry", {})
    monkeypatch.setattr(fund_lines, "_runs", fund_lines.deque())
    monkeypatch.setattr(profiles, "PROFILE_CACHE", tmp_path / "profiles.json")
    monkeypatch.setattr(profiles, "_memo", None)
    monkeypatch.setattr(openfigi, "known", lambda isin: None)


def serve(monkeypatch, answers):
    """Yahoo's search answering per query (case-blind), [] otherwise."""
    asked: list[str] = []
    table = {k.upper(): v for k, v in answers.items()}

    def fake(url, **kw):
        q = parse_qs(urlparse(url).query)["q"][0]
        asked.append(q)
        return {"quotes": table.get(q.upper(), [])}

    monkeypatch.setattr(symbols, "get_json", fake)
    return asked


def priced(prices, *, age=0.0):
    """A `marks` stand-in: {symbol: (currency, price)} quoted `age` ago."""

    def marks(syms):
        return {
            s: Mark(prices[s][0], prices[s][1], NOW - age) for s in syms if s in prices
        }

    return marks


def figi(monkeypatch, sec):
    monkeypatch.setattr(openfigi, "security", lambda isin: sec)


# ------------------------------------------------------------ Pictet-Security

PICTET_ISIN = "LU0270904781"
PICTET = fund(PICTET_ISIN, "PICTET-SECURITY-PE", ["PIML.F", "PIML.MU", "PIML.DU"])
FLOOR_NAMES = {"PIML": [quote("PIML.MU", "Pictet - Security             N", "ETF")]}
CLASSES = [
    quote("0P00006X58", "Pictet-Security P USD"),
    quote("0P0000HXRH.L", "Pictet-Security P dy GBP"),
    quote("0P00006TYP", "Pictet-Security P dy USD"),
    quote("0P00006SZ0.F", "Pictet-Security P EUR"),
    quote("0P0000XMWU.F", "Pictet-Security HI EUR"),
    quote("0P00016FI9.F", "Pictet-Security Z EUR"),
]
PRICES = {
    "PIML.F": ("EUR", 420.23),
    "PIML.MU": ("EUR", 423.43),
    "PIML.DU": ("EUR", 418.83),
    "0P00006X58": ("USD", 463.92),
    "0P00006TYP": ("USD", 463.89),
    "0P0000HXRH.L": ("GBP", 352.36),
    "0P00006SZ0.F": ("EUR", 422.62),
    "0P0000XMWU.F": ("EUR", 332.77),
    "0P00016FI9.F": ("EUR", 561.54),
    "EURUSD=X": ("USD", 1.0985),
}


def test_the_class_whose_price_matches_the_floors_is_the_line(monkeypatch):
    figi(monkeypatch, PICTET)
    serve(
        monkeypatch,
        {
            **FLOOR_NAMES,
            "Pictet-Security P EUR": CLASSES[3:4],
            "Pictet-Security P": CLASSES[:4],
            "Pictet-Security": CLASSES[3:],
        },
    )
    found = fund_lines.nav_line(PICTET_ISIN, marks=priced(PRICES), now=NOW)
    assert found == fund_lines.Found("0P00006SZ0.F", "Pictet-Security P EUR", "EUR")


def test_the_class_currency_wins_over_its_unhedged_twin(monkeypatch):
    # P USD is P EUR at the exchange rate; the class asked for is P USD, and
    # P dy USD three cents from it is told apart by its name.
    sec = fund("LU0256846139", "PICTET-SECURITY-P USD", ["PIML.F", "PIML.MU"])
    figi(monkeypatch, sec)
    serve(
        monkeypatch,
        {
            **FLOOR_NAMES,
            "Pictet-Security P USD": CLASSES[:1],
            "Pictet-Security P": CLASSES,
        },
    )
    found = fund_lines.nav_line("LU0256846139", marks=priced(PRICES), now=NOW)
    assert found and found.symbol == "0P00006X58"


def test_a_tie_goes_to_the_line_named_as_openfigi_names_the_isin(monkeypatch):
    # DWS Top Dividende LD: dealers quote 177.8-181, so LD (180.53) and LDQ
    # (175.69) are both close and not clear of each other. No rule reads
    # DWS's class codes; the name OpenFIGI gives the ISIN settles it.
    floors = ["HJUA.F", "HJUA.MU", "HJUA.DU", "HJUA.SG"]
    sec = fund("DE0009848119", "DWS TOP DIVIDENDE LD", floors)
    figi(monkeypatch, sec)
    lines = [
        quote("0P00015F4E.F", "DWS Top Dividende LDQ"),
        quote("0P00000G7B.F", "DWS Top Dividende LD"),
        quote("0P0001CGLJ.F", "DWS Top Dividende TFD"),
    ]
    serve(
        monkeypatch,
        {
            "HJUA": [quote("HJUA.F", "DWS Top Dividende", "ETF")],
            "DWS Top Dividende": lines,
            "DWS TOP DIVIDENDE LD": lines[:2],
        },
    )
    prices = {
        "HJUA.F": ("EUR", 178.0),
        "HJUA.MU": ("EUR", 180.99),
        "HJUA.DU": ("EUR", 177.86),
        "HJUA.SG": ("EUR", 177.76),
        "0P00015F4E.F": ("EUR", 175.69),
        "0P00000G7B.F": ("EUR", 180.53),
        "0P0001CGLJ.F": ("EUR", 163.35),
    }
    found = fund_lines.nav_line("DE0009848119", marks=priced(prices), now=NOW)
    assert found and found.symbol == "0P00000G7B.F"


def test_two_classes_at_one_price_and_one_name_are_no_answer(monkeypatch):
    twin = quote("0P99999999.F", "Pictet-Security P EUR")
    figi(monkeypatch, PICTET)
    serve(monkeypatch, {**FLOOR_NAMES, "Pictet-Security P EUR": [CLASSES[3], twin]})
    prices = {**PRICES, "0P99999999.F": ("EUR", 421.0)}
    assert fund_lines.nav_line(PICTET_ISIN, marks=priced(prices), now=NOW) is None


def test_a_name_without_a_matching_price_is_no_answer(monkeypatch):
    figi(monkeypatch, PICTET)
    serve(monkeypatch, {**FLOOR_NAMES, "Pictet-Security": CLASSES[4:]})
    assert fund_lines.nav_line(PICTET_ISIN, marks=priced(PRICES), now=NOW) is None


def test_a_matching_price_on_another_house_or_class_is_no_answer(monkeypatch):
    # A Yahoo answer for "Pictet-Security" can carry unrelated funds; one
    # inside the tolerance is a coincidence unless its name is the house's
    # and the class's.
    figi(monkeypatch, PICTET)
    stranger = quote("0P0000LUX1.F", "LUX IM Global Security EUR")
    sibling = quote("0P0000ZZZ1.F", "Pictet-Security I EUR")
    serve(monkeypatch, {**FLOOR_NAMES, "Pictet-Security": [stranger, sibling]})
    prices = {**PRICES, "0P0000LUX1.F": ("EUR", 421.5), "0P0000ZZZ1.F": ("EUR", 419.9)}
    assert fund_lines.nav_line(PICTET_ISIN, marks=priced(prices), now=NOW) is None


def test_stale_floor_quotes_ask_no_search(monkeypatch):
    figi(monkeypatch, PICTET)
    asked = serve(monkeypatch, {})
    marks = priced(PRICES, age=10 * DAY)
    assert fund_lines.nav_line(PICTET_ISIN, marks=marks, now=NOW) is None
    assert asked == []


def test_what_could_not_be_asked_is_no_verdict(monkeypatch):
    serve(monkeypatch, FLOOR_NAMES)
    figi(monkeypatch, PICTET)

    def cooling(syms):
        raise fund_lines.Unanswered("spark")

    with pytest.raises(fund_lines.Unanswered):
        fund_lines.nav_line(PICTET_ISIN, marks=cooling, now=NOW)

    monkeypatch.setattr(symbols, "_blocked_until", symbols.time.monotonic() + 60)
    with pytest.raises(fund_lines.Unanswered):
        fund_lines.nav_line(PICTET_ISIN, marks=priced(PRICES), now=NOW)


def test_runs_are_capped_per_window(monkeypatch):
    figi(monkeypatch, PICTET)
    serve(monkeypatch, {})
    for _ in range(fund_lines.MAX_RUNS):
        fund_lines.nav_line(PICTET_ISIN, marks=priced(PRICES, age=10 * DAY), now=NOW)
    with pytest.raises(fund_lines.Unanswered):
        fund_lines.nav_line(PICTET_ISIN, marks=priced(PRICES), now=NOW)


def test_only_an_open_end_fund_is_looked_up(monkeypatch):
    figi(monkeypatch, fund(PICTET_ISIN, "SOME ETF", ["PIML.F"], kind="ETP"))
    asked = serve(monkeypatch, {})
    assert fund_lines.nav_line(PICTET_ISIN, marks=priced(PRICES), now=NOW) is None
    assert asked == []


def test_the_same_class_in_another_currency_carries_its_letter(monkeypatch):
    # BGF World Technology A2 EUR has no NAV line of its own; A2 in USD,
    # unhedged, is the same portfolio at the rate. The hedged EUR class is
    # another price, and a USD line without the A2 is never borrowed.
    sec = fund("LU0171310443", "BGF-WRLD TECH-A2 EUR", ["MI9E.F", "MI9E.SG"])
    figi(monkeypatch, sec)
    rows = [
        quote("0P00000AWU", "BGF World Technology A2"),
        quote("0P0001DFPN.F", "BGF World Technology A2 EUR H"),
    ]
    serve(
        monkeypatch,
        {
            "MI9E": [quote("MI9E.SG", "BGF World Technology A2 EUR")],
            "BGF World Technology A2 EUR": rows,
        },
    )
    prices = {
        "MI9E.F": ("EUR", 111.02),
        "MI9E.SG": ("EUR", 111.18),
        "0P00000AWU": ("USD", 121.6),
        "0P0001DFPN.F": ("EUR", 29.94),
        "USDEUR=X": ("EUR", 0.9105),
    }
    found = fund_lines.nav_line("LU0171310443", marks=priced(prices), now=NOW)
    assert found == fund_lines.Found("0P00000AWU", "BGF World Technology A2", "USD")

    rows[0] = quote("0P00000AWU", "BGF World Technology D2")
    assert fund_lines.nav_line("LU0171310443", marks=priced(prices), now=NOW) is None


@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("PICTET-SECURITY-P EUR", [("PICTET SECURITY", "P", "EUR")]),
        ("PICTET-TIMBER-PEUR", [("PICTET TIMBER", "P", "EUR")]),
        (
            "PICTET-SECURITY-PE",
            [("PICTET SECURITY", "P", "EUR"), ("PICTET SECURITY", "PE", "")],
        ),
        ("NORDEA 1 SIC-GCL&ENV-BP-EUR", [("NORDEA 1 SIC GCL&ENV", "BP", "EUR")]),
        ("CARMIGNAC INVESTISS-A EU AC", [("CARMIGNAC INVESTISS", "A", "EUR")]),
        ("MORGAN ST INV F-GLB BRNDS-A", [("MORGAN ST INV F GLB BRNDS", "A", "")]),
        ("COMGEST MONDE", [("COMGEST MONDE", "", "")]),
    ],
)
def test_share_class_readings(name, want):
    got = [(c.stem, c.letter, c.currency) for c in fund_lines.classes(name)]
    assert got == want


# ------------------------------------------------------------ symbol_for_isin


def stub(monkeypatch, answer):
    calls: list[tuple] = []

    def nav_line(isin, *, floors=(), floor_names=()):
        calls.append((isin, list(floors)))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(fund_lines, "nav_line", nav_line)
    return calls


def test_an_isin_yahoo_misses_resolves_to_the_nav_line(monkeypatch):
    serve(monkeypatch, {})
    stub(monkeypatch, fund_lines.Found("0P00006SZ0.F", "Pictet-Security P EUR", "EUR"))
    assert symbols.symbol_for_isin(PICTET_ISIN) == "0P00006SZ0.F"
    assert symbols.cached_isin_symbol(PICTET_ISIN) == "0P00006SZ0.F"
    assert symbols.isin_name(PICTET_ISIN) == "Pictet-Security P EUR"


def test_a_borrowed_class_keeps_its_lines_currency(monkeypatch):
    # BGF A2 EUR priced off the A2 USD line: the ledger says EUR, the closes
    # are dollars, and valuation converts at the line's own currency.
    serve(monkeypatch, {})
    stub(monkeypatch, fund_lines.Found("0P00000AWU", "BGF World Technology A2", "USD"))
    assert symbols.symbol_for_isin("LU0171310443") == "0P00000AWU"
    assert profiles.known("0P00000AWU")["currency"] == "USD"


def test_floor_quotes_alone_are_handed_to_the_resolver(monkeypatch):
    serve(monkeypatch, {PICTET_ISIN: [quote("P3IE.SG", "Pictet - Security")]})
    calls = stub(monkeypatch, fund_lines.Found("0P00006SZ0.F", "Pictet-Security P EUR"))
    assert symbols.symbol_for_isin(PICTET_ISIN) == "0P00006SZ0.F"
    assert calls == [(PICTET_ISIN, ["P3IE.SG"])]


def test_a_floor_cached_earlier_is_looked_at_again_once(monkeypatch):
    symbols._save_isin_cache({PICTET_ISIN: "P3IE.SG"})
    calls = stub(monkeypatch, None)
    assert symbols.symbol_for_isin(PICTET_ISIN) == "P3IE.SG"
    assert calls == []  # not known open-end: an equity's floor asks nothing

    monkeypatch.setattr(openfigi, "known", lambda isin: PICTET)
    stub(monkeypatch, fund_lines.Unanswered("search"))
    assert symbols.symbol_for_isin(PICTET_ISIN) == "P3IE.SG"
    assert PICTET_ISIN not in symbols._floor_rechecked  # asked again later

    calls = stub(monkeypatch, None)
    assert symbols.symbol_for_isin(PICTET_ISIN) == "P3IE.SG"
    assert symbols.symbol_for_isin(PICTET_ISIN) == "P3IE.SG"
    assert len(calls) == 1

    monkeypatch.setattr(symbols, "_floor_rechecked", set())
    stub(monkeypatch, fund_lines.Found("0P00006SZ0.F", "Pictet-Security P EUR"))
    assert symbols.symbol_for_isin(PICTET_ISIN) == "0P00006SZ0.F"


def test_a_throttled_search_records_no_miss(monkeypatch):
    def refused(url, **kw):
        raise ConnectionError("429")

    monkeypatch.setattr(symbols, "get_json", refused)
    stub(monkeypatch, None)
    assert symbols.symbol_for_isin(PICTET_ISIN) is None
    assert PICTET_ISIN not in symbols._isin_misses


def test_a_resolver_that_could_not_ask_records_no_miss(monkeypatch):
    asked = serve(monkeypatch, {})
    calls = stub(monkeypatch, fund_lines.Unanswered("spark"))
    assert symbols.symbol_for_isin(PICTET_ISIN) is None
    assert PICTET_ISIN not in symbols._isin_misses
    # …nor a fresh search on every render: it waits RETRY_S.
    assert symbols.symbol_for_isin(PICTET_ISIN) is None
    assert (len(asked), len(calls)) == (1, 1)

    symbols._isin_retry[PICTET_ISIN] = 0.0
    stub(monkeypatch, fund_lines.Found("0P00006SZ0.F", "Pictet-Security P EUR", "EUR"))
    assert symbols.symbol_for_isin(PICTET_ISIN) == "0P00006SZ0.F"


def test_a_real_miss_is_kept_for_the_process(monkeypatch):
    serve(monkeypatch, {})
    stub(monkeypatch, None)
    assert symbols.symbol_for_isin(PICTET_ISIN) is None
    assert PICTET_ISIN in symbols._isin_misses


# ------------------------------------------------------------- the search box


def test_typing_the_isin_offers_the_nav_line(monkeypatch):
    serve(monkeypatch, {})
    stub(monkeypatch, fund_lines.Found("0P00006SZ0.F", "Pictet-Security P EUR"))
    loaders.world_matches.cache_clear()
    assert loaders.world_matches(PICTET_ISIN) == [
        ("0P00006SZ0.F", "Pictet-Security P EUR", "")
    ]
    assert loaders.WORLD_MEMO.items() == []  # an ISIN is never shared


# ------------------------------------------------------------- spark marks


def test_marks_read_the_spark_meta(monkeypatch):
    meta = {
        "PIML.F": {
            "currency": "EUR",
            "regularMarketPrice": 420.23,
            "regularMarketTime": 1795000000,
        },
        "VOD.L": {
            "currency": "GBp",
            "regularMarketPrice": 71.2,
            "regularMarketTime": 1795000100,
        },
        "DEAD.F": {"currency": "EUR", "regularMarketPrice": 0},
    }

    def fetch(syms, range_, timeout):
        return [{"symbol": s, "response": [{"meta": meta[s]}]} for s in syms if s in meta]

    monkeypatch.setattr(spark, "_fetch", fetch)
    monkeypatch.setattr(spark, "throttle_remaining", lambda: 0.0)
    assert spark.marks(["PIML.F", "VOD.L", "DEAD.F", "NOPE.F"]) == {
        "PIML.F": Mark("EUR", 420.23, 1795000000.0),
        "VOD.L": Mark("GBp", 71.2, 1795000100.0),  # pence, not pounds
    }


def test_strict_marks_say_when_yahoo_was_not_asked(monkeypatch):
    monkeypatch.setattr(spark, "throttle_remaining", lambda: 30.0)
    assert spark.marks(["PIML.F"]) == {}
    with pytest.raises(YFRateLimitError):
        spark.marks(["PIML.F"], strict=True)
