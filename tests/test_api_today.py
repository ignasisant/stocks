"""`GET/POST /v1/today` — the Today page's two layers.

* the GET composes the stored market read and the stored personal card, and
  never spends or writes (only the book rows are redone, off cached prices);
* a read that is missing, a session behind or without the reader's language
  starts ONE background build, however many readers ask, and a failed one is
  not retried before `MIN_REBUILD_S`;
* a guest reads the market and gets no personal card;
* the POST never abandons a generation already out for the account — in any
  language, started here or by Home's `POST /daily`.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts, loaders
from stocks.api.app import app as fastapi_app
from stocks.chat import daily_book, today_market
from stocks.views import briefing, daily_card
from tests.patching import patch_loaders

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    patch_loaders(monkeypatch, "stored_action", lambda path, mtime: {})
    patch_loaders(monkeypatch, "held_closes", lambda db, mtime: {})
    patch_loaders(monkeypatch, "file_mtime", lambda path: 1.0)
    patch_loaders(monkeypatch, "db_mtime", lambda db: 1.0)
    return paths


def _store(session: str, *, langs=("en", "es"), built_at: float | None = None):
    facts = {
        "session": session,
        "regime": {"score": 55.0, "key": "neutral", "run": 4, "score_month": 48.0},
        "rates": [{"key": "us10y", "value": 4.2, "change_bp": -8.0}],
        "banks": [{"bank": "fed", "rate": 4.0, "last_move_bp": -25.0,
                   "last_date": "2026-09-16", "moved_on": "2026-09-17",
                   "next_date": "2026-10-28", "days": 15}],
        "sectors": [{"ticker": "XLK", "name": "Technology", "week": 1.0, "month": 3.2}],
        "index": {"name": "S&P 500", "day": 0.4, "week": 1.1, "month": 2.0},
        "missing": ["crypto"],
    }
    cards = {lang: {"headline": f"Headline {lang}", "source": "llm",
                    "lines": [{"topic": "rates", "line": f"Rates {lang}"}]}
             for lang in langs}
    today_market.save({"facts": facts, "cards": cards, "session": session,
                       "built_at": time.time() if built_at is None else built_at})
    loaders.today_market.cache_clear()


@pytest.fixture
def current(monkeypatch):
    """Freeze the last settled session at 2026-10-12."""
    monkeypatch.setattr(today_market, "expected_session", lambda now=None: "2026-10-12")


def test_the_get_composes_both_layers(client, account, current):
    _store("2026-10-12")
    body = client.get("/v1/today", params=WHO | {"lang": "es"}, headers=AUTH).json()
    market = body["market"]
    assert market["headline"] == "Headline es" and market["lang"] == "es"
    assert market["lines"] == [{"topic": "rates", "line": "Rates es"}]
    assert market["banks"][0]["moved_on"] == "2026-09-17"
    assert market["index"]["month"] == 2.0
    assert market["missing"] == ["crypto"]
    assert body["market_stale"] is False
    assert body["personal"]["fresh"] is False  # no card written yet
    assert briefing.market_builds == []


def test_no_read_yet_starts_one_build(client, account, current):
    stale = []
    for _ in range(3):
        body = client.get("/v1/today", params=WHO, headers=AUTH).json()
        assert body["market"] is None
        stale.append(body["market_stale"])
    assert briefing.market_builds == [("refetch", "en")]
    # The (inert) build ended without a read: nothing newer is on its way,
    # so the page stops waiting rather than polling for two hours.
    assert stale == [True, False, False]


def test_a_read_a_session_behind_is_served_while_it_rebuilds(client, account, current):
    _store("2026-10-09")
    body = client.get("/v1/today", params=WHO, headers=AUTH).json()
    assert body["market"]["headline"] == "Headline en"
    assert body["market_stale"] is True
    assert briefing.market_builds == [("refetch", "en")]



def test_the_served_read_is_logged_once_per_state(client, account, current, monkeypatch):
    from stocks import obs

    events = []
    seen = set()
    monkeypatch.setattr(obs, "event", lambda name, **f: events.append((name, f)))
    monkeypatch.setattr(
        obs, "first_sighting", lambda name, key="": not (key in seen or seen.add(key))
    )
    _store("2026-10-09", built_at=time.time() - 7200)
    for _ in range(3):  # a page polling
        client.get("/v1/today", params=WHO, headers=AUTH)
    served = [f for name, f in events if name == "today.market_served"]
    # Stale while the (inert) build runs, then not: two states, two lines,
    # however many polls.
    assert [f["stale"] for f in served] == [True, False]
    assert served[0]["session"] == "2026-10-09"
    assert served[0]["age_h"] == 2.0 and served[0]["missing"] is False

def test_a_missing_language_builds_only_that_language(client, account, current):
    _store("2026-10-12", langs=("es",))
    body = client.get("/v1/today", params=WHO | {"lang": "en"}, headers=AUTH).json()
    assert body["market"] is None and body["market_stale"] is True
    assert briefing.market_builds == [("lang", "en")]


def test_a_build_in_flight_is_not_doubled(account, current):
    _store("2026-10-09")
    assert briefing._market_lock.acquire(blocking=False)
    try:
        _, stale = briefing.market_day("en")
    finally:
        briefing._market_lock.release()
    assert stale is True and briefing.market_builds == []


def test_a_failed_build_waits_before_the_next_try(account, current):
    _store("2026-10-09")
    now = time.time()
    briefing.market_day("en", now=now)
    briefing.market_day("en", now=now + 60)
    assert briefing.market_builds == [("refetch", "en")]
    briefing.market_day("en", now=now + today_market.MIN_REBUILD_S + 1)
    assert len(briefing.market_builds) == 2


def test_the_lazy_build_runs_the_market_read(monkeypatch, current):
    """The real `_market_start`: a thread that runs `today_market.run` for the
    asked language and frees the lock when it is done."""
    calls = []
    monkeypatch.setattr(briefing, "_market_start", briefing.__dict__["_market_start"])
    monkeypatch.setattr(
        today_market, "run",
        lambda day, langs, *, refetch=True, dry_run=False: calls.append((langs, refetch)),
    )
    assert briefing._market_lock.acquire(blocking=False)
    briefing._market_build("lang", "es")
    assert calls == [(("es",), False)]
    assert not briefing._market_lock.locked()


def test_a_guest_reads_the_market_only(client, current, monkeypatch):
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    _store("2026-10-12")
    body = client.get("/v1/today").json()
    assert body["market"]["headline"] == "Headline en"
    assert body["personal"] is None


def test_the_book_is_redrawn_over_a_window_against_an_index(client, account, monkeypatch):
    asked = []

    def compare(paths, lang, span, index):
        asked.append((paths, lang, span, index))
        dates = ["2026-01-02", "2026-10-12"]
        return [{"symbol": "@BOOK", "currency": "EUR", "dates": dates,
                 "values": [1000.0, 1040.0], "money": True, "label": "Tu cartera"},
                {"symbol": "^IBEX", "currency": "EUR", "dates": dates,
                 "values": [1000.0, 1100.0], "money": True, "label": "IBEX 35"}]

    monkeypatch.setattr(briefing, "book_compare", compare)
    query = {"lang": "es", "range": "ytd", "index": "^IBEX"}
    body = client.get("/v1/today/book", headers=AUTH, params=WHO | query).json()
    assert asked == [(account, "es", "ytd", "^IBEX")]
    assert body["range"] == "ytd" and body["index"] == "^IBEX"
    assert [line["symbol"] for line in body["chart"]] == ["@BOOK", "^IBEX"]


def test_a_young_book_says_where_it_begins(client, account, monkeypatch):
    today = date.today()

    def drawn(opens):
        dates = [opens.isoformat(), today.isoformat()]
        line = {"symbol": "@BOOK", "currency": "EUR", "dates": dates,
                "values": [1000.0, 1200.0], "money": True}
        return lambda *a, **k: [line, line | {"symbol": "SPY"}]

    young = today - timedelta(days=400)
    monkeypatch.setattr(briefing, "book_compare", drawn(young))
    body = client.get("/v1/today/book", headers=AUTH, params=WHO | {"range": "5y"}).json()
    assert body["since"] == young.isoformat()
    # A window that opens on its last close before a long weekend is whole.
    monkeypatch.setattr(briefing, "book_compare", drawn(today - timedelta(days=726)))
    body = client.get("/v1/today/book", headers=AUTH, params=WHO | {"range": "2y"}).json()
    assert body["since"] is None


@pytest.mark.parametrize(("opened", "index", "asked"), [
    (8, "SPY", ["max"]),
    (3, "SPY", ["6y"]),
    (1, "SPY", []),
    (1, "QQQ", ["6y"]),
    (8, "QQQ", ["max"]),
])
def test_the_index_is_read_back_to_the_books_first_day(
    account, monkeypatch, opened, index, asked
):
    days = pd.date_range(end=pd.Timestamp.today().normalize(),
                         start=pd.Timestamp.today() - pd.DateOffset(years=opened))
    value = pd.Series(range(1, len(days) + 1), index=days, dtype=float)
    hist = pd.DataFrame({"value": value, "injected": 1.0})
    patch_loaders(monkeypatch, "history", lambda *a, **k: (hist, None, []))
    periods = []
    monkeypatch.setattr(briefing, "_compare_closes",
                        lambda period="6y": periods.append(period) or {})
    monkeypatch.setattr(briefing, "card_closes", dict)
    # Whatever the window: the same money goes in from the book's first day.
    lines = briefing.book_compare(account, "en", "1m", index)
    assert periods == asked
    assert lines and lines[0]["symbol"] == "@BOOK"


def test_every_window_is_the_book_against_its_own_money_in_the_index(
    account, monkeypatch
):
    days = pd.date_range(end=pd.Timestamp.today().normalize(), periods=800)
    # A deposit doubles the value halfway: the book's line shows the money,
    # and the index line is bought with it on the same day.
    value = pd.Series([100.0] * 400 + [200.0] * 400, index=days)
    injected = pd.Series([100.0] * 400 + [200.0] * 400, index=days)
    spy = pd.Series(50.0, index=days)
    hist = pd.DataFrame({"value": value, "injected": injected})
    patch_loaders(monkeypatch, "history", lambda *a, **k: (hist, None, []))
    monkeypatch.setattr(briefing, "_compare_closes", lambda period="6y": {})
    monkeypatch.setattr(briefing, "card_closes", dict)
    monkeypatch.setattr(daily_book, "index_series", lambda closes, ccy: (spy, "EUR"))
    for span, days_back in (("1m", 30), ("6m", 182), ("2y", 730)):
        book, index = briefing.book_compare(account, "en", span, "SPY")
        assert book["values"][-1] == index["values"][-1] == 200.0
        assert book["injected"][-1] == 200.0
        opens = (days[-1] - pd.Timedelta(days=days_back)).date().isoformat()
        assert book["dates"][0] == index["dates"][0] == opens


def test_the_book_chart_refuses_what_it_does_not_offer(client, account):
    bad_index = client.get("/v1/today/book", headers=AUTH,
                           params=WHO | {"index": "AAPL"})
    bad_range = client.get("/v1/today/book", headers=AUTH, params=WHO | {"range": "10y"})
    assert bad_index.status_code == 422 and bad_range.status_code == 422


def test_a_failed_redraw_is_an_empty_chart(client, account, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("download")

    monkeypatch.setattr(briefing, "book_compare", boom)
    body = client.get("/v1/today/book", headers=AUTH, params=WHO | {"range": "1y"}).json()
    assert body["chart"] == []


def test_a_guest_has_no_book_to_redraw(client, current):
    assert client.get("/v1/today/book", params={"range": "3m"}).status_code in (401, 403)


def test_a_guest_cannot_post(client, current):
    assert client.post("/v1/today").status_code in (401, 403)


def test_an_unreadable_market_file_drops_the_market_only(client, account, current):
    _store("2026-10-12")
    stored = today_market.load(restore=False)
    stored["cards"]["en"]["lines"] = [{"topic": "gossip", "line": "x"}]
    today_market.save(stored)
    loaders.today_market.cache_clear()
    body = client.get("/v1/today", params=WHO, headers=AUTH).json()
    assert body["market"] is None and body["personal"] is not None


def test_the_post_never_abandons_a_running_job(account, current, monkeypatch):
    """A generation out for the account, whatever its key, is reported."""
    started = []
    running = briefing.Job(key=("other",), forced=False, computed=None)
    monkeypatch.setattr(briefing, "running", lambda paths: running)
    monkeypatch.setattr(briefing, "start", lambda *a, **k: started.append(a))
    monkeypatch.setattr(briefing, "build_facts", lambda *a, **k: {"x": 1})
    daily_card.request(account, "en", force=False, patient=True)
    assert started == []
    daily_card.request(account, "en", force=True, patient=True)
    assert len(started) == 1


def test_a_card_whose_comparisons_predate_the_readers_currency_is_rewritten():
    from stocks.chat.daily import DailyAction

    day = date(2026, 11, 5)
    key = ("", "", "", "sig")
    compare = {"id": "compare", "rows": [{"key": "compare:NVDA"}]}

    def card(*sections):
        return DailyAction(day=day.isoformat(), headline="h", bullets=[], lang="en",
                           brief_sig="sig", shape="mixed", today=list(sections))

    assert daily_card.stands(card({**compare, "currency": "EUR"}), day, "en", key)
    assert not daily_card.stands(card(compare), day, "en", key)
    # Nothing compared, nothing measured in the wrong money.
    assert daily_card.stands(card({"id": "compare", "rows": []}), day, "en", key)
    assert daily_card.stands(card({"id": "news", "rows": [{"key": "n"}]}), day, "en", key)


def test_expected_session_is_settled_us_close():
    assert today_market.expected_session(
        datetime(2026, 10, 12, 21, 0, tzinfo=UTC)) == "2026-10-09"


def test_gather_today_reads_the_account_off_the_loaders(account, monkeypatch):
    """The personal sections for one account: weights off the priced table,
    verdicts off the Review route, 8-Ks only with an EDGAR user agent."""
    from types import SimpleNamespace

    import pandas as pd

    from stocks.views import home

    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    monkeypatch.setattr(home, "enriched", lambda db, mtime, ccy: pd.DataFrame(
        {"weight": [0.7, 0.3]}, index=["AAPL", "KO"]))
    patch_loaders(monkeypatch, "headlines", lambda t: [])
    patch_loaders(monkeypatch, "insiders", lambda t: [])
    patch_loaders(monkeypatch, "eu_insiders", lambda t: [])
    monkeypatch.setattr(briefing, "card_closes", lambda: {})
    monkeypatch.setattr(briefing, "_bench_closes", lambda: {})
    row = SimpleNamespace(ticker="AAPL", verdict="trim", sector="Technology",
                          quality=70.0, cheapness=20.0)
    monkeypatch.setattr(briefing, "_review_rows", lambda paths: [row])
    # The followed names' prints come off the calendar the card already read;
    # a print's revenue off `print_facts`, the release left unread without
    # EDGAR (it would only cache the refusal).
    from stocks.data.earnings import EarningsResult

    monkeypatch.setattr(briefing, "_followed", lambda paths: ("AAPL", "KO"))
    patch_loaders(monkeypatch, "earnings_calendar", lambda tickers: (
        [], [EarningsResult("AAPL", date(2026, 10, 12), 0.98, 1.05, 7.1)]))
    asked: list = []

    def print_source(action, release=True):
        asked.append((action, release))
        return {"revenue": 35.1e9, "revenue_yoy_pct": 12.0, "currency": "USD"}

    monkeypatch.setattr(briefing, "print_facts", print_source)
    reviewed: list = []
    out = briefing.gather_today(
        account, {}, {"actions": [{"kind": "alert_hit", "ticker": "KO"}]}, "en",
        datetime(2026, 10, 13).date(), None, reviewed)
    assert out["shape"] == "concentrated"
    news = next(s for s in out["sections"] if s["id"] == "news")
    assert "edgar" in news["missing"]
    assert reviewed == [row]
    assert asked == [({"ticker": "AAPL", "date": "2026-10-12"}, False)]
    print_row = next(r for r in news["rows"] if r["kind"] == "results")
    assert print_row["key"] == "print:AAPL:2026-10-12"
    assert print_row["line"].startswith(
        "AAPL reported: EPS 1.05 vs 0.98 expected (+7.1%), revenue $35.1B (+12.0% y/y)")


def test_today_weighs_a_name_the_price_pass_missed_at_its_cost():
    """2026-11-04: the ECB rate host failed, every dollar name read NaN, and
    the comparisons covered the seven euro names as if they were the book."""
    tbl = pd.DataFrame({"value": [600.0, float("nan")], "cost": [500.0, 400.0]},
                       index=["SOL-EUR", "GOOG"])
    weights, unpriced = briefing._today_weights(tbl)
    assert weights == {"SOL-EUR": 0.6, "GOOG": 0.4}
    assert unpriced == ["GOOG"]


def _card_with_book() -> daily_card.DailyCard:
    from stocks.schemas import DailyBook, DailyBookRow, DailyCard

    rows = [DailyBookRow(window="day", pct=3.43, amount=4613.0, index_pct=1.0),
            DailyBookRow(window="week", pct=0.29, amount=402.0, index_pct=0.5)]
    return DailyCard(action_day="2026-11-05", fresh=True, headline="Written at 07:26",
                     book=DailyBook(index="S&P 500", currency="EUR", rows=rows))


def test_the_book_rows_are_the_ones_home_prints_now(account, monkeypatch):
    """The card is the morning's; its rows are figures Home's tiles print
    live. Served together they would read +402 € and −110 € for one week."""
    from stocks.views import book_moves

    monkeypatch.setattr(book_moves, "moves", lambda db, mtime, ccy: {
        "day": (3835.0, 0.0284), "week": (-110.0, -0.0008), "month": None})
    patch_loaders(monkeypatch, "history",
                  lambda db, mtime, base="EUR": (pd.DataFrame(), None, []))
    monkeypatch.setattr(briefing, "card_closes", lambda: {})
    monkeypatch.setattr(daily_book, "index_facts", lambda closes, ccy, hist=None: {
        "day_pct": 1.2, "week_pct": -0.4, "month_pct": 2.0})
    card = daily_card.live_book(account, _card_with_book())
    assert card.headline == "Written at 07:26"
    assert [(r.window, r.amount, r.pct, r.index_pct) for r in card.book.rows] == [
        ("day", 3835.0, 2.84, 1.2), ("week", -110.0, -0.08, -0.4)]


def test_rows_that_cannot_be_redone_stay_as_written(account, monkeypatch):
    from stocks.views import book_moves

    def boom(*a, **k):
        raise RuntimeError("prices down")

    monkeypatch.setattr(book_moves, "moves", boom)
    card = _card_with_book()
    assert daily_card.live_book(account, card) is card
