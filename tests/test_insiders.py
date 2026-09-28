"""Insider Form 4 tests — pure parse + aggregation, no network."""

from datetime import date

from stocks.data.insiders import (
    InsiderTx,
    parse_form4,
    summarize,
    transactions_frame,
)

REF = date(2026, 7, 24)

# Minimal but realistic Form 4: a CEO open-market sale, a director open-market
# buy, and an RSU grant (code A) that must NOT count toward the buy/sell signal.
FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerName>Example Corp</issuerName>
    <issuerTradingSymbol>EXPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>COOK JANE D</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-07-01</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>200.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-06-15</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_parse_form4_reads_owner_role_and_transactions():
    txs = parse_form4(FORM4_XML)
    assert len(txs) == 2
    sale = txs[0]
    assert sale.insider == "COOK JANE D"
    assert sale.relationship == "Chief Executive Officer"
    assert sale.ticker == "EXPL"
    assert sale.code == "S"
    assert sale.acquired is False
    assert sale.shares == 1000
    assert sale.price == 200.0
    assert sale.value == 200000.0


def test_parse_form4_grant_has_no_price_signal():
    grant = parse_form4(FORM4_XML)[1]
    assert grant.code == "A"
    assert grant.acquired is True
    assert grant.is_open_market is False


def test_parse_form4_malformed_is_empty():
    assert parse_form4("<not-xml") == []
    assert parse_form4("<ownershipDocument></ownershipDocument>") == []


def test_summarize_counts_only_open_market_and_in_window():
    summary = summarize(parse_form4(FORM4_XML), ref=REF, within_days=180)
    # Only the P/S line inside the window counts; the grant (A) is excluded.
    assert summary.sell_count == 1
    assert summary.buy_count == 0
    assert summary.sell_value == 200000.0
    assert summary.sellers == 1
    assert summary.net_value == -200000.0


def test_summarize_window_excludes_old_trades():
    old = InsiderTx(date(2024, 1, 1), "OLD EXEC", "Director", "S", False, 999, 10.0)
    summary = summarize([old], ref=REF, within_days=180)
    assert not summary.has_activity


def test_summarize_cluster_buy_needs_multiple_buyers():
    buys = [
        InsiderTx(date(2026, 7, 1), "A", "Director", "P", True, 100, 50.0),
        InsiderTx(date(2026, 7, 2), "B", "CFO", "P", True, 200, 50.0),
    ]
    summary = summarize(buys, ref=REF)
    assert summary.buyers == 2
    assert summary.buy_value == 15000.0
    assert summary.cluster_buy is True

    single = summarize(buys[:1], ref=REF)
    assert single.cluster_buy is False


def test_transactions_frame_signs_and_sorts():
    df = transactions_frame(parse_form4(FORM4_XML))
    assert list(df.columns) == [
        "Date", "Insider", "Role", "Type", "Shares", "Price", "Value"
    ]
    # Newest first; dispositions carry a negative share/value sign.
    assert df.iloc[0]["Date"] == date(2026, 7, 1)
    assert df.iloc[0]["Shares"] == -1000
    assert df.iloc[0]["Value"] == -200000.0
    # The grant (acquisition) stays positive.
    assert df.iloc[1]["Shares"] == 500


def test_transactions_frame_empty():
    assert transactions_frame([]).empty


def test_form4_documents_are_fetched_once_and_read_back_from_the_memo(
    tmp_path, monkeypatch
):
    """The index is live; the filings behind it never change. A second
    process reads them from disk and pays the index alone."""
    import json

    from stocks.data import insiders

    monkeypatch.setattr(insiders, "FORM4_CACHE", tmp_path / "form4.json")
    insiders.clear_form4_cache()
    monkeypatch.setattr(insiders, "cik_for", lambda ticker: "0000001234")
    index = json.dumps(
        {
            "filings": {
                "recent": {
                    "form": ["4", "10-K", "4/A"],
                    "accessionNumber": [
                        "0001-24-000001", "0001-24-000002", "0001-24-000003",
                    ],
                    "primaryDocument": [
                        "xslF345X06/form4.xml", "10k.htm", "xslF345X06/form4a.xml",
                    ],
                }
            }
        }
    ).encode()
    calls: list[str] = []

    def get(url: str) -> bytes:
        calls.append(url)
        return index if url.startswith("https://data.sec.gov/") else FORM4_XML.encode()

    monkeypatch.setattr(insiders, "_get", get)

    first = insiders.insider_transactions("EXPL")
    assert len(first) == 2 * len(parse_form4(FORM4_XML))
    assert len(calls) == 3  # the index and the two Form 4 documents
    assert (tmp_path / "form4.json").exists()

    insiders.clear_form4_cache()  # a new process: the memo comes back from disk
    calls.clear()
    assert insiders.insider_transactions("EXPL") == first
    assert calls == ["https://data.sec.gov/submissions/CIK0000001234.json"]
    insiders.clear_form4_cache()
