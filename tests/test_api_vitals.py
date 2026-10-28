"""`POST /v1/vitals`: a page's timings become one `client.vital` line each."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from stocks.api.app import app as fastapi_app
from stocks.api.routes import vitals as route


@pytest.fixture(autouse=True)
def _fresh_limiter():
    from stocks.web import ratelimit

    ratelimit._events.clear()
    yield
    ratelimit._events.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


def _logged(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", "") == "client.vital"]


def test_a_guest_page_view_is_logged_per_metric(client, caplog):
    caplog.set_level(logging.INFO)
    response = client.post(
        "/v1/vitals",
        json={
            "metrics": [
                {"name": "LCP", "value": 1830.4, "rating": "needs-improvement"},
                {"name": "CLS", "value": 0.0213, "rating": "good"},
                {"name": "INP", "value": 96, "rating": "good"},
            ],
            "where": "ticker",
            "nav": "navigate",
            "kept": True,
        },
        headers={"user-agent": "Mozilla/5.0 (iPhone) CriOS/120 Safari/604.1"},
    )
    assert response.status_code == 204
    records = {r.metric: r for r in _logged(caplog)}
    assert set(records) == {"LCP", "CLS", "INP"}
    assert records["LCP"].duration_ms == 1830
    assert records["LCP"].rating == "needs-improvement"
    assert records["LCP"].where == "ticker"
    assert records["LCP"].kept is True
    assert records["LCP"].ua == "chrome/ios"
    # CLS is a score, not a time: never under `duration_ms`.
    assert not hasattr(records["CLS"], "duration_ms")
    assert records["CLS"].score == 0.0213


def test_a_page_name_with_a_query_is_refused(client):
    response = client.post(
        "/v1/vitals",
        json={"metrics": [], "where": "ticker?symbol=AAPL"},
    )
    assert response.status_code == 422


def test_a_flood_is_dropped_quietly(client, caplog):
    caplog.set_level(logging.INFO)
    body = {"metrics": [{"name": "TTFB", "value": 120, "rating": "good"}]}
    for _ in range(route.MAX_PER_HOUR + 5):
        assert client.post("/v1/vitals", json=body).status_code == 204
    assert len(_logged(caplog)) == route.MAX_PER_HOUR


def test_extra_fields_are_refused(client):
    response = client.post("/v1/vitals", json={"metrics": [], "book": [1]})
    assert response.status_code == 422
