"""The ticker page's "Analyse with AI" brief (chat/brief.py)."""

import json
from datetime import date, timedelta

import pandas as pd
import pytest

from stocks.chat import brief

TODAY = date(2026, 10, 24)

LEU = {
    "longName": "Centrus Energy Corp.",
    "quoteType": "EQUITY",
    "sector": "Energy",
    "industry": "Uranium",
    "longBusinessSummary": "Centrus Energy supplies nuclear fuel and enrichment "
                           "services to utilities and the US government.",
    "totalRevenue": 440e6,
    "revenueGrowth": 0.3,
    "profitMargins": 0.15,
    "regularMarketChangePercent": 7.2,
}


class _Provider:
    id = "fake"
    classifier_model = "cheap-model"

    def __init__(self, reply="", exc=None):
        self.reply, self.exc = reply, exc
        self.calls = []

    def complete(self, api_key, model, system, messages):
        self.calls.append((system, messages))
        if self.exc:
            raise self.exc
        return self.reply


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A profile, a calendar and a book the brief reads, all in memory."""
    from stocks.api import loaders
    from stocks.chat import engine
    from stocks.data import fetch, profiles

    state = {"info": dict(LEU), "dates": [], "book": None}
    monkeypatch.setattr(fetch, "info", lambda t: state["info"])
    monkeypatch.setattr(profiles, "known", lambda t: {})
    monkeypatch.setattr(loaders, "earnings", lambda t: (state["dates"], []))
    monkeypatch.setattr(engine, "enriched_frame", lambda db, cur="EUR": state["book"])
    monkeypatch.setattr(brief, "DOSSIER_DIR", tmp_path / "dossiers")
    monkeypatch.setattr(brief.storage, "enabled", lambda: False)
    db = tmp_path / "ledger.db"
    db.write_text("")
    state["paths"] = {"watchlist": tmp_path / "watchlist.yaml", "db": db}
    return state


def _build(world, angle="full", ticker="LEU"):
    return brief.build(angle, ticker, today=TODAY, **world["paths"])


def test_the_company_picks_its_own_lens(world):
    b = _build(world)
    # Uranium, not the oil-and-gas reading of "Energy".
    assert b.skills[0] == "nuclear-uranium"
    assert "energy" not in b.skills
    assert b.debate and b.deep


def test_each_angle_brings_its_lens_and_structure(world):
    bear = _build(world, "bear")
    assert "bear-case" in bear.skills
    assert "Pre-mortem" in bear.text and not bear.deep and bear.debate
    fit = _build(world, "fit")
    assert "portfolio-risk" in fit.skills and not fit.debate
    assert "Overlap" in fit.text
    assert len(_build(world, "earnings").skills) <= 3


def test_unknown_angle_or_no_symbol_is_no_brief(world):
    assert _build(world, "hype") is None
    assert _build(world, "full", "") is None


def test_the_brief_says_whether_the_reader_holds_it(world):
    assert "does not hold it" in _build(world).text
    assert "starting size" in _build(world).text
    world["book"] = pd.DataFrame({"weight": [0.08], "pnl_pct": [0.25]},
                                 index=["LEU"])
    held = _build(world).text
    assert "weight 8.0%" in held and "P/L +25.0%" in held
    assert "add or trim" in held


def test_a_recent_report_and_the_next_one_are_named(world):
    world["dates"] = [TODAY - timedelta(days=4), TODAY + timedelta(days=20)]
    b = _build(world)
    assert "4 days ago" in b.text and "in 20 days" in b.text
    assert "earnings-review" in b.skills
    # Far away on both sides: nothing said.
    world["dates"] = [TODAY - timedelta(days=60), TODAY + timedelta(days=90)]
    assert "days ago" not in _build(world).text


def test_a_big_move_is_explained_first(world):
    assert "+7.2%" in _build(world).text
    world["info"]["regularMarketChangePercent"] = 1.0
    assert "Today it moves" not in _build(world).text


def test_a_fund_gets_its_wrapper_lens_and_no_angles(world):
    world["info"] = {"longName": "Vanguard S&P 500", "quoteType": "ETF"}
    b = _build(world, "bear")
    assert b.angle == "full" and b.skills == ["etfs"]
    assert not b.debate and not b.needs_dossier
    assert "Answer in this structure" not in b.text


def test_stage_reads_the_life_of_the_company():
    pre = brief.Facts("X", revenue=10e6)
    assert brief.stage(pre)[1] == "growth-momentum"
    payer = brief.Facts("X", revenue=5e9, margin=0.2, growth=0.02,
                        dividend_yield=4.5)  # percent points
    assert brief.stage(payer)[1] == "dividend"
    assert "cyclical" in brief.stage(brief.Facts("X", sector="Energy",
                                                 revenue=5e9, margin=0.1))[0]
    assert brief.stage(brief.Facts("X")) == ("", "")


def test_a_failing_profile_still_briefs(world, monkeypatch):
    from stocks.data import fetch

    def boom(_t):
        raise RuntimeError("throttled")

    monkeypatch.setattr(fetch, "info", boom)
    b = _build(world)
    assert b is not None and "LEU" in b.text and not b.needs_dossier


# ---------------------------------------------------------------- dossier

_DRAFT = json.dumps({
    "business": "Enriches uranium for utilities and the US government.",
    "lens": "nuclear-uranium",
    "debates": [
        "Will the HALEU contract turn into commercial demand?",
        "How long does the Russian supply waiver last?",
        "Backlog of $3.8bn is safe",  # a figure: dropped
    ],
    "watch": ["DOE task orders", "Piketon cascade build-out"],
})


def test_a_dossier_is_drafted_once_and_kept(world):
    b = _build(world)
    assert b.needs_dossier and b.dossier is None
    p = _Provider(reply=_DRAFT)
    got = brief.draft_dossier(p, "k", b.facts)
    assert got is not None and len(got.debates) == 2
    assert all("$" not in q for q in got.debates)
    assert "Profile:" in p.calls[0][1][0]["content"]
    assert "- nuclear-uranium:" in p.calls[0][0]  # the industry catalog rides along

    again = _build(world)
    assert not again.needs_dossier and again.dossier == got
    block = brief.dossier_block(again.dossier)
    assert "not facts" in block and "HALEU" in block


def test_a_stale_dossier_is_drafted_again(world):
    brief._save("LEU", brief.Dossier(business="x"), today=TODAY - timedelta(days=45))
    assert brief.cached_dossier("LEU", today=TODAY) is None
    assert _build(world).needs_dossier


def test_a_failed_draft_is_nothing(world):
    b = _build(world)
    assert brief.draft_dossier(_Provider(exc=RuntimeError("down")), "k", b.facts) is None
    assert brief.cached_dossier("LEU", today=TODAY) is None
    assert brief.dossier_block(None) == ""


def test_the_dossier_contract_drops_what_it_cannot_trust():
    d = brief.Dossier.model_validate({
        "business": "  sells   things  ",
        "lens": "not-a-skill",
        "debates": ["Q3 margins", "- Is the moat real?", "Is the moat real?", 7],
        "watch": "not a list",
    })
    assert d.business == "sells things"
    assert d.lens == ""
    assert d.debates == ["Is the moat real?"]
    assert d.watch == []


def test_a_dossier_lens_overrides_only_an_unmatched_industry(world):
    world["info"]["industry"] = "Pollution & Treatment Controls"
    world["info"]["sector"] = "Industrials"
    brief._save("LEU", brief.Dossier(business="x", lens="nuclear-uranium"),
                today=TODAY)
    # "Pollution & Treatment Controls" names no industry skill: the draft,
    # which read the business, decides.
    assert _build(world).skills[0] == "nuclear-uranium"
    world["info"]["industry"] = "Uranium"
    world["info"]["sector"] = "Energy"
    assert _build(world).skills[0] == "nuclear-uranium"


def test_about_reads_the_profile_memo_only(monkeypatch):
    from stocks.data import profiles

    monkeypatch.setattr(profiles, "known",
                        lambda t: {"sector": "Energy", "industry": "Uranium"})
    assert brief.about("LEU") == "Energy · Uranium"
    assert brief.about("") == ""
