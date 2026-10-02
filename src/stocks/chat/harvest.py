"""Which losses would cut this year's bill? Tax-loss harvesting, worked out.

"¿Qué podría vender para compensar plusvalías?" has an answer only the
ledger knows: the gains already realised this tax year, the open positions
under their cost, and which lots the jurisdiction says a sale would match.
The daily card already raises one such line at a time (`chat/signals.py`'s
harvest signal); this is the whole list, on request, each candidate replayed
through the tax engine the way the what-if sale is (`chat/whatif.py`'s
`Replay`): the ledger once as it is, then once with the whole holding sold
today, and the bill's difference is the candidate's saving. Then all of them
sold together, since the savings do not add up — once the year's gains are
cancelled, a further loss only carries forward.

The repurchase rule travels with it, because it is the part that costs money
to get wrong. A loss on shares bought within the window before today is
already deferred by the replay (`blocked`); buying them back within the window
after the sale would defer it too, and only the reader can avoid that, so the
day it clears is quoted.

The prices are the Home page's (`engine.enriched_frame`, in the
jurisdiction's currency), so the losses are the ones the P/L column shows and
no candidate costs a quote of its own.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

import pandas as pd

from stocks import obs
from stocks.chat import a2ui
from stocks.chat.signals import HARVEST_MIN, _window_end
from stocks.chat.whatif import Replay, _money

SURFACE_ID = "harvest"
# Candidates replayed, largest loss first: each is a replay of the ledger.
MAX_CANDIDATES = 6

# Matched with the accents folded away: gains to offset, losses to realise,
# or a tax bill to cut by selling.
_HARVEST_RE = re.compile(
    r"\bcompens(?:ar|o|e|ando|acion|arlas?|arlos?)\b|"
    r"\bminusvalias?\b|\bperdidas? (?:fiscal(?:es)?|patrimonial(?:es)?)\b|"
    r"\btax[- ]loss|\bharvest|\bwash[- ]sale|\bregla de los dos meses\b|"
    r"\b(?:ahorrar|ahorro|pagar menos|reducir|bajar|rebajar|optimizar)\b.{0,25}"
    r"\b(?:impuestos?|irpf|hacienda)\b|"
    r"\b(?:save|saving|cut|reduce|lower|pay less|minimi[sz]e)\b.{0,25}"
    r"\b(?:tax|taxes|tax bill|capital gains tax|cgt)\b|"
    r"\boffset\b.{0,30}\bgains?\b",
    re.IGNORECASE,
)
# How the prompt names a repurchase window (`Jurisdiction.repurchase_window`).
_WINDOW_EN = {"2m": "two months", "30d": "30 days", "28d": "28 days"}


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(ch))


def wants(message: str) -> bool:
    """Whether the message asks which losses would offset this year's gains."""
    return bool(_HARVEST_RE.search(_fold(message)))


@dataclass(frozen=True)
class Candidate:
    """One open loss, and what selling the whole holding today would do."""

    ticker: str
    shares: float
    loss: float  # realised by the sale, negative, in the jurisdiction's currency
    saving: float  # this year's bill without the sale minus with it
    blocked: float  # of the loss, deferred by a purchase inside the window


@dataclass(frozen=True)
class Harvest:
    """The year so far, the candidates, and all of them sold together."""

    candidates: tuple[Candidate, ...]
    gains: float  # realised this tax year, before any sale
    losses: float  # deductible losses realised this tax year
    tax: float  # this year's estimate as it stands
    tax_all: float  # with every candidate sold today
    carry: float  # net loss left over for later years, all of them sold
    carry_years: int | None
    currency: str
    jurisdiction: str
    year: str
    window: str  # "2m", "30d", "28d" or ""
    clear: str  # ISO day a repurchase stops touching a sale made today

    @property
    def saving(self) -> float:
        return self.tax - self.tax_all

    def line(self) -> str:
        """The prompt's paragraph: figures only, and where they came from."""
        c = self.currency
        rows = [
            f"- realised so far this tax year: gains {self.gains:,.2f} {c}, "
            f"deductible losses {self.losses:,.2f} {c}; estimated tax "
            f"{self.tax:,.2f} {c}",
        ]
        if not self.candidates:
            rows.append(f"- no open position is more than {HARVEST_MIN:,.0f} {c} "
                        "under its cost: there is no loss worth realising")
        else:
            rows.append("- open losses selling the whole holding today would "
                        "realise, each on its own:")
            for x in self.candidates:
                row = (f"  - {x.ticker}: loss {x.loss:,.2f} {c}, this year's tax "
                       f"{-x.saving:+,.2f} {c}")
                if x.blocked > 0:
                    row += (f" ({x.blocked:,.2f} {c} of the loss is deferred: "
                            "shares of it were bought inside the repurchase window)")
                rows.append(row)
            years = ("indefinitely" if self.carry_years is None
                     else f"for {self.carry_years} years")
            rows.append(
                f"- all of them sold together: tax {self.tax:,.2f} -> "
                f"{self.tax_all:,.2f} {c} (saving {self.saving:,.2f} {c}); "
                + (f"{self.carry:,.2f} {c} of net loss left to carry forward {years}"
                   if self.carry > 0 and self.carry_years != 0
                   else "no net loss left over")
            )
            if self.gains <= 0:
                rows.append("- nothing is realised to offset yet this year, so a "
                            "loss now saves nothing this year; it only carries "
                            "forward")
        if self.window in _WINDOW_EN and self.clear:
            rows.append(
                f"- repurchase rule: buying the same security within "
                f"{_WINDOW_EN[self.window]} of the sale, before or after, defers "
                f"the loss; sold today, a repurchase is clear from {self.clear}"
            )
        return (
            "\n\n---\nTax-loss harvesting worked out by the app's own tax engine "
            f"for this message ({self.jurisdiction.upper()} rules, tax year "
            f"{self.year}, today's prices). Quote these figures rather than "
            "estimating your own and call them an estimate. Say what the "
            "arithmetic is, not that the reader should sell: a loss is worth "
            "realising for the position's own sake first.\n" + "\n".join(rows)
        )


