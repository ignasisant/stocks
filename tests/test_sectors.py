"""Sector cohorts — who gets into the comparison, and who is kept out.

The ranking itself is `test_fundamentals.py`'s subject. What is tested here is
the half that is new: assembling a cohort from an ETF basket plus names a
language model proposed, and refusing the ones Yahoo will not vouch for.
"""

import json

import pytest
from yfinance.exceptions import YFRateLimitError

from stocks.analysis import sectors
from stocks.data.funds import FundHolding, FundProfile

# Six higher-is-better KPIs per row, so every ticker clears comp_scores' own
# floor of five ranked metrics. A is the best company, D the worst.
_QUALITY = ("roe", "roic", "gross_margin", "op_margin", "net_margin", "fcf_yield")


def _row(ticker: str, grade: float) -> dict:
    return {"ticker": ticker, "quote_type": "EQUITY",
            **{k: grade for k in _QUALITY}}


@pytest.fixture
def cohort(monkeypatch, tmp_path):
    """A fake Yahoo that knows one ETF basket and one set of company profiles."""
    from stocks.data import fetch, funds, symbols

    state = {
        "holdings": ["AAPL", "MSFT", "NVDA"],
        "sectors": {"AAPL": "Technology", "MSFT": "Technology",
                    "NVDA": "Technology", "ASML.AS": "Technology",
                    "XOM": "Energy"},
        "quoted": {"AAPL", "MSFT", "NVDA", "ASML.AS", "XOM", "TSM"},
    }

    def profile(ticker, info=None):
        return FundProfile(
            ticker=ticker,
            name=f"{ticker} Select Sector SPDR",
            quote_type="ETF",
            holdings=tuple(
                FundHolding(symbol=s, name=s, weight=0.1)
                for s in state["holdings"]
            ),
        )

    monkeypatch.setattr(funds, "fetch_profile", profile)
    monkeypatch.setattr(
        symbols, "search_symbols",
        lambda q, limit=6: [(q.upper(), q, "NMS")] if q.upper() in state["quoted"]
        else [],
    )
    monkeypatch.setattr(
        fetch, "info", lambda s: {"sector": state["sectors"].get(s.upper(), "")}
    )
    monkeypatch.setattr(
        sectors, "fetch_metrics_many",
        lambda ts, **kw: [_row(t, 1.0 - i * 0.1) for i, t in enumerate(ts)],
    )
    monkeypatch.setattr(sectors, "SCAN_FILE", tmp_path / "sector_scan.json")
    monkeypatch.setattr(sectors.storage, "enabled", lambda: False)
    return state


# ------------------------------------------------------------- the ETF basket


def test_the_basket_is_the_starting_cohort(cohort):
    assert sectors.etf_candidates("Technology") == ["AAPL", "MSFT", "NVDA"]


def test_the_basket_is_capped(cohort):
    cohort["holdings"] = [f"T{i}" for i in range(20)]
    assert len(sectors.etf_candidates("Technology")) == sectors.ETF_TOP


def test_a_sector_yahoo_dropped_the_basket_for_is_skipped_not_fatal(cohort):
    cohort["holdings"] = []
    assert sectors.etf_candidates("Technology") == []


def test_an_unknown_sector_is_a_programming_error(cohort):
    with pytest.raises(ValueError, match="unknown sector"):
        sectors.etf_candidates("Tech Stocks")


def test_every_sector_has_an_etf():
    """SECTORS is derived from the ETF map; a sector with no ETF has no cohort."""
    from stocks.analysis.sentiment import SECTOR_ETFS

    assert len(sectors.SECTORS) == 11
    assert all(SECTOR_ETFS.get(s) for s in sectors.SECTORS)


# ---------------------------------------------------------- the model's names


def test_a_confirmed_non_us_name_gets_in(cohort):
    assert sectors.validate_symbols(["ASML.AS"], "Technology") == ["ASML.AS"]


def test_an_invented_ticker_never_reaches_the_podium(cohort):
    # Yahoo has never heard of it: the first gate.
    assert sectors.validate_symbols(["NVDIA", "ASML.AS"], "Technology") == ["ASML.AS"]


