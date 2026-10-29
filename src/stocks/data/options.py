"""What the listed options say about a share: implied volatility and the
put/call balance. yfinance (`Ticker.options` + `option_chain`), free, keyless.

Only names with listed options answer — in practice US lines and the odd ETF;
a European or Asian share has an empty expiry list and gets `None`.

`fetch_chains` touches the network; `summarize` is pure over the frames it
returns so tests run offline. Everything here is **market-implied**, not a
forecast: IV is what traders pay for protection, the put/call ratios are how
the crowd is positioned, and Yahoo's per-contract IV is junk for illiquid
strikes, so only quoted contracts near the money are read.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import pandas as pd

# The expiry IV is read from: the first one at least this many days out, so
# the final week's pin risk and expiry-day decay do not bend it.
MIN_DAYS = 20
# Put/call balance is summed over the expiries inside this window — the
# crowd's near-term positioning, not a LEAPS hedge book.
WINDOW_DAYS = 60
MAX_EXPIRIES = 4
# Below this much open interest the ratios are one trader's book.
MIN_OPEN_INTEREST = 100
# Yahoo's IV for a quoted at-the-money contract sits well inside this band;
# outside it the figure is a stale quote or a broken solve.
IV_BAND = (0.03, 5.0)
# How far from the spot the "at-the-money" strike may sit. Past it the nearest
# quoted contract is deep in or out of the money, whose IV is mostly spread: a
# thin chain after a split (BKNG 2026-10: nothing quoted between 110 and a
# 150 spot, a 38-51.7 market) read as 138 %.
ATM_BAND = 0.10
# Outside the US session Yahoo zeroes every bid, ask and open interest and
# keeps the last session's volume (AAPL, 2026-10-29 pre-market: 1 of 71
# contracts quoted, open interest 2). A chain quoted that thinly while the
# market is not open is the closed book, not a reading: IV goes null and the
# put/call open interest becomes a ratio of leftovers (MSFT read 13.9).
QUOTED_SHARE = 0.05


@dataclass(frozen=True)
class Chain:
    """One expiry's calls and puts as yfinance returns them."""

    expiry: str
    calls: pd.DataFrame
    puts: pd.DataFrame


@dataclass(frozen=True)
class RawOptions:
    spot: float | None
    chains: list[Chain]
    # Yahoo's `marketState` for the underlying: REGULAR in session, PRE,
    # POST, POSTPOST, PREPRE or CLOSED around it.
    state: str | None = None


def pick_expiries(expiries: tuple[str, ...] | list[str], today: date) -> list[str]:
    """The expiries to download: the IV one first, then the rest of the window."""
    ahead = []
    for e in expiries:
        try:
            days = (date.fromisoformat(e) - today).days
        except ValueError:
            continue
        ahead.append((days, e))
    ahead.sort()
    iv = next((e for d, e in ahead if d >= MIN_DAYS), None)
    if iv is None:
        # Nothing that far out: the farthest listed is the closest honest read.
        iv = ahead[-1][1] if ahead else None
    if iv is None:
        return []
    window = [e for d, e in ahead if 0 <= d <= WINDOW_DAYS and e != iv]
    return ([iv, *window])[:MAX_EXPIRIES]


def fetch_chains(ticker: str, today: date | None = None) -> RawOptions | None:
    """Download the chains `summarize` needs; None when nothing is listed.

    A refusal (`YFRateLimitError` and kin) raises, so a throttled minute is
    never memoized as "this name has no options".
    """
    import yfinance as yf

    from stocks.data.fetch import retired, retry

    if retired(ticker):
        return None
    handle = yf.Ticker(ticker)
    expiries = retry(lambda: handle.options, attempts=2)
    picked = pick_expiries(tuple(expiries or ()), today or date.today())
    if not picked:
        return None

    def one(expiry: str):
        return expiry, retry(lambda: handle.option_chain(expiry), attempts=2)

    with ThreadPoolExecutor(max_workers=len(picked)) as pool:
        got = list(pool.map(one, picked))
    chains = [Chain(e, c.calls, c.puts) for e, c in got]
    underlying = getattr(got[0][1], "underlying", None) or {}
    spot = underlying.get("regularMarketPrice")
    return RawOptions(
        float(spot) if spot else None, chains, underlying.get("marketState")
    )


def closed(raw: RawOptions | None) -> bool:
    """True when the chain is Yahoo's out-of-session snapshot: the market is
    not open and almost no contract carries a two-sided quote."""
    if raw is None or not raw.chains or raw.state == "REGULAR":
        return False
    rows = quoted = 0
    for chain in raw.chains:
        for frame in (chain.calls, chain.puts):
            if frame is None or frame.empty or not {"bid", "ask"} <= set(frame.columns):
                continue
            rows += len(frame)
            quoted += int(((frame["bid"] > 0) & (frame["ask"] > 0)).sum())
    return rows > 0 and quoted < QUOTED_SHARE * rows


def _atm_iv(chain: Chain, spot: float) -> float | None:
    """Mean IV of the quoted call and put at the strike nearest `spot`,
    each only when that strike is within ATM_BAND of it."""
    values = []
    for frame in (chain.calls, chain.puts):
        if frame is None or frame.empty or "impliedVolatility" not in frame.columns:
            continue
        quoted = frame[(frame["bid"] > 0) & (frame["ask"] > 0)]
        quoted = quoted[quoted["impliedVolatility"].between(*IV_BAND)]
        if quoted.empty:
            continue
        near = quoted.iloc[(quoted["strike"] - spot).abs().argsort()[:1]]
        if abs(float(near["strike"].iloc[0]) / spot - 1) > ATM_BAND:
            continue
        values.append(float(near["impliedVolatility"].iloc[0]))
    return sum(values) / len(values) if values else None


def _total(frame: pd.DataFrame | None, column: str) -> float:
    if frame is None or frame.empty or column not in frame.columns:
        return 0.0
    return float(frame[column].fillna(0).sum())


def summarize(raw: RawOptions | None, today: date) -> dict | None:
    """IV and put/call balance, or None when the chain cannot support either.

    `iv` is annualised (0.32 = 32 %) at `iv_expiry`; the ratios sum the chosen
    expiries. A ratio is None below MIN_OPEN_INTEREST (open interest) or when
    the other side is empty — never a zero standing in for "no data".
    """
    if raw is None or not raw.chains:
        return None
    first = raw.chains[0]
    iv = _atm_iv(first, raw.spot) if raw.spot else None
    calls_oi = sum(_total(c.calls, "openInterest") for c in raw.chains)
    puts_oi = sum(_total(c.puts, "openInterest") for c in raw.chains)
    calls_vol = sum(_total(c.calls, "volume") for c in raw.chains)
    puts_vol = sum(_total(c.puts, "volume") for c in raw.chains)
    thin = calls_oi + puts_oi < MIN_OPEN_INTEREST
    pc_oi = puts_oi / calls_oi if calls_oi and not thin else None
    pc_vol = puts_vol / calls_vol if calls_vol and calls_vol + puts_vol >= 50 else None
    if iv is None and pc_oi is None and pc_vol is None:
        return None
    try:
        days = (date.fromisoformat(first.expiry) - today).days
    except ValueError:
        days = None
    return {
        "iv": round(iv, 4) if iv is not None else None,
        "iv_expiry": first.expiry if iv is not None else None,
        "iv_days": days if iv is not None else None,
        "put_call_oi": round(pc_oi, 3) if pc_oi is not None else None,
        "put_call_volume": round(pc_vol, 3) if pc_vol is not None else None,
        "open_interest": int(calls_oi + puts_oi),
        "expiries": len(raw.chains),
    }
