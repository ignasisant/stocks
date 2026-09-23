"""The written read under the sector podium, over HTTP.

What the verdict *says* — the facts it is given, the audit that rejects an
invented percentage — is `chat.sector_ai`'s and tested there. What is tested
here is the money: who pays for one, when, and how often.

* a GET never spends, so a prefetch cannot empty anybody's allowance;
* a POST writes one, stores it, and a second POST for the same scan is free;
* a new nightly scan is what makes a read worth paying for again;
* when no model answers, the reader still gets the computed stand-in — marked
  as such — rather than an error;
* writing one is a write, so a bearer token never can.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.analysis.sectors import SectorScan
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.chat import sector_ai

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}
TECH = "Technology"


def scan(as_of: str = "2026-09-17") -> SectorScan:
    return SectorScan(
        sector=TECH,
        as_of=as_of,
        tickers=("AAPL", "MSFT", "NVDA"),
        metrics=(
            {"ticker": "AAPL", "pe_ttm": 30.0, "roic": 0.40},
            {"ticker": "MSFT", "pe_ttm": 35.0, "roic": 0.25},
            {"ticker": "NVDA", "pe_ttm": 50.0, "roic": 0.60},
        ),
        scores={"AAPL": 0.91, "MSFT": 0.74, "NVDA": 0.70},
        podium=("AAPL", "MSFT", "NVDA"),
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def _cold_cache():
    loaders.sector_scans.cache_clear()
    yield
    loaders.sector_scans.cache_clear()


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR", "language": "en"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    return sign_in(client, EMAIL)


@pytest.fixture
def tonight(monkeypatch):
    current = {"scan": scan()}
    monkeypatch.setattr(loaders, "sector_scans", lambda: {TECH: current["scan"]})
    return current


@pytest.fixture
def model(monkeypatch):
    """A generation that answers, spends one unit, and counts its calls."""
    calls = []

    def generate(prefs, facts, lang, *, timeout_s=0, spend_free=None):
        calls.append(facts["sector"])
        spend_free(prefs)
        return sector_ai.Verdict(
            sector=facts["sector"], as_of=facts["as_of"], lang=lang,
            headline="Quality leads, and you own the leader.",
            bullets=("AAPL tops the ROIC column.",), source="llm",
        )

    monkeypatch.setattr(sector_ai, "generate", generate)
    monkeypatch.setattr(
        "stocks.chat.engine.spend_free_quota",
        lambda prefs: prefs.update(spent=prefs.get("spent", 0) + 1) or True,
    )
    return calls


def test_reading_the_verdict_never_spends(client, account, signed_in, tonight, model):
    body = signed_in.get(f"/v1/sectors/{TECH}/verdict").json()
    assert body["written"] is False, "nothing stored yet: the stand-in"
    assert body["headline"]
    assert model == [], "a GET a prefetch could hit must never call a model"


def test_asking_for_one_writes_it_once_and_the_second_ask_is_free(
    client, account, signed_in, tonight, model
):
    first = signed_in.post(f"/v1/sectors/{TECH}/verdict").json()
    second = signed_in.post(f"/v1/sectors/{TECH}/verdict").json()
    assert first["written"] and second["written"]
    assert second["headline"] == first["headline"]
    assert model == [TECH], "pressing twice costs once"
    assert json.loads(account.prefs.read_text())["spent"] == 1
    # …and a read afterwards serves the stored one.
    assert signed_in.get(f"/v1/sectors/{TECH}/verdict").json()["written"] is True


def test_a_new_scan_is_what_makes_it_worth_paying_for_again(
    client, account, signed_in, tonight, model
):
    signed_in.post(f"/v1/sectors/{TECH}/verdict")
    tonight["scan"] = scan(as_of="2026-09-18")
    assert signed_in.get(f"/v1/sectors/{TECH}/verdict").json()["written"] is False
    signed_in.post(f"/v1/sectors/{TECH}/verdict")
    assert model == [TECH, TECH]


def test_no_model_answering_is_the_stand_in_not_an_error(
    client, account, signed_in, tonight, monkeypatch
):
    monkeypatch.setattr(sector_ai, "generate", lambda *a, **k: None)
    response = signed_in.post(f"/v1/sectors/{TECH}/verdict")
    assert response.status_code == 200
    assert response.json()["written"] is False
    assert "verdicts" not in {p.name.split(".")[0] for p in account.root.iterdir()}


def test_a_sector_nobody_scanned_says_so(client, account, signed_in, monkeypatch):
    monkeypatch.setattr(loaders, "sector_scans", lambda: {})
    assert signed_in.get(f"/v1/sectors/{TECH}/verdict").status_code == 404


def test_writing_one_spends_the_account_so_a_token_may_not(client, account, tonight):
    response = client.post(f"/v1/sectors/{TECH}/verdict", params=WHO, headers=AUTH)
    assert response.status_code == 403
