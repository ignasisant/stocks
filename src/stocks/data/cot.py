"""CFTC Commitments of Traders — how crowded the speculators' side is.

The CFTC publishes every futures market's positions by trader group each
Friday (data as of the Tuesday before), free and keyless, through a Socrata
endpoint on ``publicreporting.cftc.gov``. Two datasets cover what the app
reads, and the group that counts as "speculators" differs between them:

* **TFF** (Traders in Financial Futures, ``gpe5-46if``, futures only) splits
  financial contracts into dealers, asset managers, leveraged funds and
  others. Speculators here are leveraged funds *plus* asset managers.
* **Legacy** (``6dca-aqww``, futures only) only knows commercials and
  non-commercials, which is the right split for commodities, where the
  commercial side is the producer hedging. Speculators are the non-commercials.

The contract codes are the CFTC's own (``cftc_contract_market_code``) and were
probed live on 2026-10-27; a code that stops answering simply yields no rows.

A figure on its own says little: 400k net short in the 10y note is normal, and
the news is where it stands against its own last three years. So each market
carries a percentile and a z-score of its net position over ~3 years of
weekly reports. Above the crowded band is a market everyone already owns.

Nothing here raises: a failed request is a market with no rows, so the block
shows its empty state rather than the page an error.
"""

from __future__ import annotations

import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from stocks import obs
from stocks.data.http import get_bytes

SOCRATA = "https://publicreporting.cftc.gov/resource/{dataset}.json"
TFF = "gpe5-46if"
LEGACY = "6dca-aqww"

# The window the percentile and z-score are measured over, in weekly reports.
WEEKS = 156
# A little more than the window is downloaded, so a skipped report (the
# government shutdown weeks) does not leave the window short.
FETCH_DAYS = 365 * 3 + 45
# Percentile bands past which a side is called crowded.
CROWDED_HIGH = 90.0
CROWDED_LOW = 10.0
# Fewer reports than this and a percentile is an anecdote.
MIN_WEEKS = 52

# Longs first, then shorts: `parse` splits the tuple in half.
TFF_FIELDS = (
    "lev_money_positions_long",
    "asset_mgr_positions_long",
    "lev_money_positions_short",
    "asset_mgr_positions_short",
)
LEGACY_FIELDS = ("noncomm_positions_long_all", "noncomm_positions_short_all")


@dataclass(frozen=True)
class Market:
    """One market the app reads: its key, its CFTC code, which dataset has it."""

    key: str
    code: str
    dataset: str
    name: str


MARKETS = (
    Market("sp500", "13874A", TFF, "E-mini S&P 500"),
    Market("nasdaq100", "209742", TFF, "E-mini Nasdaq-100"),
    Market("ust10y", "043602", TFF, "10-year Treasury note"),
    Market("eurusd", "099741", TFF, "Euro FX"),
    Market("bitcoin", "133741", TFF, "Bitcoin (CME)"),
    Market("gold", "088691", LEGACY, "Gold"),
    Market("crude", "067651", LEGACY, "Crude oil (WTI)"),
)


