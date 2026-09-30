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
  - **the earnings calendar** — a print inside a few days is a decision date,
    not news; one inside two weeks, or on a watched name, is one to plan for;
    and a print of the last few days is reported against its estimate.
  - **the price** — a watchlist name at its 52-week low is the "getting close
    to interesting" case, which is about candidates, not holdings.
  - **the market, against this book** — the index's own trend and how much of
    it is still in one, the sector bet the book is running against the index,
    how the book did beside that index, and what the currency did to it.
    `market_candidates()` owns those.
  - **the central banks** — a Fed or ECB decision inside a week, and the one
    that just happened, read off the policy-rate series (`macro_candidates()`).
  - **the tax calendar** — a filing deadline coming up, the tax year closing
    with gains or losses still open, the next savings bracket within reach,
    and the day a loss sale's repurchase window lets go.

Each candidate carries its numbers and an urgency; stocks/chat/daily.py hands
the top few to the model, which picks and phrases — it never gets to invent one
— and renders them directly when no model is available. Nothing here fetches:
every input is a frame, list or series the caller already loaded.

**A card that repeats itself is a card nobody reads.** Most of these triggers
are standing conditions, not events: an open loss with a gain behind it is
just as true tomorrow, and a fired alert stays fired for as long as the price
stays past it — which is how one alert led the card for weeks. So the card
remembers what it said (daily.DailyAction.shown: every key it showed, when,
and the figure it showed it with), and `candidates()` drops a trigger that was
on an earlier day's card and has not changed since (`repeat()`): its figure has
not moved past `_MATERIAL`, its phase has not advanced, its cooldown has not
run out. An alert is an event only on the sessions after it crossed; one that
has been past its level for longer is `alert_stale`, said once — the level has
stopped telling the user anything — and then left alone. `_CAP` and
`_FAMILY_CAP` still limit how many of one kind can reach the model at once, and
`decay()` still sinks a standing trigger shown on consecutive days.
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
# A print this close is a decision date for a held name; out to EARNINGS_AHEAD
# it is one to plan for, and the only horizon a watched name gets.
EARNINGS_DAYS = 5
EARNINGS_AHEAD = 14
# A print this recent is still the news the reader has to digest.
RESULT_DAYS = 3
# Within this of the 52-week low, a watchlist name is worth a look.
LOW_52W_PCT = 3.0
# An alert whose price has stayed past the level for more sessions than this
# is no longer an event: it fired, it was said, and the level has stopped
# telling the user anything until they move it.
ALERT_FRESH_SESSIONS = 5

# --- the calendars ------------------------------------------------------------
# A rate decision this close is worth planning around; one this recent is
# still the backdrop. The ECB's window is longer because its deposit rate only
# changes the Wednesday after the decision, and the move is read off the rate.
MACRO_DAYS = 7
_RESULT_DAYS = {"fed": 4, "ecb": 9}
# How far ahead a filing deadline, and the end of the tax year, reach the card.
TAX_DEADLINE_DAYS = 30
YEAR_END_DAYS = 60
# A savings bracket this close (as a share of its own width) is the one the
# next realised gain lands in.
BRACKET_ROOM_SHARE = 0.25
# A loss sale's repurchase window ending this soon is a date to plan a buy on.
REPURCHASE_DAYS = 7

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
# Allocation buckets that are not an equity sector: a holding whose sector
# could not be read, and the crypto and bond sleeves no index sector covers.
# Left out of any comparison with the index, and of "share of the equity".
NOT_EQUITY = ("Unknown", "Crypto", "Funds")
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
ALERT_STALE = "alert_stale"
HARVEST = "harvest"
EARNINGS = "earnings"
EARNINGS_RESULT = "earnings_result"
ALERT_NEAR = "alert_near"
MARKET = "market"
DRAWDOWN = "drawdown"
SECTOR_TILT = "sector_tilt"
LOW_52W = "low_52w"
VS_BENCH = "vs_benchmark"
FX = "fx"
CONCENTRATION = "concentration"
MACRO_EVENT = "macro_event"
MACRO_RESULT = "macro_result"
TAX_DEADLINE = "tax_deadline"
TAX_YEAR_END = "tax_year_end"
TAX_BRACKET = "tax_bracket"
REPURCHASE_CLEAR = "repurchase_clear"

