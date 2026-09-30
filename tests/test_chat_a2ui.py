"""The A2UI surfaces the server builds, and the catalog the drawer draws.

A surface is data, drawn by `frontend/app/src/chat/a2ui.tsx` from a fixed
catalog (`chat/a2ui.py`). The two failures worth a test are a component the
server emits and the drawer cannot draw — an empty card, silently — and a
surface whose parts do not add up (a child named and never sent, no root).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stocks.chat import a2ui, tools
from stocks.portfolio import llm_map

APP = Path(__file__).resolve().parents[1] / "frontend" / "app" / "src"
RENDERER = APP / "chat" / "a2ui.tsx"


def _say(key: str) -> str:
    return key


def test_the_drawer_draws_exactly_the_catalog():
    text = RENDERER.read_text()
    block = text[text.index("const CATALOG"):]
    block = block[:block.index("\n};")]
    drawn = set(re.findall(r"^  ([A-Z][A-Za-z]+):", block, re.M))
    assert drawn == set(a2ui.CATALOG)


def test_a_component_is_held_to_the_catalog_as_it_is_built():
    with pytest.raises(ValueError, match="missing"):
        a2ui.component("x", "TextField", label="Shares")
    with pytest.raises(ValueError, match="unknown"):
        a2ui.component("x", "Text", text="hi", onClick="alert(1)")
    with pytest.raises(KeyError):
        a2ui.component("x", "Script", src="evil.js")


def test_a_surface_has_a_root_and_every_child_it_names():
    good = a2ui.surface("s", [a2ui.component("root", "Column", children=["t"]),
                              a2ui.component("t", "Text", text="hi")], {})
    a2ui.check(good)
    orphan = a2ui.surface("s", [a2ui.component("root", "Column", children=["t"])], {})
    with pytest.raises(ValueError, match="children"):
        a2ui.check(orphan)
    rootless = a2ui.surface("s", [a2ui.component("t", "Text", text="hi")], {})
    with pytest.raises(ValueError, match="root"):
        a2ui.check(rootless)


@pytest.mark.parametrize("act", [
    tools.Action("favorite", "AAPL", {}),
    tools.Action("set_alerts", "AAPL", {"alerts": [
        {"type": "above", "price": 200.0}, {"type": "below", "price": 1500000.0},
    ]}),
    tools.Action("tag", "AAPL", {"tags": ["Tech", "Core"]}),
    tools.Action("add_ticker", "NVDA", {"name": "Nvidia"}),
    tools.Action("set_position", "AAPL", {"shares": 10.0, "cost": 187.5}),
])
def test_every_tool_s_form_reads_back_as_the_same_action(act):
    offer = {"id": "act_1", "kind": act.kind, "ticker": act.ticker, "args": act.args}
    messages = a2ui.proposal_form(offer, _say)
    a2ui.check(messages)
    form = messages[-1]["updateDataModel"]["value"]["form"]
    assert "e+" not in "".join(form.values()), "a big number is written out"
    fields = {c["id"] for c in messages[1]["updateComponents"]["components"]}
    names = tools.FORMS.get(act.kind, ())
    assert fields == {"root", "f_ticker", *(f"f_{n}" for n in names)}
    assert tools.revise(act, form["ticker"], tools.args_from_form(act.kind, form)) == act


def test_a_mapping_surface_offers_every_field_over_the_file_s_own_columns():
    mapping = {"header_row": 0, "columns": {"date": 0, "ticker": 1, "action": 2},
               "date_format": "", "decimal": ".", "thousands": "", "action_map": {},
               "asset_class": ""}
    messages = a2ui.column_mapping(mapping, ["When · 02/01", "What · AAPL", "Side"], _say)
    a2ui.check(messages)
    comps = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
    assert {f"c_{f}" for f in llm_map.FIELDS} <= set(comps)
    assert comps["c_date"]["options"][1] == {"label": "When · 02/01", "value": "0"}
    data = messages[-1]["updateDataModel"]["value"]["mapping"]["columns"]
    assert data["date"] == "0" and data["fee"] == ""


def test_a_grid_s_columns_are_named_by_header_and_sample():
    grid = [["Fecha", "", "Precio"], ["", "", ""], ["02/01/2024", "AAPL", "12,50"]]
    assert llm_map.columns(grid, 0) == (
        "Fecha · 02/01/2024", "#2 · AAPL", "Precio · 12,50",
    )
