"""The investor's own plan — the lines they drew, which the app measures against.

The investor profile (`web.auth.load_profile`) says who the reader is: four
enums and a note, read by the assistant as a sentence. It sets no number, so
every threshold the app acted on was its own: a 30% name is "concentrated" on
the daily card, a 15% one is trimmed on Review, the same for somebody who
holds six companies on purpose and somebody who meant to own an index. The
plan is where the reader writes those numbers down:

  - **mix**: what share of the book each kind of asset is meant to be
    (`BUCKETS`), and how far it may drift before it is worth a look
    (`band_pp`, percentage points either side).
  - **limits**: the most one position, one sector and the speculative names
    together may weigh. They replace the app's own lines on Review and on the
    daily card; one left blank keeps the app's.
  - **contribution**: the money the reader adds on a schedule, which is what
    Review's "if you add money" list is sized to.
  - **reserve**: the band the cash-like part of the book is kept in.
  - **cash**: what the reader says they hold outside any position. The app
    does not see a broker's cash balance or a bank account (importers skip
    cash movements), only the money-market funds, so the reader states it:
    `investable` is money meant for the book — a broker's idle balance, a
    savings account paying `rate_pct` — and counts in the cash bucket and
    the reserve, and Review spends it; `cushion` is the emergency fund, which
    is never invested and so never counted, and only tells the drafting rule
    (`suggest`) whether the book has to keep cash of its own. Both carry the
    day they were stated (`as_of`), since they go stale as nothing in the
    ledger moves them (`cash_stale`). Neither enters a return or the book's
    value: they are the plan's, not the ledger's.

Every block is optional and the plan is stored as the reader wrote it,
percentages as percentages (`*_pct`, 0-100), under prefs["investor_plan"].
Pure: weights and a kind lookup in, readings out. Nothing here fetches.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from stocks.data import asset_kind as kinds

PREFS_KEY = "investor_plan"

STOCKS = "stocks"
EQUITY_FUNDS = "equity_funds"
BONDS = "bonds"
CASH = "cash"
CRYPTO = "crypto"
# The order the form draws them in: from what moves most with the market's
# fortunes to what moves least, crypto last as the one apart.
BUCKETS = (STOCKS, EQUITY_FUNDS, BONDS, CASH, CRYPTO)

# A closed-end fund trades like the shares it is; an index is never held. A
# symbol the kind lookup could not place is a share, which is the lookup's own
# default (`asset_kind.classify`).
_BUCKET_OF = {
    kinds.STOCK: STOCKS,
    kinds.CLOSED_END: STOCKS,
    kinds.EQUITY_FUND: EQUITY_FUNDS,
    kinds.BOND_FUND: BONDS,
    kinds.MONEY_MARKET: CASH,
    kinds.CRYPTO: CRYPTO,
}

EVERY = ("monthly", "quarterly")
_MONTHS = {"monthly": 1, "quarterly": 3}

# How far a bucket may sit from its target before it is a drift, when the
# reader set targets but no band. Five points is a rebalancing band most
# written plans use; under it a month's market move trips it.
DEFAULT_BAND_PP = 5.0
# The targets have to add up to the whole book; this much slack absorbs a
# form's rounding (three buckets at 33.3).
MIX_SLACK_PP = 0.5
# The last day a schedule can name: every month has a 28th.
LAST_DAY = 28
# After this many days a stated cash figure is asked for again: nothing in the
# ledger moves it, so two months of salary in or spending out leave it wrong.
CASH_STALE_DAYS = 60
# The most an account's stated interest can be, a year: over it is a typo.
MAX_RATE_PCT = 20.0


@dataclass(frozen=True)
class Mix:
    targets: dict[str, float]  # bucket -> percent of the book
    band_pp: float = DEFAULT_BAND_PP


@dataclass(frozen=True)
class Limits:
    max_position_pct: float | None = None
    max_sector_pct: float | None = None
    max_speculative_pct: float | None = None


@dataclass(frozen=True)
class Contribution:
    amount: float
    every: str = "monthly"
    day: int = 1


@dataclass(frozen=True)
class Reserve:
    min_pct: float | None = None
    max_pct: float | None = None


@dataclass(frozen=True)
class Cash:
    """Money the reader holds outside any position, in the reporting
    currency, as they last stated it (`as_of`, ISO)."""

    investable: float | None = None
    cushion: float | None = None
    rate_pct: float | None = None
    as_of: str | None = None


@dataclass(frozen=True)
class Plan:
    mix: Mix | None = None
    limits: Limits = field(default_factory=Limits)
    contribution: Contribution | None = None
    reserve: Reserve | None = None
    cash: Cash | None = None
    set: bool = False

    @property
    def empty(self) -> bool:
        """True when the plan draws no line at all — the app's own stand."""
        return (
            self.mix is None
            and self.limits == Limits()
            and self.contribution is None
            and self.reserve is None
            and self.cash is None
        )

    @property
    def investable(self) -> float:
        """The stated money meant for the book, 0 when none was stated."""
        return (self.cash.investable or 0.0) if self.cash else 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Drift:
    """A bucket outside its band: `actual_pct` against `target_pct`."""

    bucket: str
    actual_pct: float
    target_pct: float
    band_pp: float

    @property
    def gap_pp(self) -> float:
        return round(self.actual_pct - self.target_pct, 1)

    @property
    def side(self) -> Literal["over", "under"]:
        return "over" if self.gap_pp > 0 else "under"


