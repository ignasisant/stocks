"""P/E relative to its own history — is today's multiple rich or cheap?

No free source publishes a clean historical P/E series, so we reconstruct it:

    P/E(t) = split-adjusted price(t) / TTM diluted EPS known at t

Price comes from yfinance (split-adjusted). TTM EPS is rebuilt from per-quarter
diluted EPS (SEC EDGAR primary; FMP fallback for non-US), summed over a trailing
four quarters and stamped at each quarter's *filing* date to avoid look-ahead
bias. As-reported EPS is split-adjusted to match the price series — without this
a split (e.g. NVDA 10:1) destroys the historical window.

A foreign filer (20-F: Sony) files no quarters, only years, often in its home
currency under IFRS. Its series is the last fiscal year's EPS, stamped at its
filing, over the price converted into the filing currency day by day — and is
drawn only when the listing provably carries one share (`ADR_BAND`), because a
depositary receipt worth eight shares would read eight times as dear.

Pure functions (split_factors / discrete_quarters / reconstruct_ttm_eps /
annual_eps / pe_series / window_stats) take their inputs explicitly and run
offline; only pe_vs_history touches the network.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import cast

import pandas as pd

# Trailing windows to average the multiple over, in calendar days.
WINDOWS: dict[str, int] = {"6mo": 182, "1y": 365, "2y": 730, "5y": 1825}

# The ranges a company page offers on the P/E chart, which are a longer set:
# the question there is "is this expensive for this company", and half a year
# of its own history cannot answer it. Here rather than in a page because two
# front ends draw that selector, and a selector whose options differ between
# them is two different questions wearing one label.
DISPLAY_WINDOWS: dict[str, int] = {"1y": 365, "3y": 1095, "5y": 1825, "10y": 3650}

# How long a fiscal year's EPS stands for a filer that reports only years. The
# next 20-F lands about a year after the last one; past that, the figure is a
# filing the feed is missing, not the latest one — the line stops rather than
# dividing today's price by earnings two years old.
ANNUAL_MAX_AGE_DAYS = 400

# A series whose last point is older than this, against the last close, has no
# "today": its current multiple and percentile are left blank.
FRESH_DAYS = 7

# Yahoo's trailing EPS for the listing over the filed year's, both per share in
# the quote's currency. One share per listing reads near 1 (SONY 1.14, NVO
# 1.16, SAP 1.19, ASML 1.49 on 2026-11-15); a receipt for several reads near
# their count (TM 9.8, BABA 5.0, PDD 3.6, HDB 3.3). Outside the band the line
# would be the receipt's multiple off by that count, so it is not drawn.
ADR_BAND = (0.6, 1.67)


def split_factors(
    splits: Mapping[date, float] | pd.Series, ends: Iterable[date]
) -> dict[date, float]:
    """Cumulative split ratio applied *after* each period end.

    Divide as-reported EPS for a period by this factor to express it in
    today's share basis (matching split-adjusted prices). A 10:1 split after
    a quarter gives that quarter a factor of 10.
    """
    items: list[tuple[date, float]]
    if isinstance(splits, pd.Series):
        # A yfinance splits Series is keyed by Timestamp; the comparison
        # below is against plain dates.
        items = [
            (ts.date(), float(v))
            for ts, v in zip(pd.DatetimeIndex(splits.index), splits, strict=True)
        ]
    else:
        items = [(k, float(v)) for k, v in splits.items()]
    out: dict[date, float] = {}
    for end in ends:
        factor = 1.0
        for sdate, ratio in items:
            if sdate > end and ratio:
                factor *= ratio
        out[end] = factor
    return out


def discrete_quarters(
    facts: pd.DataFrame, factors: Mapping[date, float] | None = None
) -> pd.DataFrame:
    """Split-adjusted discrete quarterly EPS rows, with Q4 derived from FY − 3Q.

    `facts` has columns end/filed/eps/kind as returned by edgar/fmp
    diluted_eps_facts: 'Q' rows are discrete quarters, 'FY' rows full fiscal
    years (10-Ks never report a discrete Q4). Split adjustment happens FIRST so
    the FY and its three quarters share one per-share basis — subtracting
    as-reported values across a mid-year split would corrupt Q4.

    Returns columns end/filed/eps, oldest-first. A FY row only yields a Q4 when
    exactly three discrete quarters fall inside its year window.
    """
    cols = ["end", "filed", "eps"]
    if facts is None or facts.empty:
        return pd.DataFrame(columns=cols)
    df = facts.copy()
    if factors:
        df["eps"] = [
            eps / factors.get(end, 1.0)
            for end, eps in zip(df["end"], df["eps"], strict=True)
        ]
    if "kind" not in df.columns:
        return df[cols].sort_values("end").reset_index(drop=True)

    q = df[df["kind"] == "Q"]
    q_ends = set(q["end"])
    derived = []
    for _, fy in df[df["kind"] == "FY"].iterrows():
        if fy["end"] in q_ends:
            continue  # discrete Q4 already reported
        year_start = fy["end"] - timedelta(days=370)
        inside = q[(q["end"] > year_start) & (q["end"] < fy["end"])]
        if len(inside) != 3:
            continue  # missing quarters — can't isolate Q4
        derived.append(
            {"end": fy["end"], "filed": fy["filed"],
             "eps": float(fy["eps"]) - float(inside["eps"].sum())}
        )
    out = pd.concat([q[cols], pd.DataFrame(derived, columns=cols)], ignore_index=True)
    return out.sort_values("end").reset_index(drop=True)


def reconstruct_ttm_eps(
    quarters: pd.DataFrame, factors: Mapping[date, float] | None = None
) -> pd.Series:
    """Trailing-twelve-month EPS stamped at each quarter's filing date.

    `quarters` has columns end/filed/eps (oldest-first). `factors` split-adjusts
    each quarter's EPS; missing/None means factor 1.0. Returns a Series indexed
    by the filing date (when the market learned that TTM figure), duplicates
    resolved to the latest filing.
    """
    if quarters is None or quarters.empty or len(quarters) < 4:
        return pd.Series(dtype=float)
    q = quarters.sort_values("end").copy()
    if factors:
        q["eps"] = [
            eps / factors.get(end, 1.0)
            for end, eps in zip(q["end"], q["eps"], strict=True)
        ]
    q["ttm"] = q["eps"].rolling(4).sum()
    q = q.dropna(subset=["ttm"])
    ttm = pd.Series(q["ttm"].values, index=pd.to_datetime(q["filed"])).sort_index()
    return ttm[~ttm.index.duplicated(keep="last")]


def annual_eps(
    facts: pd.DataFrame, factors: Mapping[date, float] | None = None
) -> pd.Series:
    """Fiscal-year EPS stamped at its filing date, for a filer with no quarters.

    Split-adjusted like the quarters. Where one filing carries several years
    (a first 20-F reports three), the latest year is the one it made known.
    """
    if facts is None or facts.empty or "kind" not in facts.columns:
        return pd.Series(dtype=float)
    fy = facts[facts["kind"] == "FY"].copy()
    if fy.empty:
        return pd.Series(dtype=float)
    fy["eps"] = [
        eps / (factors or {}).get(end, 1.0)
        for end, eps in zip(fy["end"], fy["eps"], strict=True)
    ]
    fy["filed"] = pd.to_datetime(fy["filed"])
    fy = fy.sort_values(["filed", "end"])
    known = pd.Series(fy["eps"].to_numpy(dtype=float), index=fy["filed"])
    return known[~known.index.duplicated(keep="last")]


def pe_series(
    close: pd.Series, ttm_known: pd.Series, max_age_days: int | None = None
) -> pd.Series:
    """Daily P/E from split-adjusted close and filing-stamped TTM EPS.

    TTM EPS is forward-filled from each filing date onto the price index, so
    each day uses the most recent figure that was actually public that day.
    Non-positive or non-finite ratios (loss-making TTM) are dropped, and with
    `max_age_days` so is every day whose figure in force was filed longer ago
    than that (a filing missing from the feed, not a figure still current).
    """
    if close is None or close.empty or ttm_known.empty:
        return pd.Series(dtype=float)
    close = close.copy()
    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    idx = close.index.union(ttm_known.index)
    ttm_aligned = ttm_known.reindex(idx).ffill().reindex(close.index)
    pe = (close / ttm_aligned).replace([float("inf"), float("-inf")], pd.NA)
    if max_age_days is not None:
        stamps = pd.Series(ttm_known.index, index=ttm_known.index)
        in_force = stamps.reindex(idx).ffill().reindex(close.index)
        pe = pe[(close.index - in_force) <= pd.Timedelta(days=max_age_days)]
    pe = pe.dropna()
    return pe[pe > 0]


def window_stats(
    pe: pd.Series,
    current: float | None = None,
    windows: dict[str, int] = WINDOWS,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Per-window mean/median/range, current percentile, z-score, premium.

    `premium` is current / mean − 1: positive means today's P/E sits above its
    trailing average (richer than usual), negative means cheaper. `percentile`
    is where today's P/E falls within the window's distribution (0–100).

    Windows count back from `end` (the last close; the series' own last day
    when not given). A series that stops more than `FRESH_DAYS` before it has
    no current multiple, so percentile, z-score and premium come back NaN
    rather than reading a months-old value as today's.
    """
    if pe is None or pe.empty:
        return pd.DataFrame()
    last = cast(pd.Timestamp, pe.index.max())
    end = last if end is None else cast(pd.Timestamp, max(pd.Timestamp(end), last))
    if current is None and last >= end - pd.Timedelta(days=FRESH_DAYS):
        current = float(pe.iloc[-1])
    now = float("nan") if current is None else float(current)
    rows = []
    for label, days in windows.items():
        w = pe[pe.index >= end - pd.Timedelta(days=days)]
        if w.empty:
            continue
        mean, std = float(w.mean()), float(w.std())
        rows.append(
            {
                "window": label,
                "n": int(w.size),
                "current": now,
                "mean": mean,
                "median": float(w.median()),
                "min": float(w.min()),
                "max": float(w.max()),
                "percentile": float((w <= now).mean() * 100)
                if current is not None else float("nan"),
                "zscore": (now - mean) / std if std else float("nan"),
                "premium": now / mean - 1 if mean else float("nan"),
            }
        )
    return pd.DataFrame(rows).set_index("window")


