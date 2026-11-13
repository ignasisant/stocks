"""Non-listed funds (Pictet-Security, Cobas, Vanguard Global Stock Index…).

Yahoo keeps a fund's daily NAV under a Morningstar id (0P0000XMWU.F) and
labels it MUTUALFUND; its German floor quotes (P3IE.MU) carry no prices.
OpenFIGI names an open-end fund's "home" with a Bloomberg mnemonic that is
no Yahoo symbol (ES0119199000 -> COBASIN.MC). Fixture rows are the live
answers, probed 2026-11-13 and trimmed; no network.
"""

import pytest

from stocks.analysis import trend
from stocks.data import asset_kind, funds, openfigi, symbols


def quote(sym, short, long=None, qtype="MUTUALFUND", exch="Frankfurt"):
    return {
        "symbol": sym,
        "shortname": short,
        "longname": long,
        "exchDisp": exch,
        "quoteType": qtype,
    }


# Yahoo's answer to "Pictet Security", in its own order.
PICTET = [
    quote("0P0000XMWU.F", "0P0000XMWU.F", "Pictet-Security HI EUR"),
    quote("P3IE.SG", "Pictet - Security Namens-Anteil", exch="Stuttgart"),
    quote("P3IE.MU", "Pictet - Security             N", qtype="ETF", exch="Munich"),
    quote("PIML.HM", "Pictet - Security             N", qtype="ETF", exch="Hamburg"),
    quote(
        "0P0001CB1C",
        'Pictet-Security I dy USD",',
        "Pictet-Security I dy USD",
        exch="OTC Markets",
    ),
    quote("0P00016FI9.F", "0P00016FI9.F", "Pictet-Security Z EUR"),
    quote("0P00017JP0.F", "0P00017JP0.F", "Pictet-Security HR EUR"),
]


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(symbols, "_blocked_until", 0.0)
    monkeypatch.setattr(symbols, "ISIN_CACHE", tmp_path / "isin_symbols.json")
    monkeypatch.setattr(symbols, "_isin_memo", None)
    monkeypatch.setattr(symbols, "_isin_misses", set())


def serve(monkeypatch, answers):
    """Yahoo's search answering per query (`answers[q]`), [] otherwise."""
    asked: list[str] = []

    def fake(url, **kw):
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(url).query)["q"][0]
        asked.append(q)
        rows = answers.get(q, answers.get("*", []))
        return {"quotes": rows}

    monkeypatch.setattr(symbols, "get_json", fake)
    return asked


# ----------------------------------------------------------------- the search


def test_search_offers_the_nav_lines_with_their_names(monkeypatch):
    serve(monkeypatch, {"*": PICTET})
    rows = symbols.search_rows("Pictet Security", limit=6)
    # The NAV lines first, each under the fund's own name and class; the one
    # floor quote that survives the issuer dedup goes last.
    assert [(r[0], r[1]) for r in rows] == [
        ("0P0000XMWU.F", "Pictet-Security HI EUR"),
        ("0P0001CB1C", "Pictet-Security I dy USD"),
        ("0P00016FI9.F", "Pictet-Security Z EUR"),
        ("0P00017JP0.F", "Pictet-Security HR EUR"),
        ("P3IE.SG", "Pictet - Security Namens-Anteil"),
    ]
    # The search box labels them as funds without another lookup.
    assert funds.quote_type("0P0000XMWU.F", fetch=False) == "MUTUALFUND"


def test_limit_cuts_after_the_floors_moved_down(monkeypatch):
    serve(monkeypatch, {"*": PICTET})
    assert [r[0] for r in symbols.search_rows("Pictet Security", limit=2)] == [
        "0P0000XMWU.F",
        "0P0001CB1C",
    ]


def test_share_search_keeps_yahoos_order(monkeypatch):
    # A share on a floor is not moved: for a share Yahoo's ranking stands.
    rows = [
        quote("IXD1.F", "Industria de Diseno Textil", qtype="EQUITY"),
        quote("ITX.MC", "Inditex", "Inditex SA", qtype="EQUITY", exch="Madrid"),
    ]
    serve(monkeypatch, {"*": rows})
    assert [r[0] for r in symbols.search_rows("inditex")] == ["IXD1.F", "ITX.MC"]