# ------------------------------------------------------------------ reading


def _pct(value) -> float | None:
    """A stored percentage, or None for anything that is not one."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x < 0 or x > 100:
        return None
    return x


def _mix(raw) -> Mix | None:
    if not isinstance(raw, Mapping):
        return None
    targets = {
        b: p
        for b in BUCKETS
        if (p := _pct((raw.get("targets") or {}).get(b))) is not None
    }
    if not targets or abs(sum(targets.values()) - 100) > MIX_SLACK_PP:
        return None
    band = _pct(raw.get("band_pp"))
    return Mix(
        {b: targets.get(b, 0.0) for b in BUCKETS}, band if band else DEFAULT_BAND_PP
    )


def _limits(raw) -> Limits:
    if not isinstance(raw, Mapping):
        return Limits()
    # Zero is "nothing at all", which no reader means for a cap on one name.
    return Limits(
        **{
            k: (p if p else None)
            for k in ("max_position_pct", "max_sector_pct", "max_speculative_pct")
            for p in [_pct(raw.get(k))]
        }
    )


def _contribution(raw) -> Contribution | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        amount = float(raw.get("amount") or 0)
        day = int(raw.get("day") or 1)
    except (TypeError, ValueError):
        return None
    every = raw.get("every") if raw.get("every") in EVERY else "monthly"
    if not math.isfinite(amount) or amount <= 0:
        return None
    return Contribution(amount, every, min(max(day, 1), LAST_DAY))


def _reserve(raw) -> Reserve | None:
    if not isinstance(raw, Mapping):
        return None
    lo, hi = _pct(raw.get("min_pct")), _pct(raw.get("max_pct"))
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None and lo > hi:
        return None
    return Reserve(lo, hi)


def _amount(value) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x >= 0 else None


def _cash(raw) -> Cash | None:
    if not isinstance(raw, Mapping):
        return None
    investable, cushion = _amount(raw.get("investable")), _amount(raw.get("cushion"))
    rate = _amount(raw.get("rate_pct"))
    if investable is None and cushion is None:
        return None
    as_of = raw.get("as_of")
    try:
        as_of = date.fromisoformat(str(as_of)).isoformat() if as_of else None
    except ValueError:
        as_of = None
    return Cash(
        investable,
        cushion,
        rate if rate is not None and rate <= MAX_RATE_PCT else None,
        as_of,
    )


def parse(raw) -> Plan:
    """The stored plan as the app reads it: a block that does not hold
    together (targets that do not add up, a reserve whose floor is over its
    ceiling) is left out rather than half-applied. The route refuses those on
    the way in; this guards against a file edited by hand."""
    if not isinstance(raw, Mapping):
        return Plan()
    return Plan(
        mix=_mix(raw.get("mix")),
        limits=_limits(raw.get("limits")),
        contribution=_contribution(raw.get("contribution")),
        reserve=_reserve(raw.get("reserve")),
        cash=_cash(raw.get("cash")),
        set=bool(raw.get("set")),
    )


def load(prefs: Mapping) -> Plan:
    return parse((prefs or {}).get(PREFS_KEY))


_BUCKET_EN = {
    STOCKS: "stocks",
    EQUITY_FUNDS: "equity funds",
    BONDS: "bonds",
    CASH: "cash (money-market funds and stated cash)",
    CRYPTO: "crypto",
}


def _said_pct(value: float) -> str:
    return f"{value:g}%"


def describe(plan: Plan) -> str:
    """The plan as the assistant is told it (`chat.engine.persona`), in
    English like the rest of that sentence; "" when it draws no line."""
    if plan.empty:
        return ""
    parts: list[str] = []
    if plan.mix:
        mix = ", ".join(
            f"{_BUCKET_EN[b]} {_said_pct(v)}" for b, v in plan.mix.targets.items() if v
        )
        parts.append(f"target mix {mix} (drift allowed ±{plan.mix.band_pp:g} points)")
    caps = [
        f"{_said_pct(v)} in {what}"
        for v, what in (
            (plan.limits.max_position_pct, "one position"),
            (plan.limits.max_sector_pct, "one sector"),
            (plan.limits.max_speculative_pct, "early-stage companies together"),
        )
        if v is not None
    ]
    if caps:
        parts.append("at most " + ", ".join(caps))
    if plan.contribution:
        c = plan.contribution
        parts.append(
            f"they add {c.amount:,.0f} in their reporting currency {c.every} "
            f"on day {c.day}"
        )
    if plan.reserve:
        low, high = plan.reserve.min_pct, plan.reserve.max_pct
        band = (
            f"{_said_pct(low or 0)}-{_said_pct(high)}"
            if high is not None
            else f"at least {_said_pct(low or 0)}"
        )
        parts.append(f"a cash reserve of {band} of the book")
    if plan.cash:
        c = plan.cash
        if c.investable:
            rate = f" earning {c.rate_pct:g}% a year" if c.rate_pct else ""
            parts.append(
                f"{c.investable:,.0f} of uninvested cash meant for the book{rate}"
            )
        if c.cushion is not None:
            parts.append(
                f"an emergency fund of {c.cushion:,.0f} kept apart, never to invest"
                if c.cushion
                else "no emergency fund outside the book"
            )
        if c.as_of:
            parts.append(f"cash figures as of {c.as_of}")
    return (
        "Their own plan: " + "; ".join(parts) + ". Weigh every suggestion against "
        "it and say when a move would break it. "
    )


# ---------------------------------------------------------------- measuring


def bucket_of(kind: str | None) -> str | None:
    """The plan's bucket for an asset kind; None for an index."""
    if kind == kinds.INDEX:
        return None
    return _BUCKET_OF.get(kind or kinds.STOCK, STOCKS)