def _url(dataset: str, codes: list[str], fields: tuple[str, ...], since: date) -> str:
    params = {
        "$select": ",".join(
            (
                "report_date_as_yyyy_mm_dd",
                "cftc_contract_market_code",
                "open_interest_all",
                *fields,
            )
        ),
        "$where": (
            "cftc_contract_market_code in("
            + ",".join(f"'{c}'" for c in codes)
            + f") AND report_date_as_yyyy_mm_dd>'{since.isoformat()}'"
        ),
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": "5000",
    }
    return SOCRATA.format(dataset=dataset) + "?" + urllib.parse.urlencode(params)


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def parse(rows: list[dict], fields: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    """Socrata rows to ``{code: frame}`` with ``net`` and ``oi`` per report date.

    ``net`` is long minus short summed over the speculative columns in
    `fields` (first half longs, second half shorts). A row with any figure
    missing is dropped rather than counted as zero.
    """
    half = len(fields) // 2
    longs, shorts = fields[:half], fields[half:]
    by_code: dict[str, list[tuple[object, float, float]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            when = pd.Timestamp(str(row["report_date_as_yyyy_mm_dd"])[:10])
        except (KeyError, ValueError):
            continue
        net = sum(_num(row.get(f)) for f in longs) - sum(
            _num(row.get(f)) for f in shorts
        )
        if pd.isna(net):
            continue
        code = str(row.get("cftc_contract_market_code", "")).strip()
        by_code.setdefault(code, []).append(
            (when, net, _num(row.get("open_interest_all")))
        )
    out = {}
    for code, items in by_code.items():
        frame = pd.DataFrame(items, columns=["date", "net", "oi"]).set_index("date")
        out[code] = frame[~frame.index.duplicated(keep="last")].sort_index()
    return out


def _fetch_dataset(
    dataset: str, markets: list[Market], fields: tuple[str, ...], since: date
) -> dict[str, pd.DataFrame]:
    url = _url(dataset, [m.code for m in markets], fields, since)
    try:
        rows = json.loads(get_bytes(url, timeout=25))
    except Exception as exc:
        obs.warn("cot.failed", dataset=dataset, error=type(exc).__name__)
        return {}
    if not isinstance(rows, list):
        obs.warn("cot.failed", dataset=dataset, error="not_a_list")
        return {}
    return parse(rows, fields)


def fetch(*, today: date | None = None) -> dict[str, pd.DataFrame]:
    """``{market key: frame(net, oi)}`` for every market that answered.

    The two datasets are fetched side by side. A market the CFTC did not
    answer for is absent from the result.
    """
    since = (today or date.today()) - timedelta(days=FETCH_DAYS)
    jobs = {
        TFF: (TFF_FIELDS, [m for m in MARKETS if m.dataset == TFF]),
        LEGACY: (LEGACY_FIELDS, [m for m in MARKETS if m.dataset == LEGACY]),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {
            ds: pool.submit(_fetch_dataset, ds, markets, fields, since)
            for ds, (fields, markets) in jobs.items()
        }
    frames = {ds: f.result() for ds, f in futures.items()}
    out = {}
    for market in MARKETS:
        frame = frames[market.dataset].get(market.code)
        if frame is not None and not frame.empty:
            out[market.key] = frame
    return out


@dataclass(frozen=True)
class Reading:
    """Where one market's speculators stand now, against their own 3 years."""

    key: str
    name: str
    as_of: str
    net: float
    net_pct_oi: float | None
    week_change: float | None
    percentile: float
    zscore: float | None
    crowded: str | None  # "long" | "short" | None
    spark: list[float]


def reading(market: Market, frame: pd.DataFrame) -> Reading | None:
    """The reading for one market, or None when the history is too short."""
    net = frame["net"].dropna().tail(WEEKS)
    if len(net) < MIN_WEEKS:
        return None
    last = float(net.iloc[-1])
    # Share of the window at or below today's net: 100 = the most long in 3y.
    percentile = float((net <= last).mean() * 100)
    sd = float(net.std(ddof=0))
    zscore = (last - float(net.mean())) / sd if sd > 0 else None
    oi = float(frame["oi"].reindex(net.index).iloc[-1])
    crowded = None
    if percentile >= CROWDED_HIGH:
        crowded = "long"
    elif percentile <= CROWDED_LOW:
        crowded = "short"
    return Reading(
        key=market.key,
        name=market.name,
        as_of=str(net.index[-1].date()),
        net=last,
        net_pct_oi=last / oi * 100 if oi and not pd.isna(oi) else None,
        week_change=last - float(net.iloc[-2]),
        percentile=percentile,
        zscore=zscore,
        crowded=crowded,
        spark=[float(v) for v in net.tail(90)],
    )


def readings(frames: dict[str, pd.DataFrame]) -> list[Reading]:
    """Readings in `MARKETS` order for the markets with enough history."""
    out = []
    for market in MARKETS:
        frame = frames.get(market.key)
        if frame is None:
            continue
        r = reading(market, frame)
        if r is not None:
            out.append(r)
    return out
