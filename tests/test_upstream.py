"""A local dashboard serves the production account while the backend matches.

`web/upstream.py` forwards `/api` and the logo mirror to production when the
checkout's backend is the commit production runs, and keeps everything local
otherwise. These pin the choice, and that a forwarded request arrives as the
browser sent it — cookie, query, body — and comes back untouched.
"""

import subprocess

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from stocks.web import upstream


@pytest.mark.parametrize("setting", ["", "local", "  local "])
def test_local_and_unset_keep_the_api_here(setting, monkeypatch):
    monkeypatch.setattr(upstream, "prod_commit", lambda: pytest.fail("no probe"))
    assert upstream.resolve(setting).base == ""


def test_prod_and_a_url_are_forced(monkeypatch):
    monkeypatch.setattr(upstream, "prod_commit", lambda: pytest.fail("no probe"))
    assert upstream.resolve("prod").base == upstream.PROD_URL
    assert upstream.resolve("http://localhost:9000/").base == "http://localhost:9000"


def test_auto_follows_production_only_while_the_backend_matches(monkeypatch):
    monkeypatch.setattr(upstream, "prod_commit", lambda: "abc1234567")
    monkeypatch.setattr(upstream, "backend_changes", lambda commit: [])
    assert upstream.resolve("auto").base == upstream.PROD_URL

    monkeypatch.setattr(upstream, "backend_changes", lambda commit: ["src/x.py"])
    choice = upstream.resolve("auto")
    assert choice.base == "" and "src/x.py" in choice.why

    # A commit this checkout never fetched cannot be compared: stay local.
    monkeypatch.setattr(upstream, "backend_changes", lambda commit: None)
    assert "git fetch" in upstream.resolve("auto").why


def test_auto_stays_local_when_production_does_not_answer(monkeypatch):
    monkeypatch.setattr(upstream, "prod_commit", lambda: None)
    assert upstream.resolve("auto").base == ""


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_backend_changes_ignore_the_bundle_and_count_new_files(tmp_path, monkeypatch):
    bundle = tmp_path / "src" / "stocks" / "web" / "static" / "app"
    bundle.mkdir(parents=True)
    (bundle / "app.js").write_text("one")
    (tmp_path / "src" / "a.py").write_text("one")
    (tmp_path / "frontend.ts").write_text("one")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(upstream, "PROJECT_ROOT", tmp_path)

    assert upstream.backend_changes(head) == []
    (bundle / "app.js").write_text("two")
    (tmp_path / "frontend.ts").write_text("two")
    assert upstream.backend_changes(head) == []

    (tmp_path / "src" / "a.py").write_text("two")
    (tmp_path / "src" / "b.py").write_text("new")
    assert upstream.backend_changes(head) == ["src/a.py", "src/b.py"]
    assert upstream.backend_changes("0" * 40) is None


class _Transport(httpx.AsyncBaseTransport):
    """`httpx.MockTransport` reads the body before handing it over, which the
    proxy's raw stream then cannot; this hands it over unread, like a socket."""

    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request):
        await request.aread()
        return self.handler(request)


def _proxy_through(monkeypatch, handler):
    client = httpx.AsyncClient(transport=_Transport(handler))
    monkeypatch.setattr(upstream, "_client", client)


def _app():
    async def here(request):
        return PlainTextResponse("local")

    return Starlette(
        routes=[Route("/{path:path}", here, methods=["GET", "POST"])],
        middleware=[Middleware(upstream.Upstream, base="https://prod.test")],
    )


def test_the_account_paths_go_upstream_as_sent(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, stream=httpx.ByteStream(b"from prod"),
                              headers={"x-prod": "1", "set-cookie": "a=b; Path=/"})

    _proxy_through(monkeypatch, handler)
    client = TestClient(_app())
    client.cookies.set("ts_session", "signed")

    response = client.post("/api/v1/chat?thread=c_1", json={"text": "hola"})
    assert (response.status_code, response.text) == (201, "from prod")
    assert response.headers["x-prod"] == "1"
    assert response.cookies.get("a") == "b"
    (sent,) = seen
    assert str(sent.url) == "https://prod.test/api/v1/chat?thread=c_1"
    assert sent.headers["host"] == "prod.test"
    assert "ts_session=signed" in sent.headers["cookie"]
    assert sent.content == b'{"text":"hola"}'

    assert client.get("/app/static/logo.png").text == "from prod"
    assert client.get("/portfolio").text == "local"
    assert len(seen) == 2


def test_an_unreachable_production_is_a_502(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down")

    _proxy_through(monkeypatch, handler)
    response = TestClient(_app()).get("/api/v1/me")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unreachable"