def test_classes_of_one_fund_are_not_collapsed(monkeypatch):
    # Each class is its own price (HI EUR ~345, Z EUR ~577): picking one for
    # another would misvalue the holding, so none swallows the next.
    serve(monkeypatch, {"*": PICTET})
    names = [r[1] for r in symbols.search_rows("Pictet Security", limit=10)]
    assert {
        "Pictet-Security HI EUR",
        "Pictet-Security Z EUR",
        "Pictet-Security HR EUR",
    } <= set(names)


# ----------------------------------------------------------------- the ISIN


@pytest.mark.parametrize(
    ("isin", "rows", "want"),
    [
        # Cobas Internacional C (Spain): the ISIN answers the NAV line.
        (
            "ES0119199000",
            [quote("0P00019W2R.F", "0P00019W2R.F", "Cobas Internacional C FI")],
            "0P00019W2R.F",
        ),
        # Vanguard Global Stock Index Inv EUR (Ireland).
        (
            "IE00B03HCZ61",
            [
                quote(
                    "0P00000RQC.F",
                    "0P00000RQC.F",
                    "Vanguard Global Stock Index Inv EUR Acc",
                )
            ],
            "0P00000RQC.F",
        ),
        # Amundi IS Core Global Govt Bond (Luxembourg): Yahoo's ".LU" line.
        (
            "LU0389812693",
            [
                quote(
                    "LU0389812693.LU",
                    "LU0389812693.LU",
                    "Amundi IS Core Global Gvt Bd IHE-C",
                    exch="Luxembourg",
                )
            ],
            "LU0389812693.LU",
        ),
        # Fidelity MSCI World Index P: a floor quote first, the NAV below it.
        (
            "IE00BYX5NX33",
            [
                quote("IE00BYX5NX33.SG", "IE00BYX5NX33.SG", exch="Stuttgart"),
                quote(
                    "0P0001CLDK.F", "0P0001CLDK.F", "Fidelity MSCI World Index EUR P Acc"
                ),
            ],
            "0P0001CLDK.F",
        ),
    ],
)
def test_fund_isin_resolves_to_its_nav_line(monkeypatch, isin, rows, want):
    serve(monkeypatch, {isin: rows})
    assert symbols.symbol_for_isin(isin) == want
    assert symbols.cached_isin_symbol(isin) == want  # what prices it from now on


def test_fund_isin_yahoo_does_not_know_stays_unresolved(monkeypatch):
    # Pictet-Security P EUR: Yahoo has the NAV (0P00006SZ0.F) but not under
    # this ISIN. No guess by name — a wrong class is a wrong price — so the
    # holding stays at cost, as any unlisted line does.
    serve(monkeypatch, {"LU0270904781": []})
    assert symbols.symbol_for_isin("LU0270904781") is None


def test_open_end_fund_never_takes_openfigis_mnemonic(monkeypatch):
    """OpenFIGI's "home" for an open-end fund is a Bloomberg mnemonic
    (SM COBASIN), which as COBASIN.MC is no Yahoo symbol at all."""

    def post(jobs, key):
        return [
            {
                "data": [
                    {
                        "name": "COBAS INTERNATIONAL FI C",
                        "ticker": "COBASIN",
                        "exchCode": "SM",
                        "compositeFIGI": "BBG00G75ZN33",
                        "securityType": "Open-End Fund",
                        "securityType2": "Mutual Fund",
                    }
                ]
            }
            for _ in jobs
        ]

    monkeypatch.setattr(openfigi, "_post", post)
    sec = openfigi.security("ES0119199000")
    assert sec is not None and sec.open_end
    assert openfigi.home("ES0119199000") is None
    assert openfigi.candidates("ES0119199000", (".MC",)) == []
    serve(
        monkeypatch,
        {
            "ES0119199000": [
                quote("0P00019W2R.F", "0P00019W2R.F", "Cobas Internacional C FI")
            ]
        },
    )
    assert symbols.symbol_for_isin("ES0119199000") == "0P00019W2R.F"