def buckets(
    weights: Mapping[str, float], kind_of: Callable[[str], str | None]
) -> dict[str, float]:
    """Each bucket's share of the book, in percent, over the weights given.

    Weights are `value_weights` fractions; a NaN one (an unpriced row) is left
    out and the rest are read over what is left, so the buckets add to 100.
    """
    totals = dict.fromkeys(BUCKETS, 0.0)
    for ticker, w in weights.items():
        try:
            x = float(w)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(x) or x <= 0:
            continue
        if (b := bucket_of(kind_of(str(ticker)))) is not None:
            totals[b] += x
    whole = sum(totals.values())
    if not whole:
        return {}
    return {b: round(v / whole * 100, 1) for b, v in totals.items()}


def with_cash(
    shares: Mapping[str, float], book_value: float, investable: float
) -> dict[str, float]:
    """`shares` (percent of the book) re-read over the book plus the stated
    investable cash, which joins the cash bucket; `book_value` is what the
    shares are shares of. No positions and some cash is all cash; no cash
    leaves the shares as they were."""
    cash = investable if math.isfinite(investable) and investable > 0 else 0.0
    value = book_value if math.isfinite(book_value) and book_value > 0 else 0.0
    if not cash:
        return dict(shares)
    if not shares:
        return {b: (100.0 if b == CASH else 0.0) for b in BUCKETS}
    if not value:
        # Shares with no value to weigh the cash against: left as they are
        # rather than guessed.
        return dict(shares)
    whole = value + cash
    out = {b: float(shares.get(b, 0.0)) * value / whole for b in BUCKETS}
    out[CASH] += cash / whole * 100
    return {b: round(v, 1) for b, v in out.items()}


def cash_stale(plan: Plan, today: date) -> int | None:
    """Days since the stated cash was last updated, once past
    `CASH_STALE_DAYS`; None while fresh or when none was stated."""
    if plan.cash is None or not plan.cash.as_of:
        return None
    try:
        age = (today - date.fromisoformat(plan.cash.as_of)).days
    except ValueError:
        return None
    return age if age > CASH_STALE_DAYS else None


