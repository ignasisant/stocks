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
import hashlib
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
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("STOCKS_LOG_LEVEL", "INFO")
# The session cookie the bench signs in with is minted with this.
os.environ.setdefault("AUTH_COOKIE_SECRET", "bench-cookie-secret")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

COUNTS: Counter = Counter()
EVENTS: list[dict] = []
DETAIL: list[str] = []


def _hit(name: str, value=None):
    """Count one stubbed request under `name`; returns `value` for lambdas."""
    COUNTS[name] += 1
    return value

WATCHLIST_EXTRA = [
    "AMZN", "AMD", "ASML", "ADBE", "CRM", "AVGO", "NFLX", "INTC", "QCOM", "TXN",
    "SAP", "MC.PA", "SAN.MC", "ITX.MC", "SHOP", "MELI", "SE", "BABA", "TSM", "PLTR",
    "SPY", "QQQ", "VWCE.DE", "BTC-EUR",
]

_PERIOD_DAYS = {
    "1d": 1, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 130, "ytd": 180,
    "1y": 252, "2y": 504, "5y": 1260, "10y": 2520, "max": 3000,
}


# ------------------------------------------------------------------ fake data
def _seed(sym: str) -> int:
    return int(hashlib.md5(sym.encode()).hexdigest()[:8], 16)


def _closes(sym: str, n: int) -> pd.Series:
    rng = np.random.default_rng(_seed(sym))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    px = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.Series(px, index=idx, name="Close")


def _ohlcv(sym: str, period: str = "1y", start=None, end=None) -> pd.DataFrame:
    n = _PERIOD_DAYS.get(str(period), 252)
    if start is not None:
        try:
            n = max(5, int((pd.Timestamp.today() - pd.Timestamp(start)).days * 5 / 7))
        except Exception:
            pass
    c = _closes(sym, n)
    df = pd.DataFrame({
        "Open": c.shift(1).fillna(c.iloc[0]),
        "High": c * 1.01,
        "Low": c * 0.99,
        "Close": c,
        "Volume": 1_000_000,
    })
    df.index.name = "Date"
    return df


def fake_download(tickers, period="1mo", interval="1d", group_by="column",
                  auto_adjust=True, progress=False, threads=True, start=None,
                  end=None, **kw):
    syms = tickers if isinstance(tickers, (list, tuple)) else str(tickers).split()
    syms = list(dict.fromkeys(str(s) for s in syms))
    COUNTS["download.calls"] += 1
    COUNTS["download.symbols"] += len(syms)
    DETAIL.append(f"download({len(syms)} syms, {period})")
    frames = {s: _ohlcv(s, period, start, end) for s in syms}
    return pd.concat(frames, axis=1)  # MultiIndex (symbol, field)


def _fin_frame(
    seed: str, rows: list[str], cols: int = 4, quarterly: bool = False
) -> pd.DataFrame:
    rng = np.random.default_rng(_seed(seed + "fin"))
    if quarterly:
        idx = [pd.Timestamp(date.today() - timedelta(days=91 * i)) for i in range(cols)]
    else:
        idx = [pd.Timestamp(date(date.today().year - 1 - i, 12, 31)) for i in range(cols)]
    data = {c: [float(abs(rng.normal(1e10, 2e9))) for _ in rows] for c in idx}
    return pd.DataFrame(data, index=rows)


_FIN_ROWS = [
    "Total Revenue", "Gross Profit", "Operating Income", "Net Income",
    "Free Cash Flow", "Operating Cash Flow", "Capital Expenditure",
    "Research And Development", "Tax Provision", "Pretax Income", "EBITDA",
    "Total Debt", "Cash And Cash Equivalents", "Stockholders Equity",
    "Total Assets", "Diluted EPS", "Basic EPS",
]


