"""The Today page's shared market read (`chat/today_market.py`).

What has to hold:

* **Facts are built block by block.** A source that fails names its block
  under `missing` and the others still answer; a block missing this morning
  keeps yesterday's.
* **No figure is printed that the facts do not carry.** A written line with
  a stray percentage, amount or basis-point move is dropped; a reply left
  with fewer than two lines falls back to the computed read. Index names
  ("S&P 500") and the breadth windows ("200-session") are not figures.
* **It is paid from the global pot only**, never an account's allowance.
* **The file is stamped by the session its figures close on**, not by the
  action day, and judged stale against the last settled US session.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from stocks import storage
from stocks.analysis import sentiment as sm
from stocks.api import loaders
from stocks.chat import engine, today_market

DAY = date(2026, 10, 13)
SESSIONS = pd.bdate_range(end="2026-10-12", periods=260)


def _series(start: float, drift: float) -> pd.Series:
    return pd.Series(start * np.exp(drift * np.arange(len(SESSIONS))), index=SESSIONS)


def _closes() -> dict[str, pd.Series]:
    out = {"SPY": _series(500.0, 0.0005)}
    for i, ticker in enumerate(sm.SECTOR_ETFS.values()):
        out[ticker] = _series(100.0, 0.0002 * i - 0.0008)
    return out


def _rates() -> dict[str, pd.Series]:
    days = pd.bdate_range(end="2026-10-12", periods=60)

    def path(start, end):
        return pd.Series(np.linspace(start, end, len(days)), index=days)

    fed = pd.Series(4.25, index=days)
    fed.iloc[40:] = 4.0
    return {
        "DGS10": path(4.6, 4.9),
        "T10Y2Y": path(0.3, 0.4),
        "BAMLH0A0HYM2": path(3.0, 3.1),
        "DFEDTARU": fed,
        "ECBDFR": pd.Series(2.0, index=days),
    }


def _inflation() -> pd.DataFrame:
    return pd.DataFrame([
        {"area": "EA", "period": "2026-09", "headline": 2.1, "core": 2.3,
         "momentum": 0.1},
        {"area": "US", "period": "2026-08", "headline": 2.9, "core": 3.1,
         "momentum": -0.2},
        {"area": "UK", "period": "2026-08", "headline": 3.8, "core": 3.5,
         "momentum": 0.0},
    ])


@pytest.fixture
def sources(monkeypatch):
    history = pd.Series(np.linspace(40, 62, 60), index=SESSIONS[-60:])
    pulse = SimpleNamespace(score=62.4, history=history)
    monkeypatch.setattr(loaders, "pulse_closes", _closes)
    monkeypatch.setattr(loaders, "market_pulse", lambda: pulse)
    monkeypatch.setattr(loaders, "pulse_rate_rows", _rates)
    monkeypatch.setattr(loaders, "inflation", _inflation)
    monkeypatch.setattr(loaders, "crypto_scan", lambda: {
        "global": {"btc_dominance": 57.26},
        "fear_greed": [[f"2026-10-{d:02d}", 30 + d] for d in range(1, 13)],
    })


# ------------------------------------------------------------------- facts


def test_facts_read_every_block(sources):
    f = today_market.facts(DAY)
    assert f["missing"] == []
    assert f["session"] == "2026-10-12"
    assert f["regime"]["key"] == sm.regime_key(62.4)
    months = [s["month"] for s in f["sectors"]]
    assert months == sorted(months, reverse=True)
    assert {r["key"] for r in f["rates"]} == {"us10y", "curve_2s10s", "hy_spread"}
    fed = next(b for b in f["banks"] if b["bank"] == "fed")
    assert fed["rate"] == 4.0 and fed["last_move_bp"] == -25.0
    assert fed["next_date"] and fed["days"] >= 0
    assert [r["area"] for r in f["inflation"]] == ["US", "EA"]
    assert f["crypto"] == {"fear_greed": 42.0, "fear_greed_week": 35.0,
                           "btc_dominance": 57.3}


def test_a_failing_source_drops_only_its_block(sources, monkeypatch):
    def down():
        raise RuntimeError("FRED is down")

    monkeypatch.setattr(loaders, "pulse_rate_rows", down)
    f = today_market.facts(DAY)
    assert "rates" in f["missing"]
    assert "rates" not in f
    assert f["sectors"] and f["regime"]


def test_a_block_missing_today_keeps_yesterdays():
    old = {"rates": [{"key": "us10y", "value": 4.5, "change_bp": 3.0}],
           "session": "2026-10-09"}
    new = {"missing": ["rates"], "session": "2026-10-12", "regime": {}}
    merged = today_market._merged(old, new)
    assert merged["rates"] == old["rates"]
    assert merged["missing"] == [] and merged["kept"] == ["rates"]


# ----------------------------------------------------------------- computed


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_computed_read_covers_every_topic(sources, lang):
    card = today_market.computed(today_market.facts(DAY), lang)
    assert card["source"] == "computed" and card["headline"]
    assert {ln["topic"] for ln in card["lines"]} == set(today_market.TOPICS)
    assert all(ln["line"] for ln in card["lines"])
    rates = next(ln["line"] for ln in card["lines"] if ln["topic"] == "rates")
    assert ("4,90" if lang == "es" else "4.90") in rates


def test_the_computed_read_with_nothing():
    card = today_market.computed({"missing": ["regime"]}, "en")
    assert card["headline"] and card["lines"] == []


# ------------------------------------------------------------------ written


def _reply(headline: str, *lines: tuple[str, str]) -> str:
    return json.dumps({"headline": headline,
                       "lines": [{"topic": t, "line": x} for t, x in lines]})


def test_a_line_with_an_unsourced_figure_is_dropped(sources):
    f = today_market.facts(DAY)
    us10y = next(r for r in f["rates"] if r["key"] == "us10y")
    card = today_market.parse(_reply(
        "Risk appetite holds as yields climb",
        ("rates", f"The US 10-year sits at {us10y['value']:.2f}%."),
        ("trend", "The S&P 500 is above its 200-session average."),
        ("sector", "Tech beat the index by 7.7% this month."),  # not in the facts
    ), f, "en")
    assert card is not None and card["source"] == "llm"
    assert [ln["topic"] for ln in card["lines"]] == ["rates", "trend"]



def test_a_topic_written_as_a_label_is_dropped(sources):
    f = today_market.facts(DAY)
    card = today_market.parse(_reply(
        "Risk appetite holds",
        ("trend", "Trend: risk appetite holds its band."),
        ("macro", "Tipos: la Fed decide pronto."),
        ("rates", "Rates rise: a label only when it is one."),
    ), f, "en")
    assert [ln["line"] for ln in card["lines"]] == [
        "Risk appetite holds its band.",
        "La Fed decide pronto.",
        "Rates rise: a label only when it is one.",
    ]

def test_a_basis_point_move_must_be_one_of_the_facts(sources):
    f = today_market.facts(DAY)
    bp = next(r for r in f["rates"] if r["key"] == "us10y")["change_bp"]
    assert today_market.miss(f"The 10-year rose {bp:.0f} bp in a month.", f) is None
    assert today_market.miss("The 10-year rose 63 pb en un mes.", f) == "63 pb"
    assert today_market.miss("The Fed cut by 25 bp last time.", f) is None


def test_too_few_lines_left_is_a_miss(sources):
    f = today_market.facts(DAY)
    assert today_market.parse(_reply(
        "Quiet day", ("sector", "Energy gained 12.3% on the month.")), f, "en") is None


def test_a_headline_with_an_unsourced_figure_is_a_miss(sources):
    f = today_market.facts(DAY)
    assert today_market.parse(_reply(
        "Stocks jump 9.9%",
        ("trend", "Risk appetite is in its band."),
        ("macro", "The Fed decides soon."),
    ), f, "en") is None


def test_off_contract_is_a_miss(sources):
    assert today_market.parse("no json here", today_market.facts(DAY), "en") is None


def test_the_write_spends_the_global_pot_only(sources, monkeypatch):
    seen = {}

    def attempts(prefs, system, messages, timeout_s, *, spend_free, accept=None):
        seen.update(prefs=prefs, spend=spend_free, system=system)
        return None

    monkeypatch.setattr(engine, "complete_attempts", attempts)
    card = today_market.write(today_market.facts(DAY), "es")
    assert seen["prefs"] == {} and seen["spend"] is engine.spend_free_global
    assert "Spanish" in seen["system"] and "decimal comma" in seen["system"]
    assert card["source"] == "computed"


def test_a_written_read_stands(sources, monkeypatch):
    def attempts(prefs, system, messages, timeout_s, *, spend_free, accept=None):
        return accept(_reply(
            "Appetite holds", ("trend", "Risk appetite is in its band."),
            ("macro", "The ECB decides soon.")))

    monkeypatch.setattr(engine, "complete_attempts", attempts)
    card = today_market.write(today_market.facts(DAY), "en")
    assert card["source"] == "llm" and card["headline"] == "Appetite holds"


# -------------------------------------------------------------------- store


def test_run_saves_both_languages_stamped_by_session(sources, monkeypatch):
    monkeypatch.setattr(engine, "complete_attempts", lambda *a, **k: None)
    status = today_market.run(DAY)
    stored = today_market.load(restore=False)
    assert status["es"] == status["en"] == "computed"
    assert stored["session"] == "2026-10-12"
    assert set(stored["cards"]) == {"es", "en"}
    card = today_market.card(stored, "es")
    assert card["session"] == "2026-10-12" and card["sectors"]


def test_a_new_language_reuses_the_stored_facts(sources, monkeypatch):
    monkeypatch.setattr(engine, "complete_attempts", lambda *a, **k: None)
    today_market.run(DAY, ("es",))
    before = today_market.load(restore=False)

    def no_fetch(day):
        raise AssertionError("refetch=False must not fetch")

    monkeypatch.setattr(today_market, "facts", no_fetch)
    today_market.run(DAY, ("en",), refetch=False)
    after = today_market.load(restore=False)
    assert set(after["cards"]) == {"es", "en"}
    assert after["built_at"] == before["built_at"]


def test_dry_run_writes_nothing(sources, monkeypatch):
    monkeypatch.setattr(engine, "complete_attempts", lambda *a, **k: None)
    status = today_market.run(DAY, ("en",), dry_run=True)
    assert "dry_run" in status and not today_market.FILE.exists()


def test_a_bucket_that_will_not_take_it_is_swallowed(sources, monkeypatch):
    monkeypatch.setattr(engine, "complete_attempts", lambda *a, **k: None)
    monkeypatch.setattr(storage, "enabled", lambda: True)
    monkeypatch.setattr(storage, "restore", lambda path: False)

    def refuse(path):
        raise OSError("bucket down")

    monkeypatch.setattr(storage, "persist", refuse)
    today_market.run(DAY, ("en",))
    assert today_market.load(restore=False)["cards"]["en"]


def test_an_unreadable_file_loads_as_none():
    today_market.FILE.write_text("{not json")
    assert today_market.load(restore=False) == {}


# -------------------------------------------------------------- freshness


@pytest.mark.parametrize(("now", "session"), [
    (datetime(2026, 10, 13, 6, 30, tzinfo=UTC), "2026-10-12"),  # Tue cron: Mon
    (datetime(2026, 10, 13, 22, 30, tzinfo=UTC), "2026-10-13"),  # Tue evening
    (datetime(2026, 10, 17, 6, 30, tzinfo=UTC), "2026-10-16"),  # Sat cron: Fri
    (datetime(2026, 10, 19, 9, 0, tzinfo=UTC), "2026-10-16"),  # Mon morning: Fri
])
def test_the_expected_session(now, session):
    assert today_market.expected_session(now) == session


def test_stale():
    now = 1_000_000.0
    fresh = {"session": "2026-10-12", "built_at": now - 3600}
    assert not today_market.stale(fresh, "2026-10-12", now)
    assert today_market.stale(fresh, "2026-10-13", now)
    assert today_market.stale({}, "2026-10-12", now)
    old = {"session": "2026-10-12", "built_at": now - today_market.STALE_AFTER_S - 1}
    assert today_market.stale(old, "2026-10-12", now)
