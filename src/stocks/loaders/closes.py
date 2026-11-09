"""The held names' daily closes: downloaded once, extended by the tail,
rebased, and overlaid with the live quote.
"""

from __future__ import annotations

import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stocks import obs, progress
from stocks.analysis.portfolio import (
    HELD_ACTIONS,
    complete_download,
    load_closes,
    plausible_closes,
    session_quotes,
)
from stocks.cache import (
    Flight,
    coalesced,
    disk_path,
    read_entry,
    register,
    ttl_cache,
    write_entry,
)
from stocks.frames import naive_dates
from stocks.loaders.keys import (
    _HELD_QUIET,
    _HELD_STALE,
    _LEDGER_TTL,
    _PRICES_TTL,
    _QUOTES_TTL,
    db_mtime,
)
from stocks.portfolio import consistency, fees, transfers
from stocks.portfolio.ledger import all_transactions
from stocks.portfolio.positions import build


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
    register(f"{fn.__module__.rsplit('.', 1)[-1]}.{fn.__qualname__}", store, lock)

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


@ttl_cache(_QUOTES_TTL, max_entries=64)
def quotes(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Live snapshot per ticker in ONE request; unquotable names drop out.

    The full snapshot rather than the bare percentage, because `as_of` is what
    stops a Wednesday response from printing Monday's close as "today".
    """
    return session_quotes(list(tickers))


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
