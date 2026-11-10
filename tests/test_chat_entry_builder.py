"""The entry builder: what it hears, the lines it drafts, and what Save takes."""

from __future__ import annotations

import pytest

from stocks.chat import a2ui, plan_builder
from stocks.chat import entry_builder as eb
from stocks.portfolio import entry


def tr(key: str, **kw) -> str:
    return key + (str(sorted(kw.items())) if kw else "")


@pytest.mark.parametrize("message", [
    "Propón mis criterios de entrada",
    "¿me ayudas a definir unos criterios de compra?",
    "escríbeme las reglas de entrada para comprar",
    "crea criterios de entrada para mi plan",
    "Propose my entry criteria",
    "help me write a buying checklist",
    "Proponi i miei criteri di ingresso",
])
def test_asking_for_entry_criteria_is_heard(message):
    assert eb.wants(message)


@pytest.mark.parametrize("message", [
    "¿qué son los criterios de entrada de Mi plan?",
    "what are entry criteria?",
    "Móntame un plan de inversión",
    "propón reglas de salida para NVDA",
    "¿cumple NVDA mis criterios de entrada?",
])
def test_other_questions_are_not(message):
    assert not eb.wants(message)


def test_the_button_prompt_is_heard_in_every_language():
    import json
    from pathlib import Path

    root = Path(eb.__file__).parents[1] / "web" / "locales"
    for lang in ("es", "en", "it"):
        for catalog, key in (("profile", "profile.entry_ask_prompt"),
                             ("ticker", "ticker.ai_prompt_entry")):
            prompt = json.loads((root / lang / f"{catalog}.json").read_text())[key]
            assert eb.wants(prompt), (lang, key)
            assert not plan_builder.wants(prompt), (lang, key)


def test_a_stranger_gets_balanced_lines_and_a_default_cap():
    k = eb.known({})
    drawn = eb.draft(k)
    levels = {r.rule: r.level for r in drawn.rules}
    assert k.risk is None and not k.replaces
    assert levels["pe_fwd_max"] == 25 and levels["weight_max"] == 8
    assert "dividend_yield_min" not in levels
    # Every drafted line is one the checklist itself would keep.
    assert entry.clean([{"rule": r.rule, "level": r.level} for r in drawn.rules]) \
        == drawn.rules


def test_more_risk_buys_more_growth_at_a_higher_multiple():
    def lines(risk):
        k = eb.known({"investor_profile": {"risk": risk, "set": True}})
        return {r.rule: r.level for r in eb.draft(k).rules}

    calm, bold = lines("conservative"), lines("very_aggressive")
    assert bold["revenue_growth_min"] > calm["revenue_growth_min"]
    assert bold["pe_fwd_max"] > calm["pe_fwd_max"]
    assert "op_margin_min" in calm and "op_margin_min" not in bold


def test_the_plan_cap_a_dividend_focus_and_the_note_are_kept():
    prefs = {
        "investor_profile": {"risk": "aggressive", "focus": ["dividends_value"],
                             "set": True},
        "investor_plan": {"limits": {"max_position_pct": 6}, "set": True},
        "entry_criteria": {"rules": [{"rule": "pe_fwd_max", "level": 18}],
                           "note": "nada de biotech sin ingresos"},
    }
    k = eb.known(prefs)
    drawn = eb.draft(k)
    levels = {r.rule: r.level for r in drawn.rules}
    assert levels["weight_max"] == 6
    assert levels["dividend_yield_min"] == 2.5
    assert drawn.note == "nada de biotech sin ingresos"
    assert k.replaces


def test_the_card_holds_the_draft_in_fields_and_says_it_replaces():
    k = eb.known({"entry_criteria": {"note": "solo rentables"}})
    (_create, comps, data) = eb.surface(k, tr)
    parts = {c["id"]: c for c in comps["updateComponents"]["components"]}
    fields = [i for i in parts if i.startswith("f_") and i != "f_note"]
    assert len(fields) == len(eb.draft(k).rules)
    assert parts["hint"]["text"] == "chat.entry_note_replace"
    model = data["updateDataModel"]["value"]["e"]
    assert model["pe_fwd_max"] == "25" and model["note"] == "solo rentables"
    sent = parts["save"]["action"]["event"]["context"]
    assert set(sent) == {*entry.RULES, "note"}
    for c in comps["updateComponents"]["components"]:
        a2ui.component(c["id"], c["component"],
                       **{k: v for k, v in c.items() if k not in ("id", "component")})


def test_save_takes_the_fields_as_typed_and_blank_is_no_line():
    typed = eb.typed({"pe_fwd_max": "32,5", "roic_min": "", "weight_max": "7 %",
                      "note": "  solo rentables "})
    assert {r.rule: r.level for r in typed.rules} == {"pe_fwd_max": 32.5,
                                                      "weight_max": 7}
    assert typed.note == "solo rentables"


@pytest.mark.parametrize("bad", [{"pe_fwd_max": "mucho"}, {"pe_fwd_max": "0"},
                                 {"weight_max": "150"}])
def test_save_refuses_a_field_it_cannot_take(bad):
    with pytest.raises(ValueError, match=next(iter(bad))):
        eb.typed(bad)


def test_the_prompt_tells_the_model_not_to_redo_the_card():
    line = eb.known({}).line()
    assert "The app drew an entry checklist" in line
    assert "do not propose levels" in line
