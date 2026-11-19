"""Insider Form 4 tests — pure parse + aggregation, no network."""

from datetime import date

import pytest

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


# ----------------------------------------------------------- Finnhub's feed
# The same Form 4 lines, one request for the year instead of a document per
# filing. EDGAR is read when Finnhub has nothing for the name.
FINNHUB_ROWS = [
    {
        "name": "Cook Jane D",
        "share": 9000,
        "change": -1000,
        "filingDate": "2026-07-03",
        "transactionDate": "2026-07-01",
        "transactionCode": "S",
        "transactionPrice": 200.0,
        "isDerivative": False,
    },
    {
        "name": "Doe John",
        "share": 500,
        "change": 500,
        "filingDate": "2026-06-20",
        "transactionDate": "2026-06-18",
        "transactionCode": "P",
        "transactionPrice": 150.0,
        "isDerivative": False,
    },
    {  # an option line: not a share trade
        "name": "Doe John",
        "change": 10000,
        "transactionDate": "2026-07-02",
        "transactionCode": "M",
        "transactionPrice": 0,
        "isDerivative": True,
    },
    {  # a holding line, no trade on it
        "name": "Roe Sam",
        "change": 0,
        "transactionDate": "2026-07-02",
        "transactionCode": "",
        "isDerivative": False,
    },
    {  # a grant with no price
        "name": "Roe Sam",
        "change": 300,
        "transactionDate": "2026-05-05",
        "transactionCode": "A",
        "transactionPrice": 0,
        "isDerivative": False,
    },
]


def test_from_finnhub_maps_the_share_lines_newest_first():
    from stocks.data.insiders import from_finnhub

    txs = from_finnhub("EXPL", FINNHUB_ROWS)
    assert [(t.date, t.insider, t.code, t.acquired, t.shares, t.price) for t in txs] == [
        (date(2026, 7, 1), "Cook Jane D", "S", False, 1000.0, 200.0),
        (date(2026, 6, 18), "Doe John", "P", True, 500.0, 150.0),
        (date(2026, 5, 5), "Roe Sam", "A", True, 300.0, None),
    ]
    assert all(t.ticker == "EXPL" and t.source == "SEC" for t in txs)
    assert all(t.relationship == "" for t in txs)  # no role on the feed
    # They feed the same signal the filings do.
    assert summarize(txs, ref=REF).sell_count == 1


def test_a_us_name_is_read_from_finnhub_and_edgar_is_left_alone(monkeypatch):
    from stocks.data import finnhub, insiders

    monkeypatch.setattr(finnhub, "api_key", lambda: "test-key")
    asked = []
    monkeypatch.setattr(
        finnhub,
        "insider_transactions",
        lambda symbol, start, end, **k: asked.append((symbol, (end - start).days))
        or FINNHUB_ROWS,
    )
    monkeypatch.setattr(insiders, "cik_for", lambda t: pytest.fail("read EDGAR"))
    txs = insiders.insider_transactions("BRK-B")
    assert len(txs) == 3
    assert asked == [("BRK.B", insiders.FINNHUB_LOOKBACK_DAYS)]


def test_edgar_is_read_when_finnhub_has_nothing(monkeypatch):
    from stocks.data import finnhub, insiders

    monkeypatch.setattr(finnhub, "api_key", lambda: "test-key")
    monkeypatch.setattr(finnhub, "insider_transactions", lambda *a, **k: [])
    asked = []
    monkeypatch.setattr(insiders, "cik_for", lambda t: asked.append(t) or None)
    assert insiders.insider_transactions("EXPL") == []
    assert asked == ["EXPL"]


def test_a_foreign_listing_is_not_asked_of_finnhub(monkeypatch):
    from stocks.data import finnhub, insiders

    monkeypatch.setattr(finnhub, "api_key", lambda: "test-key")
    monkeypatch.setattr(
        finnhub, "insider_transactions", lambda *a, **k: pytest.fail("asked")
    )
    monkeypatch.setattr(insiders, "cik_for", lambda t: None)
    assert insiders.insider_transactions("SAN.MC") == []


# ------------------------------------------------- routine vs deliberate buys


def _buy(day: date, who: str = "Boss", shares: float = 100,
         held: float | None = None) -> InsiderTx:
    return InsiderTx(day, who, "CEO", "P", True, shares, 10.0, held_after=held)


