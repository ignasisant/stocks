"""Write my entry criteria: a drafted checklist in the drawer, edited, and a Save.

"Propón mis criterios de entrada" is the checklist on Profile, My plan
(`portfolio.entry`) asked in words. A model asked it in prose lists ratios
the checklist cannot read, or levels of its own with nothing behind them.
What the app can do is draft the lines it can measure by one fixed rule, from
what it knows of the reader: the risk in their investor profile sets how much
growth and how high a multiple a buy may carry, a dividend focus adds a yield
line, and the position cap of their plan, when it states one, is the line
past which an add is refused. The reader edits any figure, blanks the lines
they do not want, and Save stores the checklist (`POST /chat/actions`,
`SAVE`) through the same model the form uses. The note of principles is the
reader's own words, so the draft keeps the one they wrote and never invents
one.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from stocks.chat import a2ui
from stocks.portfolio import entry
from stocks.portfolio import plan as plans
from stocks.userprefs import PROFILE_RISK

SURFACE_ID = "entry_builder"
SAVE = "save"

# Matched with the accents folded away: a verb that writes something, near the
# checklist named ...
_WRITE_RE = re.compile(
    r"\b(?:propon\w*|propo(?:sa|si)\w*|sugi\w*|suger\w*|escrib\w*|redact\w*|"
    r"crea\w*|defin\w*|fij(?:a|ar|ame)|haz(?:me)?|hacer(?:me)?|mont\w*|prepar\w*|"
    r"ayuda\w* a (?:escribir|definir|fijar|crear)|"
    r"propose|suggest|write|draft|create|define|set up|make|help me (?:write|set|define)|"
    r"proposa\w*|escriu\w*|fes(?:-me)?)\b"
    r".{0,40}"
    r"\b(?:criterios? de (?:entrada|compra)|reglas? de (?:entrada|compra)|"
    r"checklist de (?:entrada|compra)|entry (?:criteria|checklist|rules)|"
    r"buy(?:ing)? (?:criteria|checklist|rules)|criteris? d'entrada|"
    r"criteri di (?:ingresso|acquisto))\b",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(ch))


def wants(message: str) -> bool:
    """Whether the message asks the assistant to write the entry checklist.
    Asking what the checklist is ("¿qué son los criterios de entrada?") is
    a question for the prose, not a draft."""
    return bool(_WRITE_RE.search(_fold(message)))


# ------------------------------------------------------------------ the draft

# The lines by risk, in each rule's own unit (`entry.RULES`): a percent for a
# `pct` line, a multiple for an `x` one. More risk buys more growth at a higher
# multiple and leaves out the margin and cash floors a young company fails.
_BY_RISK: dict[str, dict[str, float]] = {
    "conservative": {"revenue_growth_min": 3, "op_margin_min": 15, "fcf_yield_min": 4,
                     "roic_min": 12, "pe_fwd_max": 20, "net_debt_ebitda_max": 2,
                     "dilution_max": 1},
    "balanced": {"revenue_growth_min": 7, "op_margin_min": 12, "fcf_yield_min": 3,
                 "roic_min": 10, "pe_fwd_max": 25, "net_debt_ebitda_max": 2.5,
                 "dilution_max": 2},
    "aggressive": {"revenue_growth_min": 15, "op_margin_min": 5, "roic_min": 8,
                   "pe_fwd_max": 40, "net_debt_ebitda_max": 3, "dilution_max": 4},
    "very_aggressive": {"revenue_growth_min": 25, "pe_fwd_max": 60,
                        "net_debt_ebitda_max": 3.5, "dilution_max": 6},
}
# The add cap when the plan states none, by the same risk.
_WEIGHT = {"conservative": 5, "balanced": 8, "aggressive": 10, "very_aggressive": 12}
# A dividend focus asks the yield it is after.
_DIVIDEND_YIELD = 2.5
_DEFAULT_RISK = "balanced"


@dataclass(frozen=True)
class Known:
    """What the draft is drawn from."""

    risk: str | None = None  # None: no profile saved, drafted as balanced
    dividends: bool = False  # the profile follows dividends and value
    cap: float | None = None  # the plan's position cap, percent
    note: str = ""  # the principles the reader already wrote
    replaces: bool = False  # a checklist is saved already

    def line(self, lang: str = "en") -> str:
        """The prompt's paragraph, as the other cards give it."""
        return prompt_line(self)


def known(prefs: Mapping) -> Known:
    profile = prefs.get("investor_profile") or {}
    told = bool(profile.get("set"))
    held = entry.load(prefs)
    cap = plans.load(prefs).limits.max_position_pct
    return Known(
        risk=(profile.get("risk")
              if told and profile.get("risk") in PROFILE_RISK else None),
        dividends=told and "dividends_value" in (profile.get("focus") or []),
        cap=cap if cap and 0 < cap <= 100 else None,
        note=held.note if held else "",
        replaces=held is not None,
    )


def draft(k: Known) -> entry.Checklist:
    """The checklist the rule draws for what is known."""
    levels = dict(_BY_RISK[k.risk or _DEFAULT_RISK])
    if k.dividends:
        levels["dividend_yield_min"] = _DIVIDEND_YIELD
    levels["weight_max"] = k.cap or _WEIGHT[k.risk or _DEFAULT_RISK]
    return entry.Checklist(entry.clean({"rule": r, "level": v}
                                       for r, v in levels.items()), k.note)


