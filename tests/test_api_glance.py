"""The dashboard's opening reads: the briefing, the movers, the 52-week edges.

Writing a briefing belongs to `chat/daily.py` and staying at a 52-week high is
arithmetic. What is tested here is what these three routes decide:

* the card is reported, never written — this API has no path that spends an
  account's model allowance;
* freshness is not just the calendar: a language switch and a session that has
  since closed both stale a card whose date has not moved;
* a book whose prices do not cover a window reads null, not a flat 0%;
* being *at* an extreme and being 0% away from one are different facts, and the
  second one is not how the first is reported.

Nothing here touches the network: every loader is replaced.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.api.routes import glance
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
def _cold_caches():
    memos = (
        loaders.stored_action,
        loaders.held_closes,
        loaders.history,
        loaders.basket_values,
        loaders.watchlist_closes,
        loaders.ledger_state,
        loaders.quotes,
    )
    for fn in memos:
        fn.cache_clear()
    yield
    for fn in memos:
        fn.cache_clear()


@pytest.fixture(autouse=True)
def _regular_session(monkeypatch):
    """Day figures read close-to-close unless a test shuts the market itself.

    Off-session the route reaches for a quote burst, so without this the day
    window would answer differently before and after 22:00 CET — and would go
    to the network to do it, which this module promises it never does.
    """
    monkeypatch.setattr(glance, "us_market_open", lambda: True)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n  - ticker: MSFT\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    monkeypatch.setattr(loaders, "file_mtime", lambda path: 1.0)
    return paths


def today_card(**over) -> dict:
    """A card stamped for whichever action day is current right now."""
    day = daily.action_day(datetime.now().astimezone())
    return {
        "day": day.isoformat(),
        "headline": "Two names carry the week",
        "bullets": ["NVDA is 8% of the book", "The dollar gave back 1.2%"],
        "focus": ["NVDA"],
        "as_of": (day - timedelta(days=1)).isoformat(),
        "lang": "en",
        "source": "llm",
    } | over


# ------------------------------------------------------------------- the card


def test_the_card_is_reported_never_written(client, account, monkeypatch):
    """No route here spends an account's model allowance; the app owns that."""
    monkeypatch.setattr(loaders, "stored_action", lambda path, mtime: {})
    monkeypatch.setattr(loaders, "held_closes", lambda db, mtime: {})
    payload = client.get("/v1/daily", params=WHO, headers=AUTH).json()
    assert payload["headline"] is None
    assert payload["fresh"] is False
    assert payload["action_day"]  # still says which day's card is wanted


def test_a_current_card_reads_fresh(client, account, monkeypatch):
    monkeypatch.setattr(loaders, "stored_action", lambda path, mtime: today_card())
    monkeypatch.setattr(loaders, "held_closes", lambda db, mtime: {})
    payload = client.get("/v1/daily", params=WHO, headers=AUTH).json()
    assert payload["fresh"] is True
    assert payload["focus"] == ["NVDA"]
    assert payload["source"] == "llm"


def test_a_language_switch_stales_a_card_whose_date_has_not_moved(
    client, account, monkeypatch
):
    """The card is prose: a reader who just switched to Spanish should not be
    left with yesterday's English briefing until tomorrow."""
    monkeypatch.setattr(loaders, "stored_action", lambda path, mtime: today_card())
    monkeypatch.setattr(loaders, "held_closes", lambda db, mtime: {})
    payload = client.get(
        "/v1/daily", params=WHO | {"lang": "es"}, headers=AUTH
    ).json()
    assert payload["fresh"] is False
    assert payload["lang"] == "en"  # what is stored, said plainly


def test_a_session_that_has_since_closed_stales_it_too(client, account, monkeypatch):
    """Every figure in the card is a day behind, and the calendar date will not
    move until the cutoff — so the date alone cannot see this."""
    day = daily.action_day(datetime.now().astimezone())
    monkeypatch.setattr(loaders, "stored_action", lambda path, mtime: today_card())
    monkeypatch.setattr(
        loaders,
        "held_closes",
        lambda db, mtime: {
            "AAPL": pd.Series([1.0], index=pd.to_datetime([day.isoformat()]))
        },
    )
    payload = client.get("/v1/daily", params=WHO, headers=AUTH).json()
    assert payload["fresh"] is False


def test_the_cutoff_is_reported_so_a_client_need_not_hardcode_it(
    client, account, monkeypatch
):
    monkeypatch.setattr(loaders, "stored_action", lambda path, mtime: {})
    monkeypatch.setattr(loaders, "held_closes", lambda db, mtime: {})
    payload = client.get("/v1/daily", params=WHO, headers=AUTH).json()
    assert payload["cutoff_hour"] == daily.CUTOFF_HOUR


# ----------------------------------------------------------------- the movers


