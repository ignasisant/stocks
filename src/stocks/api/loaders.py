"""Cached domain calls, wrapped in `api.cache.ttl_cache`.

The keys follow one convention — `(db path, ledger mtime, base currency)`.
`mtime` invalidates a book the moment an import rewrites the file
rather than when a timer expires, and `base` is in the key because money is
computed *in* the reporting currency (each leg at its own trade-date rate),
so two accounts on different currencies must never share an entry.

Nothing is reimplemented here: every function is a cache around a call into
`stocks.portfolio` / `stocks.analysis`. When a number needs changing, it
changes in the domain and every caller gets it.

The memos a page dies without when Yahoo says no — the book's closes, the
watchlist's year, a chart's bars, a company's statements and calendar, the
pulse's series — are declared `persist=`: they land on disk and in the
bucket, and stand in for a refused fetch (`api.cache`). Quotes are not: a
day move is only worth having live.
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import date
from functools import wraps
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stocks import identity, obs, progress
from stocks.analysis import naive_dates
from stocks.analysis.history import PERIODS, bars_download, shape
from stocks.analysis.portfolio import (
    HELD_ACTIONS,
    book_history,
    complete_download,
    load_closes,
    plausible_closes,
    position_values_history,
    positions_frame,
    session_quotes,
)
from stocks.api.cache import (
    Flight,
    carried,
    coalesced,
    disk_path,
    read_entry,
    ttl_cache,
    write_entry,
)
from stocks.config import DATA_DIR
from stocks.data.shared_memo import SharedMemo
from stocks.frames import midnights
from stocks.portfolio import consistency, fees, transfers
from stocks.portfolio.custody import Custody, by_position
from stocks.portfolio.ledger import all_transactions
from stocks.portfolio.positions import build

# Held prices move all day but a book's shape does not; these mirror the ttls
# the pages use for the same loads.
_LEDGER_TTL = 3600.0
_PRICES_TTL = 900.0
_QUOTES_TTL = 300.0


def db_mtime(db: str) -> float:
    """The ledger file's mtime, or 0.0 when it does not exist yet.

    Part of every cache key below, so a committed import invalidates exactly
    the entries that read the file it rewrote.
    """
    path = Path(db)
    return path.stat().st_mtime if path.exists() else 0.0


def ledger_state(db: str, mtime: float, base: str = "EUR", matching: str = "fifo"):
    """Ledger + share-matching replay -> (transactions, positions, realized).

    `matching` is in the key as well as the arguments: FIFO and s.104 produce
    different realized parcels — and different basis left behind — from the
    very same trades.

    Spelled out before the memo: `ttl_cache` keys on the arguments as passed,
    so `ledger_state(db, mtime)`, `(db, mtime, "EUR")` and `base="EUR"` were
    three entries and three replays of one book — seconds each on a long
    ledger, from routes that run side by side on the same page.
    """
    return _ledger_state(db, mtime, base, matching)


@ttl_cache(_LEDGER_TTL, max_entries=32)
def _ledger_state(db: str, mtime: float, base: str, matching: str):
    txs = all_transactions(Path(db))
    positions, realized = build(txs, base=base, matching=matching) if txs else ([], [])
    return txs, positions, realized


ledger_state.cache_clear = _ledger_state.cache_clear  # ty: ignore[unresolved-attribute]


def _currencies(txs) -> dict[str, str]:
    """ticker -> the currency the book traded it in, for the price download's
    venue search (`fetch_many(currencies=…)`)."""
    out: dict[str, str] = {}
    for t in txs:
        if t.action in ("buy", "sell"):
            out.setdefault(t.ticker, t.currency)
    return out


def _held(db: str) -> tuple[list, list[str]]:
    """(relabelled ledger, the names it ever held) — the book's price scope.

    Relabelled first (`transfers.relabel`): a book moved between brokers holds
    one position under two spellings, and downloading the other one prices
    nothing.

    Memoized per version of the file: the memos over it miss together (a book
    just imported, a download just expired), and each of them replayed the
    ledger for the same answer.
    """
    return _held_at(db, db_mtime(db))


@ttl_cache(_LEDGER_TTL, max_entries=32)
def _held_at(db: str, mtime: float) -> tuple[list, list[str]]:
    txs = transfers.relabel(all_transactions(Path(db)))
    held = [t for t in txs if t.action in HELD_ACTIONS]
    return txs, sorted({t.ticker for t in held})


# Strict expiry, not stale-while-revalidate: the two memos derived from it
# below are the ones that serve stale (for up to `_HELD_STALE`, from disk too),
# and their background refresh has to reach a real download here rather than
# be handed the same old frames back.
#
# Four books in memory and eight on disk: one entry is a whole book's OHLCV
# (~6MB live, 3-5MB pickled, for 80 names) and each of the readings below
# keeps its own copy, on an instance whose filesystem is memory too. A fifth
# active book costs a pickle read, not a download — the disk copy is fresh.
# Not persisted: the same frames are already on disk as the book's base
# (`_keep_base`), and a cold call is that base plus one spark request. The
# pickle beside it was every book twice in a filesystem that is memory. The
# last frames in memory still stand in for a refused refresh (`keep_s`); after
# a restart, the readings' own persisted copies do (`held_closes`).
@ttl_cache(_PRICES_TTL, max_entries=4, stale_s=0, keep_s=3 * 86400.0)
def _held_frames(db: str, mtime: float) -> dict[str, pd.DataFrame]:
    """One bulk download covering every name the book has ever held.

    Unadjusted (`auto_adjust=False`), so a single request carries both closes
    a book needs: `Adj Close`, the total-return series every return is
    measured on, and `Close`, the price that actually printed — what a
    52-week edge and the watchlist rows compare against. Home used to fetch
    the held names a second time for that distinction.

    Only the first download of a book reaches back to its first trade. Every
    refresh after it asks for the last month (`_extend`) and lays that over
    the book's previous frames (`_frames_base`): years of bars for eighty
    names were most of a minute on the one throttled vCPU, and all of it
    re-downloaded every quarter hour to learn one new close.

    And only one refresh a day (`_REBASE_S`) asks that month of chart, a
    request per name with every column. The rest ask spark for the closes
    alone, twenty names a request (`fetch.fetch_tail`): fifty chart requests
    every quarter hour were the burst Yahoo throttles. What spark cannot say
    — a dividend restating `Adj Close`, a day's high and low — waits for the
    next rebase, a day at most.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.fetch import fetch_many

    txs, tickers = _held(db)
    if not tickers:
        return {}
    since = min(t.date for t in txs if t.action in HELD_ACTIONS)
    span = (pd.Timestamp.today() - pd.Timestamp(since)).days
    period = f"{max(1, span // 30 + 1)}mo"
    currencies = _currencies(txs)
    base, rebased_at = _frames_base(db, since) or (None, 0.0)
    settled = _settled(base, txs) if base else {}
    rebase = time.time() - rebased_at > _REBASE_S
    # Yahoo throttling the egress IP is reported by `retry` as
    # `yahoo.rate_limit_exhausted`, and callers price the book without these
    # frames (`_self_priced_positions`): weather, not a crash to page on.
    asked = [t for t in tickers if t not in settled]
    fallback: set[str] = set()
    # What the corner banner reads while this runs (`GET /progress`): the step,
    # the names it has done, and how long the same step took last time.
    first = "prices.full" if not base else "prices.rebase" if rebase else "prices.tail"
    with (
        progress.job(db, first, total=len(tickers if not base else asked)),
        obs.timed(
            "prices.held_download", expected=(YFRateLimitError,), tickers=len(tickers)
        ) as rec,
    ):
        if not base:
            frames, stale = {}, tickers
        elif rebase:
            try:
                frames, stale = _extend(base, asked, currencies, rebase=True)
            except YFRateLimitError:
                # Spark is one request where the month of chart was fifty:
                # it may well answer what that refused. The rebase waits.
                obs.warn("prices.rebase_refused", tickers=len(asked))
                rebase = False
                progress.step("prices.tail", total=len(asked))
                frames, stale = _extend(base, asked, currencies)
        else:
            frames, stale = _extend(base, asked, currencies)
        frames.update(settled)
        rec["settled"] = len(settled)
        rec["rebase"] = rebase or not base
        if stale:
            progress.step("prices.full", total=len(stale))
            got = fetch_many(
                stale, period=period, auto_adjust=False, currencies=currencies
            )
            frames.update(got)
            # A keyed fallback's bars (`fetch._eod_fallback`) stand in for
            # this render only: they carry no dividend-adjusted close, and
            # laid under the base they would hide Yahoo's answer until the
            # next rebase. Left out of the base, the next refresh asks Yahoo.
            fallback = {t for t, f in got.items() if f.attrs.get("source")}
            rec["fallback"] = len(fallback)
            progress.tick(len(stale))
        rec["full"] = len(stale)
    # Judged here, at the download, and only here: a gutted download memoised
    # as the book's frames would land on disk and in the bucket besides. The
    # two readings below trust what this returns, and their own copies come
    # back from disk after a restart without a download — re-judging those
    # would be asking `fetch.unlisted` about a download this process never made.
    complete_download(_close_series(frames, "Close"), tickers)
    _keep_base(
        db,
        since,
        {t: f for t, f in frames.items() if t not in fallback},
        time.time() if rebase or not base else rebased_at,
    )
    return frames


