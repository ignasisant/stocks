"""The market around the book: sector scans, the day's market, the
calendar, the pulse's series, the daily card and the banks list.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from stocks.analysis.portfolio import load_closes
from stocks.cache import ttl_cache
from stocks.loaders.keys import _HELD_QUIET, _HELD_STALE, _LEDGER_TTL, _PRICES_TTL


@ttl_cache(_LEDGER_TTL, max_entries=1)
def sector_scans() -> dict:
    """The nightly sector scan, restored from the bucket if it is not on disk.

    Market-wide, not per-account: every reader gets the same cohorts, so this
    is a shared file and the cache takes no account in its key. The ttl is the
    ledger's rather than a price one because the scan is rebuilt once a night —
    an hour-old cohort is the same cohort.
    """
    from stocks.analysis.sectors import load_scan

    return load_scan()


@ttl_cache(900.0, max_entries=1, stale_s=0.0)
def today_market() -> dict:
    """The Today page's shared market read (`chat.today_market`), {} if none.

    Written once a morning by cron for every account, so no account in the
    key. A quarter of an hour, strict: the lazy rebuild clears it when it
    writes a new file, and a cron write elsewhere shows up within that.
    """
    from stocks.chat import today_market

    return today_market.load()


# The market-wide and calendar memos below serve stale for as long as the
# book's own prices do (`_HELD_STALE`), with the refresh in the background:
# under the default grace (three ttls) every one of them was cold again
# within the hour on a quiet instance — the request log's Home market card
# and watchlist rows at twenty seconds on a Sunday — and the figure a
# weekend reader waited for was Friday's close either way. Past `quiet_s`
# the response says how old it is (`X-Data-Updating-Since`), and the shell
# asks again once the refresh lands.
@ttl_cache(
    21600.0,
    max_entries=16,
    stale_s=_HELD_STALE,
    quiet_s=21600.0,
    persist="earnings_calendar",
)
def earnings_calendar(tickers: tuple[str, ...]):
    """(upcoming events, past results) for a set of names, in ONE parallel pass.

    Keyed on the ticker tuple rather than a watchlist path, because that is what
    actually invalidates it: two accounts tracking the same names share the
    answer, and editing a watchlist changes the key by itself. Six hours — a
    company reports once a quarter, and the date moves rarely.
    """
    from stocks.config import Holding
    from stocks.data.earnings import calendar_events

    if not tickers:
        return [], []
    return calendar_events([Holding(ticker=t) for t in tickers])


def calendar_tickers(entries, held) -> tuple[str, ...]:
    """The names the calendar page asks `earnings_calendar` about: the
    watchlist and the open positions, coins and funds left out, sorted.

    One function so the page and the warm pass build the same cache key. The
    ledger counts as much as the watchlist: a position imported from a
    statement and never followed by hand still reports, and the Portfolio pill
    offers it. Fund classification stays cache-only — a cold cache keeps a
    fund in rather than blocking on a lookup.
    """
    from stocks.data.crypto import is_crypto
    from stocks.data.funds import is_fund

    names = {h.ticker for h in entries} | set(held)
    return tuple(
        sorted(t for t in names if not is_crypto(t) and not is_fund(t, fetch=False))
    )


# The market-regime screen. Two years of history because the trailing-year
# percentile needs a full year before it scores anything and the 200-session
# trend average needs most of another.

_PULSE_HISTORY = "2y"


@ttl_cache(
    _PRICES_TTL,
    max_entries=2,
    stale_s=_HELD_STALE,
    quiet_s=_HELD_QUIET,
    persist="pulse_closes",
)
def pulse_closes() -> dict[str, pd.Series]:
    """Close series for every symbol the pulse reads, in ONE bulk request."""
    from stocks.analysis.sentiment import all_tickers

    return load_closes(all_tickers(), period=_PULSE_HISTORY)


@ttl_cache(
    21600.0, max_entries=1, stale_s=_HELD_STALE, quiet_s=21600.0, persist="pulse_rates"
)
def pulse_rates() -> dict[str, pd.Series]:
    """The FRED series the composite's credit input needs.

    Only the high-yield spread, not the page's whole rates block: this is what
    `sentiment.pulse` takes, and pulling the rest here would spend a slow
    request on rows nothing in the API reads yet.
    """
    from stocks.data import macro

    return macro.fred_many(["BAMLH0A0HYM2"])


# Strict for the same reason as `_held_frames`: its inputs serve stale on
# their own, and a stale-served composite of stale-served inputs lags twice.
@ttl_cache(_PRICES_TTL, max_entries=2, stale_s=0)
def market_pulse():
    """The composite, built from the two loads above.

    Its own entry rather than a recompute per request: the arithmetic walks two
    years of eight series and the answer is the same for every reader.
    """
    from stocks.analysis.sentiment import pulse

    return pulse(pulse_closes(), hy_spread=pulse_rates().get("BAMLH0A0HYM2"))


@ttl_cache(86400.0, max_entries=1)
def benchmark_sectors() -> dict[str, float]:
    """SPY's own sector split — what a book's sector bet is measured against.

    Yahoo's fund look-through, so the buckets are already spelled the way a
    stock's `info["sector"]` spells them and join onto a book's allocation with
    no mapping layer in between. A day-long ttl: an index fund's sector split
    does not move between requests.
    """
    from stocks.data.funds import sector_weights

    return sector_weights("SPY")


@ttl_cache(_LEDGER_TTL, max_entries=32)
def stored_action(path: str, mtime: float) -> dict:
    """The stored daily card as a raw dict ({} when there is none).

    Unreadable reads as "nothing stored", which is what sends the dashboard
    down the regenerate path rather than to an error.
    """
    import json

    try:
        out = json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


@ttl_cache(
    21600.0,
    max_entries=1,
    stale_s=_HELD_STALE,
    quiet_s=21600.0,
    persist="pulse_rate_rows",
)
def pulse_rate_rows() -> dict[str, pd.Series]:
    """Every FRED series the rates block draws, plus the conditions index.

    Separate from `pulse_rates`, which pulls only the one series the composite
    needs: this is a slower call and a client that never opens the rates tab
    should not pay for it.
    """
    from stocks.analysis.sentiment import RATE_ROWS
    from stocks.data import macro

    return macro.fred_many([*RATE_ROWS, "NFCI"])


@ttl_cache(
    21600.0, max_entries=1, stale_s=_HELD_STALE, quiet_s=21600.0, persist="inflation"
)
def inflation() -> pd.DataFrame:
    """Annual inflation per area — the slowest source on the page."""
    from stocks.data import macro

    return macro.inflation()


# CFTC Commitments of Traders: weekly (Tuesday data, out on Friday), so a long
# memo. Twelve hours keeps a Friday release at most half a day behind, and the
# warm route (`api.warm`) refreshes it on the cron ticks rather than a page
# request paying for it.
@ttl_cache(12 * 3600.0, max_entries=1, persist="cot_positioning", keep_s=21 * 86400.0)
def positioning() -> dict[str, pd.DataFrame]:
    """Net speculative positioning per market, ~3 years of weekly reports."""
    from stocks.data import cot

    frames = cot.fetch()
    if not frames:
        # Raising keeps an empty answer from being memoised as the week's
        # truth: the persisted copy stands in and the next read retries.
        raise RuntimeError("cot: no data")
    return frames


# Enable Banking's own bank list. Reference data: identical for every account,
# and the API rate-limits it like everything else — an hour is what the page
# already held it for.
_ASPSPS_TTL = 3600.0


@ttl_cache(_ASPSPS_TTL, max_entries=32)
def aspsps(country: str) -> list[dict]:
    """The banks that can be connected in one country."""
    from stocks.bank import enablebanking

    return enablebanking.aspsps(country)