class FakeTicker:
    def __init__(self, symbol: str, *a, **kw):
        self.ticker = str(symbol)
        COUNTS["ticker.objects"] += 1

    def _px(self):
        c = _closes(self.ticker, 5)
        return float(c.iloc[-1]), float(c.iloc[-2])

    @property
    def info(self):
        COUNTS["ticker.info"] += 1
        last, prev = self._px()
        return {
            "symbol": self.ticker, "shortName": f"{self.ticker} Inc",
            "longName": f"{self.ticker} Incorporated", "sector": "Technology",
            "industry": "Software", "country": "United States", "currency": "USD",
            "quoteType": "EQUITY", "marketCap": 1.2e12, "trailingPE": 25.0,
            "forwardPE": 20.0, "priceToBook": 6.0, "enterpriseValue": 1.25e12,
            "website": "https://example.com", "financialCurrency": "USD",
            "regularMarketPrice": last, "regularMarketPreviousClose": prev,
            "previousClose": prev, "marketState": "CLOSED", "beta": 1.1,
            "exchangeTimezoneName": "America/New_York", "grossMargins": 0.42,
            "operatingMargins": 0.3, "profitMargins": 0.25, "dividendYield": 0.01,
            "sharesOutstanding": 1e9, "trailingEps": 6.0, "forwardEps": 7.0,
            "revenueGrowth": 0.1, "earningsGrowth": 0.12, "returnOnEquity": 0.3,
            "debtToEquity": 50.0, "freeCashflow": 1e10, "totalRevenue": 4e10,
            "fiftyTwoWeekHigh": last * 1.2, "fiftyTwoWeekLow": last * 0.7,
            "exchange": "NMS", "fullExchangeName": "NasdaqGS",
        }

    def get_info(self):
        return self.info

    @property
    def fast_info(self):
        COUNTS["ticker.fast_info"] += 1
        last, prev = self._px()
        return {"lastPrice": last, "previousClose": prev, "currency": "USD",
                "marketCap": 1.2e12, "shares": 1e9, "yearHigh": last * 1.2,
                "yearLow": last * 0.7}

    def history(self, period="1mo", interval="1d", start=None, end=None, **kw):
        COUNTS["ticker.history"] += 1
        return _ohlcv(self.ticker, period, start, end)

    @property
    def calendar(self):
        COUNTS["ticker.calendar"] += 1
        return {"Earnings Date": [date.today() + timedelta(days=20)],
                "EPS Estimate": 1.5, "Revenue Estimate": 1e10}

    @property
    def earnings_dates(self):
        COUNTS["ticker.earnings_dates"] += 1
        idx = pd.DatetimeIndex([pd.Timestamp(date.today() - timedelta(days=90 * i))
                                for i in range(-1, 8)], name="Earnings Date")
        df = pd.DataFrame({"EPS Estimate": 1.4, "Reported EPS": 1.5,
                           "Surprise(%)": 7.0}, index=idx)
        future = df.index > pd.Timestamp.today()
        df.loc[future, ["Reported EPS", "Surprise(%)"]] = float("nan")
        return df

    def get_earnings_dates(self, limit=12):
        COUNTS["ticker.get_earnings_dates"] += 1
        return self.earnings_dates.head(limit)

    @property
    def splits(self):
        COUNTS["ticker.splits"] += 1
        return pd.Series(dtype=float)

    @property
    def dividends(self):
        COUNTS["ticker.dividends"] += 1
        idx = pd.DatetimeIndex([pd.Timestamp(date.today() - timedelta(days=91 * i))
                                for i in range(8, 0, -1)], name="Date")
        return pd.Series([0.25] * 8, index=idx, name="Dividends")

    @property
    def funds_data(self):
        COUNTS["ticker.funds_data"] += 1
        return None

    @property
    def isin(self):
        return "-"

    @property
    def analyst_price_targets(self):
        COUNTS["ticker.analyst_price_targets"] += 1
        last, _ = self._px()
        return {"current": last, "low": last * 0.8, "high": last * 1.3,
                "mean": last * 1.1, "median": last * 1.1}

    @property
    def news(self):
        COUNTS["ticker.news"] += 1
        return []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        COUNTS[f"ticker.{name}"] += 1
        quarterly = name.startswith("quarterly")
        if any(k in name for k in ("stmt", "financials", "cashflow", "balance",
                                    "income", "estimate", "holders",
                                    "recommend", "transactions", "targets")):
            return _fin_frame(self.ticker + name, _FIN_ROWS, quarterly=quarterly)
        return pd.DataFrame()