def interpret(percentile: float) -> str:
    """One-word read of where the current multiple sits vs its own history."""
    if percentile >= 80:
        return "expensive vs own history"
    if percentile <= 20:
        return "cheap vs own history"
    return "in line with own history"


def _receipt_ratio(trailing_eps, filed_eps: float, rate: float) -> float | None:
    """Yahoo's per-listing EPS over the filed per-share EPS in the quote's
    currency: about 1 when the listing is one share (see `ADR_BAND`)."""
    try:
        quoted = float(trailing_eps)
    except (TypeError, ValueError):
        return None
    base = filed_eps * rate
    if not quoted > 0 or not base > 0:
        return None
    return quoted / base


def pe_vs_history(
    ticker: str,
    close: pd.Series | None = None,
    current_pe: float | None = None,
) -> dict:
    """Orchestrate the full reconstruction. Network-touching.

    Returns {source, basis, pe, stats, current, as_of}. `source` is
    'SEC EDGAR', 'FMP', or None when neither yields a P/E series. A feed that
    answers with facts but no line (no quarters and no usable years) counts as
    not answering: the next feed is tried, and if none draws a line `source`
    is None, so the page says "not enough data" instead of dropping the card.
    `basis` is 'ttm' (four quarters) or 'annual' (a 20-F filer's fiscal year).
    `as_of` is the last close: the series may stop before it, and then
    `current` is None.
    """
    import yfinance as yf

    from stocks.data import edgar, fetch, fmp, fx
    from stocks.data.listing import quote_unit

    empty = {"source": None, "basis": None, "pe": pd.Series(dtype=float),
             "stats": pd.DataFrame(), "current": current_pe, "as_of": None}
    feeds = [("SEC EDGAR", edgar.diluted_eps_facts)]
    if fmp.has_key():
        feeds.append(("FMP", fmp.diluted_eps_facts))

    splits: pd.Series | None = None
    for source, read in feeds:
        facts = read(ticker)
        if facts.empty:
            continue
        if close is None:
            # As far back as the longest range the page offers: a 5y download
            # under a "10y" button draws five years and averages five.
            years = -(-max(DISPLAY_WINDOWS.values()) // 365)
            close = fetch.fetch_history(ticker, period=f"{years}y")["Close"]
        if close is None or close.empty:
            return empty
        if splits is None:
            try:
                splits = yf.Ticker(ticker).splits
            except Exception:
                splits = pd.Series(dtype=float)
        factors = split_factors(splits, list(facts["end"]))
        quarters = discrete_quarters(facts, factors)  # split-adjust, then Q4 = FY − 3Q
        known, basis, max_age = reconstruct_ttm_eps(quarters), "ttm", None
        if known.empty:
            known, basis = annual_eps(facts, factors), "annual"
            max_age = ANNUAL_MAX_AGE_DAYS
        if known.empty:
            continue

        filed_in = None
        if "currency" in facts.columns and not facts["currency"].isna().all():
            filed_in = str(facts["currency"].dropna().iloc[0]).upper()
        price = close.copy()
        price.index = pd.DatetimeIndex(price.index).tz_localize(None)
        if basis == "annual" or filed_in != "USD":
            # A foreign filer, or a feed that does not say its currency: price
            # and EPS are in the same currency only by luck, and per share
            # only when the listing is one share. FMP's Alibaba quarters in
            # CNY under an eight-share dollar ADR read a P/E of 3.2.
            try:
                quote = fetch.info(ticker)
            except Exception:
                quote = {}
            quoted_in, scale = quote_unit(quote.get("currency"))
            if not quoted_in or not filed_in:
                continue
            price = price * scale  # pence to pounds, before any rate
            rate = pd.Series(1.0, index=price.index)
            if quoted_in != filed_in:
                try:
                    first = cast(pd.Timestamp, price.index.min())
                    final = cast(pd.Timestamp, price.index.max())
                    daily = fx.rates_range(
                        str(first.date()), str(final.date()), filed_in, quoted_in,
                    )
                except Exception:
                    daily = {}
                if not daily:
                    continue
                by_day = pd.Series(daily)
                by_day.index = pd.to_datetime(by_day.index)
                rate = by_day.reindex(price.index.union(by_day.index)).ffill()
                rate = rate.reindex(price.index).bfill()
            ratio = _receipt_ratio(
                quote.get("trailingEps"), float(known.iloc[-1]), float(rate.iloc[-1])
            )
            if ratio is None or not ADR_BAND[0] <= ratio <= ADR_BAND[1]:
                continue
            price = price / rate  # into the filing currency, day by day

        pe = pe_series(price, known, max_age_days=max_age)
        if pe.empty:
            continue
        as_of = cast(pd.Timestamp, price.index.max())
        stats = window_stats(pe, current=current_pe, end=as_of)
        current = current_pe
        last = cast(pd.Timestamp, pe.index.max())
        if current is None and last >= as_of - pd.Timedelta(days=FRESH_DAYS):
            current = float(pe.iloc[-1])
        return {"source": source, "basis": basis, "pe": pe, "stats": stats,
                "current": current, "as_of": as_of}

    return empty
