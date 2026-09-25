"""The assistant on the sector screen — what it may widen, and what it may say.

Two failure modes are the subject. Widening can invent a symbol, which is not
caught here (that is `analysis.sectors.validate_symbols`) but must not crash
the scan. Reading can invent a figure, which IS caught here, because by the
time a percentage is on the page nobody can tell it apart from a real one.
"""

import pytest

from stocks.analysis.sectors import SectorScan
from stocks.chat import sector_ai


def _scan(**kw) -> SectorScan:
    base = dict(
        sector="Technology",
        as_of="2026-09-18",
        tickers=("AAPL", "MSFT", "NVDA", "ASML.AS"),
        metrics=(
            {"ticker": "AAPL", "pe_ttm": 28.0, "roic": 0.34, "fcf_yield": 0.038,
             "net_margin": 0.251, "revenue_cagr": 0.082, "ev_ebitda": 21.0},
            {"ticker": "MSFT", "pe_ttm": 32.0, "roic": 0.29, "fcf_yield": 0.031,
             "net_margin": 0.362, "revenue_cagr": 0.145, "ev_ebitda": 24.0},
            {"ticker": "NVDA", "pe_ttm": 45.0, "roic": 0.55, "fcf_yield": 0.021,
             "net_margin": 0.488, "revenue_cagr": 0.610, "ev_ebitda": 38.0},
        ),
        scores={"AAPL": 0.82, "MSFT": 0.61, "NVDA": 0.44},
        podium=("AAPL", "MSFT", "NVDA"),
    )
    return SectorScan(**(base | kw))


@pytest.fixture
def facts():
    return sector_ai.build_facts(_scan(), held=("NVDA",))


# ------------------------------------------------------------------ widening


def test_the_model_is_asked_for_names_the_etf_cannot_hold(facts):
    text = sector_ai.peers_prompt("Technology", ("AAPL", "MSFT"), 8)
    assert "outside the" in text and "United States" in text
    assert "AAPL, MSFT" in text  # and told not to repeat them


def test_proposals_come_back_as_plain_symbols(monkeypatch):
    monkeypatch.setattr(
        sector_ai.engine, "complete_attempts",
        lambda *a, accept=None, **kw: accept('{"symbols": ["asml.as", "7203.T"]}'),
    )
    out = sector_ai.propose_peers({}, "Technology", (), 8, spend_free=lambda p: True)
    assert out == ["ASML.AS", "7203.T"]


def test_a_proposal_we_already_have_is_dropped(monkeypatch):
    monkeypatch.setattr(
        sector_ai.engine, "complete_attempts",
        lambda *a, accept=None, **kw: accept('{"symbols": ["AAPL", "ASML.AS"]}'),
    )
    out = sector_ai.propose_peers({}, "Technology", ("AAPL",), 8,
                                  spend_free=lambda p: True)
    assert out == ["ASML.AS"]


def test_a_reply_that_is_not_json_is_a_miss_not_a_crash(monkeypatch):
    seen = {}

    def attempts(*a, accept=None, **kw):
        seen["verdict"] = accept("Sure! Here are some great European tech names:")
        return None

    monkeypatch.setattr(sector_ai.engine, "complete_attempts", attempts)
    assert sector_ai.propose_peers({}, "Technology", (), 8,
                                   spend_free=lambda p: True) == []
    assert seen["verdict"] is None  # rejected, so the next provider gets a turn


def test_no_provider_leaves_the_sector_with_its_etf(monkeypatch):
    monkeypatch.setattr(sector_ai.engine, "complete_attempts",
                        lambda *a, **kw: None)
    assert sector_ai.propose_peers({}, "Energy", (), 8,
                                   spend_free=lambda p: True) == []


# --------------------------------------------------------------- the facts


def test_the_facts_carry_percentages_in_the_units_a_verdict_prints(facts):
    top = facts["podium"][0]
    assert top["ticker"] == "AAPL" and top["rank"] == 1
    assert top["roic_pct"] == 34.0  # 0.34 stored, "34%" written
    assert top["score_pct"] == 82.0
    assert top["pe_ttm"] == 28.0  # a multiple is not a rate


def test_the_facts_know_what_the_reader_already_holds(facts):
    assert facts["held_in_cohort"] == ["NVDA"]
    assert [p["held"] for p in facts["podium"]] == [False, False, True]


