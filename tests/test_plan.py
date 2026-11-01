"""The investor plan: what is read from prefs, and what it measures."""

from __future__ import annotations

from datetime import date

from stocks.portfolio import plan as P


def _kind(ticker: str) -> str | None:
    return {
        "VWCE.DE": "equity_fund",
        "XEON.DE": "money_market",
        "AGGH.L": "bond_fund",
        "BTC-EUR": "crypto",
        "^GSPC": "index",
    }.get(ticker, "stock")


def test_no_plan_is_empty():
    plan = P.load({})
    assert plan.empty and not plan.set
    assert P.drift(plan, {"stocks": 100}) == []
    assert P.next_contribution(plan, date(2026, 10, 30)) is None


def test_mix_must_add_up_to_the_whole_book():
    assert P.parse({"mix": {"targets": {"stocks": 60, "cash": 30}}}).mix is None
    mix = P.parse({"mix": {"targets": {"stocks": 70, "cash": 30}}}).mix
    assert mix is not None and mix.band_pp == P.DEFAULT_BAND_PP
    assert mix.targets == {
        "stocks": 70,
        "equity_funds": 0,
        "bonds": 0,
        "cash": 30,
        "crypto": 0,
    }


def test_bad_blocks_are_left_out_not_half_applied():
    plan = P.parse(
        {
            "reserve": {"min_pct": 20, "max_pct": 10},
            "contribution": {"amount": -5},
            "limits": {
                "max_position_pct": 0,
                "max_sector_pct": "x",
                "max_speculative_pct": 4,
            },
        }
    )
    assert plan.reserve is None and plan.contribution is None
    assert plan.limits == P.Limits(max_speculative_pct=4)


def test_buckets_read_over_the_priced_rows():
    weights = {
        "AAPL": 0.4,
        "VWCE.DE": 0.3,
        "XEON.DE": 0.1,
        "BTC-EUR": float("nan"),
        "^GSPC": 0.2,
    }
    shares = P.buckets(weights, _kind)
    assert shares == {
        "stocks": 50.0,
        "equity_funds": 37.5,
        "bonds": 0.0,
        "cash": 12.5,
        "crypto": 0.0,
    }
    assert round(sum(shares.values()), 6) == 100


def test_drift_names_the_buckets_outside_their_band_furthest_first():
    plan = P.parse(
        {"mix": {"targets": {"stocks": 50, "equity_funds": 30, "cash": 20}, "band_pp": 5}}
    )
    found = P.drift(plan, {"stocks": 70, "equity_funds": 26, "cash": 4})
    assert [(d.bucket, d.gap_pp, d.side) for d in found] == [
        ("stocks", 20.0, "over"),
        ("cash", -16.0, "under"),
    ]


def test_reserve_reads_the_cash_bucket():
    plan = P.parse({"reserve": {"min_pct": 5, "max_pct": 15}})
    assert P.reserve_state(plan, {"cash": 2}) == "low"
    assert P.reserve_state(plan, {"cash": 30}) == "high"
    assert P.reserve_state(plan, {"cash": 10}) is None


def test_caps_on_positions_and_sectors():
    plan = P.parse({"limits": {"max_position_pct": 10, "max_sector_pct": 40}})
    assert P.over_position(plan, {"NVDA": 0.35, "AAPL": 0.08, "MSFT": 0.12}) == [
        ("NVDA", 35.0),
        ("MSFT", 12.0),
    ]
    assert P.over_sector(plan, {"Technology": 0.55, "Energy": 0.1}) == [
        ("Technology", 55.0)
    ]


def test_next_contribution_monthly_and_quarterly():
    monthly = P.parse({"contribution": {"amount": 500, "every": "monthly", "day": 5}})
    assert P.next_contribution(monthly, date(2026, 10, 5)) == date(2026, 10, 5)
    assert P.next_contribution(monthly, date(2026, 10, 6)) == date(2026, 11, 5)
    quarterly = P.parse(
        {"contribution": {"amount": 1500, "every": "quarterly", "day": 28}}
    )
    assert P.next_contribution(quarterly, date(2026, 10, 30)) == date(2027, 1, 28)
    assert P.next_contribution(quarterly, date(2026, 2, 1)) == date(2026, 4, 28)


def test_a_contribution_spreads_over_the_months_it_covers():
    assert P.per_month(P.load({})) is None
    monthly = P.parse({"contribution": {"amount": 500, "every": "monthly"}})
    assert P.per_month(monthly) == 500
    quarterly = P.parse({"contribution": {"amount": 1500, "every": "quarterly"}})
    assert P.per_month(quarterly) == 500