def test_an_etf_keeps_its_openfigi_lines(monkeypatch):
    def post(jobs, key):
        return [
            {
                "data": [
                    {
                        "name": "AMUNDI MSCI WORLD",
                        "ticker": "CW8",
                        "exchCode": "FP",
                        "compositeFIGI": "BBG0",
                        "securityType": "ETP",
                        "securityType2": "Mutual Fund",
                    }
                ]
            }
            for _ in jobs
        ]

    monkeypatch.setattr(openfigi, "_post", post)
    assert openfigi.home("FR0010315770") == "CW8.PA"


def test_a_fund_entry_cached_without_its_type_is_asked_again():
    old = {"at": 9e12, "kind": "Mutual Fund", "name": "X", "figi": "", "listings": []}
    assert not openfigi._fresh(old, 9e12)
    assert openfigi._fresh({**old, "type": "ETP"}, 9e12)
    stock = {"at": 9e12, "kind": "Common Stock", "listings": []}
    assert openfigi._fresh(stock, 9e12)


# ------------------------------------------------- broker codes stay shares


def test_a_broker_code_never_lands_on_a_nav_line(monkeypatch):
    serve(monkeypatch, {"*": [quote("P3IE.DE", "Pictet Security")]})
    monkeypatch.setattr(symbols, "CODE_CACHE", symbols.ISIN_CACHE.parent / "c.json")
    monkeypatch.setattr(symbols, "_code_memo", None)
    monkeypatch.setattr(symbols, "_code_misses", set())
    assert symbols.symbol_for_code("P3IE", "EUR") is None


# --------------------------------------------------------------- the lines


@pytest.mark.parametrize(
    ("symbol", "nav", "floor"),
    [
        ("0P0000XMWU.F", True, False),  # Frankfurt feed, not the floor
        ("0P0000RU81.L", True, False),
        ("0P0001CB1C", True, False),
        ("0p0000xmwu.f", True, False),
        ("P3IE.MU", False, True),
        ("MEQA.F", False, True),
        ("SAP.DE", False, False),
        ("0P00", False, False),
    ],
)
def test_nav_lines_are_not_floors(symbol, nav, floor):
    assert symbols.is_nav_line(symbol) is nav
    assert symbols.on_floor(symbol) is floor


def test_a_nav_line_reads_against_no_market_index():
    # ".F" is where Yahoo files Morningstar's feed, and a bare id is a Pink
    # sheets line: neither says the fund's market is the DAX or the S&P 500.
    assert trend.benchmark_for("0P0000XMWU.F") is None
    assert trend.benchmark_for("0P0001CB1C") is None
    assert trend.benchmark_for("SAP.DE").ticker == "^GDAXI"
    assert trend.benchmark_for("AAPL").ticker == "^GSPC"


# ------------------------------------------------------------------ the kind


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Pictet-Security HI EUR", asset_kind.EQUITY_FUND),
        ("Cobas Internacional C FI", asset_kind.EQUITY_FUND),
        ("Vanguard Global Stock Index Inv EUR Acc", asset_kind.EQUITY_FUND),
        ("Fundsmith Equity T EUR Acc", asset_kind.EQUITY_FUND),
        ("BGF Euro Short Duration Bond D2", asset_kind.BOND_FUND),
        ("Amundi IS Core Global Gvt Bd IHE-C", asset_kind.BOND_FUND),
        ("Amundi Euro Liquidity Select P C", asset_kind.MONEY_MARKET),
        ("Groupama Trésorerie IC", asset_kind.MONEY_MARKET),
        ("Santander Tesorería FI", asset_kind.MONEY_MARKET),
        ("DWS Euro Money Market Fund", asset_kind.MONEY_MARKET),
    ],
)
def test_a_mutual_fund_is_laid_out_by_its_name(name, kind):
    assert (
        asset_kind.classify(symbol="0P0000XMWU.F", quote_type="MUTUALFUND", name=name)
        == kind
    )
