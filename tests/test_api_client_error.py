"""`POST /v1/client-error`: a browser error becomes one masked log line."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from stocks.api.app import app as fastapi_app
from stocks.api.routes import client_error as route


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
    return [r for r in caplog.records if getattr(r, "event", "") == "client.error"]


def test_a_guest_error_is_logged_once_and_answered_204(client, caplog):
    caplog.set_level(logging.WARNING)
    response = client.post(
        "/v1/client-error",
        json={
            "kind": "render",
            "name": "TypeError",
            "message": "Cannot read properties of undefined (reading 'price')",
            "where": "ticker?symbol=AAPL&tab=fees",
            "src": "https://x.run.app/next-assets/ticker-AbC1.js:3:1840",
            "stack": "at q (https://x.run.app/next-assets/ticker-AbC1.js?v=1:3:1840)",
            "component": "at Fees\nat Ticker",
        },
        headers={"user-agent": "Mozilla/5.0 (iPhone) CriOS/120 Safari/604.1"},
    )
    assert response.status_code == 204
    [record] = _logged(caplog)
    assert record.levelno == logging.WARNING
    assert record.kind == "render"
    assert record.exc == "TypeError"
    assert record.error == "Cannot read properties of undefined (reading 'price')"
    assert record.src.endswith("ticker-AbC1.js:3:1840")
    assert "?v=1" not in record.stack_trace
    assert "at Fees" in record.stack_trace
    assert record.ua == "chrome/ios"


def test_values_in_the_message_are_masked():
    text = route.scrub_message(
        "no row for ana@example.com at 1234.56 in https://h/p?account=x#y, error #185"
    )
    assert "ana@example.com" not in text and "<email>" in text
    assert "1234.56" not in text and "9999.99" in text
    assert "account=x" not in text and "https://h/p" in text
    assert "#185" in text  # a React error code is not a reader's data


def test_a_flood_is_dropped_quietly(client, caplog):
    caplog.set_level(logging.WARNING)
    for _ in range(route.MAX_PER_HOUR + 5):
        response = client.post("/v1/client-error", json={"message": "loop"})
        assert response.status_code == 204
    assert len(_logged(caplog)) == route.MAX_PER_HOUR


def test_extra_fields_are_refused(client):
    response = client.post("/v1/client-error", json={"message": "x", "book": [1]})
    assert response.status_code == 422
