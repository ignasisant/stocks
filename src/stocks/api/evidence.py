"""What one line of the daily card is analysed against, fetched on the click.

The card's own facts can only restate the line: "DSGX is 31% under cost" says
what happened and nothing about why. The analysis behind it is a comparison,
and a comparison needs the other side: the company's peers, its sector's ETF,
the index, the business figures and the analysts' consensus behind each, the
tax arithmetic of a sale, which holdings explain a month behind the index.
This module fetches that side for one line, when the reader opens it, and
hands `chat.daily_analysis` a dict it can both quote and audit.

Two rules shape the dict:

* Every difference the analysis could want is computed here (`compare`), so
  the model quotes a figure rather than working one out — the audit accepts
  only figures that are in the evidence, and a subtraction done in prose is a
  number it would rightly reject.
* A company's figures sit under a dict carrying its `ticker`, and nothing else
  does: the audit reads that key as ownership (`daily._numbers`), which is what
  stops a peer's return being printed under the subject's name. Sector and
  index blocks name their fund under `etf`, so their figures stay quotable in a
  line about any holding.

Every fetch is best-effort and bounded by `WAIT_S`: a throttled peer is a
table with one row fewer, and nothing here raises into the route.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date
from typing import Any

import pandas as pd

from stocks import obs
from stocks.api import briefing, home, loaders
from stocks.api.cache import ttl_cache
from stocks.api.deps import reporting_currency
from stocks.chat import daily, signals
from stocks.data.crypto import is_crypto
from stocks.formatting import finite

# The whole fetch, every stage included. The reader clicked and is watching a
# wait line; past this the analysis is written from whatever arrived.
WAIT_S = 20.0
PEERS = 3
# Related symbols looked at to find PEERS that are companies in the same line
# of business — Yahoo's list mixes in funds and names from other sectors.
PEER_CANDIDATES = 6
# Rows a holdings / attribution / open-positions table carries.
HOLDINGS_SHOWN = 8
OPEN_SHOWN = 4
HISTORY_SHOWN = 4
_WORKERS = 8
INDEX_ETF = "SPY"

# The kinds that are about one company, and so get the company comparison.
TICKER_KINDS = frozenset(
    {
        signals.DRAWDOWN,
        signals.HARVEST,
        signals.CONCENTRATION,
        signals.ALERT_HIT,
        signals.ALERT_NEAR,
        signals.LOW_52W,
        signals.EARNINGS,
        signals.EARNINGS_RESULT,
        signals.REPURCHASE_CLEAR,
    }
)


# ------------------------------------------------------------------ figures


def _r(value, digits: int = 1) -> float | None:
    out = finite(value)
    return None if out is None else round(out, digits)


def _pct(value, digits: int = 1) -> float | None:
    """A fraction as a percentage, rounded to what the analysis prints."""
    out = finite(value)
    return None if out is None else round(out * 100, digits)


def _back(series: pd.Series, days: int) -> float | None:
    """The return over the last `days` calendar days, in percent."""
    if series.empty:
        return None
    end = series.index[-1]
    anchor = series[series.index <= end - pd.Timedelta(days=days)]
    if anchor.empty:
        return None
    start = float(anchor.iloc[-1])
    return _pct(float(series.iloc[-1]) / start - 1) if start else None


def perf(series: pd.Series | None) -> dict:
    """Price performance of one close series: 1/3/12 months, distance from
    the 12-month high, annualised volatility and worst drawdown over the year.
    Empty for a series too short to say anything."""
    from stocks.analysis.portfolio import annualized_volatility, max_drawdown

    if series is None:
        return {}
    s = series.dropna()
    if len(s) < 20:
        return {}
    year = s[s.index > s.index[-1] - pd.Timedelta(days=365)]
    returns = year.pct_change().dropna()
    return {
        "m1_pct": _back(s, 30),
        "m3_pct": _back(s, 91),
        "y1_pct": _back(s, 365),
        "from_high_pct": _pct(float(year.iloc[-1]) / float(year.max()) - 1),
        "vol_1y_pct": _pct(annualized_volatility(returns)) if len(returns) > 20 else None,
        "max_dd_1y_pct": _pct(max_drawdown(year)),
    }


def business(raw) -> dict:
    """The business figures a comparison reads, off one fundamentals pull."""
    from stocks.analysis.fundamentals import compute_metrics

    try:
        m = compute_metrics(raw)
    except Exception:  # noqa: BLE001 — a malformed statement is no figures
        return {}
    return {
        "pe_fwd": _r(m.get("pe_fwd")),
        "pe_ttm": _r(m.get("pe_ttm")),
        "ev_sales": _r(m.get("ev_sales")),
        "op_margin_pct": _pct(m.get("op_margin")),
        "net_margin_pct": _pct(m.get("net_margin")),
        "revenue_cagr_pct": _pct(m.get("revenue_cagr")),
        "fcf_yield_pct": _pct(m.get("fcf_yield")),
        "net_debt_ebitda": _r(m.get("net_debt_ebitda")),
    }


def consensus(raw) -> dict:
    """Analysts' view, labelled as such by the prompt: target and growth."""
    from stocks.data.estimates import consensus as fold

    try:
        c = fold(raw)
    except Exception:  # noqa: BLE001
        return {}
    return {
        "target_upside_pct": _pct(c.target_upside),
        "rating": c.rating,
        "rev_growth_next_fy_pct": _pct(c.rev_growth_next_fy),
        "eps_growth_next_fy_pct": _pct(c.eps_growth_next_fy),
    }


