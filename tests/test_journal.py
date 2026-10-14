"""The decision journal (`chat/journal.py`) and the ways it is read.

What is pinned: a proposal shown again is the same entry, once a day; a
different proposal about the same thing replaces it and the two are linked;
the Review page withdrawing a verdict lapses it, while a name it could not
rate does not; nothing is written for the guest. Then the readers: the HTTP
route, the chat tool and the connector's.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.chat import journal, toolbox

DAY = date(2026, 10, 1)
TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _no_bucket(monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "decisions.json"


def _shown(subject="review:AMD", action="sell", **kw):
    return journal.Shown(source=kw.pop("source", "review"), subject=subject,
                         action=action, ticker=kw.pop("ticker", "AMD"), **kw)


def _row(ticker, verdict, **kw):
    fields = {"quality": 40.0, "cheapness": 20.0, "weight": 0.15,
              "target_weight": 0.0, "pnl_pct": 0.5, "value": 1500.0,
              "held": True, "reasons": ["weak_quality"]}
    return SimpleNamespace(ticker=ticker, verdict=verdict, **{**fields, **kw})


# -------------------------------------------------------------------- store


def test_a_proposal_shown_again_is_one_entry_counted_once_a_day(path):
    assert journal.record(path, [_shown(line="Vende AMD")], DAY) == 1
    assert journal.record(path, [_shown()], DAY) == 0
    assert journal.record(path, [_shown()], DAY + timedelta(days=2)) == 1
    [entry] = journal.load(path)
    assert (entry.day, entry.last, entry.times) == ("2026-10-01", "2026-10-03", 2)
    assert entry.state == "open" and entry.line == "Vende AMD"


def test_a_new_action_on_the_same_subject_replaces_and_links(path):
    journal.record(path, [_shown(action="trim")], DAY)
    journal.record(path, [_shown(action="sell")], DAY + timedelta(days=1))
    old, new = journal.load(path)
    assert (old.action, old.state) == ("trim", "lapsed")
    assert (new.action, new.state) == ("sell", "open")
    assert old.links == (new.id,) and new.links == (old.id,)


def test_a_verdict_withdrawn_lapses_but_an_unrated_name_does_not(path):
    journal.record(path, journal.from_review([_row("AMD", "sell"),
                                              _row("SNAP", "trim")]), DAY)
    rows = [_row("AMD", "hold"), _row("SNAP", "unrated")]
    journal.record(path, journal.from_review(rows), DAY + timedelta(days=1),
                   judged=journal.judged_in_review(rows))
    states = {e.ticker: e.state for e in journal.load(path)}
    assert states == {"AMD": "lapsed", "SNAP": "open"}


def test_what_is_not_shown_for_lapse_days_lapses(path):
    journal.record(path, [_shown(source="daily", subject="harvest:ADBE",
                                 action="harvest", ticker="ADBE")], DAY)
    later = DAY + timedelta(days=journal.LAPSE_DAYS + 1)
    assert journal.record(path, [], later) == 1
    assert journal.load(path)[0].state == "lapsed"


def test_the_review_keeps_the_figures_it_judged_on(path):
    journal.record(path, journal.from_review([_row("AMD", "sell"),
                                              _row("BKNG", "pass")]), DAY)
    [entry] = journal.load(path)
    assert entry.reasons == ("weak_quality",)
    assert entry.snapshot["weight"] == 0.15 and entry.snapshot["verdict"] == "sell"


def test_a_review_that_moves_nothing_is_one_stay_on_the_book(path):
    rows = [_row("AMD", "hold"), _row("ADBE", "hold")]
    journal.record(path, [journal.stay_in_review(10_000.0, "EUR")], DAY,
                   judged=journal.judged_in_review(rows))
    [stay] = journal.load(path)
    assert (stay.action, stay.subject, stay.ticker) == ("stay", "review:book", "")
    # The next plan that moves something withdraws it.
    rows = [_row("AMD", "sell"), _row("ADBE", "hold")]
    journal.record(path, journal.from_review(rows), DAY + timedelta(days=1),
                   judged=journal.judged_in_review(rows))
    states = {e.action: e.state for e in journal.load(path)}
    assert states == {"stay": "lapsed", "sell": "open"}


def test_the_review_reads_back_the_moves_it_still_proposes(path):
    journal.record(path, journal.from_review([_row("AMD", "sell"),
                                              _row("adbe", "add")]), DAY)
    journal.record(path, [journal.stay_in_review(1.0, "EUR")], DAY)
    journal.record(path, [_shown(source="daily", subject="harvest:SNAP",
                                 action="harvest", ticker="SNAP")], DAY)
    assert journal.open_in_review(path) == {"AMD": "sell", "ADBE": "add"}
    rows = [_row("AMD", "hold")]
    journal.record(path, [], DAY + timedelta(days=1),
                   judged=journal.judged_in_review(rows))
    assert journal.open_in_review(path) == {"ADBE": "add"}


def test_card_lines_that_propose_nothing_are_not_recorded(path):
    items = [
        {"key": "harvest:ADBE", "kind": "harvest", "line": "Vende ADBE",
         "tickers": ["ADBE"]},
        {"key": "earnings:NVDA", "kind": "earnings", "line": "NVDA publica",
         "tickers": ["NVDA"]},
    ]
    facts = {"actions": [{"key": "harvest:ADBE", "ticker": "ADBE",
                          "loss": -500.0, "rows": [1, 2]}]}
    [shown] = journal.from_card(items, facts)
    assert (shown.subject, shown.action, shown.ticker) == (
        "harvest:ADBE", "harvest", "ADBE")
    journal.record(path, [shown], DAY)
    # Scalars only: nested facts are the evidence, not the snapshot.
    assert journal.load(path)[0].snapshot == {"loss": -500.0}


def test_a_chat_answer_is_recorded_settled(path):
    offer = {"id": "p1", "kind": "set_alerts", "ticker": "NVDA",
             "args": {"below": 100.0, "rules": [{"x": 1}]}, "state": "done"}
    shown = journal.from_chat(offer, "¿Pongo una alerta en NVDA a 100?")
    journal.settle(path, shown, "followed", DAY)
    [entry] = journal.load(path)
    assert (entry.source, entry.action, entry.state) == ("chat", "alert", "followed")
    assert entry.snapshot == {"below": 100.0}
    # Bookkeeping proposals are not decisions.
    assert journal.from_chat({"id": "p2", "kind": "add_transactions"}, "") is None


def test_the_engine_journals_approve_and_cancel(tmp_path):
    from stocks.chat import engine

    chat = tmp_path / "chat.json"
    engine._journal({"id": "p1", "kind": "add_ticker", "ticker": "ASML",
                     "state": "cancelled"}, chat, "¿Sigo ASML?")
    engine._journal({"id": "p2", "kind": "add_ticker", "ticker": "TSM",
                     "state": "pending"}, chat, "¿Sigo TSM?")
    [entry] = journal.load(journal.path_for(chat))
    assert (entry.ticker, entry.state) == ("ASML", "declined")


def test_attach_keeps_the_analysis_on_the_open_entry(path):
    journal.record(path, [_shown(source="daily", subject="harvest:ADBE",
                                 action="harvest", ticker="ADBE")], DAY)
    assert journal.attach(path, "daily", "harvest:ADBE", "Pérdida deducible")
    assert not journal.attach(path, "daily", "harvest:ADBE", "Pérdida deducible")
    assert not journal.attach(path, "daily", "missing", "x")
    assert journal.load(path)[0].evidence == "Pérdida deducible"


def test_nothing_is_written_for_the_guest(monkeypatch, tmp_path):
    guest = tmp_path / "_guest"
    monkeypatch.setattr(accounts, "GUEST_DIR", guest)
    target = guest / journal.FILE
    assert journal.safely(journal.record, target, [_shown()], DAY) is None
    assert not target.exists()


def test_a_failed_write_never_reaches_the_surface(monkeypatch, path):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(journal, "_save", boom)
    assert journal.safely(journal.record, path, [_shown()], DAY) is None


def test_settled_entries_are_pruned_first(monkeypatch, path):
    monkeypatch.setattr(journal, "MAX_ENTRIES", 2)
    journal.settle(path, _shown(subject="a", source="chat"), "declined", DAY)
    journal.record(path, [_shown(subject="b"), _shown(subject="c")], DAY)
    assert sorted(e.subject for e in journal.load(path)) == ["b", "c"]


def test_the_account_carries_and_syncs_its_journal(tmp_path):
    paths = accounts.paths_for(EMAIL, None, users_dir=tmp_path)
    assert paths.journal == paths.chat.with_name("decisions.json")
    assert journal.FILE in accounts.USER_FILES


def test_query_matches_a_ticker_across_exchanges(path):
    journal.record(path, [_shown(subject="review:ASML.AS", ticker="ASML.AS"),
                          _shown(subject="review:AMD")], DAY)
    found = journal.query(journal.load(path), ticker="asml")
    assert [e.ticker for e in found] == ["ASML.AS"]
    assert journal.query(journal.load(path), state="lapsed") == []


# ------------------------------------------------------------------ readers


@pytest.fixture
def book(monkeypatch, tmp_path):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AMD\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(accounts, "paths_for",
                        lambda email, owner=None, users_dir=users: paths)
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    journal.record(paths.journal, [_shown(action="trim")], DAY)
    journal.record(paths.journal, [_shown(action="sell"),
                                   _shown(subject="review:SNAP", ticker="SNAP",
                                          action="trim")],
                   DAY + timedelta(days=1))
    return paths


def test_the_route_lists_newest_first_with_state_counts(book):
    client = TestClient(fastapi_app)
    body = client.get("/v1/journal", params={"account": EMAIL, "ticker": "AMD"},
                      headers=AUTH).json()
    assert [(e["action"], e["state"]) for e in body["entries"]] == [
        ("sell", "open"), ("trim", "lapsed")]
    assert body["states"] == {"open": 1, "followed": 0, "declined": 0, "lapsed": 1}
    only = client.get("/v1/journal", params={"account": EMAIL, "state": "open"},
                      headers=AUTH).json()
    assert only["total"] == 2
    assert {e["ticker"] for e in only["entries"]} == {"AMD", "SNAP"}
    assert client.get("/v1/journal", params={"account": EMAIL, "since": "ayer"},
                      headers=AUTH).status_code == 422


def test_the_chat_tool_reads_it_and_is_offered_only_with_an_account(book):
    ctx = toolbox.Context(journal=book.journal)
    _, handler = toolbox.TOOLS["decisions"]
    out = handler({"ticker": "AMD"}, ctx)
    assert "review · sell AMD · open" in out and "lapsed" in out
    assert "decisions" in {s.name for s in toolbox.specs(ctx)}
    assert "decisions" not in {s.name for s in toolbox.specs(toolbox.Context())}
    assert "Nothing" in handler({"ticker": "NVDA"}, ctx)
