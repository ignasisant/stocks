"""OpenFIGI — ISIN to listings. Stub payloads shaped like the live answers
(probed 2026-10-27, trimmed to the venues that matter); no network."""

import json
import urllib.error

import pytest

from stocks.api.routes import import_statement
from stocks.data import openfigi, symbols


def row(exch, ticker, name="IBERDROLA SA", kind="Common Stock", figi="BBG000BC49N1"):
    return {
        "figi": "BBG0000" + exch,
        "name": name,
        "ticker": ticker,
        "exchCode": exch,
        "compositeFIGI": figi,
        "securityType": kind,
        "marketSector": "Equity",
        "shareClassFIGI": "BBG001S5S1X6",
        "securityType2": kind,
        "securityDescription": ticker,
    }


# Iberdrola: Madrid, the German lines, and an OTC dollar line under "US".
IBERDROLA = [
    row("SM", "IBE"),
    row("GY", "IBE1"),
    row("GR", "IBE1"),
    row("GF", "IBE1"),
    row("US", "IBDSF"),
    row("IX", "IBEE"),
]
# An ETF: no country primary, lines on London, Xetra, Milan.
VWCE = [
    row("LN", "VWRA", "VANG FTSE AW USDA", "Mutual Fund", "BBG00PQQHQJ2"),
    row("GY", "VWCE", "VANG FTSE AW USDA", "Mutual Fund", "BBG00PQQHQJ2"),
    row("IM", "VWCE", "VANG FTSE AW USDA", "Mutual Fund", "BBG00PQQHQJ2"),
    row("IM", "1VWCE", "VANG FTSE AW USDA", "Mutual Fund", "BBG00PQQHQJ2"),
]
AAPL = [row("US", "AAPL", "APPLE INC"), row("GY", "APC", "APPLE INC")]
BRK = [row("US", "BRK/B", "BERKSHIRE HATHAWAY INC-CL B"), row("UN", "BRK/B")]
BOOK = {
    "ES0144580Y14": IBERDROLA,
    "IE00BK5BQT80": VWCE,
    "US0378331005": AAPL,
    "US0846707026": BRK,
}


@pytest.fixture
def figi(monkeypatch):
    """OpenFIGI answering from BOOK; `calls` records every request's jobs/key."""
    calls: list[tuple[list[str], str | None]] = []

    def post(jobs, key):
        calls.append(([j["idValue"] for j in jobs], key))
        out = []
        for job in jobs:
            isin = job["idValue"]
            if isin in BOOK:
                out.append({"data": BOOK[isin]})
            else:
                out.append({"warning": "No identifier found."})
        return out

    monkeypatch.setattr(openfigi, "_post", post)
    return calls


@pytest.mark.parametrize(
    ("exch", "ticker", "symbol"),
    [
        ("SM", "IBE", "IBE.MC"),
        ("FP", "MC", "MC.PA"),
        ("NA", "ASML", "ASML.AS"),
        ("IM", "ENEL", "ENEL.MI"),
        ("GY", "SAP", "SAP.DE"),
        ("LN", "SHEL", "SHEL.L"),
        ("LN", "BP/", "BP.L"),
        ("LN", "BT/A", "BT-A.L"),
        ("US", "AAPL", "AAPL"),
        ("UN", "BRK/B", "BRK-B"),
        ("HK", "700", "0700.HK"),
        ("JT", "7203", "7203.T"),
        ("AT", "BHP", "BHP.AX"),
        ("CT", "SHOP", "SHOP.TO"),
        ("GF", "APC", "APC.F"),
        ("IM", "1AAPL", None),  # EuroTLX line of a foreign share
        ("SS", "VOLVB", None),  # Nordic class spelling can't be recovered
        ("XX", "WHATEVER", None),
        ("SM", "BAD TICKER!", None),
    ],
)
def test_yahoo_spelling(exch, ticker, symbol):
    assert openfigi.yahoo_symbol(exch, ticker) == symbol


def test_security_keeps_only_listings_yahoo_can_spell(figi):
    sec = openfigi.security("ES0144580Y14")
    assert sec is not None
    assert (sec.name, sec.kind, sec.figi) == (
        "IBERDROLA SA",
        "Common Stock",
        "BBG000BC49N1",
    )
    # IX (a Bloomberg-only venue) is dropped.
    assert [(item.exch, item.symbol) for item in sec.listings] == [
        ("SM", "IBE.MC"),
        ("GY", "IBE1.DE"),
        ("GR", "IBE1.DE"),
        ("GF", "IBE1.F"),
        ("US", "IBDSF"),
    ]


