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
from pathlib import Path
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
    assert body["states"] == {"open": 1, "followed": 0, "declined": 0, "lapsed": 1,
                              "hit": 0, "retired": 0}
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


# ------------------------------------------------------------- the ledger


def _trade(day, ticker, action, qty=10.0, price=100.0):
    from stocks.portfolio.ledger import Transaction

    return Transaction(date=day.isoformat(), ticker=ticker, action=action,
                       quantity=qty, price=price)


def test_a_sale_in_the_book_settles_a_sell_proposal(path):
    # The reader is never asked whether they took a proposal: the book says.
    journal.record(path, [_shown(action="sell"),
                          _shown(subject="review:ADBE", ticker="ADBE", action="add"),
                          _shown(subject="review:SNAP", ticker="SNAP", action="trim")],
                   DAY)
    trades = [
        _trade(DAY + timedelta(days=5), "AMD", "sell"),      # takes the sell
        _trade(DAY + timedelta(days=2), "ADBE", "sell"),     # wrong side for an add
        _trade(DAY - timedelta(days=1), "SNAP", "sell"),     # before it was proposed
    ]
    assert journal.settle_from_ledger(path, trades, DAY + timedelta(days=6)) == 1
    by = {e.ticker: e for e in journal.load(path)}
    assert by["AMD"].state == "followed" and by["AMD"].settled == "ledger:2026-10-06"
    assert by["ADBE"].state == "open" and by["SNAP"].state == "open"
    # The same trades again change nothing: followed stands.
    assert journal.settle_from_ledger(path, trades, DAY + timedelta(days=6)) == 0


def test_a_trade_too_long_after_the_last_showing_does_not_count(path):
    journal.record(path, [_shown(action="sell")], DAY)
    late = DAY + timedelta(days=journal.SETTLE_DAYS + 1)
    assert journal.settle_from_ledger(path, [_trade(late, "AMD", "sell")], late) == 0
    assert journal.load(path)[0].state == "open"


def test_a_lapsed_proposal_settles_and_names_match_across_venues(path):
    # A name sold is never judged again, so its sell lapses before anyone
    # looks; the sale still answers it. ASML on screen, ASML.AS in the book.
    journal.record(path, [_shown(subject="review:ASML", ticker="ASML", action="sell")],
                   DAY)
    journal.record(path, [], DAY + timedelta(days=journal.LAPSE_DAYS + 1))
    assert journal.load(path)[0].state == "lapsed"
    sale = _trade(DAY + timedelta(days=3), "ASML.AS", "sell")
    assert journal.settle_from_ledger(path, [sale], DAY + timedelta(days=40)) == 1
    assert journal.load(path)[0].state == "followed"


def test_a_declined_proposal_is_not_reopened_by_a_trade(path):
    journal.settle(path, _shown(source="chat", subject="p1", action="unwatch"),
                   "declined", DAY)
    journal.settle(path, _shown(source="chat", subject="p2", action="buy"),
                   "declined", DAY)
    bought = _trade(DAY + timedelta(days=1), "AMD", "buy")
    assert journal.settle_from_ledger(path, [bought], DAY + timedelta(days=2)) == 0
    assert {e.state for e in journal.load(path)} == {"declined"}
    assert {e.settled for e in journal.load(path)} == {"chat"}


def test_settle_from_db_reads_the_book_only_when_something_could_settle(
        monkeypatch, path, tmp_path):
    from stocks.portfolio import ledger

    db = tmp_path / "portfolio.db"
    ledger.add(_trade(DAY + timedelta(days=2), "AMD", "sell"), path=db)
    reads: list[Path] = []
    real = ledger.all_transactions
    monkeypatch.setattr(ledger, "all_transactions",
                        lambda p: reads.append(p) or real(p))
    # An alert has no trade that would mean "done": the book is not opened.
    journal.record(path, [_shown(source="daily", subject="alert_hit:AMD",
                                 action="alert")], DAY)
    assert journal.settle_from_db(path, db, DAY + timedelta(days=3)) == 0
    assert reads == []
    journal.record(path, [_shown(action="sell")], DAY)
    assert journal.settle_from_db(path, db, DAY + timedelta(days=3)) == 1
    assert reads == [db]
    assert journal.settle_from_db(path, tmp_path / "missing.db", DAY) == 0