def test_a_real_name_filed_under_another_sector_is_dropped(cohort):
    # The dangerous one — it exists, so it would otherwise rank against
    # companies it does not compete with.
    assert sectors.validate_symbols(["XOM"], "Technology") == []


def test_a_name_already_in_the_cohort_is_not_added_twice(cohort):
    kept = sectors.validate_symbols(["AAPL", "ASML.AS"], "Technology",
                                    known=("AAPL",))
    assert kept == ["ASML.AS"]


def test_repeats_within_one_proposal_collapse(cohort):
    assert sectors.validate_symbols(["ASML.AS", "asml.as"], "Technology") == [
        "ASML.AS"
    ]


def test_a_throttle_stops_validation_rather_than_emptying_the_sector(cohort,
                                                                    monkeypatch):
    """Mid-throttle every candidate would 'fail validation' and the sector
    would silently shrink to its ETF. Better to raise and keep yesterday's."""
    from stocks.data import fetch

    def refused(_symbol):
        raise YFRateLimitError()

    monkeypatch.setattr(fetch, "info", refused)
    with pytest.raises(YFRateLimitError):
        sectors.validate_symbols(["ASML.AS"], "Technology")


# ------------------------------------------------------------------ the scan


def test_the_scan_merges_the_basket_with_the_extras(cohort):
    scan = sectors.scan_sector("Technology", extra=("ASML.AS",))
    assert scan.tickers == ("AAPL", "MSFT", "NVDA", "ASML.AS")
    assert scan.sector == "Technology"


def test_an_extra_already_in_the_basket_is_not_scanned_twice(cohort):
    scan = sectors.scan_sector("Technology", extra=("AAPL",))
    assert scan.tickers == ("AAPL", "MSFT", "NVDA")


def test_the_podium_is_three_deep_and_best_first(cohort):
    scan = sectors.scan_sector("Technology", extra=("ASML.AS",))
    assert scan.podium == ("AAPL", "MSFT", "NVDA")  # _row grades them descending
    assert list(scan.medals.values()) == ["🥇", "🥈", "🥉"]


def test_a_cohort_too_thin_to_rank_has_no_podium(cohort):
    """comp_medals' rule, inherited rather than restated: a 2-horse race has
    no podium."""
    cohort["holdings"] = ["AAPL", "MSFT"]
    assert sectors.scan_sector("Technology").podium == ()


def test_an_empty_basket_scans_to_an_empty_sector(cohort):
    cohort["holdings"] = []
    scan = sectors.scan_sector("Technology")
    assert scan.tickers == () and scan.podium == ()


def test_the_scan_does_not_revalidate_its_extras(cohort):
    """scan_sector takes names that are already vetted — passing a bad one is
    the caller's bug, and it must not cost a silent Yahoo round trip here."""
    scan = sectors.scan_sector("Technology", extra=("XOM",))
    assert "XOM" in scan.tickers


# --------------------------------------------------------------- persistence


def test_a_scan_survives_a_round_trip(cohort):
    scan = sectors.scan_sector("Technology", extra=("ASML.AS",))
    sectors.save_scan({"Technology": scan})
    back = sectors.load_scan()["Technology"]
    assert back.tickers == scan.tickers
    assert back.podium == scan.podium
    assert back.scores == pytest.approx(scan.scores)
    assert back.as_of == scan.as_of


def test_pandas_numbers_are_written_as_json_not_as_nan(cohort, monkeypatch):
    """compute_metrics reads half its numbers out of pandas. `NaN` is not JSON
    and no other reader parses it."""
    import numpy as np

    monkeypatch.setattr(
        sectors, "fetch_metrics_many",
        lambda ts, **kw: [{"ticker": t, "pe_ttm": np.float64(21.5),
                           "peg": float("nan"), "currency": "USD"} for t in ts],
    )
    sectors.save_scan({"Technology": sectors.scan_sector("Technology")})
    raw = sectors.SCAN_FILE.read_text()
    assert "NaN" not in raw
    row = json.loads(raw)["sectors"]["Technology"]["metrics"][0]
    assert row["pe_ttm"] == 21.5 and row["peg"] is None


def test_nothing_stored_yet_is_an_empty_map_not_a_crash(cohort):
    assert sectors.load_scan() == {}


