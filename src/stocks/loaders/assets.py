"""What only some kinds of asset need: fund profiles, closed-end checks,
the policy rate, and crypto's scans.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from stocks import obs
from stocks.cache import ttl_cache
from stocks.loaders.bars import price_bars
from stocks.loaders.keys import _LEDGER_TTL, _QUOTES_TTL


@ttl_cache(86400.0, max_entries=32)
def fund_profile(ticker: str):
    """What a fund is and what it holds, or None for an ordinary company.

    A day's ttl: an expense ratio and a holdings list change on the fund's
    schedule, not the market's.
    """
    from stocks.data.funds import fetch_profile

    try:
        return fetch_profile(ticker)
    except Exception as exc:
        obs.warn(
            "api.fund_profile_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return None


@ttl_cache(14400.0, max_entries=32)
def closed_end(ticker: str):
    """A listed closed-end fund's own figures, or None for anything else.

    Four hours: NAV prints once a day after the close, and the filed figures
    (N-PORT, XBRL) move on the fund's monthly-to-yearly schedule.
    """
    from stocks.data.cef import closed_end_profile

    try:
        return closed_end_profile(ticker)
    except Exception as exc:
        obs.warn(
            "api.closed_end_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return None


def is_closed_end(ticker: str, *, fetch: bool = True) -> bool:
    """Whether `ticker` is a closed-end fund; False when that cannot be told.

    Not ttl-cached here: `stocks.data.cef` keeps its verdicts on disk, and a
    failed lookup must be asked again rather than remembered as "company".
    """
    from stocks.data.cef import is_closed_end as detect

    try:
        return detect(ticker, fetch=fetch)
    except Exception as exc:
        obs.warn(
            "api.closed_end_detect_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return False


def asset_kind(ticker: str) -> str | None:
    """Which of the seven kinds `ticker` is (`stocks.data.asset_kind`).

    Not memoized for shares, coins and indices: the quoteType and the
    closed-end verdict it reads already live on disk, and a failed lookup (a
    share by default) must be asked again. Funds go through `_fund_kind`.
    """
    from stocks.data import asset_kind as kinds
    from stocks.data.funds import FUND_TYPES, quote_type

    if hit := kinds.known(ticker):
        return hit
    qt = quote_type(ticker)
    if qt in FUND_TYPES:
        return _fund_kind(ticker, qt)
    return kinds.classify(
        symbol=ticker,
        quote_type=qt,
        closed_end=qt == "EQUITY" and is_closed_end(ticker),
    )


@ttl_cache(86400.0, max_entries=64)
def _fund_kind(ticker: str, quote_type: str) -> str | None:
    """A fund's kind from its description, and from its price when that fails.

    A day's ttl, which is also how long a price-read verdict lives: those are
    never stored (see the classifier). The bars are the chart's own 2y daily
    download, so asking costs nothing the page was not about to fetch.
    """
    from stocks.data import asset_kind as kinds
    from stocks.data.funds import fund_name

    profile = fund_profile(ticker)
    desc: dict[str, Any] = {
        "name": (profile.name if profile else "") or fund_name(ticker) or "",
        "category": (profile.category if profile else "") or "",
        "asset_classes": profile.asset_classes if profile else (),
    }
    if not kinds.needs_prices(**desc):
        kind = kinds.classify(symbol=ticker, quote_type=quote_type, **desc)
        kinds.remember(ticker, kind)
        return kind
    signals = None
    try:
        signals = kinds.price_signals(price_bars(ticker, "1y")["Close"])
    except Exception as exc:
        obs.warn(
            "api.asset_kind_prices_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
    vol, drawdown = signals or (None, None)
    return kinds.classify(
        symbol=ticker, quote_type=quote_type, vol_1y=vol, max_dd=drawdown, **desc
    )


@ttl_cache(3600.0, max_entries=4)
def policy_rate(currency: str) -> tuple[str, float, date] | None:
    """(bank, rate as a fraction, as-of) for the bank a currency's cash tracks.

    None for a currency with no bank mapped (`macro_calendar.CURRENCY_BANK`)
    or when FRED cannot be reached — the yield tile then stands alone.
    """
    from stocks.analysis.cash import policy_level
    from stocks.data import macro
    from stocks.data import macro_calendar as cal

    bank = cal.CURRENCY_BANK.get((currency or "").upper())
    if bank is None:
        return None
    sids = cal.RATE_SERIES[bank]
    try:
        level = policy_level(sids, macro.fred_many(list(sids), years=1))
    except Exception as exc:
        obs.warn(
            "api.policy_rate_failed",
            bank=bank,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return None
    return (bank, *level) if level else None


@ttl_cache(_QUOTES_TTL * 12, max_entries=64)
def crypto_info(ticker: str) -> dict:
    """Snapshot info for a coin pair — market cap, volume, supply, 52w range."""
    from stocks.data.fetch import info as quote_info

    try:
        return quote_info(ticker)
    except Exception as exc:
        obs.warn(
            "api.crypto_info_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return {}


@ttl_cache(_LEDGER_TTL, max_entries=1)
def crypto_scan() -> dict:
    """The nightly crypto scan (`analysis.crypto_scan`), shared by every account.

    Rebuilt once a night, so the ledger's hour is plenty — the same reasoning
    as `sector_scans`.
    """
    from stocks.analysis.crypto_scan import load_scan

    return load_scan()


@ttl_cache(900.0, max_entries=64, stale_s=900.0)
def crypto_positioning(coin: str):
    """A coin's perpetual swap on the first venue that lists it, or None.

    Fifteen minutes: funding settles every eight hours (four, one, for some
    coins) and the rate in between drifts slowly. Read live from the app
    because the venues refuse US IPs, where the nightly runners are. Raises
    when every venue failed, so the failure is not cached as "unlisted".
    """
    from stocks.data.crypto_market import positioning

    return positioning(coin)


@ttl_cache(_LEDGER_TTL, max_entries=16)
def crypto_replay(db: str, mtime: float, prefs: str, prefs_mtime: float):
    """The ledger replayed under the account's tax rules (`chat.whatif`), the
    yardstick a coin's harvest line is measured against. Keyed on both files'
    mtimes: a new trade or a changed residence each change the answer."""
    from stocks.chat import whatif

    return whatif.replay(db=Path(db), prefs_path=Path(prefs))
