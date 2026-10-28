"""Every document the server writes ships an enforcing CSP it actually meets."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from stocks.web import csp, landing, landing_static, server
from tests.csp_check import assert_enforced


@pytest.fixture(autouse=True)
def shell(tmp_path, monkeypatch):
    """A built shell on disk, with the markers the server fills."""
    build = tmp_path / "app"
    build.mkdir()
    (build / "index.html").write_text(
        "<html><head><!--AG-TOKENS--><!--AG-FONTS--></head><body>APP-SHELL</body></html>"
    )
    monkeypatch.setattr(server, "_APP_BUILD", build)
    server._app_document.cache_clear()
    server._app_policy.cache_clear()
    server._manifest.cache_clear()
    yield build
    server._app_document.cache_clear()
    server._app_policy.cache_clear()


@pytest.fixture
def client(monkeypatch):
    landing_static.document.cache_clear()
    server._gzipped.cache_clear()
    server._landing_csp.cache_clear()
    monkeypatch.setattr(server, "secret", lambda *a, **k: "")
    app = Starlette(
        routes=server.routes,
        middleware=[Middleware(server.SecurityHeaders), Middleware(server.LandingGate)],
    )
    return TestClient(app, base_url="https://topstocks.example")


def test_the_landing_in_both_languages_is_enforced(client):
    for path in ("/", "/es/"):
        r = client.get(path)
        assert r.status_code == 200
        assert_enforced(r)


def test_the_landing_has_no_style_attributes():
    for lang in ("en", "es"):
        assert 'style="' not in landing_static.document(lang, "https://x.example")
    assert 'style="' not in landing.page_body()


def test_the_landing_without_gzip_is_enforced(client):
    assert_enforced(client.get("/", headers={"accept-encoding": "identity"}))


@pytest.mark.parametrize("path", ["/legal/privacy", "/legal/terms?lang=es"])
def test_the_legal_pages_are_enforced(client, path):
    assert_enforced(client.get(path))


def test_the_404_is_enforced(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404
    assert_enforced(r)
    assert_enforced(client.get("/legal/nonsense"))


def test_the_app_shell_is_enforced(client):
    r = client.get("/portfolio")
    assert r.status_code == 200
    assert "APP-SHELL" in r.text
    assert_enforced(r)
    # What the shell reaches beyond itself, and nothing more.
    policy = r.headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in policy
    assert "connect-src 'self' https://openrouter.ai" in policy


def test_the_ticker_link_card_does_not_loosen_the_shell(client):
    plain = client.get("/ticker").headers["content-security-policy"]
    r = client.get("/ticker?ticker=AAPL")
    assert 'property="og:title"' in r.text
    assert_enforced(r)
    assert r.headers["content-security-policy"] == plain


def test_a_hash_covers_exactly_the_block_it_names():
    styles, scripts = csp.inline_blocks(
        "<style>a{}</style><script>x()</script>"
        '<script src="/a.js"></script><script type="application/ld+json">{}</script>'
    )
    assert styles == [csp.source("a{}")]
    assert scripts == [csp.source("x()")]


def test_a_reflected_value_never_reaches_the_policy(client):
    r = client.get("/ticker?ticker=AAPL<script>alert(1)</script>")
    assert csp.source("alert(1)") not in r.headers["content-security-policy"]


def test_the_boot_block_is_data_and_changes_nothing_in_the_policy(
    client, sign_in, monkeypatch, tmp_path
):
    """The per-request JSON the shell starts from is written after the policy
    was hashed from the build-constant document, and is not code: a session's
    document and a guest's ship the same header, and both are enforced."""
    import json

    from stocks import accounts
    from stocks.api import loaders

    email = "reader@example.com"
    users = tmp_path / "users"
    paths = accounts.paths_for(email, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.prefs.write_text(json.dumps({"currency": "EUR", "language": "es"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda e, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)

    guest = client.get("/portfolio")
    assert 'id="ag-boot"' in guest.text
    assert_enforced(guest)
    sign_in(client, email)
    signed = client.get("/portfolio")
    assert f'"email":"{email}"' in signed.text
    assert_enforced(signed)
    assert (
        signed.headers["content-security-policy"]
        == guest.headers["content-security-policy"]
    )
