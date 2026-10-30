"""The daily card measured against the reader's plan (signals.plan_candidates).

Each trigger fires on the book that earns it and stays quiet on the one that
does not; the plan's cap takes the app's concentration line's place; the
lines read in both languages; and every line carries a link to the page that
resolves it.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from stocks.chat import daily, signals
from stocks.portfolio import plan as plans

DAY = date(2026, 10, 30)

KINDS = {
    "NVDA": "stock", "AAPL": "stock", "MSFT": "stock", "VWCE.DE": "equity_fund",
    "AGGH": "bond_fund", "XEON.DE": "money_market", "BTC-EUR": "crypto",
}


def _book(weights: dict[str, float], pnl: dict[str, float] | None = None,
          value: float | None = None):
    pnl = pnl or {}
    cols = {
        "weight": weights,
        "pnl_pct": {t: pnl.get(t, 0.05) for t in weights},
        "pnl": {t: 100.0 for t in weights},
    }
    if value is not None:
        cols["value"] = {t: w * value for t, w in weights.items()}
    return pd.DataFrame(cols)


def _plan(**blocks) -> plans.Plan:
    return plans.parse({**blocks, "set": True})


def _signals(investor, weights, *, sectors=None, holdings=(), criteria=(),
             day=DAY, value=None):
    return signals.plan_candidates(
        investor,
        tbl=_book(weights, value=value),
        kind_of=KINDS.get,
        sectors=sectors or {},
        holdings=holdings,
        criteria=criteria,
        currency="EUR",
        today=day,
    )


def _kinds(found) -> list[str]:
    return [s.kind for s in found]


MIX = {"targets": {"stocks": 40, "equity_funds": 40, "bonds": 10, "cash": 10},
       "band_pp": 5}
KEPT = {"NVDA": 0.12, "AAPL": 0.14, "MSFT": 0.14, "VWCE.DE": 0.40,
        "AGGH": 0.10, "XEON.DE": 0.10}


# ------------------------------------------------------------------- the mix


def test_a_book_on_plan_raises_no_plan_line():
    investor = _plan(mix=MIX, limits={"max_position_pct": 20})
    alerted = [SimpleNamespace(ticker=t, alerts=[object()]) for t in KEPT]
    found = _signals(investor, KEPT, holdings=alerted)
    assert found == []


def test_a_bucket_past_its_band_is_one_line_with_its_figures():
    heavy = {**KEPT, "NVDA": 0.30, "VWCE.DE": 0.22}
    total = sum(heavy.values())
    found = _signals(_plan(mix=MIX), {t: w / total for t, w in heavy.items()})
    drift = [s for s in found if s.kind == signals.PLAN_DRIFT]
    over = next(s for s in drift if s.data["side"] == "over")
    assert over.data["bucket"] == "stocks"
    assert over.data["target_pct"] == 40
    assert over.data["actual_pct"] > 45
    assert over.key == "plan_drift:stocks"
    assert any(s.data["side"] == "under" for s in drift)


def test_a_cash_shortfall_is_said_by_the_reserve_not_twice():
    thin = {**KEPT, "XEON.DE": 0.01, "VWCE.DE": 0.49}
    investor = _plan(mix=MIX, reserve={"min_pct": 8, "max_pct": 15})
    found = _signals(investor, thin)
    reserve = [s for s in found if s.kind == signals.RESERVE]
    assert [s.data["state"] for s in reserve] == ["low"]
    assert not any(s.kind == signals.PLAN_DRIFT and s.data["bucket"] == "cash"
                   for s in found)


def test_idle_cash_over_the_reserve_reads_high():
    idle = {"VWCE.DE": 0.5, "XEON.DE": 0.5}
    found = _signals(_plan(reserve={"max_pct": 20}), idle)
    assert [s.data["state"] for s in found if s.kind == signals.RESERVE] == ["high"]


def test_stated_cash_fills_the_reserve_the_book_alone_misses():
    thin = {**KEPT, "XEON.DE": 0.01, "VWCE.DE": 0.49}
    reserve = {"min_pct": 8, "max_pct": 15}
    bare = _signals(_plan(reserve=reserve), thin, value=10_000)
    assert [s.data["state"] for s in bare if s.kind == signals.RESERVE] == ["low"]
    covered = _plan(reserve=reserve,
                    cash={"investable": 1000, "as_of": DAY.isoformat()})
    assert not any(s.kind == signals.RESERVE
                   for s in _signals(covered, thin, value=10_000))


def test_the_cushion_never_counts_toward_the_reserve():
    thin = {**KEPT, "XEON.DE": 0.01, "VWCE.DE": 0.49}
    investor = _plan(reserve={"min_pct": 8},
                     cash={"cushion": 50_000, "as_of": DAY.isoformat()})
    found = _signals(investor, thin, value=10_000)
    assert [s.data["state"] for s in found if s.kind == signals.RESERVE] == ["low"]


def test_cash_stated_long_ago_asks_to_be_updated_once():
    old = _plan(cash={"investable": 1000, "as_of": "2026-08-01"})
    found = [s for s in _signals(old, KEPT, value=10_000)
             if s.kind == signals.CASH_STALE]
    assert [s.data["days"] for s in found] == [90]
    fresh = _plan(cash={"investable": 1000, "as_of": "2026-10-01"})
    assert not any(s.kind == signals.CASH_STALE
                   for s in _signals(fresh, KEPT, value=10_000))


# ------------------------------------------------------------------ the caps


def test_a_position_past_the_plans_cap_is_a_plan_limit():
    found = _signals(_plan(limits={"max_position_pct": 10}), KEPT)
    limits = [s for s in found if s.kind == signals.PLAN_LIMIT]
    # VWCE.DE is 40 % too, but a fund is not one position's risk.
    assert [s.ticker for s in limits] == ["AAPL", "MSFT", "NVDA"]
    assert all(s.data["cap_pct"] == 10 for s in limits)
    assert all(s.data["weight_pct"] > 10 for s in limits)


def test_a_sector_past_its_cap_is_keyed_on_the_sector():
    found = _signals(_plan(limits={"max_sector_pct": 30}), KEPT,
                     sectors={"Technology": 0.40, "Funds": 0.50, "Unknown": 0.1})
    sector = [s for s in found if s.kind == signals.PLAN_LIMIT]
    assert [s.data["sector"] for s in sector] == ["Technology"]
    assert sector[0].key == "plan_limit:Technology"


def test_the_plans_cap_takes_concentrations_place():
    heavy = _book({"NVDA": 0.45, "VWCE.DE": 0.55})
    plain = signals.candidates(tbl=heavy, today=DAY)
    capped = signals.candidates(tbl=heavy, today=DAY, concentration=False)
    assert signals.CONCENTRATION in _kinds(plain)
    assert signals.CONCENTRATION not in _kinds(capped)


@pytest.mark.parametrize(("risk", "fires"), [
    ("conservative", True), ("balanced", True), (None, False),
    ("very_aggressive", False),
])
def test_the_drawdown_line_follows_the_readers_risk(risk, fires):
    down = _book({"NVDA": 0.5, "AAPL": 0.5}, pnl={"NVDA": -0.22})
    found = signals.candidates(tbl=down, today=DAY,
                               drawdown_pct=signals.drawdown_line(risk))
    assert (signals.DRAWDOWN in _kinds(found)) is fires


# ------------------------------------------------------------ the contribution


@pytest.mark.parametrize(("day", "due"), [
    (date(2026, 10, 30), True),   # the 1st is two days out
    (date(2026, 11, 1), True),    # today
    (date(2026, 11, 2), False),   # next is a month away
])
def test_a_contribution_is_named_only_when_close(day, due):
    investor = _plan(contribution={"amount": 500, "every": "monthly", "day": 1})
    found = _signals(investor, KEPT, day=day)
    assert (signals.CONTRIBUTION_DUE in _kinds(found)) is due


def test_a_due_contribution_names_the_buckets_under_target():
    light = {**KEPT, "AGGH": 0.0, "VWCE.DE": 0.50}
    investor = _plan(mix=MIX, contribution={"amount": 500, "day": 1})
    found = _signals(investor, light)
    due = next(s for s in found if s.kind == signals.CONTRIBUTION_DUE)
    assert due.data["under"] == ["bonds"]
    assert due.data["amount"] == 500
    assert due.data["phase"] == "soon"


# ---------------------------------------------------------------- exit rules


def test_the_heaviest_unguarded_company_asks_for_an_exit_rule():
    found = _signals(_plan(limits={"max_position_pct": 20}), KEPT)
    rule = [s for s in found if s.kind == signals.NO_EXIT_RULE]
    assert [s.ticker for s in rule] == ["AAPL"]


def test_a_position_with_a_rule_or_an_alert_is_guarded():
    investor = _plan(limits={"max_position_pct": 20})
    criteria = [{"ticker": "AAPL", "rule": "below"}]
    holdings = [SimpleNamespace(ticker="MSFT", alerts=[object()])]
    found = _signals(investor, KEPT, criteria=criteria, holdings=holdings)
    assert [s.ticker for s in found if s.kind == signals.NO_EXIT_RULE] == ["NVDA"]


def test_a_big_fund_needs_no_exit_rule():
    found = _signals(_plan(limits={"max_position_pct": 20}),
                     {"VWCE.DE": 0.9, "AGGH": 0.1})
    assert signals.NO_EXIT_RULE not in _kinds(found)


# --------------------------------------------------------------- no plan yet


def test_without_a_plan_the_card_invites_one_once():
    found = _signals(plans.Plan(), KEPT)
    assert signals.PLAN_MISSING in _kinds(found)
    assert not {signals.PLAN_DRIFT, signals.PLAN_LIMIT, signals.RESERVE,
                signals.CONTRIBUTION_DUE} & set(_kinds(found))
    invite = next(s for s in found if s.kind == signals.PLAN_MISSING)
    shown = {invite.key: {"last": "2026-10-20", "run": 1, "v": {}}}
    later = signals.candidates(plan=found, shown=shown, today=DAY)
    assert signals.PLAN_MISSING not in _kinds(later)


def test_a_watchlist_only_account_is_not_asked_for_a_plan():
    assert signals.plan_candidates(plans.Plan(), tbl=None, today=DAY) == []


def test_an_unchanged_drift_is_not_said_again_the_next_day():
    heavy = {"NVDA": 0.6, "VWCE.DE": 0.4}
    investor = _plan(mix={"targets": {"stocks": 40, "equity_funds": 60}})
    first = [s for s in _signals(investor, heavy) if s.kind == signals.PLAN_DRIFT]
    shown = {s.key: {"last": "2026-10-29", "run": 1,
                     "v": signals.measure(s.kind, s.data)} for s in first}
    again = signals.candidates(plan=first, shown=shown, today=DAY)
    assert again == []
    moved = signals.plan_candidates(
        investor, tbl=_book({"NVDA": 0.7, "VWCE.DE": 0.3}), kind_of=KINDS.get,
        today=DAY)
    assert signals.PLAN_DRIFT in _kinds(
        signals.candidates(plan=moved, shown=shown, today=DAY))


# ----------------------------------------------------------- lines and links


def _all_plan_actions():
    investor = _plan(
        mix=MIX, limits={"max_position_pct": 10, "max_sector_pct": 30},
        contribution={"amount": 500, "day": 1}, reserve={"min_pct": 12},
        cash={"investable": 0, "as_of": "2026-07-01"},
    )
    heavy = {**KEPT, "AGGH": 0.0, "XEON.DE": 0.02, "NVDA": 0.20}
    found = _signals(investor, heavy, sectors={"Technology": 0.46})
    found += _signals(plans.Plan(), KEPT)
    return [s.to_dict() for s in found]


def test_every_plan_kind_is_drawn():
    kinds = {a["kind"] for a in _all_plan_actions()}
    assert kinds == {
        signals.PLAN_DRIFT, signals.PLAN_LIMIT, signals.CONTRIBUTION_DUE,
        signals.RESERVE, signals.NO_EXIT_RULE, signals.PLAN_MISSING,
        signals.CASH_STALE,
    }


@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_plan_line_reads_with_its_figures(lang):
    for action in _all_plan_actions():
        line = daily._action_line(action, lang, "EUR")
        assert line and "{" not in line, action
        assert daily._short_line(action, lang), action
        detail = daily._detail_line(action, {}, lang, "EUR")
        assert detail.startswith(line) and len(detail) > len(line)
        if action.get("ticker"):
            assert action["ticker"] in line
    drift = next(a for a in _all_plan_actions() if a["kind"] == signals.PLAN_DRIFT)
    assert "40%" in daily._action_line(drift, lang, "EUR")


def test_the_computed_card_carries_the_plan_lines():
    facts = {"currency": "EUR", "actions": _all_plan_actions()[:4]}
    card = daily.computed(facts, "es", DAY)
    assert len(card.items) == 4
    assert {i["kind"] for i in card.items} <= {a["kind"] for a in facts["actions"]}


@pytest.mark.parametrize(("kind", "tickers", "go"), [
    (signals.PLAN_DRIFT, [], "/profile?tab=plan"),
    (signals.RESERVE, [], "/profile?tab=plan"),
    (signals.CASH_STALE, [], "/profile?tab=plan"),
    (signals.PLAN_MISSING, [], "/profile?tab=plan"),
    (signals.PLAN_LIMIT, ["NVDA"], "/review"),
    (signals.CONTRIBUTION_DUE, [], "/review"),
    (signals.CONCENTRATION, ["NVDA"], "/review"),
    (signals.DRAWDOWN, ["NVDA"], "/review"),
    (signals.HARVEST, ["NVDA"], "/portfolio?tab=tax"),
    (signals.TAX_YEAR_END, [], "/portfolio?tab=tax"),
    (signals.EARNINGS, ["NVDA"], "/earnings"),
    (signals.NO_EXIT_RULE, ["NVDA"], "/profile?tab=journal"),
    (signals.CRITERION_HIT, ["NVDA"], "/profile?tab=journal"),
    (signals.SECTOR_TILT, [], "/sector"),
    (signals.LOW_52W, ["ASML.AS"], ""),  # the ticker cell is the link
    (signals.MARKET, [], ""),
    ("", [], ""),
])
def test_each_line_links_to_the_page_that_resolves_it(kind, tickers, go):
    assert daily.go_of({"kind": kind, "tickers": tickers}) == go


def test_every_link_lands_on_a_page_the_shell_serves():
    from stocks import navigation

    served = set(navigation.SHELL_PATHS) | {""}
    for kind in signals._URGENCY:
        go = daily.go_of({"kind": kind, "tickers": ["NVDA"]})
        if go:
            assert go.split("?")[0].strip("/") in served, kind


# ------------------------------------------------------------ the plan holds


def test_a_plan_that_holds_is_what_a_quiet_day_says():
    from stocks.api import briefing

    investor = _plan(mix=MIX, contribution={"amount": 500, "day": 1})
    fact = briefing.plan_fact(investor, _signals(investor, KEPT), DAY)
    assert fact == {"on_track": True, "next_contribution": "2026-11-01",
                    "amount": 500.0}
    card = daily.computed({"currency": "EUR", "plan": fact}, "es", DAY)
    assert card.headline.startswith("Tu plan se cumple")
    assert any("500" in b and "01/11" in b for b in card.bullets)


def test_a_drift_already_said_still_means_the_plan_does_not_hold():
    from stocks.api import briefing

    investor = _plan(mix={"targets": {"stocks": 40, "equity_funds": 60}})
    found = _signals(investor, {"NVDA": 0.6, "VWCE.DE": 0.4})
    fact = briefing.plan_fact(investor, found, DAY)
    assert fact == {"on_track": False}
    card = daily.computed({"currency": "EUR", "plan": fact}, "en", DAY)
    assert "plan holds" not in card.headline


def test_no_plan_no_plan_fact():
    from stocks.api import briefing

    assert briefing.plan_fact(plans.Plan(), [], DAY) is None
