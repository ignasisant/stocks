"""How is my portfolio split? The book's weights, drawn as a donut under the answer.

"¿Estoy bien diversificado?" is a question about figures the app already
prints on the Risk tab, and one a model answers badly from a list of
positions: it adds a fund's whole weight to "ETF" rather than to the sectors
inside it, and draws its pie in ASCII. So the split is summed here, the way the
Risk tab and the Home card's sector line sum it (`analysis.portfolio
.allocation`, funds looked through to their holdings), and reaches the reader
twice, as the what-if sale does (`chat/whatif.py`): the figures ride on the
question so the prose quotes them, and the donut is a surface under the answer.

All four splits — by position, sector, country and currency — go in one
surface's data, and the chips under the ring switch between them in the
drawer: no action, no request, no model.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from stocks import obs
from stocks.chat import a2ui

SURFACE_ID = "allocation"
DIMENSIONS = ("position", "sector", "country", "currency")
# Slices per split quoted to the model; the drawer folds its own tail.
PROMPT_SLICES = 8

# Matched with the accents folded away. A split being asked about...
_MIX_RE = re.compile(
    r"\breparto\b|\brepartid[ao]s?\b|\bdistribucion\b|\bdistribuid[ao]s?\b|"
    r"\ballocation\b|\basignacion\b|\bdiversific|\bdiversified\b|\bexposicion\b|"
    r"\bexposure\b|\bexpuest[oa]s?\b|\bexposed\b|\bbreakdown\b|\bdesglose\b|"
    r"\bcomposicion\b|\bconcentrad[ao]s?\b|\bconcentracion\b|\bconcentration\b|"
    r"\bconcentrated\b|\btarta\b|\bquesito\b|\bdonut\b|\bpie chart\b",
    re.IGNORECASE,
)
# ... by one of the dimensions it is summed over ...
_BY_RE = re.compile(
    r"\b(?:por|by|per) (?:sectores|sector|sectors|paises|pais|country|countries|"
    r"regiones|region|regions|divisas|divisa|monedas|moneda|currency|currencies|"
    r"posiciones|posicion|positions|position|holdings|valores|empresas)\b",
    re.IGNORECASE,
)
# ... of the reader's own book, not of a fund or the market. A split of the
# dividends ("¿cómo se reparten mis dividendos?") is the income tab's, not this.
_NOT_RE = re.compile(r"\bdividend|\bcupon|\bcoupon|\bimpuesto|\btax", re.IGNORECASE)
# ... of the reader's own book, not of a fund or the market.
_MINE_RE = re.compile(
    r"\b(?:mi|mis|my) (?:cartera|portfolio|portafolio|book|inversiones|"
    r"investments|holdings|posiciones|positions|acciones|shares)\b|"
    r"\btengo\b|\bestoy\b|\bam i\b|\bdo i\b|\bi have\b|\bi hold\b|\bi'm\b",
    re.IGNORECASE,
)
_DIMENSION_RES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (dimension, re.compile(pattern, re.IGNORECASE)) for dimension, pattern in (
        ("sector", r"\bsector|\bindustri|\btecnolog|\btech\b"),
        ("country", r"\bpais|\bcountr|\bregion|\bgeograf|\bgeograph|\bemergentes?\b|"
                    r"\bemerging\b|\bestados unidos\b|\beeuu\b|\busa\b|\beuropa?\b"),
        ("currency", r"\bdivisa|\bmoneda|\bcurrenc|\bdolar|\bdollar|\bfx\b"),
    )
)


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(ch))


def wants(message: str) -> bool:
    """Whether the message asks how the reader's own book is split."""
    text = _fold(message)
    if _NOT_RE.search(text):
        return False
    mix, by, mine = (bool(p.search(text)) for p in (_MIX_RE, _BY_RE, _MINE_RE))
    return (mix and (mine or by)) or (by and mine)


def dimension_asked(message: str) -> str:
    """The split the message names, or the book by position."""
    text = _fold(message)
    return next((d for d, pattern in _DIMENSION_RES if pattern.search(text)),
                "position")


