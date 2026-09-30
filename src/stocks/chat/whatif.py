"""What if I sold? A sale that has not happened, run through the tax engine.

"How much tax would I pay if I sold my NVDA?" is not a question a model can
answer from memory, and it is not one a model should answer at all: the
figure depends on which lots the jurisdiction says go first, what else was
realised this year, and the brackets. The app already knows all three — it is
exactly what the Tax tab reports. So the answer is computed here, the same
way: the ledger replayed under the jurisdiction's own matching rule and
currency, once as it is and once with one more sale today, and the difference
is the scenario.

The scenario reaches the reader twice. Its figures ride on the question to
the model, so the prose quotes numbers that came from the engine rather than
inventing them; and it is drawn under the answer as an A2UI surface with a
slider, whose every release asks the engine again for that many shares
(`POST /chat/actions`). No model sees a slider move.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from stocks import obs
from stocks.chat import a2ui, market
from stocks.config import currency_symbol

# A sale being contemplated, in the two languages the app speaks. The gate is
# cheap and loose on purpose: a false hit costs one replay and no model call,
# and a message that is not about a holding never gets a surface anyway.
_SELL_RE = re.compile(
    r"\bvend(?:o|er|erlas?|erlos?|iera|iese|er[ií]a|emos|es|a)\b|\bsell(?:ing)?\b|"
    r"\bsold\b|\btrim(?:ming)?\b|\bliquid(?:ar|o|ate)\b|\bdeshacerme\b|\bcash out\b",
    re.IGNORECASE,
)
_HALF_RE = re.compile(r"\b(?:la mitad|half)\b", re.IGNORECASE)
_COUNT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:acciones|títulos|titulos|participaciones|shares|"
    r"units|unidades)\b",
    re.IGNORECASE,
)

SURFACE_ID = "whatif"
ACTION = "simulate"


@dataclass(frozen=True)
class Scenario:
    """One simulated sale and what it does to this tax year."""

    ticker: str
    held: float
    shares: float
    price: float  # per share, in `price_currency`
    price_currency: str
    proceeds: float  # in `currency`, the jurisdiction's
    gain: float  # realised by this sale alone, in `currency`
    tax_before: float  # this tax year's estimate without the sale
    tax_after: float  # and with it
    currency: str
    jurisdiction: str
    year: str  # as the jurisdiction writes it: "2026", "2026/27"

    @property
    def extra_tax(self) -> float:
        return self.tax_after - self.tax_before

    def line(self) -> str:
        """The prompt's paragraph: figures only, and where they came from."""
        c = self.currency
        return (
            "\n\n---\nSale simulated by the app's own tax engine for this "
            f"message ({self.jurisdiction.upper()} rules, tax year {self.year}, "
            f"today's price {self.price:,.2f} {self.price_currency}). Quote these "
            "figures rather than estimating your own, and say they are an "
            "estimate:\n"
            f"- selling {self.shares:g} of {self.held:g} {self.ticker} shares\n"
            f"- proceeds {self.proceeds:,.2f} {c}\n"
            f"- realised gain on this sale {self.gain:+,.2f} {c}\n"
            f"- estimated tax this year {self.tax_before:,.2f} -> "
            f"{self.tax_after:,.2f} {c} (change {self.extra_tax:+,.2f} {c})"
        )


def wants(message: str) -> bool:
    """Whether the message is contemplating a sale."""
    return bool(_SELL_RE.search(message or ""))


def shares_asked(message: str, held: float) -> float:
    """How many shares the message is about: a count, half, or all of them."""
    if _HALF_RE.search(message or ""):
        return round(held / 2, 6)
    hit = _COUNT_RE.search(message or "")
    if hit:
        asked = float(hit.group(1).replace(",", "."))
        if 0 < asked <= held:
            return asked
    return held


def _price(ticker: str) -> tuple[float, str] | None:
    quote = next(iter(market.quotes([ticker])), None)
    if quote is None or not quote.price:
        return None
    return float(quote.price), quote.currency or ""