def _profile(raw) -> dict:
    info = getattr(raw, "info", None) or {}
    return {
        "name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "quote_type": info.get("quoteType"),
    }


def _median(values) -> float | None:
    got = [v for v in values if v is not None]
    return round(statistics.median(got), 1) if got else None


def _gap(a, b) -> float | None:
    return None if a is None or b is None else round(a - b, 1)


_MEDIAN_FIELDS = (
    ("perf", "m1_pct"),
    ("perf", "m3_pct"),
    ("perf", "y1_pct"),
    ("perf", "vol_1y_pct"),
    ("business", "pe_fwd"),
    ("business", "ev_sales"),
    ("business", "op_margin_pct"),
    ("business", "fcf_yield_pct"),
    ("consensus", "rev_growth_next_fy_pct"),
    ("consensus", "target_upside_pct"),
)


def compare(subject: dict, peers: list[dict], sector: dict, index: dict) -> dict:
    """The differences, already taken. `…_pp` are percentage points."""
    median = (
        {
            field: _median((p.get(group) or {}).get(field) for p in peers)
            for group, field in _MEDIAN_FIELDS
        }
        if peers
        else {}
    )
    own = subject.get("perf") or {}
    sec, idx = sector.get("perf") or {}, index.get("perf") or {}
    out: dict[str, Any] = {
        "vs_sector_m3_pp": _gap(own.get("m3_pct"), sec.get("m3_pct")),
        "vs_sector_y1_pp": _gap(own.get("y1_pct"), sec.get("y1_pct")),
        "vs_index_m3_pp": _gap(own.get("m3_pct"), idx.get("m3_pct")),
        "vs_index_y1_pp": _gap(own.get("y1_pct"), idx.get("y1_pct")),
        "vol_vs_index_pp": _gap(own.get("vol_1y_pct"), idx.get("vol_1y_pct")),
    }
    if median:
        out |= {
            "peers_median": median,
            "vs_peers_m3_pp": _gap(own.get("m3_pct"), median.get("m3_pct")),
            "vs_peers_y1_pp": _gap(own.get("y1_pct"), median.get("y1_pct")),
            "vol_vs_peers_pp": _gap(own.get("vol_1y_pct"), median.get("vol_1y_pct")),
        }
    return {k: v for k, v in out.items() if v is not None}


