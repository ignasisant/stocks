"""The whole app on one port, sealed off from everything it normally talks to.

Run by `tests/e2e/conftest.py` as its own process, never imported by a test:

    python tests/e2e/serve.py <port> <root>

A process of its own rather than a uvicorn thread inside pytest, because the
suite's autouse fixtures (tests/conftest.py) rewrite module globals such as
`accounts.GUEST_DIR` around every test, and a server sharing those globals
would see its guest book vanish between one browser test and the next.

What is sealed, and why each one:

* **accounts** live under `<root>`: `<root>/users/<slug>` for a signed-in
  browser, `<root>/guest` for an anonymous one. No test can read or write the
  checkout's `data/`, and no owner email maps a session onto the repo-root book.
* **the bucket** is off. A developer machine carries `[storage]` secrets, and a
  test run that persisted its fabricated books into production R2 would be a
  real incident.
* **Yahoo** is behind a tripped circuit breaker, so every fetch site takes the
  degraded path it already has for a throttled Cloud IP — which is the one
  path that is the same on every machine.
* **exchange rates** come from a fixed table, answered in-process: a book
  holding dollars cannot be replayed without them, and a checkout's own
  `data/fx_history.json` would otherwise answer on a developer machine and
  leave CI with a 503 on every page that prices one.
* **the on-disk memos** (`data/memo/`, `data/form4.json`) live under `<root>`
  too, for the same reason: frames salvaged from a real session would render
  a page here that renders nowhere else.
* **the chat** answers from a script: no provider, no key, no daily cap, and
  the same words every time.
* **the secrets file** is one that does not exist: a developer machine's
  `.streamlit/secrets.toml` carries the free model chain's keys, and with them
  every statement preview asked a model first — refused at the socket, then
  retried after `llm_map`'s pause — and took longer than the import test
  waits, on that machine only. CI has no file; now neither does anyone else.
* **the burst limit** is lifted: the whole suite is one client on loopback.
* **the network** refuses anything but loopback, so the next outbound call
  somebody adds fails loudly here instead of making the suite flaky.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import sys
from pathlib import Path

#: The chat's scripted answer. The tests read it back off the page.
CHAT_ANSWER = "Respuesta de prueba: la cartera está bien diversificada."


def _seal_network() -> None:
    real_connect = socket.socket.connect

    def connect(self, address):  # noqa: ANN001 — socket's own signature
        host = address[0] if isinstance(address, tuple) else address
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost" or self.family == socket.AF_UNIX
        if not loopback:
            raise ConnectionRefusedError(f"e2e: outbound connection to {host!r} blocked")
        return real_connect(self, address)

    socket.socket.connect = connect  # type: ignore[method-assign]
    # Name resolution is where most clients start; refusing it here means they
    # fail fast rather than after a resolver timeout.
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if host not in (None, "localhost", "127.0.0.1", "::1"):
            raise socket.gaierror(f"e2e: name resolution for {host!r} blocked")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo


def _seal_accounts(root: Path) -> None:
    from stocks import accounts, storage

    users = root / "users"
    guest = root / "guest"
    users.mkdir(parents=True, exist_ok=True)
    real_paths_for = accounts.paths_for

    accounts.GUEST_DIR = guest
    accounts.USERS_DIR = users
    accounts.paths_for = lambda email, owner=None, users_dir=users: real_paths_for(  # type: ignore[assignment]
        email, None, users_dir
    )
    accounts.configured_owner = lambda: None  # type: ignore[assignment]
    storage.enabled = lambda: False  # type: ignore[assignment]
    from stocks.api import cache
    from stocks.data import insiders

    cache.MEMO_DIR = root / "memo"
    insiders.FORM4_CACHE = root / "form4.json"
    insiders.clear_form4_cache()


def _seal_secrets(root: Path) -> None:
    from stocks import secrets_env

    secrets_env.SECRETS_FILE = root / "no-secrets.toml"


def _seal_yahoo() -> None:
    from stocks.data import fetch

    fetch.trip_throttle(cooldown=10**9)


#: Units of each currency per euro. Round on purpose: a figure on the page is
#: then the fixture's arithmetic, never a real day's rate.
PER_EUR = {"EUR": 1.0, "USD": 1.1, "GBP": 0.85, "CHF": 0.95}


def _script_fx(root: Path) -> None:
    """Answer the three frankfurter shapes `stocks.data.fx` asks for — latest,
    one day, a range — from `PER_EUR`, without a socket."""
    from datetime import date
    from urllib.parse import parse_qs, urlparse

    import pandas as pd

    from stocks.data import fx

    fx.FX_CACHE = root / "fx_history.json"
    fx._MEM_CACHE = None

    def get_json(url: str, timeout: float = 15) -> dict:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        base, quote = query["base"][0], query["symbols"][0]
        rate = PER_EUR.get(quote, 1.0) / PER_EUR.get(base, 1.0)
        when = parsed.path.rsplit("/", 1)[1]
        if ".." in when:
            start, end = when.split("..")
            days = pd.bdate_range(start, end)
            return {"rates": {d.date().isoformat(): {quote: rate} for d in days}}
        day = date.today().isoformat() if when == "latest" else when
        return {"rates": {quote: rate}, "date": day}

    fx.get_json = get_json  # type: ignore[assignment]


def _script_chat() -> None:
    from stocks.chat import engine

    def answer_stream(**_kwargs):
        yield "phase", "writing"
        yield "meta", {
            "provider": "e2e", "model": "scripted", "skills": [], "sources": [],
        }
        for word in CHAT_ANSWER.split(" "):
            yield "text", word + " "
        yield "done", engine.Reply(text=CHAT_ANSWER, provider_id="e2e")

    engine.answer_stream = answer_stream  # type: ignore[assignment]


def main() -> None:
    port, root = int(sys.argv[1]), Path(sys.argv[2])
    os.environ.setdefault("AUTH_COOKIE_SECRET", "e2e-cookie-signing-secret-long-enough")
    # `session.sign_in_configured()` also needs these three before a guest gets
    # a real "Sign in with Google" link instead of "not set up yet" — sealed
    # here like every other secret, so the suite reads the same whether or not
    # the machine running it has a real .streamlit/secrets.toml on its cwd.
    # Never dialed: `_seal_network()` refuses anything past loopback before a
    # click could reach Google with these.
    os.environ.setdefault("AUTH_CLIENT_ID", "e2e-client-id")
    os.environ.setdefault("AUTH_CLIENT_SECRET", "e2e-client-secret")
    os.environ.setdefault("AUTH_REDIRECT_URI", f"http://127.0.0.1:{port}/oauth2callback")

    _seal_network()
    _seal_secrets(root)
    _seal_accounts(root)
    _seal_yahoo()
    _script_fx(root)
    _script_chat()

    import uvicorn

    from stocks.web import server

    # One client, 127.0.0.1, loading page after page: the per-IP burst limit
    # would start answering 429 halfway through the suite.
    server.CLIENT_MAX_DOCS = server.API_MAX_REQUESTS = 10**6
    app = server.app

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