@dataclass(frozen=True)
class Mix:
    """The book's weights, summed four ways, and how concentrated it is."""

    by: str  # the split asked about, drawn first
    groups: dict[str, tuple[tuple[str, float], ...]]  # dimension -> (label, weight)
    positions: int
    largest: str
    largest_weight: float
    top5: float
    effective: float  # 1 / HHI: how many equal-sized names it behaves like
    currency: str

    @property
    def dimensions(self) -> list[str]:
        return [d for d in DIMENSIONS if self.groups.get(d)]

    def line(self) -> str:
        """The prompt's paragraph: the splits and the concentration, quoted."""
        rows = []
        for d in self.dimensions:
            slices = self.groups[d]
            shown = ", ".join(f"{label} {weight:.1%}"
                              for label, weight in slices[:PROMPT_SLICES])
            rest = sum(weight for _, weight in slices[PROMPT_SLICES:])
            if rest > 0:
                shown += f", {len(slices) - PROMPT_SLICES} more together {rest:.1%}"
            rows.append(f"- by {d}: {shown}")
        return (
            "\n\n---\nThe app draws the reader's allocation as a donut under your "
            f"answer, opened on the split by {self.by} (weights of the market value "
            f"in {self.currency} at today's prices; funds looked through to what "
            "they hold, so an index fund counts in the sectors and countries inside "
            "it). Do not draw a chart, pie or diagram yourself — no ASCII art, no "
            "bars of symbols; refer to the donut shown, and quote these figures "
            "rather than any of your own:\n" + "\n".join(rows) + "\n"
            f"- concentration: {self.positions} positions; the largest, "
            f"{self.largest}, is {self.largest_weight:.1%}; the top five are "
            f"{self.top5:.1%}; the book behaves like {self.effective:.1f} "
            "equal-sized positions (1 / sum of squared weights)"
        )


def _split(series: pd.Series) -> tuple[tuple[str, float], ...]:
    total = float(series.sum())
    if not total > 0:
        return ()
    shares = (series / total).sort_values(ascending=False)
    return tuple((str(label), float(weight)) for label, weight in shares.items()
                 if weight > 0.0005)


def build(tbl: pd.DataFrame | None, by: str = "position", currency: str = "EUR", *,
          meta=None) -> Mix | None:
    """The book's split from the Home page's frame (`engine.enriched_frame`),
    or None when nothing in it is weighted. `meta` is `load_meta`, the
    sector/country/currency per ticker the Risk tab sums with."""
    from stocks.analysis.portfolio import allocation, effective_positions, top_n_weight

    if tbl is None or "weight" not in tbl:
        return None
    weights = {str(t): float(w) for t, w in tbl["weight"].dropna().items() if w > 0}
    if not weights:
        return None
    total = sum(weights.values())
    weights = {t: w / total for t, w in weights.items()}
    groups = {"position": _split(pd.Series(weights, dtype=float))}
    try:
        if meta is None:
            from stocks.analysis.portfolio import load_meta

            meta = load_meta(sorted(weights))
        for d in DIMENSIONS[1:]:
            groups[d] = _split(allocation(weights, meta, d))
    except Exception as exc:  # noqa: BLE001 — the split by position still stands
        obs.warn("chat.allocation_meta_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
    largest, largest_weight = groups["position"][0]
    obs.event("chat.allocation", by=by, positions=len(weights))
    return Mix(
        by=by if groups.get(by) else "position", groups=groups,
        positions=len(weights), largest=largest, largest_weight=largest_weight,
        top5=top_n_weight(weights, 5), effective=effective_positions(weights),
        currency=currency,
    )


# -------------------------------------------------------------------- surface


def _pct(value: float) -> str:
    return f"{value:.0%}" if value >= 0.1 else f"{value:.1%}"


def surface(m: Mix, translate) -> list[dict]:
    """Three concentration figures, the ring, and the chips that switch it."""
    parts = [
        a2ui.component("root", "Column",
                       children=["title", "figures", "ring", "splits", "note"]),
        a2ui.component("title", "Text", text=translate("chat.mix_title"),
                       variant="h3"),
        a2ui.component("figures", "Row", children=["largest", "top5", "effective"]),
        a2ui.component("largest", "Metric", label=translate("chat.mix_largest"),
                       value=_pct(m.largest_weight), hint=m.largest),
        a2ui.component("top5", "Metric", label=translate("chat.mix_top5"),
                       value=_pct(m.top5),
                       hint=translate("chat.mix_positions", count=m.positions)),
        a2ui.component("effective", "Metric", label=translate("chat.mix_effective"),
                       value=f"{m.effective:.1f}",
                       hint=translate("chat.mix_effective_hint")),
        a2ui.component("ring", "Donut", slices=a2ui.path("/groups"),
                       by=a2ui.path("/by"), label=translate("chat.mix_title"),
                       other=translate("chat.mix_other")),
        a2ui.component(
            "splits", "ChoicePicker",
            options=[{"label": translate(f"chat.mix_by_{d}"), "value": d}
                     for d in m.dimensions],
            value=a2ui.path("/by"), variant="chips",
        ),
        a2ui.component("note", "Text", text=translate("chat.mix_note"),
                       variant="caption"),
    ]
    data = {
        "by": m.by,
        "groups": {d: [{"label": label, "weight": round(weight, 6)}
                       for label, weight in m.groups[d]]
                   for d in m.dimensions},
    }
    return a2ui.surface(SURFACE_ID, parts, data)
