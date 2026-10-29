"""Options-implied view and rating changes — stubbed yfinance payloads.

Frame shapes recorded from live probes (2026-10-27): `option_chain` columns
contractSymbol..currency, `upgrades_downgrades` indexed by GradeDate with
Firm/ToGrade/FromGrade/Action/priceTargetAction/currentPriceTarget/
priorPriceTarget.
"""

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from yfinance.exceptions import YFRateLimitError

from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.data import options as options_data
from stocks.data.estimates import rating_changes
from stocks.data.options import Chain, RawOptions, closed, pick_expiries, summarize

TODAY = date(2026, 10, 27)
TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


def side(rows):
    """rows: (strike, bid, ask, iv, oi, volume)."""
    return pd.DataFrame(
        rows,
        columns=["strike", "bid", "ask", "impliedVolatility", "openInterest", "volume"],
    )


def chain(expiry, calls, puts):
    return Chain(expiry, side(calls), side(puts))


def test_expiry_for_iv_is_the_first_at_least_twenty_days_out():
    got = pick_expiries(("2026-10-28", "2026-11-06", "2026-11-20", "2026-12-18"), TODAY)
    assert got[0] == "2026-11-20"
    # the rest of the 60-day window rides along for the put/call balance
    assert set(got) == {"2026-11-20", "2026-11-06", "2026-10-28", "2026-12-18"}


def test_expiry_falls_back_to_the_farthest_when_all_are_near():
    assert pick_expiries(("2026-10-28", "2026-11-06"), TODAY)[0] == "2026-11-06"
    assert pick_expiries((), TODAY) == []


def test_atm_iv_reads_the_quoted_strike_nearest_the_spot():
    raw = RawOptions(
        100.0,
        [
            chain(
                "2026-11-20",
                [
                    (90, 11, 12, 0.40, 500, 10),
                    (100, 3, 3.2, 0.30, 900, 20),
                    (110, 0.5, 0.6, 0.35, 300, 5),
                ],
                # the put at 100 is unquoted junk (bid 0, iv 3.2) so it is skipped
                [(95, 1.0, 1.2, 0.34, 800, 30), (100, 0, 0, 3.2, 10, 0)],
            )
        ],
    )
    out = summarize(raw, TODAY)
    assert out is not None
    assert out["iv"] == pytest.approx((0.30 + 0.34) / 2)
    assert out["iv_expiry"] == "2026-11-20" and out["iv_days"] == 24


def test_atm_iv_skips_a_chain_quoted_only_far_from_the_spot():
    # BKNG after its split: the nearest quoted call was the 110 against a 150
    # spot, its IV mostly a wide market — no reading beats that one.
    raw = RawOptions(
        150.14,
        [
            chain(
                "2026-11-20",
                [(110, 38.0, 51.7, 1.38, 1, 0), (100, 48, 61.5, 1.65, 8, 0)],
                [(200, 50, 60, 0.9, 5, 3)],
            )
        ],
    )
    out = summarize(raw, TODAY)
    assert out is None or out["iv"] is None


def test_put_call_sums_every_expiry_and_hides_a_thin_book():
    raw = RawOptions(
        100.0,
        [
            chain(
                "2026-11-20",
                [(100, 3, 3.2, 0.3, 600, 100)],
                [(100, 3, 3.2, 0.3, 300, 80)],
            ),
            chain(
                "2026-12-04",
                [(100, 4, 4.2, 0.3, 400, 100)],
                [(100, 4, 4.2, 0.3, 300, 20)],
            ),
        ],
    )
    out = summarize(raw, TODAY)
    assert out["put_call_oi"] == pytest.approx(600 / 1000)
    assert out["put_call_volume"] == pytest.approx(100 / 200)
    assert out["open_interest"] == 1600 and out["expiries"] == 2

    thin = RawOptions(
        100.0,
        [chain("2026-11-20", [(100, 3, 3.2, 0.3, 20, 1)], [(100, 3, 3.2, 0.3, 30, 1)])],
    )
    got = summarize(thin, TODAY)
    assert got["put_call_oi"] is None and got["put_call_volume"] is None
    assert got["iv"] == pytest.approx(0.3)