def rank_peers(ticker: str, profile: dict, candidates: dict[str, dict]) -> list[str]:
    """Up to PEERS companies from `candidates` ({ticker: profile}): same
    industry first, then same sector, Yahoo's order within each. Funds and
    anything that is not a company are left out — a sector ETF is already its
    own row."""

    def tier(p: dict) -> int:
        if profile.get("industry") and p.get("industry") == profile.get("industry"):
            return 0
        if profile.get("sector") and p.get("sector") == profile.get("sector"):
            return 1
        return 2

    usable = [
        t
        for t, p in candidates.items()
        if t != ticker and p.get("quote_type") == "EQUITY"
    ]
    if profile.get("sector"):
        # A company from another sector is not a comparable, whatever Yahoo
        # suggests; with no sector to go on, its order is all there is.
        usable = [t for t in usable if tier(candidates[t]) < 2]
    return sorted(usable, key=lambda t: tier(candidates[t]))[:PEERS]


def tax(action: dict, today: date) -> dict:
    """What selling a harvest line's position today would do to the bill.

    The saving is the progressive scale run twice — on the gain realised so
    far, and on it minus the offset — so it is right across a bracket edge,
    which a single marginal rate is not. Spain's savings scale only
    (`signals._brackets`); elsewhere the offset stands without a rate.
    """
    from stocks.portfolio.tax.base import progressive_tax

    loss, gain, offset = (finite(action.get(k)) for k in ("loss", "gain_ytd", "offset"))
    named = (("loss", loss), ("gain_ytd", gain), ("offset", offset))
    out: dict[str, Any] = {k: v for k, v in named if v is not None}
    brackets = signals._brackets(action.get("jurisdiction"))
    if brackets and gain is not None and offset:
        before = progressive_tax(gain, brackets)
        saving = before - progressive_tax(gain - offset, brackets)
        out["saving"] = round(saving, 2)
        out["saving_pct_of_offset"] = _pct(saving / offset)
        out["marginal_rate_pct"] = next(
            (round(rate * 100) for upper, rate in brackets if gain <= upper),
            round(brackets[-1][1] * 100),
        )
    window = str(action.get("repurchase_window") or "")
    end = signals._window_end(today, window) if window else None
    if end is not None:
        out["repurchase_window"] = window
        out["clear_if_sold_today"] = end.isoformat()
    return out


def history(results, closes: pd.Series | None) -> dict:
    """The last prints: EPS against its estimate and how the stock moved
    from the close before the report to the close after it."""
    rows = []
    s = closes.dropna() if closes is not None else pd.Series(dtype=float)
    for r in sorted(
        (r for r in results or () if getattr(r, "reported_eps", None) is not None),
        key=lambda r: r.date,
        reverse=True,
    )[:HISTORY_SHOWN]:
        move = None
        if not s.empty:
            day = pd.Timestamp(r.date)
            tz = getattr(s.index, "tz", None)
            if tz is not None:
                day = day.tz_localize(tz)
            before, after = s[s.index < day], s[s.index > day]
            if not before.empty and not after.empty and float(before.iloc[-1]):
                move = _pct(float(after.iloc[0]) / float(before.iloc[-1]) - 1)
        rows.append(
            {
                "date": r.date.isoformat(),
                "eps_estimate": _r(r.eps_estimate, 2),
                "reported_eps": _r(r.reported_eps, 2),
                "surprise_pct": _r(r.surprise_pct),
                "move_pct": move,
            }
        )
    if not rows:
        return {}
    surprises = [row["surprise_pct"] for row in rows if row["surprise_pct"] is not None]
    moves = [abs(row["move_pct"]) for row in rows if row["move_pct"] is not None]
    return {
        "prints": rows,
        "beats": sum(1 for v in surprises if v >= 0),
        "counted": len(surprises),
        "avg_surprise_pct": round(statistics.mean(surprises), 1) if surprises else None,
        "avg_abs_move_pct": round(statistics.mean(moves), 1) if moves else None,
    }


def outlook(raw) -> dict:
    """Consensus for the quarter about to be reported — never guidance."""
    from stocks.data.estimates import CURRENT_Q, quarter_outlook

    try:
        q = quarter_outlook(raw, CURRENT_Q)
    except Exception:  # noqa: BLE001
        return {}
    if q.empty:
        return {}
    return {
        k: v
        for k, v in {
            "eps_avg": _r(q.eps_avg, 2),
            "eps_growth_pct": _pct(q.eps_growth),
            "revenue_avg_bn": _r((q.rev_avg or 0) / 1e9, 2) if q.rev_avg else None,
            "revenue_growth_pct": _pct(q.rev_growth),
            "currency": q.currency,
            "analysts": q.eps_analysts,
        }.items()
        if v is not None
    }


