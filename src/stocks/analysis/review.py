"""What to sell, trim, keep or add to — and which outside names earn a place.

The Review page's engine. Pure: it is handed each name's fundamentals, its
weight in the book and its share of the book's risk, and answers a verdict key
and the reason codes behind it. Fetching, pricing and the tax a sale would
cost are the route's (`stocks.api.routes.review`); nothing here touches the
network, so every threshold below is testable with a dict.

**Two scores, both 0-100, both from the KPIs the ticker page already shows.**

* *Quality* — is this a good business? Return on invested capital, the moat
  score, operating margin and free-cash-flow yield (the last only as "does it
  make cash at all", so its scale tops out at 4%). A mature name still growing
  20% or more a year adds the rule of 40 as a fifth: otherwise a grower that
  has just crossed into profit scores worse than it did losing money, and the
  pace that is most of its case counts for nothing.
* *Cheapness* — is the price asking little for it? Forward P/E, free-cash-flow
  yield and EV/EBITDA, each mapped linearly between a dear and a cheap end.
  The forward P/E reads as the better of itself and itself per point of
  sustained sales growth per share (a PEG on the app's own growth, net of
  dilution, never the feed's PEG): thirty times earnings is dear for a
  company growing 5% and cheap for one growing 40%, and a slow grower is not
  marked down for being slow.

A score needs two of its inputs or it is None: one KPI is an anecdote. A name
that cannot be scored is `unrated`, never "hold by default" dressed up as an
opinion — the reader is told the data is missing, not that the name is fine.

Growth, wherever it picks a lens or a reason, is the sustained pace: the
lower of the last quarter on a year before and the multi-year rate. One
quarter alone reads an oil major's price spike or a merger's first
consolidated quarter as a fast grower.

**Three stages, three lenses.** Profits are the wrong ruler for a company
that has not reached them yet, and using it anyway is how a clinical-stage
biotech with four years of cash reads as "quality 0, sell":

* *Mature* — the two scores above.
* *Growth* — sales growing 25% or more a year while the operating margin is
  still under 10%. Quality is the rule of 40 (growth plus free-cash-flow
  margin), gross margin and moat; cheapness is EV/sales per point of growth,
  the cash it burns against its price, and a forward P/E only once there is
  one. A forward loss is the stage, not the dear end of a multiple.
* *Early* — no sales to speak of (none, or a price over 40 times them) and
  cash going out; or sales, but an operating loss bigger than all of them
  (`deep_burn`) — a drug developer living on collaboration fees, a car maker
  losing more per car than it sells it for. There is nothing to score: the
  value is a product that does not sell yet (or not at a price that covers
  it), and whether it ever does turns on trials, approval and
  patents, which no ratio sees. Its verdict is `bet` — a position sized to be
  lost — with the cash runway as the one hard number, and above `SPEC_MAX` of
  the book it is cut back to it. A grower is added to `SPEC_MAX` too, not to
  a mature name's `ADD_TO`: its case still has to be executed.

Drug makers at any stage carry `patent_risk`: their earnings stand on
patents with an expiry date, which the filings' ratios do not price.

**Free cash flow is the owner's.** Share-based pay is taken off it again
(the feed adds it back as if it were free; at a software house it can be most
of the figure, and the row says `share_pay`). What is left, if it is still
over twice EBITDA, is someone else's money passing through — a lender's book,
a payments float, subscriptions paid ahead — and is left out (`fcf_float`).

**Data the scores refuse.** `compute_metrics` converts an ADR's statements
into its quote currency; where no rate exists, or the feed is broken anyway,
it shows up as a free-cash-flow yield above 25% or a negative enterprise
value. Those inputs are dropped and the row carries `data_suspect`, because a
screen that ranks a broken number first is worse than one that ranks nothing.
A yield over 25% that the forward P/E backs (no more than twice the earnings
yield, under 50%) is a real price, not a currency mix: a name the market has
given up on can trade at five times earnings and yield 30% in cash.

**What stops an add or a buy.** Two good scores are not enough when the
numbers behind them are the kind that lie: a margin at a cyclical peak (well
above its own median over the filed years, at a company whose sales have
fallen in one of them, and without the fast growth that would make it
operating leverage), sales falling now and over the years or a
margin sliding for years (the value trap: cheap because it is shrinking),
earnings the analysts expect to fall 10% or more next year (a forward P/E
above the trailing one: the low multiple is on a profit about to shrink),
net debt at three times EBITDA or more, or a price that is cheap only on
its kindest reading (the mean clears the bar, the other inputs without the
best one do not: a range, not a point, has to be cheap). Each holds the name
at hold or watch and says why; none of them ever pushes a name into an add.

**Sizing reads the whole book.** Where a concentration starts depends on
how many companies there are (`concentration_line`): 15% in a wide book,
more in a narrow one, and nothing at all under three — a book of two is
told it is narrow, not to sell 80% of itself. A cut aims at an even share,
and only halfway there for a good business at a good price. What the sales
free is then spread over the names worth adding to (`redeploy`) before any
of it is left as cash — never into a sector already carrying
`SECTOR_LINE` of the book, which the page names instead. A concentration
cut that would cost a tenth of the sale in tax is taken in two steps
(`stage_for_tax`): half now, half in another tax year.

**Verdicts are keys.** The client translates them, the same way the sector
page's regime travels as a band key. Held names: sell, trim, hold, add, plus
`core` (a fund held as the book's base) and `cash` (a money-market line).
Outside names: buy, watch, pass. Either side: bet, unrated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

# Held
SELL = "sell"
TRIM = "trim"
HOLD = "hold"
ADD = "add"
CORE = "core"
CASH = "cash"
# Outside the book
BUY = "buy"
WATCH = "watch"
PASS = "pass"
# Either
BET = "bet"
UNRATED = "unrated"

#: How the page orders held rows: the actions first, the quiet ones last.
HELD_ORDER = (SELL, TRIM, ADD, HOLD, BET, CORE, CASH, UNRATED)
CANDIDATE_ORDER = (BUY, WATCH, BET, PASS, UNRATED)

# Stages (see the module docstring).
MATURE = "mature"
GROWTH = "growth"
EARLY = "early"

# Where a reinforced name is taken to, and where a trimmed one is cut back to
# (a share of its current weight). One position at 5% is a conviction that
# still cannot sink the book; halving a weak, heavy name halves the damage
# without betting the other way.
ADD_TO = 0.05
TRIM_KEEPS = 0.5
# Above this weight a single company is a concentration, whatever its quality.
CONCENTRATED = 0.15
CONCENTRATED_TO = 0.10
# The line scales with how many companies the book holds: four cannot all sit
# under 15%, and cutting all four to cash protects nothing. `SPREAD` over the
# count, never under `CONCENTRATED` nor over `CONCENTRATED_MAX`; a cut aims at
# an even share (`1 / names`, never under `CONCENTRATED_TO`).
SPREAD = 1.5
CONCENTRATED_MAX = 0.35
# Under this many companies concentration is the book's shape, not one
# position's fault: nothing is trimmed for it, and where the companies are
# most of the book (`FEW_NAMES_SHARE`) the page says so instead.
FEW_NAMES = 3
FEW_NAMES_SHARE = 0.5
# One sector this much of the book is named on the page, and nothing the
# sales free is spread into it. Two companies at least: one alone is a
# concentration, which has its own line.
SECTOR_LINE = 0.40
# Coins this much of the book are named too: there is nothing to score, so
# it is a note, never a cut.
CRYPTO_LINE = 0.25
# A concentration cut whose tax is this much of what the sale raises is
# taken in two steps: half now, the rest in another tax year.
TAX_STAGE = 0.10
# A weak name this heavy, or this much of the book's risk, is cut back.
HEAVY = 0.06
RISKY = 0.10
# Below this a position cannot move the book even if it doubles.
SMALL = 0.005
# The most of the book a bet on an unsold product should be: a total loss
# costs three points, which a year of the rest of the book can make back.
SPEC_MAX = 0.03
# Sales growth that makes a loss a stage rather than a verdict, and the
# operating margin under which a grower is still judged as one.
GROWTH_MIN = 0.25
GROWTH_MARGIN = 0.10
# Market cap over sales above which the sales are not what is being priced.
PRE_REVENUE_PS = 40.0
# An operating margin this low (losing more than the sales) with cash going
# out is an early-stage bet whatever the sales are.
DEEP_BURN_MARGIN = -1.0
# Sustained growth from which a mature name's quality counts the rule of 40.
RULE_40_MIN = 0.20
# Forward P/E per point of sustained sales growth per share: 0.5x scores 100,
# 2.5x scores 0, so 1x (the ticker page's "cheap" band) reads 75 and 1.5x sits
# on the cheap bar. Growth past `PEG_GROWTH_CAP` is a cycle or a base effect,
# not a pace to pay for; at or under `PEG_CHEAP` the row says it is cheap for
# its growth.
PEG_LO = 0.5
PEG_HI = 2.5
PEG_GROWTH_CAP = 0.40
PEG_CHEAP = 1.0
# An operating margin this many times its own median over the filed years,
# and at least `PEAK_GAP` above it, is a peak at a company whose sales fell in
# one of those years, unless they now grow `RULE_40_MIN`. Without a down year
# a widening margin is a compounder's operating leverage, not a cycle.
PEAK_RATIO = 1.5
PEAK_GAP = 0.05
# A margin down this much since the first filed year, and by this share of
# its median, has been sliding: the business is losing its pricing.
MARGIN_SLIDE = 0.05
MARGIN_SLIDE_SHARE = 0.25
# Net debt over EBITDA from which a cheap price may be the lenders' claim.
HIGH_DEBT = 3.0
# The analysts' next-year earnings this far under the last twelve months'
# (a forward P/E that much above the trailing one): the low P/E is on a
# profit already expected to shrink.
EARNINGS_DROP = 0.10
# Years of cash at the current burn: under the first, a raise (and the
# dilution with it) is close; over the second, the company can wait.
RUNWAY_SHORT = 1.5
RUNWAY_LONG = 3.0
# Free cash flow (net of share-based pay) this many times EBITDA is not what
# the business earns: a lender's book, a payments float or subscriptions
# paid ahead passing through.
FCF_FLOAT = 2.0
# An FCF yield over `FCF_SANE` is a broken feed unless the forward P/E backs
# it: at most `FCF_BACKED` times the earnings yield, and never over `FCF_MAX`.
FCF_SANE = 0.25
FCF_BACKED = 2.0
FCF_MAX = 0.50
# Share-based pay this share of FCF is named: the yield is scored without it.
SHARE_PAY = 0.5

# Score bands.
GOOD = 60.0
WEAK = 45.0
POOR = 40.0
CHEAP = 50.0

#: The metric keys a row carries back to the client, in display order.
SHOWN = (
    "pe_fwd",
    "growth_pe",
    "fcf_yield",
    "owner_fcf_yield",
    "ev_ebitda",
    "roic",
    "op_margin",
    "moat",
    "revenue_cagr",
    "share_dilution",
    "net_debt_ebitda",
    "ev_sales",
    "revenue_growth",
    "fcf_margin",
    "runway_years",
)

#: Industries (Yahoo's names) whose earnings stand on patents and trials.
PHARMA = frozenset(
    {
        "Biotechnology",
        "Drug Manufacturers - General",
        "Drug Manufacturers - Specialty & Generic",
    }
)

# Reason codes. The client has a sentence for each (`review.reason_<code>`).
R_QUALITY = "quality"  # quality score high
R_LOW_QUALITY = "low_quality"
R_CHEAP = "cheap"
R_EXPENSIVE = "expensive"
R_HIGH_ROIC = "high_roic"
R_LOW_ROIC = "low_roic"
R_WIDE_MOAT = "wide_moat"
R_NO_MOAT = "no_moat"
R_NEGATIVE_FCF = "negative_fcf"
R_LOSS = "loss_making"
R_BUYBACKS = "buybacks"
R_DILUTION = "dilution"
R_DEBT = "high_debt"
R_SHRINKING = "shrinking"
R_GROWTH = "growth"
R_CONCENTRATED = "concentrated"
R_HEAVY = "heavy"
R_RISKY = "risk_heavy"
R_UNDERWEIGHT = "underweight"
R_SMALL = "small"
R_SUSPECT = "data_suspect"
R_NO_DATA = "no_data"
R_FUND = "fund"
R_CASH = "money_market"
R_CRYPTO = "crypto"
R_PRE_REVENUE = "pre_revenue"
R_DEEP_BURN = "deep_burn"
R_TRIAL_RISK = "trial_risk"
R_PATENT_RISK = "patent_risk"
R_GROWTH_STAGE = "growth_stage"
R_RULE_40 = "rule_of_40"
R_SHORT_RUNWAY = "short_runway"
R_LONG_RUNWAY = "long_runway"
R_BET_HEAVY = "bet_heavy"
R_FCF_FLOAT = "fcf_float"
R_SHARE_PAY = "share_pay"
R_CHEAP_FOR_GROWTH = "cheap_for_growth"
R_PEAK_MARGIN = "peak_margin"
R_SALES_FALLING = "sales_falling"
R_MARGIN_FALLING = "margin_falling"
R_EARNINGS_FALLING = "earnings_falling"
R_ONE_READING = "cheap_on_one_reading"
R_FEW_NAMES = "few_names"
R_REDEPLOY = "redeploy"
R_TAX_STAGED = "tax_staged"
R_SECTOR_FULL = "sector_full"

# Book-level notes (`review.note_<code>`).
N_FEW_NAMES = "few_names"
N_SECTOR_HEAVY = "sector_heavy"
N_CRYPTO_HEAVY = "crypto_heavy"
N_TAX_OFFSET = "tax_offset"

# Reasons that read a loss as a fault; in the growth and early stages it is
# the stage itself, and the row says so once instead.
_PROFIT_REASONS = frozenset({R_LOSS, R_LOW_ROIC, R_HIGH_ROIC})


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def _lin(value: float, lo: float, hi: float) -> float:
    """`lo` maps to 0 and `hi` to 100, clamped either side."""
    return _clamp(100.0 * (value - lo) / (hi - lo))


def _fcf_yield(metrics: Mapping) -> float | None:
    """FCF yield net of share-based pay, where the feed gave the pay."""
    if "owner_fcf_yield" in metrics:
        return _num(metrics, "owner_fcf_yield")
    return _num(metrics, "fcf_yield")


def _num(metrics: Mapping, key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def _mean(parts: list[float]) -> float | None:
    return sum(parts) / len(parts) if len(parts) >= 2 else None


def _without_best(parts: list[float]) -> float | None:
    """The mean once the kindest input is left out: the price a sceptic reads."""
    if len(parts) < 2:
        return None
    rest = sorted(parts)[:-1]
    return sum(rest) / len(rest)


@dataclass(frozen=True)
class Scores:
    quality: float | None
    cheapness: float | None
    suspect: bool = False
    stage: str = MATURE
    #: Free cash flow left out because it is a float, not earnings.
    fcf_float: bool = False
    #: Cheapness without its kindest input (see `_without_best`).
    price_floor: float | None = None

    @property
    def total(self) -> float | None:
        if self.quality is None or self.cheapness is None:
            return None
        return (self.quality + self.cheapness) / 2


def growth_of(metrics: Mapping) -> float | None:
    """Sales growth now: last quarter on a year before, else the long CAGR."""
    recent = _num(metrics, "revenue_growth")
    return recent if recent is not None else _num(metrics, "revenue_cagr")


def sustained_growth(metrics: Mapping) -> float | None:
    """The pace that decides a lens or a reason: the lower of the last quarter
    and the multi-year rate, so one spiky quarter is not a grower."""
    recent = _num(metrics, "revenue_growth")
    long_run = _num(metrics, "revenue_cagr")
    if recent is not None and long_run is not None:
        return min(recent, long_run)
    return recent if recent is not None else long_run


def per_share_growth(metrics: Mapping) -> float | None:
    """Sustained sales growth per share: what a holder's slice grows by once
    new shares (or buybacks) have diluted (or concentrated) it."""
    growth = sustained_growth(metrics)
    if growth is None:
        return None
    dilution = _num(metrics, "share_dilution")
    if dilution is None or dilution <= -1:
        return growth
    return (1 + growth) / (1 + dilution) - 1


def growth_pe(metrics: Mapping) -> float | None:
    """Forward P/E per point of sustained per-share sales growth; None
    without a positive P/E or positive growth."""
    pe = _num(metrics, "pe_fwd")
    growth = per_share_growth(metrics)
    if pe is None or pe <= 0 or growth is None or growth <= 0:
        return None
    return pe / (min(growth, PEG_GROWTH_CAP) * 100)


def _unsold(metrics: Mapping) -> bool:
    """No sales to speak of: none, or a price over `PRE_REVENUE_PS` times them."""
    revenue = _num(metrics, "revenue")
    cap = _num(metrics, "market_cap")
    return revenue is not None and (
        revenue <= 0 or (cap is not None and cap / revenue >= PRE_REVENUE_PS)
    )


def _deep_burn(metrics: Mapping) -> bool:
    """Sales, but an operating loss larger than them, and cash going out."""
    fcf = _num(metrics, "fcf")
    margin = _num(metrics, "op_margin")
    return (
        fcf is not None and fcf < 0 and margin is not None and margin <= DEEP_BURN_MARGIN
    )


def stage(metrics: Mapping) -> str:
    """Mature, growth or early: which lens judges this business."""
    fcf = _num(metrics, "fcf")
    burning = fcf is not None and fcf < 0
    if (burning and _unsold(metrics)) or _deep_burn(metrics):
        return EARLY
    growth = sustained_growth(metrics)
    margin = _num(metrics, "op_margin")
    if (
        growth is not None
        and growth >= GROWTH_MIN
        and margin is not None
        and margin < GROWTH_MARGIN
    ):
        return GROWTH
    return MATURE


def score(metrics: Mapping) -> Scores:
    """Quality and cheapness, 0-100, off `compute_metrics` output."""
    phase = stage(metrics)
    if phase == EARLY:
        return Scores(None, None, stage=EARLY)
    roic = _num(metrics, "roic")
    moat = _num(metrics, "moat")
    margin = _num(metrics, "op_margin")
    fcf = _fcf_yield(metrics)
    pe = _num(metrics, "pe_fwd")
    ev = _num(metrics, "ev")
    ev_ebitda = _num(metrics, "ev_ebitda")

    fcf_ebitda = _num(metrics, "fcf_ebitda")
    floated = fcf is not None and fcf_ebitda is not None and fcf_ebitda > FCF_FLOAT
    if floated:
        # Real money, but not the business's: it says nothing about quality
        # or price, and left in it reads a lender as the cheapest name here.
        fcf = None
    suspect = _fcf_broken(fcf, pe) or (ev is not None and ev <= 0)
    if suspect:
        # Which of the two is broken is not knowable from here; both lean on
        # the enterprise value or the cash flow the mixed currency corrupts.
        fcf = None
        ev_ebitda = None

    if phase == GROWTH:
        return _growth_scores(metrics, fcf, pe, suspect, floated)

    quality = [
        _lin(v, lo, hi)
        for v, lo, hi in ((roic, 0.0, 0.40), (margin, 0.0, 0.40), (fcf, -0.02, 0.04))
        if v is not None
    ]
    if moat is not None:
        quality.append(_clamp(moat))
    rule_40 = _rule_40(metrics, floated)
    if quality and rule_40 is not None:
        quality.append(_lin(rule_40, 0.0, 0.60))

    cheap: list[float] = []
    if pe is not None:
        # A forward loss has no multiple; it is the dear end, not a missing one.
        pe_score = _lin(-pe, -40.0, -8.0) if pe > 0 else 0.0
        peg = growth_pe(metrics)
        if peg is not None:
            pe_score = max(pe_score, _lin(-peg, -PEG_HI, -PEG_LO))
        cheap.append(pe_score)
    if fcf is not None:
        cheap.append(_lin(fcf, 0.0, 0.10))
    if ev_ebitda is not None and ev_ebitda > 0:
        cheap.append(_lin(-ev_ebitda, -50.0, -8.0))
    pb = _num(metrics, "pb")
    if floated and pb is not None and pb > 0:
        # A lender is priced on its book once its cash flow says nothing.
        cheap.append(_lin(-pb, -4.0, -1.0))

    return Scores(
        quality=_mean(quality),
        cheapness=_mean(cheap),
        suspect=suspect,
        fcf_float=floated,
        price_floor=_without_best(cheap),
    )


def _fcf_broken(fcf: float | None, pe: float | None) -> bool:
    """An FCF yield too high to be a price, unless the forward P/E — analysts'
    earnings in the quote's own currency, not the converted statements — says
    the market really is paying that little."""
    if fcf is None or fcf <= FCF_SANE:
        return False
    backed = pe is not None and pe > 0 and fcf <= FCF_BACKED / pe
    return fcf > FCF_MAX or not backed


def _rule_40(metrics: Mapping, floated: bool) -> float | None:
    """Sustained growth plus FCF margin, for a mature name still growing
    `RULE_40_MIN` or more; None otherwise."""
    growth = sustained_growth(metrics)
    margin = None if floated else _num(metrics, "fcf_margin")
    if growth is None or growth < RULE_40_MIN or margin is None:
        return None
    return min(growth, 1.0) + margin


def _growth_scores(
    metrics: Mapping, fcf: float | None, pe: float | None, suspect: bool, floated: bool
) -> Scores:
    """The growth lens: how good the growth is, and what is paid per point."""
    # Past 100% a year the number is a base effect more than a pace.
    growth = min(growth_of(metrics) or 0.0, 1.0)
    fcf_margin = None if floated else _num(metrics, "fcf_margin")
    gross = _num(metrics, "gross_margin")
    moat = _num(metrics, "moat")
    ev_sales = None if suspect else _num(metrics, "ev_sales")

    quality: list[float] = []
    if fcf_margin is not None:
        quality.append(_lin(growth + fcf_margin, 0.0, 0.60))
    if gross is not None:
        quality.append(_lin(gross, 0.20, 0.80))
    if moat is not None:
        quality.append(_clamp(moat))

    cheap: list[float] = []
    if ev_sales is not None and ev_sales > 0 and growth > 0:
        # EV/sales per point of growth: 0.1x a point is cheap, 0.6x dear.
        cheap.append(_lin(-ev_sales / (growth * 100), -0.6, -0.1))
    if fcf is not None:
        # What the burn costs against the price: -5% a year is the dear end.
        cheap.append(_lin(fcf, -0.05, 0.05))
    if pe is not None and pe > 0:
        cheap.append(_lin(-pe, -40.0, -8.0))

    return Scores(
        quality=_mean(quality),
        cheapness=_mean(cheap),
        suspect=suspect,
        stage=GROWTH,
        fcf_float=floated,
        price_floor=_without_best(cheap),
    )


def _cautions(metrics: Mapping, s: Scores) -> list[str]:
    """Why two good scores still do not make an add or a buy (see the module
    docstring): the reasons the numbers behind them may not hold."""
    out: list[str] = []
    margin = _num(metrics, "op_margin")
    median = _num(metrics, "op_margin_median")
    change = _num(metrics, "op_margin_change")
    growth = sustained_growth(metrics)
    if s.stage == MATURE:
        if (
            margin is not None
            and median is not None
            and margin - median >= PEAK_GAP
            and (median <= 0 or margin >= PEAK_RATIO * median)
            and (_num(metrics, "revenue_down_years") or 0) >= 1
            and (growth is None or growth < RULE_40_MIN)
        ):
            out.append(R_PEAK_MARGIN)
        paces = [
            g
            for g in (_num(metrics, "revenue_growth"), _num(metrics, "revenue_cagr"))
            if g is not None
        ]
        if paces and max(paces) < 0:
            out.append(R_SALES_FALLING)
        if (
            change is not None
            and median is not None
            and median > 0
            and change <= -MARGIN_SLIDE
            and -change >= MARGIN_SLIDE_SHARE * median
        ):
            out.append(R_MARGIN_FALLING)
    trailing = _num(metrics, "pe_ttm")
    forward = _num(metrics, "pe_fwd")
    if (
        trailing is not None
        and forward is not None
        and 0 < trailing <= forward * (1 - EARNINGS_DROP)
    ):
        out.append(R_EARNINGS_FALLING)
    debt = _num(metrics, "net_debt_ebitda")
    if debt is not None and debt >= HIGH_DEBT and not s.fcf_float:
        out.append(R_DEBT)
    if (
        s.cheapness is not None
        and s.cheapness >= CHEAP
        and s.price_floor is not None
        and s.price_floor < CHEAP
    ):
        out.append(R_ONE_READING)
    return out


def _business_reasons(metrics: Mapping, s: Scores) -> list[str]:
    """What about the company itself speaks for or against it, strongest first."""
    out: list[str] = []
    roic = _num(metrics, "roic")
    moat = _num(metrics, "moat")
    # The cash actually leaving, not the owner's view: pay in shares is
    # `share_pay`, not a business that consumes cash.
    fcf = None if s.suspect else _num(metrics, "fcf_yield")
    pe = _num(metrics, "pe_fwd")
    dilution = _num(metrics, "share_dilution")
    debt = _num(metrics, "net_debt_ebitda")
    growth = sustained_growth(metrics)
    earnings = _num(metrics, "net_income_cagr")

    if s.quality is not None:
        if s.quality >= GOOD:
            out.append(R_QUALITY)
        elif s.quality < WEAK:
            out.append(R_LOW_QUALITY)
    if s.cheapness is not None:
        if s.cheapness >= CHEAP:
            out.append(R_CHEAP)
        elif s.cheapness < 30:
            out.append(R_EXPENSIVE)
    if pe is not None and pe <= 0:
        out.append(R_LOSS)
    if roic is not None:
        if roic >= 0.25:
            out.append(R_HIGH_ROIC)
        elif roic < 0.08:
            out.append(R_LOW_ROIC)
    if moat is not None:
        if moat >= 70:
            out.append(R_WIDE_MOAT)
        elif moat < 45:
            out.append(R_NO_MOAT)
    if fcf is not None and fcf < 0:
        out.append(R_NEGATIVE_FCF)
    if dilution is not None:
        if dilution <= -0.02:
            out.append(R_BUYBACKS)
        elif dilution >= 0.03:
            out.append(R_DILUTION)
    share_pay = _num(metrics, "sbc_fcf")
    if share_pay is not None and share_pay >= SHARE_PAY:
        out.append(R_SHARE_PAY)
    if debt is not None and debt >= HIGH_DEBT:
        out.append(R_DEBT)
    out.extend(r for r in _cautions(metrics, s) if r not in out)
    if earnings is not None and earnings <= -0.05:
        out.append(R_SHRINKING)
    elif growth is not None and growth >= 0.20:
        out.append(R_GROWTH)
    if s.suspect:
        out.append(R_SUSPECT)
    if s.fcf_float:
        out.append(R_FCF_FLOAT)
    if s.stage != MATURE:
        out = [r for r in out if r not in _PROFIT_REASONS]
    if s.stage == GROWTH:
        out.insert(0, R_GROWTH_STAGE)
        margin = _num(metrics, "fcf_margin")
        g = growth_of(metrics)
        if not s.fcf_float and margin is not None and g is not None:
            if g + margin >= 0.40:
                out.append(R_RULE_40)
    elif s.stage == MATURE:
        rule_40 = _rule_40(metrics, s.fcf_float)
        if rule_40 is not None and rule_40 >= 0.40:
            out.append(R_RULE_40)
        peg = growth_pe(metrics)
        if peg is not None and peg <= PEG_CHEAP:
            out.append(R_CHEAP_FOR_GROWTH)
    # A long runway only matters to a company that needs one; a short one
    # matters to any company burning cash.
    out.extend(
        r for r in _runway_reasons(metrics) if r != R_LONG_RUNWAY or s.stage != MATURE
    )
    if metrics.get("industry") in PHARMA and s.stage != EARLY:
        out.append(R_PATENT_RISK)
    return out


def _runway_reasons(metrics: Mapping) -> list[str]:
    runway = _num(metrics, "runway_years")
    if runway is None:
        return []
    if runway < RUNWAY_SHORT:
        return [R_SHORT_RUNWAY]
    if runway >= RUNWAY_LONG:
        return [R_LONG_RUNWAY]
    return []


def _early_reasons(metrics: Mapping) -> list[str]:
    """Why an early name is a bet: no sales, what it hangs on, its cash."""
    out = [R_PRE_REVENUE if _unsold(metrics) else R_DEEP_BURN]
    if metrics.get("industry") in PHARMA:
        out.append(R_TRIAL_RISK)
    out.extend(_runway_reasons(metrics))
    dilution = _num(metrics, "share_dilution")
    if dilution is not None and dilution >= 0.03:
        out.append(R_DILUTION)
    return out


@dataclass(frozen=True)
class Verdict:
    verdict: str
    reasons: tuple[str, ...] = ()
    quality: float | None = None
    cheapness: float | None = None
    #: The weight this verdict takes a held name to; None for outside names
    #: and for verdicts that move nothing.
    target: float | None = None
    metrics: dict[str, float | None] = field(default_factory=dict)
    #: For a held name good and cheap enough to add to: the weight money a
    #: sale frees elsewhere may take it to (`redeploy`); None otherwise.
    fill: float | None = None


@dataclass(frozen=True)
class Note:
    """One thing the page says about the book as a whole (`review.note_<key>`)."""

    key: str
    count: int | None = None
    sector: str | None = None
    weight: float | None = None
    #: Money, in the tax jurisdiction's currency (`tax_offset`'s saving).
    amount: float | None = None
    tickers: tuple[str, ...] = ()
    #: ISO day a repurchase no longer undoes the loss, where a window applies.
    day: str | None = None


def _shown(metrics: Mapping | None) -> dict[str, float | None]:
    metrics = metrics or {}
    derived = {"growth_pe": growth_pe(metrics)}
    return {key: derived[key] if key in derived else _num(metrics, key) for key in SHOWN}


def _kind_verdict(kind: str | None, held: bool) -> Verdict | None:
    """Funds, cash and coins have no fundamentals to judge: a verdict by kind."""
    if kind == "money_market":
        return Verdict(CASH if held else UNRATED, (R_CASH,))
    if kind in ("equity_fund", "bond_fund", "closed_end", "fund"):
        return Verdict(CORE if held else UNRATED, (R_FUND,))
    if kind == "crypto":
        return Verdict(UNRATED, (R_CRYPTO,))
    return None


def _unscored(s: Scores, shown: dict[str, float | None]) -> Verdict:
    # Broken source data and absent data are different things to tell a reader.
    why = R_SUSPECT if s.suspect else R_FCF_FLOAT if s.fcf_float else R_NO_DATA
    return Verdict(UNRATED, (why,), s.quality, s.cheapness, None, shown)


def company(kind: str | None) -> bool:
    """A name judged as a business: not a fund, cash or a coin."""
    return _kind_verdict(kind, held=True) is None


def concentration_line(names: int | None) -> float | None:
    """The weight from which one company is a concentration in a book of
    `names` companies; None when there are too few for it to be one
    position's fault. An unknown count reads as a wide book."""
    if names is None:
        return CONCENTRATED
    if names < FEW_NAMES:
        return None
    return min(CONCENTRATED_MAX, max(CONCENTRATED, SPREAD / names))


