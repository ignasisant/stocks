"""How the book is split: the Risk tab's sums, under the answer as a donut."""

from __future__ import annotations

import pandas as pd
import pytest

from stocks.chat import a2ui, allocation

META = {
    "NVDA": {"sector": "Technology", "country": "United States", "currency": "USD"},
    "SAN": {"sector": "Financial Services", "country": "Spain", "currency": "EUR"},
    # A fund counts in the sectors inside it, not as one "ETF" slice.
    "VWCE": {"sector_weights": {"Technology": 0.5, "Financial Services": 0.5},
             "country_weights": {"United States": 0.6, "Spain": 0.4},
             "currency": "EUR"},
}


@pytest.fixture
def tbl():
    return pd.DataFrame({"weight": [0.5, 0.25, 0.25]}, index=["NVDA", "SAN", "VWCE"])


@pytest.mark.parametrize(("said", "wants"), [
    ("¿Estoy bien diversificado?", True),
    ("¿cómo está repartida mi cartera por sectores?", True),
    ("my portfolio breakdown by country", True),
    ("¿qué exposición tengo al dólar?", True),
    ("¿cómo se reparten mis dividendos?", False),
    ("¿cuál es la exposición de QQQ a tecnología?", False),
    ("gráfico de NVDA", False),
])
def test_only_the_reader_s_own_split_opens_one(said, wants):
    assert allocation.wants(said) is wants


@pytest.mark.parametrize(("said", "by"), [
    ("mi cartera por sectores", "sector"),
    ("¿cuánto tengo por país?", "country"),
    ("¿qué exposición tengo al dólar?", "currency"),
    ("¿estoy diversificado?", "position"),
])
def test_the_split_asked_about_is_the_one_opened(said, by):
    assert allocation.dimension_asked(said) == by


def test_funds_are_looked_through_and_every_split_sums_to_one(tbl):
    mix = allocation.build(tbl, "sector", meta=META)
    assert dict(mix.groups["sector"]) == pytest.approx(
        {"Technology": 0.625, "Financial Services": 0.375})
    assert dict(mix.groups["country"]) == pytest.approx(
        {"United States": 0.65, "Spain": 0.35})
    for d in allocation.DIMENSIONS:
        assert sum(w for _, w in mix.groups[d]) == pytest.approx(1.0)


def test_concentration_is_the_risk_tab_s(tbl):
    mix = allocation.build(tbl, meta=META)
    assert (mix.largest, mix.largest_weight, mix.positions) == ("NVDA", 0.5, 3)
    assert mix.effective == pytest.approx(1 / (0.25 + 0.0625 * 2))
    assert "behaves like 2.7 equal-sized positions" in mix.line()


def test_without_metadata_the_split_by_position_still_stands(tbl, monkeypatch):
    from stocks.analysis import portfolio

    monkeypatch.setattr(portfolio, "load_meta", lambda tickers: 1 / 0)
    mix = allocation.build(tbl, "sector")
    assert mix.dimensions == ["position"] and mix.by == "position"


def test_nothing_weighted_is_no_split():
    assert allocation.build(None) is None
    assert allocation.build(pd.DataFrame({"weight": [0.0]}, index=["X"])) is None


def test_the_surface_is_a_ring_and_chips_bound_to_one_split(tbl):
    mix = allocation.build(tbl, "country", meta=META)
    messages = allocation.surface(mix, lambda key, **kw: key)
    a2ui.check(messages)
    parts = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
    assert parts["ring"]["slices"] == {"path": "/groups"}
    # The chips switch the ring in the drawer: no action, no request.
    assert parts["splits"]["value"] == {"path": "/by"} and "action" not in parts["splits"]
    data = messages[-1]["updateDataModel"]["value"]
    assert data["by"] == "country" and set(data["groups"]) == set(allocation.DIMENSIONS)


def test_the_split_is_quoted_in_money_too():
    """Local review 2026-10-29: "¿cuánto tengo en EE. UU.?" got weights only —
    the prompt carried no amount for the model to quote."""
    frame = pd.DataFrame({"weight": [0.5, 0.25, 0.25], "value": [5000.0, 2500.0, 2500.0]},
                         index=["NVDA", "SAN", "VWCE"])
    mix = allocation.build(frame, "country", meta=META)
    assert mix.total == pytest.approx(10_000)
    assert "United States 65.0% (6,500 EUR)" in mix.line()
    assert "worth 10,000 EUR" in mix.line()


def test_an_unclassified_slice_names_the_holdings_it_comes_from():
    """The same review: 17.5 % "sin clasificar" with no word of whose it was."""
    meta = {**META, "VWCE": {**META["VWCE"],
                             "country_weights": {"United States": 0.6}}}
    frame = pd.DataFrame({"weight": [0.5, 0.25, 0.25]}, index=["NVDA", "SAN", "VWCE"])
    mix = allocation.build(frame, "country", meta=meta)
    assert mix.unknown["country"] == (("VWCE", pytest.approx(0.1)),)
    assert "Unknown by country" in mix.line() and "VWCE 10.0%" in mix.line()
    assert "sector" not in mix.unknown