def stamp_cash(new: Mapping | None, old: Cash | None, today: date) -> dict | None:
    """The cash block to store: `new` as written, dated today when either
    amount differs from what was stored, else keeping the old date — a rate
    corrected is not a balance checked. None when no amount is stated."""
    if not new or (new.get("investable") is None and new.get("cushion") is None):
        return None
    out = {k: new.get(k) for k in ("investable", "cushion", "rate_pct")}
    same = old is not None and (old.investable, old.cushion) == (
        out["investable"],
        out["cushion"],
    )
    out["as_of"] = old.as_of if same and old.as_of else today.isoformat()
    return out


def drift(plan: Plan, shares: Mapping[str, float]) -> list[Drift]:
    """The buckets outside their band, the furthest first."""
    if plan.mix is None or not shares:
        return []
    out = [
        Drift(b, float(shares.get(b, 0.0)), t, plan.mix.band_pp)
        for b, t in plan.mix.targets.items()
        if abs(float(shares.get(b, 0.0)) - t) > plan.mix.band_pp
    ]
    return sorted(out, key=lambda d: (-abs(d.gap_pp), d.bucket))


def reserve_state(plan: Plan, shares: Mapping[str, float]) -> str | None:
    """ "low" / "high" when the cash bucket is outside the reserve, else None."""
    if plan.reserve is None or not shares:
        return None
    cash = float(shares.get(CASH, 0.0))
    if plan.reserve.min_pct is not None and cash < plan.reserve.min_pct:
        return "low"
    if plan.reserve.max_pct is not None and cash > plan.reserve.max_pct:
        return "high"
    return None


def over_position(plan: Plan, weights: Mapping[str, float]) -> list[tuple[str, float]]:
    """(ticker, percent) for each position past the plan's cap, heaviest first."""
    cap = plan.limits.max_position_pct
    if cap is None:
        return []
    out = []
    for ticker, w in weights.items():
        try:
            pct = float(w) * 100
        except (TypeError, ValueError):
            continue
        if math.isfinite(pct) and pct > cap:
            out.append((str(ticker), round(pct, 1)))
    return sorted(out, key=lambda r: (-r[1], r[0]))


def over_sector(plan: Plan, sectors: Mapping[str, float]) -> list[tuple[str, float]]:
    """(sector, percent) for each sector past the plan's cap; `sectors` are
    fractions of the book (`briefing.book_sectors`)."""
    cap = plan.limits.max_sector_pct
    if cap is None:
        return []
    out = [
        (str(s), round(float(w) * 100, 1))
        for s, w in sectors.items()
        if math.isfinite(float(w)) and float(w) * 100 > cap
    ]
    return sorted(out, key=lambda r: (-r[1], r[0]))


