"""`data.fx.rates_range` when frankfurter is down.

On 2026-11-04 it answered 522 for two hours, `portfolio.fx_range_failed`
dropped every USD row, and the book's history and the sell/add weights went
with them. The rates a range already fetched are kept in the per-date history
and answer in its place.
"""

from __future__ import annotations

from urllib.error import HTTPError

import pytest

from stocks.data import fx


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "FX_CACHE", tmp_path / "fx_history.json")
    monkeypatch.setattr(fx, "_MEM_CACHE", None)
    monkeypatch.setattr(fx, "_range_memo", {})
    monkeypatch.setattr(fx, "_mirror_timer", None)
    monkeypatch.setattr(fx.storage, "enabled", lambda: False)
    return tmp_path / "fx_history.json"


def _up(rates: dict[str, float], quote: str = "EUR"):
    def get_json(url, timeout=15):
        return {"rates": {d: {quote: r} for d, r in rates.items()}}

    return get_json


def _down(url, timeout=15):
    raise HTTPError(url, 522, "Origin Connection Time-out", None, None)


def test_a_range_fetched_once_answers_when_frankfurter_is_down(history, monkeypatch):
    monkeypatch.setattr(fx, "get_json", _up({"2026-11-02": 0.86, "2026-11-03": 0.87}))
    assert fx.rates_range("2026-11-02", "2026-11-03", "USD", "EUR") == {
        "2026-11-02": 0.86,
        "2026-11-03": 0.87,
    }
    monkeypatch.setattr(fx, "get_json", _down)
    monkeypatch.setattr(fx, "_MEM_CACHE", None)  # a fresh process: from disk
    assert fx.rates_range("2026-11-01", "2026-11-04", "USD", "EUR") == {
        "2026-11-02": 0.86,
        "2026-11-03": 0.87,
    }, "same days, a wider span: callers forward-fill the rest"


def test_the_fallback_is_not_memoised(history, monkeypatch):
    monkeypatch.setattr(fx, "get_json", _up({"2026-11-02": 0.86}))
    fx.rates_range("2026-11-02", "2026-11-02", "USD", "EUR")
    monkeypatch.setattr(fx, "get_json", _down)
    fx.rates_range("2026-11-02", "2026-11-04", "USD", "EUR")
    monkeypatch.setattr(fx, "get_json", _up({"2026-11-02": 0.86, "2026-11-04": 0.88}))
    assert fx.rates_range("2026-11-02", "2026-11-04", "USD", "EUR")["2026-11-04"] == 0.88


def test_rate_on_entries_count_both_ways_round(history, monkeypatch):
    fx._cache()["2026-11-03:EUR:USD"] = 1.25
    monkeypatch.setattr(fx, "get_json", _down)
    assert fx.rates_range("2026-11-01", "2026-11-04", "USD", "EUR") == {"2026-11-03": 0.8}


def test_nothing_kept_still_raises(history, monkeypatch):
    monkeypatch.setattr(fx, "get_json", _down)
    with pytest.raises(HTTPError):
        fx.rates_range("2026-11-01", "2026-11-04", "USD", "EUR")


def test_the_book_keeps_its_foreign_rows_through_the_outage(history, monkeypatch):
    import pandas as pd

    from stocks.analysis import portfolio

    days = {"2026-11-02": 0.86, "2026-11-03": 0.87}
    monkeypatch.setattr(fx, "get_json", _up(days))
    fx.rates_range("2026-11-02", pd.Timestamp.today().date().isoformat(), "USD", "EUR")
    monkeypatch.setattr(fx, "get_json", _down)
    monkeypatch.setattr(fx, "_range_memo", {})
    index = pd.bdate_range("2026-11-02", "2026-11-04")
    rates = portfolio.fx_frame(["USD"], index, base="EUR")
    assert list(rates["USD"]) == [0.86, 0.87, 0.87]