# How far back a refresh asks. A month overlaps the previous frames by weeks
# even after a long weekend, which is what `_extend` checks them against.
_TAIL = "1mo"
# How long past its last trade a closed name keeps being refreshed: one whole
# tail laid over the sale, so its last bars are settled ones. After that
# nothing a refresh learns about it reaches any figure — a closed position is
# valued at nothing — and it is a third of the names a book has ever held.
_SETTLE = pd.Timedelta(days=31)
# The columns two downloads of one day must agree on to be laid end to end:
# a dividend rewrites every earlier `Adj Close`, a split every earlier price.
_AGREE = ("Close", "Adj Close")
# How old a book's last chart month may grow before a refresh asks for one
# again instead of spark's closes. Under a day, so the warm-up's pre-market
# tick (Cloud Scheduler, infra/cron.tf) is the one that pays it.
_REBASE_S = 20 * 3600.0


def _extend(
    base: dict[str, pd.DataFrame],
    tickers: list[str],
    currencies: dict[str, str],
    *,
    rebase: bool = False,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """The last month laid over `base`: (frames extended, names to download whole).

    A name goes back for its whole history when the base never had it, or
    when the two disagree on a day both hold — Yahoo restated the past (a
    dividend, a split), so the base's bars are no longer the series this
    month continues. The base's last day is left out of that check: it may
    have been a session still trading. A name Yahoo already said it does not
    list (`fetch.unlisted`) is not asked again: it would come back empty every
    quarter hour.

    The month is chart's when `rebase` (every column, checked on both closes
    and laid from its first day), spark's otherwise: printed closes only, so
    only those are checked — a split still sends the name back whole, a
    dividend waits for the rebase — and only the days from the base's last
    one on are taken (`_lay`).

    A name the month came back without keeps the base's bars as they are.
    Asking for its whole history instead asks the same source that just
    said nothing — a coin while CoinGecko cools off, every quarter hour — and
    when that comes back empty too the name drops out of the book's prices
    altogether rather than standing at its last close.
    """
    from stocks.data.fetch import fetch_many, fetch_tail, unlisted

    known = [t for t in tickers if t in base]
    if not known:
        tail = {}
    elif rebase:
        tail = fetch_many(known, period=_TAIL, auto_adjust=False, currencies=currencies)
    else:
        tail = fetch_tail(known)
    # Gutted is gutted whichever request it was; the whole-history fallback
    # below must not turn a refused month into eighty full downloads.
    complete_download(_close_series(tail, "Close"), known)
    frames: dict[str, pd.DataFrame] = {}
    for t in known:
        new, old = tail.get(t), base[t]
        if new is None or new.empty:
            if not old.empty:
                frames[t] = old
                obs.warn_once("prices.tail_missing", t, ticker=t)
            continue
        if old.empty or new.index[0] <= old.index[0]:
            frames[t] = new  # a name bought this month: the month is all of it
        elif rebase and _continues(old, new):
            frames[t] = pd.concat([old[old.index < new.index[0]], new])
        elif not rebase and _continues(old, new, ("Close",)):
            frames[t] = _lay(old, new)
    disowned = unlisted(tickers)
    return frames, [t for t in tickers if t not in frames and t not in disowned]


def _settled(base: dict[str, pd.DataFrame], txs: list) -> dict[str, pd.DataFrame]:
    """The base's frames for names closed `_SETTLE` before their last bar.

    Taken as they are, not asked for again: the history a closed position
    needs ends at its sale, and the base already holds a month past it. A
    name bought back is open again and leaves this set by itself; its gap
    since the sale fails `_continues` and it is downloaded whole.
    """
    try:
        positions, _ = build(txs, to_base=lambda amount, ccy, day: amount)
    except Exception:  # noqa: BLE001 — an inconsistent ledger refreshes everything
        return {}
    open_ = {p.ticker for p in positions}
    last: dict[str, str] = {}
    for t in txs:
        if t.action in HELD_ACTIONS and t.ticker not in open_:
            last[t.ticker] = max(last.get(t.ticker, t.date), t.date)
    out: dict[str, pd.DataFrame] = {}
    for ticker, day in last.items():
        frame = base.get(ticker)
        if frame is not None and not frame.empty:
            if naive_dates(frame.index)[-1] >= pd.Timestamp(day) + _SETTLE:
                out[ticker] = frame
    return out


def _continues(
    old: pd.DataFrame, new: pd.DataFrame, agree: tuple[str, ...] = _AGREE
) -> bool:
    """Whether `new` agrees with `old` on every settled day both hold."""
    shared = old.index[:-1].intersection(new.index)
    cols = [c for c in agree if c in old.columns and c in new.columns]
    if shared.empty or not cols or old.index[-1] < new.index[0]:
        return False
    a = old.loc[shared, cols].to_numpy(dtype=float)
    b = new.loc[shared, cols].to_numpy(dtype=float)
    return bool(np.allclose(a, b, rtol=1e-5, atol=0.0, equal_nan=True))


def _lay(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """`new`'s days from `old`'s last one on, over `old`.

    Not the whole month: the base's earlier bars carry what a close-only
    month does not (the day's high and low, `Adj Close` as the last rebase
    adjusted it), and the base's last day — a session that may still have
    been trading — keeps those columns while its closes are brought up to
    date.
    """
    cut = old.index[-1]
    fresh = new[new.index >= cut]
    if fresh.empty:
        return old
    fresh = fresh.combine_first(old[old.index >= cut])
    return pd.concat([old[old.index < cut], fresh.reindex(columns=old.columns)])


# The last frames each book was priced from, and the first trade they reach
# back to — what the next refresh extends. Keyed by the ledger's path alone,
# not its mtime: an import changes which names are held, not the bars of the
# ones that were, and the file a boot restores from the bucket carries a new
# mtime every time. On disk (and in the bucket) beside the memo, so the first
# Home after a deploy extends rather than downloads.
# Beside them, when the book's last chart month was asked (`_REBASE_S`).
_bases: dict[str, tuple[str, dict[str, pd.DataFrame], float]] = {}
_bases_lock = threading.Lock()
# As many live as `_held_frames` keeps — they share its frames — and on disk
# as many books as the readings of them (`held_closes`).
_BASES_LIVE = 4
# Frames compress 2.5x against the closes' 5x, so fewer of them on disk keep
# the bytes where four raw ones were (`_HELD_ON_DISK`).
_BASES_ON_DISK = 10


def _base_path(db: str) -> Path:
    return disk_path("held_base", (db,))


def _stored_base(db: str) -> tuple | None:
    """The book's last kept frames as `_keep_base` wrote them, memory first."""
    with _bases_lock:
        held = _bases.get(db)
    if held is None:
        with obs.swallow("prices.base_restore"):
            entry = read_entry(_base_path(db), 0.0, _BASES_ON_DISK)
            if entry is not None:
                held = entry[1]
    return held


def _frames_base(db: str, since: str) -> tuple[dict[str, pd.DataFrame], float] | None:
    """(the book's previous frames, when they were rebased), when they reach
    back to `since` (ISO). A base written before rebases were stamped reads
    as never rebased."""
    held = _stored_base(db)
    if held is None:
        return None
    reaches: str = held[0]
    frames: dict[str, pd.DataFrame] = held[1]
    rebased_at = float(held[2]) if len(held) > 2 else 0.0
    # A trade imported from before the base began: its history is missing.
    return (frames, rebased_at) if reaches <= since else None


def _keep_base(
    db: str, since: str, frames: dict[str, pd.DataFrame], rebased_at: float
) -> None:
    with _bases_lock:
        _bases.pop(db, None)
        _bases[db] = (since, frames, rebased_at)
        while len(_bases) > _BASES_LIVE:
            _bases.pop(next(iter(_bases)))
    with obs.swallow("prices.base_persist"):
        write_entry(
            _base_path(db),
            (0.0, (since, frames, rebased_at), time.time()),
            _BASES_ON_DISK,
        )


def _close_series(frames: dict[str, pd.DataFrame], column: str) -> dict[str, pd.Series]:
    """`load_closes`'s shape — one named Series per ticker, NaNs dropped —
    read off one column of each frame. A frame without the column (the crypto
    fallbacks carry no `Adj Close`) reads its `Close`: a coin pays nothing to
    adjust for."""
    out: dict[str, pd.Series] = {}
    for ticker, df in frames.items():
        name = column if column in df else "Close"
        series = df[name].dropna() if name in df else pd.Series(dtype=float)
        if not series.empty:
            out[ticker] = series.rename(ticker)
    return out


# How long the book's last prices answer at once while the next download runs
# behind them. The download is twenty seconds to a minute on the production
# vCPU, and every Home, Posiciones and Pulso read waits on it: with a 45-minute
# window, the first visit of every morning (and the first after any hour away)
# paid all of it. Past the quiet window the answer is marked stale, so the
# page says how old its figures are until the refresh has landed. Persisted,
# so a new process answers from the last one's prices the same way — they are
# a fraction of the frames' size, one Series per name.
_HELD_STALE = 2 * 86400.0
_HELD_QUIET = 3 * _PRICES_TTL
# Four books live, sixteen on disk: past four readers in a morning a book
# evicted from memory comes back off disk in milliseconds, not off the bucket
# or a fresh download. Compressed (`cache._ZLEVEL`), sixteen weigh about what
# four did raw — memory, on Cloud Run.
_HELD_ON_DISK = 16


@ttl_cache(
    _QUOTES_TTL,
    max_entries=4,
    stale_s=_HELD_STALE,
    quiet_s=_HELD_QUIET,
    persist="held_closes",
    disk_max=_HELD_ON_DISK,
)
def held_closes(db: str, mtime: float) -> dict[str, pd.Series]:
    """Adjusted close per name the book has ever held, from `_held_frames`,
    its last bar at the live price (`_overlay_live`).

    The series every return, value and history is measured on. Refused whole
    (`YFRateLimitError`) when the download came back gutted — `_held_frames`
    raises it — so a throttled burst is never memoized as a book worth a
    third of itself.
    """
    txs, tickers = _held(db)
    if not tickers:
        return {}
    return _overlay_live(_frame_closes(db, mtime, "Adj Close", txs), (db, "Adj Close"))


@ttl_cache(
    _QUOTES_TTL,
    max_entries=4,
    stale_s=_HELD_STALE,
    quiet_s=_HELD_QUIET,
    persist="held_printed_closes",
    disk_max=_HELD_ON_DISK,
)
def held_printed_closes(db: str, mtime: float) -> dict[str, pd.Series]:
    """Close as printed per held name, from the same download as `held_closes`.

    What `api.home.year_closes` reads for the names the ledger holds, instead
    of asking `watchlist_closes` to download them again unadjusted.
    """
    txs, tickers = _held(db)
    if not tickers:
        return {}
    return _overlay_live(_frame_closes(db, mtime, "Close", txs), (db, "Close"))


# One reading per book and column of the frames it was read from, and of the
# overlay laid over it. `held_closes` now recomputes every five minutes for
# the live layer while the frames move every fifteen; re-reading them each
# time would hand `_on_download` a new object and rebuild every frame of the
# book for nothing. Same frames in, same object out; same quotes over it,
# same object out. Capped like `_held_frames` itself: each entry keeps its
# frames alive.
_READINGS: dict[tuple, tuple[object, object, dict]] = {}
_READINGS_MAX = 8
_readings_lock = threading.Lock()


def _remember(key: tuple, source: object, sign: object, value: dict) -> dict:
    with _readings_lock:
        _READINGS.pop(key, None)
        _READINGS[key] = (source, sign, value)
        while len(_READINGS) > _READINGS_MAX:
            _READINGS.pop(next(iter(_READINGS)))
    return value


def _recall(key: tuple, source: object, sign: object = None) -> dict | None:
    with _readings_lock:
        hit = _READINGS.get(key)
    if hit is not None and hit[0] is source and hit[1] == sign:
        return hit[2]
    return None


def _frame_closes(db: str, mtime: float, column: str, txs) -> dict[str, pd.Series]:
    """`column` of the book's frames as `load_closes` would shape it, less the
    names its own fills say are another instrument (`plausible_closes`)."""
    frames = _held_frames(db, mtime)
    key = ("frames", db, column)
    if (hit := _recall(key, frames)) is not None:
        return hit
    closes = plausible_closes(_close_series(frames, column), txs)
    return _remember(key, frames, None, closes)


# A live price about a hundred times the name's last close, or a hundredth of
# it, is another unit (pence against pounds), not a move. Anything nearer is
# left alone: a small cap doubling in a session is a real day (AB9.DE,
# 2026-10-13, 2.60 to 5.99), and hiding it shows yesterday's price
# (`consistency.unit_slip`).
def _overlay_live(
    closes: dict[str, pd.Series], key: tuple | None
) -> dict[str, pd.Series]:
    """`closes` with each name's last bar brought to its live regular price.

    The bars come from a refresh at most fifteen minutes old (`_held_frames`);
    the batch quote (`quotes`, one request, five-minute memo) is fresher. A
    quote for a later session than the last bar adds that bar; one for the
    same session replaces its close; an older one, or pre/after-hours, leaves
    the series alone — those are a move, not a close (`_snapshot`). Never
    fails the memo it runs in: no quotes is the bars as they were.

    `key` names the reading for the identity short-circuit (`_READINGS`);
    None for a memo nothing downstream keys on.
    """
    if not closes:
        return closes
    with obs.swallow("prices.live"):
        snaps = quotes(tuple(sorted(closes)))
        moves: dict[str, tuple[Any, float]] = {}
        rejected = 0
        for ticker, series in closes.items():
            snap = snaps.get(ticker) or {}
            price, day = snap.get("regular"), snap.get("regular_as_of")
            if not price or not day or series.empty:
                continue
            when = pd.Timestamp(day)
            if (zone := getattr(series.index, "tz", None)) is not None:
                when = when.tz_localize(zone)
            last_day, last = series.index[-1], float(series.iloc[-1])
            if when < last_day or (when == last_day and price == last):
                continue
            if last > 0 and consistency.unit_slip(float(price) / last):
                rejected += 1
                obs.warn_once(
                    "prices.live_rejected", ticker, ticker=ticker, last=last, live=price
                )
                continue
            moves[ticker] = (when, float(price))
        if not moves:
            return closes
        sign = tuple(sorted((t, w.isoformat(), p) for t, (w, p) in moves.items()))
        live_key = ("live", *key) if key is not None else None
        if live_key and (hit := _recall(live_key, closes, sign)) is not None:
            return hit
        out = dict(closes)
        appended = 0
        for ticker, (when, price) in moves.items():
            series = closes[ticker].copy()
            appended += when not in series.index
            series.loc[when] = price
            out[ticker] = series
        obs.event(
            "prices.live",
            tickers=len(closes),
            replaced=len(moves) - appended,
            appended=appended,
            rejected=rejected,
        )
        return _remember(live_key, closes, sign, out) if live_key else out
    return closes


_clear_adjusted = held_closes.cache_clear  # ty: ignore[unresolved-attribute]


def _clear_held(expire: bool = True) -> None:
    """Drop the download and both readings of it together — a refresh that
    cleared one would have the other re-derived from the frames it kept."""
    _held_frames.cache_clear(expire)  # ty: ignore[unresolved-attribute]
    _held_at.cache_clear(expire)  # ty: ignore[unresolved-attribute]
    with _readings_lock:
        _READINGS.clear()
    _clear_adjusted(expire)
    held_printed_closes.cache_clear(expire)  # ty: ignore[unresolved-attribute]


held_closes.cache_clear = _clear_held  # ty: ignore[unresolved-attribute]


def _on_download(fn):
    """Memoize `fn(db, mtime, base, closes)` on the `held_closes` object itself.

    Every "value of the book" the pages print — the Posiciones and Home
    tiles, Rendimiento real, the last point of the value chart, the
    day/week/month deltas, a ticker's share of the book — is read off one of
    the frames below. Each used to sit in its own timer (15 min here, an hour
    for the history), so two of them could be built from two different
    downloads and the same "Valor de mercado" printed two numbers. Keyed on
    the download they were built from, they rebuild together the moment it is
    replaced and can never straddle two. Holding the object in the entry keeps
    the identity test sound: a live object's id cannot be reused.
    """
    store: dict[tuple, tuple[object, object]] = {}
    flights: dict[tuple, Flight] = {}
    lock = threading.Lock()

    @wraps(fn)
    def wrapper(db: str, mtime: float, base: str = "EUR"):
        closes = held_closes(db, mtime)
        # Single-flight like `ttl_cache`: the three movers windows, the tiles
        # and the chart all ask for the same frame in the same instant, and
        # each replay of a book is seconds of pandas on one vCPU. A waiter that
        # arrived holding a *newer* download than the flight's gets the
        # flight's frame — one TTL older at most, and the next call rebuilds.
        return coalesced(
            store,
            flights,
            lock,
            (db, mtime, base),
            fresh=lambda entry: entry[0] is closes,
            compute=lambda: (closes, fn(db, mtime, base, closes)),
            # Each entry holds the `closes` it was built from, so an entry
            # left behind by a newer download keeps that whole download alive
            # after `held_closes` has let it go: the cap is per book, not per
            # frame.
            max_entries=8,
        )

    clearable: object = wrapper
    clearable.cache_clear = store.clear  # ty: ignore[unresolved-attribute]
    return wrapper


@_on_download
def _priced_positions(db: str, mtime: float, base: str, closes) -> pd.DataFrame:
    positions = ledger_state(db, mtime, base)[1]
    vals = position_values_history(positions, base=base, closes=closes)
    latest = (
        {t: float(v) for t, v in vals.iloc[-1].items() if pd.notna(v)}
        if not vals.empty
        else None
    )
    return positions_frame(positions, base=base, values=latest)


@ttl_cache(_PRICES_TTL, max_entries=16)
def _self_priced_positions(db: str, mtime: float, base: str) -> pd.DataFrame:
    """The table while Yahoo refuses the book's download.

    The live pass alone priced 7 of 47 names one throttled morning, and the
    Home row then set a 28k "Valor hoy" beside the 111k that went in. Whatever
    it misses reads the book's last kept frames instead (`_stored_base`) — a
    close a day old at most, flagged `stale` so the page can say so — and
    only a name those never held stays NaN.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.analysis import portfolio as analysis

    positions = ledger_state(db, mtime, base)[1]
    try:
        values = analysis.market_values(positions, base=base)
    except YFRateLimitError:
        values = {}
    missing = [p for p in positions if p.ticker not in values]
    kept = _kept_values(db, missing, base) if missing else {}
    if not values and not kept:
        # Nothing at all: the caller's own degrade path, as before.
        raise YFRateLimitError()
    table = positions_frame(positions, base=base, values={**kept, **values})
    if not table.empty:
        table["stale"] = table.index.isin(list(kept))
    return table


def _kept_values(db: str, positions: list, base: str) -> dict[str, float]:
    """`base` value per position at its last close in the kept frames."""
    held = _stored_base(db)
    if held is None:
        return {}
    txs, _tickers = _held(db)
    closes = plausible_closes(_close_series(held[1], "Adj Close"), txs)
    with obs.swallow("prices.kept_values"):
        vals = position_values_history(positions, base=base, closes=closes)
        if not vals.empty:
            return {t: float(v) for t, v in vals.iloc[-1].items() if pd.notna(v)}
    return {}


def positions_table(db: str, mtime: float, base: str = "EUR") -> pd.DataFrame:
    """Per-position frame in `base`: shares, cost, live value, unrealised P/L.

    Values are the last row of `held_closes`, the download `history()` and
    `basket_values()` are built from too (`_on_download`), so every tile that
    prints the book's value reads the same prices.

    A name it has no series for reads NaN in `value` rather than zero, which
    is what keeps `priced_totals` from dividing an intact book's whole basis
    by a fraction of its market value. Prices itself only when `held_closes`
    refuses an incomplete download — Yahoo throttling — and then the history
    endpoints are refusing too, rather than disagreeing with it.
    """
    from yfinance.exceptions import YFRateLimitError

    try:
        return _priced_positions(db, mtime, base)
    except YFRateLimitError:
        return _self_priced_positions(db, mtime, base)


def book_value_today(
    db: str, mtime: float, base: str, hist: pd.DataFrame
) -> float | None:
    """What the book is worth today, one figure for every tile that prints it.

    The Positions tile sums the priced table; the Overview, the Risk tab and
    the projection read the last point of the replayed value path. The two are
    built off the same download, but by different arithmetic, and they landed
    a euro apart on a six-figure book ("Valor hoy" 146.196 against 146.197).
    The table is what the rest of the app quotes, so when every position
    priced it is the figure; otherwise the path (which carries the unpriced at
    cost) stands.
    """
    from stocks.analysis.portfolio import priced_totals

    table = positions_table(db, mtime, base)
    if not table.empty and "value" in table:
        _cost, value, unpriced = priced_totals(table)
        if not unpriced and value > 0:
            return float(value)
    series = hist["value"].dropna() if "value" in hist else pd.Series(dtype=float)
    return float(series.iloc[-1]) if not series.empty else None


def allocation_weights(
    db: str, mtime: float, base: str, meta: dict[str, dict], key: str, fallback
) -> dict[str, float]:
    """`key`'s buckets as shares of the book, off the priced positions table.

    The Allocation tab and the Pulse card each read their own backtest report,
    whose weights come from that download's last close and drop whatever has no
    series in its window — so one book printed Technology at 36% on one and
    41.6% on the other, and USD at 81% against 80.6%. Both read this instead:
    the rows the tiles print, priced ones only, as the slices' own value and
    cost sums already do. `fallback` is the report's own split, for a table
    with nothing priced.
    """
    from stocks.analysis.portfolio import allocation_parts

    table = positions_table(db, mtime, base)
    if table.empty or "value" not in table:
        return dict(fallback)
    amounts = {
        str(ticker): float(value) for ticker, value in table["value"].dropna().items()
    }
    parts = allocation_parts(amounts, meta, key)
    sums = {label: sum(held.values()) for label, held in parts.items()}
    total = sum(sums.values())
    if not total:
        return dict(fallback)
    return dict(sorted(((k, v / total) for k, v in sums.items()), key=lambda kv: -kv[1]))


def _clear_positions() -> None:
    _priced_positions.cache_clear()
    _self_priced_positions.cache_clear()  # ty: ignore[unresolved-attribute]


positions_table.cache_clear = _clear_positions  # ty: ignore[unresolved-attribute]


@_on_download
def history(db: str, mtime: float, base: str, closes):
    """Full-span daily history: (injected-vs-value frame, daily TWR, unpriced).

    Built from the same download as `positions_table`, so its last value is
    the one the Posiciones tile prints. No timer of its own: a rebuild is a
    third of a second, and an hour-old copy is what used to show a different
    "Valor de mercado" on Rendimiento real than on Posiciones.
    """
    return book_history(all_transactions(Path(db)), base=base, closes=closes)


# How far back the fixed basket reaches. The movers card's longest window is a
# month, and three months covers it with room to spare.
_BASKET_MONTHS = 3


@_on_download
def basket_values(db: str, mtime: float, base: str, closes) -> pd.DataFrame:
    """Daily `base` value per open position at *today's* quantities.

    The frame the day/week/month deltas are measured on, and NOT
    `history()`'s `value` column: that one is the book as it happened, so a
    deposit or an import inside the window lands in it and reads as a gain —
    a €12k book that took €38k on a Monday shows "+316% this week" when
    nothing moved. A basket held at today's shares cannot say that: every day
    carries the same quantities, so money moving in or out is invisible to it
    and only prices and rates move the line.

    Which also makes the question it answers a hypothetical one — what today's
    book would have done over the window, a name bought yesterday included,
    priced back across days nobody held it. That is the right question for
    "how is my portfolio doing" and the wrong one for "what did this account
    earn", which is `history()` and `/portfolio/performance`. A name with no
    price at one end of a window drops out there (`basket_change`) rather than
    being counted from zero.

    Values rather than closes, because the shares are in them: a book is
    judged in its reporting currency, so a position's move includes its FX
    move. Prices come off the book's shared download, sliced to the window —
    no request of its own.
    """
    positions = ledger_state(db, mtime, base)[1]
    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(months=_BASKET_MONTHS)
    window = {}
    for ticker, series in closes.items():
        # Series arrive naive or stamped in the exchange's zone depending on
        # the market; `naive_dates` is where the app flattens that.
        tail = series[naive_dates(series.index) >= cutoff]
        if not tail.empty:
            window[ticker] = tail
    return position_values_history(
        positions, period=f"{_BASKET_MONTHS}mo", base=base, closes=window
    )


@ttl_cache(_QUOTES_TTL, max_entries=64)
def quotes(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Live snapshot per ticker in ONE request; unquotable names drop out.

    The full snapshot rather than the bare percentage, because `as_of` is what
    stops a Wednesday response from printing Monday's close as "today".
    """
    return session_quotes(list(tickers))


# ----------------------------------------------------------- one ticker's page
# Ranges and quotes move all day; a company's calendar does not. The ttls below
# mirror what the Ticker page uses for the same loads.
_HISTORY_TTL = 300.0
_EVENTS_TTL = 3600.0


@ttl_cache(_HISTORY_TTL, max_entries=64, persist="bars", disk_max=64)
def _bars_download(ticker: str, period: str, interval: str) -> pd.DataFrame:
    return bars_download(ticker, period, interval)


def price_bars(ticker: str, label: str) -> pd.DataFrame:
    """OHLCV plus indicators for one range label, shaped by `analysis.history`.

    The memo is on the download, not the label: the four daily labels under a
    year are one 2y frame cut four ways, and keying by label fetched it four
    times as a reader flipped through them.
    """
    period, interval = PERIODS[label]
    return shape(_bars_download(ticker, period, interval), label)


price_bars.cache_clear = _bars_download.cache_clear  # ty: ignore[unresolved-attribute]


def bar_closes(ticker: str, label: str) -> pd.Series:
    """Adjusted daily closes behind `label`, untrimmed — its whole download.

    The comparison card reads other listings at the subject's first day, which
    can sit a session before their own trimmed window opens. Same memo as
    `price_bars`, so a name the reader also charts costs nothing more.
    """
    period, interval = PERIODS[label]
    df = _bars_download(ticker, period, interval)
    if df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    return df["Close"]


# The review's return columns: a book of 150 names would evict every chart
# the ticker pages keep warm in `_bars_download`'s 64 entries, and needs five
# closes of each, not five years. So the download is its own and only the
# closes on the days a window opens or ends are kept.
@ttl_cache(_PRICES_TTL, max_entries=512)
def window_closes(ticker: str, days: str) -> pd.Series:
    """Adjusted close in the listing's own money on each of `days` (ISO,
    comma-separated — `analysis.compare.window_axis`): the last close on or
    before each, NaN before the listing's history."""
    from stocks.analysis.compare import on_axis
    from stocks.data.fetch import fetch_history

    df = fetch_history(ticker, period="5y", interval="1d")
    if df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    return on_axis(df["Close"], pd.DatetimeIndex(days.split(",")))


# `disk_max` on the per-name memos below: the memo directory is RAM on Cloud
# Run (`cache.MEMO_DIR`), and eight memos each keeping the default 256 files
# was tens of MB of the 1 GiB for names nobody had opened in a week.
@ttl_cache(_EVENTS_TTL, max_entries=64, persist="earnings", disk_max=64)
def earnings(ticker: str):
    """(all known earnings dates, reported results) — one yfinance pass.

    Never raises: Yahoo throttles shared cloud IPs hard, and a calendar is
    garnish on a price chart. An empty answer degrades the markers; an
    exception would take the whole response down with them.
    """
    from stocks.data.earnings import fetch_earnings

    try:
        return fetch_earnings(ticker)
    except Exception as exc:
        obs.warn(
            "api.earnings_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return [], []


@ttl_cache(_PRICES_TTL, max_entries=32)
def spot_rates(ccys: tuple[str, ...], base: str = "EUR") -> dict[str, float]:
    """{currency: native->`base` spot} for the currencies a book trades in.

    Every money figure here is computed *in* the reporting currency, so
    dividing one back by its rate is how a share price gets quoted in the
    currency its market quotes it in. Pairs whose lookup fails are absent —
    the caller prints nothing rather than a dollar figure under a euro sign.
    """
    from concurrent.futures import ThreadPoolExecutor

    from stocks.data.fx import spot

    def rate(ccy: str) -> float | None:
        if str(ccy).upper() == base.upper():
            return 1.0
        with obs.swallow("fx.spot", ccy=ccy, base=base):
            return float(spot(ccy, base)[0])
        return None

    # One request per pair, side by side: a book in six currencies waited for
    # six round trips in a row on every cold Posiciones load.
    unique = list(dict.fromkeys(ccys))
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=min(len(unique), 8)) as pool:
        rates = list(pool.map(carried(rate), unique))
    return {ccy: r for ccy, r in zip(unique, rates, strict=True) if r is not None}


def native_price(row, rates: dict[str, float]) -> float | None:
    """One share's price in the currency it trades in, backed out of `value`.

    `value` is shares * price * rate, so dividing by the shares and the rate
    (`spot_rates`) recovers the quote. Null rather than a guess when the row
    has no value or the pair is missing: a price under the wrong symbol is
    worse than none.
    """
    shares, value = row.get("shares"), row.get("value")
    rate = rates.get(str(row.get("ccy") or "").upper())
    if not shares or not rate or value is None or pd.isna(value):
        return None
    return float(value) / float(shares) / rate


@ttl_cache(_LEDGER_TTL, max_entries=32)
def native_positions(db: str, mtime: float):
    """Open positions carrying *native-currency* cost — identity FX, no network.

    What a per-ticker view needs: the share count and the average buy price in
    the currency the position actually trades in. Converting those to a
    reporting currency would price the whole book to answer a question about
    one name.
    """
    txs = all_transactions(Path(db))
    positions, _ = build(txs, to_base=lambda amount, ccy, day: amount)
    return {p.ticker: p for p in positions}


@ttl_cache(_LEDGER_TTL, max_entries=32)
def custody(db: str, mtime: float) -> dict[str, dict[str, Custody]]:
    """Open shares per (ticker, broker): which broker's account holds them.

    Identity FX like `native_positions` — the split is a share count, not a
    basis, so this stays off the network too.
    """
    return by_position(all_transactions(Path(db)), to_base=lambda a, c, d: a)


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="fundamentals", disk_max=64)
def fundamentals(ticker: str):
    """One yfinance fundamentals pull: info, income statements, cash flow.

    Three sections of the page read it — the KPI grid, the financials charts
    and the moat score — and each used to be its own cached call. One pull,
    one cache entry, three derivations.
    """
    from stocks.data import esef
    from stocks.data.fundamentals import fetch_fundamentals

    # EU/UK issuers' audited annual statements (ESEF) over Yahoo's. Disk only:
    # the first sight of a name returns Yahoo's frames and fetches the filing
    # in the background, so no page waits on it.
    return esef.overlay(fetch_fundamentals(ticker))


# The review page scores a whole book plus its watchlist — fifty names is a
# normal account — off the ticker page's KPIs. Holding each name's frames for
# that would blow `fundamentals`' cap (and memory) every visit, so the review
# keeps only the derived KPI dict: a few hundred bytes a name, a day old at
# worst. Statements move quarterly and the price-led ratios by a few percent
# a day, which no verdict threshold notices. A stale entry answers at once
# while it refreshes; the gate keeps those refreshes from leaving as one burst.
_METRICS_TTL = 4 * 3600.0
_metrics_gate = threading.BoundedSemaphore(6)


@ttl_cache(_METRICS_TTL, max_entries=256, stale_s=20 * 3600.0, persist="review_metrics")
def review_metrics(ticker: str) -> dict:
    """`compute_metrics` over `fundamentals(ticker)`, memoized as the dict."""
    from stocks.analysis.fundamentals import compute_metrics

    with _metrics_gate:
        return compute_metrics(fundamentals(ticker))


# Where each name's business stood at its last few filings, for the review
# map's "then" point. A filing lands once a quarter at most, so a day is fresh
# and a week still right; kept apart from `review_metrics` so the API's row
# metrics stay today's.
@ttl_cache(
    24 * 3600.0,
    max_entries=256,
    stale_s=7 * 86400.0,
    persist="review_history",
    disk_max=128,
)
def review_history(ticker: str) -> list[dict]:
    """`filed_history` over `fundamentals(ticker)`: [{filed, then, base}]."""
    from stocks.analysis.fundamentals import filed_history

    with _metrics_gate:
        return filed_history(fundamentals(ticker))


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="estimates", disk_max=64)
def estimates(ticker: str):
    """Analyst price targets, EPS/revenue consensus and ratings.

    Degrades to an empty RawEstimates per field rather than raising, so a name
    with no coverage renders as "no consensus" instead of failing the request.
    """
    from stocks.data.estimates import fetch_estimates

    return fetch_estimates(ticker)


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="rating_changes", disk_max=64)
def rating_changes(ticker: str) -> list[dict]:
    """Recent upgrades, downgrades, initiations and target changes, newest first.

    A refusal raises (never memoized as "no changes"); a name Yahoo has no
    coverage for answers `[]`.
    """
    from stocks.data.estimates import fetch_rating_changes
    from stocks.data.estimates import rating_changes as fold

    return fold(fetch_rating_changes(ticker), date.today())