# ------------------------------------------------------------- the record


def test_track_record_counts_what_became_of_the_proposals(path):
    journal.record(path, [_shown(action="sell"),
                          _shown(subject="review:SNAP", ticker="SNAP", action="trim"),
                          journal.stay_in_review(1000.0, "EUR")], DAY)
    journal.settle(path, _shown(source="chat", subject="p1", action="watch"),
                   "declined", DAY)
    journal.settle_from_ledger(path, [_trade(DAY + timedelta(days=1), "AMD", "sell")],
                               DAY + timedelta(days=1))
    record = journal.track_record(journal.load(path))
    # The stay is advice to do nothing, not a move made.
    assert {k: record[k] for k in ("proposed", "open", "followed", "declined",
                                   "lapsed")} == {
        "proposed": 3, "open": 1, "followed": 1, "declined": 1, "lapsed": 0}
    assert record["by_source"]["review"]["proposed"] == 2
    assert record["by_source"]["chat"]["declined"] == 1


def test_history_lines_say_what_was_proposed_and_what_came_of_it(path):
    journal.record(path, [_shown(action="sell"),
                          _shown(subject="review:SNAP", ticker="SNAP", action="trim")],
                   DAY)
    journal.settle_from_ledger(path, [_trade(DAY + timedelta(days=4), "AMD.US", "sell")],
                               DAY + timedelta(days=4))
    journal.settle(path, journal.Shown(source="chat", subject="p9", action="watch",
                                       ticker="NVDA"),
                   "declined", DAY + timedelta(days=2))
    # Shown for the first time today: not history yet.
    journal.record(path, [_shown(subject="review:ADBE", ticker="ADBE", action="add")],
                   DAY + timedelta(days=5))
    lines = journal.history_for(path, ["amd", "NVDA", "ADBE.DE", "SNAP"],
                                DAY + timedelta(days=5))
    # Newest showing first; ADBE is shown for the first time today.
    assert lines == [
        "NVDA: watch (chat, 2026-10-03) · the user declined",
        "AMD: sell (review, 2026-10-01) · the user did it (trade on 2026-10-05)",
        "SNAP: trim (review, 2026-10-01) · still open",
    ]
    assert journal.history_for(path, [], DAY) == []
    # Older than HISTORY_DAYS is forgotten.
    assert journal.history_for(path, ["AMD"],
                               DAY + timedelta(days=journal.HISTORY_DAYS + 10)) == []


def test_the_chat_proposal_tool_reads_what_was_proposed_before(path):
    journal.settle(path, journal.Shown(source="chat", subject="p1", action="watch",
                                       ticker="ASML"), "declined", DAY)
    note = toolbox._proposed_before(toolbox.Context(journal=path), "ASML.AS")
    assert "ASML: watch (chat, 2026-10-01) · the user declined" in note
    assert "not pressed again" in note
    assert toolbox._proposed_before(toolbox.Context(), "ASML") == ""
    assert toolbox._proposed_before(toolbox.Context(journal=path), "NVDA") == ""


# ------------------------------------------------------------- the export


