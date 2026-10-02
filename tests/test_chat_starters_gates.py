"""The opening screen's suggestions each open the surface they show off.

A suggestion is a prefilled question, and the ones on the drawer's empty
thread (`frontend/app/src/chat/Empty.tsx`) are there to show what the app
works out rather than the model: the book against an index, the split with
funds looked through, the losses the tax engine would offset, a position
sized to a weight, the bull-and-bear debate, a chart. Each of those is gated
on the wording of the message, so a reworded suggestion can quietly stop
opening its surface, or open a second one beside it. This reads the copy in
every language, fills its slots the way the drawer does and runs it through
every gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stocks.chat import allocation, charts, debate, harvest, rebalance, whatif

LOCALES = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web" / "locales"
SLOTS = {"a": "NVDA", "b": "MSFT", "top": "ASML.AS", "n": 12}
GATES = {
    "chart": charts.wants,
    "mix": allocation.wants,
    "harvest": harvest.wants,
    "rebalance": rebalance.wants,
    "debate": debate.wants,
}
# The surface each suggestion opens; None for one answered in prose.
OPENS = {
    "benchmark": "chart",
    "exposure": "mix",
    "harvest": "harvest",
    "rebalance": "rebalance",
    "movers": None,
    "debate": "debate",
    "chart": "chart",
    "earnings": None,
}


def _asked(lang: str, name: str) -> str:
    catalog = json.loads((LOCALES / lang / "chat.json").read_text())
    text = catalog[f"chat.starter_{name}"]
    for slot, value in SLOTS.items():
        text = text.replace(f"{{{slot}}}", str(value))
    return text


@pytest.mark.parametrize("lang", ["en", "es"])
@pytest.mark.parametrize(("name", "gate"), OPENS.items())
def test_each_suggestion_opens_its_surface_and_no_other(lang, name, gate):
    asked = _asked(lang, name)
    opened = [g for g, wants in GATES.items() if wants(asked)]
    assert opened == ([gate] if gate else []), asked


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_book_question_is_the_book_against_the_index_this_year(lang):
    asked = _asked(lang, "benchmark")
    assert charts.targets(asked, {}, "", "EUR", lookup=lambda _n: "") == [
        charts.BOOK, "^GSPC"]
    assert charts.window_asked(asked) == "ytd"


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_split_is_by_country_where_funds_are_looked_through(lang):
    assert allocation.dimension_asked(_asked(lang, "exposure")) == "country"


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_rebalance_names_the_position_and_the_weight(lang):
    asked = _asked(lang, "rebalance")
    assert whatif.target(asked, None, "") == SLOTS["top"]
    assert rebalance.target_asked(asked) == SLOTS["n"]


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_chart_draws_both_tickers_and_the_index(lang):
    asked = _asked(lang, "chart")
    assert set(charts.targets(asked, {}, "", "EUR", lookup=lambda _n: "")) == {
        "NVDA", "MSFT", "^IXIC"}
