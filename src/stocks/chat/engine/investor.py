"""The persona: the investor profile and plan, in English, as the system
prompt's opening paragraph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:

    pass


# English phrasings for the stored profile enum keys (auth.PROFILE_*). The
# system prompt is English regardless of UI language, so the persona is built
# from these, not from the localized form labels.

_RISK_EN = {
    "aggressive": "an aggressive",
    "very_aggressive": "a very aggressive",
    "balanced": "a balanced",
    "conservative": "a conservative",
}
_HORIZON_EN = {
    "5y_plus": "5+ year",
    "3_5y": "3–5 year",
    "1_3y": "1–3 year",
    "under_1y": "under-1-year",
}
_FOCUS_EN = {
    "tech": "technology and growth stocks",
    "em": "emerging markets",
    "crypto": "crypto assets",
    "dividends_value": "dividends, value and broad-index holdings",
}
_CONSTRAINT_EN = {
    # Not "no wash-sale rule": a model read that as "no repurchase rule" and
    # told a Spanish filer so, when the two-month rule is exactly that. What
    # the rules are is `tax_rules`' block, from the engine that applies them.
    "spain_tax": "factor in Spanish tax residency (IRPF)",
    "us_tax": (
        "factor in US tax residency (IRS; wash-sale rule, short versus "
        "long-term rates)"
    ),
    "eur": "reason and report in EUR",
    "no_leverage": "avoid recommending leverage, margin or derivatives",
    "esg": "apply ESG screening",
}


def _join_en(parts: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def persona(prof: dict) -> str:
    """The 'who am I advising' sentence, from a loaded investor profile
    (auth.load_profile(prefs)). Falls back to the historical default when the user
    hasn't filled the form yet (prof['set'] is False). The investor plan, when
    saved, follows either way (`portfolio.plan.describe`)."""
    return _who(prof) + _plan_said(prof)


def _plan_said(prof: dict) -> str:
    if not prof.get("plan"):
        return ""
    from stocks.portfolio import plan as plans

    return plans.describe(plans.parse(prof["plan"]))


def _who(prof: dict) -> str:
    if not prof.get("set"):
        return "The signed-in user is an aggressive long-term (5y+) investor. "
    risk = _RISK_EN.get(prof.get("risk"), "an aggressive")
    horizon = _HORIZON_EN.get(prof.get("horizon"), "5+ year")
    out = (
        f"The signed-in user describes themselves as {risk} investor with a "
        f"{horizon} time horizon. "
    )
    focus = [_FOCUS_EN[f] for f in prof.get("focus", []) if f in _FOCUS_EN]
    if focus:
        out += "They focus on " + _join_en(focus) + ". "
    cons = [_CONSTRAINT_EN[c] for c in prof.get("constraints", [])
            if c in _CONSTRAINT_EN]
    if cons:
        out += "Always respect these constraints: " + _join_en(cons) + ". "
    notes = (prof.get("notes") or "").strip()
    if notes:
        out += f"Additional context from the user: {notes} "
    return out