def basket() -> pd.DataFrame:
    """Two positions valued daily at today's shares — what `/movers` measures.

    Values, not closes: the route reads a fixed basket so that money arriving
    inside a window cannot be reported as a gain.
    """
    index = pd.to_datetime([date(2024, 3, 1) + timedelta(days=i) for i in range(40)])
    return pd.DataFrame(
        {
            "AAPL": pd.Series([100.0] * 39 + [110.0], index=index),  # +10% on the day
            "MSFT": pd.Series([200.0] * 39 + [180.0], index=index),  # -10% on the day
        }
    )


def test_the_best_and_worst_names_are_split(client, account, monkeypatch):
    monkeypatch.setattr(loaders, "basket_values", lambda db, mtime, base="EUR": basket())
    payload = client.get("/v1/movers", params=WHO, headers=AUTH).json()
    assert [m["ticker"] for m in payload["gainers"]] == ["AAPL"]
    assert payload["gainers"][0]["pct"] == pytest.approx(0.10)
    assert [m["ticker"] for m in payload["losers"]] == ["MSFT"]
    assert payload["losers"][0]["pct"] == pytest.approx(-0.10)


def test_a_window_nobody_defined_is_refused(client, account, monkeypatch):
    monkeypatch.setattr(loaders, "basket_values", lambda db, mtime, base="EUR": basket())
    response = client.get(
        "/v1/movers", params=WHO | {"window": "decade"}, headers=AUTH
    )
    assert response.status_code == 422


def test_a_book_with_no_prices_reads_empty_rather_than_flat(
    client, account, monkeypatch
):
    monkeypatch.setattr(
        loaders, "basket_values", lambda db, mtime, base="EUR": pd.DataFrame()
    )
    payload = client.get("/v1/movers", params=WHO, headers=AUTH).json()
    assert payload["gainers"] == [] and payload["losers"] == []
    assert payload["basket"] is None  # not 0.0, which would read as a flat book


def test_money_paid_in_during_the_window_is_not_a_gain(client, account, monkeypatch):
    """The bug this basket exists for.

    The book's own value history carries contributions, so an import that put
    38k into a 12k book on a Monday read as "+316% this week" with the market
    flat. Measured on a basket held at today's quantities, the same week is
    the move of the prices and nothing else.
    """
    index = pd.to_datetime([date(2024, 3, 1) + timedelta(days=i) for i in range(10)])
    # One name, up 2% across the week. The book it sits in quadrupled, because
    # money arrived — `history()` would report that, and this must not.
    frame = pd.DataFrame({"AAPL": pd.Series([100.0] * 9 + [102.0], index=index)})
    monkeypatch.setattr(loaders, "basket_values", lambda db, mtime, base="EUR": frame)
    monkeypatch.setattr(
        loaders,
        "history",
        lambda db, mtime, base="EUR": (
            pd.DataFrame(
                {
                    "value": [12_000.0] * 9 + [56_000.0],
                    "injected": [6_500.0] * 9 + [45_000.0],
                },
                index=index,
            ),
            None,
            [],
        ),
    )
    payload = client.get(
        "/v1/movers", params=WHO | {"window": "week"}, headers=AUTH
    ).json()
    assert payload["basket"] == pytest.approx(0.02)


def test_the_move_comes_back_as_money_as_well_as_a_percentage(
    client, account, monkeypatch
):
    """A tile that leads with the percentage and chips the same percentage is
    printing one fact twice. The money is what moved; the fraction is what it
    was worth relatively, and the card wants both."""
    monkeypatch.setattr(loaders, "basket_values", lambda db, mtime, base="EUR": basket())
    payload = client.get("/v1/movers", params=WHO, headers=AUTH).json()
    # 300 -> 290 across the two positions.
    assert payload["amount"] == pytest.approx(-10.0)
    assert payload["basket"] == pytest.approx(-10.0 / 300.0)
    assert payload["base"] == "EUR"


def test_a_position_the_basket_cannot_price_is_declared(client, account, monkeypatch):
    """Two names held, one measurable. The percentage is honest about the rows
    it came from only if the ones it left out are countable."""
    monkeypatch.setattr(loaders, "basket_values", lambda db, mtime, base="EUR": basket())
    monkeypatch.setattr(
        loaders,
        "ledger_state",
        lambda db, mtime, base="EUR", matching="fifo": (
            [],
            [SimpleNamespace(ticker=t) for t in ("AAPL", "MSFT", "ORGN")],
            [],
        ),
    )
    payload = client.get("/v1/movers", params=WHO, headers=AUTH).json()
    assert payload["positions"] == 3
    assert payload["unpriced"] == 1  # ORGN has no column in the basket


