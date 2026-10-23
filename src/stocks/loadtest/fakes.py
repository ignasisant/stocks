"""Made-up market data: every Yahoo / FX / macro / LLM call answered locally.

Deterministic per symbol (one random walk seeded by its name), so two runs —
or two requests — see the same prices, and every call COUNTS itself, so a
caller can tell how many upstream requests a page would have made.

Two users: `scripts/bench_page.py`, which drives the API in-process to time a
page, and the server's load-test mode (`stocks.loadtest`), which answers a
thousand simulated readers without asking Yahoo for anything. Nothing imports
this module otherwise; installing it replaces functions process-wide.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from datetime import date, timedelta

import numpy as np
import pandas as pd

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
    """The last `n` sessions of one long walk per symbol, so every period —
    and the fake quote — ends on the same price."""
    longest = max(n, _PERIOD_DAYS["max"])
    rng = np.random.default_rng(_seed(sym))
    walk = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, longest))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.Series(walk[-n:], index=idx, name="Close")


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


def fake_spark(syms: list[str], range_: str) -> dict:
    """The v7 spark payload: each symbol's daily closes at the session open."""
    COUNTS["spark.calls"] += 1
    COUNTS["spark.symbols"] += len(syms)
    DETAIL.append(f"spark({len(syms)} syms, {range_})")
    rows = []
    for s in syms:
        c = _closes(s, _PERIOD_DAYS.get(range_, 22))
        stamps = [int((d + pd.Timedelta(hours=14)).timestamp()) for d in c.index]
        rows.append({"symbol": s, "response": [{
            "meta": {"symbol": s, "exchangeTimezoneName": "America/New_York"},
            "timestamp": stamps,
            "indicators": {"quote": [{"close": [float(x) for x in c]}]},
        }]})
    return {"spark": {"result": rows}}


def fake_get_raw_json(self, url, params=None, timeout=None, **kw):
    syms = str((params or {}).get("symbols", "")).split(",")
    syms = [s for s in syms if s]
    if "/spark" in str(url):
        return fake_spark(syms, str((params or {}).get("range", "1mo")))
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


def install_upstream() -> None:
    """Swap every known market-data and LLM fetch site for the fakes above."""
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
    macro.as_of = lambda: "fake"

    from stocks.data import funds
    funds.sector_weights = lambda t: _hit("funds.sector_weights", {})
    funds.fetch_profile = lambda t, info=None: None

    # Finnhub, keyed: the earnings window, the market clock and the insider
    # feed answer locally and count themselves, so a page's Yahoo count is
    # what it would be in a keyed deployment (prod has a key).
    from stocks.data import finnhub
    from stocks.portfolio import demo

    finnhub.api_key = lambda: "bench"
    finnhub.clear()
    us_names = [
        finnhub.spelling(t)
        for t in dict.fromkeys([*demo.TICKERS, *WATCHLIST_EXTRA])
        if finnhub.covers(t)
    ]

    def _finnhub_get(path, params, key, timeout):
        COUNTS[f"finnhub.{path}"] += 1
        if path == "calendar/earnings":
            a, b = date.fromisoformat(params["from"]), date.fromisoformat(params["to"])
            rows = []
            for symbol in us_names:
                # One print ahead and one a quarter behind it, spread over
                # the next few weeks so the calendar has something to draw.
                spread = int(hashlib.md5(symbol.encode()).hexdigest()[:4], 16) % 25
                ahead = date.today() + timedelta(days=3 + spread)
                for day, actual in ((ahead, None), (ahead - timedelta(days=91), 1.1)):
                    if a <= day <= b:
                        rows.append({
                            "symbol": symbol, "date": day.isoformat(), "hour": "amc",
                            "epsEstimate": 1.0, "epsActual": actual,
                            "revenueEstimate": 1e9, "revenueActual": None,
                            "quarter": 1, "year": day.year,
                        })
            return {"earningsCalendar": rows}
        if path == "stock/market-status":
            return {
                "exchange": "US", "holiday": None, "isOpen": False, "session": None,
                "t": int(time.time()), "timezone": "America/New_York",
            }
        if path == "stock/insider-transactions":
            return {"symbol": params.get("symbol"), "data": []}
        return {}

    finnhub._get = _finnhub_get
    finnhub._fetch = lambda symbol, key, timeout: _hit(
        "finnhub.quote", {"c": 100.0, "pc": 99.0, "t": int(time.time())}
    )

    from stocks.data import http as shttp
    def _get_bytes(*a, **kw):
        COUNTS["http.get_bytes"] += 1
        import urllib.error
        raise urllib.error.URLError("network disabled by stocks.loadtest.fakes")
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