def test_to_markdown_is_one_obsidian_file(path):
    journal.record(path, [_shown(action="trim")], DAY)
    journal.record(path, [_shown(action="sell", line="Sell AMD: margins keep falling.",
                                 reasons=("weak_quality",),
                                 snapshot={"quality": 40.0, "cheapness": 20.0})],
                   DAY + timedelta(days=1))
    journal.attach(path, "review", "review:AMD", "Margins fell two quarters running.")
    journal.settle_from_ledger(path, [_trade(DAY + timedelta(days=3), "AMD", "sell")],
                               DAY + timedelta(days=3))
    sell, trim = journal.load(path)[1], journal.load(path)[0]
    text = journal.to_markdown(journal.load(path), DAY + timedelta(days=4))
    assert text.startswith("---\ntitle: Decision journal\nexported: 2026-10-05\n"
                           "entries: 2\n---\n")
    # One sale answers both the trim and the sell that replaced it.
    assert "Proposed 2 · followed 2 · declined 0 · lapsed 0 · open 0" in text
    assert "> Sell AMD: margins keep falling." in text
    # Newest first; each entry a section with its block id, tags and links.
    assert text.index(f"^{sell.id}") < text.index(f"^{trim.id}")
    assert "## 2026-10-02 · review · sell AMD · followed" in text
    assert "#ticker/AMD #state/followed #source/review #move/sell" in text
    assert "- **State:** followed (trade on 2026-10-04)" in text
    assert "- **Why:** weak_quality" in text
    assert "- **Figures then:** quality 40.0, cheapness 20.0" in text
    assert "- **Analysis:** Margins fell two quarters running." in text
    assert f"- **Linked:** [[decisions#^{trim.id}]]" in text
    assert journal.to_markdown([], DAY).endswith("open 0\n")


def test_the_route_exports_the_file_and_counts_the_record(book):
    client = TestClient(fastapi_app)
    body = client.get("/v1/journal", params={"account": EMAIL}, headers=AUTH).json()
    assert body["record"]["proposed"] == 3 and body["record"]["lapsed"] == 1
    assert body["entries"][0]["settled"] == ""
    got = client.get("/v1/journal.md", params={"account": EMAIL}, headers=AUTH)
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("text/markdown")
    disposition = got.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="decisions-')
    assert "## 2026-10-02 · review · sell AMD · open" in got.text


# ------------------------------------------------------------- the outcome


class _Closes:
    """`journal.ClosesOn` off a table of {day: close}; logs every ask."""

    def __init__(self, table: dict[date, float], fail: bool = False):
        self.table, self.fail, self.asked = table, fail, []

    def __call__(self, ticker: str, days: list[date]) -> list[float | None]:
        self.asked.append((ticker, list(days)))
        if self.fail:
            raise TimeoutError("throttled")
        return [self.table.get(d) for d in days]


def test_the_price_is_read_back_a_month_and_a_quarter_on(path):
    journal.record(path, [_shown(action="sell"),
                          _shown(source="daily", subject="alert_hit:AMD",
                                 action="alert")], DAY)
    closes = _Closes({DAY: 100.0, DAY + timedelta(days=30): 88.0,
                      DAY + timedelta(days=90): 120.0})
    # Not due yet: nothing is fetched.
    assert journal.mark_outcomes(path, closes, DAY + timedelta(days=29)) == 0
    assert closes.asked == []
    assert journal.mark_outcomes(path, closes, DAY + timedelta(days=31)) == 1
    sell = journal.load(path)[0]
    assert sell.outcome == {"then": 100.0, "d30": -12.0}
    assert journal.went_its_way(sell) is True
    # An alert bets on no direction and is never priced.
    assert journal.load(path)[1].outcome == {}
    # The quarter mark asks for the quarter only, from the close kept.
    assert journal.mark_outcomes(path, closes, DAY + timedelta(days=95)) == 1
    assert closes.asked[-1] == ("AMD", [DAY, DAY + timedelta(days=90)])
    sell = journal.load(path)[0]
    assert sell.outcome == {"then": 100.0, "d30": -12.0, "d90": 20.0}
    assert journal.went_its_way(sell) is False
    assert journal.since_line(sell) == "−12.0 % 30 days on, +20.0 % 90 days on"
    assert journal.mark_outcomes(path, closes, DAY + timedelta(days=200)) == 0


