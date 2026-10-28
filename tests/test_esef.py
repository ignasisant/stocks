"""ESEF annual statements — recorded ASML facts, filings.xbrl.org stubbed."""

import gzip
import json
import pathlib

import pandas as pd
import pytest

from stocks.data import esef
from stocks.data.fundamentals import RawFundamentals

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "esef_asml.json"
LEI = "724500Y6DUVHQD6OXN27"


@pytest.fixture
def doc() -> dict:
    return json.loads(FIXTURE.read_text())


def test_extract_maps_ifrs_concepts_to_statement_rows(doc):
    years = esef.extract(doc)
    assert sorted(years) == ["2023-12-31", "2024-12-31", "2025-12-31"]
    y = years["2024-12-31"]
    assert y["currency"] == "EUR"
    # the segment fact (dimensioned) did not replace the statement's revenue
    assert y["income"]["Total Revenue"] == 28_262_900_000.0
    assert y["income"]["Net Income"] == 8_349_000_000.0
    assert y["income"]["Diluted EPS"] == 21.21
    assert y["income"]["EBIT"] == pytest.approx(9_956_900_000 + 162_600_000)
    # yfinance's signs: capex and dividends paid are outflows
    assert y["cashflow"]["Capital Expenditure"] == pytest.approx(-3_205_600_000.0)
    assert y["cashflow"]["Free Cash Flow"] == pytest.approx(
        12_369_700_000 - 3_205_600_000
    )
    assert y["cashflow"]["Cash Dividends Paid"] == -2_452_900_000.0
    # a balance sheet is read at the instant the year closes (midnight after)
    assert y["balance"]["Total Assets"] == 52_566_500_000.0
    assert y["balance"]["Total Liabilities Net Minority Interest"] == pytest.approx(
        52_566_500_000 - 22_021_900_000
    )
    assert y["balance"]["Total Debt"] == pytest.approx(1_010_300_000 + 3_677_300_000)
    assert y["balance"]["Net Debt"] == pytest.approx(4_687_600_000 - 12_735_900_000)


def test_day_reads_midnight_as_the_previous_day():
    assert str(esef._day("2026-01-01T00:00:00", end=True)) == "2025-12-31"
    assert str(esef._day("2025-01-01T00:00:00", end=False)) == "2025-01-01"
    assert str(esef._day("2025-12-31", end=True)) == "2025-12-31"


def test_name_match_ignores_legal_suffix_and_accents():
    assert esef._name_match("ASML Holding N.V.", "ASML HOLDING NV")
    assert esef._name_match("Iberdrola, S.A.", "IBERDROLA SA")
    assert esef._name_match(
        "Industria de Diseño Textil, S.A.", "INDUSTRIA DE DISENO TEXTIL SA"
    )
    assert not esef._name_match("Iberdrola, S.A.", "IBERDROLA INMOBILIARIA SA")
    assert not esef._name_match("", "ASML")


def test_eligible_is_eu_uk_equity_only():
    assert esef.eligible("ASML.AS") and esef.eligible("BP.L")
    assert not esef.eligible("AAPL")
    assert not esef.eligible("SAP.DE")  # Germany is not indexed
    assert not esef.eligible("IBE.MC", {"quoteType": "ETF"})


def _filings(*periods) -> dict:
    return {
        "data": [
            {
                "id": str(i),
                "attributes": {
                    "period_end": p,
                    "json_url": f"/{LEI}/{p}.json",
                    "error_count": err,
                    "published": pub,
                },
            }
            for i, (p, err, pub) in enumerate(periods, 1)
        ]
    }


def test_list_filings_keeps_one_record_per_period(monkeypatch):
    monkeypatch.setattr(
        esef,
        "_get",
        lambda url, **kw: json.dumps(
            _filings(
                ("2025-12-31", 0, None),
                ("2025-12-31", 0, "2026-02-25 00:00:00"),
                ("2024-12-31", 0, None),
                ("2023-12-31", 0, None),
            )
        ).encode(),
    )
    rows = esef.list_filings(LEI, limit=2)
    assert [r["period_end"] for r in rows] == ["2025-12-31", "2024-12-31"]
    assert rows[0]["published"] == "2026-02-25"


@pytest.fixture
def web(monkeypatch, doc):
    """GLEIF + filings.xbrl.org as one fake host; counts what was fetched."""
    calls: list[str] = []

    def get(url, *, gzip_ok=False):
        calls.append(url)
        if "gleif" in url:
            return json.dumps({"data": [{"id": LEI}]}).encode()
        if "/api/entities" in url:
            return json.dumps(
                {"data": [{"attributes": {"identifier": LEI, "name": "ASML HOLDING NV"}}]}
            ).encode()
        if "/api/filings" in url:
            return json.dumps(
                _filings(("2025-12-31", 0, None), ("2024-12-31", 0, None))
            ).encode()
        return gzip.compress(json.dumps(doc).encode())

    monkeypatch.setattr(esef, "_get", get)
    return calls


