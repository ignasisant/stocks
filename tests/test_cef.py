"""Closed-end funds: detection, the filed figures, and the cross-check.

Yahoo files a listed closed-end fund (MUA, PDI, UTF, NEA) as ``EQUITY``, so the
ticker page used to read one as a company and print empty fundamentals. These
pin the three things that replaced that:

- Detection asks EDGAR which forms the filer files, never a name pattern
  first, and a company (AAPL), a bank, a BDC (ARCC) or an ETF (SPY) is never
  mistaken for a fund — including when EDGAR is down.
- Every figure carries its source and date, and an empty one names the
  sources asked instead of reading as zero.
- Where EDGAR files a figure Yahoo also prints, the two are compared on
  EDGAR's date, and a disagreement comes back as one — both numbers kept.

Offline throughout: every network hop in `stocks.data.cef` is a seam these
replace, and the verdict cache lives in tmp_path.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.data import cef

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _subs(*forms: str, **extra) -> dict:
    """An EDGAR submissions payload carrying `forms` in `filings.recent`."""
    n = len(forms)
    recent = {
        "form": list(forms),
        "accessionNumber": extra.get(
            "accessions", [f"0000-26-{i:06d}" for i in range(n)]
        ),
        "reportDate": extra.get("reports", [""] * n),
        "filingDate": extra.get("filed", ["2026-09-01"] * n),
        "primaryDocument": ["primary_doc.xml"] * n,
    }
    return {"cik": "901243", "filings": {"recent": recent}}


# What each filer's recent index actually carries (trimmed, form types only).
MUA_FORMS = ("NPORT-P", "N-CSRS", "N-2/A", "424B2", "N-CSR", "497", "8-K", "SC 13D/A")
AAPL_FORMS = ("10-K", "10-Q", "8-K", "4", "DEF 14A")
ARCC_FORMS = ("10-K", "10-Q", "N-2", "497", "424B2", "8-K")  # a BDC
SPY_FORMS = ("N-CSR", "24F-2NT", "485BPOS", "NPORT-P")  # open-end also files N-CSR
QQQ_FORMS = ("N-CSR", "N-CSRS", "497K", "485BPOS")


# ----------------------------------------------------------- classification


@pytest.mark.parametrize(
    ("forms", "expected"),
    [
        (MUA_FORMS, True),
        (("N-CSRS",), True),
        # A fund too new for its first shareholder report.
        (("N-2", "NPORT-P", "497"), True),
        (AAPL_FORMS, False),
        (ARCC_FORMS, False),
        (SPY_FORMS, False),
        (QQQ_FORMS, False),
        (("NPORT-P",), False),
        (("N-2",), False),
        ((), False),
    ],
)
def test_the_form_signature_is_a_closed_end_funds_and_nothing_elses(forms, expected):
    assert cef.classify_forms(forms) is expected


def test_the_nav_line_is_the_symbol_between_two_xs():
    assert cef.nav_symbol("mua") == "XMUAX"


# ---------------------------------------------------------------- detection


class Net:
    """Every hop `is_closed_end` can make, scripted and counted."""

    def __init__(self, monkeypatch, *, quote="EQUITY", stored=None, cik="0000901243"):
        self.calls: list[str] = []
        self.infos: dict[str, dict] = {}
        self.forms: tuple[str, ...] | Exception = MUA_FORMS
        monkeypatch.setattr("stocks.data.fetch.resolve", lambda t: t)
        monkeypatch.setattr("stocks.data.funds.quote_type", lambda t, fetch=True: quote)
        monkeypatch.setattr(
            "stocks.data.profiles.known", lambda t: dict(stored) if stored else None
        )
        monkeypatch.setattr(cef, "_cik", lambda t: self._hit("cik", cik))
        monkeypatch.setattr(cef, "_info", self._info)
        monkeypatch.setattr(cef, "_submissions", self._submissions)

    def _hit(self, name, value):
        self.calls.append(name)
        return value

    def _info(self, symbol):
        self.calls.append(f"info:{symbol}")
        return self.infos.get(symbol, {})

    def _submissions(self, cik, timeout):
        self.calls.append("edgar")
        if isinstance(self.forms, Exception):
            raise self.forms
        return _subs(*self.forms)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cef, "CEF_CACHE", tmp_path / "closed_end.json")
    monkeypatch.setattr(cef, "_verdicts", None)
    monkeypatch.setattr(cef, "_failed_at", {})
    monkeypatch.setattr(cef, "_subs_memo", {})
    monkeypatch.setenv("API_TOKEN", TOKEN)
    yield
    monkeypatch.setattr(cef, "_verdicts", None)


ASSET_MANAGER = {
    "sector": "Financial Services",
    "industry": "Asset Management",
    "longName": "BlackRock MuniAssets Fund, Inc.",
}


def test_edgar_settles_a_closed_end_fund_and_the_answer_is_kept(monkeypatch):
    net = Net(monkeypatch, stored={"sector": "Financial Services"})
    net.infos["MUA"] = ASSET_MANAGER
    assert cef.is_closed_end("mua") is True
    assert "edgar" in net.calls
    assert '"MUA": true' in cef.CEF_CACHE.read_text()

    # Next process: straight from disk, no request at all.
    monkeypatch.setattr(cef, "_verdicts", None)
    net.calls.clear()
    assert cef.is_closed_end("MUA") is True
    assert net.calls == []


def test_a_company_outside_finance_is_never_sent_to_edgar(monkeypatch):
    net = Net(monkeypatch, stored={"sector": "Technology", "quoteType": "EQUITY"})
    assert cef.is_closed_end("AAPL") is False
    assert "edgar" not in net.calls


def test_a_bank_is_ruled_out_by_its_industry_without_edgar(monkeypatch):
    net = Net(monkeypatch, stored={"sector": "Financial Services"})
    net.infos["JPM"] = {"sector": "Financial Services", "industry": "Banks - Diversified"}
    assert cef.is_closed_end("JPM") is False
    assert "edgar" not in net.calls


def test_a_bdc_files_like_a_company_and_stays_one(monkeypatch):
    net = Net(monkeypatch)
    net.infos["ARCC"] = {"sector": "Financial Services", "industry": "Asset Management"}
    net.forms = ARCC_FORMS
    assert cef.is_closed_end("ARCC") is False
    assert '"ARCC": false' in cef.CEF_CACHE.read_text()


def test_an_etf_is_a_fund_already_and_is_not_asked_about(monkeypatch):
    net = Net(monkeypatch, quote="ETF")
    assert cef.is_closed_end("SPY") is False
    assert net.calls == []


@pytest.mark.parametrize("symbol", ["SAN.MC", "BTC-EUR", "", "TOOLONG"])
def test_only_plain_us_symbols_are_candidates(monkeypatch, symbol):
    net = Net(monkeypatch)
    assert cef.is_closed_end(symbol) is False
    assert net.calls == []


def test_no_sec_filer_no_question(monkeypatch):
    net = Net(monkeypatch, cik=None)
    assert cef.is_closed_end("ZZQQ") is False
    assert "edgar" not in net.calls


def test_the_cache_only_read_never_fetches(monkeypatch):
    net = Net(monkeypatch)
    assert cef.is_closed_end("MUA", fetch=False) is False
    assert net.calls == []


def test_edgar_down_falls_back_to_the_nav_line_and_does_not_cache(monkeypatch):
    net = Net(monkeypatch)
    net.infos["MUA"] = ASSET_MANAGER
    net.infos["XMUAX"] = {
        "quoteType": "MUTUALFUND",
        "longName": "BlackRock MuniAssets Fund, Inc.",
    }
    net.forms = TimeoutError("sec.gov timed out")
    assert cef.is_closed_end("MUA") is True
    assert not cef.CEF_CACHE.exists()  # a guess is asked again, not kept

    # Within the back-off the fallback answers without waiting on EDGAR.
    net.calls.clear()
    assert cef.is_closed_end("MUA") is True
    assert "edgar" not in net.calls


def test_a_nav_line_under_another_name_is_not_this_funds(monkeypatch):
    net = Net(monkeypatch)
    net.infos["ABC"] = {**ASSET_MANAGER, "longName": "Abc Asset Management Holdings"}
    net.infos["XABCX"] = {"quoteType": "MUTUALFUND", "longName": "Xtreme Bond Fund"}
    net.forms = OSError("down")
    assert cef.is_closed_end("ABC") is False


def test_the_description_is_the_last_resort(monkeypatch):
    net = Net(monkeypatch)
    net.infos["GAB"] = {
        **ASSET_MANAGER,
        "longName": "Gabelli Equity Trust",
        "longBusinessSummary": (
            "The Gabelli Equity Trust is a closed-ended equity mutual fund."
        ),
    }
    net.forms = OSError("down")
    assert cef.is_closed_end("GAB") is True


# ------------------------------------------------------------------ filings

NPORT = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <headerData><submissionType>NPORT-P</submissionType></headerData>
  <formData>
    <genInfo>
      <regName>BlackRock MuniAssets Fund, Inc.</regName>
      <seriesName>BlackRock MuniAssets Fund, Inc.</seriesName>
      <repPdEnd>2026-07-31</repPdEnd>
      <repPdDate>2026-07-31</repPdDate>
    </genInfo>
    <fundInfo>
      <totAssets>841226880.94</totAssets>
      <totLiabs>282599797.96</totLiabs>
      <netAssets>558627082.98</netAssets>
      <liquidPref>251000000.00</liquidPref>
    </fundInfo>
    <invstOrSecs>
      <invstOrSec>
        <name>Public Finance Authority</name>
        <title>PUBLIC FIN AUTH WI REVENUE 2044</title>
        <valUSD>30000000.00</valUSD><pctVal>5.37</pctVal>
        <assetCat>DBT</assetCat>
      </invstOrSec>
      <invstOrSec>
        <name>PUBLIC FINANCE AUTHORITY</name>
        <title>PUBLIC FIN AUTH WI REVENUE 2051</title>
        <valUSD>24000000.00</valUSD><pctVal>4.30</pctVal>
        <assetCat>DBT</assetCat>
      </invstOrSec>
      <invstOrSec>
        <name>Commonwealth of Puerto Rico</name>
        <valUSD>38000000.00</valUSD><pctVal>6.84</pctVal>
        <assetCat>DBT</assetCat>
      </invstOrSec>
      <invstOrSec>
        <name>BlackRock Liquidity Funds MuniCash</name>
        <valUSD>4000000.00</valUSD><pctVal>0.72</pctVal>
        <assetCat>STIV</assetCat>
      </invstOrSec>
      <invstOrSec>
        <name>Rate swap</name>
        <valUSD>-150000.00</valUSD><pctVal>-0.03</pctVal>
        <assetConditional assetCat="OTHER" description="swap"/>
      </invstOrSec>
    </invstOrSecs>
  </formData>
</edgarSubmission>
"""