_URGENCY = {
    ALERT_HIT: 90,
    HARVEST: 75,
    EARNINGS_RESULT: 72,
    EARNINGS: 70,
    MACRO_RESULT: 66,
    TAX_DEADLINE: 62,
    ALERT_NEAR: 60,
    MARKET: 58,
    MACRO_EVENT: 57,
    DRAWDOWN: 55,
    SECTOR_TILT: 52,
    TAX_YEAR_END: 50,
    TAX_BRACKET: 48,
    REPURCHASE_CLEAR: 47,
    LOW_52W: 45,
    VS_BENCH: 44,
    ALERT_STALE: 42,
    FX: 40,
    CONCENTRATION: 35,
}
# How far a watched (not held) name's print or result sits under a held one's:
# news about a candidate, not a decision about money already in it.
WATCHED_DISCOUNT = 22

# How many of one kind may reach the model in a single card. Events are allowed
# to crowd it — three alerts firing on one morning IS the morning — but a
# standing condition gets one line and no more. Before this cap a book with
# five losing positions and a booked gain produced five harvest candidates,
# which outranked everything else and made every card the same card.
_CAP = {
    ALERT_HIT: 3,
    ALERT_NEAR: 2,
    EARNINGS: 2,
    EARNINGS_RESULT: 2,
    LOW_52W: 2,
    MACRO_EVENT: 2,
}
_CAP_DEFAULT = 1

# And how many of one family: two central banks and the index are one story
# about rates and the tape, and the four tax lines are one about this year's
# bill — a card spending all its lines on either is the monotony `_CAP` exists
# to prevent, one level up.
_FAMILY = {
    ALERT_HIT: "alert",
    ALERT_NEAR: "alert",
    ALERT_STALE: "alert",
    EARNINGS: "earnings",
    EARNINGS_RESULT: "earnings",
    MARKET: "macro",
    MACRO_EVENT: "macro",
    MACRO_RESULT: "macro",
    HARVEST: "tax",
    TAX_DEADLINE: "tax",
    TAX_YEAR_END: "tax",
    TAX_BRACKET: "tax",
    REPURCHASE_CLEAR: "tax",
}
_FAMILY_CAP = {"alert": 3, "earnings": 3, "macro": 2, "tax": 2}

# The kinds a reader would see word for word again tomorrow, and so the ones
# `decay()` sinks. Left out on purpose: events (an alert crossing, a print, a
# decision, a deadline) whose phase moves on its own, and `market` and
# `vs_benchmark`, re-read from the tape every day.
_STANDING = frozenset(
    {
        HARVEST, DRAWDOWN, CONCENTRATION, LOW_52W, SECTOR_TILT, FX, ALERT_NEAR,
        ALERT_STALE, TAX_BRACKET,
    }
)
# Urgency lost per consecutive day already offered, and the floor it stops at.
# Three days takes harvest from 75 to 39 — under a fresh drawdown, over a fresh
# 52-week low — which is the point: it drops down the card rather than off it.
DECAY_PER_DAY = 12
DECAY_MAX = 36
# A key not offered for this many days has stopped being repetitive; its streak
# is forgotten rather than carried forever.
DECAY_FORGET_DAYS = 7
# How long the card remembers having shown a key at all. Longer than any
# cooldown below, or a print shown a fortnight out would be forgotten — and
# shown again as new — before its own date came round.
MEMORY_DAYS = 45


@dataclass(frozen=True)
class _Rel:
    """A material move measured against the old figure: 0.25 is a quarter."""

    share: float