def test_refresh_stores_years_and_rechecks_without_downloading_again(web):
    held = esef.refresh("ASML.AS", "ASML Holding N.V.", isin="NL0010273215")
    assert held and held["lei"] == LEI
    assert sorted(held["years"]) == ["2023-12-31", "2024-12-31", "2025-12-31"]
    docs = [u for u in web if u.endswith(".json")]
    assert len(docs) == 2

    web.clear()
    esef.refresh("ASML.AS", "ASML Holding N.V.")
    assert not [u for u in web if u.endswith(".json")]  # nothing new, no download
    got = esef.cached("ASML.AS")
    assert got and got.currency == "EUR" and "2025-12-31" in got.years


def test_name_lookup_when_no_isin(web):
    assert esef.resolve_lei("ASML.AS", "ASML Holding N.V.") == LEI
    assert any("/api/entities" in u for u in web)
    assert not any("gleif" in u for u in web)


def test_a_miss_is_remembered_then_retried(monkeypatch):
    monkeypatch.setattr(esef, "_get", lambda url, **kw: b'{"data": []}')
    assert esef.refresh("NOPE.MC", "Nope SA") is None
    assert esef.cached("NOPE.MC") is None
    known = esef._read_map()["NOPE.MC"]
    assert known["lei"] is None
    # inside the miss window it does not ask again
    monkeypatch.setattr(esef, "_get", lambda *a, **k: pytest.fail("asked again"))
    assert esef.resolve_lei("NOPE.MC", "Nope SA") is None


def test_upstream_failure_degrades_to_nothing():
    assert esef.refresh("ASML.AS", "ASML Holding N.V.") is None  # host refuses
    assert esef.cached("ASML.AS") is None


def _yahoo(day="2024-12-31", revenue=28.3e9) -> RawFundamentals:
    col = pd.Timestamp(day)
    return RawFundamentals(
        ticker="ASML.AS",
        info={
            "longName": "ASML Holding N.V.",
            "financialCurrency": "EUR",
            "quoteType": "EQUITY",
        },
        income=pd.DataFrame({col: [revenue, 1.0]}, index=["Total Revenue", "Other"]),
        balance=pd.DataFrame(),
        cashflow=pd.DataFrame(),
    )


def test_overlay_lays_filed_rows_over_yahoo_and_labels_the_source(web):
    esef.refresh("ASML.AS", "ASML Holding N.V.")
    out = esef.overlay(_yahoo(revenue=28.0e9))
    assert out.source == "ESEF"
    assert out.source_years[0] == "2025-12-31"
    assert out.income.at["Total Revenue", pd.Timestamp("2024-12-31")] == 28_262_900_000.0
    assert (
        out.income.at["Other", pd.Timestamp("2024-12-31")] == 1.0
    )  # untouched row stays
    # years Yahoo no longer shows are added, newest first
    assert list(out.income.columns) == sorted(out.income.columns, reverse=True)
    assert pd.Timestamp("2025-12-31") in out.income.columns
    assert not out.balance.empty and "Total Debt" in out.balance.index
    assert out.cashflow.at["Free Cash Flow", pd.Timestamp("2025-12-31")] > 0


def test_overlay_skips_a_year_whose_revenue_is_wildly_off(web):
    esef.refresh("ASML.AS", "ASML Holding N.V.")
    out = esef.overlay(_yahoo(revenue=28.2e9 * 1000))  # a unit mismatch
    kept = out.income.at["Total Revenue", pd.Timestamp("2024-12-31")]
    assert kept == 28.2e12


def test_overlay_leaves_other_currencies_us_names_and_misses_alone(web):
    esef.refresh("ASML.AS", "ASML Holding N.V.")
    clash = _yahoo()
    clash.info["financialCurrency"] = "USD"
    assert esef.overlay(clash) is clash
    us = _yahoo()
    us.ticker = "AAPL"
    assert esef.overlay(us) is us
    assert esef.overlay(us).source is None
    unknown = _yahoo()
    unknown.ticker = "NEW.AS"
    assert esef.overlay(unknown) is unknown  # first sight: Yahoo's frames


def test_overlay_never_raises(monkeypatch, web):
    esef.refresh("ASML.AS", "ASML Holding N.V.")
    monkeypatch.setattr(esef, "_merge", lambda *a: 1 / 0)
    raw = _yahoo()
    assert esef.overlay(raw) is raw