def typed(context: Mapping) -> entry.Checklist:
    """The checklist the fields hold, for Save: a blank field is no line.
    Raises ValueError naming the first field that is not a number, or whose
    figure the checklist does not take (a P/E under zero)."""
    rules = []
    for rule in entry.RULES:
        text = str(context.get(rule) or "").strip().replace(" ", "").rstrip("%")
        if not text:
            continue
        try:
            level = float(text.replace(",", "."))
        except ValueError as exc:
            raise ValueError(rule) from exc
        if not entry.clean([{"rule": rule, "level": level}]):
            raise ValueError(rule)
        rules.append({"rule": rule, "level": level})
    note = str(context.get("note") or "").strip()[:entry.MAX_NOTE]
    return entry.Checklist(entry.clean(rules), note)


# ------------------------------------------------------------------ the card


def _known(k: Known, translate) -> str:
    bits = []
    if k.risk:
        bits.append(translate(f"profile.iv_risk_{k.risk}"))
    if k.dividends:
        bits.append(translate("profile.iv_focus_dividends_value"))
    if k.cap:
        bits.append(translate("chat.entry_known_cap", cap=f"{k.cap:g}"))
    return translate("chat.entry_known", what=" · ".join(bits)) if bits else ""


def _label(rule: str, translate) -> str:
    unit = "%" if entry.RULES[rule][1] == "pct" else "×"
    return f"{translate(f'profile.entry_{rule}')} ({unit})"


def surface(k: Known, translate) -> list[dict]:
    """The drafted lines as fields, the reader's note under them, and Save."""
    drawn = draft(k)
    told = _known(k, translate)
    parts = [a2ui.component("title", "Text", text=translate("chat.entry_title"),
                            variant="h3")]
    order = ["title"]
    if told:
        parts.append(a2ui.component("known", "Text", text=told, variant="caption"))
        order.append("known")
    for line in drawn.rules:
        parts.append(a2ui.component(
            f"f_{line.rule}", "TextField", label=_label(line.rule, translate),
            value=a2ui.path(f"/e/{line.rule}"), variant="number"))
        order.append(f"f_{line.rule}")
    parts += [
        a2ui.component("f_note", "TextField", label=translate("profile.entry_note"),
                       value=a2ui.path("/e/note")),
        a2ui.component("hint", "Text",
                       text=translate("chat.entry_note_replace" if k.replaces
                                      else "chat.entry_note"),
                       variant="caption"),
        a2ui.component("save", "Button", text=translate("chat.entry_save"),
                       variant="primary",
                       action=a2ui.event(SAVE, **{f: a2ui.path(f"/e/{f}")
                                                  for f in (*entry.RULES, "note")})),
    ]
    order += ["f_note", "hint", "save"]
    parts.insert(0, a2ui.component("root", "Column", children=order))
    data = {"e": {**{line.rule: f"{line.level:g}" for line in drawn.rules},
                  "note": drawn.note}}
    return a2ui.surface(SURFACE_ID, parts, data)


def saved(kept: entry.Checklist, translate) -> list[dict]:
    """The surface once stored: how many lines, and where they are edited.
    Every field blanked and no note is the checklist cleared, as in the form."""
    count = len(kept.rules)
    title = ("chat.entry_cleared" if kept.empty
             else "chat.entry_saved_one" if count == 1 else "chat.entry_saved")
    parts = [
        a2ui.component("root", "Column", children=["title", "done"]),
        a2ui.component("title", "Text", text=translate(title, n=count),
                       variant="h3"),
        a2ui.component("done", "Text", text=translate("chat.entry_saved_where"),
                       variant="caption"),
    ]
    return [{"version": a2ui.VERSION,
             "updateComponents": {"surfaceId": SURFACE_ID, "components": parts}}]


def prompt_line(k: Known) -> str:
    """The prompt's paragraph: the card is drawn, so the prose does not redo it."""
    drawn = draft(k)
    lines = ", ".join(f"{r.rule} {r.level:g}" for r in drawn.rules)
    basis = "; ".join(b for b in (
        f"risk {k.risk} from their investor profile" if k.risk
        else "no investor profile saved, so a balanced risk",
        "a dividend focus" if k.dividends else "",
        f"a position cap of {k.cap:g}% from their plan" if k.cap else "",
    ) if b)
    return (
        "\n\n---\nThe app drew an entry checklist under this answer: the lines "
        f"it can measure, drafted by one fixed rule from {basis} ({lines}), "
        "each an editable field (blank drops the line), the reader's own note "
        "of principles, and a Save button that stores it as their entry "
        "criteria (Profile, My plan), "
        + ("replacing the checklist they saved before. " if k.replaces else ". ")
        + "Review then warns when a buy or an add breaks a line, and the "
        "ticker page counts how many a company meets. In two or three short "
        "sentences, speaking to the reader as 'you': invite them to adjust "
        "the figures in the card below to their own standards and save, say "
        "it is a starting point drawn from their profile rather than advice, "
        "and that a principle no figure measures belongs in the note. Do not "
        "list the card's figures, do not describe how the card works, and do "
        "not propose levels or ratios of your own."
    )
