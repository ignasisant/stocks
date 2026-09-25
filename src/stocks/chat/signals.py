"""Candidate actions for the dashboard's daily card — computed, not written.

The daily card is meant to answer "what should I DO today", and an action is a
decision with a trigger behind it: *sell X, your own exit alert just fired*,
*X is 2% from the level you set*, *realising the loss on X offsets the gain you
already booked this year*. A model asked for that from raw portfolio numbers
invents triggers — it has no way to know the user's exit rule, and every
sentence it produces reads equally confident.

So the triggers are computed here, in plain Python, from things the user
actually declared or the ledger actually holds:

  - **their own alerts** — a `below`/`above` price rule on a watchlist entry is
    the user's own exit or entry level, the closest thing to a stated kill
    criterion this app has. Fired, or within `NEAR_PCT` of firing.
  - **the ledger** — a position deep under its cost, a weight that has drifted
    past `CONCENTRATION_PCT`, and the loss-harvesting arithmetic: an open loss
    is only worth surfacing when there is a realised gain this tax year for it
    to offset, and the jurisdiction's repurchase window is the trap that goes
    with it.
  - **the calendar** — a print inside a few days is a decision date, not news.
  - **the price** — a watchlist name at its 52-week low is the "getting close
    to interesting" case, which is about candidates, not holdings.
  - **the market, against this book** — the index's own trend and how much of
    it is still in one, the sector bet the book is running against the index,
    how the book did beside that index, and what the currency did to it.
    `market_candidates()` owns those, and they are the only ones here that are
    not about a single ticker.

Each candidate carries its numbers and an urgency; stocks/chat/daily.py hands
the top few to the model, which picks and phrases — it never gets to invent one
— and renders them directly when no model is available. Nothing here fetches:
every input is a frame or list the dashboard already loaded.

**A card that repeats itself is a card nobody reads.** Most of these triggers
are standing conditions, not events: an open loss with a gain behind it is
just as true tomorrow, and the card used to spend all four of its lines on the
same family of them. Two rules fix that, both in `candidates()`: `_CAP` limits
how many of one kind can reach the model at once, and `decay()` sinks a
standing trigger a little further each consecutive day it has already been
offered, so today's card leads with something yesterday's did not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from stocks.formatting import finite

# An alert this close to its level is "about to fire" — near enough to plan
# around today, far enough that it does not just repeat the fired ones.
NEAR_PCT = 3.0
# A position this far under its own cost is where a thesis gets re-read. Not a
# rule the app invents on the user's behalf: the card asks them to review it,
# never to sell.
DRAWDOWN_PCT = 25.0
# Below this the tax tail wags the dog — harvesting a €40 loss costs more in
# spread and attention than it saves.
HARVEST_MIN = 150.0
CONCENTRATION_PCT = 30.0
EARNINGS_DAYS = 5
# Within this of the 52-week low, a watchlist name is worth a look.
LOW_52W_PCT = 3.0

# --- the market block's own thresholds ---------------------------------------
# Sessions in a month and in a trading year, and the average trend breadth is
# read against. Same constants sentiment.py uses; named here so this module
# stays readable on its own.
MONTH_SESSIONS = 21
TREND_MA = 200
# An index this far below its own 52-week high is a drawdown the reader is
# living through, not noise.
INDEX_DIP_PCT = 5.0
# Breadth under this is the reading worth a line: the market is narrowing and
# the index is being carried by a few sectors. There is no matching high
# threshold — broad participation is the healthy case, and a card that
# announces it is a market summary, which this card refuses to be.
BREADTH_LOW_PCT = 50.0
# An active sector weight this far from the index is a bet, not a rounding
# difference — at 8 points the sector has to move for the book to notice.
TILT_PP = 8.0
# A sector bet is only measurable when most of the book sits in sectors that
# can be compared to the index at all. Under this, too much of it is crypto, a
# bond sleeve or a failed metadata lookup for the difference to mean anything.
TILT_COVERAGE = 0.75
# The book beating or trailing the index by this much over a month is the gap
# worth explaining.
VS_BENCH_PP = 3.0
# Currency counts when it moved this much and the book is this exposed to it.
FX_MOVE_PCT = 2.0
FX_SHARE_PCT = 25.0

# Kinds, and the base urgency each starts from (higher sorts first). A fired
# alert is the user's own trigger going off today; a concentration drift has
# been true for weeks and will still be true tomorrow.
ALERT_HIT = "alert_hit"
HARVEST = "harvest"
EARNINGS = "earnings"
ALERT_NEAR = "alert_near"
MARKET = "market"
DRAWDOWN = "drawdown"
SECTOR_TILT = "sector_tilt"
LOW_52W = "low_52w"
VS_BENCH = "vs_benchmark"
FX = "fx"
CONCENTRATION = "concentration"

_URGENCY = {
    ALERT_HIT: 90,
    HARVEST: 75,
    EARNINGS: 70,
    ALERT_NEAR: 60,
    MARKET: 58,
    DRAWDOWN: 55,
    SECTOR_TILT: 52,
    LOW_52W: 45,
    VS_BENCH: 44,
    FX: 40,
    CONCENTRATION: 35,
}

# How many of one kind may reach the model in a single card. Events are allowed
# to crowd it — three alerts firing on one morning IS the morning — but a
# standing condition gets one line and no more. Before this cap a book with
# five losing positions and a booked gain produced five harvest candidates,
# which outranked everything else and made every card the same card.
_CAP = {
    ALERT_HIT: 3,
    ALERT_NEAR: 2,
    EARNINGS: 2,
    LOW_52W: 2,
    HARVEST: 1,
    DRAWDOWN: 1,
    CONCENTRATION: 1,
    MARKET: 1,
    SECTOR_TILT: 1,
    VS_BENCH: 1,
    FX: 1,
}
_CAP_DEFAULT = 1

# The kinds a reader would see word for word again tomorrow, and so the ones
# `decay()` sinks. Left out on purpose: alert_hit and earnings are events (one
# fires once, the other gets more urgent as the date approaches), and `market`
# and `vs_benchmark` are re-read from the tape every day — their numbers are
# different on Tuesday even when their key is not.
_STANDING = frozenset(
    {HARVEST, DRAWDOWN, CONCENTRATION, LOW_52W, SECTOR_TILT, FX, ALERT_NEAR}
)
# Urgency lost per consecutive day already offered, and the floor it stops at.
# Three days takes harvest from 75 to 39 — under a fresh drawdown, over a fresh
# 52-week low — which is the point: it drops down the card rather than off it.
DECAY_PER_DAY = 12
DECAY_MAX = 36
# A key not offered for this many days has stopped being repetitive; its streak
# is forgotten rather than carried forever.
DECAY_FORGET_DAYS = 7


@dataclass(frozen=True)
class Signal:
    """One candidate action. `data` holds the numbers its phrasing needs."""

    kind: str
    ticker: str
    urgency: int
    data: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """What "the same trigger as yesterday" means, for `decay()`.

        Kind plus subject: a market-wide signal carries no ticker and is keyed
        on its kind alone, and a sector bet is keyed on the sector rather than
        on a holding, because that is the thing that would read as a repeat.
        """
        subject = self.ticker or str(self.data.get("sector") or "")
        return f"{self.kind}:{subject}"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ticker": self.ticker, **self.data}


def _round(value, digits: int = 2) -> float | None:
    out = finite(value)
    return None if out is None else round(out, digits)


# ------------------------------------------------------------ the user's own


def _alert_signals(holdings, closes: dict, held: set[str]) -> list[Signal]:
    """Price-threshold alerts against the last close, fired and nearly fired.

    Only `above`/`below` rules: they carry an explicit price, which is what
    makes them readable as the user's own level ("your exit at 150"). The
    history-based rules (drawdown, RSI, SMA cross) are evaluated by
    notify/alerts.py against a full price history — a fetch this card has no
    business making, and the notification path already covers them.

    Comparison is in the ticker's own quote currency, because that is the
    currency the user typed the level in.
    """
    out: list[Signal] = []
    for h in holdings:
        prices = closes.get(h.ticker) or []
        price = finite(prices[-1]) if prices else None
        if price is None:
            continue
        for alert in h.alerts:
            if alert.type not in ("above", "below") or alert.price is None:
                continue
            level = float(alert.price)
            if not level:
                continue
            gap_pct = (price / level - 1) * 100
            data = {
                "rule": alert.type,
                "level": _round(level),
                "price": _round(price),
                "held": h.ticker in held,
                "gap_pct": _round(abs(gap_pct)),
            }
            if alert.triggered(price):
                out.append(Signal(ALERT_HIT, h.ticker, _URGENCY[ALERT_HIT], data))
            elif abs(gap_pct) <= NEAR_PCT:
                out.append(Signal(ALERT_NEAR, h.ticker, _URGENCY[ALERT_NEAR], data))
    return out


# ------------------------------------------------------------- the ledger


def _position_signals(tbl, currency: str) -> list[Signal]:
    """Drawdown against cost and weight drift, straight off the positions frame."""
    out: list[Signal] = []
    if tbl is None or tbl.empty:
        return out
    for ticker, row in tbl.iterrows():
        pnl_pct = finite(row.get("pnl_pct"))
        if pnl_pct is not None and pnl_pct * 100 <= -DRAWDOWN_PCT:
            out.append(Signal(
                DRAWDOWN, str(ticker), _URGENCY[DRAWDOWN],
                {
                    "pnl_pct": _round(pnl_pct * 100),
                    "pnl": _round(row.get("pnl")),
                    "currency": currency,
                },
            ))
        weight = finite(row.get("weight"))
        if weight is not None and weight * 100 >= CONCENTRATION_PCT:
            out.append(Signal(
                CONCENTRATION, str(ticker), _URGENCY[CONCENTRATION],
                {"weight_pct": _round(weight * 100), "currency": currency},
            ))
    return out


def realized_this_year(realized, jurisdiction=None, today: date | None = None) -> float:
    """Net realised result booked in the tax year `today` falls in.

    The jurisdiction decides where the year starts (6 April in the UK, 1 July
    in Australia) — the same boundary the tax tab reports on, so the figure the
    card quotes is the one the user can go and check.
    """
    day = today or date.today()
    if jurisdiction is not None:
        year = jurisdiction.tax_year_of(day.isoformat())
        in_year = [s for s in realized if jurisdiction.tax_year_of(s.sell_date) == year]
    else:
        in_year = [s for s in realized if s.sell_date[:4] == f"{day.year:04d}"]
    return sum(s.gain for s in in_year)


def _harvest_signals(
    tbl, realized, jurisdiction, currency: str, today: date | None
) -> list[Signal]:
    """Open losses worth realising *because* there is a booked gain to offset.

    Deliberately gated on the realised side: an unrealised loss on its own is
    not an action, it is a fact the P/L column already shows. It becomes one
    when the user has a taxable gain this year that the loss would cancel — and
    then the repurchase window is the part that costs money to get wrong, so it
    travels with the signal.
    """
    if tbl is None or tbl.empty:
        return []
    net_gain = realized_this_year(realized, jurisdiction, today)
    if net_gain <= 0:
        return []
    out: list[Signal] = []
    for ticker, row in tbl.iterrows():
        pnl = finite(row.get("pnl"))
        if pnl is None or pnl > -HARVEST_MIN:
            continue
        out.append(Signal(
            HARVEST, str(ticker), _URGENCY[HARVEST],
            {
                "loss": _round(abs(pnl)),
                "gain_ytd": _round(net_gain),
                "offset": _round(min(abs(pnl), net_gain)),
                "pnl_pct": _round((finite(row.get("pnl_pct")) or 0) * 100),
                "currency": currency,
                "jurisdiction": getattr(jurisdiction, "code", None),
                "repurchase_window": getattr(jurisdiction, "repurchase_window", ""),
            },
        ))
    return out


# --------------------------------------------------------- calendar & price


def _earnings_signals(earnings, held: set[str]) -> list[Signal]:
    """Prints inside EARNINGS_DAYS — a date the user can still act before.

    Held names only: a print on a name you do not own is news, not a decision.
    The closer the date the higher it sorts, so tomorrow's print outranks
    Friday's.
    """
    out: list[Signal] = []
    for event in earnings:
        days = getattr(event, "days_until", None)
        if getattr(event, "date", None) is None or days is None:
            continue
        if event.ticker not in held or not 0 <= days <= EARNINGS_DAYS:
            continue
        out.append(Signal(
            EARNINGS, event.ticker, _URGENCY[EARNINGS] + (EARNINGS_DAYS - days),
            {"in_days": int(days), "date": event.date.isoformat()},
        ))
    return out


def _low_signals(extremes, held: set[str]) -> list[Signal]:
    """Watchlist names at their 52-week low — the "getting interesting" case.

    Held names are excluded on purpose: for something already owned this is the
    drawdown signal's territory, and printing both would say the same thing
    twice in a card with three lines.
    """
    out: list[Signal] = []
    for ticker, price, kind, distance in extremes:
        if kind != "low" or ticker in held:
            continue
        gap = abs(finite(distance) or 0.0) * 100
        if gap > LOW_52W_PCT:
            continue
        out.append(Signal(
            LOW_52W, ticker, _URGENCY[LOW_52W],
            {"price": _round(price), "gap_pct": _round(gap)},
        ))
    return out


# ------------------------------------------------- the market, against this book


def _market_signal(closes: dict, sector_etfs: dict[str, str]) -> Signal | None:
    """The tape itself: the index's trend, its drawdown, and trend breadth.

    Not a market summary — the card refuses to be one. This fires only when
    the market is in a state that changes how the rest of the card should be
    read: off its high, out of an uptrend, or being carried by a narrowing set
    of sectors while the index itself looks fine. A market quietly making
    highs with broad participation raises nothing, because there is nothing
    for the reader to do about it.
    """
    from stocks.analysis import sentiment as sm

    index = closes.get("SPY")
    if index is None or index.dropna().empty:
        return None
    trend = sm.trend_state(index)
    dip = finite(sm.from_high(index) * 100)
    month = finite(sm.pct_over(index, MONTH_SESSIONS) * 100)
    hits, total = sm.above_ma_share(closes, list(sector_etfs.values()), TREND_MA)
    breadth = _round(hits / total * 100) if total else None

    interesting = (
        (trend not in ("up", "unknown"))
        or (dip is not None and dip <= -INDEX_DIP_PCT)
        or (breadth is not None and breadth <= BREADTH_LOW_PCT)
    )
    if not interesting:
        return None
    data = {
        "index": "S&P 500",
        "trend": trend,
        "from_high_pct": _round(dip),
        "month_pct": _round(month),
    }
    if breadth is not None:
        # Both the share and the count: "5 of 11" is the sentence a reader
        # checks, and the percentage is what the model compares against.
        data |= {
            "breadth_pct": breadth,
            "sectors_in_uptrend": hits,
            "sectors_read": total,
        }
    return Signal(MARKET, "", _URGENCY[MARKET], data)


def _tilt_signal(
    book_sectors, bench_sectors, excess, currency: str
) -> Signal | None:
    """The book's single largest sector bet against the index, and how that
    bet has been paying over the last month.

    One line, not a table: the reader does not need eleven active weights, they
    need the one that decides how their book behaves. Over- and underweights
    both qualify — not holding the sector that led the month is the same
    decision as holding the one that lagged — and the sector's own excess
    return is carried so the line can say whether the bet is working.
    """
    import pandas as pd

    from stocks.analysis import sentiment as sm

    if book_sectors is None or not len(book_sectors) or not bench_sectors:
        return None
    bench = pd.Series(bench_sectors, dtype=float)
    # "Unknown" is the bucket for a holding whose sector could not be read; a
    # tilt against it is an artefact of the lookup, not a decision the reader
    # made. Same for crypto and bond sleeves, which no equity sector covers.
    # They are dropped from the BOOK, not from the comparison: leaving them in
    # the denominator would report every index sector as a large underweight
    # purely because a third of the book is unclassified — which is how this
    # first fired on a book holding no technology at all.
    equity = book_sectors.drop(
        labels=["Unknown", "Crypto", "Funds"], errors="ignore"
    ).dropna()
    covered = float(equity.sum())
    if equity.empty or covered < TILT_COVERAGE:
        return None
    # Renormalised onto the part that can be compared, so "55%" means 55% of
    # the equity the index also holds, which is the only reading that makes
    # the subtraction below honest.
    equity = equity / covered
    tilts = sm.tilt(equity, bench).dropna()
    if tilts.empty:
        return None
    sector = str(tilts.abs().idxmax())
    tilt_pp = float(tilts[sector]) * 100
    if abs(tilt_pp) < TILT_PP:
        return None
    own = float(equity.get(sector, 0.0)) * 100
    bench_pct = float(bench.get(sector, 0.0)) * 100
    move = None
    if excess is not None and sector in getattr(excess, "index", ()):
        move = finite(float(excess[sector]) * 100)
    return Signal(
        SECTOR_TILT, "", _URGENCY[SECTOR_TILT],
        {
            "sector": sector,
            "own_pct": _round(own),
            "index_pct": _round(bench_pct),
            "tilt_pp": _round(tilt_pp),
            "excess_month_pct": _round(move),
            # What share of the book these percentages are OF, so a line
            # written about a book that is also part crypto can say so.
            "equity_share_pct": _round(covered * 100),
            "currency": currency,
        },
    )


def _vs_bench_signal(book_month_pct, bench_month_pct, currency: str) -> Signal | None:
    """The book's month against the index's, when the two parted company.

    Both figures are in the reader's base currency (the caller converts the
    index), so the gap is the one they would get by subtracting the two numbers
    themselves — and the currency's own contribution is the `fx` signal's line,
    not hidden inside this one.
    """
    book, bench = finite(book_month_pct), finite(bench_month_pct)
    if book is None or bench is None:
        return None
    gap = book - bench
    if abs(gap) < VS_BENCH_PP:
        return None
    return Signal(
        VS_BENCH, "", _URGENCY[VS_BENCH],
        {
            "index": "S&P 500",
            "book_month_pct": _round(book),
            "index_month_pct": _round(bench),
            "gap_pp": _round(gap),
            "currency": currency,
        },
    )


def _fx_signal(currency_weights, moves: dict, base: str) -> Signal | None:
    """What the currency did to a book that is not priced in its own.

    A euro investor holding US names is short euro whether they meant to be or
    not, and in a month the dollar moves 3% that position is a bigger part of
    the return than any single holding. It fires on the exposure *and* the
    move: a large dollar share in a flat month is a fact about the book, not
    something to do today.
    """
    from stocks.analysis import sentiment as sm

    if currency_weights is None or not len(currency_weights):
        return None
    drag, contributions = sm.fx_exposure(currency_weights, moves, base=base)
    if drag != drag or contributions.empty:
        return None
    foreign = float(sum(w for c, w in currency_weights.items() if c != base)) * 100
    biggest = str(contributions.abs().idxmax())
    move = finite((moves.get(biggest) or 0.0) * 100)
    if foreign < FX_SHARE_PCT or move is None or abs(move) < FX_MOVE_PCT:
        return None
    return Signal(
        FX, "", _URGENCY[FX],
        {
            "base": base,
            "currency": biggest,
            "foreign_share_pct": _round(foreign),
            "share_pct": _round(float(currency_weights.get(biggest, 0.0)) * 100),
            "move_month_pct": _round(move),
            "drag_month_pct": _round(drag * 100),
        },
    )


def market_candidates(
    closes: dict | None = None,
    *,
    book_sectors=None,
    bench_sectors: dict | None = None,
    currency_weights=None,
    book_month_pct: float | None = None,
    bench_month_pct: float | None = None,
    currency: str = "EUR",
) -> list[Signal]:
    """The triggers that are about the market and the shape of the book, not
    about one holding.

    Split from `candidates()` because these are the only ones with an input the
    dashboard does not already hold: index and sector-ETF closes. The caller
    fetches them (web/market_data.py caches the download across sessions) and
    passes frames in, so this stays as pure and as testable as the rest.

    Every argument is optional and every signal is independent: a book whose
    sectors could not be read still gets the index line, and an account on a
    throttled Yahoo gets none of them and a card built the way it was before.
    """
    from stocks.analysis import sentiment as sm

    closes = closes or {}
    excess = None
    if closes:
        excess = sm.relative_strength(
            closes, sm.SECTOR_ETFS, "SPY", MONTH_SESSIONS
        )
    out = [
        _market_signal(closes, sm.SECTOR_ETFS) if closes else None,
        _tilt_signal(book_sectors, bench_sectors, excess, currency),
        _vs_bench_signal(book_month_pct, bench_month_pct, currency),
        _fx_signal(currency_weights, _fx_moves(closes, currency), currency),
    ]
    return [s for s in out if s is not None]


def _fx_moves(closes: dict, base: str) -> dict[str, float]:
    """{currency: its move against `base` over a month} from the FX series the
    card downloads.

    Only EUR/USD today, which covers the case that matters — a European book
    full of American names. `EURUSD=X` quotes dollars per euro, so the dollar's
    own move against the euro is the reciprocal, and getting that inversion
    wrong would report every dollar rally as a fall.
    """
    from stocks.analysis import sentiment as sm

    pair = closes.get("EURUSD=X")
    if pair is None or base != "EUR":
        return {}
    move = sm.pct_over(pair, MONTH_SESSIONS)
    return {} if move != move else {"USD": 1.0 / (1.0 + move) - 1.0}


# ------------------------------------------------------------------ the set


def decay(signal: Signal, shown: dict | None, today: date) -> int:
    """`signal`'s urgency after the days it has already been offered.

    `shown` is the card's own memory (daily.DailyAction.shown): key -> {"last",
    "run"}, written when a card is stored. A standing trigger that was on the
    last few days' cards sinks `DECAY_PER_DAY` per day, to `DECAY_MAX`, so the
    card turns over even when the book does not. Events never sink — an alert
    firing today is today's news however long it has been near the level — and
    a streak that stopped more than `DECAY_FORGET_DAYS` ago is ignored, so a
    trigger that goes away and comes back arrives at full urgency.
    """
    if signal.kind not in _STANDING:
        return signal.urgency
    seen = (shown or {}).get(signal.key)
    if not isinstance(seen, dict):
        return signal.urgency
    try:
        last = date.fromisoformat(str(seen.get("last") or ""))
    except ValueError:
        return signal.urgency
    if (today - last).days > DECAY_FORGET_DAYS:
        return signal.urgency
    run = max(int(seen.get("run") or 0), 0)
    return signal.urgency - min(run * DECAY_PER_DAY, DECAY_MAX)


def candidates(
    *,
    holdings=(),
    tbl=None,
    closes: dict | None = None,
    realized=(),
    earnings=(),
    extremes=(),
    market=(),
    shown: dict | None = None,
    jurisdiction=None,
    currency: str = "EUR",
    today: date | None = None,
    limit: int = 8,
) -> list[Signal]:
    """Every action the book currently justifies, most urgent first.

    One ticker can raise several (a name can be both deeply down and the
    harvest candidate), and the card's job is to choose — but only within
    `_CAP` per kind, so one crowded family cannot take the whole card, and
    after `decay()`, so a family that had its turn yesterday gives way today.
    Ties keep ticker order, which keeps the list stable between reruns of an
    unchanged book.

    `market` is the list `market_candidates()` built, passed in rather than
    computed here because it is the one part with a download behind it.
    """
    day = today or date.today()
    held = set(tbl.index.astype(str)) if tbl is not None and not tbl.empty else set()
    out = [
        *_alert_signals(holdings, closes or {}, held),
        *_harvest_signals(tbl, realized, jurisdiction, currency, today),
        *_earnings_signals(earnings, held),
        *_position_signals(tbl, currency),
        *_low_signals(extremes, held),
        *market,
    ]
    ranked = sorted(out, key=lambda s: (-decay(s, shown, day), s.kind, s.ticker))
    kept: list[Signal] = []
    seen: dict[str, int] = {}
    for signal in ranked:
        room = _CAP.get(signal.kind, _CAP_DEFAULT)
        if seen.get(signal.kind, 0) >= room:
            continue
        seen[signal.kind] = seen.get(signal.kind, 0) + 1
        kept.append(signal)
        if len(kept) >= limit:
            break
    return kept
