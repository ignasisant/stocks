"""The analysis behind one line of the daily card: the evidence it is written
from, the audit that gates the model's prose, and the computed stand-in.

What is pinned here is what makes it an analysis rather than a longer line:

* the differences are computed before the model sees them, so every
  comparison it can make is a figure it can quote;
* a figure is audited against the company it is written under — a peer's
  return printed under the subject's name is rejected, the peers' median is
  quotable anywhere;
* without a model the same evidence is still stated as a comparison, and the
  tables are computed either way.

Nothing here touches the network: the evidence builders take series and
frames, and the fetch itself (`evidence.gather`) is exercised by the route
tests with its loaders replaced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from stocks.api import evidence as ev
from stocks.chat import daily
from stocks.chat import daily_analysis as da

TODAY = date(2026, 9, 29)

FACTS = {
    "date": TODAY.isoformat(),
    "currency": "EUR",
    "actions": [
        {
            "kind": "drawdown",
            "ticker": "DSGX",
            "pnl_pct": -31.2,
            "pnl": -1520.4,
            "currency": "EUR",
            "key": "drawdown:DSGX",
        },
        {
            "kind": "harvest",
            "ticker": "FISV",
            "loss": 1840.0,
            "gain_ytd": 5200.0,
            "offset": 1840.0,
            "pnl_pct": -22.5,
            "currency": "EUR",
            "jurisdiction": "ES",
            "repurchase_window": "2m",
            "key": "harvest:FISV",
        },
        {
            "kind": "vs_benchmark",
            "ticker": "",
            "index": "S&P 500",
            "book_month_pct": -1.2,
            "index_month_pct": 2.44,
            "gap_pp": -3.64,
            "currency": "EUR",
            "key": "vs_benchmark:",
        },
    ],
}


def card() -> daily.DailyAction:
    written = daily.computed(FACTS, "en", TODAY)
    return daily.DailyAction.from_dict(daily.to_store(None, written, FACTS))


def perf(m1, m3, y1, vol=25.0) -> dict:
    return {
        "m1_pct": m1,
        "m3_pct": m3,
        "y1_pct": y1,
        "from_high_pct": -20.0,
        "vol_1y_pct": vol,
        "max_dd_1y_pct": -30.0,
    }


def company_evidence() -> dict:
    subject = {
        "ticker": "DSGX",
        "sector": "Technology",
        "perf": perf(-8.0, -18.0, -25.0, 30.0),
        "business": {"pe_fwd": 38.2, "op_margin_pct": 27.1},
        "consensus": {"target_upside_pct": 24.3, "rev_growth_next_fy_pct": 12.1},
    }
    peers = [
        {
            "ticker": "MANH",
            "perf": perf(1.0, -4.5, 3.0, 26.0),
            "business": {"pe_fwd": 33.0, "op_margin_pct": 22.0},
            "consensus": {},
        },
        {
            "ticker": "SPSC",
            "perf": perf(2.0, 0.5, 7.0, 28.0),
            "business": {"pe_fwd": 29.0, "op_margin_pct": 18.0},
            "consensus": {},
        },
    ]
    sector = {"etf": "XLK", "sector": "Technology", "perf": perf(1.5, 6.0, 19.0, 22.0)}
    index = {"etf": "SPY", "name": "S&P 500", "perf": perf(1.0, 4.0, 15.0, 16.0)}
    return {
        "subject": subject,
        "peers": peers,
        "sector": sector,
        "index": index,
        "compare": ev.compare(subject, peers, sector, index),
    }


# ----------------------------------------------------------------- evidence


def closes(values, end="2026-09-25") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)))


def test_performance_is_read_over_calendar_windows():
    series = closes(np.linspace(100.0, 150.0, 400))
    out = ev.perf(series)
    assert out["y1_pct"] > out["m3_pct"] > out["m1_pct"] > 0
    assert out["from_high_pct"] == 0.0
    assert ev.perf(closes([1.0] * 10)) == {} and ev.perf(None) == {}


def test_the_differences_are_computed_before_anyone_quotes_them():
    cmp = company_evidence()["compare"]
    assert cmp["vs_sector_m3_pp"] == -24.0
    assert cmp["peers_median"]["m3_pct"] == -2.0
    assert cmp["vs_peers_m3_pp"] == -16.0
    assert cmp["vol_vs_peers_pp"] == 3.0
    # Loose: no "ticker" key, so quotable in a line about any company.
    assert "ticker" not in cmp


def test_peers_are_companies_in_the_same_line_of_business_first():
    me = {"sector": "Technology", "industry": "Software"}
    candidates = {
        "QQQ": {"quote_type": "ETF", "sector": None},
        "JPM": {"quote_type": "EQUITY", "sector": "Financial Services"},
        "AAPL": {"quote_type": "EQUITY", "sector": "Technology", "industry": "Hardware"},
        "MANH": {"quote_type": "EQUITY", "sector": "Technology", "industry": "Software"},
    }
    assert ev.rank_peers("DSGX", me, candidates) == ["MANH", "AAPL"]
    # No sector to go on: Yahoo's order, companies only.
    assert ev.rank_peers("DSGX", {}, candidates) == ["JPM", "AAPL", "MANH"]


def test_the_tax_saving_runs_the_scale_twice_across_a_bracket_edge():
    action = dict(FACTS["actions"][1], gain_ytd=7000.0, offset=2000.0)
    out = ev.tax(action, TODAY)
    # 7000 -> 6000*19% + 1000*21% = 1350; 5000 -> 950: 400 saved, not 2000*21%.
    assert out["saving"] == 400.0
    assert out["marginal_rate_pct"] == 21
    assert out["clear_if_sold_today"] == "2026-11-30"
    abroad = ev.tax(dict(action, jurisdiction="US", repurchase_window="30d"), TODAY)
    assert "saving" not in abroad and abroad["clear_if_sold_today"] == "2026-10-30"


@dataclass
class Result:
    date: date
    eps_estimate: float | None
    reported_eps: float | None
    surprise_pct: float | None


def test_a_print_is_measured_from_the_close_before_to_the_close_after():
    # Tue..Fri; reported on the Wednesday, before or after its session.
    series = closes([100.0, 100.0, 110.0, 111.0], end="2026-07-24")
    results = [
        Result(date(2026, 7, 22), 1.0, 1.1, 10.0),
        Result(date(2026, 4, 1), 1, None, None),
    ]
    out = ev.history(results, series)
    assert out["prints"] == [
        {
            "date": "2026-07-22",
            "eps_estimate": 1.0,
            "reported_eps": 1.1,
            "surprise_pct": 10.0,
            "move_pct": 10.0,
        }
    ]
    assert out["beats"] == 1 and out["avg_abs_move_pct"] == 10.0


def test_attribution_is_weight_times_the_month():
    tbl = pd.DataFrame({"weight": [0.5, 0.5]}, index=["UP", "DOWN"])
    rows = ev.attribution(
        tbl,
        {
            "UP": closes(np.linspace(100, 110, 60)),
            "DOWN": closes(np.linspace(100, 80, 60)),
        },
    )
    assert [r["ticker"] for r in rows] == ["DOWN", "UP"]
    down = rows[0]
    assert down["contribution_pp"] == round(0.5 * down["m1_pct"], 2)


# -------------------------------------------------------------- model prose


def test_the_prompt_carries_the_line_its_trigger_and_the_evidence():
    evidence = company_evidence()
    system, messages = da.prompt(card(), "drawdown:DSGX", evidence, {}, "es")
    payload = json.loads(messages[0]["content"])
    assert payload["action"]["pnl_pct"] == -31.2
    assert payload["evidence"]["compare"]["vs_peers_m3_pp"] == -16.0
    assert "Spanish" in system and "Do the analysis" in system


def reply(verdict: str, *texts: str) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "points": [{"title": f"Point {n}", "text": t} for n, t in enumerate(texts)],
        }
    )


def test_a_point_with_a_figure_nobody_fetched_is_dropped_alone():
    raw = reply(
        "The fall is DSGX's own: it trails its peers by 16.0 points.",
        "DSGX is 31.2% under your cost.",
        "Its peers' median is -2.0% over three months, its sector +6.0%.",
        "DSGX will recover 57% by spring.",
    )
    out = da.parse(raw, card(), company_evidence(), "en")
    assert out is not None and len(out["points"]) == 2
    assert all("57%" not in p["text"] for p in out["points"])


def test_a_peers_figure_under_the_subjects_name_is_rejected():
    evidence = company_evidence()
    # -4.5% is MANH's three months, not DSGX's.
    lie = "DSGX fell 4.5% in three months."
    assert da.parse(reply("DSGX trails.", lie, lie), card(), evidence, "en") is None
    true = "MANH fell 4.5% in three months, DSGX 18.0%."
    assert da.parse(reply("DSGX trails.", true, true), card(), evidence, "en")


def test_a_difference_in_points_is_audited_like_a_percentage():
    ok = "DSGX is 31.2% under your cost."
    evidence = company_evidence()
    assert da.parse(
        reply("DSGX trails its peers by 16.0 pp.", ok, ok), card(), evidence, "en"
    )
    wrong = reply("DSGX trails its peers by 21 puntos.", ok, ok)
    assert da.parse(wrong, card(), evidence, "es") is None


def test_a_verdict_that_fails_the_audit_fails_the_reply():
    ok = "DSGX is 31.2% under your cost."
    assert da.parse(reply("DSGX is 55% cheap.", ok, ok), card(), {}, "en") is None
    assert da.parse("not json", card(), {}, "en") is None


# ----------------------------------------------------------------- computed


def test_without_a_model_the_comparison_is_still_made():
    out = da.computed(card(), "drawdown:DSGX", company_evidence(), "en")
    assert out["verdict"].startswith("DSGX is 16.0 points behind its peers")
    titles = [p["title"] for p in out["points"]]
    assert titles == ["What happened", "Against its group", "The business"]
    compare = out["points"][1]["text"]
    assert "MANH, SPSC" in compare and "XLK" in compare and "S&P 500" in compare


def test_three_months_and_twelve_that_disagree_conclude_neither():
    evidence = company_evidence()
    evidence["compare"] |= {"vs_peers_m3_pp": 29.5, "vs_peers_y1_pp": -6.0}
    out = da.computed(card(), "drawdown:DSGX", evidence, "en")
    assert out["verdict"].startswith("Against its peers, DSGX is +29.5 points")
    assert "-6.0 over twelve" in out["verdict"]


def test_spanish_figures_are_written_the_spanish_way_throughout():
    out = da.computed(
        card(), "harvest:FISV", {"tax": ev.tax(FACTS["actions"][1], TODAY)}, "es"
    )
    text = " ".join([out["verdict"]] + [p["text"] for p in out["points"]])
    assert "1.840 €" in text and "-22,5%" in text
    assert "€1,840" not in text and "22.5%" not in text


def test_every_triggered_line_gets_a_verdict_even_with_no_evidence():
    for item in card().entries:
        out = da.computed(card(), item["key"], {}, "en")
        assert out["verdict"], item["key"]


def test_the_tables_are_computed_with_the_subject_highlighted():
    tables = da.tables(card(), "drawdown:DSGX", company_evidence(), "en")
    price, business = tables
    assert price["title"] == "Price performance"
    assert len(price["columns"]) == len(price["rows"][0]["cells"]) + 1
    assert [r["ticker"] for r in price["rows"]] == ["DSGX", "MANH", "SPSC", "XLK", "SPY"]
    assert price["rows"][0]["highlight"] and not price["rows"][1]["highlight"]
    assert business["rows"][-1]["label"] == "Peer median"
    assert business["rows"][0]["cells"][0] == "38.2x"


def test_a_record_says_who_wrote_it():
    evidence = company_evidence()
    written = {"verdict": "v", "points": [{"title": "t", "text": "x"}]}
    assert da.record(card(), "drawdown:DSGX", evidence, written, "en")["source"] == "llm"
    body = da.record(card(), "drawdown:DSGX", evidence, None, "en")
    assert (
        body["source"] == "computed" and body["tables"] and body["as_of"] == "2026-09-29"
    )


# -------------------------------------------------------------------- fetch


def test_gather_builds_the_company_comparison_from_the_loaders(monkeypatch):
    from stocks.api import briefing, loaders
    from stocks.data.estimates import RawEstimates
    from stocks.data.fundamentals import RawFundamentals

    info = {
        "DSGX": {
            "sector": "Technology",
            "industry": "Software",
            "quoteType": "EQUITY",
            "forwardPE": 38.2,
            "operatingMargins": 0.271,
        },
        "MANH": {
            "sector": "Technology",
            "industry": "Software",
            "quoteType": "EQUITY",
            "forwardPE": 33.0,
        },
        "QQQ": {"quoteType": "ETF"},
    }
    series = {
        t: closes(np.linspace(100, end, 400))
        for t, end in (("DSGX", 80), ("MANH", 110), ("XLK", 120), ("SPY", 115))
    }
    monkeypatch.setattr(
        loaders, "fundamentals", lambda t: RawFundamentals(t, info=info[t])
    )
    monkeypatch.setattr(
        loaders,
        "estimates",
        lambda t: RawEstimates(t, price_targets={"current": 100.0, "mean": 125.0}),
    )
    monkeypatch.setattr(loaders, "related", lambda t: ("QQQ", "MANH", "DSGX"))
    monkeypatch.setattr(briefing, "_card_closes", lambda: series)
    monkeypatch.setattr(ev, "_closes", lambda tickers: {t: series[t] for t in tickers})
    tbl = pd.DataFrame(
        {"weight": [0.25], "value": [3400.0], "pnl": [-1520.4], "pnl_pct": [-0.312]},
        index=["DSGX"],
    )
    monkeypatch.setattr(ev, "_book", lambda paths: tbl)

    out = ev.gather(None, card(), "drawdown:DSGX", today=TODAY)
    assert out["subject"]["business"]["pe_fwd"] == 38.2
    assert out["subject"]["consensus"]["target_upside_pct"] == 25.0
    assert out["subject"]["position"]["pnl_pct"] == -31.2
    assert [p["ticker"] for p in out["peers"]] == ["MANH"]
    assert out["sector"]["etf"] == "XLK" and out["index"]["etf"] == "SPY"
    assert out["compare"]["vs_peers_y1_pp"] < 0 and out["compare"]["vs_sector_y1_pp"] < 0
    assert ev.gather(None, card(), "nope") == {}