def _even_share(names: int | None, line: float) -> float:
    """Where a cut concentration is taken: an even share of the companies."""
    share = CONCENTRATED_TO if names is None else max(CONCENTRATED_TO, 1 / names)
    return min(share, line)


def book_notes(rows: list[tuple[str | None, str | None, float | None]]) -> list[Note]:
    """What the page says about the book as a whole, before any one row.

    `rows` is each held name's kind, sector and weight. One or two companies
    carrying the book, one sector carrying `SECTOR_LINE` of it across two
    companies or more, and coins past `CRYPTO_LINE` are each named once.
    """
    companies = [(sector, w or 0.0) for kind, sector, w in rows if company(kind)]
    names = len(companies)
    notes: list[Note] = []
    if 0 < names < FEW_NAMES and sum(w for _, w in companies) >= FEW_NAMES_SHARE:
        notes.append(Note(N_FEW_NAMES, count=names))
    if names >= FEW_NAMES:
        sectors: dict[str, list[float]] = {}
        for sector, w in companies:
            if sector:
                sectors.setdefault(sector, []).append(w)
        heavy = [
            Note(N_SECTOR_HEAVY, count=len(ws), sector=sector, weight=sum(ws))
            for sector, ws in sectors.items()
            if len(ws) >= 2 and sum(ws) >= SECTOR_LINE
        ]
        notes += sorted(heavy, key=lambda n: -(n.weight or 0.0))
    coins = sum(w or 0.0 for kind, _, w in rows if kind == "crypto")
    if coins >= CRYPTO_LINE:
        notes.append(Note(N_CRYPTO_HEAVY, weight=coins))
    return notes


