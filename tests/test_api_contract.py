"""The conventions of docs/API.md, enforced over the whole route table."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from stocks.api.app import app

ALLOWED_TOP = {"error", "detail", "reason"}

#: Models that spell their fields as the AG-UI protocol does (docs/API.md,
#: "v2 candidates"). Nothing else may be camelCase.
CAMEL_BY_PROTOCOL = {
    "ActivityMessage", "AssistantMessage", "DataSource", "DeveloperMessage",
    "FileSource", "ReasoningMessage", "ResumeEntry", "Run", "SurfacePress",
    "SystemMessage", "ToolCall", "ToolMessage", "UrlSource", "UserMessage",
}  # fmt: skip


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr("stocks.api.security.configured_token", lambda: "tok")
    return TestClient(app, raise_server_exceptions=False)


def _paths() -> list[str]:
    """Every declared path. The OpenAPI schema, not `app.routes`: included
    routers are nested there and a walk of the top level sees none of them."""
    paths = list(app.openapi()["paths"])
    assert len(paths) > 100
    return paths


def _assert_envelope(resp, status: int, code: str) -> dict:
    assert resp.status_code == status, resp.text
    data = resp.json()
    assert set(data) <= ALLOWED_TOP
    assert data["error"]["code"] == code
    assert isinstance(data["error"]["message"], str) and data["error"]["message"]
    assert "detail" in data  # the shell's fetch helpers read it
    return data


def test_every_route_lives_under_the_version_prefix():
    bad = [p for p in _paths() if not p.startswith("/v1/")]
    assert not bad


def test_paths_are_lowercase_kebab_with_snake_params():
    for path in _paths():
        for seg in path.split("/")[1:]:
            if seg.startswith("{"):
                assert re.fullmatch(r"\{[a-z][a-z0-9_]*\}", seg), path
            else:
                assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*(\.(md|csv|zip))?", seg), path


def test_query_params_and_fields_are_snake_case():
    snake = re.compile(r"[a-z][a-z0-9_]*")
    schema = app.openapi()
    for path, item in schema["paths"].items():
        for op in item.values():
            for param in op.get("parameters", []):
                assert snake.fullmatch(param["name"]) or param["name"].lower() == param[
                    "name"
                ], (path, param["name"])
    for name, comp in schema["components"]["schemas"].items():
        if name in CAMEL_BY_PROTOCOL:
            continue
        for field in comp.get("properties", {}):
            assert snake.fullmatch(field) or field.lower() == field, (name, field)


def test_paging_is_limit_offset_everywhere():
    seen = set()
    for path, item in app.openapi()["paths"].items():
        for method, op in item.items():
            names = {p["name"] for p in op.get("parameters", [])}
            seen |= names & {"limit", "offset", "cursor", "page", "page_size", "per_page"}
            assert not names & {"cursor", "page", "page_size", "per_page"}, (path, method)
    assert "limit" in seen and "offset" in seen


def test_the_paged_ledger_keeps_its_bounds():
    params = {
        p["name"]: p["schema"]
        for p in app.openapi()["paths"]["/v1/portfolio/transactions"]["get"][
            "parameters"
        ]
    }
    assert (params["limit"]["default"], params["limit"]["maximum"]) == (200, 1000)
    assert (params["offset"]["default"], params["offset"]["minimum"]) == (0, 0)


def test_unknown_path_is_a_404_envelope(client):
    _assert_envelope(client.get("/v1/no-such-thing"), 404, "not_found")


def test_wrong_method_is_a_405_envelope(client):
    _assert_envelope(client.delete("/v1/health"), 405, "method_not_allowed")


def test_unauthenticated_is_a_401_envelope_with_its_header(client):
    resp = client.get("/v1/journal")
    data = _assert_envelope(resp, 401, "unauthenticated")
    assert resp.headers["www-authenticate"] == "Bearer"
    assert data["detail"] == data["error"]["message"]


def test_invalid_input_is_a_422_envelope_keeping_the_detail_list(client):
    @app.get("/v1/_typed_for_contract_test")
    def typed(n: int) -> dict:
        return {"n": n}

    try:
        resp = client.get("/v1/_typed_for_contract_test?n=x")
    finally:
        app.router.routes.pop()
    data = _assert_envelope(resp, 422, "validation_error")
    assert isinstance(data["detail"], list) and data["detail"][0]["loc"]
    assert "n" in data["error"]["message"]


def test_a_handwritten_422_is_an_envelope_with_its_sentence(client):
    resp = client.get(
        "/v1/portfolio/transactions", headers={"Authorization": "Bearer tok"}
    )
    data = _assert_envelope(resp, 422, "validation_error")
    assert data["detail"] == data["error"]["message"]


def test_a_missing_account_is_a_404_envelope(client, monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKS_DATA_DIR", str(tmp_path))
    resp = client.get(
        "/v1/portfolio/transactions?account=nobody@example.com",
        headers={"Authorization": "Bearer tok"},
    )
    assert resp.status_code in (404, 503)
    assert "error" in resp.json()


def test_upstream_refusal_keeps_reason_and_retry_after(client):
    from stocks.api.app import _unavailable

    class Req:
        class url:
            path = "/v1/x"

    resp = _unavailable(Req(), "rate_limited")  # type: ignore[arg-type]
    assert resp.status_code == 503 and resp.headers["retry-after"] == "60"
    import json

    data = json.loads(resp.body)
    assert data["reason"] == "rate_limited"
    assert data["error"]["code"] == "unavailable"


def test_an_unhandled_bug_is_a_500_envelope_without_the_exception_text(client):
    @app.get("/v1/_boom_for_contract_test")
    def boom():
        raise RuntimeError("secret /path")

    try:
        data = _assert_envelope(
            client.get("/v1/_boom_for_contract_test"), 500, "internal_error"
        )
    finally:
        app.router.routes.pop()
    assert "secret" not in str(data)