def test_nothing_listed_or_nothing_readable_is_none():
    assert summarize(None, TODAY) is None
    assert summarize(RawOptions(None, []), TODAY) is None
    empty = RawOptions(100.0, [chain("2026-11-20", [], [])])
    assert summarize(empty, TODAY) is None


def session_chain():
    return chain(
        "2026-11-20",
        [(95, 6, 6.2, 0.31, 800, 40), (100, 3, 3.2, 0.30, 900, 20)],
        [(100, 2.9, 3.1, 0.32, 700, 25), (105, 6, 6.3, 0.33, 400, 10)],
    )


def zeroed_chain():
    """Yahoo out of session: no bid, no ask, no open interest; the last
    session's volume and a stale IV stay (AAPL, 2026-10-29 pre-market)."""
    return chain(
        "2026-11-20",
        [(95, 0, 0, 0.31, 0, 40), (100, 0, 0, 0.30, 0, 20)],
        [(100, 0, 0, 0.32, 0, 25), (105, 0, 0, 0.33, 2, 10)],
    )


def test_a_zeroed_chain_out_of_session_is_closed():
    assert closed(RawOptions(100.0, [zeroed_chain()], "PRE"))
    assert closed(RawOptions(100.0, [zeroed_chain()], "CLOSED"))
    # in session a thin chain is the market, however thin
    assert not closed(RawOptions(100.0, [zeroed_chain()], "REGULAR"))
    # out of session but still quoted (the minutes after the bell)
    assert not closed(RawOptions(100.0, [session_chain()], "POST"))
    assert not closed(None)
    assert not closed(RawOptions(100.0, [chain("2026-11-20", [], [])], "PRE"))


def test_out_of_session_the_last_session_reading_answers(monkeypatch):
    loaders.options_view.cache_clear()
    raw = {"now": RawOptions(100.0, [session_chain()], "REGULAR")}
    monkeypatch.setattr(options_data, "fetch_chains", lambda t: raw["now"])
    live = loaders.options_view("AAPL")
    assert live is not None and live["iv"] == pytest.approx(0.31)

    loaders.options_view.cache_clear()
    raw["now"] = RawOptions(100.0, [zeroed_chain()], "PRE")
    assert loaders.options_view("AAPL") == live
    # a name never read in session has nothing to stand in: no card, no zeros
    assert loaders.options_view("MSFT") is None


def test_a_session_reading_past_its_keep_does_not_answer(monkeypatch):
    loaders.options_view.cache_clear()
    monkeypatch.setattr(
        options_data,
        "fetch_chains",
        lambda t: RawOptions(100.0, [session_chain()], "REGULAR"),
    )
    loaders.options_view("AAPL")
    monkeypatch.setattr(loaders, "_SESSION_KEEP_S", 0.0)
    monkeypatch.setattr(
        options_data,
        "fetch_chains",
        lambda t: RawOptions(100.0, [zeroed_chain()], "PRE"),
    )
    loaders.options_view.cache_clear()
    assert loaders.options_view("AAPL") is None


# ---------------------------------------------------------- rating changes


def sample_changes() -> pd.DataFrame:
    rows = [
        (
            "2026-10-22 09:50:43",
            "Needham",
            "Buy",
            "Buy",
            "reit",
            "Maintains",
            300.0,
            300.0,
        ),
        (
            "2026-10-20 18:00:28",
            "MoffettNathanson",
            "Buy",
            "Neutral",
            "up",
            "Raises",
            330.0,
            304.0,
        ),
        (
            "2026-09-10 14:02:40",
            "Piper Sandler",
            "Overweight",
            "",
            "init",
            "Announces",
            300.0,
            0.0,
        ),
        (
            "2026-08-27 19:31:05",
            "Citigroup",
            "Buy",
            "Buy",
            "main",
            "Raises",
            315.0,
            300.0,
        ),
        (
            "2026-08-01 10:00:00",
            "Mizuho",
            "Neutral",
            "Outperform",
            "down",
            "Lowers",
            250.0,
            315.0,
        ),
        ("2025-01-01 10:00:00", "Old", "Buy", "Buy", "up", "Raises", 1.0, 0.5),
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "GradeDate",
            "Firm",
            "ToGrade",
            "FromGrade",
            "Action",
            "priceTargetAction",
            "currentPriceTarget",
            "priorPriceTarget",
        ],
    )
    frame["GradeDate"] = pd.to_datetime(frame["GradeDate"])
    return frame.set_index("GradeDate")