# What "changed since the reader last saw it" means, per kind: the fields the
# card remembers with each key, and how far each must move before the trigger
# reads as new. A number is an absolute move in the field's own units (points
# for a percentage), `_Rel` a share of the old value, None an exact change — a
# new phase, a new date, a different sector. An event's phase ("week", "soon",
# "now") is how a print is allowed back onto the card as it gets closer.
_MATERIAL: dict[str, dict] = {
    ALERT_HIT: {"rule": None, "level": None},
    ALERT_STALE: {"rule": None, "level": None},
    ALERT_NEAR: {"rule": None, "level": None, "gap_pct": 1.5},
    HARVEST: {"offset": _Rel(0.25)},
    DRAWDOWN: {"pnl_pct": 5.0},
    CONCENTRATION: {"weight_pct": 3.0},
    LOW_52W: {"price": _Rel(0.05)},
    MARKET: {"trend": None, "from_high_pct": 3.0, "breadth_pct": 15.0},
    SECTOR_TILT: {"sector": None, "tilt_pp": 3.0},
    VS_BENCH: {"gap_pp": 3.0},
    FX: {"currency": None, "move_month_pct": 1.5},
    EARNINGS: {"date": None, "phase": None},
    EARNINGS_RESULT: {"date": None},
    MACRO_EVENT: {"date": None, "phase": None},
    MACRO_RESULT: {"date": None},
    TAX_DEADLINE: {"date": None, "phase": None},
    TAX_YEAR_END: {"end": None, "phase": None},
    TAX_BRACKET: {"rate_pct": None, "room": _Rel(0.5)},
    REPURCHASE_CLEAR: {"clear_date": None},
}

# Days after which an unchanged trigger may come back as a reminder. None is
# never: an event is said once per phase, and its next phase is its reminder.
_COOLDOWN: dict[str, int | None] = {
    ALERT_HIT: None,
    ALERT_STALE: 14,
    ALERT_NEAR: 7,
    HARVEST: 7,
    DRAWDOWN: 10,
    CONCENTRATION: 14,
    LOW_52W: 7,
    MARKET: 7,
    SECTOR_TILT: 14,
    VS_BENCH: 7,
    FX: 7,
    EARNINGS: None,
    EARNINGS_RESULT: None,
    MACRO_EVENT: None,
    MACRO_RESULT: None,
    TAX_DEADLINE: None,
    TAX_YEAR_END: None,
    TAX_BRACKET: 14,
    REPURCHASE_CLEAR: None,
}


@dataclass(frozen=True)
class Signal:
    """One candidate action. `data` holds the numbers its phrasing needs."""

    kind: str
    ticker: str
    urgency: int
    data: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """What "the same trigger as yesterday" means, for `repeat()` and
        `decay()`.

        Kind plus subject: a market-wide signal carries no ticker and is keyed
        on its kind alone, a sector bet on the sector rather than on a holding,
        a rate decision on its bank, and a tax deadline on the deadline —
        because each of those is the thing that would read as a repeat.
        """
        return key_of(self.kind, {"ticker": self.ticker, **self.data})

    def to_dict(self) -> dict:
        # The key rides along: the model hands it back with each line it
        # writes, which is how the card knows which triggers it actually
        # showed (and so which to remember) rather than which it was offered.
        return {"kind": self.kind, "ticker": self.ticker, **self.data, "key": self.key}


def key_of(kind: str, data: dict) -> str:
    """`Signal.key` from a kind and its dict — what a stored action carries."""
    subject = (
        data.get("ticker")
        or data.get("sector")
        or data.get("bank")
        or data.get("deadline")
        or ""
    )
    return f"{kind}:{subject}"


def _round(value, digits: int = 2) -> float | None:
    out = finite(value)
    return None if out is None else round(out, digits)


# ------------------------------------------------------------ the user's own