def test_a_price_that_cannot_be_read_stays_due(path):
    journal.record(path, [_shown(subject="review:ADBE", ticker="ADBE", action="add")],
                   DAY)
    later = DAY + timedelta(days=31)
    assert journal.mark_outcomes(path, _Closes({}, fail=True), later) == 0
    assert journal.mark_outcomes(path, _Closes({}), later) == 0  # no close yet
    assert journal.load(path)[0].outcome == {}
    closes = _Closes({DAY: 50.0, DAY + timedelta(days=30): 55.0})
    assert journal.mark_outcomes(path, closes, later) == 1
    add = journal.load(path)[0]
    assert add.outcome == {"then": 50.0, "d30": 10.0}
    assert journal.went_its_way(add) is True


def test_one_pass_prices_a_bounded_number_of_names(path, monkeypatch):
    monkeypatch.setattr(journal, "MAX_MARKED", 2)
    journal.record(path, [_shown(subject=f"review:T{i}", ticker=f"T{i}", action="sell")
                          for i in range(4)], DAY)
    closes = _Closes({DAY: 10.0, DAY + timedelta(days=30): 9.0})
    assert journal.mark_outcomes(path, closes, DAY + timedelta(days=31)) == 2
    assert journal.mark_outcomes(path, closes, DAY + timedelta(days=31)) == 2
    assert all(e.outcome for e in journal.load(path))


def test_the_record_and_the_lines_carry_the_price_since(path):
    journal.record(path, [_shown(action="sell"),
                          _shown(subject="review:SNAP", ticker="SNAP", action="trim"),
                          _shown(subject="review:ADBE", ticker="ADBE", action="add")],
                   DAY)
    month = DAY + timedelta(days=30)
    table = {"AMD": {DAY: 100.0, month: 90.0}, "SNAP": {DAY: 10.0, month: 11.0}}

    def closes(ticker, days):
        return [table.get(ticker, {}).get(d) for d in days]

    journal.mark_outcomes(path, closes, DAY + timedelta(days=31))
    record = journal.track_record(journal.load(path))
    # AMD fell after a sell, SNAP rose after a trim, ADBE has no price yet.
    assert (record["marked"], record["its_way"]) == (2, 1)
    assert record["by_source"]["review"]["marked"] == 2
    amd = journal.load(path)[0]
    assert journal.history_line(amd).endswith("· still open · price −10.0 % 30 days on")
    assert "  price since: −10.0 % 30 days on" in journal.line_for(amd)
    text = journal.to_markdown(journal.load(path), DAY + timedelta(days=31))
    assert "· went its way 1 of 2 priced" in text
    assert "- **Price since:** −10.0 % 30 days on (close 100 on 2026-10-01)" in text


def test_the_route_returns_the_outcome(book):
    client = TestClient(fastapi_app)
    body = client.get("/v1/journal", params={"account": EMAIL}, headers=AUTH).json()
    assert body["entries"][0]["outcome"] == {}
    assert body["record"]["marked"] == 0 and body["record"]["its_way"] == 0


def test_the_card_job_reads_closes_off_the_window_download(monkeypatch):
    import pandas as pd

    from stocks.api import briefing, loaders

    asked = []

    def window(ticker, days):
        asked.append((ticker, days))
        return pd.Series([float("nan"), 12.5], index=pd.DatetimeIndex(days.split(",")))

    monkeypatch.setattr(loaders, "window_closes", window)
    got = briefing._closes_on("AMD", [DAY, DAY + timedelta(days=30)])
    assert got == [None, 12.5]
    assert asked == [("AMD", "2026-10-01,2026-10-31")]
    monkeypatch.setattr(loaders, "window_closes", lambda t, d: pd.Series(dtype=float))
    assert briefing._closes_on("AMD", [DAY]) == [None]


# ----------------------------------------------------------------- criteria