def test_an_nport_reads_to_balance_sheet_issuers_and_mix():
    n = cef.parse_nport(NPORT)
    assert n.report_date == "2026-07-31"
    assert n.name == "BlackRock MuniAssets Fund, Inc."
    assert n.net_assets == pytest.approx(558627082.98)
    # Liabilities (preferred shares and borrowings included) over total assets.
    assert n.leverage == pytest.approx(1 - 558627082.98 / 841226880.94)
    assert n.holdings_count == 5
    # One issuer across two bond lines is one row, case-insensitively; a
    # negative line (a swap marked down) is no holding.
    names = [(h.name, round(h.weight, 4)) for h in n.holdings]
    assert names == [
        ("Public Finance Authority", 0.0967),
        ("Commonwealth of Puerto Rico", 0.0684),
        ("BlackRock Liquidity Funds MuniCash", 0.0072),
    ]
    assert all(h.symbol == "" for h in n.holdings)
    mix = dict(n.asset_mix)
    assert mix["Bonds"] == pytest.approx(92 / 96)
    assert mix["Cash"] == pytest.approx(4 / 96)
    assert "Other" not in mix  # only positive investments make the mix


def test_an_nport_with_a_dtd_is_refused():
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
    with pytest.raises(ValueError):
        cef.parse_nport(evil)