def sectors(closes: dict[str, pd.Series], against: str | None = None) -> list[dict]:
    """Every sector ETF's performance and, with `against`, its one-year
    correlation of daily returns to that sector's ETF — which of the others
    would actually move differently."""
    from stocks.analysis.sentiment import SECTOR_ETFS

    base = closes.get(against) if against else None
    base_returns = base.dropna().pct_change().tail(252) if base is not None else None
    out = []
    for name, etf in SECTOR_ETFS.items():
        series = closes.get(etf)
        row = {"etf": etf, "sector": name, **perf(series)}
        if base_returns is not None and series is not None and etf != against:
            joined = pd.concat(
                [base_returns, series.dropna().pct_change().tail(252)], axis=1
            ).dropna()
            if len(joined) > 60:
                row["corr_1y"] = _r(joined.iloc[:, 0].corr(joined.iloc[:, 1]), 2)
        if len(row) > 2:
            out.append(row)
    return out


def holdings(tbl, closes: dict[str, pd.Series], names) -> list[dict]:
    """The book's positions among `names`, largest first, each with its own
    weight, P/L and price performance."""
    if tbl is None or tbl.empty:
        return []
    rows: list[dict[str, Any]] = []
    for ticker in names:
        if ticker not in tbl.index:
            continue
        row = tbl.loc[ticker]
        p = perf(closes.get(ticker))
        rows.append(
            {
                "ticker": str(ticker),
                "weight_pct": _pct(row.get("weight")),
                "pnl_pct": _pct(row.get("pnl_pct")),
                "m1_pct": p.get("m1_pct"),
                "y1_pct": p.get("y1_pct"),
            }
        )
    rows.sort(key=lambda r: -(r["weight_pct"] or 0))
    return rows[:HOLDINGS_SHOWN]


def attribution(tbl, closes: dict[str, pd.Series]) -> list[dict]:
    """Each position's share of the month: today's weight × its month move.

    In each listing's own currency and at today's weights, so the column is
    an attribution, not a reconciliation — the prompt says so."""
    if tbl is None or tbl.empty or "weight" not in tbl:
        return []
    rows: list[dict[str, Any]] = []
    for ticker, weight in tbl["weight"].dropna().items():
        month = perf(closes.get(ticker)).get("m1_pct")
        if month is None:
            continue
        rows.append(
            {
                "ticker": str(ticker),
                "weight_pct": _pct(weight),
                "m1_pct": month,
                "contribution_pp": round(float(weight) * month, 2),
            }
        )
    rows.sort(key=lambda r: r["contribution_pp"])
    if len(rows) <= HOLDINGS_SHOWN:
        return rows
    half = HOLDINGS_SHOWN // 2
    return rows[:half] + rows[-half:]


def open_positions(tbl) -> dict:
    """The largest open losses and gains — what a tax-year plan picks from."""
    if tbl is None or tbl.empty or "pnl" not in tbl:
        return {}
    pnl = tbl["pnl"].dropna().sort_values()

    def row(ticker) -> dict:
        return {
            "ticker": str(ticker),
            "pnl": _r(tbl.at[ticker, "pnl"], 2),
            "pnl_pct": _pct(tbl.at[ticker, "pnl_pct"]) if "pnl_pct" in tbl else None,
        }

    return {
        "losses": [row(t) for t, v in pnl.head(OPEN_SHOWN).items() if v < 0],
        "gains": [row(t) for t, v in pnl.iloc[::-1].head(OPEN_SHOWN).items() if v > 0],
    }


# ------------------------------------------------------------------ fetches


@ttl_cache(900.0, max_entries=32)
def _closes(tickers: tuple[str, ...]) -> dict[str, pd.Series]:
    """A subject and its peers in one bulk download, two years deep so the
    12-month return has its anchor."""
    from stocks.analysis.portfolio import load_closes

    return load_closes(list(tickers), period="2y")