def build(book: Replay | None, tbl: pd.DataFrame | None) -> Harvest | None:
    """The candidates in `tbl` (`engine.enriched_frame` in the book's
    currency), replayed on `book`; None without a ledger or open positions."""
    if book is None or tbl is None or tbl.empty or "pnl" not in tbl:
        return None
    losers = tbl[pd.to_numeric(tbl["pnl"], errors="coerce") < -HARVEST_MIN]
    losers = losers.sort_values("pnl").head(MAX_CANDIDATES)
    sales, out = [], []
    for ticker, row in losers.iterrows():
        shares, value = float(row.get("shares") or 0), float(row.get("value") or 0)
        held = book.held(str(ticker))
        if held is None or shares <= 0 or value <= 0:
            continue
        price = value / shares
        sale = book.scenario(held.ticker, held.quantity, price, book.currency)
        # The Home P/L is against average cost; the replay matches lots, and
        # on the lots this sale would match it may not be a loss at all.
        if sale is None or sale.gain >= 0:
            continue
        sales.append((held.ticker, held.quantity, price, book.currency))
        out.append(Candidate(held.ticker, held.quantity, sale.gain,
                             -sale.extra_tax, sale.blocked))
    before = book.before
    after = book.after(sales)[1] if sales else before
    window = book.jurisdiction.repurchase_window or ""
    clear = _window_end(date.fromisoformat(book.day), window) if window else None
    obs.event("chat.harvest", jurisdiction=book.code, candidates=len(out))
    return Harvest(
        candidates=tuple(out), gains=before.realized_gain,
        losses=before.deductible_loss, tax=before.estimated_tax,
        tax_all=after.estimated_tax, carry=after.carryforward_loss,
        carry_years=book.jurisdiction.carryforward_years,
        currency=book.currency, jurisdiction=book.code, year=book.year_label,
        window=window, clear=clear.isoformat() if clear else "",
    )


# -------------------------------------------------------------------- surface


def surface(h: Harvest, translate) -> list[dict]:
    """The year so far, one row per candidate, and the repurchase rule."""
    c = h.currency
    rows = [f"c{n}" for n in range(len(h.candidates))]
    parts = [
        a2ui.component("root", "Column",
                       children=["title", "figures", *rows, "note"]),
        a2ui.component("title", "Text", text=translate("chat.harvest_title"),
                       variant="h3"),
        a2ui.component("figures", "Row", children=["gains", "saving"]),
        a2ui.component("gains", "Metric", label=translate("chat.harvest_gains"),
                       value=_money(h.gains - h.losses, c, signed=True),
                       hint=translate("chat.harvest_tax_hint", year=h.year,
                                      tax=_money(h.tax, c))),
        a2ui.component("saving", "Metric", label=translate("chat.harvest_saving"),
                       value=_money(h.saving, c),
                       tone="up" if h.saving > 0 else "flat",
                       hint=translate("chat.harvest_saving_hint",
                                      count=len(h.candidates))),
    ]
    for cid, x in zip(rows, h.candidates, strict=True):
        hint = (translate("chat.harvest_blocked", amount=_money(x.blocked, c))
                if x.blocked > 0 else None)
        parts += [
            a2ui.component(cid, "Row", children=[f"{cid}_t", f"{cid}_l", f"{cid}_s"],
                           align="center"),
            a2ui.component(f"{cid}_t", "Ticker", symbol=x.ticker),
            a2ui.component(f"{cid}_l", "Metric", label=translate("chat.harvest_loss"),
                           value=_money(x.loss, c, signed=True), tone="down"),
            a2ui.component(f"{cid}_s", "Metric", label=translate("chat.harvest_save"),
                           value=_money(x.saving, c),
                           tone="up" if x.saving > 0 else "flat", hint=hint),
        ]
    note = translate("chat.harvest_note")
    if h.window in _WINDOW_EN and h.clear:
        note = translate(f"chat.harvest_window_{h.window}", day=h.clear) + " " + note
    parts.append(a2ui.component("note", "Text", text=note, variant="caption"))
    return a2ui.surface(SURFACE_ID, parts, {})
