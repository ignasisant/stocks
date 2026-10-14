"""`GET/POST /v1/today` — the Today page's two layers.

* the GET composes the stored market read and the stored personal card, and
  never fetches, spends or writes;
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
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import briefing, daily_card, loaders
from stocks.api.app import app as fastapi_app
from stocks.chat import today_market

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
    monkeypatch.setattr(loaders, "stored_action", lambda path, mtime: {})
    monkeypatch.setattr(loaders, "held_closes", lambda db, mtime: {})
    monkeypatch.setattr(loaders, "file_mtime", lambda path: 1.0)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
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


def test_expected_session_is_settled_us_close():
    assert today_market.expected_session(
        datetime(2026, 10, 12, 21, 0, tzinfo=UTC)) == "2026-10-09"


def test_gather_today_reads_the_account_off_the_loaders(account, monkeypatch):
    """The personal sections for one account: weights off the priced table,
    verdicts off the Review route, 8-Ks only with an EDGAR user agent."""
    from types import SimpleNamespace

    import pandas as pd

    from stocks.api import home

    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    monkeypatch.setattr(home, "enriched", lambda db, mtime, ccy: pd.DataFrame(
        {"weight": [0.7, 0.3]}, index=["AAPL", "KO"]))
    monkeypatch.setattr(loaders, "headlines", lambda t: [])
    monkeypatch.setattr(loaders, "insiders", lambda t: [])
    monkeypatch.setattr(loaders, "eu_insiders", lambda t: [])
    monkeypatch.setattr(briefing, "_card_closes", lambda: {})
    row = SimpleNamespace(ticker="AAPL", verdict="trim", sector="Technology",
                          quality=70.0, cheapness=20.0)
    monkeypatch.setattr(briefing, "_review_rows", lambda paths: [row])
    reviewed: list = []
    out = briefing.gather_today(
        account, {}, {"actions": [{"kind": "alert_hit", "ticker": "KO"}]}, "en",
        datetime(2026, 10, 13).date(), None, reviewed)
    assert out["shape"] == "concentrated"
    news = next(s for s in out["sections"] if s["id"] == "news")
    assert "edgar" in news["missing"]
    assert reviewed == [row]
