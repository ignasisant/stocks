"""Related-tickers parsing — pure, no network."""

import pytest

import stocks.data.related as related
from stocks.data.related import parse_related, related_tickers

PAYLOAD = {
    "finance": {
        "result": [
            {
                "symbol": "NVDA",
                "recommendedSymbols": [
                    {"symbol": "AMD", "score": 0.13},
                    {"symbol": "AVGO", "score": 0.12},
                    {"symbol": "TSM", "score": 0.11},
                ],
            }
        ],
        "error": None,
    }
}


def test_parse_related():
    assert parse_related(PAYLOAD) == ["AMD", "AVGO", "TSM"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"finance": {}},
        {"finance": {"result": None}},
        {"finance": {"result": []}},
        {"finance": {"result": [{"symbol": "NVDA"}]}},
        {"finance": {"result": [{"recommendedSymbols": None}]}},
    ],
)
def test_parse_related_malformed(payload):
    assert parse_related(payload) == []


def test_related_tickers_drops_self(monkeypatch):
    self_ref = {
        "finance": {
            "result": [
                {
                    "symbol": "NVDA",
                    "recommendedSymbols": [
                        {"symbol": "NVDA"},
                        {"symbol": "AMD"},
                    ],
                }
            ]
        }
    }
    monkeypatch.setattr(related, "get_json", lambda url: self_ref)
    assert related_tickers("NVDA") == ["AMD"]


def test_related_tickers_network_failure(monkeypatch):
    def boom(url):
        raise OSError("offline")

    monkeypatch.setattr(related, "get_json", boom)
    assert related_tickers("NVDA") == []


def test_the_cohort_rivals_come_before_the_co_viewed(monkeypatch):
    from stocks.analysis import sectors
    from stocks.api import loaders
    from stocks.data import profiles

    scan = sectors.SectorScan(
        "Technology", "2026-10-17", ("NVDA", "AMD", "AVGO"),
        (
            {"ticker": "NVDA", "industry": "Semiconductors"},
            {"ticker": "AMD", "industry": "Semiconductors"},
            {"ticker": "AVGO", "industry": "Semiconductors"},
        ),
        {}, (),
    )
    monkeypatch.setattr(loaders, "sector_scans", lambda: {"Technology": scan})
    monkeypatch.setattr(loaders, "sec_title", lambda t: t)
    monkeypatch.setattr(profiles, "known", lambda t: {
        "TSLA": {"industry": "Auto Manufacturers"},
        "MU": {"industry": "Semiconductors"},
    }.get(t))
    monkeypatch.setattr(related, "get_json", lambda url: {
        "finance": {"result": [{"recommendedSymbols": [
            {"symbol": "TSLA"}, {"symbol": "AMD"}, {"symbol": "MU"},
        ]}]}
    })
    loaders.peer_groups.cache_clear()
    assert loaders.peer_groups("NVDA") == (("AMD", "AVGO"), ("MU",))
    assert loaders.related("NVDA") == ("AMD", "AVGO", "MU")


def test_co_viewed_names_outside_the_industry_are_dropped(monkeypatch):
    """Next to Adobe, Yahoo's readers also watch PayPal and Visa: co-viewed,
    not rivals. A name nobody can file is dropped rather than vouched for."""
    from stocks.api import loaders
    from stocks.data import fetch, profiles

    monkeypatch.setattr(loaders, "sector_scans", lambda: {})
    monkeypatch.setattr(loaders, "sec_title", lambda t: t)
    monkeypatch.setattr(profiles, "known", lambda t: {
        "ADBE": {"industry": "Software - Application"},
        "CRM": {"industry": "Software - Application"},
        "PYPL": {"industry": "Credit Services"},
        "V": {"industry": "Credit Services"},
    }.get(t))

    def throttled(t):
        raise OSError("429")

    monkeypatch.setattr(fetch, "info", throttled)
    monkeypatch.setattr(related, "get_json", lambda url: {
        "finance": {"result": [{"recommendedSymbols": [
            {"symbol": s} for s in ("CRM", "PYPL", "V", "NOWHERE")
        ]}]}
    })
    loaders.peer_groups.cache_clear()
    assert loaders.peer_groups("ADBE") == ((), ("CRM",))


def test_a_fund_keeps_what_its_readers_also_watch(monkeypatch):
    """An ETF files under no industry, so there is nothing to filter by."""
    from stocks.api import loaders
    from stocks.data import profiles

    monkeypatch.setattr(loaders, "sector_scans", lambda: {})
    monkeypatch.setattr(loaders, "sec_title", lambda t: None)
    monkeypatch.setattr(profiles, "known", lambda t: {"quoteType": "ETF"})
    monkeypatch.setattr(related, "get_json", lambda url: {
        "finance": {"result": [{"recommendedSymbols": [
            {"symbol": "QQQ"}, {"symbol": "VTI"},
        ]}]}
    })
    loaders.peer_groups.cache_clear()
    assert loaders.peer_groups("SPY") == ((), ("QQQ", "VTI"))


def test_an_equity_memo_from_before_industries_asks_yahoo(monkeypatch):
    """Memo entries written before `industry` was kept carry none: that is a
    gap to fill, not a company with no industry."""
    from stocks.api import loaders
    from stocks.data import fetch, profiles

    monkeypatch.setattr(loaders, "sector_scans", lambda: {})
    monkeypatch.setattr(profiles, "known", lambda t: {"quoteType": "EQUITY"})
    monkeypatch.setattr(fetch, "info", lambda t: {"industry": "Software - Application"})
    assert loaders._industry("ADBE", {}) == "Software - Application"
