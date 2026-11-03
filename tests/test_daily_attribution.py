"""The day split by position and block (`chat.daily.attribution`)."""

from __future__ import annotations

import pandas as pd
import pytest

from stocks.api.daily_card import _book
from stocks.chat import daily_book
from stocks.chat.daily import attribution

META = {
    "MSFT": {"sector": "Technology"},
    "NVDA": {"sector": "Technology"},
    "UNH": {"sector": "Healthcare"},
    "IUSN.DE": {"sector_weights": {"Technology": 0.3, "Industrials": 0.7}},
}


def frame(rows: dict[str, tuple]) -> pd.DataFrame:
    """{ticker: (value, day, day_pct)} as `home.enriched` lays it out."""
    tbl = pd.DataFrame(
        {
            "value": {t: v for t, (v, _, _) in rows.items()},
            "day": {t: d for t, (_, d, _) in rows.items()},
            "day_pct": {t: p for t, (_, _, p) in rows.items()},
        }
    )
    tbl["weight"] = tbl["value"] / tbl["value"].sum()
    return tbl


@pytest.fixture
def reported(monkeypatch):
    said: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        attribution, "_report", lambda kind, **ev: said.append((kind, ev))
    )
    return said


def test_positions_and_blocks_add_up_to_the_day():
    tbl = frame({
        "MSFT": (5000.0, 100.0, 0.02),
        "NVDA": (3000.0, -60.0, -0.0196),
        "UNH": (2000.0, -40.0, -0.0196),
        "IUSN.DE": (4000.0, 20.0, 0.005),
        "BTC-EUR": (1000.0, 30.0, 0.031),
    })
    out = attribution.day(tbl, META)

    assert out["amount"] == pytest.approx(50.0)
    assert out["start"] == pytest.approx(15000.0 - 50.0)
    assert [r["ticker"] for r in out["up"]] == ["MSFT", "BTC-EUR", "IUSN.DE"]
    assert [r["ticker"] for r in out["down"]] == ["NVDA", "UNH"]
    assert out["up"][0]["pp"] == pytest.approx(100 / 14950 * 100, abs=0.01)
    labels = {(b["kind"], b["label"]): b for b in out["blocks"]}
    # A fund is its own block: its look-through split is not a day move.
    assert labels[("fund", "IUSN.DE")]["amount"] == pytest.approx(20.0)
    assert labels[("sector", "Technology")]["tickers"] == ["MSFT", "NVDA"]
    assert labels[("sector", "Technology")]["amount"] == pytest.approx(40.0)
    assert labels[("crypto", "Crypto")]["amount"] == pytest.approx(30.0)
    assert sum(b["amount"] for b in out["blocks"]) == pytest.approx(out["amount"])
    # Largest block first, whichever way it moved.
    sizes = [abs(b["amount"]) for b in out["blocks"]]
    assert sizes == sorted(sizes, reverse=True)
    assert "gap" not in out


def test_a_position_with_no_day_is_left_out_not_counted_as_zero():
    tbl = frame({"MSFT": (5000.0, 100.0, 0.02), "UNH": (2000.0, float("nan"), None)})
    out = attribution.day(tbl, META)

    assert out["amount"] == pytest.approx(100.0)
    assert out["start"] == pytest.approx(4900.0)
    assert [b["label"] for b in out["blocks"]] == ["Technology"]


def test_nothing_priced_is_no_breakdown():
    tbl = frame({"MSFT": (5000.0, float("nan"), None)})
    assert attribution.day(tbl, META) is None
    assert attribution.day(pd.DataFrame(), META) is None


def test_a_gap_is_said_and_logged_only_when_the_rows_are_the_day(reported):
    tbl = frame({"MSFT": (5000.0, 100.0, 0.02)})

    during = attribution.day(tbl, META, total=112.0)
    assert during["gap"] == pytest.approx(12.0)
    assert reported == []

    attribution.day(tbl, META, total=112.0, report=True)
    assert reported == [("attribution_gap", {"off": pytest.approx(0.107, abs=0.001)})]

    reported.clear()
    attribution.day(tbl, META, total=100.004, report=True)
    assert reported == []


def test_a_repeated_bar_is_named_not_counted_as_a_quiet_day(reported):
    tbl = frame({"MSFT": (5000.0, 0.0, 0.0), "UNH": (2000.0, 0.0, 0.0)})
    year = {"MSFT": [410.0, 412.5, 412.5], "UNH": [500.0, 498.0, 501.0]}
    out = attribution.day(tbl, META, year=year, report=True)

    assert out["stale"] == ["MSFT"]
    assert reported == [("stale_bar", {"ticker": "MSFT"})]