def test_rules_are_cleaned_before_they_are_kept():
    assert journal.clean_rules([
        {"rule": "below", "level": "95,5"},
        {"rule": "drawdown_cost", "level": "30%"},
        {"rule": "drawdown_cost", "level": 25},   # the last one per rule wins
        {"rule": "weight_above", "level": 120},   # no weight past 100 %
        {"rule": "below", "level": -3},           # overwritten by nothing: dropped
        {"rule": "moon", "level": 5},
        "not a rule",
    ]) == [{"rule": "below", "level": 95.5}, {"rule": "drawdown_cost", "level": 25.0}]


def test_a_new_rule_retires_the_old_one_and_links_both(path):
    [old] = journal.add_criteria(path, "nvda", [{"rule": "below", "level": 100}],
                                 DAY, thesis="AI capex leader")
    [new] = journal.add_criteria(path, "NVDA", [{"rule": "below", "level": 90}],
                                 DAY + timedelta(days=1))
    saved = {e.id: e for e in journal.load(path)}
    assert saved[old.id].state == "retired" and new.id in saved[old.id].links
    assert saved[new.id].state == "open" and old.id in saved[new.id].links
    assert old.evidence == "AI capex leader" and old.ticker == "NVDA"
    assert [e.id for e in journal.criteria(journal.load(path))] == [new.id]
    assert journal.add_criteria(path, "NVDA", [{"rule": "moon", "level": 1}], DAY) == []


def test_criteria_never_lapse_and_survive_the_proposal_bookkeeping(path):
    [rule] = journal.add_criteria(path, "AMD", [{"rule": "drawdown_cost", "level": 30}],
                                  DAY)
    # A Review run that no longer names AMD lapses its proposals, never a rule.
    journal.record(path, [_shown(subject="review:SNAP", ticker="SNAP")],
                   DAY + timedelta(days=60))
    assert {e.id: e.state for e in journal.load(path)}[rule.id] == "open"


def test_each_rule_reads_its_own_figure():
    import pandas as pd

    tbl = pd.DataFrame({"pnl_pct": [-0.32], "weight": [0.21]}, index=["AMD"])
    row = journal._row(tbl, "AMD")
    prices = [100.0, 120.0, 90.0]
    assert journal.measure_rule("below", 95, prices, row) == (90.0, -5.26, True)
    assert journal.measure_rule("drawdown_high", 20, prices, row) == (-25.0, -5.0, True)
    assert journal.measure_rule("drawdown_cost", 40, prices, row) == (-32.0, 8.0, False)
    assert journal.measure_rule("weight_above", 20, prices, row) == (21.0, -1.0, True)
    # A figure missing today is not judged at all.
    assert journal.measure_rule("drawdown_cost", 40, prices, None) is None
    assert journal.measure_rule("below", 95, [], row) is None


def test_a_met_rule_is_marked_hit_once_and_keeps_its_first_day(path):
    journal.add_criteria(path, "AMD", [{"rule": "below", "level": 95}], DAY)
    closes = {"AMD": [100.0, 90.0]}
    rows = journal.mark_hit(path, journal.measured(journal.load(path), closes, None),
                            DAY + timedelta(days=1))
    assert rows[0]["state"] == "hit" and rows[0]["hit_day"] == "2026-10-02"
    later = journal.mark_hit(path, journal.measured(journal.load(path), closes, None),
                             DAY + timedelta(days=5))
    assert later[0]["hit_day"] == "2026-10-02"
    [entry] = journal.load(path)
    assert entry.state == "hit" and entry.snapshot["hit_value"] == 90.0


def test_retire_takes_down_only_a_live_rule(path):
    [rule] = journal.add_criteria(path, "AMD", [{"rule": "below", "level": 95}], DAY)
    journal.record(path, [_shown()], DAY)
    proposal = next(e for e in journal.load(path) if e.type == "proposal")
    assert journal.retire(path, proposal.id) is None
    assert journal.retire(path, rule.id).state == "retired"
    assert journal.retire(path, rule.id) is None
    assert journal.criteria(journal.load(path)) == []


