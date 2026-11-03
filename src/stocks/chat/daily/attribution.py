"""What moved the book on the day, in money: by position, by block, and
against the index over the last sessions. No network.

The card's "Today" figure is one number. Under it the reader wants to know
who made it: which names added and which took away, whether it was one
sector or the whole book, and whether the day was the market's or their
picks'. Every figure here is a share of that one number, so the parts add up
to the whole to the cent — a breakdown that does not sum is a breakdown the
reader cannot trust for anything else either.

Positions are `api.home.enriched` rows: `day` is each holding's move in the
book's currency (FX included, re-read from the quote burst for a market that
is shut), `day_pct` its price move. A block is a sector for a single name,
the fund itself for a fund (its look-through split is a weighting, not a
move: an ETF's day is not spread evenly over its sectors) and crypto for a
coin. Each position sits in exactly one block, so blocks sum to positions.

Two checks ride along. A position whose day is exactly 0.00 % on a close
equal to the one before is a bar the feed repeated, not a quiet day — the
breakdown says so instead of crediting the name with holding steady. And a
move past two of its own standard deviations is set against its sector's ETF
the same session: the same move there is the sector's, a different one the
company's.
"""

from __future__ import annotations

import math

import pandas as pd

from stocks.formatting import finite

SHOWN = 3
ALPHA_SESSIONS = 10
# How many daily returns a standard deviation needs before a move is called
# unusual against it: a month of sessions.
SIGMA_MIN_DAYS = 20
SIGMA_MULTIPLE = 2.0
# Under a cent of the book's currency is rounding, not a gap.
GAP_FLOOR = 0.01
FUND = "fund"
SECTOR = "sector"
CRYPTO = "crypto"


def _num(value) -> float | None:
    out = finite(value)
    return None if out is None else float(out)


def _pp(amount: float, start: float) -> float | None:
    """`amount` as percentage points of the book where the day opened."""
    return round(amount / start * 100, 2) if start > 0 else None


def block_of(ticker: str, meta: dict) -> tuple[str, str]:
    """(kind, label) of the block a position is counted in: a fund is its own
    block, a coin goes to crypto, a single name to its sector ("Unknown" when
    the profile has none)."""
    from stocks.data.crypto import is_crypto

    row = meta.get(ticker) or {}
    if row.get("sector_weights"):
        return FUND, ticker
    if is_crypto(ticker):
        return CRYPTO, "Crypto"
    return SECTOR, str(row.get("sector") or "Unknown")


def stale(pct: float | None, closes: list[float] | None) -> bool:
    """Whether a day move is the feed repeating yesterday's bar: exactly zero,
    on a last close equal to the one before (or no closes to tell)."""
    if pct is None or pct != 0.0:
        return False
    return not closes or len(closes) < 2 or closes[-1] == closes[-2]


def sigma(closes: list[float] | None) -> float | None:
    """The standard deviation of the daily returns in `closes`, or None with
    under `SIGMA_MIN_DAYS` of them."""
    if not closes or len(closes) <= SIGMA_MIN_DAYS:
        return None
    series = pd.Series(closes, dtype=float)
    returns = (series / series.shift(1) - 1).dropna()
    returns = returns[returns.map(math.isfinite)]
    if len(returns) < SIGMA_MIN_DAYS:
        return None
    out = float(returns.std())
    return out if out > 0 else None


def session_pct(series: pd.Series | None, on: str | None) -> float | None:
    """`series`' move into the session `on` (its last bar on or before it,
    against the bar before), or None without two bars."""
    if series is None:
        return None
    clean = series.dropna()
    if on:
        from stocks.analysis import naive_dates

        clean = clean.copy()
        clean.index = naive_dates(clean.index)
        clean = clean.loc[: pd.Timestamp(on)]
    if len(clean) < 2 or not clean.iloc[-2]:
        return None
    return float(clean.iloc[-1] / clean.iloc[-2] - 1)


