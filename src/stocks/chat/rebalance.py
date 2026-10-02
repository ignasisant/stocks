"""What would it take for this position to weigh N%? A trade sized, then taxed.

"Quiero que NVDA pese un 10%" is two sums a model gets wrong in prose: how
many shares move the weight there, and what the sale of them costs in tax.
The first is arithmetic on the Home page's frame (`engine.enriched_frame`):
with the rest of the book left as it is — what is sold leaves for cash, what
is bought comes in with new money, the way the app's weights never count
cash — the trade `d` that takes value `v` of a book worth `T` to weight `w`
solves (v + d) / (T + d) = w, so d = (wT - v) / (1 - w). The second is the
what-if sale (`chat/whatif.py`): the shares to sell replayed through the tax
engine at the same price. A purchase has no tax to show.

Drawn with a slider over the target weight, whose every release asks the
server for that weight again (`POST /chat/actions`), as the what-if slider
asks for a number of shares.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from stocks import obs
from stocks.chat import a2ui
from stocks.chat.whatif import Replay, _money

SURFACE_ID = "rebalance"
ACTION = "reweigh"
# The slider's step and its ceiling: a single position at 95% of a book is
# as far as "weigh N%" means anything, and the sum breaks down at 100%.
STEP = 0.5
CEILING = 95.0

# Matched with the accents folded away. A rebalance named as such...
_REBALANCE_RE = re.compile(
    r"\breequilibr|\brebalanc|\breajust(?:ar|e) (?:el |los )?pesos?\b",
    re.IGNORECASE,
)
# ... or a weight the reader wants one position at.
_WEIGHT_RE = re.compile(
    r"\bpes(?:e|en|ar|ara|ase|a|o)\b|\bweigh(?:s|t|ted|ting)?\b|"
    r"\b(?:reduc\w*|baj(?:ar|arla|arlo|o|e)|sub(?:ir|irla|irlo|o|a)|aument\w*|"
    r"recort\w*|llev(?:ar|arla|arlo|o|e)|dej(?:ar|arla|arlo|o|e)|trim|cut|bring|"
    r"raise|increase|lift|top up)\b.{0,40}"
    r"\b(?:al|a un|a|hasta(?: el| un)?|to|down to|up to)\s*"
    r"\d+(?:[.,]\d+)?\s*(?:%|por ?ciento|percent)",
    re.IGNORECASE,
)
_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|por ?ciento|percent)", re.IGNORECASE)


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(ch))


def wants(message: str) -> bool:
    """Whether the message asks to take a position to a weight."""
    text = _fold(message)
    if _REBALANCE_RE.search(text):
        return True
    return bool(_PCT_RE.search(text) and _WEIGHT_RE.search(text))


def target_asked(message: str) -> float | None:
    """The weight the message names, in percent, or None."""
    hit = _PCT_RE.search(_fold(message))
    if not hit:
        return None
    value = float(hit.group(1).replace(",", "."))
    return value if 0 <= value <= CEILING else None


@dataclass(frozen=True)
class Reweigh:
    """One position taken from its weight to a target, and the trade's cost."""

    ticker: str
    held: float  # shares
    value: float  # in `currency`, today
    total: float  # the whole book's value, in `currency`
    target: float  # percent
    shares: float  # to trade: negative sells, positive buys
    amount: float  # the trade's value, signed the same way
    gain: float  # realised by a sale, in `currency`; 0 for a purchase
    tax_before: float
    tax_after: float
    currency: str
    jurisdiction: str
    year: str

    @property
    def weight(self) -> float:
        """Today's weight, in percent."""
        return 100 * self.value / self.total if self.total else 0.0

    @property
    def extra_tax(self) -> float:
        return self.tax_after - self.tax_before

    @property
    def ceiling(self) -> float:
        """The slider's top: room above today's weight, within `CEILING`."""
        return min(CEILING, max(50.0, math.ceil(self.weight / 10) * 10 + 20))

    def line(self) -> str:
        """The prompt's paragraph: figures only, and where they came from."""
        c = self.currency
        verb = "sell" if self.shares < 0 else "buy"
        trade = (f"{verb} {_count(self.shares)} shares, {abs(self.amount):,.2f} {c}"
                 if self.shares else "no trade: it is already there")
        rows = [
            f"- {self.ticker} today: {self.held:g} shares, {self.value:,.2f} {c}, "
            f"{self.weight:.1f}% of a book of {self.total:,.2f} {c}",
            f"- to weigh {self.target:g}%: {trade}",
        ]
        if self.shares < 0:
            rows.append(
                f"- that sale realises {self.gain:+,.2f} {c}; estimated tax "
                f"{self.year} {self.tax_before:,.2f} -> {self.tax_after:,.2f} {c} "
                f"(change {self.extra_tax:+,.2f} {c}, "
                f"{self.jurisdiction.upper()} rules)"
            )
        return (
            "\n\n---\nRebalance worked out by the app for this message, at "
            "today's prices, with the rest of the book left as it is (a sale "
            "leaves for cash, a purchase comes in as new money; the app's "
            "weights do not count cash). Quote these figures rather than "
            "working out your own, and call the tax an estimate:\n"
            + "\n".join(rows)
        )