def test_home_is_the_country_primary_not_the_otc_line(figi):
    assert openfigi.home("ES0144580Y14") == "IBE.MC"
    assert openfigi.home("US0378331005") == "AAPL"
    assert openfigi.home("US0846707026") == "BRK-B"
    assert openfigi.home("IE00BK5BQT80") is None  # an ETF has no home line


def test_candidates_follow_the_venue_order_and_skip_floors_and_otc(figi):
    assert openfigi.candidates("IE00BK5BQT80", (".DE", ".MI", ".L")) == [
        "VWCE.DE",
        "VWCE.MI",
        "VWRA.L",
    ]
    # Primary first, the German line next; the floor and the OTC line never.
    assert openfigi.candidates("ES0144580Y14", (".DE", ".MC", ".F", "")) == [
        "IBE.MC",
        "IBE1.DE",
    ]
    assert openfigi.candidates("US0378331005", ("",)) == ["AAPL"]


def test_answers_are_batched_and_cached_to_disk(figi):
    isins = [f"XS{n:09d}0" for n in range(23)]
    # Check digits don't matter to the shape test; the real three are asked too.
    openfigi.securities(isins + list(BOOK))
    assert [len(jobs) for jobs, _ in figi] == [10, 10, 7]
    assert all(key is None for _, key in figi)

    figi.clear()
    got = openfigi.securities(list(BOOK) + ["XS0000000000"])
    assert figi == []  # all fresh: hits and the confirmed misses
    assert got["XS0000000000"] is None
    assert got["ES0144580Y14"] is not None

    # A new process reads the file back.
    saved = json.loads(openfigi.CACHE.read_text())
    assert saved["XS0000000000"]["miss"] is True
    assert saved["ES0144580Y14"]["listings"][0] == ["SM", "IBE"]
    openfigi._memo = None
    openfigi.securities(["ES0144580Y14"])
    assert figi == []


def test_a_key_raises_the_batch_and_travels_in_the_header(figi, monkeypatch):
    monkeypatch.setattr(openfigi, "api_key", lambda: "k3y")
    openfigi.securities([f"XS{n:09d}0" for n in range(25)])
    assert [(len(jobs), key) for jobs, key in figi] == [(25, "k3y")]


def test_a_miss_is_asked_again_after_its_shorter_ttl(figi, monkeypatch):
    openfigi.securities(["XS0000000000"])
    stale = openfigi._load()["XS0000000000"]
    stale["at"] -= openfigi.MISS_TTL_S + 1
    openfigi.securities(["XS0000000000"])
    assert len(figi) == 2
    # A hit that old is still good: its listings barely move.
    openfigi.securities(["ES0144580Y14"])
    openfigi._load()["ES0144580Y14"]["at"] -= openfigi.MISS_TTL_S + 1
    openfigi.securities(["ES0144580Y14"])
    assert len(figi) == 3


def test_a_rejected_isin_is_not_a_verdict(monkeypatch):
    monkeypatch.setattr(openfigi, "_post", lambda jobs, key: [{"error": "Invalid"}])
    assert openfigi.security("ES0000000000") is None
    assert "ES0000000000" not in openfigi._load()


