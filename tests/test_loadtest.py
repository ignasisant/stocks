"""Load-test mode (stocks.loadtest): where it refuses to run, and what it does.

The refusals run in-process — they raise before touching anything. The mode
itself replaces functions process-wide for good, so it boots in a subprocess.
"""

import json
import os
import re
import subprocess
import sys
import textwrap

import pytest

from stocks import loadtest


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("K_SERVICE", loadtest.SECRET_ENV, "STOCKS_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(loadtest, "_installed", False)
    return monkeypatch


def test_refuses_any_cloud_run_service_but_staging(clean_env):
    clean_env.setenv("K_SERVICE", "topstocks")
    clean_env.setenv(loadtest.SECRET_ENV, "x")
    with pytest.raises(RuntimeError, match="topstocks"):
        loadtest.install()


def test_refuses_the_checkouts_own_data_dir(clean_env):
    clean_env.setenv(loadtest.SECRET_ENV, "x")
    with pytest.raises(RuntimeError, match="STOCKS_DATA_DIR"):
        loadtest.install()


def test_refuses_without_its_own_cookie_secret(clean_env):
    clean_env.setenv("K_SERVICE", "topstocks-staging")
    with pytest.raises(RuntimeError, match=loadtest.SECRET_ENV):
        loadtest.install()


def test_synthetic_addresses():
    assert loadtest.email(7) == "load-0007@loadtest.invalid"
    assert loadtest.synthetic(loadtest.email(7))
    assert not loadtest.synthetic("someone@example.com")


def test_every_page_call_is_a_route():
    """The generator replays `PAGES`; a renamed endpoint must fail here, not
    show up as a wall of 404s in the middle of a load test."""
    from stocks.api.app import app

    patterns = [
        re.compile(re.sub(r"\{[^}]+\}", "[^/]+", path) + "$")
        for path, ops in app.openapi()["paths"].items()
        if "get" in ops
    ]
    missing = [
        path
        for paths in loadtest.PAGES.values()
        for path in paths
        if not any(p.match(path.format(t="AAPL")) for p in patterns)
    ]
    assert not missing


_BOOT = textwrap.dedent("""
    import json, os, socket
    from fastapi.testclient import TestClient
    from stocks import loadtest, session
    from stocks.api.app import app

    out = {}
    # Signed with the deployment's real secret, before the mode swaps it.
    os.environ["AUTH_COOKIE_SECRET"] = "the-prod-secret"
    foreign = session.mint({"email": "real@example.com", "email_verified": True})
    with TestClient(app, raise_server_exceptions=False) as c:  # runs the lifespan
        out["foreign"] = c.get("/v1/me", cookies={session.COOKIE: foreign}).json()["kind"]
        c.cookies.set(session.COOKIE, session.mint(
            {"email": loadtest.email(1), "email_verified": True, "name": "L"}))
        r = c.get("/v1/portfolio/positions")
        out["positions"] = r.status_code, len(r.json().get("positions") or [])
        out["watchlist"] = len(c.get("/v1/watchlist").json().get("entries") or [])
        out["quote"] = c.get("/v1/ticker/AAPL/quote").status_code
        try:
            socket.create_connection(("192.0.2.1", 80), timeout=1)
            out["outbound"] = "open"
        except OSError:
            out["outbound"] = "blocked"
    print("RESULT" + json.dumps(out))
""")


def test_boots_with_fakes_and_a_demo_book(tmp_path):
    env = dict(os.environ)
    env.pop("K_SERVICE", None)
    env.update({
        loadtest.ENV: "1",
        loadtest.SECRET_ENV: "test-secret",
        "STOCKS_DATA_DIR": str(tmp_path / "data"),
    })
    # cwd outside the checkout: no .streamlit/secrets.toml, so no bucket and
    # no owner to resolve, whatever the developer's machine carries.
    run = subprocess.run(
        [sys.executable, "-c", _BOOT], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=180,
    )
    line = next((s for s in run.stdout.splitlines() if s.startswith("RESULT")), None)
    assert line, run.stderr[-2000:]
    out = json.loads(line.removeprefix("RESULT"))

    status, positions = out["positions"]
    assert status == 200 and positions > 0  # the demo book, not a starter
    assert out["watchlist"] > 20
    assert out["quote"] == 200
    assert out["outbound"] == "blocked"
    assert out["foreign"] == "guest"  # a real session opens nothing here
    # Every cache and account went to the scratch dir, none to the checkout.
    assert any((tmp_path / "data" / "users").glob("load_0001_*"))