def build(book: Replay | None, tbl: pd.DataFrame | None, ticker: str,
          target: float | None) -> Reweigh | None:
    """`ticker` taken to `target` percent (today's weight when None), from
    `tbl` (`engine.enriched_frame` in the book's currency) and replayed on
    `book`; None when it is not held or not priced."""
    if book is None or tbl is None or tbl.empty or "value" not in tbl:
        return None
    symbol = ticker.strip().upper()
    held = book.held(symbol)
    if held is None or symbol not in tbl.index:
        return None
    row = tbl.loc[symbol]
    shares, value = float(row.get("shares") or 0), float(row.get("value") or 0)
    total = float(pd.to_numeric(tbl["value"], errors="coerce").clip(lower=0).sum())
    if shares <= 0 or value <= 0 or total <= 0:
        return None
    price = value / shares
    weight = 100 * value / total
    if target is None:
        # No weight named: the slider opens where the position stands, and
        # nothing trades until it moves.
        goal, count = round(weight, 1), 0.0
    else:
        goal = round(max(0.0, min(CEILING, float(target))) / STEP) * STEP
        w = goal / 100
        count = max(-held.quantity, (w * total - value) / (1 - w) / price)
        if abs(count) < 1e-9:
            count = 0.0
    tax_before = tax_after = book.before.estimated_tax
    gain = 0.0
    if count < 0:
        sale = book.scenario(held.ticker, -count, price, book.currency)
        if sale is not None:
            gain, tax_after = sale.gain, sale.tax_after
    obs.event("chat.rebalance", jurisdiction=book.code,
              direction="sell" if count < 0 else "buy" if count > 0 else "none")
    return Reweigh(
        ticker=held.ticker, held=held.quantity, value=value, total=total,
        target=goal, shares=count, amount=count * price, gain=gain,
        tax_before=tax_before, tax_after=tax_after, currency=book.currency,
        jurisdiction=book.code, year=book.year_label,
    )


# -------------------------------------------------------------------- surface


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _count(shares: float) -> str:
    """Shares to two decimals, or six for a fraction of one (crypto, a fund)."""
    text = f"{abs(shares):,.{2 if abs(shares) >= 1 else 6}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def view(r: Reweigh, translate) -> dict:
    """The figures the surface shows, formatted: its `/view` data."""
    c = r.currency
    if r.shares < 0:
        trade = translate("chat.rebalance_sell", shares=_count(r.shares))
    elif r.shares > 0:
        trade = translate("chat.rebalance_buy", shares=_count(r.shares))
    else:
        trade = translate("chat.rebalance_none")
    return {
        "weight": f"{_pct(r.weight)} → {_pct(r.target)}",
        "trade": trade,
        "amount": _money(abs(r.amount), c),
        "tax": _money(r.extra_tax, c, signed=True),
        "tax_tone": "down" if r.extra_tax > 0 else "up" if r.extra_tax < 0 else "flat",
        "tax_hint": (translate("chat.whatif_tax_hint", year=r.year,
                               before=_money(r.tax_before, c),
                               after=_money(r.tax_after, c))
                     if r.shares < 0 else translate("chat.rebalance_tax_buy")),
    }


def surface(r: Reweigh, translate) -> list[dict]:
    """A slider over the target weight and the three figures that move with it."""
    parts = [
        a2ui.component("root", "Column",
                       children=["head", "target", "figures", "note"]),
        a2ui.component("head", "Row", children=["ticker", "title"], align="center"),
        a2ui.component("ticker", "Ticker", symbol=r.ticker),
        a2ui.component("title", "Text", text=translate("chat.rebalance_title"),
                       variant="h3"),
        a2ui.component(
            "target", "Slider", label=translate("chat.rebalance_target"),
            value=a2ui.path("/target"), min=0, max=r.ceiling, step=STEP,
            action=a2ui.event(ACTION, ticker=r.ticker, target=a2ui.path("/target")),
        ),
        a2ui.component("figures", "Row", children=["weight", "trade", "tax"]),
        a2ui.component("weight", "Metric", label=translate("chat.rebalance_weight"),
                       value=a2ui.path("/view/weight")),
        a2ui.component("trade", "Metric", label=translate("chat.rebalance_trade"),
                       value=a2ui.path("/view/trade"), hint=a2ui.path("/view/amount")),
        a2ui.component("tax", "Metric", label=translate("chat.whatif_tax"),
                       value=a2ui.path("/view/tax"), tone=a2ui.path("/view/tax_tone"),
                       hint=a2ui.path("/view/tax_hint")),
        a2ui.component("note", "Text", text=translate("chat.rebalance_note"),
                       variant="caption"),
    ]
    data = {"target": r.target, "view": view(r, translate)}
    return a2ui.surface(SURFACE_ID, parts, data)


def moved(r: Reweigh, translate) -> list[dict]:
    """The same surface after the slider moved: its data, nothing else."""
    return [a2ui.data_update(SURFACE_ID, "/view", view(r, translate)),
            a2ui.data_update(SURFACE_ID, "/target", r.target)]