def _sessions_past(alert, prices: list) -> int:
    """How many closes in a row, counting back from the last, the alert has
    been triggered on — the age of the crossing, in sessions."""
    run = 0
    for value in reversed(prices):
        price = finite(value)
        if price is None or not alert.triggered(price):
            break
        run += 1
    return run


def _alert_signals(holdings, closes: dict, held: set[str]) -> list[Signal]:
    """Price-threshold alerts against the last close, fired and nearly fired.

    Only `above`/`below` rules: they carry an explicit price, which is what
    makes them readable as the user's own level ("your exit at 150"). The
    history-based rules (drawdown, RSI, SMA cross) are evaluated by
    notify/alerts.py against a full price history — a fetch this card has no
    business making, and the notification path already covers them.

    `closes` is each ticker's recent closes, oldest first, and the history is
    what tells an event from a state: an alert past its level for at most
    `ALERT_FRESH_SESSIONS` closes just crossed (`alert_hit`, with the count);
    one past it for longer is `alert_stale` — the level is no longer telling
    the user anything, which is its own, one-off, line. With only the last
    close to go on (a caller that passes one) every fired alert reads fresh.

    Comparison is in the ticker's own quote currency, because that is the
    currency the user typed the level in.
    """
    out: list[Signal] = []
    for h in holdings:
        prices = list(closes.get(h.ticker) or [])
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
                sessions = _sessions_past(alert, prices)
                kind = ALERT_HIT if sessions <= ALERT_FRESH_SESSIONS else ALERT_STALE
                out.append(Signal(
                    kind, h.ticker, _URGENCY[kind], data | {"sessions": sessions}
                ))
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


def phase(days: int) -> str:
    """Where a dated event sits: "now" (today or tomorrow), "soon" (inside
    `EARNINGS_DAYS`), "week" (further out). The card says an event once per
    phase, so a print two weeks out is announced, then recalled the week of,
    then on the day — three lines, not fourteen."""
    if days <= 1:
        return "now"
    if days <= EARNINGS_DAYS:
        return "soon"
    return "week"


def _earnings_signals(earnings, held: set[str]) -> list[Signal]:
    """Prints inside `EARNINGS_AHEAD` days — a date the user can still act
    before.

    A held name's print is a decision about money already in it, and inside
    `EARNINGS_DAYS` it sorts by how close it is, so tomorrow's print outranks
    Friday's. A watched name's is news about a candidate — worth a line, well
    under any held one (`WATCHED_DISCOUNT`).
    """
    out: list[Signal] = []
    for event in earnings:
        days = getattr(event, "days_until", None)
        if getattr(event, "date", None) is None or days is None:
            continue
        if not 0 <= days <= EARNINGS_AHEAD:
            continue
        owned = event.ticker in held
        urgency = _URGENCY[EARNINGS] + max(EARNINGS_DAYS - days, 0)
        if days > EARNINGS_DAYS:
            urgency -= 12
        if not owned:
            urgency -= WATCHED_DISCOUNT
        out.append(Signal(
            EARNINGS, event.ticker, urgency,
            {
                "in_days": int(days),
                "date": event.date.isoformat(),
                "held": owned,
                "phase": phase(int(days)),
            },
        ))
    return out


def _result_signals(results, held: set[str], today: date) -> list[Signal]:
    """Prints of the last `RESULT_DAYS` days: what was reported against what
    was expected.

    The calendar pass already carries these (loaders.earnings_calendar's
    second half — yfinance's reported EPS, the estimate and the surprise), so
    the line costs nothing; the revenue and the press release behind it are
    fetched only if the reader opens the detail. One per ticker, the newest.
    """
    out: list[Signal] = []
    seen: set[str] = set()
    for result in results:
        when = getattr(result, "date", None)
        reported = finite(getattr(result, "reported_eps", None))
        if when is None or reported is None or result.ticker in seen:
            continue
        ago = (today - when).days
        if not 0 <= ago <= RESULT_DAYS:
            continue
        seen.add(result.ticker)
        owned = result.ticker in held
        estimate = finite(getattr(result, "eps_estimate", None))
        surprise = finite(getattr(result, "surprise_pct", None))
        data = {
            "date": when.isoformat(),
            "days_ago": ago,
            "held": owned,
            "reported_eps": _round(reported),
            "eps_estimate": _round(estimate),
            "surprise_pct": _round(surprise),
        }
        if estimate is not None:
            data["beat"] = reported >= estimate
        urgency = _URGENCY[EARNINGS_RESULT] - ago * 3
        if not owned:
            urgency -= WATCHED_DISCOUNT
        out.append(Signal(EARNINGS_RESULT, result.ticker, urgency, data))
    return out