def test_a_shut_market_reads_the_quote_and_not_the_flat_bar(
    client, account, monkeypatch
):
    """The "+0.00% today" a reader gets before the open.

    Outside a session the newest daily bar repeats the last close, so
    close-to-close says the book did not move. The quotes say what it did —
    the live pre/after-hours move, or the last completed session — and the
    answer is dated so nobody reads it as today's.
    """
    index = pd.to_datetime([date(2024, 3, 1) + timedelta(days=i) for i in range(3)])
    flat = pd.DataFrame(
        {
            "AAPL": pd.Series([100.0] * 3, index=index),
            "MSFT": pd.Series([200.0] * 3, index=index),
        }
    )
    monkeypatch.setattr(loaders, "basket_values", lambda db, mtime, base="EUR": flat)
    monkeypatch.setattr(glance, "us_market_open", lambda: False)
    monkeypatch.setattr(glance, "market_live", lambda ticker: False)
    monkeypatch.setattr(
        loaders,
        "quotes",
        lambda tickers: {
            "AAPL": {"pct": 0.05, "as_of": "2024-03-01"},
            "MSFT": {"pct": -0.01, "as_of": "2024-03-01"},
        },
    )
    payload = client.get("/v1/movers", params=WHO, headers=AUTH).json()
    assert payload["basket"] != 0.0
    # Each name's opening value backed out of its own move: 100/1.05 + 200/0.99.
    opening = 100 / 1.05 + 200 / 0.99
    assert payload["amount"] == pytest.approx(300 - opening)
    assert payload["basket"] == pytest.approx((300 - opening) / opening)
    assert payload["as_of"] == "2024-03-01"
    assert [m["ticker"] for m in payload["gainers"]] == ["AAPL"]


def test_a_live_session_leaves_the_bars_alone(client, account, monkeypatch):
    """Inside the session the bars already track the live price, so reaching
    for a quote would cost a request to be told what the frame says."""
    called = []
    monkeypatch.setattr(loaders, "basket_values", lambda db, mtime, base="EUR": basket())
    monkeypatch.setattr(loaders, "quotes", lambda tickers: called.append(tickers) or {})
    payload = client.get("/v1/movers", params=WHO, headers=AUTH).json()
    assert called == []
    assert payload["gainers"][0]["pct"] == pytest.approx(0.10)


def test_a_longer_window_never_reads_a_quote(client, account, monkeypatch):
    """A week is close-to-close by construction — there is no live figure for
    it, and last night's quote is not one."""
    called = []
    monkeypatch.setattr(loaders, "basket_values", lambda db, mtime, base="EUR": basket())
    monkeypatch.setattr(glance, "us_market_open", lambda: False)
    monkeypatch.setattr(loaders, "quotes", lambda tickers: called.append(tickers) or {})
    client.get("/v1/movers", params=WHO | {"window": "week"}, headers=AUTH)
    assert called == []


# --------------------------------------------------------------- the extremes


def year(last_aapl: float, last_msft: float) -> dict[str, pd.Series]:
    index = pd.to_datetime([date(2024, 1, 1) + timedelta(days=i) for i in range(60)])
    return {
        "AAPL": pd.Series([100.0] * 59 + [last_aapl], index=index),
        "MSFT": pd.Series([200.0] * 59 + [last_msft], index=index),
    }


def test_a_name_at_its_high_is_reported_without_a_distance(
    client, account, monkeypatch
):
    """At or beyond the edge is a different fact from 0% away from it."""
    monkeypatch.setattr(loaders, "watchlist_closes", lambda tickers: year(140.0, 200.0))
    payload = client.get("/v1/extremes", params=WHO, headers=AUTH).json()
    by_ticker = {e["ticker"]: e for e in payload["extremes"]}
    assert by_ticker["AAPL"]["edge"] == "high"
    assert by_ticker["AAPL"]["distance"] is None


def test_a_name_just_under_its_high_carries_how_far(client, account, monkeypatch):
    monkeypatch.setattr(loaders, "watchlist_closes", lambda tickers: year(99.0, 150.0))
    payload = client.get("/v1/extremes", params=WHO, headers=AUTH).json()
    by_ticker = {e["ticker"]: e for e in payload["extremes"]}
    assert by_ticker["AAPL"]["edge"] == "high"
    assert by_ticker["AAPL"]["distance"] == pytest.approx(-0.01)
    assert by_ticker["MSFT"]["edge"] == "low"


def test_a_name_in_the_middle_of_its_range_is_not_reported(
    client, account, monkeypatch
):
    index = pd.to_datetime([date(2024, 1, 1) + timedelta(days=i) for i in range(60)])
    middle = pd.Series([50.0] + [100.0] * 58 + [75.0], index=index)
    monkeypatch.setattr(loaders, "watchlist_closes", lambda tickers: {"AAPL": middle})
    payload = client.get("/v1/extremes", params=WHO, headers=AUTH).json()
    assert payload["extremes"] == []