def simulate(*, db: Path, prefs_path: Path, ticker: str,
             shares: float | Callable[[float], float] | None = None,
             price: tuple[float, str] | None = None,
             today: date | None = None) -> Scenario | None:
    """The sale of `shares` of `ticker` today, or None when there is nothing
    to sell or no price to sell it at. `shares` None is the whole holding; a
    callable is asked with the holding's size (`shares_asked`), since how
    many "half" is depends on a replay this function is the one to run."""
    from stocks.portfolio import tax
    from stocks.portfolio.ledger import Transaction, all_transactions
    from stocks.portfolio.positions import build
    from stocks.portfolio.tax import prefs as tax_prefs

    prefs = tax_prefs.load(prefs_path)
    code, _how = tax_prefs.resolve(prefs)
    jur = tax.get(code)
    txs = all_transactions(db) if db.exists() else []
    if not txs:
        return None
    positions, realized = build(txs, base=jur.currency, matching=jur.matching)
    symbol = ticker.strip().upper()
    held = next((p for p in positions if p.ticker == symbol and p.quantity > 0), None)
    if held is None:
        return None
    quoted = price or _price(symbol)
    if quoted is None:
        return None
    if shares is None:
        wanted = held.quantity
    elif isinstance(shares, (int, float)):
        wanted = float(shares)
    else:
        wanted = shares(held.quantity)
    count = max(0.0, min(wanted, held.quantity))
    day = (today or date.today()).isoformat()
    year = jur.tax_year_of(day)
    settings = tax_prefs.with_funds(tax_prefs.settings(prefs), tax.labels(txs))
    before = jur.fiscal_year(realized, year, tax.buy_dates(txs), settings)
    if count <= 0:
        return Scenario(symbol, held.quantity, 0.0, quoted[0], quoted[1] or held.currency,
                        0.0, 0.0, before.estimated_tax, before.estimated_tax,
                        jur.currency, code, jur.year_label(year))
    sale = Transaction(date=day, ticker=symbol, action="sell", quantity=count,
                       price=quoted[0], currency=quoted[1] or held.currency)
    after_txs = [*txs, sale]
    _, after_realized = build(after_txs, base=jur.currency, matching=jur.matching)
    after = jur.fiscal_year(after_realized, year, tax.buy_dates(after_txs), settings)
    # Today's sale replays last, so everything before it matched as it did:
    # the difference between the two replays is this sale's parcels alone.
    obs.event("chat.whatif", jurisdiction=code, part=round(count / held.quantity, 2))
    return Scenario(
        ticker=symbol, held=held.quantity, shares=count, price=quoted[0],
        price_currency=quoted[1] or held.currency,
        proceeds=sum(s.proceeds for s in after_realized)
        - sum(s.proceeds for s in realized),
        gain=sum(s.gain for s in after_realized) - sum(s.gain for s in realized),
        tax_before=before.estimated_tax, tax_after=after.estimated_tax,
        currency=jur.currency, jurisdiction=code, year=jur.year_label(year),
    )


def target(message: str, watchlist: Path | None, focus: str) -> str:
    """The symbol a sale question is about: named, or the one on screen."""
    known = market.watchlist_names(watchlist) if watchlist else {}
    # No name lookup: a symbol the reader does not hold has nothing to sell,
    # and the replay says so faster than a Yahoo search would.
    found = market.mentioned(message, known, focus, lookup=lambda _name: "")
    return found[0] if found else ""


# -------------------------------------------------------------------- surface


def _money(value: float, currency: str, signed: bool = False) -> str:
    sign = "+" if signed and value > 0 else "-" if value < 0 else ""
    return f"{sign}{currency_symbol(currency)}{abs(value):,.0f}"


def view(s: Scenario, translate) -> dict:
    """The figures the surface shows, formatted: its `/view` data."""
    return {
        "proceeds": _money(s.proceeds, s.currency),
        "gain": _money(s.gain, s.currency, signed=True),
        "gain_tone": "up" if s.gain > 0 else "down" if s.gain < 0 else "flat",
        "tax": _money(s.extra_tax, s.currency, signed=True),
        "tax_tone": "down" if s.extra_tax > 0 else "up" if s.extra_tax < 0 else "flat",
        "tax_hint": translate(
            "chat.whatif_tax_hint", year=s.year,
            before=_money(s.tax_before, s.currency),
            after=_money(s.tax_after, s.currency),
        ),
    }


def surface(s: Scenario, translate) -> list[dict]:
    """A slider over the holding and the three figures that move with it."""
    # Whole shares for a whole holding; a hundredth of it for a fractional
    # one (crypto, a fund), which a one-share step would make unmovable.
    whole = s.held >= 1 and float(s.held).is_integer()
    step = 1 if whole else round(s.held / 100, 6) or 1
    parts = [
        a2ui.component("root", "Column",
                       children=["head", "shares", "figures", "note"]),
        a2ui.component("head", "Row", children=["ticker", "title"], align="center"),
        a2ui.component("ticker", "Ticker", symbol=s.ticker),
        a2ui.component("title", "Text", text=translate("chat.whatif_title"),
                       variant="h3"),
        a2ui.component(
            "shares", "Slider", label=translate("chat.whatif_shares"),
            value=a2ui.path("/shares"), min=0, max=s.held, step=step,
            action=a2ui.event(ACTION, ticker=s.ticker, shares=a2ui.path("/shares")),
        ),
        a2ui.component("figures", "Row",
                       children=["proceeds", "gain", "tax"]),
        a2ui.component("proceeds", "Metric", label=translate("chat.whatif_proceeds"),
                       value=a2ui.path("/view/proceeds")),
        a2ui.component("gain", "Metric", label=translate("chat.whatif_gain"),
                       value=a2ui.path("/view/gain"), tone=a2ui.path("/view/gain_tone")),
        a2ui.component("tax", "Metric", label=translate("chat.whatif_tax"),
                       value=a2ui.path("/view/tax"), tone=a2ui.path("/view/tax_tone"),
                       hint=a2ui.path("/view/tax_hint")),
        a2ui.component("note", "Text", text=translate("chat.whatif_note"),
                       variant="caption"),
    ]
    data = {"shares": s.shares, "view": view(s, translate)}
    return a2ui.surface(SURFACE_ID, parts, data)


def moved(s: Scenario, translate) -> list[dict]:
    """The same surface after the slider moved: its data, nothing else."""
    return [a2ui.data_update(SURFACE_ID, "/view", view(s, translate)),
            a2ui.data_update(SURFACE_ID, "/shares", s.shares)]