# --------------------------------------------------------------- the tax year


def _window_end(sell: date, window: str) -> date | None:
    """The first day a repurchase no longer touches a loss sold on `sell`."""
    from datetime import timedelta

    from stocks.portfolio.tax.base import shift_months

    if window == "2m":
        return shift_months(sell, 2) + timedelta(days=1)
    if window in ("30d", "28d"):
        return sell + timedelta(days=int(window[:-1]) + 1)
    return None


def _year_end(jurisdiction, today: date) -> date:
    """The last day of the tax year `today` falls in."""
    from datetime import timedelta

    month, day = getattr(jurisdiction, "year_start", (1, 1)) or (1, 1)
    start = date(today.year, month, day)
    nxt = start if start > today else date(today.year + 1, month, day)
    return nxt - timedelta(days=1)


def _tax_signals(
    tbl, realized, jurisdiction, currency: str, today: date
) -> list[Signal]:
    """The tax calendar against this book: what is due, what closes, what the
    next euro of gain costs, and when a blocked loss lets go.

    Each is a date or a threshold the user can plan a sale or a purchase
    around — the part of tax the tax tab reports after the fact.
    """
    if jurisdiction is None:
        return []
    out: list[Signal] = []
    code = getattr(jurisdiction, "code", None)

    # Filing deadlines — the soonest one only; the tax tab lists the rest.
    try:
        from stocks.portfolio.tax import deadlines

        due = deadlines.due_soon(code, today, within=TAX_DEADLINE_DAYS)
    except Exception:  # noqa: BLE001 — a calendar gap is no card line
        due = []
    for d in due[:1]:
        days = d.days_until(today)
        out.append(Signal(
            TAX_DEADLINE, "", _URGENCY[TAX_DEADLINE] + max(7 - days, 0),
            {
                "deadline": d.key,
                "year": d.year_label,
                "date": d.date.isoformat(),
                "in_days": days,
                "phase": "now" if days <= 1 else "soon" if days <= 7 else "week",
            },
        ))

    net_gain = realized_this_year(realized, jurisdiction, today)
    losses = gains = 0.0
    if tbl is not None and not tbl.empty and "pnl" in tbl:
        pnl = tbl["pnl"].dropna()
        losses = float(-pnl[pnl < 0].sum())
        gains = float(pnl[pnl > 0].sum())

    # The tax year closing with something still to decide in it.
    end = _year_end(jurisdiction, today)
    left = (end - today).days
    if 0 <= left <= YEAR_END_DAYS and (net_gain or losses >= HARVEST_MIN):
        out.append(Signal(
            TAX_YEAR_END, "", _URGENCY[TAX_YEAR_END] + (8 if left <= 30 else 0),
            {
                "end": end.isoformat(),
                "days_left": left,
                "gain_ytd": _round(net_gain),
                "open_losses": _round(losses),
                "open_gains": _round(gains),
                "currency": currency,
                "phase": "10" if left <= 10 else "30" if left <= 30 else "60",
            },
        ))

    # The next savings bracket, where the scale is progressive and in this
    # book's own currency (a USD-reported book against euro brackets would be
    # arithmetic on the wrong number).
    brackets = _brackets(code)
    if brackets and net_gain > 0 and currency == getattr(jurisdiction, "currency", ""):
        floor = 0.0
        for i, (upper, rate) in enumerate(brackets):
            if net_gain < upper:
                if i + 1 < len(brackets) and upper != float("inf"):
                    room = upper - net_gain
                    if room <= (upper - floor) * BRACKET_ROOM_SHARE:
                        out.append(Signal(
                            TAX_BRACKET, "", _URGENCY[TAX_BRACKET],
                            {
                                "gain_ytd": _round(net_gain),
                                "threshold": _round(upper),
                                "room": _round(room),
                                "rate_pct": _round(rate * 100),
                                "next_rate_pct": _round(brackets[i + 1][1] * 100),
                                "currency": currency,
                            },
                        ))
                break
            floor = upper

    # A loss sale whose repurchase window ends within the week, on a name not
    # bought back — the date from which buying it again keeps the loss.
    window = getattr(jurisdiction, "repurchase_window", "") or ""
    held = set(tbl.index.astype(str)) if tbl is not None and not tbl.empty else set()
    latest: dict[str, _Loss] = {}
    for sale in realized:
        if sale.gain >= 0 or sale.ticker in held:
            continue
        try:
            sold = date.fromisoformat(str(sale.sell_date)[:10])
        except ValueError:
            continue
        mine = latest.get(sale.ticker)
        if mine is None or sold > mine.sold:
            latest[sale.ticker] = _Loss(sold, -sale.gain)
        elif sold == mine.sold:
            latest[sale.ticker] = _Loss(sold, mine.loss - sale.gain)
    for ticker, loss in sorted(latest.items()):
        clear = _window_end(loss.sold, window)
        if clear is None:
            continue
        days = (clear - today).days
        if 0 <= days <= REPURCHASE_DAYS and loss.loss >= HARVEST_MIN:
            out.append(Signal(
                REPURCHASE_CLEAR, ticker, _URGENCY[REPURCHASE_CLEAR],
                {
                    "sell_date": loss.sold.isoformat(),
                    "clear_date": clear.isoformat(),
                    "in_days": days,
                    "loss": _round(loss.loss),
                    "currency": currency,
                    "repurchase_window": window,
                },
            ))
    return out


