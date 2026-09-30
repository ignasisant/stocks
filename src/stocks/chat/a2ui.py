"""A2UI surfaces the server builds for the drawer to draw.

A2UI (a2ui.org, v0.9) is UI as data: a surface is a flat list of components
from a catalog the client already knows how to draw, plus a JSON data model
the components bind to by JSON Pointer. Nothing in it is code, so a surface
cannot run anything in the reader's browser — the worst a malformed one can do
is draw nothing — and the drawer grows a new card without growing a component
for it.

The surfaces here are built by the server from data it already holds — a
proposal's fields, a mapping's columns — and never written by a model. The
free chain's models cannot be trusted to author layout JSON, and they do not
need to: a model at most chooses *which* surface and with what arguments, the
way the classifier chooses a tool, and this module lays it out.

The catalog is Aguait's: the basic catalog's layout and input components the
drawer needs, plus two of its own — `Metric` (a label over a figure, the KPI
readout) and `Ticker` (a symbol with its logo, linking to its page: every
ticker on screen is one) — and a `Slider` that may carry an `action`, sent when
the reader lets go. `chat/a2ui.tsx` draws exactly this set, and
`tests/test_chat_a2ui.py` holds the two to each other.

On the AG-UI wire a surface travels as an activity: `ACTIVITY_SNAPSHOT` with
`activityType` "a2ui" and the surface's messages as its content.
"""

from __future__ import annotations

from typing import Any

VERSION = "v0.9"
# A URI naming the catalog, as A2UI asks. A URN rather than a URL: there is no
# document to fetch at it, the drawer carries the catalog in its bundle.
CATALOG_ID = "urn:topstocks:a2ui:catalog:aguait:v1"
ACTIVITY_TYPE = "a2ui"

# component -> (required props, optional props). What the drawer draws.
CATALOG: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "Column": (frozenset({"children"}), frozenset({"align", "justify"})),
    "Row": (frozenset({"children"}), frozenset({"align", "justify"})),
    "Text": (frozenset({"text"}), frozenset({"variant"})),
    "Divider": (frozenset(), frozenset({"axis"})),
    "TextField": (frozenset({"label", "value"}), frozenset({"variant"})),
    "ChoicePicker": (frozenset({"options", "value"}),
                     frozenset({"label", "variant"})),
    "CheckBox": (frozenset({"label", "value"}), frozenset()),
    "Slider": (frozenset({"value", "min", "max"}),
               frozenset({"label", "step", "action"})),
    "Button": (frozenset({"text"}), frozenset({"variant", "action"})),
    "Metric": (frozenset({"label", "value"}), frozenset({"tone", "hint"})),
    "Ticker": (frozenset({"symbol"}), frozenset()),
}


def path(pointer: str) -> dict[str, str]:
    """A binding to the data model, `{"path": "/form/shares"}`."""
    return {"path": pointer}


def component(cid: str, kind: str, **props: Any) -> dict:
    """One component, checked against the catalog as it is built."""
    required, optional = CATALOG[kind]
    given = {k for k, v in props.items() if v is not None}
    missing = required - given
    unknown = given - required - optional
    if missing or unknown:
        raise ValueError(f"{kind} {cid}: missing {sorted(missing)}, "
                         f"unknown {sorted(unknown)}")
    return {"id": cid, "component": kind,
            **{k: v for k, v in props.items() if v is not None}}


def event(name: str, **context: Any) -> dict:
    """A server action: sent back as `{name, surfaceId, context}` on press."""
    return {"event": {"name": name, "context": context}}


def surface(surface_id: str, components: list[dict], data: dict) -> list[dict]:
    """The three messages that put one surface on screen, whole.

    The root is the component with id "root", as A2UI requires; every child a
    component names has to be in the list, which `check` holds a test to.
    """
    return [
        {"version": VERSION,
         "createSurface": {"surfaceId": surface_id, "catalogId": CATALOG_ID,
                           "sendDataModel": True}},
        {"version": VERSION,
         "updateComponents": {"surfaceId": surface_id, "components": components}},
        {"version": VERSION,
         "updateDataModel": {"surfaceId": surface_id, "value": data}},
    ]


