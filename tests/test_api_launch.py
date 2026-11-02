"""`POST /v1/launch`: the app opened from a Home Screen becomes one `app.launch`."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from stocks.api.app import app as fastapi_app
from stocks.api.routes import launch as route

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/26.5 Mobile/15E148 Safari/604.1"
)


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
    return [r for r in caplog.records if getattr(r, "event", "") == "app.launch"]


def test_a_launch_is_logged_with_its_device(client, caplog):
    caplog.set_level(logging.INFO)
    response = client.post(
        "/v1/launch", json={"device": "ios"}, headers={"user-agent": IPHONE},
    )
    assert response.status_code == 204
    [record] = _logged(caplog)
    assert record.device == "ios"
    assert record.ua == "safari/ios"


def test_an_unknown_device_is_refused(client):
    assert client.post("/v1/launch", json={"device": "fridge"}).status_code == 422


def test_extra_fields_are_refused(client):
    assert client.post(
        "/v1/launch", json={"device": "ios", "email": "a@b.c"},
    ).status_code == 422


def test_a_flood_is_dropped_quietly(client, caplog):
    caplog.set_level(logging.INFO)
    for _ in range(route.MAX_PER_HOUR + 5):
        assert client.post("/v1/launch", json={"device": "android"}).status_code == 204
    assert len(_logged(caplog)) == route.MAX_PER_HOUR
