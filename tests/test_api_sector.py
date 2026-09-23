"""The sector cohorts over HTTP.

Who belongs in a cohort and how it is scored is `analysis.sectors`' job and is
tested with it. What is tested here is the contract this endpoint adds: a
sector nobody has scanned yet is a different answer from a sector that does not
exist, a metric nobody defined is refused rather than sorted by, and a row with
no value for the sort metric sinks instead of ranking as a zero.

Nothing here touches the network or the bucket: the scan loader is replaced.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stocks.analysis.sectors import SECTORS, SectorScan
from stocks.api import loaders
from stocks.api.app import app as fastapi_app

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TECH = "Technology"


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


def scan() -> SectorScan:
    """Three names: a cheap one, an expensive one, and one nobody could price."""
    return SectorScan(
        sector=TECH,
        as_of="2026-09-17",
        tickers=("AAPL", "MSFT", "XYZ"),
        metrics=(
            {"ticker": "AAPL", "pe_ttm": 30.0, "roic": 0.40},
            {"ticker": "MSFT", "pe_ttm": 35.0, "roic": 0.25},
            {"ticker": "XYZ", "pe_ttm": None, "roic": None},
        ),
        scores={"AAPL": 0.91, "MSFT": 0.74},
        podium=("AAPL", "MSFT"),
    )


@pytest.fixture
def scanned(monkeypatch):
    monkeypatch.setattr(loaders, "sector_scans", lambda: {TECH: scan()})


def test_every_sector_is_listed_even_the_unscanned_ones(client, scanned):
    """"Not scanned yet" and "no such sector" are different answers."""
    payload = client.get("/v1/sectors", headers=AUTH).json()
    assert [row["sector"] for row in payload["sectors"]] == list(SECTORS)
    tech = next(row for row in payload["sectors"] if row["sector"] == TECH)
    assert tech["as_of"] == "2026-09-17"
    assert tech["cohort"] == 3
    assert tech["etf"]  # the basket the cohort was seeded from
    other = next(row for row in payload["sectors"] if row["sector"] != TECH)
    assert other["as_of"] is None and other["cohort"] == 0


def test_a_sector_url_does_not_have_to_carry_the_capitals(client, scanned):
    """A sector travels in a URL; it is resolved back to the catalog spelling,
    which is what `info["sector"]` joins on."""
    payload = client.get("/v1/sectors/technology", headers=AUTH).json()
    assert payload["sector"] == TECH


def test_an_invented_sector_is_a_404(client, scanned):
    assert client.get("/v1/sectors/Cryptozoology", headers=AUTH).status_code == 404


def test_the_default_rank_puts_the_best_compounder_first(client, scanned):
    payload = client.get(f"/v1/sectors/{TECH}", headers=AUTH).json()
    assert payload["sort"] == "roic"
    assert payload["ascending"] is False  # more ROIC is better
    assert [row["ticker"] for row in payload["rows"]] == ["AAPL", "MSFT", "XYZ"]
    assert [row["rank"] for row in payload["rows"]] == [1, 2, 3]
    assert payload["rows"][0]["score"] == pytest.approx(0.91)


def test_a_cheapness_ranking_climbs_instead_of_falling(client, scanned):
    """P/E is in `lower_is_better`, so the default direction flips with it."""
    payload = client.get(
        f"/v1/sectors/{TECH}", params={"sort": "pe_ttm"}, headers=AUTH
    ).json()
    assert payload["ascending"] is True
    assert [row["ticker"] for row in payload["rows"]][:2] == ["AAPL", "MSFT"]
    assert "pe_ttm" in payload["lower_is_better"]


def test_an_unmeasured_row_sinks_rather_than_ranking_as_zero(client, scanned):
    """Null is "nobody could measure this", and on a cheapness ranking a zero
    would make it the cheapest name in the sector."""
    payload = client.get(
        f"/v1/sectors/{TECH}", params={"sort": "pe_ttm"}, headers=AUTH
    ).json()
    last = payload["rows"][-1]
    assert last["ticker"] == "XYZ"
    assert last["metrics"]["pe_ttm"] is None


def test_the_sort_direction_can_be_asked_for_outright(client, scanned):
    payload = client.get(
        f"/v1/sectors/{TECH}",
        params={"sort": "roic", "ascending": "true"},
        headers=AUTH,
    ).json()
    assert [row["ticker"] for row in payload["rows"]][:2] == ["MSFT", "AAPL"]


def test_a_metric_nobody_defined_is_refused(client, scanned):
    response = client.get(
        f"/v1/sectors/{TECH}", params={"sort": "vibes"}, headers=AUTH
    )
    assert response.status_code == 422


def test_an_unscanned_sector_still_answers_with_the_table_it_would_draw(
    client, monkeypatch
):
    """The metric catalog is not a property of the scan: a client can build the
    columns and the sort control before any cohort exists."""
    monkeypatch.setattr(loaders, "sector_scans", lambda: {})
    payload = client.get(f"/v1/sectors/{TECH}", headers=AUTH).json()
    assert payload["rows"] == [] and payload["as_of"] is None
    assert "roic" in payload["metric_keys"]
    assert payload["default_columns"]


def test_the_cohort_is_open_to_a_guest(client, monkeypatch):
    """Inverted when guest mode landed, and the inversion is the point: a cohort
    is an answer about a sector, not about anybody's book, and Sector is one of
    the screens the landing drops a visitor into with no account at all.

    The sector routes take no `?account=` at all — nothing here is derived from
    a book — so there is no "but not about somebody" half to pin, and adding
    one would pin a parameter that does not exist. That half lives in
    `test_api_surface.test_a_guest_may_not_ask_a_guest_route_about_an_account`,
    which asks the schema which routes have the parameter rather than guessing.
    """
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("stocks.api.security.configured_token", lambda: "")
    assert client.get("/v1/sectors").status_code == 200


# --------------------------------------------------------- what a table needs
# Two things every screen that lists holdings needs and that used to have no
# batch answer: how to format a KPI, and what to draw beside a ticker. Both are
# tested here because the cohort table is what made each of them a problem.


def test_a_kpi_says_how_it_reads(client, scanned):
    """Nothing else on the wire says `roic` is a fraction shown as a percentage
    while `pe_ttm` is a multiple. A client formatting them alike prints one of
    them wrong, and the alternative is every client carrying its own copy of
    this table and drifting from it."""
    rows = client.get("/v1/kpi-sources", headers=AUTH).json()["kpis"]
    units = {row["key"]: row["unit"] for row in rows}
    assert units["roic"] == "pct"
    assert units["pe_ttm"] == "x"
    assert units["market_cap"] == "money"
    assert all(row["unit"] for row in rows), "a KPI with no unit cannot be printed"