def day(
    tbl,
    meta: dict | None = None,
    *,
    total: float | None = None,
    year: dict[str, list[float]] | None = None,
    sector_day: dict[str, float] | None = None,
    report: bool = False,
) -> dict | None:
    """The day's move split by position and block, or None with nothing moved.

    Args:
        tbl: the positions frame (`api.home.enriched`), `day` / `day_pct` /
            `weight` / `value` per ticker.
        meta: `load_meta` profiles, for the blocks.
        total: the day the card states (`facts["day"]`), when the caller
            resolved it from somewhere else than these rows — the close-to-
            close basket during a session. Its difference from the rows is
            `gap`; None means the rows are the day.
        year: a year of closes per ticker, for the repeated bar and the
            standard deviation a move is measured against.
        sector_day: each sector ETF's move the same session, by sector name
            (`sentiment.SECTOR_ETFS` spelling).
        report: log a gap or a repeated bar to the inconsistency log — set
            when `total` is meant to be these rows' own sum.

    Returns:
        `amount` (the rows' sum), `start` (the book where the day opened),
        `up` / `down` (the largest contributions each way, `ticker`,
        `amount`, `pct`, `pp` of the book, `weight_pct`), `blocks` (`kind`,
        `label`, `amount`, `pp`, `tickers`, largest move first), and when
        they apply `gap`, `stale` (tickers) and `explained` (movers past
        two sigma against their sector's ETF).
    """
    if tbl is None or getattr(tbl, "empty", True) or "day" not in tbl:
        return None
    meta = meta or {}
    year = year or {}
    rows: list[dict] = []
    stale_names: list[str] = []
    for ticker, row in tbl.iterrows():
        name = str(ticker)
        amount = _num(row.get("day"))
        if amount is None:
            continue
        pct = _num(row.get("day_pct"))
        if stale(pct, year.get(name)):
            stale_names.append(name)
        weight = _num(row.get("weight"))
        rows.append({
            "ticker": name,
            "amount": amount,
            "pct": None if pct is None else round(pct * 100, 2),
            "weight_pct": None if weight is None else round(weight * 100, 2),
            "_pct": pct,
        })
    if not rows:
        return None

    moved = sum(r["amount"] for r in rows)
    held = tbl["value"] if "value" in tbl else None
    priced = 0.0 if held is None else sum(_num(held[r["ticker"]]) or 0.0 for r in rows)
    start = priced - moved
    for r in rows:
        r["pp"] = _pp(r["amount"], start)

    blocks: dict[tuple[str, str], dict] = {}
    for r in rows:
        kind, label = block_of(r["ticker"], meta)
        block = blocks.setdefault(
            (kind, label), {"kind": kind, "label": label, "amount": 0.0, "tickers": []}
        )
        block["amount"] += r["amount"]
        block["tickers"].append(r["ticker"])
    ranked = sorted(blocks.values(), key=lambda b: -abs(b["amount"]))
    for block in ranked:
        block["pp"] = _pp(block["amount"], start)
        block["amount"] = round(block["amount"], 2)

    out: dict = {
        "amount": round(moved, 2),
        "start": round(start, 2),
        "up": _side(rows, positive=True),
        "down": _side(rows, positive=False),
        "blocks": ranked,
    }
    if total is not None:
        gap = total - moved
        if abs(gap) >= GAP_FLOOR:
            out["gap"] = round(gap, 2)
            if report:
                _report("attribution_gap", off=_ratio(gap, total))
    if stale_names:
        out["stale"] = stale_names
        if report:
            for name in stale_names:
                _report("stale_bar", ticker=name)
    explained = _explained(rows, meta, year, sector_day or {})
    if explained:
        out["explained"] = explained
    return out


def _side(rows: list[dict], *, positive: bool) -> list[dict]:
    picked = [r for r in rows if (r["amount"] > 0 if positive else r["amount"] < 0)]
    picked.sort(key=lambda r: -abs(r["amount"]))
    return [
        {k: (round(v, 2) if k == "amount" else v) for k, v in r.items() if k != "_pct"}
        for r in picked[:SHOWN]
    ]


def _explained(rows, meta, year, sector_day) -> list[dict]:
    """Each position that moved past `SIGMA_MULTIPLE` of its own deviation,
    against its sector ETF's move the same session: `sector` when the ETF
    made at least half of it in the same direction, else `company`."""
    from stocks.analysis.sentiment import SECTOR_ETFS

    out: list[dict] = []
    for r in sorted(rows, key=lambda r: -abs(r["_pct"] or 0.0)):
        pct = r["_pct"]
        sd = sigma(year.get(r["ticker"]))
        if pct is None or sd is None or abs(pct) < SIGMA_MULTIPLE * sd:
            continue
        kind, sector = block_of(r["ticker"], meta)
        etf = SECTOR_ETFS.get(sector) if kind == SECTOR else None
        etf_pct = sector_day.get(sector) if etf else None
        if etf is None or etf_pct is None:
            continue
        same = etf_pct * pct > 0 and abs(etf_pct) >= abs(pct) / 2
        out.append({
            "ticker": r["ticker"],
            "pct": r["pct"],
            "sigmas": round(abs(pct) / sd, 1),
            "etf": etf,
            "etf_pct": round(etf_pct * 100, 2),
            "verdict": SECTOR if same else "company",
        })
        if len(out) >= SHOWN:
            break
    return out


def alpha(hist: pd.DataFrame | None, index: pd.Series | None,
          sessions: int = ALPHA_SESSIONS) -> dict | None:
    """The book's last `sessions` days against the index, day by day.

    The book is the fixed basket (`basket_values` summed): what the names
    held did, flows aside. Each day the index is read over the same stretch,
    its last close on or before each of the book's two dates — a book day the
    index did not trade is the index standing still, not a missing row.

    Returns `sessions` (`date`, `book`, `index`, each %), `ahead` (how many
    the book beat) and `excess_pp` (their summed difference), or None
    without two sessions on both sides.
    """
    if hist is None or hist.empty or index is None:
        return None
    from stocks.analysis import naive_dates

    book = hist.sum(axis=1, min_count=1).dropna()
    book.index = naive_dates(book.index)
    book = book[~book.index.duplicated(keep="last")].sort_index()
    ix = index.dropna().copy()
    ix.index = naive_dates(ix.index)
    ix = ix[~ix.index.duplicated(keep="last")].sort_index()
    if len(book) < 2 or len(ix) < 2:
        return None
    on = ix.reindex(book.index, method="ffill")
    rows: list[dict] = []
    for prev, cur in zip(book.index[:-1], book.index[1:], strict=True):
        a, b, i0, i1 = book[prev], book[cur], on[prev], on[cur]
        if not a or pd.isna(i0) or pd.isna(i1) or not i0:
            continue
        rows.append({
            "date": str(cur.date()),
            "book": round((b / a - 1) * 100, 2),
            "index": round((i1 / i0 - 1) * 100, 2),
        })
    rows = rows[-sessions:]
    if len(rows) < 2:
        return None
    return {
        "sessions": rows,
        "ahead": sum(1 for r in rows if r["book"] > r["index"]),
        "excess_pp": round(sum(r["book"] - r["index"] for r in rows), 2),
    }


def _ratio(part: float, whole: float | None):
    from stocks.portfolio.consistency import ratio

    return ratio(part, whole or 0.0)


def _report(kind, **evidence) -> None:
    from stocks.portfolio import consistency

    consistency.report(kind, source="card", **evidence)