def test_a_rule_reads_as_a_journal_line(path):
    [rule] = journal.add_criteria(path, "AMD", [{"rule": "drawdown_high", "level": 25}],
                                  DAY, thesis="Data-centre share gains")
    line = journal.line_for(rule)
    assert "exit rule AMD" in line and "25%" in line and "Data-centre" in line


def test_the_route_retires_a_rule_for_a_writer(book, sign_in):
    [rule] = journal.add_criteria(book.journal, "AMD", [{"rule": "below", "level": 95}],
                                  DAY)
    url = f"/v1/journal/criteria/{rule.id}"
    # A token reads the journal but never writes it.
    refused = TestClient(fastapi_app).delete(url, params={"account": EMAIL}, headers=AUTH)
    assert refused.status_code == 403
    session = sign_in(TestClient(fastapi_app), EMAIL)
    assert session.delete(url).status_code == 204
    assert session.delete(url).status_code == 404
    assert session.delete("/v1/journal/criteria/not a path").status_code in (404, 422)
    body = TestClient(fastapi_app).get(
        "/v1/journal", params={"account": EMAIL, "state": "retired"}, headers=AUTH).json()
    assert [e["id"] for e in body["entries"]] == [rule.id]


def test_the_chat_prompt_carries_the_live_rules(tmp_path):
    from stocks.chat import engine

    chat = tmp_path / "chat.json"
    assert engine.criteria_block(chat) == ""
    journal.add_criteria(journal.path_for(chat), "AMD",
                         [{"rule": "below", "level": 95}], DAY, thesis="Share gains")
    block = engine.criteria_block(chat)
    assert "exit rules" in block and "AMD" in block and "Share gains" in block


# ---------------------------------------------------------------- slow rules


def _quarters(*rows):
    """Quarters newest first from (end, revenue, gross_profit, operating_income)."""
    from stocks.data.earnings import Quarter

    return [Quarter(end=date.fromisoformat(end), revenue=rev, gross_profit=gp,
                    operating_income=op) for end, rev, gp, op in rows]


BOOK = _quarters(
    ("2026-09-30", 100.0, 38.0, 12.0),
    ("2026-06-30", 100.0, 39.0, 14.0),
    ("2026-03-31", 100.0, 45.0, 20.0),
    ("2025-12-31", 100.0, 45.0, 20.0),
    ("2025-09-30", 95.0, 44.0, 19.0),
)


def test_fundamental_and_event_rules_are_cleaned_too():
    assert journal.clean_rules([
        {"rule": "operating_margin_below", "level": "15", "quarters": 9},
        {"rule": "revenue_growth_below", "level": -5},        # shrinking is a level
        {"rule": "gross_margin_below", "level": 140},         # no margin past 100 %
        {"rule": "ceo_change", "level": 3},                   # an event has no level
    ]) == [
        {"rule": "operating_margin_below", "level": 15.0, "quarters": 4},
        {"rule": "revenue_growth_below", "level": -5.0, "quarters": 1},
        {"rule": "ceo_change"},
    ]


def test_a_fundamental_rule_needs_every_quarter_of_its_run_under_the_line():
    one = journal.measure_fundamental("gross_margin_below", 40, 1, BOOK)
    assert one == {"value": 38.0, "gap": -2.0, "met": True, "quarter_end": "2026-09-30"}
    assert journal.measure_fundamental("gross_margin_below", 40, 2, BOOK)["met"]
    assert not journal.measure_fundamental("gross_margin_below", 40, 3, BOOK)["met"]
    growth = journal.measure_fundamental("revenue_growth_below", 10, 1, BOOK)
    assert growth["value"] == pytest.approx(5.26, abs=0.01) and growth["met"]
    # A quarter without its year-ago twin cannot be judged at all.
    assert journal.measure_fundamental("revenue_growth_below", 10, 2, BOOK) is None
    assert journal.measure_fundamental("gross_margin_below", 40, 9, BOOK) is None


def _no_passages(ticker, since):
    raise AssertionError("no event rule here")


def _no_judge(rule, ticker, passages):
    raise AssertionError("nothing to judge")