@pytest.mark.parametrize(
    ("pct", "closes", "expected"),
    [
        (0.0, [10.0, 10.0], True),
        (0.0, [10.0, 10.1], False),
        (0.0, None, True),
        (0.001, [10.0, 10.0], False),
        (None, [10.0, 10.0], False),
    ],
)
def test_stale(pct, closes, expected):
    assert attribution.stale(pct, closes) is expected


def calm_year(days: int = 60, step: float = 0.005) -> list[float]:
    """A year that moves ±`step` every day: a sigma of about `step`."""
    out, price = [], 100.0
    for i in range(days):
        price *= 1 + (step if i % 2 else -step)
        out.append(price)
    return out


def test_an_unusual_move_is_set_against_its_sector_etf():
    tbl = frame({
        "MSFT": (5000.0, -250.0, -0.05),
        "UNH": (2000.0, -120.0, -0.06),
        "NVDA": (3000.0, 3.0, 0.001),
    })
    year = {t: calm_year() for t in ("MSFT", "UNH", "NVDA")}
    out = attribution.day(
        tbl, META, year=year, sector_day={"Technology": -0.04, "Healthcare": 0.002}
    )

    by = {e["ticker"]: e for e in out["explained"]}
    assert by["MSFT"]["etf"] == "XLK"
    assert by["MSFT"]["verdict"] == "sector"
    assert by["MSFT"]["etf_pct"] == pytest.approx(-4.0)
    assert by["UNH"]["verdict"] == "company"
    assert by["UNH"]["sigmas"] > 2
    # A move inside two of its own sigmas is not explained at all.
    assert "NVDA" not in by
    # Biggest move first.
    assert out["explained"][0]["ticker"] == "UNH"


def test_a_short_history_has_no_sigma():
    assert attribution.sigma(calm_year(10)) is None
    assert attribution.sigma(calm_year()) == pytest.approx(0.005, rel=0.05)


def test_session_pct_reads_the_bar_on_or_before_the_session():
    series = pd.Series(
        [100.0, 102.0, 99.96],
        index=pd.to_datetime(["2026-10-29", "2026-10-30", "2026-11-02"]),
    )
    assert attribution.session_pct(series, "2026-10-31") == pytest.approx(0.02)
    assert attribution.session_pct(series, None) == pytest.approx(-0.02)
    assert attribution.session_pct(series, "2026-10-29") is None
    assert attribution.session_pct(None, "2026-10-30") is None


def test_alpha_reads_the_index_over_the_books_own_days():
    days = pd.to_datetime(["2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02"])
    hist = pd.DataFrame(
        {"A": [100.0, 101.0, 101.0, 102.01], "B": [100.0, 101.0, 101.0, 102.01]},
        index=days,
    )
    # No index bar on the 30th: the index stood still that day, not a hole.
    index = pd.Series(
        [50.0, 50.25, 50.75],
        index=pd.to_datetime(["2026-10-28", "2026-10-29", "2026-11-02"]),
    )
    out = attribution.alpha(hist, index)

    dates = [s["date"] for s in out["sessions"]]
    assert dates == ["2026-10-29", "2026-10-30", "2026-11-02"]
    assert [s["book"] for s in out["sessions"]] == [1.0, 0.0, 1.0]
    assert [s["index"] for s in out["sessions"]] == [0.5, 0.0, 1.0]
    assert out["ahead"] == 1
    assert out["excess_pp"] == pytest.approx(0.5)


def test_alpha_keeps_the_last_sessions_only():
    days = pd.bdate_range("2026-09-01", periods=30)
    hist = pd.DataFrame({"A": [100.0 + i for i in range(30)]}, index=days)
    index = pd.Series([200.0 + i for i in range(30)], index=days)
    out = attribution.alpha(hist, index)

    assert len(out["sessions"]) == attribution.ALPHA_SESSIONS
    assert out["sessions"][-1]["date"] == str(days[-1].date())
    assert attribution.alpha(hist.iloc[:2], None) is None
    assert attribution.alpha(hist.iloc[:2], index) is None


def test_the_portfolio_section_carries_the_breakdown():
    facts = {
        "currency": "EUR",
        "index": {"name": "S&P 500", "day_pct": 0.4},
        "day": {"amount": 50.0, "pct": 0.3},
        "attribution": {"amount": 50.0, "up": [{"ticker": "MSFT", "amount": 50.0}]},
    }
    section = daily_book.section(facts)
    assert section["attribution"]["up"][0]["ticker"] == "MSFT"

    book = _book(section)
    assert book.attribution.up[0].amount == 50.0


def test_a_breakdown_that_does_not_fit_costs_only_the_breakdown():
    raw = {
        "index": "S&P 500",
        "currency": "EUR",
        "rows": [{"window": "day", "pct": 0.3, "amount": 50.0, "index_pct": 0.4}],
        "attribution": {"amount": "lots"},
    }
    book = _book(raw)
    assert book is not None
    assert book.attribution is None
    assert book.rows[0].amount == 50.0
