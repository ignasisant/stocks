"""Build me a plan: a short interview in the drawer, a draft, and a Save.

"Móntame un plan de inversión" is a form the reader has not found yet
(Profile, My plan), and a model asked it in prose either lectures for a page
or invents an allocation. Neither is the app's to say. What the app can do is
ask the few questions a plan turns on, turn the answers into numbers by one
fixed rule (`portfolio.plan.suggest`), and let the reader save the result
where the form would have.

What it already knows it does not ask: risk and horizon when the investor
profile is set, the contribution when a plan has one, the style (funds or
single companies) when the book already leans one way, crypto when the book
holds some or the profile follows it. At most `MOST` questions are left,
drawn as chips, and under them one optional field for the cash the reader
holds uninvested, the one figure the app can never read off the ledger
(asked until the plan states it). Every press redrafts the plan below them
(`POST /chat/actions`, `DRAFT`), and the Save button stores it (`SAVE`)
through the same merge the form uses. The draft is recomputed on the server
from the answers alone: the surface cannot hand back a plan of its own.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field

from stocks.chat import a2ui
from stocks.portfolio import plan as plans
from stocks.web.auth import PROFILE_HORIZON, PROFILE_RISK

SURFACE_ID = "plan_builder"
DRAFT = "draft"
SAVE = "save"
# More than this and it is the form again, in a smaller box.
MOST = 4

# Matched with the accents folded away. A verb that makes something, near a
# plan ...
_BUILD_RE = re.compile(
    r"\b(?:monta\w*|mont(?:ar|ame|arme)|haz(?:me)?|hacer(?:me)?|crea\w*|arm(?:a|ame|ar)|"
    r"disen\w*|prepar\w*|ayuda\w* a (?:montar|hacer|crear|definir|fijar)|defin\w*|"
    r"fij(?:a|ar|ame)|build|make|create|set up|draw up|design|help me (?:build|make|set)|"
    r"fes(?:-me)?|munta\w*)\b"
    r".{0,40}\bpla(?:n|nes|ns)?\b",
    re.IGNORECASE,
)
# ... or the thing named outright.
_NAMED_RE = re.compile(
    r"\bplan (?:de inversion|d'inversio|inversor|financiero)\b|"
    r"\b(?:investment|investing|financial) plan\b|"
    r"\bmi plan\b.{0,30}\b(?:cartera|inversion)",
    re.IGNORECASE,
)
# Plans that are not this one: a pension, a phone, a company's or a trip's.
_OTHER_RE = re.compile(
    r"\bplan(?:es)? de (?:pensiones|empleo|ahorro sistematico|negocio|viaje|datos)\b|"
    r"\bpension plan\b|\bbusiness plan\b|\b401k\b|"
    r"\bplan (?:de|of) (?:\w+ )?(?:accion|stock)",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(ch))


def wants(message: str) -> bool:
    """Whether the message asks the assistant to put a plan together."""
    text = _fold(message)
    if _OTHER_RE.search(text):
        return False
    return bool(_BUILD_RE.search(text) or _NAMED_RE.search(text))


# ------------------------------------------------------------------ the interview

RISK, HORIZON, CUSHION, AMOUNT, STYLE, CRYPTO = (
    "risk", "horizon", "cushion", "amount", "style", "crypto")
# The cash field: optional, outside `MOST`, since it moves no target — it is
# stored with the plan (`plan.Cash`) and read as money the book can spend.
INVESTABLE = "investable"
# The order questions are asked in when more are missing than fit: what sets
# the size of everything else first.
ORDER = (RISK, HORIZON, CUSHION, AMOUNT, STYLE, CRYPTO)
CHOICES = {
    RISK: PROFILE_RISK,
    HORIZON: PROFILE_HORIZON,
    CUSHION: plans.CUSHIONS,
    STYLE: plans.STYLES,
    CRYPTO: plans.CRYPTO_WISH,
}
# What a question not asked, and not known, reads as: the profile's own
# defaults for risk and horizon, the cautious end for the rest.
_DEFAULT = {RISK: "balanced", HORIZON: "5y_plus", CUSHION: "none",
            STYLE: "funds", CRYPTO: "none"}
# Single companies' share of the equity in the book, past which it leans.
_FUNDS_UNDER, _STOCKS_OVER = 0.35, 0.65
# A crypto share past which the reader already holds "more" than a pinch.
_CRYPTO_MORE = 5.0


@dataclass(frozen=True)
class Known:
    """What the app has on the reader before asking anything."""

    risk: str | None = None
    horizon: str | None = None
    style: str | None = None
    crypto: str | None = None
    amount: float | None = None
    every: str = "monthly"
    cushion: str | None = None  # "none" once the plan states an emergency fund of 0
    investable: float | None = None  # the plan's stated uninvested cash
    shares: dict[str, float] = field(default_factory=dict)  # bucket -> percent today
    currency: str = "EUR"
    replaces: bool = False  # a plan is saved already

    def line(self, lang: str = "en") -> str:
        """The prompt's paragraph (`prompt_line`), as the other cards give it."""
        return prompt_line(self)