def test_a_fundamental_rule_is_read_once_per_new_quarter(path):
    [rule] = journal.add_criteria(
        path, "AMD", [{"rule": "operating_margin_below", "level": 15, "quarters": 2}],
        DAY)
    asked = []

    def quarters_of(ticker):
        asked.append(ticker)
        return BOOK

    day = date(2026, 10, 30)
    fired = journal.check_slow(path, day, quarters_of=quarters_of,
                               passages_of=_no_passages, judge=_no_judge)
    assert [(r["id"], r["value"], r["quarters"]) for r in fired] == [(rule.id, 12.0, 2)]
    [entry] = journal.load(path)
    assert entry.state == "hit" and entry.snapshot["hit_value"] == 12.0
    assert entry.snapshot["quarter_end"] == "2026-09-30"
    # Met once: never read again, and the card reads it back from the snapshot.
    assert journal.check_slow(path, day + timedelta(days=100), quarters_of=quarters_of,
                              passages_of=_no_passages, judge=_no_judge) == []
    assert asked == ["AMD"]
    [row] = journal.measured(journal.load(path), {}, None)
    assert row["met"] and row["value"] == 12.0


def test_an_open_fundamental_rule_waits_for_the_next_quarter(path):
    journal.add_criteria(path, "AMD", [{"rule": "gross_margin_below", "level": 30}], DAY)
    asked = []

    def quarters_of(ticker):
        asked.append(ticker)
        return BOOK

    day = date(2026, 10, 30)
    for later in (0, 1, 30):
        assert journal.check_slow(path, day + timedelta(days=later),
                                  quarters_of=quarters_of, passages_of=_no_passages,
                                  judge=_no_judge) == []
    assert asked == ["AMD"]  # the 2026-09-30 quarter is read, the next one not out
    assert journal.fundamental_due(journal.load(path)[0], date(2026, 12, 20))
    [row] = journal.measured(journal.load(path), {}, None)
    assert row["state"] == "open" and row["gap_pct"] == 8.0


def _passage(text, day="2026-10-20", source="8-K (5.02)"):
    return {"source": source, "day": day, "text": text}


def test_an_event_rule_is_met_only_on_a_quote_its_passage_holds(path):
    [rule] = journal.add_criteria(path, "AMD", [{"rule": "ceo_change"}], DAY)
    passages = [
        _passage("Dividend declared.", day="2026-10-02"),               # no keyword
        _passage("Old news: the CEO resigned.", day="2026-09-01"),      # before the rule
        _passage("Lisa Su will step down as CEO on December 1."),
    ]
    calls = []

    def judge(rule_, ticker, shown):
        calls.append([p["text"] for p in shown])
        return {"met": True, "item": 0, "quote": "Lisa Su will  step down as CEO"}

    fired = journal.check_slow(path, date(2026, 10, 21), quarters_of=list,
                               passages_of=lambda t, since: passages, judge=judge)
    assert calls == [["Lisa Su will step down as CEO on December 1."]]
    assert fired[0]["id"] == rule.id
    assert fired[0]["quote"] == "Lisa Su will step down as CEO"
    assert fired[0]["source"] == "8-K (5.02)" and fired[0]["source_day"] == "2026-10-20"
    assert "8-K (5.02)" in journal.line_for(journal.load(path)[0])


def test_an_invented_quote_or_a_silent_model_fires_nothing(path):
    journal.add_criteria(path, "AMD", [{"rule": "dividend_cut"}], DAY)
    passages = [_passage("AMD suspends its dividend.", source="Reuters")]
    day = date(2026, 10, 21)

    def silent(rule, ticker, shown):
        return None

    assert journal.check_slow(path, day, quarters_of=list,
                              passages_of=lambda t, s: passages, judge=silent) == []
    # Nobody answered: nothing was stamped, the passage is judged next time.
    assert "checked" not in journal.load(path)[0].snapshot

    def invents(rule, ticker, shown):
        return {"met": True, "item": 0, "quote": "AMD cuts its dividend by half"}

    assert journal.check_slow(path, day, quarters_of=list,
                              passages_of=lambda t, s: passages, judge=invents) == []
    [entry] = journal.load(path)
    assert entry.state == "open" and len(entry.snapshot["seen"]) == 1
    # A passage judged once is not shown to the model again.
    assert journal.check_slow(path, day + timedelta(days=1), quarters_of=list,
                              passages_of=lambda t, s: passages, judge=_no_judge) == []