def test_a_podium_place_with_no_metrics_row_still_appears():
    scan = _scan(podium=("AAPL", "MSFT", "GHOST"))
    rows = sector_ai.build_facts(scan)["podium"]
    assert [r["ticker"] for r in rows] == ["AAPL", "MSFT", "GHOST"]
    assert rows[2]["roic_pct"] is None


# -------------------------------------------------------------- the verdict


def test_a_verdict_quoting_the_real_figures_is_kept(facts):
    raw = (
        "AAPL leads on quality at a price the others do not ask.\n"
        "- AAPL: ROIC of 34% against a P/E of 28.\n"
        "- MSFT: a 36.2% net margin, and growth of 14.5%.\n"
        "- NVDA: the best ROIC here at 55%, and the one you already hold."
    )
    verdict = sector_ai.parse(raw, facts=facts, lang="en")
    assert verdict is not None
    assert verdict.source == "llm"
    assert verdict.headline.startswith("AAPL leads")
    assert len(verdict.bullets) == 3
    assert not verdict.bullets[0].startswith("-")  # bullet furniture stripped


def test_an_invented_percentage_kills_the_whole_verdict(facts):
    raw = (
        "AAPL leads the screen.\n"
        "AAPL trades on a free cash flow yield of 9.4%."  # it is 3.8%
    )
    assert sector_ai.parse(raw, facts=facts, lang="en") is None


def test_a_verdict_about_other_companies_is_rejected(facts):
    raw = ("Samsung and TSMC look like the best value in Asian technology.\n"
           "Both are cheaper than their American peers.")
    assert sector_ai.parse(raw, facts=facts, lang="en") is None


def test_an_empty_reply_is_a_miss(facts):
    assert sector_ai.parse("   \n  \n", facts=facts, lang="en") is None


def test_only_three_bullets_survive(facts):
    raw = "AAPL leads.\n" + "\n".join(f"AAPL point {i}" for i in range(6))
    verdict = sector_ai.parse(raw, facts=facts, lang="en")
    assert len(verdict.bullets) == sector_ai.MAX_BULLETS


def test_generation_asks_in_the_readers_language(facts):
    system, messages = sector_ai.prompt(facts, "es")
    assert "Spanish" in system
    assert "Technology" in messages[0]["content"]
    assert "34.0" in messages[0]["content"]  # the figures, not the fractions


def test_a_thin_podium_is_never_sent_to_a_model(monkeypatch):
    called = []
    monkeypatch.setattr(sector_ai.engine, "complete_attempts",
                        lambda *a, **kw: called.append(1))
    facts = sector_ai.build_facts(_scan(podium=(), scores={}))
    assert sector_ai.generate({}, facts, "en") is None
    assert called == []  # no podium, no question worth paying for


# ------------------------------------------------------------- the fallback


def test_every_provider_down_still_names_the_leader(facts, monkeypatch):
    monkeypatch.setattr(sector_ai.engine, "complete_attempts",
                        lambda *a, **kw: None)
    assert sector_ai.generate({}, facts, "en") is None
    fallback = sector_ai.computed(facts, "en")
    assert fallback.source == "computed"
    assert "AAPL" in fallback.headline


def test_the_fallback_says_only_what_the_podium_cannot(facts):
    """The card above it already prints each place's rank, score and figures.

    Restating them was this block's entire content, which on a phone meant
    scrolling the same three numbers twice. What is left is the one thing the
    podium has no room for: which of the three the reader already owns.
    """
    fallback = sector_ai.computed(facts, "en")
    body = " ".join(fallback.bullets)
    assert "NVDA" in body  # the held line
    assert "34" not in body and "/100" not in body  # ...and no restated figures
    assert len(fallback.bullets) == 1


def test_a_reader_who_owns_none_of_the_three_gets_no_bullets(facts):
    plain = sector_ai.build_facts(_scan())  # held=() by default
    assert sector_ai.computed(plain, "en").bullets == ()


def test_the_fallback_speaks_the_readers_language(facts):
    assert "encabeza" in sector_ai.computed(facts, "es").headline
    assert "cartera" in sector_ai.computed(facts, "es").bullets[0]


def test_the_fallback_says_so_when_there_is_no_podium():
    facts = sector_ai.build_facts(_scan(podium=(), scores={}))
    fallback = sector_ai.computed(facts, "en")
    assert fallback.bullets == ()
    assert "Technology" in fallback.headline


def test_a_verdict_survives_a_round_trip(facts):
    verdict = sector_ai.computed(facts, "en")
    back = sector_ai.Verdict.from_dict(verdict.to_dict())
    assert back == verdict