def judge_held(
    metrics: Mapping | None,
    *,
    weight: float | None,
    risk_share: float | None = None,
    kind: str | None = "stock",
    names: int | None = None,
) -> Verdict:
    """The verdict on one name the book holds.

    `weight` is its share of the priced book (None when it could not be
    priced), `risk_share` its share of the book's volatility and `names` how
    many companies the book holds (`company`), which sets where a
    concentration starts (`concentration_line`).
    """
    if by_kind := _kind_verdict(kind, held=True):
        return by_kind
    s = score(metrics or {})
    shown = _shown(metrics)
    line = concentration_line(names)
    if s.stage == EARLY:
        reasons = _early_reasons(metrics or {})
        if weight is not None and weight > SPEC_MAX:
            return Verdict(TRIM, (R_BET_HEAVY, *reasons), None, None, SPEC_MAX, shown)
        return Verdict(BET, tuple(reasons), None, None, None, shown)
    if s.quality is None or s.cheapness is None:
        unscored = _unscored(s, shown)
        # Size is a fact the ledger knows without the filings: one company
        # this big is cut whether or not its numbers can be read — but only
        # halfway back, since unread is not weak.
        if weight is not None and line is not None and weight >= line:
            return Verdict(
                TRIM,
                (R_CONCENTRATED, *unscored.reasons),
                s.quality,
                s.cheapness,
                (line + _even_share(names, line)) / 2,
                shown,
            )
        return unscored

    q, c = s.quality, s.cheapness
    w = weight
    add_to = SPEC_MAX if s.stage == GROWTH else ADD_TO
    reasons = _business_reasons(metrics or {}, s)
    clean = q >= GOOD and c >= CHEAP and not s.suspect and not _cautions(metrics or {}, s)
    over = w is not None and line is not None and w >= line
    position: list[str] = []
    if over:
        position.append(R_CONCENTRATED)
    elif w is not None and w >= HEAVY:
        position.append(R_HEAVY)
    if line is None and w is not None and w >= CONCENTRATED:
        position.append(R_FEW_NAMES)
    if risk_share is not None and risk_share >= RISKY:
        position.append(R_RISKY)

    verdict, target = HOLD, None
    # A position too small to move the book is worth its line in the ledger
    # only if it is good enough to grow into a real one.
    if (q < POOR and c < POOR) or (q < GOOD and w is not None and w < SMALL):
        verdict, target = SELL, 0.0
        if w is not None and w < SMALL:
            position.append(R_SMALL)
    elif over:
        even = _even_share(names, line)
        # A good business at a good price is cut only halfway back: the
        # excess goes, the conviction stays, and the next rally does not
        # trip the line again the week after.
        verdict, target = TRIM, (line + even) / 2 if clean else even
    elif q < WEAK and (
        (w is not None and w >= HEAVY) or (risk_share is not None and risk_share >= RISKY)
    ):
        verdict, target = TRIM, (w * TRIM_KEEPS if w is not None else None)
    # An add has to be a trade: a name a hair under its mark is not told
    # to buy one day and hold the next.
    elif clean and w is not None and add_to - w >= SMALL:
        verdict, target = ADD, add_to
        position.append(R_UNDERWEIGHT)

    fill = None
    if verdict in (HOLD, ADD) and clean and w is not None:
        # With too few companies, money freed goes to new names, not to
        # the one or two already carrying the book.
        wide = line is not None and s.stage == MATURE
        fill = max(add_to, _even_share(names, line)) if wide else add_to

    # The position's own reasons lead when they are why it moves; the
    # business ones lead otherwise.
    ordered = position + reasons if verdict == TRIM else reasons + position
    return Verdict(verdict, tuple(dict.fromkeys(ordered)), q, c, target, shown, fill)