def _on(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def per_month(plan: Plan) -> float | None:
    """The contribution spread over the months it covers — a quarterly one
    is a third a month — or None without one. What a monthly simulation
    adds at each month's end (`/portfolio/projection`)."""
    c = plan.contribution
    return None if c is None else c.amount / _MONTHS[c.every]


def next_contribution(plan: Plan, today: date) -> date | None:
    """The next scheduled contribution on or after `today`.

    Quarterly runs on the first month of each quarter (Jan, Apr, Jul, Oct):
    a schedule nobody anchored has to start somewhere, and the calendar
    quarter is the one a bank's standing order follows.
    """
    c = plan.contribution
    if c is None:
        return None
    step = _MONTHS[c.every]
    year, month = today.year, today.month
    for _ in range(13):
        if (month - 1) % step == 0:
            when = _on(year, month, c.day)
            if when >= today:
                return when
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return None


# ------------------------------------------------------------------ drafting
# A first plan for a reader who asked the assistant to build one
# (`chat.plan_builder`). It turns the reader's own answers into numbers by a
# fixed rule, the same rule for everybody, and the reader edits the result
# before or after saving it. It sets buckets and caps, never names a security:
# `web.auth.FOCUS_EXAMPLES` explains why a list picked from someone's risk
# would be a recommendation, and this stays on the side of a calculator.

CUSHIONS = ("none", "short", "covered")
STYLES = ("funds", "mixed", "stocks")
CRYPTO_WISH = ("none", "some", "more")

# Share of the book in stocks and equity funds together, by stated risk...
_EQUITY = {"conservative": 35, "balanced": 60, "aggressive": 80, "very_aggressive": 95}
# ...and the most a horizon carries, whatever the risk: money needed within a
# year is not money to hold in shares, however steady the nerves.
_HORIZON_CAP = {"under_1y": 20, "1_3y": 45, "3_5y": 75, "5y_plus": 100}
# Cash kept inside the book when the reader has no emergency fund outside it
# ("none"), a thin one ("short") or a full one ("covered").
_CUSHION_CASH = {"none": 10, "short": 5, "covered": 0}
# Crypto carved out of the equity share, by wish and then by risk, and never
# more than a third of it.
_CRYPTO = {
    "none": (0, 0, 0, 0),
    "some": (1, 2, 5, 5),
    "more": (2, 5, 10, 15),
}
# Of the equity share, the part in single companies rather than funds.
_STOCK_SHARE = {"funds": 0.2, "mixed": 0.5, "stocks": 0.8}
# Caps per stated risk, conservative to very aggressive.
_POSITION = (8, 10, 15, 20)
_SECTOR = (30, 35, 40, 45)
_SPECULATIVE = (1, 3, 5, 10)
# The reserve band either side of the cash target.
_RESERVE_BAND = 5


@dataclass(frozen=True)
class Answers:
    """What the reader told the plan builder; None is "not asked"."""

    risk: str | None = None
    horizon: str | None = None
    cushion: str | None = None
    style: str | None = None
    crypto: str | None = None
    amount: float | None = None
    every: str | None = None
    investable: float | None = None


def _whole(parts: Mapping[str, float]) -> dict[str, float]:
    """`parts` rounded to whole points that still add up to 100: the floor of
    each, then the points left over to the largest remainders."""
    floors = {k: math.floor(v) for k, v in parts.items()}
    left = 100 - sum(floors.values())
    for k in sorted(parts, key=lambda k: parts[k] - floors[k], reverse=True)[:left]:
        floors[k] += 1
    return {k: float(v) for k, v in floors.items()}


def suggest(answers: Answers) -> dict:
    """A plan drawn from `answers`, in the shape `PUT /prefs/plan` takes.

    Equity is the stated risk's share, capped by the horizon and by the cash
    the cushion keeps in the book. Money due within three years holds cash
    first: half of what is not in equity under a year, ten points under three.
    The rest of the non-equity part is bonds. Crypto comes out of equity, and
    single companies take the style's share of what equity is left. The caps
    grow with risk, and the reserve is the cash target give or take five
    points. An unanswered risk or horizon reads as the profile's own default
    (`auth._PROFILE_DEFAULTS`), and unanswered style, cushion or crypto as
    the cautious end.
    """
    risk = answers.risk if answers.risk in _EQUITY else "balanced"
    horizon = answers.horizon if answers.horizon in _HORIZON_CAP else "5y_plus"
    cushion = answers.cushion if answers.cushion in _CUSHION_CASH else "none"
    style = answers.style if answers.style in _STOCK_SHARE else "funds"
    wish = answers.crypto if answers.crypto in _CRYPTO else "none"
    at = tuple(_EQUITY).index(risk)

    cash = float(_CUSHION_CASH[cushion])
    equity = float(min(_EQUITY[risk], _HORIZON_CAP[horizon], 100 - cash))
    rest = 100 - equity
    if horizon == "under_1y":
        cash = max(cash, rest / 2)
    elif horizon == "1_3y":
        cash = max(cash, min(10.0, rest))
    # Nor crypto for money due within the year, the one place its swings bite.
    crypto = 0.0 if horizon == "under_1y" else float(min(_CRYPTO[wish][at], equity / 3))
    shares = equity - crypto
    stocks = shares * _STOCK_SHARE[style]
    targets = _whole(
        {
            STOCKS: stocks,
            EQUITY_FUNDS: shares - stocks,
            BONDS: rest - cash,
            CASH: cash,
            CRYPTO: crypto,
        }
    )
    cash_pct = targets[CASH]
    out: dict = {
        "mix": {"targets": targets, "band_pp": DEFAULT_BAND_PP},
        "limits": {
            "max_position_pct": float(_POSITION[at]),
            "max_sector_pct": float(_SECTOR[at]),
            "max_speculative_pct": float(_SPECULATIVE[at]),
        },
        "contribution": None,
        "reserve": (
            {
                "min_pct": max(cash_pct - _RESERVE_BAND, 0.0),
                "max_pct": cash_pct + _RESERVE_BAND,
            }
            if cash_pct
            else None
        ),
    }
    if answers.amount and math.isfinite(answers.amount) and answers.amount > 0:
        out["contribution"] = {
            "amount": float(answers.amount),
            "every": answers.every if answers.every in EVERY else "monthly",
            "day": 1,
        }
    if (
        answers.investable is not None
        and math.isfinite(answers.investable)
        and answers.investable >= 0
    ):
        out["cash"] = {"investable": float(answers.investable)}
    return out