def known(prefs: Mapping, shares: Mapping[str, float], currency: str = "EUR") -> Known:
    """Read `Known` off prefs and today's mix by bucket (`plan.buckets`)."""
    profile = prefs.get("investor_profile") or {}
    told = bool(profile.get("set"))
    stored = plans.load(prefs)
    stocks = shares.get(plans.STOCKS, 0.0)
    equity = stocks + shares.get(plans.EQUITY_FUNDS, 0.0)
    style = None
    if equity > 0:
        lean = stocks / equity
        style = ("funds" if lean < _FUNDS_UNDER
                 else "stocks" if lean > _STOCKS_OVER else None)
    coins = shares.get(plans.CRYPTO, 0.0)
    crypto = ("more" if coins >= _CRYPTO_MORE else "some" if coins > 0
              else "some" if "crypto" in (profile.get("focus") or []) else None)
    c = stored.contribution
    cash = stored.cash
    return Known(
        risk=(profile.get("risk")
              if told and profile.get("risk") in PROFILE_RISK else None),
        horizon=(profile.get("horizon")
                 if told and profile.get("horizon") in PROFILE_HORIZON else None),
        style=style,
        crypto=crypto,
        amount=c.amount if c else None,
        every=c.every if c else "monthly",
        cushion="none" if cash and cash.cushion == 0 else None,
        investable=cash.investable if cash else None,
        shares={k: round(v, 1) for k, v in shares.items() if v > 0},
        currency=currency,
        replaces=bool(stored.set and not stored.empty),
    )


def questions(k: Known) -> tuple[str, ...]:
    """The questions left to ask, most decisive first, at most `MOST`. The
    cushion outside the broker is the one thing the app can never know,
    unless the plan already states there is none."""
    have = {RISK: k.risk, HORIZON: k.horizon, CUSHION: k.cushion, AMOUNT: k.amount,
            STYLE: k.style, CRYPTO: k.crypto}
    return tuple(q for q in ORDER if have[q] is None)[:MOST]


def answers(k: Known, picked: Mapping[str, object] | None = None) -> plans.Answers:
    """The answers a draft is computed from: what was picked, else what is
    known, else the default. A pick outside its choices is not one."""
    picked = picked or {}

    def one(q: str) -> str:
        value = picked.get(q)
        if value in CHOICES[q]:
            return str(value)
        return getattr(k, q, None) or _DEFAULT[q]

    return plans.Answers(
        risk=one(RISK), horizon=one(HORIZON), cushion=one(CUSHION),
        style=one(STYLE), crypto=one(CRYPTO),
        amount=_typed(picked[AMOUNT]) if AMOUNT in picked else k.amount,
        every=str(picked.get("every") or k.every),
        investable=(_typed_cash(picked[INVESTABLE]) if INVESTABLE in picked
                    else k.investable),
    )


def _typed(value: object) -> float | None:
    """`amount_of`, with text that is not an amount read as blank: a draft
    redrawn while the reader is still typing. Save checks it strictly."""
    try:
        return amount_of(value)
    except ValueError:
        return None


def _typed_cash(value: object) -> float | None:
    try:
        return cash_amount(value)
    except ValueError:
        return None


def amount_of(value: object) -> float | None:
    """A typed contribution ("300", "1.500,50") as a number; None when blank.
    Raises ValueError for text that is not one."""
    text = str(value if value is not None else "").strip().replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    number = float(text)
    if not math.isfinite(number) or number < 0:
        raise ValueError("not an amount")
    return number or None


def cash_amount(value: object) -> float | None:
    """`amount_of` for the cash field, where 0 is an answer ("none"), not a
    blank. Raises ValueError for text that is not an amount."""
    text = str(value if value is not None else "").strip()
    if text and amount_of(text) is None:
        return 0.0
    return amount_of(text)