def stage_for_tax(
    weight: float | None, verdict: Verdict, tax_share: float | None
) -> Verdict:
    """A concentration cut whose tax is `TAX_STAGE` of what the sale raises
    (`tax_share`, tax over proceeds), taken halfway: the rest is next year's,
    under another year's allowance and brackets. A sale for quality — a weak
    or poor business — is not deferred: the tax is the price of leaving."""
    if (
        verdict.verdict != TRIM
        or R_CONCENTRATED not in verdict.reasons
        or weight is None
        or verdict.target is None
        or tax_share is None
        or tax_share < TAX_STAGE
    ):
        return verdict
    to = weight - (weight - verdict.target) / 2
    if weight - to < SMALL:
        return verdict
    rest = tuple(r for r in verdict.reasons if r != R_CONCENTRATED)
    return replace(verdict, target=to, reasons=(R_CONCENTRATED, R_TAX_STAGED, *rest))


def redeploy(
    book: list[tuple[float | None, Verdict]],
    sectors: list[str | None] | None = None,
) -> list[Verdict]:
    """Where the money the sales free goes before it is left as cash.

    `book` is each held name's weight and verdict, `sectors` each one's
    sector (None where unknown). What the sales and trims free beyond the
    adds already planned is spread over the names good and cheap enough to
    add to, best first, each up to its `fill`; a top-up under `SMALL` of the
    book is not worth a trade. No add, planned or spread, takes a sector past
    `SECTOR_LINE`. Adds are never funded with money the plan does not raise:
    what has no home stays unplaced.
    """
    out = [v for _, v in book]
    sector_of = list(sectors) if sectors is not None else [None] * len(book)
    after: dict[str, float] = {}
    for (w, v), sector in zip(book, sector_of, strict=True):
        if sector and w is not None:
            kept = v.target if v.target is not None else w
            after[sector] = after.get(sector, 0.0) + kept

    def room(i: int) -> float:
        sector = sector_of[i]
        return SECTOR_LINE - after[sector] if sector else float("inf")

    # A planned add into a sector already past the line shrinks to fit it,
    # weakest first, or is held.
    adds = [i for i, v in enumerate(out) if v.verdict == ADD and book[i][0] is not None]

    def worth(i: int) -> float:
        return (out[i].quality or 0.0) + (out[i].cheapness or 0.0)

    for i in sorted(adds, key=worth):
        w, v = book[i][0], out[i]
        over = -room(i)
        if over <= 0 or v.target is None:
            continue
        cut = min(over, v.target - w)
        after[sector_of[i]] -= cut
        to = v.target - cut
        if to - w < SMALL:
            after[sector_of[i]] -= to - w
            kept = tuple(r for r in v.reasons if r != R_UNDERWEIGHT)
            out[i] = replace(v, verdict=HOLD, target=None, reasons=(R_SECTOR_FULL, *kept))
        else:
            out[i] = replace(v, target=to)

    moves = [
        v.target - w
        for (w, _), v in zip(book, out, strict=True)
        if w is not None and v.target is not None
    ]
    budget = -sum(moves)
    if budget < SMALL:
        return out

    for i in sorted(range(len(book)), key=lambda i: -worth(i)):
        w, v = book[i][0], out[i]
        if w is None or v.fill is None or v.verdict not in (HOLD, ADD):
            continue
        start = v.target if v.target is not None else w
        to = min(v.fill, start + budget, start + room(i))
        if to - start < SMALL:
            continue
        budget -= to - start
        if sector_of[i]:
            after[sector_of[i]] += to - start
        reasons = v.reasons if v.verdict == ADD else (R_REDEPLOY, *v.reasons)
        out[i] = replace(v, verdict=ADD, target=to, reasons=reasons)
        if budget < SMALL:
            break
    return out


