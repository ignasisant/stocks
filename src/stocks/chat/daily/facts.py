"""The facts the card is written from, built from the frames Home already
loaded. No network.
"""

from __future__ import annotations

from datetime import date

from stocks.chat.daily.card import (
    _VS_BENCH,
    EARNINGS_DAYS,
    MOVERS_SHOWN,
    WEIGHTS_SHOWN,
)
from stocks.formatting import finite


def _pct(value) -> float | None:
    out = finite(value)
    return None if out is None else round(out * 100, 2)


def _asof(tbl, ticker) -> str | None:
    """The session date `tbl` carries for one row (`api.home.enriched` writes
    `day_asof`), or None on a frame built without it."""
    if "day_asof" not in getattr(tbl, "columns", ()):
        return None
    try:
        value = tbl.at[ticker, "day_asof"]
    except KeyError:
        return None
    text = str(value or "").strip()
    return text[:10] if text and text.lower() not in ("nan", "nat", "none") else None


def _session(facts: dict) -> dict | None:
    """`{"date", "is_today"}` — the trading day the card's figures are from.

    The latest session any mover carries: with a European name still trading
    while New York sleeps the rows can straddle two dates, so each mover keeps
    its own `as_of` and this is only the headline one. None when no mover
    carried a date (a frame from before the column existed, or no movers).
    """
    dates = sorted(
        d for d in (m.get("as_of") for m in facts.get("movers") or []) if d
    )
    if not dates:
        return None
    return {"date": dates[-1], "is_today": dates[-1] == facts.get("date")}


def build_facts(
    tbl,
    hist=None,
    *,
    currency: str = "EUR",
    day: tuple[float, float] | None = None,
    earnings=(),
    extremes=(),
    signals=(),
    today: date | None = None,
    index: dict | None = None,
    brief: dict | None = None,
    money=None,
    plan: dict | None = None,
    attribution: dict | None = None,
) -> dict:
    """What the card is written from: the candidate actions, plus context.

    `signals` (stocks/chat/signals.py) are the "To watch" candidates — each
    one a trigger the book actually raised, with the numbers behind it. The
    portfolio totals are the Portfolio section's: `day` / `week` / `month`
    against `index` (`daily_book.index_facts`), which the headline opens on.
    With the index in hand the month-against-the-index trigger is dropped:
    the section says it on every card, and a line repeating it is a line
    some real trigger did not get.

    Args:
        tbl: the live-priced positions frame (api/home.enriched) —
            value/cost/pnl/weight/day_pct per ticker, plus the
            `day_asof` stamp saying which session each day_pct is from (the
            last completed one, off-hours).
        hist: fixed-basket daily values (basket_history), for the day when
            `day` is not given, and the week and month when `money` is not.
        money: the book's value and money put in, day by day
            (`loaders.history`): the week and month on the book's own money
            (`money_change`), so a deposit inside the window is not a gain,
            and a month on 5,000 € does not read as one on 100,000 €.
        day: today's (change, pct) when the caller already resolved it — Home
            overrides the close-to-close basket off-session, and the card must
            show the same number the KPI row above it does.
        earnings: EarningsEvent list (any window); only the next
            EARNINGS_DAYS days reach the prompt as context.
        extremes: Home's 52-week scan rows, (ticker, price, kind, distance).
        signals: the Signal list from signals.candidates().
        index: the index's day / week / month in `currency`.
        brief: the reader's brief with its data (`daily_routines.gather`), or
            only its lines while that is fetched (`daily_routines.seeded`).
        plan: the book against a saved plan (`briefing.plan_fact`): whether
            it holds and when the next contribution is — what a day with
            nothing else to say can close on. None without a plan.
        attribution: the day split by position and block, and the last
            sessions against the index (`daily.attribution.day`).
    """
    from stocks.analysis.portfolio import basket_change, money_change, priced_totals

    facts: dict = {
        "date": (today or date.today()).isoformat(),
        "currency": currency,
    }
    if index and index.get("month_pct") is not None:
        signals = [s for s in signals if s.kind != _VS_BENCH]
    if signals:
        facts["actions"] = [s.to_dict() for s in signals]
    if index:
        facts["index"] = dict(index)
    if brief:
        facts["brief"] = dict(brief)
    if plan:
        facts["plan"] = dict(plan)
    if attribution:
        facts["attribution"] = dict(attribution)
    if tbl is not None and not tbl.empty:
        # Cost over the priced rows only: against the full basis a partly
        # priced book reads as a crash, and the briefing would open on it.
        _cost, _value, unpriced = priced_totals(tbl)
        value, cost = finite(_value), finite(_cost)
        if unpriced:
            facts["unpriced_positions"] = unpriced
        facts["total_value"] = None if value is None else round(value, 2)
        if value is not None and cost:
            facts["unrealised_pl_pct"] = round((value / cost - 1) * 100, 2)
        weights = tbl["weight"] if "weight" in tbl else None
        if weights is not None:
            facts["top_weights"] = [
                {
                    "ticker": str(t),
                    "weight_pct": _pct(w),
                    "pl_pct": _pct(tbl.at[t, "pnl_pct"]) if "pnl_pct" in tbl else None,
                }
                for t, w in weights.dropna().nlargest(WEIGHTS_SHOWN).items()
            ]
        if "day_pct" in tbl:
            moves = tbl["day_pct"].dropna()
            ranked = moves.reindex(moves.abs().sort_values(ascending=False).index)
            facts["movers"] = [
                {
                    "ticker": str(t),
                    "pct": _pct(v),
                    "weight_pct": (
                        _pct(tbl.at[t, "weight"]) if weights is not None else None
                    ),
                    # The session the move is from — off-hours it is the last
                    # completed one, which is a different day from `date` and
                    # the reason this key exists at all.
                    "as_of": _asof(tbl, t),
                }
                for t, v in ranked.head(MOVERS_SHOWN).items()
            ]

    if day:
        facts["day"] = {"amount": round(day[0], 2), "pct": _pct(day[1])}
    elif hist is not None and not hist.empty:
        chg = basket_change(hist, 1)
        if chg:
            facts["day"] = {"amount": round(chg[0], 2), "pct": _pct(chg[1])}
    session = _session(facts)
    if session:
        facts["session"] = session
        if "day" in facts:
            facts["day"]["as_of"] = session["date"]
    if money is not None or (hist is not None and not hist.empty):
        for label, days in (("week", 7), ("month", 30)):
            chg = (
                money_change(money, days)
                if money is not None
                else basket_change(hist, days) if hist is not None
                else None
            )
            if chg:
                facts[label] = {"amount": round(chg[0], 2), "pct": _pct(chg[1])}

    soon = [
        e for e in earnings
        if getattr(e, "date", None)
        and e.days_until is not None
        and 0 <= e.days_until <= EARNINGS_DAYS
    ]
    if soon:
        facts["earnings_soon"] = [
            {"ticker": e.ticker, "date": e.date.isoformat(), "in_days": e.days_until}
            for e in sorted(soon, key=lambda e: e.days_until)
        ]
    if extremes:
        facts["at_52w"] = [
            {"ticker": t, "kind": kind, "distance_pct": _pct(pct)}
            for t, _price, kind, pct in extremes
        ]
    return facts