# ------------------------------------------------------------------ the draft


def draft(k: Known, picked: Mapping[str, object] | None = None) -> dict:
    """The plan the answers make, shaped for `PUT /prefs/plan`."""
    return plans.suggest(answers(k, picked))


def _bucket_line(targets: Mapping[str, float], translate) -> str:
    # Whole points: a target is one already, and today's share to a decimal
    # would print with the server's point where a Spanish reader expects a comma.
    return " · ".join(
        f"{translate(f'profile.plan_bucket_{b}')} {round(targets[b])} %"
        for b in plans.BUCKETS if round(targets.get(b) or 0))


def view(k: Known, picked: Mapping[str, object] | None, translate) -> dict:
    """The draft as the surface shows it: its `/view` data."""
    plan = draft(k, picked)
    targets = plan["mix"]["targets"]
    lim = plan["limits"]
    res = plan["reserve"]
    return {
        "slices": [{"label": translate(f"profile.plan_bucket_{b}"),
                    "weight": targets[b] / 100}
                   for b in plans.BUCKETS if targets.get(b)],
        "mix": _bucket_line(targets, translate),
        "limits": translate("chat.plan_limits", position=f"{lim['max_position_pct']:g}",
                            sector=f"{lim['max_sector_pct']:g}",
                            spec=f"{lim['max_speculative_pct']:g}"),
        "reserve": (translate("chat.plan_reserve", low=f"{res['min_pct']:g}",
                              high=f"{res['max_pct']:g}")
                    if res else translate("chat.plan_reserve_none")),
    }


def _told(k: Known, translate) -> str:
    """The caption of what was not asked because the app knew it."""
    bits = []
    if k.risk:
        bits.append(translate(f"profile.iv_risk_{k.risk}"))
    if k.horizon:
        bits.append(translate(f"profile.iv_horizon_{k.horizon}"))
    if k.amount:
        bits.append(translate(f"chat.plan_known_amount_{k.every}",
                              amount=f"{round(k.amount)} {k.currency}"))
    if k.shares:
        bits.append(translate("chat.plan_known_today",
                              mix=_bucket_line(k.shares, translate)))
    return translate("chat.plan_known", what=" · ".join(bits)) if bits else ""


def _picker(q: str, translate) -> dict:
    labels = {RISK: "profile.iv_risk_", HORIZON: "profile.iv_horizon_"}
    prefix = labels.get(q, f"chat.plan_{q}_")
    return a2ui.component(
        f"q_{q}", "ChoicePicker",
        label=translate("profile.iv_risk" if q == RISK
                        else "profile.iv_horizon" if q == HORIZON
                        else f"chat.plan_q_{q}"),
        options=[{"label": translate(f"{prefix}{c}"), "value": c} for c in CHOICES[q]],
        value=a2ui.path(f"/a/{q}"), variant="chips",
        action=_event(DRAFT),
    )


def _event(name: str) -> dict:
    return a2ui.event(name, **{q: a2ui.path(f"/a/{q}")
                               for q in (*CHOICES, AMOUNT, INVESTABLE)},
                      every=a2ui.path("/a/every"))