@dataclass(frozen=True)
class _Loss:
    """A ticker's latest loss sale: its date and what it lost, parcels summed."""

    sold: date
    loss: float


def _brackets(code: str | None) -> list[tuple[float, float]]:
    """The progressive savings scale the card can reason about, or none.

    Spain's base del ahorro only, today: a single scale with no filing status
    and no other income in it, so the bracket a realised gain lands in is
    arithmetic on that gain alone. Every other jurisdiction's rate depends on
    settings the card does not read.
    """
    if code != "ES":
        return []
    from stocks.portfolio.tax import es

    return list(es.SAVINGS_BRACKETS)


# --------------------------------------------------------- the central banks


def macro_due(bank: str, today: date) -> bool:
    """Whether `bank` has a decision close enough, ahead or behind, for
    `macro_candidates()` to say anything — so the caller downloads the rate
    series only on the few days a year it can matter."""
    from stocks.data import macro_calendar as cal

    nxt = cal.next_decision(bank, today)
    last = cal.last_decision(bank, today)
    return (nxt is not None and (nxt - today).days <= MACRO_DAYS) or (
        last is not None and (today - last).days <= _RESULT_DAYS.get(bank, 4)
    )


def macro_candidates(
    today: date, rates: dict | None = None, *, banks=("fed", "ecb")
) -> list[Signal]:
    """A rate decision inside `MACRO_DAYS`, and the one just taken.

    The calendar is data (stocks/data/macro_calendar.py); the rate is the
    policy series itself, which the caller fetches (FRED, keyless) and passes
    in as `rates` — {series id: date-indexed Series} — so this stays pure.

    The result is read off the series, not a headline: an observation dated
    after the decision day that differs from the one before it is a move, and
    one that matches is a hold. The ECB's deposit rate only changes on the
    following Wednesday, so a hold there is indistinguishable from a move not
    yet effective and is left unsaid; a move is reported once it shows.
    """
    from stocks.data import macro_calendar as cal

    rates = rates or {}
    out: list[Signal] = []
    for bank in banks:
        ids = cal.RATE_SERIES.get(bank, ())
        series = [s for sid in ids if (s := rates.get(sid)) is not None]
        if not series or len(series) < len(ids) or any(s.dropna().empty for s in series):
            continue
        upper = series[-1].dropna()
        lower = series[0].dropna() if len(series) > 1 else None
        rate = _round(float(upper.iloc[-1]))
        low = _round(float(lower.iloc[-1])) if lower is not None else None

        nxt = cal.next_decision(bank, today)
        if nxt is not None and (nxt - today).days <= MACRO_DAYS:
            days = (nxt - today).days
            data = {
                "bank": bank,
                "date": nxt.isoformat(),
                "in_days": days,
                "rate": rate,
                "phase": "now" if days <= 1 else "week",
            }
            if low is not None:
                data["rate_low"] = low
            out.append(Signal(
                MACRO_EVENT, "", _URGENCY[MACRO_EVENT] + max(3 - days, 0), data
            ))

        last = cal.last_decision(bank, today)
        if last is None or (today - last).days > _RESULT_DAYS.get(bank, 4):
            continue
        stamp = _stamp(last)
        before = upper[upper.index <= stamp]
        after = upper[upper.index > stamp]
        if before.empty or after.empty:
            continue
        was, now = float(before.iloc[-1]), float(after.iloc[-1])
        change_bp = round((now - was) * 100)
        if change_bp == 0 and bank == "ecb":
            continue
        data = {
            "bank": bank,
            "date": last.isoformat(),
            "days_ago": (today - last).days,
            "rate_before": _round(was),
            "rate": _round(now),
            "change_bp": change_bp,
            "decision": "hike" if change_bp > 0 else "cut" if change_bp < 0 else "hold",
        }
        if low is not None:
            data["rate_low"] = low
        urgency = _URGENCY[MACRO_RESULT] - (10 if change_bp == 0 else 0)
        out.append(Signal(MACRO_RESULT, "", urgency, data))
    return out


