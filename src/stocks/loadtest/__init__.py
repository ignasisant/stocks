"""Load-test mode: the server answering simulated readers, upstreams faked.

    STOCKS_LOADTEST=1 STOCKS_LOADTEST_SECRET=<any string> \
        STOCKS_DATA_DIR=$(mktemp -d) uv run stocks dashboard --port 8502
    uv run --with locust locust -f loadtest/locustfile.py --host http://localhost:8502

`loadtest/locustfile.py` is the load generator; this is the server's half,
installed at boot by `api.app`'s lifespan when STOCKS_LOADTEST=1. Everything it
changes is process-wide and for the life of the process:

* market data and the LLM: `fakes.install_upstream`. A load test that reached
  Yahoo would measure Yahoo's throttle, not this app — and get the deployment's
  address throttled for the real readers sharing it;
* outbound network: any other connection to a non-loopback address is refused
  and logged once per host (`loadtest.blocked`), so a fetch site the fakes do
  not know shows up instead of quietly hitting the internet a thousand times;
* the data dir: a local run must point STOCKS_DATA_DIR at a scratch dir, or
  the fakes' prices land in the memos and caches the dev server reads;
* the bucket: off. Staging runs on the prod secret, whose [storage] is the
  prod bucket, and a thousand synthetic accounts do not belong in it;
* the cookie secret: replaced by STOCKS_LOADTEST_SECRET. The cookies the load
  generator mints then open nothing but a load-test process — not prod, which
  shares staging's secret — and a real session opens nothing here;
* a synthetic address (`load-0001@loadtest.invalid`) gets the demo book and a
  ~30-name watchlist when its first request provisions it, so it reads like a
  reader with positions rather than an empty starter.

Refuses to boot on any Cloud Run service whose name does not end in -staging,
and locally on the checkout's own data/.
"""

from __future__ import annotations

import errno
import ipaddress
import os
import socket
import threading

from stocks import obs

ENV = "STOCKS_LOADTEST"
SECRET_ENV = "STOCKS_LOADTEST_SECRET"
DOMAIN = "loadtest.invalid"

_installed = False
_seed_lock = threading.Lock()

# The GET calls each page of the shell makes when it mounts. Taken from the
# `get<…>("/…")` calls under frontend/app/src/pages/<page>/; the ones a click
# or a scroll triggers are left out. Relative to the API's mount (`/api`).
PAGES: dict[str, list[str]] = {
    "home": [
        "/v1/onboarding", "/v1/daily", "/v1/market/status",
        "/v1/portfolio/summary", "/v1/portfolio/positions",
        "/v1/portfolio/performance", "/v1/portfolio/history",
        "/v1/portfolio/transactions", "/v1/home/closes", "/v1/movers",
        "/v1/extremes", "/v1/earnings", "/v1/watchlist",
    ],
    "portfolio": [
        "/v1/market/status", "/v1/portfolio/summary",
        "/v1/portfolio/positions", "/v1/portfolio/performance",
        "/v1/portfolio/history", "/v1/portfolio/monthly", "/v1/movers",
        "/v1/portfolio/risk", "/v1/portfolio/dividends", "/v1/portfolio/fees",
        "/v1/portfolio/tax", "/v1/portfolio/projection",
        "/v1/portfolio/transactions",
    ],
    "ticker": [
        "/v1/ticker/{t}/quote", "/v1/ticker/{t}/bars", "/v1/ticker/{t}/trend",
        "/v1/ticker/{t}/profile",
        "/v1/ticker/{t}/metrics", "/v1/ticker/{t}/valuation",
        "/v1/ticker/{t}/financials", "/v1/ticker/{t}/events",
        "/v1/ticker/{t}/peers", "/v1/ticker/{t}/position",
        "/v1/ticker/{t}/insiders", "/v1/kpi-sources", "/v1/watchlist",
        "/v1/watchlist/tags", "/v1/alert-types",
    ],
    "earnings": ["/v1/earnings"],
    "sector": ["/v1/sectors"],
    "sentiment": ["/v1/pulse", "/v1/pulse/book", "/v1/pulse/tables"],
    "profile": [
        "/v1/me", "/v1/profile", "/v1/profile-options", "/v1/jurisdictions",
        "/v1/onboarding", "/v1/import/last", "/v1/notify/telegram",
        "/v1/watchlist", "/v1/watchlist/suggestions",
        "/v1/portfolio/transactions",
    ],
    "import": [
        "/v1/import/platforms", "/v1/import/last", "/v1/import/moves/scan",
        "/v1/import/splits/scan", "/v1/portfolio/performance",
        "/v1/portfolio/dividends",
    ],
}


