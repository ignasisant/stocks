"""The plan builder: what it hears, what it asks, and the card it draws."""

from __future__ import annotations

import pytest

from stocks.chat import a2ui
from stocks.chat import plan_builder as pb
from stocks.portfolio import plan as plans


def tr(key: str, **kw) -> str:
    return key + (str(sorted(kw.items())) if kw else "")


@pytest.mark.parametrize("message", [
    "Móntame un plan de inversión",
    "¿me ayudas a crear un plan para mi cartera?",
    "hazme un plan",
    "quiero definir mi plan",
    "build me an investment plan",
    "can you help me set up a plan?",
    "fes-me un pla d'inversió",
])
def test_asking_for_a_plan_is_heard(message):
    assert pb.wants(message)


@pytest.mark.parametrize("message", [
    "¿qué es un plan de pensiones?",
    "hazme un plan de pensiones",
    "plan de acción para NVDA",
    "cuánto pesa NVDA en mi cartera",
    "hazme un plano de la casa",
    "make a business plan for my shop",
    "¿qué planes tiene Apple?",
])
def test_other_plans_are_not(message):
    assert not pb.wants(message)


def test_a_stranger_is_asked_what_matters_most_and_no_more():
    k = pb.known({}, {})
    assert pb.questions(k) == (pb.RISK, pb.HORIZON, pb.CUSHION, pb.AMOUNT)
    assert len(pb.questions(k)) <= pb.MOST


def test_what_is_known_is_not_asked():
    prefs = {
        "investor_profile": {"risk": "aggressive", "horizon": "5y_plus",
                             "focus": ["crypto"], "set": True},
        "investor_plan": {"contribution": {"amount": 500, "every": "monthly"},
                          "set": True},
    }
    k = pb.known(prefs, {"stocks": 70.0, "equity_funds": 10.0})
    assert (k.risk, k.horizon, k.amount, k.style, k.crypto) == (
        "aggressive", "5y_plus", 500.0, "stocks", "some")
    assert pb.questions(k) == (pb.CUSHION,)
    assert k.replaces


def test_an_unsaved_profile_is_asked_again():
    """The defaults the form pre-selects are a guess, not an answer."""
    k = pb.known({"investor_profile": {"risk": "aggressive"}}, {})
    assert k.risk is None and pb.RISK in pb.questions(k)


def test_a_book_that_does_not_lean_leaves_the_style_open():
    k = pb.known({"investor_profile": {"risk": "balanced", "horizon": "3_5y",
                                       "set": True}},
                 {"stocks": 50.0, "equity_funds": 50.0})
    assert k.style is None and pb.STYLE in pb.questions(k)


def test_the_draft_is_the_rule_on_the_answers():
    k = pb.known({}, {})
    picked = {"risk": "conservative", "horizon": "1_3y", "cushion": "short",
              "style": "funds", "crypto": "none", "amount": "1.500,50",
              "every": "quarterly"}
    assert pb.draft(k, picked) == plans.suggest(plans.Answers(
        "conservative", "1_3y", "short", "funds", "none", 1500.5, "quarterly"))


def test_a_pick_outside_its_choices_is_not_one():
    k = pb.known({}, {})
    assert pb.answers(k, {"risk": "yolo"}).risk == "balanced"


def test_a_half_typed_amount_does_not_break_the_draft():
    assert pb.answers(pb.known({}, {}), {"amount": "12,,"}).amount is None
    with pytest.raises(ValueError):
        pb.amount_of("12,,")


def test_the_card_is_one_well_formed_surface():
    k = pb.known({}, {"stocks": 40.0, "cash": 60.0})
    messages = pb.surface(k, tr)
    a2ui.check(messages)
    data = messages[-1]["updateDataModel"]["value"]
    assert set(data["a"]) == {*pb.CHOICES, pb.AMOUNT, pb.INVESTABLE, "every"}
    assert abs(sum(s["weight"] for s in data["view"]["slices"]) - 1) < 1e-9
    ids = {c["id"] for c in messages[1]["updateComponents"]["components"]}
    assert {"q_risk", "q_horizon", "q_cushion", "q_amount", "q_investable", "save"} <= ids
    assert "q_style" not in ids and "q_crypto" not in ids


def test_every_chip_and_save_carry_every_answer():
    messages = pb.surface(pb.known({}, {}), tr)
    for comp in messages[1]["updateComponents"]["components"]:
        if "action" in comp:
            context = comp["action"]["event"]["context"]
            assert set(context) == {*pb.CHOICES, pb.AMOUNT, pb.INVESTABLE, "every"}


def test_the_prompt_says_the_card_is_drawn_and_forbids_figures():
    said = pb.known({}, {"stocks": 100.0}).line("es")
    assert "drew a plan builder" in said and "stocks 100%" in said
    assert "risk, horizon, cushion, amount" in said
    assert "do not ask the card's questions again" in said
    assert "Do not describe how the card works" in said
    assert "figures of your own" in said


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_profile_press_asks_in_words_the_builder_hears(lang):
    """Profile → My plan's AI press sends `profile.plan_ask_prompt`; a
    rewording the detector misses would answer with prose and no card."""
    from stocks.web.i18n import translate

    assert pb.wants(translate("profile.plan_ask_prompt", lang))