def judge_candidate(metrics: Mapping | None, *, kind: str | None = "stock") -> Verdict:
    """The verdict on one name the book does not hold yet."""
    if by_kind := _kind_verdict(kind, held=False):
        return by_kind
    s = score(metrics or {})
    shown = _shown(metrics)
    if s.stage == EARLY:
        return Verdict(BET, tuple(_early_reasons(metrics or {})), None, None, None, shown)
    if s.quality is None or s.cheapness is None:
        return _unscored(s, shown)
    q, c = s.quality, s.cheapness
    if q >= GOOD and c >= CHEAP and not s.suspect and not _cautions(metrics or {}, s):
        verdict = BUY
    elif q >= GOOD or (q >= WEAK and c >= CHEAP):
        verdict = WATCH
    else:
        verdict = PASS
    reasons = tuple(_business_reasons(metrics or {}, s))
    return Verdict(verdict, reasons, q, c, None, shown)


def sort_key(verdict: str, score_total: float | None, weight: float | None, held: bool):
    """Actions first; inside a verdict, the stronger case (or the heavier
    position, for funds) first. A missing number sinks."""
    order = HELD_ORDER if held else CANDIDATE_ORDER
    rank = order.index(verdict) if verdict in order else len(order)
    s = -score_total if score_total is not None else float("inf")
    if verdict in (SELL, TRIM, PASS):
        s = -s if score_total is not None else float("inf")
    return (rank, s, -(weight or 0.0))