def _sell(day: date, who: str = "Boss") -> InsiderTx:
    return InsiderTx(day, who, "CEO", "S", False, 50, 10.0)


def test_a_buy_in_the_same_month_three_years_running_is_routine():
    from stocks.data.insiders import ROUTINE, buy_pattern

    history = [_buy(date(y, 3, 10)) for y in (2023, 2024, 2025, 2026)]
    assert buy_pattern(history[-1], history) == ROUTINE


def test_a_trader_every_year_who_buys_off_calendar_is_not_routine():
    from stocks.data.insiders import NOT_ROUTINE, buy_pattern

    # Traded each of the three years before, but no March buy in 2024.
    history = [_buy(date(2023, 3, 10)), _sell(date(2024, 8, 1)),
               _buy(date(2025, 3, 10)), _buy(date(2026, 3, 10))]
    assert buy_pattern(history[-1], history) == NOT_ROUTINE


def test_a_first_ever_buy_is_unclassified_not_deliberate():
    """No three-year track record, no habit to break (CMP 2012)."""
    from stocks.data.insiders import buy_pattern

    only = _buy(date(2026, 3, 10))
    assert buy_pattern(only, [only]) is None
    gap = [_buy(date(2023, 3, 10)), _buy(date(2025, 3, 10)), only]
    assert buy_pattern(only, gap) is None


def test_another_insiders_calendar_does_not_make_a_buy_routine():
    from stocks.data.insiders import buy_pattern

    history = [_buy(date(y, 3, 10), who="Director") for y in (2023, 2024, 2025)]
    first = _buy(date(2026, 3, 10), who="Boss")
    assert buy_pattern(first, [*history, first]) is None


def test_only_open_market_trades_build_the_track_record():
    from stocks.data.insiders import buy_pattern

    grants = [InsiderTx(date(y, 3, 10), "Boss", "CEO", "A", True, 50, 0.0)
              for y in (2023, 2024, 2025)]
    buy = _buy(date(2026, 3, 10))
    assert buy_pattern(buy, [*grants, buy]) is None


def test_only_open_market_buys_get_a_pattern():
    from stocks.data.insiders import buy_pattern

    history = [_sell(date(y, 3, 10)) for y in (2023, 2024, 2025, 2026)]
    assert buy_pattern(history[-1], history) is None


def test_summarize_counts_buyers_by_pattern_only_with_history():
    routine = [_buy(date(y, 6, 1), who="Calendar") for y in (2023, 2024, 2025, 2026)]
    past = [_sell(date(y, 2, 1), who="Boss") for y in (2023, 2024, 2025)]
    deliberate = _buy(date(2026, 6, 2), who="Boss")
    txs = [*routine, *past, deliberate]
    plain = summarize(txs, ref=REF)
    assert (plain.deliberate_buyers, plain.routine_buyers) == (0, 0)
    read = summarize(txs, ref=REF, history=txs)
    assert (read.buyers, read.deliberate_buyers, read.routine_buyers) == (2, 1, 1)
    assert read.cluster_buy is True  # its meaning does not change


def test_stake_change_is_against_the_holding_before():
    from stocks.data.insiders import stake_change

    assert stake_change(_buy(date(2026, 1, 1), shares=100, held=500)) == 0.25
    # A first stake: nothing before it to grow.
    assert stake_change(_buy(date(2026, 1, 1), shares=100, held=100)) is None
    assert stake_change(_buy(date(2026, 1, 1), held=None)) is None


def test_from_finnhub_keeps_the_filing_date_and_the_holding_after():
    from stocks.data.insiders import from_finnhub

    rows = [{"name": "Doe", "change": 50, "share": 250, "filingDate": "2026-06-20",
             "transactionDate": "2026-06-18", "transactionCode": "P",
             "transactionPrice": 10.0, "isDerivative": False, "id": "a"}]
    (tx,) = from_finnhub("EXPL", rows)
    assert (tx.filed, tx.held_after) == (date(2026, 6, 20), 250.0)


def test_an_amended_filing_is_one_trade_not_two():
    """NKE, April 2026: a Form 4 and its 4/A both carried the same buy."""
    from stocks.data.insiders import from_finnhub

    line = {"name": "Hill", "change": 23660, "share": 265247,
            "transactionDate": "2026-04-13", "transactionCode": "P",
            "isDerivative": False}
    rows = [
        {**line, "filingDate": "2026-04-22", "transactionPrice": 42.27, "id": "amend"},
        {**line, "filingDate": "2026-04-14", "transactionPrice": 42.265, "id": "orig"},
    ]
    txs = from_finnhub("NKE", rows)
    assert len(txs) == 1 and txs[0].filed == date(2026, 4, 22)
    assert summarize(txs, ref=date(2026, 5, 1)).buy_shares == 23660


