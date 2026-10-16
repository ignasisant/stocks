"""Load generator: simulated readers walking the shell's pages.

Server, in load-test mode (fakes every upstream, see `stocks.loadtest`):

    STOCKS_LOADTEST=1 STOCKS_LOADTEST_SECRET=s3cret STOCKS_DATA_DIR=$(mktemp -d) \
        TRUSTED_PROXY_HOPS=0 uv run stocks dashboard --port 8502

Generator, same secret (it signs the readers' session cookies):

    STOCKS_LOADTEST_SECRET=s3cret uv run --with locust locust \\
        -f loadtest/locustfile.py --host http://localhost:8502 \\
        -u 1000 -r 5 --run-time 20m --headless --csv out/run1

Drop `--headless` for the live UI on :8089. To find where it breaks, step
the load instead: LOADTEST_STEPS=50,100,200,400 holds each user count for
LOADTEST_STEP_S seconds (default 60) and ignores -u/-r/--run-time.

Past a few hundred users one generator process saturates a core: add
`--processes -1`.

Each simulated reader is either signed in (its own synthetic account, the demo
book provisioned on its first request) or a guest (the shared demo book), and
comes from its own made-up address in X-Forwarded-For, so the per-address
throttle meters it as a person rather than lumping a thousand into one. That
needs the server to trust the header: run it with TRUSTED_PROXY_HOPS=0
locally. On Cloud Run it trusts the entry before the last one, which is
this header only if Cloud Run appends exactly one hop. A run there whose API
calls come back 429 `throttled` means it does not, and every reader is being
metered as one address.

A page visit fires its calls together, the way the browser does, and is also
reported as one `PAGE` row — the wall time a reader waits for that screen.
Between pages a reader thinks for 5-15 s, so 1000 readers is ~100 API req/s.

Refuses any host that is not local or a -staging service, unless
LOADTEST_ALLOW_HOST=1: the readers' cookies are worthless elsewhere, but their
guests and their traffic are not.
"""

from __future__ import annotations

import itertools
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from gevent.pool import Group
from locust import HttpUser, LoadTestShape, between, events, task

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stocks import loadtest, session  # noqa: E402
from stocks.loadtest.fakes import WATCHLIST_EXTRA  # noqa: E402
from stocks.portfolio.demo import TICKERS  # noqa: E402

GUEST_SHARE = float(os.environ.get("LOADTEST_GUEST_SHARE", "0.2"))
TICKER_POOL = [*TICKERS, *WATCHLIST_EXTRA]
_ids = itertools.count(1)


@events.init.add_listener
def _check(environment, **_kw):
    secret = os.environ.get(loadtest.SECRET_ENV, "").strip()
    if not secret:
        raise SystemExit(f"set {loadtest.SECRET_ENV} to the server's value")
    # `session.mint` signs with this; the server swapped it for the same value.
    os.environ["AUTH_COOKIE_SECRET"] = secret
    host = urlparse(environment.host or "").hostname or ""
    local = host in ("localhost", "127.0.0.1", "::1")
    if not (local or "-staging" in host or os.environ.get("LOADTEST_ALLOW_HOST") == "1"):
        raise SystemExit(f"refusing {host!r}: not local, not -staging")


class Reader(HttpUser):
    wait_time = between(5, 15)

    def on_start(self):
        # `--processes N` forks N workers, each counting from 1 on its own: the
        # worker's index keeps their readers (and addresses) apart.
        worker = getattr(self.environment.runner, "worker_index", 0) or 0
        n = worker * 100_000 + next(_ids)
        ip = f"10.{n >> 16 & 255}.{n >> 8 & 255}.{n & 255}"
        self.client.headers["X-Forwarded-For"] = ip
        self.guest = random.random() < GUEST_SHARE
        if not self.guest:
            address = loadtest.email(n)
            cookie = session.mint(
                {"email": address, "email_verified": True, "name": f"Load {n}"}
            )
            self.client.cookies.set(session.COOKIE, cookie)
        # One call on its own before the first page: it provisions the
        # account, which the page's dozen parallel calls would otherwise race.
        self.client.get("/api/v1/me", name="/api/v1/me")

    def _get(self, path: str, name: str) -> int:
        """One call; a guest's 401 is the shell's answer, not a failure."""
        with self.client.get(path, name=name, catch_response=True) as r:
            if r.status_code == 401 and self.guest:
                r.success()
                return 200
            return r.status_code

    def _page(self, page: str, ticker: str = "") -> None:
        calls = [f"/api{p.format(t=ticker)}" for p in loadtest.PAGES[page]]
        names = [f"/api{p}" for p in loadtest.PAGES[page]]
        start = time.perf_counter()
        group = Group()
        spawned = [
            group.spawn(self._get, path, name)
            for path, name in zip(calls, names, strict=True)
        ]
        group.join()
        failed = [g for g in spawned if g.value is None or g.value >= 400]
        events.request.fire(
            request_type="PAGE",
            name=page,
            response_time=(time.perf_counter() - start) * 1000,
            response_length=0,
            exception=Exception(f"{len(failed)} calls failed") if failed else None,
            context={},
        )

    @task(35)
    def home(self):
        self._page("home")

    @task(20)
    def portfolio(self):
        self._page("portfolio")

    @task(25)
    def ticker(self):
        self._page("ticker", random.choice(TICKER_POOL))

    @task(5)
    def earnings(self):
        self._page("earnings")

    @task(5)
    def sector(self):
        self._page("sector")

    @task(5)
    def sentiment(self):
        self._page("sentiment")

    @task(3)
    def profile(self):
        self._page("profile")

    @task(2)
    def imports(self):
        self._page("import")


if os.environ.get("LOADTEST_STEPS"):

    class Steps(LoadTestShape):
        """Each user count in LOADTEST_STEPS, held LOADTEST_STEP_S seconds."""

        steps = [int(n) for n in os.environ["LOADTEST_STEPS"].split(",")]
        hold = int(os.environ.get("LOADTEST_STEP_S", "60"))

        def tick(self):
            i = int(self.get_run_time() // self.hold)
            if i >= len(self.steps):
                return None
            return self.steps[i], max(1, self.steps[i] // 10)