def test_a_failed_fetch_leaves_the_rule_for_the_next_card(path):
    journal.add_criteria(path, "AMD", [{"rule": "guidance_cut"},
                                       {"rule": "gross_margin_below", "level": 40}], DAY)

    def down(*args):
        raise TimeoutError("throttled")

    assert journal.check_slow(path, date(2026, 10, 21), quarters_of=down,
                              passages_of=down, judge=_no_judge) == []
    assert all("checked" not in e.snapshot for e in journal.load(path))


def test_slow_rules_read_as_words(path):
    journal.add_criteria(path, "AMD", [
        {"rule": "operating_margin_below", "level": 15, "quarters": 2},
        {"rule": "ceo_change"}], DAY)
    margin, ceo = journal.load(path)
    assert "2 quarters running" in journal.criterion_text(margin)
    assert "CEO" in journal.criterion_text(ceo)


def test_the_judge_reads_its_contract_and_asks_one_question_per_event(monkeypatch):
    from stocks.chat import engine, exit_judge

    assert exit_judge.parse('{"met": true, "item": 1, "quote": "steps down"}') == {
        "met": True, "item": 1, "quote": "steps down"}
    assert exit_judge.parse("the CEO left") is None
    assert set(exit_judge.QUESTIONS) == set(journal.EVENT_RULES)
    asked = {}

    def complete(prefs, system, messages, timeout_s, *, spend_free, accept):
        asked.update(system=system, text=messages[-1]["content"])
        return accept('{"met": false}')

    monkeypatch.setattr(engine, "complete_attempts", complete)
    judge = exit_judge.make_judge({}, spend_free=lambda prefs: True)
    verdict = judge("dividend_cut", "AMD", [_passage("AMD suspends its dividend.")])
    assert verdict == {"met": False, "item": None, "quote": ""}
    assert "AMD" in asked["system"] and "[0] 8-K (5.02) 2026-10-20" in asked["text"]
    assert judge("moon", "AMD", [_passage("x")]) is None


def test_a_long_release_is_judged_on_the_stretch_that_says_it(path):
    journal.add_criteria(path, "AMD", [{"rule": "guidance_cut"}], DAY)
    # The words far apart are not a guidance cut; together, pages in, they are.
    scattered = "We reaffirm our guidance. " + "Filler. " * 200 + "Costs were lower."
    release = "Results. " * 600 + "We now lower our full-year guidance to 30 billion."
    shown = []

    def judge(rule, ticker, passages):
        shown.extend(passages)
        return {"met": False}

    journal.check_slow(path, date(2026, 10, 21), quarters_of=list,
                       passages_of=lambda t, s: [_passage(scattered),
                                                 _passage(release, source="8-K (2.02)")],
                       judge=judge)
    [passage] = shown
    assert passage["source"] == "8-K (2.02)"
    assert len(passage["text"]) == journal.EXCERPT_CHARS
    assert "lower our full-year guidance" in passage["text"]


@pytest.mark.parametrize(("left", "charged"), [(5, True), (3, True), (2, False),
                                               (0, False)])
def test_the_judge_never_takes_the_cards_free_units(monkeypatch, left, charged):
    from stocks.api import briefing
    from stocks.chat import daily, engine

    assert daily.FREE_UNITS == 2
    monkeypatch.setattr(engine, "free_left", lambda prefs: left)
    calls = []
    assert briefing.spend_for_judge({}, lambda p: calls.append(p) or True) is charged
    assert len(calls) == int(charged)