def fake_get_raw_json(self, url, params=None, timeout=None, **kw):
    syms = str((params or {}).get("symbols", "")).split(",")
    syms = [s for s in syms if s]
    COUNTS["quote.calls"] += 1
    COUNTS["quote.symbols"] += len(syms)
    DETAIL.append(f"quote({len(syms)} syms)")
    rows = []
    for s in syms:
        last, prev = FakeTicker(s)._px()
        COUNTS["ticker.objects"] -= 1
        rows.append({
            "symbol": s, "regularMarketPrice": last,
            "regularMarketPreviousClose": prev, "marketState": "CLOSED",
            "regularMarketTime": int(time.time()) - 3600 * 5,
            "exchangeTimezoneName": "America/New_York", "currency": "USD",
            "shortName": f"{s} Inc", "quoteType": "EQUITY",
        })
    return {"quoteResponse": {"result": rows}}


# ------------------------------------------------------------------- stubs
def install_stubs():
    import yfinance as yf
    from yfinance import data as yfdata

    yf.download = fake_download
    yf.Ticker = FakeTicker
    yfdata.YfData.get_raw_json = fake_get_raw_json
    import stocks.data.fetch as fetch
    fetch.yf.download = fake_download
    fetch.yf.Ticker = FakeTicker

    from stocks.data import fx
    def _spot(base, quote):
        COUNTS["fx.spot"] += 1
        return (1.0 if base == quote else 0.92, date.today().isoformat())
    fx.spot = _spot
    fx._fetch = lambda url, quote: _hit("fx.fetch", (0.92, "x"))
    fx.rate_on = lambda day, base, quote: _hit(
        "fx.rate_on", 1.0 if base == quote else 0.92
    )
    def _rates_range(start, end, base, quote):
        COUNTS["fx.rates_range"] += 1
        days = pd.date_range(start, end, freq="D")
        r = 1.0 if base == quote else 0.92
        return {d.date().isoformat(): r for d in days}
    fx.rates_range = _rates_range
    fx.prefetch = lambda *a, **k: _hit("fx.prefetch")
    fx.usd_eur = lambda: (0.92, date.today().isoformat())

    from stocks.data import macro
    def _fred_many(ids, **kw):
        COUNTS["macro.fred_many"] += 1
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=750)
        return {
            sid: pd.Series(np.linspace(2, 4, 750), index=idx, name=sid) for sid in ids
        }
    macro.fred_many = _fred_many
    macro.fred = lambda sid, **kw: _fred_many([sid])[sid]
    def _inflation(*a, **kw):
        COUNTS["macro.inflation"] += 1
        return pd.DataFrame()
    macro.inflation = _inflation
    macro.hicp = _inflation
    macro.as_of = lambda: "bench"

    from stocks.data import funds
    funds.sector_weights = lambda t: _hit("funds.sector_weights", {})
    funds.fetch_profile = lambda t, info=None: None

    from stocks.data import http as shttp
    def _get_bytes(*a, **kw):
        COUNTS["http.get_bytes"] += 1
        import urllib.error
        raise urllib.error.URLError("network disabled by bench")
    shttp.get_bytes = _get_bytes

    from stocks.data import logo
    logo.mirror_logo = lambda t, d: None
    logo.logo_url = lambda t: None

    from stocks.api import loaders
    loaders.sec_matches = lambda q: []
    loaders.world_matches = lambda q: []
    loaders.sec_title = lambda t: None

    from stocks.chat import daily, engine
    daily.generate = lambda *a, **k: _hit("llm.daily")
    engine.spend_free_quota = lambda p: False

    from stocks import storage
    storage.enabled = lambda: False

    from stocks.data import funds, profiles
    scratch = Path(tempfile.mkdtemp(prefix="bench-data-"))
    profiles.PROFILE_CACHE = scratch / "profiles.json"
    profiles.clear()
    funds.TYPE_CACHE = scratch / "quote_types.json"
    funds._types = None

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
        "/v1/ticker/{t}/quote", "/v1/ticker/{t}/bars", "/v1/ticker/{t}/profile",
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
