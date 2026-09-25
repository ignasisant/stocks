"""Browser tests: the built React shell, served by the real ASGI app, in Chromium.

    uv run playwright install chromium     # once per machine
    uv run pytest -m e2e                   # the default run leaves these out

The server is `tests/e2e/serve.py` in a process of its own — that file says
what it seals off and why. One server for the session: booting the app costs
seconds, and every test gets its own account directory anyway, so nothing a
test writes is seen by the next.

What these tests can see is the app with Yahoo unreachable. That is on
purpose, not a gap: it is the only market-data state that is the same on
every machine, and it is also the state a throttled Cloud Run IP puts real
users in — the one that most needs to keep rendering.
"""

from __future__ import annotations

import itertools
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page

HERE = Path(__file__).parent
SECRET = "e2e-cookie-signing-secret-long-enough"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_root(tmp_path_factory) -> Path:
    """Where the server keeps every account it is asked about."""
    return tmp_path_factory.mktemp("e2e-data")


@pytest.fixture(scope="session")
def base_url(server_root: Path) -> Iterator[str]:
    """The app, booted and answering. Overrides pytest-base-url's fixture, so
    `page.goto("/portfolio")` resolves against it."""
    port = _free_port()
    log = (server_root / "server.log").open("w")
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "serve.py"), str(port), str(server_root)],
        env={**os.environ, "AUTH_COOKIE_SECRET": SECRET},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while True:
        try:
            urllib.request.urlopen(f"{url}/healthz", timeout=1)
            break
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                log.close()
                pytest.fail(
                    "e2e server did not come up:\n"
                    + (server_root / "server.log").read_text()[-3000:]
                )
            time.sleep(0.25)
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()


@pytest.fixture
def browser_context_args(browser_context_args: dict) -> dict:
    """English, whatever the machine's locale — the tests read UI copy."""
    return {**browser_context_args, "locale": "en-US"}


_accounts = itertools.count()


def settled() -> dict:
    """The prefs of an account that has been here before and is caught up:
    tour taken, guide finished, latest release seen, investor profile saved.
    Nothing opens over the page it asked for, which is what a test about that
    page wants — the profile is in this list for the same reason the other
    three are: `ProfilePrompt` nags for it on every session until it is set,
    same as it stands the tour and the release list down, and a "caught up"
    account that still triggered it would fail every test in this file for a
    reason none of them are about."""
    from stocks.web import guide, onboarding

    return {
        onboarding.PREF_DONE: True,
        onboarding.PREF_SEEN_VERSION: onboarding.CURRENT_VERSION,
        guide.PREF_DONE: True,
        "investor_profile": {"set": True},
    }


@pytest.fixture
def sign_in(
    context: BrowserContext, base_url: str, server_root: Path, monkeypatch
) -> Callable[..., Path]:
    """Sign this test's browser in as a new account, and hand back its dir.

    Caught up by default (`settled`); `fresh=True` for one that has never been
    here. `prefs` go over either, written before the first request — which is
    how a test starts from "was last here two releases ago" without clicking
    its way there.
    """
    monkeypatch.setenv("AUTH_COOKIE_SECRET", SECRET)
    from stocks import accounts, session

    def _sign_in(prefs: dict | None = None, *, fresh: bool = False) -> Path:
        email = f"e2e-{os.getpid()}-{next(_accounts)}@example.com"
        root = server_root / "users" / accounts.slug(email)
        root.mkdir(parents=True)
        written = {"language": "en", **({} if fresh else settled()), **(prefs or {})}
        (root / "prefs.json").write_text(json.dumps(written))
        # What the OIDC callback leaves behind on a first sign-in; the API
        # answers 404 for an address with neither a watchlist nor a ledger.
        (root / "watchlist.yaml").write_text(accounts.STARTER_WATCHLIST)
        token = session.mint({"email": email, "email_verified": True, "name": "E2E"})
        assert token, "session.mint refused the test secret"
        context.add_cookies([{"name": session.COOKIE, "value": token, "url": base_url}])
        return root

    return _sign_in


@pytest.fixture(autouse=True)
def no_uncaught_errors(page: Page) -> Iterator[list[str]]:
    """Fail any test whose page threw an exception nobody caught.

    Uncaught errors only, not every `console.error`: a refused API call logs
    one of those, and refusing is what the API does for a guest on a private
    endpoint and for everybody while Yahoo is down.
    """
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    yield errors
    assert not errors, f"uncaught errors on the page: {errors}"


@pytest.fixture(autouse=True)
def no_server_errors(page: Page) -> Iterator[list[str]]:
    """Fail any test during which the server answered 500.

    A 503 is the API saying the upstream is throttling it — the state this
    suite runs in — and a 401 is a guest asking for something private. A 500
    is a crash, whoever asked.
    """
    crashes: list[str] = []
    page.on(
        "response",
        lambda r: r.status == 500 and crashes.append(f"{r.request.method} {r.url}"),
    )
    yield crashes
    assert not crashes, f"the server answered 500: {crashes}"
