"""Local page-load benchmark: one page per process, network stubbed + counted.

    uv run python scripts/bench_page.py home [--runs 3] [--profile] [--json out.json]

Pages: the keys of `PAGES` below (home, portfolio, ticker --ticker AAPL,
earnings, sector, sentiment, profile, import). Each is the list of GET calls
the shell's page makes when it mounts, read off `frontend/app/src/pages/`.
Run each page in its own process, so a cold run really starts cold.

Drives the API (`stocks.api.app`) in-process through a TestClient, signed in
as an account with the demo ledger and a ~30-name watchlist. The calls go one
after another, where the browser fires them together, so the wall time is the
sum of the endpoints rather than the slowest. Every Yahoo / FX / macro / LLM
call is replaced by a deterministic stub that COUNTS itself, and every other
socket is blocked, so the numbers are:

  * wall time per endpoint and for the page (cold = empty caches, warm = again)
  * requests the page would have made per kind (the driver of prod p95)
  * warn/error events emitted during the run (the "degraded" KPI)
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import logging
import os
import pstats
import socket
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("STOCKS_LOG_LEVEL", "INFO")
# The session cookie the bench signs in with is minted with this.
os.environ.setdefault("AUTH_COOKIE_SECRET", "bench-cookie-secret")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


from stocks.loadtest import PAGES  # noqa: E402
from stocks.loadtest.fakes import (  # noqa: E402
    COUNTS,
    DETAIL,
    EVENTS,
    WATCHLIST_EXTRA,
    install_upstream,
)


# ------------------------------------------------------------------- stubs
def install_stubs():
    install_upstream()

    from stocks import storage
    storage.enabled = lambda: False

    from stocks.data import funds, profiles
    scratch = Path(tempfile.mkdtemp(prefix="bench-data-"))
    profiles.PROFILE_CACHE = scratch / "profiles.json"
    profiles.clear()
    funds.TYPE_MEMO.clear()
    funds.TYPE_MEMO.path = scratch / "quote_types.json"
    funds._types = None
    from stocks.api import loaders
    loaders.WORLD_MEMO.clear()
    loaders.WORLD_MEMO.path = scratch / "symbol_search.json"
    # Memos on disk too: the dev memo dir would serve a run from the last one
    # and keep this bench's made-up prices for the dev server to read.
    from stocks.api import cache
    cache.MEMO_DIR = scratch / "memo"

    # Any other socket = a fetch site this bench does not know about. Fail
    # fast and count it instead of hanging on DNS.
    def _blocked(*a, **kw):
        COUNTS["net.blocked"] += 1
        raise OSError("network disabled by bench")
    socket.getaddrinfo = _blocked
    socket.create_connection = _blocked
    socket.socket.connect = _blocked  # type: ignore[assignment]


def install_account(tmp: Path):
    import yaml

    from stocks import accounts
    from stocks.portfolio import demo
    from stocks.web import auth, onboarding

    paths = auth.paths_for("bench@example.com", users_dir=tmp)
    paths.root.mkdir(parents=True, exist_ok=True)
    prefs = dict(auth.DEFAULT_PREFS) | {
        "language": "en", "currency": "EUR", "email": "bench@example.com",
        "onboarding_dismissed": True, "setup_card_dismissed": True,
        onboarding.PREF_DONE: True,
        onboarding.PREF_SEEN_VERSION: onboarding.CURRENT_VERSION,
        "guide_done": True,
        "first_seen": "2026-01-01T00:00:00+00:00", "last_seen": "2026-09-15",
    }
    paths.prefs.write_text(json.dumps(prefs))
    wl = yaml.safe_load(auth.STARTER_WATCHLIST) or {}
    rows = list(wl.get("watchlist") or [])
    have = {str(r.get("ticker", "")).upper() for r in rows if isinstance(r, dict)}
    for t in [*demo.TICKERS, *WATCHLIST_EXTRA]:
        if t not in have:
            rows.append({"ticker": t})
            have.add(t)
    wl["watchlist"] = rows
    paths.watchlist.write_text(yaml.safe_dump(wl, sort_keys=False))
    demo.seed(paths.db)

    # Every request resolves its account through `accounts.paths_for`; point
    # it at the scratch one and keep the bucket out of it.
    accounts.configured_owner = lambda: None
    accounts.paths_for = lambda email, owner=None, users_dir=None: paths
    accounts.restore_account = lambda *a, **k: False
    return paths, len(rows)


# The GET calls each page of the shell makes when it mounts. Taken from the
# `get<…>("/…")` calls under frontend/app/src/pages/<page>/; the ones a click
# or a scroll triggers are left out.


def client():
    """A TestClient on the API, signed in as the bench account."""
    from fastapi.testclient import TestClient

    from stocks import session
    from stocks.api.app import app

    c = TestClient(app, raise_server_exceptions=False)
    c.cookies.set(session.COOKIE, session.mint({
        "email": "bench@example.com", "email_verified": True, "name": "Bench",
    }))
    return c


class _Capture(logging.Handler):
    def emit(self, record):
        ev = getattr(record, "event", None)
        if not ev:
            return
        EVENTS.append({
            "event": ev, "level": record.levelname,
            "duration_ms": getattr(record, "duration_ms", None),
            "page": getattr(record, "page", None),
            "error": getattr(record, "error", None),
            "ticker": getattr(record, "ticker", None),
            "last": getattr(record, "last", None), "live": getattr(record, "live", None),
        })


def _profile_top(pr: cProfile.Profile, n: int = 40) -> str:
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(400)
    out = []
    for line in s.getvalue().splitlines():
        ours = "stocks/" in line or "site-packages/yfinance" in line
        if ours and "bench_page" not in line:
            out.append(line[:200])
        if len(out) >= n:
            break
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("page", choices=sorted(PAGES))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--ticker", default="AAPL")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="bench-"))
    install_stubs()
    paths, n_wl = install_account(tmp)
    logging.getLogger("stocks").addHandler(_Capture())
    logging.getLogger("stocks").setLevel(logging.INFO)

    api = client()
    calls = [path.format(t=args.ticker) for path in PAGES[args.page]]

    results = []
    for i in range(args.runs):
        COUNTS.clear()
        EVENTS.clear()
        DETAIL.clear()
        pr = cProfile.Profile() if args.profile else None
        endpoints = []
        t0 = time.perf_counter()
        if pr:
            pr.enable()
        for path in calls:
            t = time.perf_counter()
            status = api.get(path).status_code
            endpoints.append({
                "path": path, "status": status,
                "ms": round((time.perf_counter() - t) * 1000),
            })
        if pr:
            pr.disable()
        wall = time.perf_counter() - t0
        warns = [e for e in EVENTS if e["level"] in ("WARNING", "ERROR")]
        row = {
            "run": "cold" if i == 0 else f"warm{i}",
            "wall_ms": round(wall * 1000),
            "endpoints": endpoints,
            "failed": [e["path"] for e in endpoints if e["status"] >= 400],
            "warnings": Counter(e["event"] for e in warns),
            "counts": dict(sorted(COUNTS.items())),
        }
        results.append(row)
        print(f"\n=== {args.page} [{row['run']}] wall={row['wall_ms']}ms")
        for e in sorted(endpoints, key=lambda e: -e["ms"]):
            print(f"  {e['ms']:>6}ms {e['status']} {e['path']}")
        if row["failed"]:
            print("  FAILED:", row["failed"])
        print("  requests:", json.dumps(row["counts"]))
        if DETAIL:
            print("  bulk     :", ", ".join(DETAIL))
        row["detail"] = list(DETAIL)
        if row["warnings"]:
            print("  warn/err :", dict(row["warnings"]))
        if pr:
            print(_profile_top(pr))
    print(f"\nwatchlist rows: {n_wl}; user dir: {paths.root}")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"page": args.page, "runs": results}, default=str, indent=1))


if __name__ == "__main__":
    main()