def data_update(surface_id: str, pointer: str, value: Any) -> dict:
    """One change to a surface's data model, for a surface already drawn."""
    return {"version": VERSION,
            "updateDataModel": {"surfaceId": surface_id, "path": pointer,
                                "value": value}}


def check(messages: list[dict]) -> None:
    """Raise unless `messages` is one well-formed surface in this catalog."""
    ids: set[str] = set()
    refs: set[str] = set()
    for message in messages:
        if message.get("version") != VERSION:
            raise ValueError("wrong A2UI version")
        body = message.get("updateComponents")
        if not body:
            continue
        for comp in body["components"]:
            kind = comp.get("component")
            if kind not in CATALOG:
                raise ValueError(f"{kind} is not in the catalog")
            props = {k: v for k, v in comp.items() if k not in ("id", "component")}
            component(comp["id"], kind, **props)
            ids.add(comp["id"])
            refs.update(comp.get("children") or [])
    if "root" not in ids:
        raise ValueError("no root component")
    if refs - ids:
        raise ValueError(f"children not in the surface: {sorted(refs - ids)}")


def activity(surface_id: str, messages: list[dict]) -> dict:
    """A surface as an AG-UI activity: `{id, type, content}`."""
    return {"id": surface_id, "type": ACTIVITY_TYPE,
            "content": {"messages": messages}}


# ------------------------------------------------------------------ surfaces


def proposal_form(offer: dict, translate) -> list[dict]:
    """The edit fields under a proposal card: its symbol and its tool's values.

    Only the fields — the card's Confirm and Cancel are the drawer's own, and
    they send this surface's `/form` back as the answer to the interrupt
    (`tools.args_from_form` turns it back into the tool's arguments).
    """
    from stocks.chat import tools

    act = tools.Action(str(offer["kind"]), str(offer["ticker"]),
                       dict(offer.get("args") or {}))
    sid = f"form_{offer['id']}"
    names = ("ticker", *tools.FORMS.get(act.kind, ()))
    fields = [
        component(
            f"f_{name}", "TextField",
            label=translate(f"chat.action_field_{name}"),
            value=path(f"/form/{name}"),
            variant="number" if name in tools.NUMERIC_FIELDS else "shortText",
        )
        for name in names
    ]
    root = component("root", "Row", children=[f["id"] for f in fields],
                     align="end")
    return surface(sid, [root, *fields], {"form": tools.form_of(act)})


def column_mapping(mapping: dict, columns: list[str], translate) -> list[dict]:
    """How an unrecognised export's columns were read, and the way to fix it.

    One picker per ledger field over the file's own columns (header and a
    sample value, so "Column 4 — 12,50" is recognisable), preset to what the
    mapper chose. "Read again" sends the whole mapping back, and the file is
    re-read with it in Python — no model call, so the second read cannot
    disagree with the first about anything the reader did not change.
    """
    from stocks.portfolio import llm_map

    sid = "import_mapping"
    options = [{"label": translate("chat.import_col_none"), "value": ""}] + [
        {"label": label, "value": str(i)} for i, label in enumerate(columns)
    ]
    pickers = [
        component(
            f"c_{field}", "ChoicePicker",
            label=translate(f"chat.import_col_{field}"),
            options=options,
            value=path(f"/mapping/columns/{field}"),
            variant="mutuallyExclusive",
        )
        for field in llm_map.FIELDS
    ]
    intro = component("intro", "Text", text=translate("chat.import_col_intro"),
                      variant="caption")
    again = component("again", "Button", text=translate("chat.import_col_again"),
                      variant="primary",
                      action=event("remap", mapping=path("/mapping")))
    root = component("root", "Column",
                     children=["intro", *[p["id"] for p in pickers], "again"])
    cols = mapping.get("columns") or {}
    data = {"mapping": {
        **mapping,
        "columns": {f: ("" if cols.get(f) is None else str(cols[f]))
                    for f in llm_map.FIELDS},
    }}
    return surface(sid, [root, intro, *pickers, again], data)
