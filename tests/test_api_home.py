"""The React Home's server half: writing the daily card, the watchlist closes,
the refresh button and the recent-transactions amount.

What the card *says* is `chat.daily`'s and tested there. What is tested here is
what these routes decide:

* `POST /daily` writes today's card once — a stored card that stands, or a key
  already tried today, costs nothing — and a slow provider answers `pending`
  with the computed stand-in, never an empty slot;
* `GET /daily` is the poll: it sees the job, and a job whose model gave nothing
  back leaves the computed card, not yesterday's briefing;
* Regenerate takes the old card away the moment it is pressed;
* the watchlist's day % is close-to-close, re-read from a quote only for a
  name whose exchange is shut, and the close column stays a close;
* the refresh drops the price caches, and does not do it twice in a row;
* a ledger row's cash is converted at its own trade date's rate.

Nothing here touches the network: facts, models, closes and quotes are all
replaced.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import briefing, home, loaders
from stocks.api.app import app as fastapi_app
from stocks.api.routes import home as home_routes
from stocks.chat import daily

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


@pytest.fixture(autouse=True)
def _clean():
    memos = (
        loaders.stored_action,
        loaders.held_closes,
        loaders.held,
        loaders.watchlist_closes,
        loaders.ledger_state,
        loaders.quotes,
    )
    for fn in memos:
        fn.cache_clear()
    briefing._jobs.clear()
    home_routes._last_refresh = float("-inf")
    yield
    for fn in memos:
        fn.cache_clear()
    briefing._jobs.clear()


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text(
        "watchlist:\n  - ticker: AAPL\n    favorite: true\n  - ticker: SAP.DE\n"
    )
    paths.prefs.write_text(json.dumps({"currency": "EUR", "language": "en"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    # No held closes: the freshness check's "latest session" reads empty, so
    # the card's key is the day and the language alone.
    monkeypatch.setattr(loaders, "held_closes", lambda db, mtime: {})
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    return sign_in(client, EMAIL)


FACTS = {"date": "2026-09-24", "currency": "EUR", "day": {"amount": 12.0, "pct": 0.4}}


@pytest.fixture
def facts(monkeypatch):
    """Facts without a download; the stand-in card is built from these."""
    monkeypatch.setattr(briefing, "build_facts", lambda paths, prefs, day, stored: FACTS)


def written(day: date, headline: str = "Two names carry the week") -> daily.DailyAction:
    return daily.DailyAction(
        day=day.isoformat(),
        headline=headline,
        bullets=["NVDA is 8% of the book", "The dollar gave back 1.2%"],
        focus=["NVDA"],
        as_of=(day - timedelta(days=1)).isoformat(),
        lang="en",
        generated=time.time(),
    )


def today() -> date:
    return daily.action_day(datetime.now().astimezone())


def wait_done(paths, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = briefing._jobs.get(str(paths.root))
        if job is None or job.done:
            return
        time.sleep(0.01)
    raise AssertionError("the generation never finished")


# ------------------------------------------------------------------ the card


def test_a_card_that_stands_is_returned_and_costs_nothing(
    client, account, signed_in, facts, monkeypatch
):
    account.action.write_text(json.dumps(written(today()).to_dict()))
    called = []
    monkeypatch.setattr(daily, "generate", lambda *a, **k: called.append(1))
    body = signed_in.post("/v1/daily", params={"lang": "en"}).json()
    assert body["headline"] == "Two names carry the week"
    assert body["fresh"] is True and body["pending"] is False
    assert body["generated"], "the stamp's clock comes back with the card"
    assert called == []


def test_a_quick_model_lands_in_the_response_and_is_stored(
    client, account, signed_in, facts, monkeypatch
):
    monkeypatch.setattr(daily, "generate", lambda *a, **k: written(today(), "Fresh"))
    body = signed_in.post("/v1/daily", params={"lang": "en"}).json()
    assert body["headline"] == "Fresh"
    assert body["fresh"] is True and body["pending"] is False
    stored = json.loads(account.action.read_text())
    assert stored["headline"] == "Fresh"
    assert stored["recent"] == ["Fresh"], "tomorrow's prompt is told not to repeat it"


def test_a_slow_model_answers_pending_with_the_stand_in_then_the_poll_sees_it(
    client, account, signed_in, facts, monkeypatch
):
    release = threading.Event()

    def slow(*a, **k):
        release.wait(5)
        return written(today(), "Worth the wait")

    monkeypatch.setattr(daily, "generate", slow)
    monkeypatch.setattr(briefing, "GRACE_S", 0.05)
    first = signed_in.post("/v1/daily", params={"lang": "en"}).json()
    assert first["pending"] is True
    assert first["source"] == "computed" and first["headline"], "never an empty slot"
    assert signed_in.get("/v1/daily", params={"lang": "en"}).json()["pending"] is True

    release.set()
    wait_done(account)
    after = signed_in.get("/v1/daily", params={"lang": "en"}).json()
    assert after["pending"] is False
    assert after["headline"] == "Worth the wait"


def test_no_model_answering_leaves_the_stand_in_and_is_not_retried(
    client, account, signed_in, facts, monkeypatch
):
    account.action.write_text(
        json.dumps(written(today() - timedelta(days=1), "Yesterday").to_dict())
    )
    calls = []
    monkeypatch.setattr(daily, "generate", lambda *a, **k: calls.append(1))
    first = signed_in.post("/v1/daily", params={"lang": "en"}).json()
    assert first["source"] == "computed" and first["fresh"] is True
    # The poll must not fall back to yesterday's briefing either.
    polled = signed_in.get("/v1/daily", params={"lang": "en"}).json()
    assert polled["headline"] == first["headline"] != "Yesterday"
    signed_in.post("/v1/daily", params={"lang": "en"})
    assert calls == [1], "a provider that is down stays down for the next few seconds"


def test_regenerate_takes_the_old_card_away_at_once(
    client, account, signed_in, facts, monkeypatch
):
    account.action.write_text(json.dumps(written(today(), "Old").to_dict()))
    release = threading.Event()

    def slow(*a, **k):
        release.wait(5)
        return written(today(), "New")

    monkeypatch.setattr(daily, "generate", slow)
    monkeypatch.setattr(briefing, "GRACE_S", 0.05)
    body = signed_in.post("/v1/daily", params={"lang": "en", "force": True}).json()
    assert body["pending"] is True and body["headline"] is None
    release.set()
    wait_done(account)
    assert signed_in.get("/v1/daily", params={"lang": "en"}).json()["headline"] == "New"


def test_an_account_with_nothing_to_brief_on_gets_no_card(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(briefing, "build_facts", lambda *a: None)
    monkeypatch.setattr(daily, "generate", lambda *a, **k: pytest.fail("no call"))
    body = signed_in.post("/v1/daily", params={"lang": "en"}).json()
    assert body["headline"] is None and body["pending"] is False


def test_writing_one_spends_the_account_so_a_token_may_not(client, account):
    response = client.post("/v1/daily", params=WHO, headers=AUTH)
    assert response.status_code == 403


# ------------------------------------------------------------ watchlist rows


def closes(*values: float) -> pd.Series:
    start = date(2026, 9, 1)
    index = pd.to_datetime([start + timedelta(days=i) for i in range(len(values))])
    return pd.Series(list(values), index=index)


def test_the_day_move_is_close_to_close_unless_the_exchange_is_shut(
    client, account, monkeypatch
):
    monkeypatch.setattr(
        loaders,
        "watchlist_closes",
        lambda tickers: {"AAPL": closes(100.0, 110.0), "SAP.DE": closes(50.0, 50.0)},
    )
    # New York trading, Frankfurt shut: only SAP's move comes off a quote.
    monkeypatch.setattr(home, "market_live", lambda t: t == "AAPL")
    monkeypatch.setattr(home_routes, "market_active", lambda t: t == "AAPL")
    asked = []
    monkeypatch.setattr(
        loaders,
        "quotes",
        lambda tickers: (
            asked.append(tickers)
            or {"SAP.DE": {"pct": -0.03, "as_of": "2026-09-23", "price": 48.5}}
        ),
    )
    rows = {
        r["ticker"]: r
        for r in client.get("/v1/home/closes", params=WHO, headers=AUTH).json()["rows"]
    }
    assert rows["AAPL"]["close"] == 110.0
    assert rows["AAPL"]["pct"] == pytest.approx(0.10)
    assert rows["AAPL"]["active"] is True
    assert rows["SAP.DE"]["close"] == 50.0, "the column is a close, not the quote"
    assert rows["SAP.DE"]["pct"] == pytest.approx(-0.03)
    assert rows["SAP.DE"]["active"] is False
    assert asked == [("SAP.DE",)]


def test_a_name_the_download_missed_keeps_its_row(client, account, monkeypatch):
    monkeypatch.setattr(loaders, "watchlist_closes", lambda tickers: {})
    monkeypatch.setattr(home, "market_live", lambda t: True)
    rows = client.get("/v1/home/closes", params=WHO, headers=AUTH).json()["rows"]
    assert [r["ticker"] for r in rows] == ["AAPL", "SAP.DE"]
    assert rows[0]["close"] is None and rows[0]["pct"] is None


# ------------------------------------------------------------------ refresh


def test_the_refresh_drops_the_price_caches_once_per_cooldown(
    client, account, signed_in, monkeypatch
):
    cleared = []
    for memo in ("watchlist_closes", "quotes", "basket_values"):
        fn = getattr(loaders, memo)
        monkeypatch.setattr(fn, "cache_clear", lambda name=memo: cleared.append(name))
    first = signed_in.post("/v1/home/refresh").json()
    second = signed_in.post("/v1/home/refresh").json()
    assert first == {"cleared": True}
    assert second == {"cleared": False}, "one press cannot keep Yahoo busy"
    assert sorted(cleared) == ["basket_values", "quotes", "watchlist_closes"]


def test_a_token_may_not_press_the_refresh(client, account):
    assert client.post("/v1/home/refresh", params=WHO, headers=AUTH).status_code == 403


# ------------------------------------------------------------- transactions


def test_a_row_is_converted_at_its_own_trade_date(client, account, monkeypatch):
    from stocks.portfolio.ledger import Transaction

    rows = [
        Transaction(
            id=1,
            date="2026-01-05",
            ticker="AAPL",
            action="buy",
            quantity=2,
            price=100.0,
            currency="USD",
            fee=1.0,
            note="",
        ),
        Transaction(
            id=2,
            date="2026-02-02",
            ticker="AAPL",
            action="split",
            quantity=2,
            price=0.0,
            currency="USD",
            fee=0.0,
            note="",
        ),
    ]
    monkeypatch.setattr(
        loaders,
        "ledger_state",
        lambda db, mtime, base="EUR", matching="fifo": (rows, [], []),
    )
    seen = []

    def rate_on(day, frm, to):
        seen.append((day, frm, to))
        return 0.9

    monkeypatch.setattr("stocks.data.fx.rate_on", rate_on)
    body = client.get("/v1/portfolio/transactions", params=WHO, headers=AUTH).json()
    by_id = {t["id"]: t for t in body["transactions"]}
    assert body["base"] == "EUR"
    assert by_id[1]["amount"] == pytest.approx(201.0 * 0.9)
    assert by_id[2]["amount"] is None, "a split moves no cash"
    assert seen == [("2026-01-05", "USD", "EUR")]