def test_the_assistant_is_told_the_plan_in_one_sentence():
    assert P.describe(P.load({})) == ""
    said = P.describe(
        P.parse(
            {
                "mix": {"targets": {"stocks": 80, "crypto": 20}, "band_pp": 5},
                "limits": {"max_sector_pct": 35},
                "reserve": {"min_pct": 5},
            }
        )
    )
    assert "stocks 80%, crypto 20%" in said and "bonds" not in said
    assert "35% in one sector" in said
    assert "at least 5%" in said


def test_the_persona_carries_the_plan_with_or_without_a_profile():
    from stocks.chat.engine import persona
    from stocks.web import auth

    plan = {"set": True, "limits": {"max_position_pct": 10}}
    bare = persona(auth.load_profile({"investor_plan": plan}))
    assert bare.startswith("The signed-in user is an aggressive")
    assert "at most 10% in one position" in bare
    assert "plan" not in persona(auth.load_profile({}))
    # A plan nobody saved is not said.
    assert "Their own plan" not in persona(
        auth.load_profile({"investor_plan": {**plan, "set": False}})
    )


# ------------------------------------------------------------------ drafting

_RISKS = ("conservative", "balanced", "aggressive", "very_aggressive")
_HORIZONS = ("under_1y", "1_3y", "3_5y", "5y_plus")


def _every_answer():
    for risk in _RISKS:
        for horizon in _HORIZONS:
            for cushion in P.CUSHIONS:
                for style in P.STYLES:
                    for crypto in P.CRYPTO_WISH:
                        yield P.Answers(risk, horizon, cushion, style, crypto)


def test_every_draft_is_a_plan_the_form_would_take():
    from stocks.api.routes.prefs import PlanWrite

    for answers in _every_answer():
        drafted = P.suggest(answers)
        PlanWrite.model_validate(drafted)
        targets = drafted["mix"]["targets"]
        assert sum(targets.values()) == 100
        assert all(v == int(v) and v >= 0 for v in targets.values())
        assert P.parse({**drafted, "set": True}).mix is not None


def _equity(drafted: dict) -> float:
    t = drafted["mix"]["targets"]
    return t["stocks"] + t["equity_funds"] + t["crypto"]


def test_more_risk_never_draws_less_equity_or_crypto():
    for horizon in _HORIZONS:
        for cushion in P.CUSHIONS:
            for crypto in P.CRYPTO_WISH:
                drafts = [P.suggest(P.Answers(r, horizon, cushion, "mixed", crypto))
                          for r in _RISKS]
                equity = [_equity(d) for d in drafts]
                coins = [d["mix"]["targets"]["crypto"] for d in drafts]
                caps = [d["limits"]["max_position_pct"] for d in drafts]
                assert equity == sorted(equity), (horizon, cushion, crypto)
                assert coins == sorted(coins), (horizon, cushion, crypto)
                assert caps == sorted(caps)


def test_a_short_horizon_caps_equity_and_keeps_cash():
    soon = P.suggest(P.Answers("very_aggressive", "under_1y", "covered", "stocks",
                               "more"))
    t = soon["mix"]["targets"]
    assert _equity(soon) <= 20 and t["crypto"] == 0
    assert t["cash"] >= t["bonds"]
    near = P.suggest(P.Answers("very_aggressive", "1_3y", "covered", "stocks", "none"))
    assert _equity(near) <= 45 and near["mix"]["targets"]["cash"] >= 10


def test_no_cushion_outside_keeps_cash_inside():
    bare = P.suggest(P.Answers("aggressive", "5y_plus", "none"))
    covered = P.suggest(P.Answers("aggressive", "5y_plus", "covered"))
    assert bare["mix"]["targets"]["cash"] == 10
    assert bare["reserve"] == {"min_pct": 5.0, "max_pct": 15.0}
    assert covered["mix"]["targets"]["cash"] == 0 and covered["reserve"] is None


def test_crypto_is_at_most_a_third_of_equity():
    for answers in _every_answer():
        t = P.suggest(answers)["mix"]["targets"]
        assert t["crypto"] <= (t["stocks"] + t["equity_funds"] + t["crypto"]) / 3 + 1