def _run(pool, calls: dict[str, Callable], deadline: float) -> dict:
    """Run `calls` in parallel until `deadline`; what finished, by name."""
    futures = {pool.submit(fn): name for name, fn in calls.items()}
    done, _ = wait(futures, timeout=max(0.0, deadline - time.monotonic()))
    out = {}
    for future in done:
        try:
            out[futures[future]] = future.result()
        except Exception as exc:  # noqa: BLE001 — one missing row, not an error
            obs.warn(
                "daily_analysis.fetch_failed",
                what=futures[future].split(":")[0],
                error_type=type(exc).__name__,
            )
    return out


def _book(paths):
    """The live positions frame, or None — the same one the card was built on."""
    db = str(paths.db)
    try:
        tbl = home.enriched(db, loaders.db_mtime(db), reporting_currency(paths))
    except Exception:  # noqa: BLE001
        return None
    return None if tbl is None or tbl.empty else tbl


def _held(paths) -> dict[str, pd.Series]:
    db = str(paths.db)
    try:
        return loaders.held_closes(db, loaders.db_mtime(db))
    except Exception:  # noqa: BLE001
        return {}


def _market() -> dict[str, pd.Series]:
    try:
        return briefing._card_closes()
    except Exception:  # noqa: BLE001
        return {}


def _index(market: dict) -> dict:
    return {"etf": INDEX_ETF, "name": "S&P 500", "perf": perf(market.get(INDEX_ETF))}


def _company(pool, action: dict, tbl, market: dict, deadline: float) -> dict:
    """Subject, peers, sector, index and the differences between them."""
    from stocks.analysis.sentiment import SECTOR_ETFS

    ticker = str(action.get("ticker") or "")
    kind = str(action.get("kind") or "")
    crypto = is_crypto(ticker)
    first = (
        {}
        if crypto
        else _run(
            pool,
            {
                "fund": lambda: loaders.fundamentals(ticker),
                "est": lambda: loaders.estimates(ticker),
                "related": lambda: loaders.related(ticker),
                **(
                    {"earnings": lambda: loaders.earnings(ticker)}
                    if kind in (signals.EARNINGS, signals.EARNINGS_RESULT)
                    else {}
                ),
            },
            deadline,
        )
    )
    profile = _profile(first.get("fund"))
    subject: dict = {"ticker": ticker, **{k: v for k, v in profile.items() if v}}

    candidates = [
        t for t in first.get("related") or () if t != ticker and not is_crypto(t)
    ][:PEER_CANDIDATES]
    pulled = _run(
        pool,
        {f"peer:{t}": (lambda t=t: loaders.fundamentals(t)) for t in candidates},
        deadline,
    )
    profiles = {t: _profile(pulled.get(f"peer:{t}")) for t in candidates}
    chosen = rank_peers(ticker, profile, profiles)

    third = _run(
        pool,
        {
            "closes": lambda: _closes(tuple(sorted({ticker, *chosen}))),
            **{f"est:{t}": (lambda t=t: loaders.estimates(t)) for t in chosen},
        },
        deadline,
    )
    closes = third.get("closes") or {}

    subject["perf"] = perf(closes.get(ticker))
    if first.get("fund") is not None:
        subject["business"] = business(first["fund"])
    if first.get("est") is not None:
        subject["consensus"] = consensus(first["est"])
    if tbl is not None and ticker in tbl.index:
        row = tbl.loc[ticker]
        subject["position"] = {
            "weight_pct": _pct(row.get("weight")),
            "value": _r(row.get("value"), 2),
            "pnl": _r(row.get("pnl"), 2),
            "pnl_pct": _pct(row.get("pnl_pct")),
        }

    peers = []
    for t in chosen:
        raw = pulled.get(f"peer:{t}")
        peer = {"ticker": t, "name": profiles[t].get("name"), "perf": perf(closes.get(t))}
        peer["business"] = business(raw)
        if third.get(f"est:{t}") is not None:
            peer["consensus"] = consensus(third[f"est:{t}"])
        peers.append(peer)

    etf = SECTOR_ETFS.get(str(profile.get("sector") or ""))
    sector = (
        {"etf": etf, "sector": profile.get("sector"), "perf": perf(market.get(etf))}
        if etf
        else {}
    )
    index = _index(market)
    out = {"subject": subject, "index": index}
    if peers:
        out["peers"] = peers
    if sector:
        out["sector"] = sector
    out["compare"] = compare(subject, peers, sector, index)

    if kind in (signals.EARNINGS, signals.EARNINGS_RESULT):
        _, results = first.get("earnings") or ((), ())
        past = history(results, closes.get(ticker))
        if past:
            out["history"] = past
        if kind == signals.EARNINGS and first.get("est") is not None:
            ahead = outlook(first["est"])
            if ahead:
                out["outlook"] = ahead
    return out


