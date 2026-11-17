"""A catalog key no language has is logged as `i18n.missing`, an ERROR.

Server side from `i18n.translate`, browser side through
`POST /v1/missing-strings`. Asking whether a key exists (`i18n.has`) logs
nothing, and a key family the app builds from data ships a label for every
member — the journal's rule chips once drew `journal.action_dividend_cut`.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from stocks import obs
from stocks.api.app import app as fastapi_app
from stocks.chat.journal import CRITERION_RULES
from stocks.i18n import catalog, has, translate


@pytest.fixture(autouse=True)
def _fresh():
    from stocks import ratelimit

    ratelimit._events.clear()
    obs._once.clear()
    yield
    ratelimit._events.clear()
    obs._once.clear()


def _logged(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", "") == "i18n.missing"]


def test_a_key_no_catalog_has_is_one_error_line(caplog):
    caplog.set_level(logging.WARNING)
    assert translate("nowhere.at_all", "es") == "nowhere.at_all"
    assert translate("nowhere.at_all", "es") == "nowhere.at_all"
    [record] = _logged(caplog)
    assert record.levelno == logging.ERROR
    assert (record.key, record.lang, record.source) == ("nowhere.at_all", "es", "server")


def test_a_key_english_has_is_not_missing(caplog):
    caplog.set_level(logging.WARNING)
    translate("common.save", "it")
    assert not has("nowhere.at_all")
    assert _logged(caplog) == []


def test_the_browser_reports_keys_once_and_the_rest_are_dropped(caplog):
    caplog.set_level(logging.WARNING)
    client = TestClient(fastapi_app)
    response = client.post(
        "/v1/missing-strings",
        json={
            "lang": "es",
            "keys": [
                "nowhere.at_all", "common.save", "nowhere.at_all",
                "not a key", "nodot", "x." + "y" * 200,
            ],
            "where": "review?tab=journal",
        },
    )
    assert response.status_code == 204
    [record] = _logged(caplog)
    assert record.levelno == logging.ERROR
    assert (record.key, record.lang, record.source) == ("nowhere.at_all", "es", "browser")
    assert record.where == "review?tab=journal"


@pytest.mark.parametrize(
    "body",
    [
        {"keys": ["a.b"], "book": 1},
        {"keys": [f"x.k{i}" for i in range(51)]},
    ],
)
def test_a_body_out_of_shape_is_refused(body):
    response = TestClient(fastapi_app).post("/v1/missing-strings", json=body)
    assert response.status_code == 422


def test_every_rule_chip_has_a_label():
    english = catalog("en")
    assert [r for r in CRITERION_RULES if f"journal.action_{r}" not in english] == []