def test_a_throttle_degrades_and_holds_off(monkeypatch):
    calls = []

    def post(jobs, key):
        calls.append(jobs)
        raise urllib.error.HTTPError("u", 429, "Too Many", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(openfigi, "_post", post)
    assert openfigi.securities(["ES0144580Y14"]) == {"ES0144580Y14": None}
    assert openfigi.home("ES0144580Y14") is None
    assert len(calls) == 1  # the second ask never left the process
    assert not openfigi.CACHE.exists()  # a refusal is not a miss


def test_the_minute_allowance_is_respected(figi, monkeypatch):
    monkeypatch.setattr(openfigi, "PER_MINUTE", 2)
    for n in range(4):
        openfigi.securities([f"XS{n:09d}0"])
    assert len(figi) == 2


def test_offline_is_no_answer_not_an_error():
    # The autouse fixture's `_post` raises ConnectionError.
    assert openfigi.securities(["ES0144580Y14", "not-an-isin"]) == {"ES0144580Y14": None}
    assert openfigi.home("ES0144580Y14") is None
    assert openfigi.candidates("ES0144580Y14", (".MC",)) == []


# ------------------------------------------------------- inside the resolver


@pytest.fixture
def yahoo(monkeypatch, tmp_path):
    """Yahoo's search stubbed; the ISIN and code maps point at tmp files."""
    asked: list[str] = []

    def fake_quotes(query, count, min_len=3):
        asked.append(query)
        return []

    monkeypatch.setattr(symbols, "_quotes", fake_quotes)
    monkeypatch.setattr(symbols, "ISIN_CACHE", tmp_path / "isin_symbols.json")
    monkeypatch.setattr(symbols, "CODE_CACHE", tmp_path / "code_symbols.json")
    monkeypatch.setattr(symbols, "_isin_memo", None)
    monkeypatch.setattr(symbols, "_isin_misses", set())
    monkeypatch.setattr(symbols, "_code_memo", None)
    monkeypatch.setattr(symbols, "_code_misses", set())
    monkeypatch.setattr(symbols, "_code_settled", set())
    monkeypatch.setattr(symbols, "_blocked_until", 0.0)
    return asked


def test_isin_resolves_to_the_home_line_without_asking_yahoo(figi, yahoo):
    assert symbols.symbol_for_isin("ES0144580Y14") == "IBE.MC"
    assert symbols.symbol_for_isin("US0846707026") == "BRK-B"
    assert yahoo == []
    assert json.loads(symbols.ISIN_CACHE.read_text()) == {
        "ES0144580Y14": "IBE.MC",
        "US0846707026": "BRK-B",
    }


def test_isin_falls_back_to_yahoo_when_openfigi_has_no_home(figi, yahoo, monkeypatch):
    monkeypatch.setattr(
        symbols,
        "_quotes",
        lambda q, n, min_len=3: [{"symbol": "VWRA.L", "quoteType": "ETF"}],
    )
    # An ETF has no primary line in OpenFIGI's eyes: Yahoo answers as before.
    assert symbols.symbol_for_isin("IE00BK5BQT80") == "VWRA.L"


def test_isin_falls_back_to_yahoo_when_openfigi_is_offline(yahoo, monkeypatch):
    monkeypatch.setattr(
        symbols,
        "_quotes",
        lambda q, n, min_len=3: [{"symbol": "IBE.MC", "quoteType": "EQUITY"}],
    )
    assert symbols.symbol_for_isin("ES0144580Y14") == "IBE.MC"


def test_a_code_with_an_isin_lands_on_the_home_line_never_the_floor(figi, yahoo):
    symbols._code_memo = {"IBE": "IBE.F"}
    assert symbols.symbol_for_code("IBE", "EUR", isin="ES0144580Y14") == "IBE.MC"
    assert json.loads(symbols.CODE_CACHE.read_text()) == {"IBE": "IBE.MC"}


def test_an_etf_line_must_agree_with_the_fills_when_they_exist(figi, yahoo):
    vetted: list[str] = []

    def vet(symbol):
        vetted.append(symbol)
        return symbol == "VWCE.MI"

    got = symbols.symbol_for_code("VWCE", "EUR", isin="IE00BK5BQT80", vet=vet)
    assert got == "VWCE.MI"
    assert vetted == ["VWCE.DE", "VWCE.MI"]


def test_an_etf_line_without_fills_follows_the_venue_order(figi, yahoo):
    got = symbols.symbol_for_code("VWCE", "EUR", isin="IE00BK5BQT80")
    assert got == "VWCE.DE"


def test_the_import_places_a_statements_isins_in_one_request(figi):
    import_statement._place_isins({"ES0144580Y14", "US0378331005", "IE00BK5BQT80"})
    assert [len(jobs) for jobs, _ in figi] == [3]
    import_statement._place_isins(set())
    assert len(figi) == 1


def test_parallel_callers_share_one_request(monkeypatch):
    """The importer's per-code lookups run in threads: one ISIN, one request."""
    import threading
    import time

    calls = []
    gate = threading.Event()

    def slow(jobs, key):
        calls.append([j["idValue"] for j in jobs])
        gate.wait(2)
        return [{"data": IBERDROLA} for _ in jobs]

    monkeypatch.setattr(openfigi, "_post", slow)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(openfigi.home("ES0144580Y14")))
        for _ in range(5)
    ]
    for t in threads:
        t.start()
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join(5)
    assert results == ["IBE.MC"] * 5
    assert calls == [["ES0144580Y14"]]


def test_a_big_statement_asks_its_batches_together(figi):
    isins = [f"XS{n:09d}0" for n in range(40)]
    assert set(openfigi.securities(isins)) == set(isins)
    assert sorted(len(jobs) for jobs, _ in figi) == [10, 10, 10, 10]