def test_the_newest_nport_wins_amendments_included():
    subs = _subs(
        "NPORT-P",
        "N-CSR",
        "NPORT-P/A",
        "NPORT-P",
        accessions=["a-1", "b-2", "c-3", "d-4"],
        reports=["2026-04-30", "2026-04-30", "2026-07-31", "2026-06-30"],
        filed=["2026-06-25", "2026-07-01", "2026-09-26", "2026-08-27"],
    )
    assert cef.latest_nport(subs) == ("c-3", "2026-07-31")
    assert cef.latest_nport(_subs("N-CSR")) is None


def _facts(nav=None, premium=None, expense=None) -> dict:
    def unit(rows):
        return [
            {"end": end, "val": val, "filed": filed, "form": form}
            for end, val, filed, form in rows
        ]

    facts: dict = {"us-gaap": {}, "cef": {}}
    if nav:
        facts["us-gaap"]["NetAssetValuePerShare"] = {"units": {"USD/shares": unit(nav)}}
    if premium:
        facts["cef"]["LatestPremiumDiscountToNavPercent"] = {
            "units": {"pure": unit(premium)}
        }
    if expense:
        facts["cef"]["TotalAnnualExpensesPercent"] = {"units": {"pure": unit(expense)}}
    return {"facts": facts}


