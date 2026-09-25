"""The live sector rescan over HTTP — the Streamlit page's refresh button.

What a scan *is* (the ETF basket, the metrics, the podium rule) is
`analysis.sectors`' job and tested there. What is tested here is what the two
routes add on top:

* a rescan runs off the request and the client polls for it;
* a finished rescan is what the cohort answers with, until a newer nightly
  scan supersedes it;
* a rescan that failed, or came back empty, leaves the stored cohort standing;
* it keeps the widened peers the nightly job validated instead of shrinking
  the cohort to the ETF basket;
* two presses are one scan, the account's hourly budget is a 429 past its
  end, and a bearer token may never start one.

Nothing here touches Yahoo: `scan_sector` is replaced, and the background
thread is run inline.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.analysis import sectors
from stocks.analysis.sectors import SectorScan
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.api.routes import sector as route
from stocks.web import ratelimit

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TECH = "Technology"


def scan(as_of: str, tickers: tuple[str, ...] = ("AAPL", "MSFT")) -> SectorScan:
    return SectorScan(
        sector=TECH,
        as_of=as_of,
        tickers=tickers,
        metrics=tuple({"ticker": t, "roic": 0.2, "pe_ttm": 25.0} for t in tickers),
        scores={t: 0.5 for t in tickers},
        podium=(),
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def _clean_state():
    """The live scans, the job table and the burst budget are process-wide."""

    def clear():
        loaders.sector_scans.cache_clear()
        route._live.clear()
        route._jobs.clear()
        with ratelimit._lock:
            ratelimit._events.clear()

    clear()
    yield
    clear()


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    return paths


@pytest.fixture
def signed_in(client, sign_in, account):
    return sign_in(client, EMAIL)


@pytest.fixture
def stored(monkeypatch):
    """Last night's cohort: widened with one non-US peer the ETF lacks."""
    monkeypatch.setattr(
        loaders,
        "sector_scans",
        lambda: {TECH: scan("2026-09-17", ("AAPL", "MSFT", "ASML"))},
    )


@pytest.fixture
def inline(monkeypatch):
    """Run the background job on the request thread, and record what it asked."""
    asked: list[tuple[str, tuple[str, ...]]] = []
    result = {"scan": scan("2026-09-24", ("AAPL", "MSFT", "ASML", "NVDA"))}

    def fake(name, extra=(), *, as_of=None):
        asked.append((name, tuple(extra)))
        outcome = result["scan"]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(sectors, "scan_sector", fake)
    monkeypatch.setattr(route, "_spawn", lambda job: job())
    return {"asked": asked, "result": result}


def test_a_rescan_lands_and_the_cohort_answers_with_it(signed_in, stored, inline):
    started = signed_in.post(f"/v1/sectors/{TECH}/rescan")
    assert started.status_code == 202
    assert started.json()["state"] == "running"

    polled = signed_in.get(f"/v1/sectors/{TECH}/rescan").json()
    assert polled["state"] == "done"
    assert polled["as_of"] == "2026-09-24"
    assert polled["cohort"] == 4

    cohort = signed_in.get(f"/v1/sectors/{TECH}").json()
    assert cohort["as_of"] == "2026-09-24"
    assert {row["ticker"] for row in cohort["rows"]} >= {"NVDA", "ASML"}
    summary = next(
        s for s in signed_in.get("/v1/sectors").json()["sectors"] if s["sector"] == TECH
    )
    assert summary["cohort"] == 4


def test_the_rescan_keeps_the_peers_the_nightly_job_validated(
    signed_in, stored, inline
):
    """The Streamlit button rescans the ETF basket alone and drops them; a
    refresh that shrinks the cohort is not a refresh."""
    signed_in.post(f"/v1/sectors/{TECH}/rescan")
    assert inline["asked"] == [(TECH, ("AAPL", "MSFT", "ASML"))]