def active() -> bool:
    return os.environ.get(ENV, "").strip().lower() in ("1", "true", "yes")


def email(n: int) -> str:
    """The address of simulated reader `n`."""
    return f"load-{n:04d}@{DOMAIN}"


def synthetic(address: str) -> bool:
    return address.strip().lower().endswith("@" + DOMAIN)


def install() -> None:
    """Put this process in load-test mode. Raises where it must not run."""
    global _installed
    if _installed:
        return
    service = os.environ.get("K_SERVICE", "")
    if service and not service.endswith("-staging"):
        raise RuntimeError(
            f"{ENV}=1 on Cloud Run service {service!r}: load-test mode fakes "
            "every price and runs only locally or on a -staging service"
        )
    from stocks.config import DATA_DIR, PROJECT_ROOT

    if not service and DATA_DIR == PROJECT_ROOT / "data":
        raise RuntimeError(
            f"{ENV}=1 locally needs STOCKS_DATA_DIR pointed at a scratch dir: "
            "the fakes would leave made-up prices in data/ for the dev server"
        )
    secret = os.environ.get(SECRET_ENV, "").strip()
    if not secret:
        raise RuntimeError(f"{ENV}=1 needs {SECRET_ENV}, the cookie secret it signs with")
    os.environ["AUTH_COOKIE_SECRET"] = secret

    from stocks import storage
    from stocks.loadtest import fakes

    storage.enabled = lambda: False
    fakes.install_upstream()
    _block_outbound()
    _seed_synthetic()
    _installed = True
    obs.warn("loadtest.on", service=service or "local")


def _loopback(sock: socket.socket, address: object) -> bool:
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return True  # unix sockets and the like never leave the machine
    host = str(address[0]) if isinstance(address, tuple) else str(address)
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _block_outbound() -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _refuse(address: object) -> None:
        host = str(address[0]) if isinstance(address, tuple) else str(address)
        obs.warn_once("loadtest.blocked", host, host=host)

    def connect(self, address):
        if not _loopback(self, address):
            _refuse(address)
            raise OSError(errno.ENETUNREACH, "outbound network is off in load-test mode")
        return real_connect(self, address)

    def connect_ex(self, address):
        if not _loopback(self, address):
            _refuse(address)
            return errno.ENETUNREACH
        return real_connect_ex(self, address)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]


def _seed_synthetic() -> None:
    """Give a synthetic account the demo book the moment it is provisioned."""
    import yaml

    from stocks import accounts, atomic
    from stocks.loadtest.fakes import WATCHLIST_EXTRA
    from stocks.portfolio import demo
    from stocks.web import onboarding

    real_provision = accounts.provision

    def provision(address, *args, **kwargs):
        paths, seeded = real_provision(address, *args, **kwargs)
        if not synthetic(address):
            return paths, seeded
        # A reader's first page fires a dozen requests at once, and each may
        # find the account missing; `demo.seed` refuses a non-empty ledger,
        # the watchlist merge is the part that must not interleave.
        with _seed_lock:
            demo.seed(paths.db)
            wl = yaml.safe_load(paths.watchlist.read_text()) or {}
            rows = list(wl.get("watchlist") or [])
            have = {str(r.get("ticker", "")).upper() for r in rows if isinstance(r, dict)}
            for t in [*demo.TICKERS, *WATCHLIST_EXTRA]:
                if t not in have:
                    rows.append({"ticker": t})
                    have.add(t)
            wl["watchlist"] = rows
            atomic.write_text(paths.watchlist, yaml.safe_dump(wl, sort_keys=False))
            accounts.update_prefs(paths.prefs, {
                "language": "en", "currency": "EUR",
                onboarding.PREF_DONE: True,
                onboarding.PREF_SEEN_VERSION: onboarding.CURRENT_VERSION,
            })
        return paths, seeded

    accounts.provision = provision