# PDI as filed: the June N-CSR, then the August figures in its N-2ASR.
PDI_FACTS = _facts(
    nav=[
        ("2026-06-30", 15.93, "2026-08-28", "N-CSR"),
        ("2026-08-31", 15.60, "2026-09-24", "N-2ASR"),
    ],
    premium=[
        ("2026-06-30", 0.0483, "2026-08-28", "N-CSR"),
        ("2026-08-31", -0.0263, "2026-09-24", "N-2ASR"),
    ],
    expense=[("2026-09-24", 0.0379, "2026-09-24", "N-2ASR")],
)


def test_xbrl_latest_takes_the_latest_period():
    assert cef.xbrl_latest(
        PDI_FACTS, "us-gaap", "NetAssetValuePerShare", "USD/shares"
    ) == (
        "2026-08-31",
        15.60,
        "N-2ASR",
    )
    assert cef.xbrl_latest(None, "cef", "X", "pure") is None
    assert cef.xbrl_latest(PDI_FACTS, "cef", "Missing", "pure") is None


# ------------------------------------------------------------------ profile

PRICE = {
    "2026-08-31": 15.19,
    "2026-09-25": 13.95,
    "2026-09-28": 13.90,
    "2026-09-29": 14.05,
}
NAV = {"2026-08-31": 15.60, "2026-09-25": 15.02, "2026-09-28": 15.00}
PDI_INFO = {
    "longName": "PIMCO Dynamic Income Fund",
    "currency": "USD",
    "dividendRate": 2.65,
    "trailingAnnualDividendRate": 0.0,
    "regularMarketPrice": 14.05,
}


def _profile(
    *, nav_closes: dict | None = None, facts: dict | None = None
) -> cef.ClosedEndProfile:
    return cef.build_profile(
        "PDI",
        PDI_INFO,
        price_closes=PRICE,
        nav_closes=NAV if nav_closes is None else nav_closes,
        facts=facts or PDI_FACTS,
        nport=cef.parse_nport(NPORT),
    )


