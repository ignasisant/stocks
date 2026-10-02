"""Tax-loss harvesting and the rebalance, both replayed through the tax engine.

A ledger with one gain booked this year and open positions on either side of
their cost. What is tested is that each candidate's saving is the difference
the engine's own replay makes (Spain's savings base, 19% on the first
6,000), that the savings are not added up when they cannot all be used, and
that a rebalance sizes the trade that lands the position on its target.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from stocks.chat import a2ui, harvest, rebalance, whatif
from stocks.portfolio.ledger import Transaction, add_many

TODAY = date(2026, 9, 29)


@pytest.fixture
def book(tmp_path):
    """A 1,000 EUR gain booked in 2026, two open losses worth realising, one
    too small to bother with and one winner."""
    db = tmp_path / "portfolio.db"
    prefs = tmp_path / "prefs.json"
    prefs.write_text(json.dumps({"tax_residence": "ES"}))
    add_many([
        Transaction("2025-01-02", "AAPL", "buy", 10, 100.0, "EUR"),
        Transaction("2026-03-02", "AAPL", "sell", 10, 200.0, "EUR"),
        Transaction("2025-02-03", "NVO", "buy", 10, 300.0, "EUR"),
        Transaction("2025-02-03", "TTD", "buy", 10, 100.0, "EUR"),
        Transaction("2025-02-03", "SMALL", "buy", 10, 60.0, "EUR"),
        Transaction("2025-02-03", "WIN", "buy", 10, 50.0, "EUR"),
    ], db)
    return whatif.replay(db=db, prefs_path=prefs, today=TODAY)


@pytest.fixture
def tbl():
    """The Home page's frame for that book at today's prices."""
    rows = {
        "NVO": (10, 1000.0, -2000.0),
        "TTD": (10, 500.0, -500.0),
        "SMALL": (10, 500.0, -100.0),
        "WIN": (10, 1000.0, 500.0),
    }
    frame = pd.DataFrame.from_dict(rows, orient="index",
                                   columns=["shares", "value", "pnl"])
    frame["weight"] = frame["value"] / frame["value"].sum()
    return frame


def _tr(key, **kw):
    return key + (f" {kw}" if kw else "")


# ------------------------------------------------------------------ harvest


@pytest.mark.parametrize(("said", "wants"), [
    ("¿Qué podría vender para compensar plusvalías?", True),
    ("¿tengo minusvalías que aprovechar?", True),
    ("¿Cómo puedo pagar menos impuestos este año?", True),
    ("any tax-loss harvesting I should look at?", True),
    ("which losses would offset my gains?", True),
    ("how do I cut my capital gains tax?", True),
    ("¿compensa comprar NVDA ahora?", False),
    ("¿cuánto pagaría si vendo mis AAPL?", False),
])
def test_only_losses_against_gains_open_a_harvest(said, wants):
    assert harvest.wants(said) is wants


def test_each_open_loss_saves_what_the_engine_s_replay_says(book, tbl):
    found = harvest.build(book, tbl)
    assert [c.ticker for c in found.candidates] == ["NVO", "TTD"]  # largest first
    nvo, ttd = found.candidates
    assert nvo.loss == pytest.approx(-2000.0) and ttd.loss == pytest.approx(-500.0)
    # 1,000 realised: NVO's loss cancels all of it, TTD's half.
    assert found.tax == pytest.approx(190.0)
    assert nvo.saving == pytest.approx(190.0)
    assert ttd.saving == pytest.approx(95.0)
    assert (found.gains, found.losses) == (pytest.approx(1000.0), 0.0)


def test_the_savings_do_not_add_up_past_the_year_s_gains(book, tbl):
    """Together the losses are 2,500 against a 1,000 gain: the bill goes to
    nothing, not below it, and the rest carries forward."""
    found = harvest.build(book, tbl)
    assert found.saving == pytest.approx(190.0)
    assert found.tax_all == 0
    assert found.carry == pytest.approx(1500.0)
    assert found.carry_years == 4


def test_the_repurchase_window_closes_two_months_and_a_day_out(book, tbl):
    found = harvest.build(book, tbl)
    assert (found.window, found.clear) == ("2m", "2026-11-30")
    assert "clear from 2026-11-30" in found.line()


def test_a_loss_too_small_to_matter_is_not_a_candidate(book, tbl):
    found = harvest.build(book, tbl)
    assert "SMALL" not in {c.ticker for c in found.candidates}


def test_no_open_loss_says_so_and_draws_nothing_to_choose_from(book, tbl):
    found = harvest.build(book, tbl.loc[["WIN"]])
    assert found.candidates == ()
    assert "no loss worth realising" in found.line()


def test_without_a_ledger_there_is_nothing_to_harvest(tbl):
    assert harvest.build(None, tbl) is None


def test_the_prompt_line_carries_the_engine_s_figures(book, tbl):
    line = harvest.build(book, tbl).line()
    assert "ES rules, tax year 2026" in line
    assert "NVO: loss -2,000.00 EUR, this year's tax -190.00 EUR" in line
    assert "tax 190.00 -> 0.00 EUR (saving 190.00 EUR)" in line
    assert "1,500.00 EUR of net loss left to carry forward for 4 years" in line


def test_a_deferred_part_of_a_loss_is_named(book, tbl):
    found = harvest.build(book, tbl)
    blocked = harvest.Harvest(**{
        **found.__dict__,
        "candidates": (harvest.Candidate("NVO", 10, -2000.0, 0.0, 300.0),),
    })
    assert "300.00 EUR of the loss is deferred" in blocked.line()


def test_the_surface_is_a_row_per_candidate_and_the_window(book, tbl):
    messages = harvest.surface(harvest.build(book, tbl), _tr)
    a2ui.check(messages)
    parts = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
    assert parts["c0_t"]["symbol"] == "NVO" and parts["c1_t"]["symbol"] == "TTD"
    assert parts["c0_s"]["value"] == "€190"
    assert parts["note"]["text"].startswith("chat.harvest_window_2m")


# ---------------------------------------------------------------- rebalance


@pytest.mark.parametrize(("said", "wants"), [
    ("quiero que WIN pese un 20%", True),
    ("vender WIN hasta que pese un 10%", True),
    ("reduce WIN to 5% of my portfolio", True),
    ("bajar WIN al 7,5%", True),
    ("¿cómo rebalanceo la cartera?", True),
    ("¿WIN bajó un 10% hoy?", False),
    ("¿cuánto pesa WIN?", False),
])
def test_only_a_weight_asked_for_opens_a_rebalance(said, wants):
    assert rebalance.wants(said) is wants


@pytest.mark.parametrize(("said", "target"), [
    ("que pese un 20%", 20.0),
    ("bajar al 7,5%", 7.5),
    ("rebalancear", None),
    ("al 120%", None),
])
def test_the_target_is_read_off_the_message(said, target):
    assert rebalance.target_asked(said) == target


def test_a_sale_down_to_the_target_lands_on_it_and_is_taxed(book, tbl):
    """WIN is 1,000 of 3,000. At 20% with the rest untouched it is 500 of
    2,500: five shares sold at 100, a 250 gain on the 1,000 booked."""
    moved = rebalance.build(book, tbl, "win", 20)
    assert moved.weight == pytest.approx(100 / 3)
    assert moved.shares == pytest.approx(-5.0)
    assert moved.amount == pytest.approx(-500.0)
    assert (moved.value + moved.amount) / (moved.total + moved.amount) == (
        pytest.approx(0.20))
    assert moved.gain == pytest.approx(250.0)
    assert moved.extra_tax == pytest.approx(250.0 * 0.19)


def test_a_purchase_up_to_the_target_owes_nothing(book, tbl):
    moved = rebalance.build(book, tbl, "WIN", 50)
    assert moved.shares == pytest.approx(10.0)  # 2,000 of 4,000
    assert moved.extra_tax == 0 and moved.gain == 0


def test_nothing_named_opens_where_it_stands(book, tbl):
    moved = rebalance.build(book, tbl, "WIN", None)
    assert (moved.target, moved.shares) == (33.3, 0.0)


def test_a_sale_never_sells_more_than_is_held(book, tbl):
    assert rebalance.build(book, tbl, "WIN", 0).shares == pytest.approx(-10.0)


def test_something_not_held_is_not_reweighed(book, tbl):
    assert rebalance.build(book, tbl, "MSFT", 10) is None


def test_the_rebalance_surface_is_a_slider_over_the_weight(book, tbl):
    moved = rebalance.build(book, tbl, "WIN", 20)
    messages = rebalance.surface(moved, _tr)
    a2ui.check(messages)
    parts = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
    assert parts["target"]["action"] == {"event": {
        "name": "reweigh", "context": {"ticker": "WIN", "target": {"path": "/target"}},
    }}
    view = messages[-1]["updateDataModel"]["value"]["view"]
    assert view["weight"] == "33.3% → 20.0%"
    assert view["trade"] == "chat.rebalance_sell {'shares': '5'}"
    assert view["tax"] == "+€48"
    assert [m["updateDataModel"]["path"] for m in rebalance.moved(moved, _tr)] == [
        "/view", "/target"]