# How long the last in-session options reading answers while the market is
# shut: a long weekend, Friday's close to Tuesday's open, and a little over.
_SESSION_KEEP_S = 5 * 86400.0


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="options", disk_max=64)
def options_view(ticker: str) -> dict | None:
    """ATM implied volatility and put/call ratios; None when nothing is listed.

    Cold this is an expiry list plus up to four chains (~3-6 s), which is why
    it has its own endpoint and slot. A refusal raises, so a throttled minute
    is never cached as "no options".
    """
    from stocks.data.options import closed, fetch_chains, summarize

    raw = fetch_chains(ticker)
    path = disk_path("options_session", (ticker,))
    if closed(raw):
        # Out of session the chain is zeroed; the last in-session reading is
        # what the market said, and it is still the latest thing it said.
        kept = read_entry(path, 0.0)
        if kept is not None and time.time() - kept[2] < _SESSION_KEEP_S:
            return kept[1]
        return None
    view = summarize(raw, date.today())
    if view is not None:
        with obs.swallow("options.keep_session"):
            write_entry(path, (time.monotonic(), view, time.time()))
    return view


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="valuation", disk_max=64)
def valuation(ticker: str) -> dict:
    """P/E reconstructed against its own history: {source, pe, stats, current}.

    `source` says which filing feed backed it — SEC EDGAR, FMP, or None when
    neither yields quarterly EPS. A client has to print that: a multiple with
    no provenance is a number somebody will act on.
    """
    from stocks.analysis.pe_history import pe_vs_history

    try:
        return pe_vs_history(ticker)
    except Exception as exc:
        obs.warn(
            "api.pe_history_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return {"source": None, "pe": None, "stats": None, "current": None}


@ttl_cache(_EVENTS_TTL, max_entries=32)
def insiders(ticker: str):
    """Recent Form 4 lines, newest filing first; [] when the feed says nothing.

    US filers only through this path. The EU regulators publishing the same
    disclosure are `data.bafin` and `data.cnmv`, which the route folds in separately.
    """
    from stocks.data.insiders import insider_transactions

    try:
        return insider_transactions(ticker)
    except Exception as exc:
        obs.warn(
            "api.insiders_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return []


def issuer_name(ticker: str) -> str | None:
    """The company name a register or a headline is searched by.

    Yahoo's `longName` first. Then the fund catalog and the SEC map, without
    any watchlist: a name somebody typed on their own list is theirs, not the
    company's. Rarely reached: the common miss is Yahoo throttled, and a German
    issuer is then usually in neither list, so the caller says "not covered"
    rather than guessing.
    """
    issuer = str(fundamentals(ticker).info.get("longName") or "").strip()
    if issuer:
        return issuer
    try:
        from stocks.data.funds import fund_name

        resolved = display_symbol(ticker)
        return fund_name(resolved) or sec_title(resolved)
    except Exception:
        return None


@ttl_cache(_EVENTS_TTL, max_entries=32)
def _bafin_insiders(ticker: str):
    from stocks.data.bafin import insider_transactions

    issuer = issuer_name(ticker)
    return insider_transactions(ticker, issuer=issuer) if issuer else []


# CNMV reads PDFs in the background and report whether they all got read: a
# complete list is kept like any event feed, a partial one only briefly so the
# next load picks up what the workers have memoised since.
_CNMV_PARTIAL_TTL = 60.0
_CNMV_MAX = 32
_cnmv_cache: dict[str, tuple[float, list]] = {}
_cnmv_lock = threading.Lock()


def _cnmv_insiders(ticker: str):
    from stocks.data import cnmv

    key = ticker.upper()
    now = time.monotonic()
    with _cnmv_lock:
        hit = _cnmv_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    issuer = issuer_name(ticker)
    rows, complete = cnmv.read(ticker, issuer=issuer) if issuer else ([], True)
    ttl = _EVENTS_TTL if complete else _CNMV_PARTIAL_TTL
    with _cnmv_lock:
        if len(_cnmv_cache) >= _CNMV_MAX:
            _cnmv_cache.pop(min(_cnmv_cache, key=lambda k: _cnmv_cache[k][0]))
        _cnmv_cache[key] = (time.monotonic() + ttl, rows)
    return rows


def eu_insiders(ticker: str):
    """Art. 19 MAR notifications for a German (BaFin) or Spanish (CNMV) issuer,
    searched by the company's name; [] for any other listing, a name not found
    or a failed search (the registers' readers never raise)."""
    from stocks.data.bafin import german_listing
    from stocks.data.cnmv import spanish_listing

    if german_listing(ticker):
        return _bafin_insiders(ticker)
    if spanish_listing(ticker):
        return _cnmv_insiders(ticker)
    return []


def _clear_eu_insiders() -> None:
    getattr(_bafin_insiders, "cache_clear", lambda: None)()
    with _cnmv_lock:
        _cnmv_cache.clear()


@ttl_cache(3600.0, max_entries=64)
def headlines(ticker: str):
    """The last days' headlines that name `ticker`'s company (`data.news`).
    The SEC map's title first — a local file, no request — then Yahoo's name.
    Raises on a failed search."""
    from stocks.data import edgar, news

    try:
        name = edgar.title_for(ticker)
    except Exception:  # noqa: BLE001 — the name is a help, not a need
        name = None
    if not name:
        try:
            name = issuer_name(ticker)
        except Exception:  # noqa: BLE001
            name = None
    return news.headlines(ticker, name)


# 8-Ks are read a month back and narrowed by the caller: one cached feed per
# name serves a Monday card and a Thursday one alike.
FILINGS_DAYS = 30


@ttl_cache(10800.0, max_entries=64)
def current_reports(ticker: str):
    """`ticker`'s 8-Ks over FILINGS_DAYS (`data.edgar`); [] for a name that
    does not file with the SEC. Raises on a refused request."""
    from datetime import timedelta

    from stocks.data import edgar

    return edgar.current_reports(ticker, date.today() - timedelta(days=FILINGS_DAYS))


@ttl_cache(86400.0, max_entries=64)
def institutions(ticker: str):
    """`ticker`'s institutional holders (`data.holders`), or None. A day's
    ttl: the figures move once a quarter. Raises on a failed request."""
    from stocks.data import holders

    return holders.institutions(ticker)


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


# ---------------------------------------------------------------- search tiers
# The tiers themselves live in `stocks.search`; these are the cached lookups it
# is handed. Every one swallows its exceptions: search degrading to the tiers
# that answered is the app's behaviour, and a dead Yahoo must not 500 a
# keystroke.

_SEARCH_TTL = 86400.0
# Short and strict: the answers themselves live in WORLD_MEMO, and an empty
# list from a throttled Yahoo must not stand in for a minute longer than this.
_WORLD_TTL = 60.0


@ttl_cache(_LEDGER_TTL, max_entries=32)
def held(db: str, mtime: float) -> tuple[str, ...]:
    """Tickers with an open position, so imported activity is searchable.

    Quantities need no FX, so the replay runs with an identity converter and
    stays offline — this is on the path of every keystroke.
    """
    try:
        positions, _ = build(all_transactions(Path(db)), to_base=lambda a, c, d: a)
        return tuple(p.ticker for p in positions)
    except Exception:
        return ()  # an empty or inconsistent ledger must never break search


@ttl_cache(_SEARCH_TTL, max_entries=256)
def sec_title(ticker: str) -> str | None:
    """Company name for a held-but-unlisted ticker, from the SEC map."""
    from stocks.data.edgar import title_for

    try:
        return title_for(ticker)
    except Exception:
        return None


@ttl_cache(_SEARCH_TTL, max_entries=128)
def sec_matches(query: str) -> list[tuple[str, str]]:
    """SEC ticker-map search. In-memory, but memoised so typing doesn't rescan."""
    from stocks.data.edgar import search_companies

    try:
        return search_companies(query, limit=6)
    except Exception:
        return []


# What Yahoo lists for a query, shared by every account and kept across boots:
# a symbol, once listed, stays listed, and the same few hundred queries ("nvda",
# "asml") are what everybody types. A month an answer — new listings do appear.
# A few MB of JSON at the cap.
#
# The bucket must not become a log of what people type, so the key is a hash
# of the query, an empty answer (a typo, a name, whatever was in the field)
# is never kept, and an ISIN is never asked through it: an ISIN somebody types
# is one they hold, which is the fingerprint `isin_symbols.json` stays local
# to avoid.
WORLD_MEMO = SharedMemo(DATA_DIR / "symbol_search.json", ttl=30 * 86400.0, cap=5000)


def _world_key(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:24]


@ttl_cache(_WORLD_TTL, max_entries=128, stale_s=0.0)
def world_matches(query: str) -> list[tuple[str, str, str]]:
    """Worldwide symbol search (Yahoo) — the only search tier that is a network
    round-trip, so its answers live in `WORLD_MEMO` for every account; this
    process-wide memo in front is what makes a burst of keystrokes one call.

    Only a listing is kept: an empty list from a throttled host is "could not
    ask", and a real "nothing" is a typed string nobody else needs to read.
    """
    from stocks.data import funds, symbols
    from stocks.fuzzy import MIN_QUERY

    key = query.strip().upper()
    if len(key) < MIN_QUERY:
        return []
    shared = not symbols.is_isin(key)
    if shared and (hit := WORLD_MEMO.get(_world_key(key))) is not None:
        for symbol, _, _, quote_type in hit:
            funds.remember(symbol, quote_type)  # the row's label, as on a miss
        return [(s, n, x) for s, n, x, _ in hit]
    try:
        rows = symbols.search_rows(key, limit=6)
    except Exception:
        return []
    if shared and rows:
        WORLD_MEMO.put(_world_key(key), rows)
    return [(s, n, x) for s, n, x, _ in rows]


@ttl_cache(_SEARCH_TTL, max_entries=128)
def coin_matches(query: str) -> list[tuple[str, str]]:
    """Coin pairs for a query — a local table, cached only to skip the rescan."""
    from stocks.data.crypto import search_crypto

    try:
        return search_crypto(query)
    except Exception:
        return []


@ttl_cache(_SEARCH_TTL, max_entries=128)
def fund_matches(query: str) -> list[tuple[str, str]]:
    """Fund catalog matches — the tier that still answers while Yahoo throttles."""
    from stocks.data.funds import search_funds

    try:
        return search_funds(query)
    except Exception:
        return []


def related(ticker: str) -> tuple[str, ...]:
    """Rivals for Compare and the evidence pack: both `peer_groups`, rivals
    first, as one list."""
    rivals, watched = peer_groups(ticker)
    return (*rivals, *watched)


@ttl_cache(86400.0, max_entries=128)
def peer_groups(ticker: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(rivals, also watched) for the comps picker.

    Rivals are the sector screen's cohort in the same industry, double-checked
    (`analysis.sectors`). Also watched is Yahoo's "people also watch" list,
    which is what readers co-view: next to Adobe it had PayPal, Visa and
    Broadcom. Only the names filed under the subject's own industry are kept —
    a name whose industry cannot be told is dropped, never vouched for. A
    subject with no industry (a fund) keeps the list as Yahoo sent it.

    A day's ttl and empty on any failure: a suggestion nobody asked for must
    never be the thing that fails the page.
    """
    from stocks.analysis.sectors import industry_rivals
    from stocks.data.related import related_tickers

    try:
        yahoo = related_tickers(ticker)
    except Exception:
        yahoo = []
    try:
        scans = sector_scans()
    except Exception:
        scans = {}
    industry = _industry(ticker, scans)
    try:
        rivals = industry_rivals(scans, ticker) or (
            industry_rivals(scans, ticker, industry) if industry else []
        )
    except Exception:
        rivals = []
    # Another class of the same company (GOOG beside GOOGL) is no rival.
    own = sec_title(ticker)
    rivals = [r for r in rivals if not own or sec_title(r) != own]
    watched = [s for s in dict.fromkeys(yahoo) if s not in rivals]
    if industry and watched:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(len(watched), 4)) as pool:
            filed = list(pool.map(lambda s: _industry(s, scans), watched))
        watched = [s for s, i in zip(watched, filed, strict=True) if i == industry]
    return tuple(rivals), tuple(watched)


def _industry(ticker: str, scans: dict) -> str | None:
    """Yahoo's industry for `ticker`: the nightly scan, the profile memo, then
    `info` — None when none of them can say."""
    from stocks.data import profiles
    from stocks.data.fetch import info, resolve

    subject = ticker.upper()
    for scan in scans.values():
        for m in scan.metrics:
            if str(m.get("ticker", "")).upper() == subject and m.get("industry"):
                return str(m["industry"])
    stored = profiles.known(resolve(ticker)) or {}
    if stored.get("industry"):
        return stored["industry"]
    # A fund files under no industry. An equity without one is a memo written
    # before the field was kept, so `info` is asked (and fills it in).
    if stored.get("quoteType", "EQUITY") != "EQUITY":
        return None
    try:
        return info(ticker).get("industry") or None
    except Exception:
        return None


# ------------------------------------------------------------------- identity
# What a ticker is called and what it looks like. All three reach the network
# on a cold path and none of them changes within a day.

_IDENTITY_TTL = 86400.0


@ttl_cache(_IDENTITY_TTL, max_entries=512)
def display_symbol(ticker: str) -> str:
    """The Yahoo symbol a stored broker label resolves to."""
    return identity.yahoo_symbol(ticker)


def listed(ticker: str) -> bool | None:
    """Whether Yahoo quotes `ticker` at all — None when it could not say.

    False only on two agreeing answers: a profile that came back cleanly with
    no quoteType (Yahoo's 404 for a symbol it has never heard of) and no year
    of bars. A throttle raises instead, and that is None: a page must never
    call a real company missing because the feed was busy. Both reads are the
    ones the page makes anyway, so asking costs nothing extra.
    """
    from stocks.data import asset_kind as kinds
    from stocks.data import fetch
    from stocks.data.crypto import is_crypto
    from stocks.data.funds import quote_type

    if is_crypto(ticker) or kinds.known(ticker) or quote_type(ticker, fetch=False):
        return True
    if fetch.retired(ticker):
        return None
    try:
        if fetch.info(ticker).get("quoteType"):
            return True
        return not price_bars(ticker, "1y").empty
    except Exception:
        return None


def missing(ticker: str, db: str, name: str | None) -> bool:
    """Whether `ticker` is no symbol at all, for this account.

    `name` is `company_name`'s answer, which the caller already holds. A name
    from any source (the account's own list first), or a row in the book,
    makes it somebody's: a delisted line held at cost is still a page worth
    opening. Only then is Yahoo asked, and only its sure "no" counts. The
    ledger is read uncached: only a symbol nothing knows gets this far.
    """
    if name:
        return False
    if listed(display_symbol(ticker)) is not False:
        return False
    try:
        return not any(t.ticker == ticker for t in all_transactions(Path(db)))
    except Exception:
        return False


@ttl_cache(_IDENTITY_TTL, max_entries=512)
def _company_name(ticker: str, watchlist: str) -> str | None:
    return identity.company_name(ticker, watchlist)


def company_name(ticker: str, watchlist: str) -> str | None:
    """Human name for a ticker.

    `watchlist` is in the key, not just the arguments: a custom name one
    account set on its own list must never render for another.

    A miss is not held for the day like a hit: it asks the two memos again,
    which costs two dict reads. A name the page header (`listing_name`) or a
    peer list (`listing_names`) learns after the miss would otherwise leave
    every list drawing "2330.TW" while the header above says TSMC.
    """
    if name := _company_name(ticker, watchlist):
        return name
    from stocks.data import profiles

    symbol = display_symbol(ticker)
    return (profiles.known(symbol) or {}).get("name") or learned_name(symbol)


def listing_name(symbol: str) -> str | None:
    """Yahoo's own name for a listing, asked when no local source has one.

    `company_name` never reaches Yahoo for it: the bulk routes (search, the
    profiles batch) call it per row, and a quoteSummary each is what the
    profile memo exists to avoid. The page header is one symbol, and a non-US
    listing nobody holds — "005930.KS", which is Samsung — has no other source,
    so the header asks here once. The blob lands in the profile memo, so the
    next `company_name` miss finds it. Not memoized: a refused fetch must be
    asked again, not held as "no name" for a day.
    """
    from stocks.data import profiles
    from stocks.data.fetch import info

    if name := (profiles.known(symbol) or {}).get("name"):
        return name
    try:
        blob = info(symbol)
    except Exception:
        return None
    return blob.get("longName") or blob.get("shortName") or None


# What `listing_names` has learned, per process. Names only, never written
# into the profile memo: a blob there with a name and no sector would read
# as a company with no sector to the allocation donuts that trust it.
_LISTING_NAMES: dict[str, str] = {}
_LISTING_NAMES_CAP = 4096


def listing_names(symbols: list[str]) -> dict[str, str]:
    """`{symbol: name}` for a list of other companies — peers, compare lines.

    The SEC map and the profile memo first, then one spark request for every
    twenty still unnamed (`spark.names`), where `.info` would be one each. A
    non-US peer has no other source: without this "Valores relacionados" on
    Sony read "7974.T", "8306.T". Only names found are kept, so a refused
    request is asked again next time rather than held as "no name".
    """
    from stocks.data import profiles
    from stocks.data.spark import names

    out: dict[str, str] = {}
    cold: list[str] = []
    for symbol in dict.fromkeys(symbols):
        name = (
            sec_title(symbol)
            or (profiles.known(symbol) or {}).get("name")
            or _LISTING_NAMES.get(symbol)
        )
        if name:
            out[symbol] = name
        else:
            cold.append(symbol)
    if cold:
        found = names(cold)
        if len(_LISTING_NAMES) + len(found) > _LISTING_NAMES_CAP:
            _LISTING_NAMES.clear()
        _LISTING_NAMES.update(found)
        out.update(found)
    return out


def learned_name(symbol: str) -> str | None:
    """A name `listing_names` already found, without asking anybody."""
    return _LISTING_NAMES.get(symbol)


@ttl_cache(_IDENTITY_TTL, max_entries=512)
def logo(ticker: str) -> str | None:
    """Same-origin logo URL, absolute.

    Absolute, not relative: a relative path would resolve against whatever
    route the reader happens to be on.
    """
    return identity.logo_src(ticker, prefix="/" + identity.STATIC_PREFIX)


def mirrored_logo(ticker: str) -> str | None:
    """`logo`, from this host's mirror only — never a network call. Not
    memoized: a stat per row, and a miss must see the file once it lands."""
    return identity.logo_src(ticker, prefix="/" + identity.STATIC_PREFIX, fetch=False)


@ttl_cache(_IDENTITY_TTL, max_entries=64)
def brand_logo(broker: str) -> str | None:
    """Same-origin logo for a broker brand — the custody marks in the header.

    Mirrored into the same directory ticker logos are, for the same reason: the
    brand's CDN never sees a request per viewer telling it who banks where. The
    external URL is the fallback for an image this host could not fetch, and
    None is the honest answer for a key that declares no domain at all — a
    hand-entered row has no brand, and the client draws a name pill instead.
    """
    from stocks.portfolio import platforms

    return _brand_src(broker, platforms.broker_domain(broker))


@ttl_cache(_IDENTITY_TTL, max_entries=16)
def provider_logo(provider: str, domain: str | None) -> str | None:
    """Same-origin logo for a chat provider — the marks on the settings tiles.

    Mirrored under an `ai-` key so a provider can never take a broker's file,
    and None for the keyless chain, which is this app's own and has no brand
    domain to ask for.
    """
    return _brand_src(f"ai-{provider}", domain)


def _brand_src(key: str, domain: str | None) -> str | None:
    from stocks.data.logo import brand_logo_url, mirror_brand

    if not domain:
        return None
    if name := mirror_brand(key, domain, identity.STATIC_LOGO_DIR):
        return "/" + identity.STATIC_PREFIX + name
    return brand_logo_url(domain)


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


def daily_closes(ticker: str, period: str = "max") -> pd.Series:
    """Daily closes over `period` off the shared bar download, or empty."""
    try:
        df = _bars_download(ticker, period, "1d")
    except Exception as exc:
        obs.warn(
            "api.daily_closes_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return pd.Series(dtype=float)
    if df is None or df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    close.index = midnights(pd.DatetimeIndex(close.index).tz_localize(None))
    return close[~close.index.duplicated(keep="last")]


@ttl_cache(_LEDGER_TTL, max_entries=16)
def crypto_replay(db: str, mtime: float, prefs: str, prefs_mtime: float):
    """The ledger replayed under the account's tax rules (`chat.whatif`), the
    yardstick a coin's harvest line is measured against. Keyed on both files'
    mtimes: a new trade or a changed residence each change the answer."""
    from stocks.chat import whatif

    return whatif.replay(db=Path(db), prefs_path=Path(prefs))


# --------------------------------------------------------------- the book's cost
# What the Portfolio page's Fees, Dividends and Risk tabs each need, with the
# ttls those tabs already use. Same rule as everything above: the cache lives
# here, the arithmetic lives in the domain.


@ttl_cache(_LEDGER_TTL, max_entries=4, stale_s=_HELD_STALE)
def trade_bars(db: str, mtime: float) -> dict[str, pd.DataFrame]:
    """Daily UNADJUSTED OHLC per traded ticker, spanning the whole ledger.

    Feeds the spread estimate: execution prices are as-traded, so the reference
    bars must not be dividend-adjusted (`auto_adjust=False` — splits are
    replayed from the ledger in `portfolio.fees`). They are the book's own
    download (`_held_frames`) — same names, same span, same unadjusted bars —
    which this used to ask Yahoo for a second time, whole, on its own.

    Served stale like the closes read off it, so the Fees tab never waits on
    a refresh; copies, because the listing currency is stamped on each frame
    and the frames are shared with every other reading of the book.
    """
    frames = {t: df.copy(deep=False) for t, df in _held_frames(db, mtime).items()}
    # An alias can price a ticker on another venue (Revolut's dollar ASML ->
    # ASML.AS in euros); the spread converts when the frames say so.
    return fees.stamp_listing_currency(frames, fees.listing_currencies(list(frames)))


@ttl_cache(21600.0, max_entries=8)
def dividend_estimates(db: str, mtime: float, base: str = "EUR") -> tuple:
    """(estimated years, forward income, forward totals in `base`, unrecorded).

    What the book was entitled to, from Yahoo's per-share history and the
    ledger's own share timeline — the half no statement can be asked for, since
    a dividend is owed to whoever held the share the day before it went ex
    whether or not the import carried a row for it. Six-hour ttl: a payment goes
    ex once a quarter and this is one request per name ever held.

    Raises `YFRateLimitError` when Yahoo is in cooldown and nothing came back,
    so a throttled minute is never cached as "this book pays nothing" — the
    route turns it into a 503 with a `Retry-After` like every other fetch here.
    """
    from stocks.portfolio import dividends as div

    txs, history, payments = _entitled(db, mtime, base)
    estimated = div.estimate_by_year(payments, base=base)
    forward = div.forward_income(txs, history)
    totals = div.forward_totals(forward, base=base)
    unrecorded = div.unrecorded_by_year(
        div.by_year(txs, base=base, capital=True), estimated
    )
    return estimated, forward, totals, unrecorded


@ttl_cache(21600.0, max_entries=8)
def unbooked_dividends(db: str, mtime: float, base: str = "EUR") -> list[tuple]:
    """[(EstimatedPayment, gross in `base` or None), …], newest first.

    The payments `dividend_estimates` counts as unrecorded, one by one: what the
    shares were entitled to with no ledger dividend row to answer for it. Most
    of them are the tail a statement never reached — it was exported in July,
    the book kept paying in August. Valued at the ex-date's rate, as the yearly
    estimate is; a date with no rate is None, never today's standing in.

    Raises `YFRateLimitError` under the same rule as `dividend_estimates`.
    """
    from stocks.data.fx import converter, prefetch
    from stocks.portfolio import dividends as div

    txs, _history, payments = _entitled(db, mtime, base)
    missing = div.unbooked(payments, transfers.relabel(txs))
    prefetch((p.ex_date, p.currency) for p in missing)
    to_base = converter(base)
    out: list[tuple] = []
    for p in reversed(missing):
        try:
            amount = to_base(p.gross, p.currency, p.ex_date)
        except Exception:  # noqa: BLE001 — an unpriced row is n/a, not a 500
            amount = None
        out.append((p, amount))
    return out


@ttl_cache(21600.0, max_entries=8)
def dividend_payments(db: str, mtime: float, base: str = "EUR") -> list:
    """Every ex-date the ledger's shares were entitled to, oldest first.

    `EstimatedPayment`s straight off `_entitled`: the calendar's past dividend
    chips, drawn whether or not a statement ever booked the cash.

    Raises `YFRateLimitError` under the same rule as `dividend_estimates`.
    """
    return _entitled(db, mtime, base)[2]


@ttl_cache(
    21600.0,
    max_entries=16,
    stale_s=_HELD_STALE,
    quiet_s=21600.0,
    persist="ex_dividends",
)
def ex_dividends(tickers: tuple[str, ...]) -> list:
    """The next declared ex-date per name, inside a year — `DividendEvent`s.

    Keyed on the ticker tuple like `earnings_calendar`, and six hours like it:
    a company declares once a quarter. Yahoo's `exDividendDate` stays on the
    LAST ex-date until the next is declared, so most names come back with
    nothing ahead — which is the answer, not a gap.

    Raises `YFRateLimitError` when Yahoo is in cooldown and nothing came back,
    so a throttled minute is never cached as "nothing declared".
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.dividends import upcoming_ex_dividends
    from stocks.data.fetch import throttle_remaining

    if not tickers:
        return []
    if throttle_remaining():
        raise YFRateLimitError
    events = upcoming_ex_dividends(list(tickers), within_days=366)
    if not events and throttle_remaining():
        raise YFRateLimitError
    return events


@ttl_cache(
    21600.0,
    max_entries=16,
    stale_s=_HELD_STALE,
    persist="dividend_histories",
    disk_max=16,
)
def dividend_histories(tickers: tuple[str, ...]) -> dict:
    """Per-share payment history per name — what the projected ex-dates repeat
    and what the Dividendos tab's estimates start from (`_entitled`).

    `DividendHistory`s keyed by the caller's label, names that pay nothing
    left out. One request per name — eighty for a book that has held eighty —
    and the process memo under it (`stocks.data.dividends`) died with every
    restart, so it is persisted, and served stale for a while: a series only
    changes when a payment goes ex.

    Raises `YFRateLimitError` when Yahoo throttled any of them: a name that
    came back empty then may well pay, and a persisted "pays nothing" would
    outlive the cooldown by days.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.dividends import histories
    from stocks.data.fetch import throttle_remaining

    if not tickers:
        return {}
    found = histories(list(tickers))
    if throttle_remaining():
        raise YFRateLimitError
    return found


def _entitled(db: str, mtime: float, base: str) -> tuple:
    """(ledger, per-share histories, every payment the shares were owed).

    The half both dividend estimates start from. The histories are memoized
    (`dividend_histories`), so the second loader to ask pays no request.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.dividends import histories
    from stocks.data.fetch import throttle_remaining
    from stocks.portfolio import dividends as div

    txs = ledger_state(db, mtime, base)[0]
    tickers = sorted(
        {t.ticker for t in transfers.relabel(txs) if t.action in HELD_ACTIONS}
    )
    try:
        history = dividend_histories(tuple(tickers))
    except YFRateLimitError:
        # What the process memo has: the names that did come back.
        history = histories(tickers)
    if not history and (tickers and throttle_remaining()):
        raise YFRateLimitError
    return txs, history, div.estimate_payments(txs, history)


# Persisted and served stale like the book's own download (`_HELD_STALE`): the
# backtest downloads every held name again over its own window, seconds cold,
# and the risk tab and both Pulso cards wait on it. ~2 MB a book.
@ttl_cache(
    _LEDGER_TTL,
    max_entries=16,
    stale_s=_HELD_STALE,
    quiet_s=_HELD_QUIET,
    persist="basket_report",
    disk_max=8,
)
def basket_report(db: str, mtime: float, base: str, period: str):
    """Today's holdings backtested at fixed `base` weights over `period`.

    A risk profile of what is held *now* — not a performance figure, which is
    what `history` returns. The weights are rebuilt on one currency's footing
    after the fetch, because `analyze` weights in native prices and a book that
    is mostly USD with some EUR is measured wrong by that.

    So are the returns, and for the same reason. `analyze` reads them off
    native closes, which measured a book whose *weights* were in the reporting
    currency against moves that were not: the volatility, the drawdown, the
    betas and the whole correlation matrix came out with the currency leg
    missing — for a EUR reader in US names, the seven-odd annual points of
    EUR/USD simply were not in the answer. Per-position values in `base` are
    the same prices times the daily rate, and their ratio is the move that
    reader actually lived. The benchmarks are converted with them
    (`rebase_returns`), because a beta with the dollar on one side only is not
    a beta.
    """
    from stocks.analysis.portfolio import (
        analyze,
        first_owned,
        holdings_from_positions,
        rebase_report,
    )

    txs, positions, _ = ledger_state(db, mtime, base)
    if not positions:
        return None
    report = analyze(period=period, holdings=holdings_from_positions(positions))
    return rebase_report(report, positions, base, period, since=first_owned(txs))


def inception_period(first_trade: str) -> str:
    """The shortest fetch window that reaches back to the book's first trade.

    The same ladder the Portfolio page climbs for its "since inception" choice:
    yfinance only takes named periods, so the fetch is the next one up and the
    slice to the first trade happens afterwards (`basket_report_since`).
    """
    span = (pd.Timestamp.today().normalize() - pd.Timestamp(first_trade)).days
    if span <= 360:
        return "1y"
    if span <= 700:
        return "2y"
    if span <= 1780:
        return "5y"
    return "max"


def basket_report_since(db: str, mtime: float, base: str):
    """`basket_report` clipped to the book's first trade — the page's default.

    Measured from the stock's IPO the backtest would score years the reader
    never held anything: a volatility and a drawdown for money that was not
    there, and betas taken over the same borrowed past. So the basket returns,
    each benchmark's returns and the correlation input all start at the first
    transaction.

    A copy, never the cached report mutated in place: `basket_report` is
    memoized and shared with every other window (and with the Pulse page), and
    slicing it here would quietly shorten theirs too. After the rebase, not
    before — `rebase_report` rebuilds `returns` from the full download and
    would undo the slice.

    Not memoized: the slice is a few filters, and a memo of its own would keep
    the report it was cut from — and that report's stale mark — for an hour
    after `basket_report` had refreshed.
    """
    from dataclasses import replace

    txs = ledger_state(db, mtime, base)[0]
    if not txs:
        return None
    first = min(t.date for t in txs)
    report = basket_report(db, mtime, base, inception_period(first))
    if report is None:
        return None
    start = pd.Timestamp(first)

    def since(obj):
        # Series come back naive or stamped in an exchange's zone depending on
        # the market; compare on the naive calendar date either way.
        return obj[naive_dates(obj.index) >= start]

    # The basket's daily return is sliced rather than rebuilt: it is weighted
    # per date (`portfolio_returns` renormalises each day over the names that
    # traded), so a day's figure does not depend on the days before it and the
    # slice is exactly what a rebuild over the clipped frame would give.
    return replace(
        report,
        returns=since(report.returns),
        bench_returns={b: since(r) for b, r in report.bench_returns.items()},
        port_returns=since(report.port_returns),
    )


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


# ------------------------------------------------------------------ the pulse
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


@ttl_cache(
    _PRICES_TTL,
    max_entries=32,
    stale_s=_HELD_STALE,
    quiet_s=_HELD_QUIET,
    persist="watchlist_closes",
)
def watchlist_closes(tickers: tuple[str, ...]) -> dict[str, pd.Series]:
    """A year of closes for a set of names, in ONE bulk download.

    Keyed on the ticker tuple rather than an account, so two accounts tracking
    the same names share it. A year because that is what a 52-week extreme
    needs; anything shorter cannot answer the question at all.

    Prices as they printed (`adjusted=False`), which is the difference between
    a 52-week high and a 52-week total return. An adjusted series walks every
    close before an ex-date down by the dividend, so the high of a payer sits
    under the price somebody actually paid for it — and the name reads as
    sitting at its high while it is a dividend's worth below it. This is the
    only reader of the download, so nothing else pays for the distinction.
    """
    if not tickers:
        return {}
    closes = load_closes(list(tickers), period="1y", adjusted=False)
    return _overlay_live(closes, None)


def file_mtime(path: Path) -> float:
    """Any account file's mtime, or 0.0 when it does not exist yet.

    The sibling of `db_mtime` for the JSON files beside the ledger: part of a
    cache key so a rewrite invalidates exactly the entry that read it.
    """
    return path.stat().st_mtime if path.exists() else 0.0


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