def test_a_corrupt_file_reads_as_no_scan(cohort):
    sectors.SCAN_FILE.write_text("{not json")
    assert sectors.load_scan() == {}


def test_saving_one_sector_keeps_the_others(cohort):
    """The cron merges into what load_scan gave it — a sector Yahoo refused
    tonight keeps yesterday's cohort."""
    first = sectors.scan_sector("Technology")
    sectors.save_scan({"Technology": first})
    stored = sectors.load_scan()
    cohort["holdings"] = ["XOM", "CVX", "SHEL"]
    cohort["sectors"] |= {"CVX": "Energy", "SHEL": "Energy"}
    stored["Energy"] = sectors.scan_sector("Energy")
    sectors.save_scan(stored)
    back = sectors.load_scan()
    assert set(back) == {"Technology", "Energy"}
    assert back["Technology"].tickers == first.tickers


# -------------------------------------------------------------- the nightly run


@pytest.fixture
def cron(cohort, monkeypatch):
    """The scan runner with the model stubbed out and the pause removed."""
    from stocks.chat import sector_ai

    proposals = {"Technology": ["ASML.AS"], "Energy": []}
    monkeypatch.setattr(
        sector_ai, "propose_peers",
        lambda prefs, sector, known, count, **kw: list(proposals.get(sector, [])),
    )
    cohort["proposals"] = proposals
    return cohort


def test_a_run_widens_the_cohort_and_stores_it(cron):
    status = sectors.run_scan(("Technology",), pause_s=0)
    assert status == {"Technology": "scanned 4"}
    assert sectors.load_scan()["Technology"].tickers[-1] == "ASML.AS"


def test_a_sector_yahoo_refuses_keeps_yesterdays_cohort(cron, monkeypatch):
    sectors.run_scan(("Technology",), pause_s=0)
    yesterday = sectors.load_scan()["Technology"]

    def refused(*a, **kw):
        raise YFRateLimitError()

    monkeypatch.setattr(sectors, "scan_sector", refused)
    assert sectors.run_scan(("Technology",), pause_s=0) == {"Technology": "kept"}
    assert sectors.load_scan()["Technology"].tickers == yesterday.tickers


def test_a_failed_widening_still_scans_the_etf_basket(cron, monkeypatch):
    from stocks.chat import sector_ai

    def dead(*a, **kw):
        raise RuntimeError("every provider down")

    monkeypatch.setattr(sector_ai, "propose_peers", dead)
    status = sectors.run_scan(("Technology",), pause_s=0)
    assert status == {"Technology": "scanned 3"}  # the basket, unwidened


def test_no_widen_never_asks_a_model(cron, monkeypatch):
    from stocks.chat import sector_ai

    asked = []
    monkeypatch.setattr(sector_ai, "propose_peers",
                        lambda *a, **kw: asked.append(1) or [])
    sectors.run_scan(("Technology",), widen=False, pause_s=0)
    assert asked == []


def test_one_sector_failing_does_not_lose_the_others(cron, monkeypatch):
    real = sectors.scan_sector

    def flaky(sector, extra=(), **kw):
        if sector == "Energy":
            raise YFRateLimitError()
        return real(sector, extra, **kw)

    monkeypatch.setattr(sectors, "scan_sector", flaky)
    status = sectors.run_scan(("Technology", "Energy"), pause_s=0)
    assert status["Technology"].startswith("scanned")
    assert status["Energy"] == "failed"  # never stored, so nothing to keep
    assert set(sectors.load_scan()) == {"Technology"}


def test_a_dry_run_scans_without_publishing(cron):
    status = sectors.run_scan(("Technology",), pause_s=0, dry_run=True)
    assert status["Technology"].startswith("scanned")
    assert sectors.load_scan() == {}


def test_the_default_run_is_every_sector(cron, monkeypatch):
    seen = []
    monkeypatch.setattr(sectors, "scan_sector",
                        lambda s, extra=(), **kw: seen.append(s) or
                        sectors.SectorScan(s, "2026-09-18", ("X",), (), {}, ()))
    monkeypatch.setattr(sectors, "etf_candidates", lambda s, limit=10: ["X"])
    sectors.run_scan(pause_s=0)
    assert seen == list(sectors.SECTORS)