def test_style_splits_equity_between_companies_and_funds():
    funds = P.suggest(P.Answers("balanced", "5y_plus", "covered", "funds"))
    stocks = P.suggest(P.Answers("balanced", "5y_plus", "covered", "stocks"))
    assert funds["mix"]["targets"]["equity_funds"] > funds["mix"]["targets"]["stocks"]
    assert stocks["mix"]["targets"]["stocks"] > stocks["mix"]["targets"]["equity_funds"]


def test_a_contribution_is_kept_only_when_named():
    assert P.suggest(P.Answers())["contribution"] is None
    assert P.suggest(P.Answers(amount=300, every="quarterly"))["contribution"] == {
        "amount": 300.0, "every": "quarterly", "day": 1}
    assert P.suggest(P.Answers(amount=300, every="weekly"))["contribution"][
        "every"] == "monthly"


# ---------------------------------------------------------------- stated cash


def test_cash_is_read_only_with_an_amount_and_a_sane_rate():
    assert P.parse({"cash": {"rate_pct": 2}}).cash is None
    assert P.parse({"cash": {"investable": -5}}).cash is None
    cash = P.parse(
        {"cash": {"investable": 4000, "rate_pct": 35, "as_of": "garbage"}}
    ).cash
    assert cash == P.Cash(4000.0, None, None, None)
    kept = P.parse(
        {"cash": {"investable": 0, "cushion": 9000, "rate_pct": 2.5,
                  "as_of": "2026-10-01"}}
    )
    assert kept.cash == P.Cash(0.0, 9000.0, 2.5, "2026-10-01")
    assert not kept.empty and kept.investable == 0.0


def test_stated_cash_joins_the_cash_bucket_and_dilutes_the_rest():
    shares = {"stocks": 80.0, "equity_funds": 0.0, "bonds": 0.0, "cash": 20.0,
              "crypto": 0.0}
    out = P.with_cash(shares, 10_000, 10_000)
    assert out["stocks"] == 40.0 and out["cash"] == 60.0
    assert abs(sum(out.values()) - 100) < 0.2
    assert P.with_cash(shares, 10_000, 0) == shares
    assert P.with_cash({}, 0, 500)["cash"] == 100.0
    # Shares with nothing to weigh the cash against are left alone.
    assert P.with_cash(shares, 0, 500) == shares


def test_stated_cash_goes_stale_after_sixty_days():
    plan = P.parse({"cash": {"investable": 100, "as_of": "2026-08-01"}})
    assert P.cash_stale(plan, date(2026, 9, 30)) is None
    assert P.cash_stale(plan, date(2026, 10, 30)) == 90
    undated = P.parse({"cash": {"investable": 100}})
    assert P.cash_stale(undated, date(2026, 10, 30)) is None
    assert P.cash_stale(P.load({}), date(2026, 10, 30)) is None


def test_a_changed_amount_is_dated_today_a_changed_rate_is_not():
    old = P.Cash(1000.0, 5000.0, 2.0, "2026-08-01")
    today = date(2026, 10, 30)
    rate = P.stamp_cash({"investable": 1000.0, "cushion": 5000.0, "rate_pct": 3.0},
                        old, today)
    assert rate == {"investable": 1000.0, "cushion": 5000.0, "rate_pct": 3.0,
                    "as_of": "2026-08-01"}
    moved = P.stamp_cash({"investable": 1200.0, "cushion": 5000.0}, old, today)
    assert moved["as_of"] == "2026-10-30"
    assert P.stamp_cash({"investable": 1.0}, None, today)["as_of"] == "2026-10-30"
    assert P.stamp_cash({"rate_pct": 2}, old, today) is None
    assert P.stamp_cash(None, old, today) is None


def test_the_assistant_is_told_the_cash_and_the_cushion_apart():
    said = P.describe(
        P.parse({"cash": {"investable": 4000, "cushion": 9000, "rate_pct": 2.5,
                          "as_of": "2026-10-01"}})
    )
    assert "4,000 of uninvested cash meant for the book earning 2.5% a year" in said
    assert "emergency fund of 9,000 kept apart, never to invest" in said
    assert "as of 2026-10-01" in said
    bare = P.describe(P.parse({"cash": {"investable": 0, "cushion": 0}}))
    assert "no emergency fund outside the book" in bare
    assert "uninvested" not in bare


def test_the_builder_keeps_the_cash_it_was_told():
    assert "cash" not in P.suggest(P.Answers())
    assert P.suggest(P.Answers(investable=2500))["cash"] == {"investable": 2500.0}
    assert P.suggest(P.Answers(investable=0))["cash"] == {"investable": 0.0}
    assert "cash" not in P.suggest(P.Answers(investable=float("nan")))