def test_a_failed_rescan_leaves_the_stored_cohort_standing(signed_in, stored, inline):
    from yfinance.exceptions import YFRateLimitError

    inline["result"]["scan"] = YFRateLimitError()
    signed_in.post(f"/v1/sectors/{TECH}/rescan")
    polled = signed_in.get(f"/v1/sectors/{TECH}/rescan").json()
    assert polled["state"] == "failed"
    assert polled["reason"] == "rate_limited"
    assert signed_in.get(f"/v1/sectors/{TECH}").json()["as_of"] == "2026-09-17"


def test_an_empty_basket_is_a_failure_not_an_empty_sector(signed_in, stored, inline):
    inline["result"]["scan"] = scan("2026-09-24", ())
    signed_in.post(f"/v1/sectors/{TECH}/rescan")
    assert signed_in.get(f"/v1/sectors/{TECH}/rescan").json()["reason"] == "no_data"
    assert len(signed_in.get(f"/v1/sectors/{TECH}").json()["rows"]) == 3


def test_a_newer_nightly_scan_supersedes_the_live_one(
    signed_in, stored, inline, monkeypatch
):
    signed_in.post(f"/v1/sectors/{TECH}/rescan")
    monkeypatch.setattr(loaders, "sector_scans", lambda: {TECH: scan("2026-09-25")})
    assert signed_in.get(f"/v1/sectors/{TECH}").json()["as_of"] == "2026-09-25"


def test_a_rescan_dated_the_same_day_as_the_nightly_file_still_wins(
    signed_in, inline, monkeypatch
):
    """The nightly job runs before the day starts, so a same-day rescan was
    fetched after it — pressing the button must visibly do something."""
    monkeypatch.setattr(loaders, "sector_scans", lambda: {TECH: scan("2026-09-24")})
    signed_in.post(f"/v1/sectors/{TECH}/rescan")
    assert len(signed_in.get(f"/v1/sectors/{TECH}").json()["rows"]) == 4


def test_a_sector_never_scanned_can_be_scanned_from_its_empty_state(
    signed_in, inline, monkeypatch
):
    monkeypatch.setattr(loaders, "sector_scans", dict)
    signed_in.post(f"/v1/sectors/{TECH}/rescan")
    assert inline["asked"] == [(TECH, ())]
    assert signed_in.get(f"/v1/sectors/{TECH}").json()["as_of"] == "2026-09-24"


def test_pressing_twice_while_it_runs_is_one_scan(signed_in, stored, monkeypatch):
    jobs: list = []
    monkeypatch.setattr(route, "_spawn", jobs.append)  # never runs: stays running
    first = signed_in.post(f"/v1/sectors/{TECH}/rescan").json()
    second = signed_in.post(f"/v1/sectors/{TECH}/rescan").json()
    assert len(jobs) == 1
    assert second["started_at"] == first["started_at"]


def test_the_hourly_budget_is_a_429_with_a_retry_after(signed_in, stored, inline):
    for _ in range(route.RESCAN_MAX):
        assert signed_in.post(f"/v1/sectors/{TECH}/rescan").status_code == 202
    refused = signed_in.post(f"/v1/sectors/{TECH}/rescan")
    assert refused.status_code == 429
    assert refused.json()["detail"] == "sector.rescan_limited"
    assert int(refused.headers["Retry-After"]) >= 1


def test_nothing_asked_reads_idle(signed_in, stored):
    assert signed_in.get(f"/v1/sectors/{TECH}/rescan").json()["state"] == "idle"


def test_an_invented_sector_is_a_404(signed_in):
    assert signed_in.post("/v1/sectors/Astrology/rescan").status_code == 404


def test_a_token_may_not_start_one(client, account, stored, inline):
    response = client.post(
        f"/v1/sectors/{TECH}/rescan", params={"account": EMAIL}, headers=AUTH
    )
    assert response.status_code == 403
    assert inline["asked"] == []