def test_two_equal_lines_in_one_filing_are_two_trades():
    from stocks.data.insiders import from_finnhub

    line = {"name": "Hill", "change": 100, "transactionDate": "2026-04-13",
            "transactionCode": "P", "transactionPrice": 10.0, "isDerivative": False,
            "filingDate": "2026-04-14", "id": "one"}
    assert len(from_finnhub("NKE", [line, dict(line)])) == 2


def test_parse_form4_reads_the_holding_after_and_the_signature_date():
    xml = FORM4_XML.replace(
        "</transactionAmounts>",
        "</transactionAmounts><postTransactionAmounts><sharesOwnedFollowingTransaction>"
        "<value>4000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>",
        1,
    ).replace(
        "</ownershipDocument>",
        "<ownerSignature><signatureDate>2026-07-03</signatureDate></ownerSignature>\n"
        "</ownershipDocument>",
    )
    sale = parse_form4(xml)[0]
    assert sale.held_after == 4000.0 and sale.filed == date(2026, 7, 3)


# ------------------------------------------------- roles for Finnhub's lines


def test_a_learnt_role_fills_a_blank_one_by_name_alone():
    from stocks.data.insiders import apply_roles

    finnhub_line = InsiderTx(date(2026, 9, 15), "Cook Jane D.", "", "P", True, 10, 5.0)
    edgar_line = InsiderTx(date(2026, 9, 15), "Roe Max", "Director", "S", False, 1, 5.0)
    out = apply_roles([finnhub_line, edgar_line],
                      {"COOK JANE D": "Chief Executive Officer", "ROE MAX": "CFO"})
    assert [t.relationship for t in out] == ["Chief Executive Officer", "Director"]


def test_with_roles_reads_what_is_learnt_and_asks_for_the_rest(monkeypatch):
    from stocks.data import insiders

    asked = []
    monkeypatch.setattr(insiders, "_learn_roles_later",
                        lambda ticker, wanted: asked.append((ticker, wanted)))
    today = date.today()
    insiders._roles_cache()["EXPL"] = {"at": "2000-01-01",
                                       "roles": {"COOK JANE D": "Director"}}
    txs = [InsiderTx(today, "Cook Jane D", "", "P", True, 1, 1.0),
           InsiderTx(today, "New Face", "", "P", True, 1, 1.0),
           InsiderTx(date(2001, 1, 1), "Long Gone", "", "S", False, 1, 1.0)]
    out = insiders.with_roles("expl", txs)
    assert [t.relationship for t in out] == ["Director", "", ""]
    # Only the year shown is worth a pass; a name from 2001 is not.
    assert asked == [("EXPL", {"NEW FACE"})]

    insiders._roles_cache()["EXPL"]["at"] = today.isoformat()
    asked.clear()
    insiders.with_roles("EXPL", txs)
    assert asked == []  # tried today already


def test_the_role_pass_stops_once_every_name_is_found(tmp_path, monkeypatch):
    import json

    from stocks.data import insiders

    monkeypatch.setattr(insiders, "FORM4_CACHE", tmp_path / "form4.json")
    insiders.clear_form4_cache()
    monkeypatch.setattr(insiders, "cik_for", lambda ticker: "0000001234")
    index = json.dumps({"filings": {"recent": {
        "form": ["4", "4", "4"],
        "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001-26-000003"],
        "primaryDocument": ["a.xml", "b.xml", "c.xml"],
    }}}).encode()
    calls: list[str] = []

    def get(url: str) -> bytes:
        calls.append(url)
        return index if url.startswith("https://data.sec.gov/") else FORM4_XML.encode()

    monkeypatch.setattr(insiders, "_get", get)
    insiders._learn_roles("EXPL", {"COOK JANE D"})
    assert len(calls) == 2  # the index and the first filing, not the other two
    entry = json.loads(insiders.ROLES_CACHE.read_text())["EXPL"]
    assert entry["roles"] == {"COOK JANE D": "Chief Executive Officer"}
    assert entry["at"] == date.today().isoformat()
    insiders.clear_form4_cache()