def gather(paths, card, key: str, *, today: date | None = None) -> dict:
    """The evidence for the line `key` of `card`. Empty when the line has no
    trigger behind it; partial when a fetch failed or ran out of time."""
    from stocks.analysis.sentiment import SECTOR_ETFS

    action = daily.keyed_actions(card.facts).get(key)
    if action is None:
        return {}
    kind = str(action.get("kind") or "")
    deadline = time.monotonic() + WAIT_S
    today = today or date.today()
    pool = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="daily-evidence")
    out: dict = {}
    try:
        base = _run(pool, {"book": lambda: _book(paths), "market": _market}, deadline)
        tbl, market = base.get("book"), base.get("market") or {}
        if kind in TICKER_KINDS and action.get("ticker"):
            out |= _company(pool, action, tbl, market, deadline)
        if kind == signals.HARVEST:
            out["tax"] = tax(action, today)
        elif kind == signals.EARNINGS_RESULT:
            out["print"] = briefing._print_source(action)
        elif kind in (signals.MACRO_EVENT, signals.MACRO_RESULT):
            rates = briefing._rate_source(action)
            if rates:
                out["rates"] = rates
        elif kind == signals.SECTOR_TILT:
            name = str(action.get("sector") or "")
            etf = SECTOR_ETFS.get(name)
            names = tuple(sorted(str(t) for t in tbl.index)) if tbl is not None else ()
            meta = briefing._meta(names) if names else {}
            inside = [t for t, m in meta.items() if (m or {}).get("sector") == name]
            out["holdings"] = holdings(tbl, _held(paths), inside)
            out["sectors"] = sectors(market, etf)
            out["index"] = _index(market)
            own = next((r for r in out["sectors"] if r["etf"] == etf), {})
            idx = out["index"]["perf"]
            gaps = {
                "sector_vs_index_m3_pp": _gap(own.get("m3_pct"), idx.get("m3_pct")),
                "sector_vs_index_y1_pp": _gap(own.get("y1_pct"), idx.get("y1_pct")),
            }
            out["compare"] = {k: v for k, v in gaps.items() if v is not None}
        elif kind == signals.VS_BENCH:
            out["attribution"] = attribution(tbl, _held(paths))
            out["index"] = _index(market)
            out["fx"] = {"pair": "EURUSD", **perf(market.get("EURUSD=X"))}
        elif kind == signals.MARKET:
            out["sectors"] = sectors(market)
            out["index"] = _index(market)
        elif kind == signals.FX:
            currency = str(action.get("currency") or "")
            names = (
                [t for t in tbl.index if str(tbl.at[t, "ccy"]) == currency]
                if tbl is not None and "ccy" in tbl
                else []
            )
            out["holdings"] = holdings(tbl, _held(paths), names)
            if {currency, str(action.get("base") or "")} == {"USD", "EUR"}:
                out["fx"] = {"pair": "EURUSD", **perf(market.get("EURUSD=X"))}
        elif kind in (signals.TAX_YEAR_END, signals.TAX_BRACKET):
            out["open"] = open_positions(tbl)
    except Exception as exc:  # noqa: BLE001 — the analysis is written from what arrived
        obs.warn(
            "daily_analysis.evidence_failed",
            kind=kind,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out