def _stamp(day: date):
    import pandas as pd

    return pd.Timestamp(day)


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
    equity = book_sectors.drop(labels=list(NOT_EQUITY), errors="ignore").dropna()
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
    if last >= today:
        # Today's own stamp is not a day it was already offered: a Regenerate
        # must rank the same triggers the card it replaces ranked.
        run -= 1
    return signal.urgency - min(max(run, 0) * DECAY_PER_DAY, DECAY_MAX)


def measure(kind: str, data: dict) -> dict:
    """The figures `repeat()` compares for one trigger — what the card stores
    beside each key it showed (daily.seen)."""
    return {name: data.get(name) for name in _MATERIAL.get(kind, {})}


def _moved(before: dict, after: dict, rules: dict) -> bool:
    """Whether any remembered figure moved past its rule (`_MATERIAL`)."""
    for name, rule in rules.items():
        old, new = before.get(name), after.get(name)
        if rule is None or old is None or new is None:
            if old != new:
                return True
            continue
        try:
            old, new = float(old), float(new)
        except (TypeError, ValueError):
            if old != new:
                return True
            continue
        limit = rule.share * abs(old) if isinstance(rule, _Rel) else float(rule)
        if abs(new - old) >= limit:
            return True
    return False


def _weekdays(start: date, end: date) -> int:
    """Weekdays in (start, end] — sessions elapsed, holidays aside."""
    from datetime import timedelta

    days, count = start, 0
    while days < end:
        days += timedelta(days=1)
        count += days.weekday() < 5
    return count


