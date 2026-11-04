"""What of an answer may leave the account when its reader shares it.

An answer is written for one person and routinely quotes their book: what a
position is worth, what a sale would realise, how many shares they hold. A
shared link is read by anybody it reaches, so the snapshot (`web/shares.py`)
is cut here first, and the reader is shown the cut — the preview and the
published page run the same function, so nothing surprises them later.

Two cuts, one always and one by default:

* Always: the answer's surfaces keep what they *show* and lose what they *do*.
  A slider, a chip that refetches, a button — each sends an action back to the
  account that drew it, and a stranger's press has no account to land in.
* By default ("hide my amounts"): money figures and holdings sizes become
  `•••`, the currency kept so the sentence still reads. Tickers, percentages
  and dates stay — they are what makes an answer worth sending. Surfaces built
  from amounts (a sale's what-if, a loss harvest, a rebalance, a plan) are
  left out whole: a table with every figure masked says nothing.

Prices are money too, and are masked with the rest. A rule that told a
quoted price from a position's value would have to read the sentence, and a
miss would publish the figure the reader asked to hide.
"""

from __future__ import annotations

import re
from copy import deepcopy

from stocks.chat import a2ui

MASK = "•••"

# Surfaces that hold no figure of the reader's: a price line (the book's own
# line is an index from 100) and a ring of weights.
PUBLIC_SURFACES = frozenset({"chart", "allocation"})
# Surfaces that are tables of the reader's money: shared only unmasked.
AMOUNT_SURFACES = frozenset({"whatif", "harvest", "rebalance", "plan_builder"})

_NUM = (r"[+\-−]?(?:\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
        r"(?:\s?(?:k|K|M|mil|millones|bn|B)\b)?")
_CCY = r"(?:US\$|€|\$|£|EUR|USD|GBP|CHF|JPY|CAD|AUD|SEK|NOK|DKK)"
_UNITS = (r"(?:acci[oó]n(?:es)?|participaci[oó]n(?:es)?|t[ií]tulos?|shares?|units?|"
          r"unidades|uds?\.?|BTC|ETH|SOL|monedas|coins?)")

_MONEY_BEFORE = re.compile(rf"(?P<ccy>{_CCY})\s?(?P<num>{_NUM})")
_MONEY_AFTER = re.compile(rf"(?P<num>{_NUM})\s?(?P<ccy>{_CCY})(?![A-Za-z])")
_HOLDING = re.compile(rf"(?P<num>{_NUM})\s(?P<unit>{_UNITS})(?![A-Za-z])",
                      re.IGNORECASE)


def _masked(match: re.Match[str]) -> str:
    start, end = match.span("num")
    text = match.group(0)
    offset = match.start()
    return text[: start - offset] + MASK + text[end - offset:]


def mask_text(text: str) -> str:
    """`text` with its money figures and holding sizes as `•••`."""
    for pattern in (_MONEY_BEFORE, _MONEY_AFTER, _HOLDING):
        text = pattern.sub(_masked, text)
    return text


def surfaces(activities: list[dict], masked: bool) -> list[dict]:
    """The answer's surfaces as a stranger may see them, inert.

    A proposal's form or diff (`form_*`, `diff_*`) is never kept: it is an
    edit to the reader's ledger, not something the answer showed."""
    out = []
    for activity in activities:
        if not isinstance(activity, dict) or activity.get("type") != a2ui.ACTIVITY_TYPE:
            continue
        sid = str(activity.get("id") or "")
        if sid in PUBLIC_SURFACES or (sid in AMOUNT_SURFACES and not masked):
            out.append(inert(activity))
    return out


def inert(activity: dict) -> dict:
    """`activity` without a component that sends anything back: those, and
    their ids out of every parent's children, so the surface still checks."""
    copy = deepcopy(activity)
    messages = copy.get("content", {}).get("messages") or []
    for message in messages:
        body = message.get("updateComponents")
        if not body:
            continue
        gone = {c["id"] for c in body["components"]
                if c.get("action") is not None or c.get("component") == "Button"}
        kept = [c for c in body["components"] if c["id"] not in gone]
        for c in kept:
            if "children" in c:
                c["children"] = [k for k in c["children"] if k not in gone]
        body["components"] = kept
    return copy