def test_rating_changes_keep_moves_and_drop_reiterations_and_stale_rows():
    got = rating_changes(sample_changes(), TODAY)
    assert [r["firm"] for r in got] == [
        "MoffettNathanson",
        "Piper Sandler",
        "Citigroup",
        "Mizuho",
    ]
    up, init, trim, down = got[0], got[1], got[2], got[3]
    assert up["action"] == "upgrade" and up["from_grade"] == "Neutral"
    assert up["target"] == 330.0 and up["prior_target"] == 304.0
    assert up["target_move"] == "raised" and up["date"] == "2026-10-20"
    assert init["action"] == "initiated" and init["from_grade"] is None
    assert init["prior_target"] is None  # Yahoo's 0.0 means "none before"
    assert trim["action"] == "reiterated" and trim["target_move"] == "raised"
    assert down["action"] == "downgrade" and down["target_move"] == "lowered"


def test_rating_changes_of_nothing_is_empty():
    assert rating_changes(None, TODAY) == []
    assert rating_changes(pd.DataFrame(), TODAY) == []


# ------------------------------------------------------------------ routes


def test_analysts_carry_the_changes_beside_the_consensus(client, monkeypatch):
    from stocks.data.estimates import RawEstimates

    monkeypatch.setattr(loaders, "estimates", lambda t: RawEstimates(ticker=t))
    monkeypatch.setattr(
        loaders, "rating_changes", lambda t: rating_changes(sample_changes(), TODAY)
    )
    body = client.get("/v1/ticker/NVDA/analysts", headers=AUTH).json()
    assert [c["firm"] for c in body["changes"]][0] == "MoffettNathanson"
    assert body["changes"][0]["target"] == 330.0


def test_a_refused_changes_call_leaves_the_card_whole(client, monkeypatch):
    from stocks.data.estimates import RawEstimates

    def refused(t):
        raise YFRateLimitError()

    monkeypatch.setattr(loaders, "estimates", lambda t: RawEstimates(ticker=t))
    monkeypatch.setattr(loaders, "rating_changes", refused)
    res = client.get("/v1/ticker/NVDA/analysts", headers=AUTH)
    assert res.status_code == 200 and res.json()["changes"] == []


def test_options_route_shapes_the_view_and_says_unlisted_for_the_rest(
    client, monkeypatch
):
    view = {
        "iv": 0.28,
        "iv_expiry": "2026-11-20",
        "iv_days": 24,
        "put_call_oi": 0.88,
        "put_call_volume": 0.9,
        "open_interest": 986682,
        "expiries": 4,
    }
    monkeypatch.setattr(loaders, "options_view", lambda t: view if t == "AAPL" else None)
    body = client.get("/v1/ticker/AAPL/options", headers=AUTH).json()
    assert body["listed"] is True and body["iv"] == 0.28 and body["put_call_oi"] == 0.88
    other = client.get("/v1/ticker/SAP.DE/options", headers=AUTH).json()
    assert other["listed"] is False and other["iv"] is None
    assert (
        client.get("/v1/ticker/BTC-EUR/options", headers=AUTH).json()["listed"] is False
    )


def test_a_throttled_options_call_is_a_503_not_a_verdict(client, monkeypatch):
    def refused(t):
        raise YFRateLimitError()

    monkeypatch.setattr(loaders, "options_view", refused)
    assert client.get("/v1/ticker/AAPL/options", headers=AUTH).status_code == 503


def test_a_suffixed_line_is_not_asked_for_rating_changes(monkeypatch):
    """Yahoo has no rating changes for IBE.MC and says so with a slow 404;
    the line never reaches yfinance."""
    import yfinance as yf

    from stocks.data import estimates

    def boom(*args, **kwargs):
        raise AssertionError("asked Yahoo")

    monkeypatch.setattr(yf, "Ticker", boom)
    assert estimates.fetch_rating_changes("IBE.MC").empty
    assert estimates.fetch_rating_changes("^GSPC").empty