def repeat(signal: Signal, shown: dict | None, today: date) -> bool:
    """Whether `signal` is one an earlier day's card already showed, and
    nothing about it has changed since — the card's memory, as a filter.

    `shown` is daily.DailyAction.shown: key -> {"last", "run", "v"}, where "v"
    is `measure()` at the time. A trigger is a repeat when it was last shown
    before today (today's own card — a Regenerate — is free to show it again),
    its figures have not moved past `_MATERIAL`, and its `_COOLDOWN` has not
    run out. A fired alert is the one case measured by time instead: it is the
    crossing already shown while the price has stayed past the level since
    the day it was shown — a fresh crossing after a retreat is news again.

    A memory entry from before the figures were stored ("v" missing) cannot
    say whether anything changed, so only its cooldown applies.
    """
    entry = (shown or {}).get(signal.key)
    if not isinstance(entry, dict) or signal.kind not in _MATERIAL:
        return False
    try:
        last = date.fromisoformat(str(entry.get("last") or ""))
    except ValueError:
        return False
    if last >= today:
        return False
    before = entry.get("v")
    rules = _MATERIAL[signal.kind]
    now = measure(signal.kind, signal.data)
    if isinstance(before, dict) and _moved(before, now, rules):
        return False
    if signal.kind == ALERT_HIT:
        return int(signal.data.get("sessions") or 1) >= _weekdays(last, today)
    cooldown = _COOLDOWN.get(signal.kind)
    if not isinstance(before, dict) and cooldown is None:
        # An event remembered without its phase: said once is enough until
        # the memory ages out.
        return (today - last).days <= DECAY_FORGET_DAYS
    return cooldown is None or (today - last).days < cooldown


def candidates(
    *,
    holdings=(),
    tbl=None,
    closes: dict | None = None,
    realized=(),
    earnings=(),
    results=(),
    extremes=(),
    market=(),
    macro=(),
    shown: dict | None = None,
    jurisdiction=None,
    currency: str = "EUR",
    today: date | None = None,
    limit: int = 8,
) -> list[Signal]:
    """Every action the book currently justifies and the card has not already
    said, most urgent first.

    One ticker can raise several (a name can be both deeply down and the
    harvest candidate), and the card's job is to choose — but only among the
    ones `repeat()` lets through, within `_CAP` per kind and `_FAMILY_CAP` per
    family so one crowded family cannot take the whole card, and after
    `decay()`, so a family that had its turn yesterday gives way today. Ties
    keep ticker order, which keeps the list stable between reruns of an
    unchanged book.

    `market` and `macro` are the lists `market_candidates()` and
    `macro_candidates()` built, passed in rather than computed here because
    they are the parts with a download behind them. `results` is the
    calendar's past prints (EarningsResult), newest first.
    """
    day = today or date.today()
    held = set(tbl.index.astype(str)) if tbl is not None and not tbl.empty else set()
    out = [
        *_alert_signals(holdings, closes or {}, held),
        *_harvest_signals(tbl, realized, jurisdiction, currency, today),
        *_earnings_signals(earnings, held),
        *_result_signals(results, held, day),
        *_position_signals(tbl, currency),
        *_low_signals(extremes, held),
        *_tax_signals(tbl, realized, jurisdiction, currency, day),
        *market,
        *macro,
    ]
    fresh = [s for s in out if not repeat(s, shown, day)]
    ranked = sorted(fresh, key=lambda s: (-decay(s, shown, day), s.kind, s.ticker))
    kept: list[Signal] = []
    per_kind: dict[str, int] = {}
    per_family: dict[str, int] = {}
    for signal in ranked:
        family = _FAMILY.get(signal.kind, signal.kind)
        if per_kind.get(signal.kind, 0) >= _CAP.get(signal.kind, _CAP_DEFAULT):
            continue
        if per_family.get(family, 0) >= _FAMILY_CAP.get(family, limit):
            continue
        per_kind[signal.kind] = per_kind.get(signal.kind, 0) + 1
        per_family[family] = per_family.get(family, 0) + 1
        kept.append(signal)
        if len(kept) >= limit:
            break
    return kept