def test_every_figure_names_its_source_and_date():
    p = _profile()
    assert (p.nav.value, p.nav.source, p.nav.as_of) == (15.00, "yahoo_nav", "2026-09-28")
    # The premium pairs the last session BOTH lines have: the listed line's
    # live 09-29 row has no NAV yet, and must not be divided by 09-28's.
    assert p.price.as_of == "2026-09-28"
    assert p.premium.value == pytest.approx(13.90 / 15.00 - 1)
    assert p.premium.source == "yahoo_nav"
    assert p.distribution_rate.value == pytest.approx(2.65 / 14.05)
    assert p.distribution_rate.source == "yahoo"
    assert (p.expense_ratio.value, p.expense_ratio.source) == (0.0379, "edgar_xbrl")
    assert (p.net_assets.source, p.net_assets.as_of) == ("edgar_nport", "2026-07-31")
    assert p.leverage.value == pytest.approx(1 - 558627082.98 / 841226880.94)
    assert p.nav_symbol == "XPDIX"
    assert p.is_bond_fund is True


def test_edgar_and_yahoo_agreeing_on_edgars_date_is_a_passed_check():
    checks = {c.metric: c for c in _profile().checks}
    assert checks["nav"].as_of == "2026-08-31"
    assert (checks["nav"].official, checks["nav"].market) == (15.60, 15.60)
    assert checks["nav"].agree is True
    assert checks["premium"].market == pytest.approx(15.19 / 15.60 - 1)
    assert checks["premium"].agree is True


def test_a_disagreement_is_returned_as_one_with_both_numbers():
    nav = NAV | {"2026-08-31": 16.40}  # Yahoo 5% off what the fund filed
    checks = {c.metric: c for c in _profile(nav_closes=nav).checks}
    assert checks["nav"].agree is False
    assert (checks["nav"].official, checks["nav"].market) == (15.60, 16.40)
    assert checks["nav"].official_source == "edgar_xbrl"
    assert checks["nav"].market_source == "yahoo_nav"
    # The headline NAV is still Yahoo's latest, not quietly swapped for EDGAR's.
    assert _profile(nav_closes=nav).nav.value == 15.00


def test_no_market_row_for_the_filed_date_is_unchecked_not_agreed():
    late = {"2026-09-28": 15.00}  # Yahoo's NAV series starts after 08-31
    checks = {c.metric: c for c in _profile(nav_closes=late).checks}
    assert checks["nav"].market is None and checks["nav"].agree is None
    assert checks["premium"].agree is None


def test_a_weekend_filing_date_is_priced_on_the_friday():
    facts = _facts(nav=[("2026-08-30", 15.60, "2026-09-24", "N-2ASR")])  # a Sunday
    nav = {"2026-08-28": 15.58, "2026-09-28": 15.00}
    (check,) = _profile(facts=facts, nav_closes=nav).checks
    assert check.market == 15.58 and check.agree is True


def test_a_missing_figure_names_every_source_asked():
    p = cef.build_profile(
        "NEA", {}, price_closes={}, nav_closes={}, facts=None, nport=None
    )
    assert p.nav.value is None and p.nav.tried == ("yahoo_nav", "edgar_xbrl")
    assert p.premium.tried == ("yahoo_nav", "edgar_xbrl")
    assert p.price.tried == ("yahoo",)
    assert p.distribution_rate.tried == ("yahoo",)
    assert p.expense_ratio.tried == ("edgar_xbrl",)
    assert p.net_assets.tried == ("edgar_nport",)
    assert p.leverage.tried == ("edgar_nport",)
    assert p.checks == ()


