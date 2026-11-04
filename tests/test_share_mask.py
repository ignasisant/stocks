"""What of a chat answer may leave the account when it is shared by link.

The masked cut hides the sharer's money and holding sizes and keeps what makes
the answer worth sending (tickers, percentages, dates); every cut leaves the
surfaces inert, and the masked one drops the surfaces that are tables of money.
"""

from __future__ import annotations

import pytest

from stocks.chat import a2ui, share_mask


@pytest.mark.parametrize(
    ("text", "hidden"),
    [
        ("Tu posición vale 12.345,67 € hoy.", "12.345,67"),
        ("Vale €1,234.50 al cierre.", "1,234.50"),
        ("A sale would realise $980 before tax.", "980"),
        ("Unos 15 k€ en total.", "15 k"),
        ("Ganarías 2.300 EUR.", "2.300"),
        ("Tienes 120 acciones de NVDA.", "120"),
        ("You hold 35 shares of AAPL.", "35"),
        ("0,5 BTC al precio de hoy.", "0,5"),
        ("Plusvalía de +1.250,00 USD.", "+1.250,00"),
    ],
)
def test_money_and_holding_sizes_are_hidden(text, hidden):
    out = share_mask.mask_text(text)
    assert hidden not in out
    assert share_mask.MASK in out


def test_what_makes_the_answer_worth_sending_is_kept():
    text = ("NVDA sube un 12,5 % desde el 3 de octubre de 2026; "
            "el P/E de 45 está por encima de la media de 5 años.")
    assert share_mask.mask_text(text) == text


def test_the_currency_and_unit_stay_so_the_sentence_still_reads():
    assert share_mask.mask_text("Vale 1.000 €.") == "Vale ••• €."
    assert share_mask.mask_text("Tienes 30 acciones.") == "Tienes ••• acciones."


def _surface(sid: str, *, action: bool = True) -> dict:
    parts = [
        a2ui.component("root", "Column", children=["title", "pick", "go"]),
        a2ui.component("title", "Text", text="t"),
        a2ui.component(
            "pick", "ChoicePicker", options=[{"label": "1M", "value": "1m"}],
            value=a2ui.path("/w"),
            action=a2ui.event("x", w=a2ui.path("/w")) if action else None,
        ),
        a2ui.component("go", "Button", text="Go"),
    ]
    return a2ui.activity(sid, a2ui.surface(sid, parts, {"w": "1m"}))


def test_a_shared_surface_keeps_what_it_shows_and_loses_what_it_does():
    (kept,) = share_mask.surfaces([_surface("chart")], masked=True)
    messages = kept["content"]["messages"]
    a2ui.check(messages)
    comps = next(m["updateComponents"]["components"] for m in messages
                 if "updateComponents" in m)
    ids = {c["id"] for c in comps}
    assert ids == {"root", "title"}
    assert next(c for c in comps if c["id"] == "root")["children"] == ["title"]


def test_a_picker_without_an_action_is_only_a_label_and_stays():
    (kept,) = share_mask.surfaces([_surface("allocation", action=False)], masked=True)
    comps = next(m["updateComponents"]["components"]
                 for m in kept["content"]["messages"] if "updateComponents" in m)
    assert "pick" in {c["id"] for c in comps}


def test_the_original_surface_is_not_touched():
    original = _surface("chart")
    share_mask.surfaces([original], masked=True)
    comps = next(m["updateComponents"]["components"]
                 for m in original["content"]["messages"] if "updateComponents" in m)
    assert {c["id"] for c in comps} == {"root", "title", "pick", "go"}


def test_tables_of_money_go_only_unmasked_and_proposals_never():
    acts = [_surface(s) for s in ("whatif", "harvest", "rebalance", "plan_builder",
                                  "form_a1", "diff_a1", "chart")]
    assert [a["id"] for a in share_mask.surfaces(acts, masked=True)] == ["chart"]
    assert [a["id"] for a in share_mask.surfaces(acts, masked=False)] == [
        "whatif", "harvest", "rebalance", "plan_builder", "chart"]