def surface(k: Known, translate) -> list[dict]:
    """The questions, the draft under them, and Save."""
    asked = questions(k)
    first = answers(k)
    told = _told(k, translate)
    parts = [a2ui.component("title", "Text", text=translate("chat.plan_title"),
                            variant="h3")]
    order = ["title"]
    if told:
        parts.append(a2ui.component("known", "Text", text=told, variant="caption"))
        order.append("known")
    for q in asked:
        if q == AMOUNT:
            parts += [
                a2ui.component("q_amount", "TextField",
                               label=translate("chat.plan_q_amount", currency=k.currency),
                               value=a2ui.path("/a/amount"), variant="number"),
                a2ui.component(
                    "q_every", "ChoicePicker",
                    options=[{"label": translate(f"profile.plan_every_{e}"), "value": e}
                             for e in plans.EVERY],
                    value=a2ui.path("/a/every"), variant="chips",
                    action=_event(DRAFT)),
            ]
            order += ["q_amount", "q_every"]
        else:
            parts.append(_picker(q, translate))
            order.append(f"q_{q}")
    if k.investable is None:
        parts.append(a2ui.component(
            "q_investable", "TextField",
            label=translate("chat.plan_q_investable", currency=k.currency),
            value=a2ui.path("/a/investable"), variant="number"))
        order.append("q_investable")
    parts += [
        a2ui.component("rule", "Divider"),
        a2ui.component("ring", "Donut", slices=a2ui.path("/view/slices"),
                       label=translate("chat.plan_draft"),
                       other=translate("chat.mix_other")),
        a2ui.component("mix", "Text", text=a2ui.path("/view/mix")),
        a2ui.component("limits", "Text", text=a2ui.path("/view/limits")),
        a2ui.component("reserve", "Text", text=a2ui.path("/view/reserve")),
        a2ui.component("note", "Text",
                       text=translate("chat.plan_note_replace" if k.replaces
                                      else "chat.plan_note"),
                       variant="caption"),
        a2ui.component("save", "Button", text=translate("chat.plan_save"),
                       variant="primary", action=_event(SAVE)),
    ]
    order += ["rule", "ring", "mix", "limits", "reserve", "note", "save"]
    parts.insert(0, a2ui.component("root", "Column", children=order))
    data = {
        "a": {RISK: first.risk, HORIZON: first.horizon, CUSHION: first.cushion,
              STYLE: first.style, CRYPTO: first.crypto,
              AMOUNT: f"{k.amount:g}" if k.amount else "", "every": k.every,
              INVESTABLE: f"{k.investable:g}" if k.investable is not None else ""},
        "view": view(k, None, translate),
    }
    return a2ui.surface(SURFACE_ID, parts, data)


def moved(k: Known, picked: Mapping[str, object], translate) -> list[dict]:
    """The draft again, for the answers the chips now hold."""
    return [a2ui.data_update(SURFACE_ID, "/view", view(k, picked, translate))]


def saved(plan: Mapping, translate) -> list[dict]:
    """The surface once stored: what was saved, and where it is edited."""
    targets = (plan.get("mix") or {}).get("targets") or {}
    parts = [
        a2ui.component("root", "Column", children=["title", "mix", "done"]),
        a2ui.component("title", "Text", text=translate("chat.plan_saved"),
                       variant="h3"),
        a2ui.component("mix", "Text", text=_bucket_line(targets, translate)),
        a2ui.component("done", "Text", text=translate("chat.plan_saved_where"),
                       variant="caption"),
    ]
    return [{"version": a2ui.VERSION,
             "updateComponents": {"surfaceId": SURFACE_ID, "components": parts}}]


def prompt_line(k: Known) -> str:
    """The prompt's paragraph: the card is drawn, so the prose does not redo it."""
    asked = questions(k)
    plan = draft(k)
    t = plan["mix"]["targets"]
    known_bits = [f"risk {k.risk} and horizon {k.horizon} from their profile"
                  if k.risk and k.horizon else "",
                  f"a contribution of {k.amount:g} {k.currency} {k.every}" if k.amount
                  else "",
                  "today's mix by asset type " + ", ".join(
                      f"{b} {v:g}%" for b, v in k.shares.items()) if k.shares else ""]
    known_text = "; ".join(b for b in known_bits if b) or "nothing beyond the defaults"
    return (
        "\n\n---\nThe app drew a plan builder under this answer: "
        f"{len(asked)} question(s) as chips ({', '.join(asked) or 'none'}), "
        + ("an optional field for the cash they hold uninvested, "
           if k.investable is None else "")
        + "a draft "
        "plan the app computes from the answers by one fixed rule, redrawn on "
        "every press, and a Save button that stores it as their plan (Profile, "
        f"My plan). Already known, so not asked: {known_text}. With the picks "
        f"shown first the draft reads: stocks {t['stocks']:g}%, equity funds "
        f"{t['equity_funds']:g}%, bonds {t['bonds']:g}%, cash {t['cash']:g}%, "
        f"crypto {t['crypto']:g}%. In two or three short sentences, speaking "
        "to the reader as 'you': invite them to answer the questions in the "
        "card below and watch the draft change, "
        "say it is a starting point worked out from their own answers rather than "
        "advice, and that they can save it and change any figure later in My plan. "
        "Do not describe how the card works (no 'the card only asks…', no talk "
        "of the app's data), do not list the draft's figures, do not ask the "
        "card's questions again in prose, and do not propose an allocation or "
        "figures of your own."
    )