def test_edgar_stands_in_when_yahoos_nav_line_is_missing():
    p = _profile(nav_closes={})
    assert (p.nav.value, p.nav.source, p.nav.tried) == (
        15.60,
        "edgar_xbrl",
        ("yahoo_nav",),
    )
    assert (p.premium.value, p.premium.source) == (-0.0263, "edgar_xbrl")


def test_closed_end_profile_is_none_for_a_company(monkeypatch):
    monkeypatch.setattr("stocks.data.fetch.resolve", lambda t: t)
    monkeypatch.setattr(cef, "is_closed_end", lambda t, fetch=True: False)
    assert cef.closed_end_profile("AAPL") is None


def test_closed_end_profile_survives_a_missing_nport(monkeypatch):
    monkeypatch.setattr("stocks.data.fetch.resolve", lambda t: t)
    monkeypatch.setattr(cef, "is_closed_end", lambda t, fetch=True: True)
    monkeypatch.setattr(cef, "_info", lambda s: PDI_INFO)
    monkeypatch.setattr(cef, "_cik", lambda t: "0000898300")
    monkeypatch.setattr(cef, "_submissions", lambda cik, timeout: _subs("NPORT-P"))
    monkeypatch.setattr(
        cef, "_get_bytes", lambda url, timeout: (_ for _ in ()).throw(OSError("404"))
    )
    monkeypatch.setattr(cef, "_company_facts", lambda t: PDI_FACTS)
    monkeypatch.setattr(cef, "_daily_closes", lambda s: NAV if s == "XPDIX" else PRICE)
    p = cef.closed_end_profile("PDI")
    assert p is not None
    assert p.nav.value == 15.00
    assert p.net_assets.tried == ("edgar_nport",)
    assert p.holdings == ()


# -------------------------------------------------------------------- route


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


def test_the_fund_route_serves_a_closed_end_fund_with_its_sources(client, monkeypatch):
    nav = NAV | {"2026-08-31": 16.40}
    monkeypatch.setattr(loaders, "fund_profile", lambda t: None)
    monkeypatch.setattr(loaders, "closed_end", lambda t: _profile(nav_closes=nav))
    body = client.get("/v1/ticker/PDI/fund", headers=AUTH).json()
    assert body["is_fund"] is True
    assert body["quote_type"] == "CEF"
    assert body["aum"] == pytest.approx(558627082.98)
    assert body["expense_ratio"] == 0.0379
    assert body["holdings"][0]["name"] == "Public Finance Authority"
    ce = body["closed_end"]
    assert ce["nav_symbol"] == "XPDIX"
    assert ce["nav"] == {
        "value": 15.0,
        "source": "yahoo_nav",
        "as_of": "2026-09-28",
        "tried": [],
    }
    nav_check = next(c for c in ce["checks"] if c["metric"] == "nav")
    assert nav_check["agree"] is False
    assert (nav_check["official"], nav_check["market"]) == (15.6, 16.4)


def test_an_empty_figure_crosses_the_wire_as_null_with_what_was_tried(
    client, monkeypatch
):
    empty = cef.build_profile(
        "NEA", {}, price_closes={}, nav_closes={}, facts=None, nport=None
    )
    monkeypatch.setattr(loaders, "fund_profile", lambda t: None)
    monkeypatch.setattr(loaders, "closed_end", lambda t: empty)
    ce = client.get("/v1/ticker/NEA/fund", headers=AUTH).json()["closed_end"]
    assert ce["nav"] == {
        "value": None,
        "source": None,
        "as_of": None,
        "tried": ["yahoo_nav", "edgar_xbrl"],
    }
    assert ce["checks"] == []


def test_a_company_is_still_not_a_fund(client, monkeypatch):
    monkeypatch.setattr(loaders, "fund_profile", lambda t: None)
    monkeypatch.setattr(loaders, "closed_end", lambda t: None)
    body = client.get("/v1/ticker/AAPL/fund", headers=AUTH).json()
    assert body["is_fund"] is False
    assert body["closed_end"] is None
