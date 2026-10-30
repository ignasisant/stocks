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
  still under 10%; or growing 15% or more with a cash rule of 40 (growth plus
  free cash flow before share-based pay) of 30% or more, a margin thin
  because it is spent on growth (`_scaling`). Quality is the rule of 40
  (growth plus free-cash-flow margin), gross margin and moat; cheapness is
  EV/sales per point of growth, the cash it burns against its price, and a
  forward P/E only once there is one. A forward loss is the stage, not the
  dear end of a multiple.
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

import math
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

# Lenses: which ratios judge the business at all (`lens`).
STANDARD = "standard"
FINANCIAL = "financial"
REAL_ESTATE = "real_estate"
UTILITY = "utility"

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
# One country this much of the book, across `COUNTRY_NAMES` companies or
# more, is named: a home bias, or a bet on one economy, the reader may not
# have meant. The reader's own country is not excused.
COUNTRY_LINE = 0.70
COUNTRY_NAMES = 3
# One quote currency other than the reporting one this much of the book:
# the result in the reader's money turns on the exchange rate.
CURRENCY_LINE = 0.80
# Funds this much of the book make the companies satellites: said once,
# so the reader knows a verdict on one company is not one on the book.
FUND_CORE_LINE = 0.60
# Money-market lines this much of the book while the plan has names to add
# to or buy: cash idle beside the page's own proposals.
CASH_LINE = 0.20
# A concentration cut whose tax is this much of what the sale raises is
# taken in two steps: half now, the rest in another tax year.
TAX_STAGE = 0.10
# A weak name this heavy, or this much of the book's risk, is cut back.
HEAVY = 0.06
RISKY = 0.10
# Below this a position cannot move the book even if it doubles; nor is a
# trade this size worth making. In a wide book the line a held crumb is sold
# under shrinks with the count (`small_line`): `SMALL_SPREAD` over the
# companies, so 200 names at 0.4% each are a book, not 200 crumbs.
SMALL = 0.005
SMALL_SPREAD = 0.5
# The most crumbs one pass sells: past it, the weakest go and the rest wait.
SMALL_SELLS_MAX = 5
# An add's mark shrinks with the count too (`add_line`): `ADD_SPREAD` over the
# companies — twice an even share, a conviction weight and not an equal one —
# never over `ADD_TO` nor under `ADD_MIN`: 5% up to 40 names, 4% at 50, 1%
# from 200.
ADD_SPREAD = 2.0
ADD_MIN = 0.01
# The most of the book a bet on an unsold product should be: a total loss
# costs three points, which a year of the rest of the book can make back.
SPEC_MAX = 0.03
# Sales growth that makes a loss a stage rather than a verdict, and the
# operating margin under which a grower is still judged as one.
GROWTH_MIN = 0.25
GROWTH_MARGIN = 0.10
# A slower grower is judged as one too when its cash says the thin margin is
# what it spends on growth, not what it earns: sustained growth from
# `SCALING_MIN` plus free cash flow before share-based pay (the cash rule of
# 40) at `SCALING_RULE_40` or more. A software house at 15% growth and an 18%
# cash margin, at break-even only after the shares it pays its staff in,
# read under the mature lens as "ROIC 0, margin 0, sell".
SCALING_MIN = 0.15
SCALING_RULE_40 = 0.30
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
#: Where debt is heavy for a landlord and for a regulated network: rents and
#: tariffs carry more of it than a cyclical's profits can.
REIT_DEBT = 8.0
REGULATED_DEBT = 5.0
#: A dividend counts toward the price from `DIVIDEND_LEG_MIN` (a landlord's
#: and a utility's always), scored from `DIVIDEND_LO` to `DIVIDEND_HI`; the
#: row names it from `DIVIDEND_HIGH`. The minimum is where the yield reads
#: cheap: under it a payout says no more about the price than a buyback
#: would, and counted it made a 2% payer dearer than a name paying nothing.
#: A payout over `PAYOUT_STRETCHED` of earnings is one the business may not
#: keep paying. So is one over the owner's free cash flow across the filed
#: years (`DIVIDEND_FCF_MAX`), but only where earnings back the doubt (a
#: payout over `PAYOUT_TIGHT`) or the gap is wide (`DIVIDEND_FCF_HARD`): a
#: dividend earnings cover twice over is short of cash flow for a reason
#: the feed cannot see (Coca-Cola's tax deposit and Fairlife payment).
DIVIDEND_LEG_MIN = 0.035
DIVIDEND_LO = 0.01
DIVIDEND_HI = 0.06
DIVIDEND_HIGH = 0.04
PAYOUT_STRETCHED = 0.90
PAYOUT_TIGHT = 0.75
DIVIDEND_FCF_MAX = 1.0
DIVIDEND_FCF_HARD = 1.5
#: The return a bank's equity has to earn to be worth its book.
COST_OF_EQUITY = 0.10
#: The growth a bank's book compounds at for ever, in the justified price to
#: tangible book (ROTCE - g) / (COE - g): nominal GDP's, no more.
BANK_GROWTH = 0.03
HIGH_ROE = 0.15
LOW_ROE = 0.08
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
# Share-based pay this share of FCF, or of sales, is named: the yield is
# scored without it.
SHARE_PAY = 0.5
SHARE_PAY_SALES = 0.10
# Share count growing this fast a year: each share owns a shrinking slice of
# whatever the business earns, so a cheap price per share may not stay cheap.
HEAVY_DILUTION = 0.05
# Earnings the cash does not back: accruals (Sloan's net income less operating
# cash flow, over assets) past `ACCRUALS_HIGH`, or operating cash under
# `CASH_BACKED_MIN` of the profit summed over the filed years. Profits that
# are bookkeeping tend to come back down; a cheap P/E on them is not cheap.
ACCRUALS_HIGH = 0.10
CASH_BACKED_MIN = 0.70
# Goodwill this share of assets, or past the owners' equity, is a bet that the
# acquisitions were worth their price; with a return on all the capital
# (goodwill in) under `GOODWILL_ROIC` they are not earning it back, and the
# write-down that says so comes off the book.
GOODWILL_ASSETS = 0.50
GOODWILL_EQUITY = 1.0
GOODWILL_ROIC = 0.08
# Dollars traded a day under which getting in and out costs a spread and moves
# the price: a cheap reading on a name nobody trades may be the reason.
THIN_TURNOVER = 1_000_000.0
# Insiders holding this share run the company with their own money in it:
# named, never scored (Yahoo's figure counts a family's or a state's stake).
INSIDERS_OWN = 0.10

# Score bands.
GOOD = 60.0
WEAK = 45.0
POOR = 40.0
CHEAP = 50.0
# Doing nothing costs nothing; a move costs its spread, its fees and often its
# tax, and the scores are read off figures that move a few points with the
# price. So a move starts only clearly past its line and, once proposed,
# stands until it is back inside it: a sale starts with both scores under
# `SELL_BELOW` and stands while they stay under `POOR`; an add starts at
# `ADD_MARGIN` past GOOD and CHEAP and stands while it clears them. Between
# the two the verdict is hold (`close_call`), and a plan with no move left is
# itself the advice: stay put.
SELL_BELOW = 35.0
ADD_MARGIN = 5.0
# A sale whose tax is more than this share of what it raises waits as a hold
# (`sale_costly`) unless the business is poor past doubt (`COSTLY_FLOOR`):
# the tax is a cost now for a verdict a few points from the line.
SALE_COST_MAX = 0.05
COSTLY_FLOOR = 25.0

#: The metric keys a row carries back to the client, in display order.
SHOWN = (
    "pe_fwd",
    "growth_pe",
    "fcf_yield",
    "owner_fcf_yield",
    "ev_ebitda",
    "roic",
    "roic_ex_goodwill",
    "op_margin",
    "moat",
    "revenue_cagr",
    "share_dilution",
    "net_debt_ebitda",
    "ev_sales",
    "revenue_growth",
    "fcf_margin",
    "runway_years",
    "pe_ttm",
    "pb",
    "roe",
    "ptbv",
    "rotce",
    "dividend_yield",
    "payout_ratio",
)

#: Industries (Yahoo's names) judged on their book: a lender's or an
#: insurer's cash flow is its customers' money moving, and its debt is its
#: raw material. Card networks, brokers of insurance and exchanges are left
#: out on purpose: they score fine as businesses; a card lender that does
#: not still falls back on `fcf_float`. So is "Capital Markets": Yahoo files
#: bitcoin miners (CLSK, MARA) there beside the brokers, and a miner read on
#: its book is a bank it is not.
FINANCIALS = frozenset(
    {
        "Banks - Diversified",
        "Banks - Regional",
        "Mortgage Finance",
        "REIT - Mortgage",
        "Insurance - Diversified",
        "Insurance - Life",
        "Insurance - Property & Casualty",
        "Insurance - Reinsurance",
        "Insurance - Specialty",
        "Asset Management",
        "Financial Conglomerates",
    }
)

#: Regulated networks: their return is the one the regulator allows, their
#: capex is funded with debt on purpose, so ROIC, free cash flow and the moat
#: read every one as a poor business. Renewables developers and merchant
#: power producers sell at market prices and keep the standard lens.
UTILITIES = frozenset(
    {
        "Utilities - Diversified",
        "Utilities - Regulated Electric",
        "Utilities - Regulated Gas",
        "Utilities - Regulated Water",
    }
)

#: Landlords: priced on book, earnings (a stand-in for FFO) and yield.
REITS = frozenset(
    {
        "REIT - Diversified",
        "REIT - Healthcare Facilities",
        "REIT - Hotel & Motel",
        "REIT - Industrial",
        "REIT - Office",
        "REIT - Residential",
        "REIT - Retail",
        "REIT - Specialty",
    }
)

#: Industries whose names read like a bank, an insurer, a landlord or a
#: utility but that keep the standard lens on purpose (see the tables above).
STANDARD_ON_PURPOSE = frozenset(
    {
        "Capital Markets",
        "Credit Services",
        "Financial Data & Stock Exchanges",
        "Insurance Brokers",
        "Utilities - Independent Power Producers",
        "Utilities - Renewable",
    }
)
_LENS_WORDS = ("Bank", "Insurance", "Mortgage", "REIT", "Utilities")


def unmapped_industry(industry: str | None) -> bool:
    """Whether `industry` names a bank, insurer, landlord or utility that no
    lens table lists: Yahoo renamed one, and its names fell back on the
    standard lens without a word."""
    if not industry or industry in STANDARD_ON_PURPOSE:
        return False
    if industry in FINANCIALS or industry in REITS or industry in UTILITIES:
        return False
    return any(word in industry for word in _LENS_WORDS)


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
R_HEAVY_DILUTION = "heavy_dilution"
R_EARNINGS_NOT_CASH = "earnings_not_cash"
R_GOODWILL_HEAVY = "goodwill_heavy"
R_THIN_TRADING = "thin_trading"
R_INSIDERS_OWN = "insiders_own"
R_ONE_READING = "cheap_on_one_reading"
R_FEW_NAMES = "few_names"
R_REDEPLOY = "redeploy"
R_TAX_STAGED = "tax_staged"
R_SECTOR_FULL = "sector_full"
R_TRAILING_PE = "trailing_pe"
R_BOOK_PRICED = "priced_on_book"
R_FINANCIAL_LENS = "financial_lens"
R_REIT_LENS = "reit_lens"
R_UTILITY_LENS = "utility_lens"
R_HIGH_ROE = "high_roe"
R_LOW_ROE = "low_roe"
R_DIVIDEND = "dividend"
R_PAYOUT_STRETCHED = "payout_stretched"
R_CLOSE_CALL = "close_call"
R_SALE_COSTLY = "sale_costly"
R_NEW_MONEY = "needs_new_money"

# Book-level notes (`review.note_<code>`).
N_FEW_NAMES = "few_names"
N_SECTOR_HEAVY = "sector_heavy"
N_CRYPTO_HEAVY = "crypto_heavy"
N_TAX_OFFSET = "tax_offset"
N_COUNTRY_HEAVY = "country_heavy"
N_CURRENCY_HEAVY = "currency_heavy"
N_FUND_CORE = "fund_core"
N_CASH_HEAVY = "cash_heavy"
# A kind of asset outside the band the reader's plan keeps it in
# (`portfolio.plan.drift`): over it the page buys no more of it, under it says
# where the next money goes.
N_PLAN_OVER = "plan_over"
N_PLAN_UNDER = "plan_under"

#: Kinds that are a fund held as the book's base (not money-market).
FUND_KINDS = frozenset({"equity_fund", "bond_fund", "closed_end", "fund"})

# Reasons that read a loss as a fault; in the growth and early stages it is
# the stage itself, and the row says so once instead.
_PROFIT_REASONS = frozenset({R_LOSS, R_LOW_ROIC, R_HIGH_ROIC})

# Reasons that read a bank, a landlord or a utility with a company's ruler:
# ROIC, cash flow (and the runway it gives), margins and the moat (whose
# pillars are those three) say nothing about a balance sheet that is the
# business. A landlord's and a utility's debt still counts.
_FINANCIAL_SUPPRESSED = frozenset(
    {
        R_HIGH_ROIC,
        R_LOW_ROIC,
        R_NEGATIVE_FCF,
        R_FCF_FLOAT,
        R_SHARE_PAY,
        R_DEBT,
        R_PEAK_MARGIN,
        R_MARGIN_FALLING,
        R_RULE_40,
        R_CHEAP_FOR_GROWTH,
        R_WIDE_MOAT,
        R_NO_MOAT,
        R_SHORT_RUNWAY,
        R_LONG_RUNWAY,
    }
)
_LENS_SUPPRESSED = {
    FINANCIAL: _FINANCIAL_SUPPRESSED,
    REAL_ESTATE: _FINANCIAL_SUPPRESSED - {R_DEBT},
    UTILITY: _FINANCIAL_SUPPRESSED - {R_DEBT},
}
_LENS_REASON = {
    FINANCIAL: R_FINANCIAL_LENS,
    REAL_ESTATE: R_REIT_LENS,
    UTILITY: R_UTILITY_LENS,
}


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


def _cheap_reads(parts: list[float]) -> int:
    """How many of the price inputs read cheap on their own."""
    return sum(1 for p in parts if p >= CHEAP)


@dataclass(frozen=True)
class Scores:
    quality: float | None
    cheapness: float | None
    suspect: bool = False
    stage: str = MATURE
    #: Free cash flow left out because it is a float, not earnings.
    fcf_float: bool = False
    #: How many price inputs read cheap on their own (`_cheap_reads`).
    cheap_reads: int = 0
    #: Which ratios judged it (`lens`).
    lens: str = STANDARD
    #: The P/E read was the trailing one: no analyst covers the name.
    trailing_pe: bool = False
    #: Book value joined the price because the feed gave too little else.
    book_priced: bool = False
    #: The P/E was read on the median margin: this one is a cycle's peak.
    normal_pe: bool = False

    @property
    def total(self) -> float | None:
        if self.quality is None or self.cheapness is None:
            return None
        return (self.quality + self.cheapness) / 2


def growth_of(metrics: Mapping) -> float | None:
    """Sales growth now: last quarter on a year before, else the long CAGR."""
    recent = _num(metrics, "revenue_growth")
    return recent if recent is not None else _num(metrics, "revenue_cagr")


def _roic(metrics: Mapping) -> float | None:
    """Return on the capital the business runs on: past what an acquirer
    paid over book (goodwill) and the amortisation of what it bought, when
    the filings show them. An acquisition is judged by its price, which is
    the cheapness score's job; leaving the premium in reads a chip designer
    that bought a rival as a poor business."""
    roic = _num(metrics, "roic")
    own = _num(metrics, "roic_ex_goodwill")
    if own is None:
        return roic
    return own if roic is None else max(roic, own)


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


def lens(metrics: Mapping) -> str:
    """Which ratios judge this business, by Yahoo's industry."""
    industry = metrics.get("industry")
    if industry in FINANCIALS:
        return FINANCIAL
    if industry in REITS:
        return REAL_ESTATE
    if industry in UTILITIES:
        return UTILITY
    return STANDARD


def debt_line(metrics: Mapping) -> float:
    """Net debt over EBITDA from which the debt is heavy for this industry."""
    industry = metrics.get("industry") or ""
    if industry in REITS:
        return REIT_DEBT
    if industry.startswith("Utilities - ") or industry == "Telecom Services":
        return REGULATED_DEBT
    return HIGH_DEBT


def _dividend_leg(metrics: Mapping, always: bool = False) -> float | None:
    """The yield as a price input: only from `DIVIDEND_LEG_MIN`, so a token
    payout does not count against a name that reinvests instead (a bias
    toward payers, accepted); a landlord's (`always`) counts whatever it is."""
    y = _num(metrics, "dividend_yield")
    if y is None or (not always and y < DIVIDEND_LEG_MIN):
        return None
    return _lin(y, DIVIDEND_LO, DIVIDEND_HI)


def _pe(metrics: Mapping) -> tuple[float | None, bool]:
    """The P/E to read and whether it is the trailing one: the forward one
    where analysts cover the name, else the last twelve months'. Many
    European small caps have no estimates at all, and without a P/E they had
    one price input and no loss test."""
    forward = _num(metrics, "pe_fwd")
    if forward is not None:
        return forward, False
    trailing = _num(metrics, "pe_ttm")
    return trailing, trailing is not None


def _at_peak(metrics: Mapping) -> bool:
    """The operating margin is a cycle's top (`PEAK_RATIO`), not a new normal."""
    margin = _num(metrics, "op_margin")
    median = _num(metrics, "op_margin_median")
    growth = sustained_growth(metrics)
    return (
        margin is not None
        and median is not None
        and margin - median >= PEAK_GAP
        and (median <= 0 or margin >= PEAK_RATIO * median)
        and (_num(metrics, "revenue_down_years") or 0) >= 1
        and (growth is None or growth < RULE_40_MIN)
    )


def _normal_pe(metrics: Mapping, pe: float | None) -> float | None:
    """The P/E on the median margin instead of the peak one: today's sales at
    a normal year's margin. A cyclical at the top looks cheapest exactly when
    its earnings are about to fall; a median at or under zero is a normal
    year at a loss, the dear end."""
    if pe is None or pe <= 0:
        return pe
    margin = _num(metrics, "op_margin")
    median = _num(metrics, "op_margin_median")
    if margin is None or median is None or margin <= 0:
        return pe
    if median <= 0:
        return 0.0
    return pe * margin / median


def peak_pe(metrics: Mapping) -> float | None:
    """The trailing P/E on a normal year's margin, when this year's is a
    cycle's peak (`_at_peak`); None when it is not, or there is no P/E."""
    if lens(metrics) != STANDARD or stage(metrics) != MATURE or not _at_peak(metrics):
        return None
    pe = _num(metrics, "pe_ttm")
    return _normal_pe(metrics, pe) if pe is not None and pe > 0 else None


def growth_pe(metrics: Mapping, pe: float | None = None) -> float | None:
    """P/E (`_pe`, or the one given) per point of sustained per-share sales
    growth; None without a positive P/E or positive growth."""
    if pe is None:
        pe, _ = _pe(metrics)
    growth = per_share_growth(metrics)
    if pe is None or pe <= 0 or growth is None or growth <= 0:
        return None
    return pe / (min(growth, PEG_GROWTH_CAP) * 100)


def _unsold(metrics: Mapping) -> bool:
    """No sales to speak of: none, or a price over `PRE_REVENUE_PS` times them."""
    revenue = _num(metrics, "revenue")
    if revenue is None:
        return False
    if revenue <= 0:
        return True
    # `ps` is in one currency (`compute_metrics` converts an ADR's sales);
    # cap over raw revenue is the fallback for a memo written before it.
    ps = _num(metrics, "ps")
    cap = _num(metrics, "market_cap")
    if ps is None and cap is not None:
        ps = cap / revenue
    return ps is not None and ps >= PRE_REVENUE_PS


def _deep_burn(metrics: Mapping) -> bool:
    """Sales, but an operating loss larger than them, and cash going out."""
    fcf = _num(metrics, "fcf")
    margin = _num(metrics, "op_margin")
    return (
        fcf is not None and fcf < 0 and margin is not None and margin <= DEEP_BURN_MARGIN
    )


def stage(metrics: Mapping) -> str:
    """Mature, growth or early: which lens judges this business. A bank or
    a landlord is always mature: its cash flow going out is lending or
    building, not a business burning to reach a product."""
    if lens(metrics) != STANDARD:
        return MATURE
    fcf = _num(metrics, "fcf")
    burning = fcf is not None and fcf < 0
    if (burning and _unsold(metrics)) or _deep_burn(metrics):
        return EARLY
    growth = sustained_growth(metrics)
    margin = _num(metrics, "op_margin")
    if growth is None or margin is None or margin >= GROWTH_MARGIN:
        return MATURE
    if growth >= GROWTH_MIN or _scaling(metrics, growth):
        return GROWTH
    return MATURE


def _scaling(metrics: Mapping, growth: float) -> bool:
    """A grower under `GROWTH_MIN` whose cash rule of 40 says the thin margin
    is spent on growth (`SCALING_MIN`, `SCALING_RULE_40`). The cash is the
    feed's, share-based pay added back: here the question is whether the
    business throws off cash before it pays its staff in shares, which the
    growth lens then charges for (its quality reads the owner's margin)."""
    fcf = _num(metrics, "fcf")
    revenue = _num(metrics, "revenue")
    if growth < SCALING_MIN or fcf is None or not revenue or revenue <= 0:
        return False
    return growth + fcf / revenue >= SCALING_RULE_40


def score(metrics: Mapping) -> Scores:
    """Quality and cheapness, 0-100, off `compute_metrics` output."""
    view = lens(metrics)
    if view == FINANCIAL:
        return _financial_scores(metrics)
    if view == REAL_ESTATE:
        return _real_estate_scores(metrics)
    if view == UTILITY:
        return _utility_scores(metrics)
    phase = stage(metrics)
    if phase == EARLY:
        return Scores(None, None, stage=EARLY)
    roic = _roic(metrics)
    moat = _num(metrics, "moat")
    margin = _num(metrics, "op_margin")
    fcf = _fcf_yield(metrics)
    pe, trailing = _pe(metrics)
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
        return replace(
            _growth_scores(metrics, fcf, pe, suspect, floated), trailing_pe=trailing
        )

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
    peak = _at_peak(metrics)
    if peak:
        pe = _normal_pe(metrics, pe)
    if pe is not None:
        # A forward loss has no multiple; it is the dear end, not a missing one.
        pe_score = _lin(-pe, -40.0, -8.0) if pe > 0 else 0.0
        peg = growth_pe(metrics, pe) if pe > 0 else None
        if peg is not None:
            pe_score = max(pe_score, _lin(-peg, -PEG_HI, -PEG_LO))
        cheap.append(pe_score)
    if fcf is not None:
        cheap.append(_lin(fcf, 0.0, 0.10))
    if ev_ebitda is not None and ev_ebitda > 0:
        cheap.append(_lin(-ev_ebitda, -50.0, -8.0))
    if (paid := _dividend_leg(metrics)) is not None:
        cheap.append(paid)
    pb = _num(metrics, "pb")
    # A lender is priced on its book once its cash flow says nothing; any
    # name is, when the feed gave fewer than two other prices for it.
    book = pb is not None and pb > 0 and (floated or len(cheap) < 2)
    if book:
        cheap.append(_lin(-pb, -4.0, -1.0))

    return Scores(
        quality=_mean(quality),
        cheapness=_mean(cheap),
        suspect=suspect,
        fcf_float=floated,
        cheap_reads=_cheap_reads(cheap),
        trailing_pe=trailing and pe is not None,
        book_priced=book and not floated,
        normal_pe=peak and pe is not None,
    )


# The KPIs that are a price over something the filings fix, and the ones that
# are something over a price: at another price the first scale with it and
# the second against it. Everything else in `compute_metrics` is the business.
_PRICED = ("price", "market_cap", "pe_ttm", "pe_fwd", "pb", "ptbv", "ps", "turnover_usd")
_YIELDS = ("fcf_yield", "owner_fcf_yield", "dividend_yield")


def at_price(metrics: Mapping, factor: float) -> dict:
    """`metrics` as they read with the share price at `factor` times the one
    they were taken at, the business unchanged.

    The map's trail where no score was recorded that far back: the price is
    known for every day, the statements of that day are not, so this is where
    today's company would sit at that day's price. The enterprise value moves
    by the market cap's change only; the debt and cash under it stay. A
    forward P/E keeps today's estimate of the earnings. Quality moves a
    little too: it reads the cash yield as "does it make cash at all".
    """
    out = dict(metrics)
    if not factor or factor <= 0 or factor != factor:
        return out
    for key in _PRICED:
        if (value := _num(metrics, key)) is not None:
            out[key] = value * factor
    for key in _YIELDS:
        if (value := _num(metrics, key)) is not None:
            out[key] = value / factor
    ev = _num(metrics, "ev")
    cap = _num(metrics, "market_cap")
    if ev is not None and cap is not None:
        then = ev + cap * (factor - 1)
        out["ev"] = then
        for key in ("ev_ebitda", "ev_sales"):
            if key not in metrics:
                continue
            value = _num(metrics, key)
            # A multiple over a non-positive EV has no "same business" scale.
            out[key] = (
                value * then / ev if value is not None and ev > 0 and then > 0 else None
            )
    return out


def _pb_for_roe(metrics: Mapping) -> float | None:
    """Price to book over the book's worth: (return - g) / (`COST_OF_EQUITY`
    - g), g `BANK_GROWTH`. On the tangible book when the filings give it
    (goodwill is the first thing a bad year writes off), else on the whole.
    A bank earning 15% on tangible equity is worth 1.7 times it; one earning
    under g is worth less than any price, so it reads as dear."""
    pb, roe = _num(metrics, "ptbv"), _num(metrics, "rotce")
    if pb is None or roe is None:
        pb, roe = _num(metrics, "pb"), _num(metrics, "roe")
    if pb is None or pb <= 0 or roe is None:
        return None
    if roe <= BANK_GROWTH:
        return math.inf
    return pb / ((roe - BANK_GROWTH) / (COST_OF_EQUITY - BANK_GROWTH))


def _financial_scores(metrics: Mapping) -> Scores:
    """The financial lens: what the book earns, and what is paid for it."""
    roe = _num(metrics, "roe")
    earnings = _num(metrics, "net_income_cagr")
    dilution = _num(metrics, "share_dilution")
    pe, trailing = _pe(metrics)
    # A bank is priced on its tangible book when the filings give one.
    pb = _num(metrics, "ptbv") or _num(metrics, "pb")
    fair = _pb_for_roe(metrics)

    quality = [
        _lin(v, lo, hi)
        for v, lo, hi in (
            (roe, 0.04, 0.18),
            (earnings, -0.05, 0.15),
            (None if dilution is None else -dilution, -0.04, 0.04),
        )
        if v is not None
    ]
    cheap: list[float] = []
    if pe is not None:
        cheap.append(_lin(-pe, -16.0, -6.0) if pe > 0 else 0.0)
    if pb is not None and pb > 0:
        cheap.append(_lin(-pb, -2.5, -0.7))
    if fair is not None:
        cheap.append(_lin(-fair, -1.6, -0.6))
    if (paid := _dividend_leg(metrics)) is not None:
        cheap.append(paid)
    return Scores(
        quality=_mean(quality),
        cheapness=_mean(cheap),
        lens=FINANCIAL,
        cheap_reads=_cheap_reads(cheap),
        trailing_pe=trailing,
    )


def _real_estate_scores(metrics: Mapping) -> Scores:
    """The landlord's lens: rents that grow without new shares, at a margin,
    bought near book and on what they pay."""
    roe = _num(metrics, "roe")
    growth = _num(metrics, "revenue_cagr")
    dilution = _num(metrics, "share_dilution")
    margin = _num(metrics, "op_margin")
    pe, trailing = _pe(metrics)
    pb = _num(metrics, "pb")
    ev_ebitda = _num(metrics, "ev_ebitda")

    quality = [
        _lin(v, lo, hi)
        for v, lo, hi in (
            (roe, 0.0, 0.10),
            (growth, -0.05, 0.10),
            (None if dilution is None else -dilution, -0.10, 0.0),
            (margin, 0.20, 0.60),
        )
        if v is not None
    ]
    cheap: list[float] = []
    if pb is not None and pb > 0:
        cheap.append(_lin(-pb, -2.0, -0.7))
    if pe is not None:
        # Earnings stand in for FFO, which the feed does not give: they carry
        # the depreciation FFO adds back, so the scale is a wide one.
        cheap.append(_lin(-pe, -45.0, -12.0) if pe > 0 else 0.0)
    if ev_ebitda is not None and ev_ebitda > 0:
        cheap.append(_lin(-ev_ebitda, -28.0, -12.0))
    if (paid := _dividend_leg(metrics, always=True)) is not None:
        cheap.append(paid)
    return Scores(
        quality=_mean(quality),
        cheapness=_mean(cheap),
        lens=REAL_ESTATE,
        cheap_reads=_cheap_reads(cheap),
        trailing_pe=trailing,
    )


def _utility_scores(metrics: Mapping) -> Scores:
    """The utility's lens: the return its regulator lets the equity earn, the
    profit growing without new shares, and debt its tariffs can carry;
    bought on earnings, EBITDA and what it pays."""
    roe = _num(metrics, "roe")
    earnings = _num(metrics, "net_income_cagr")
    dilution = _num(metrics, "share_dilution")
    debt = _num(metrics, "net_debt_ebitda")
    pe, trailing = _pe(metrics)
    ev_ebitda = _num(metrics, "ev_ebitda")

    quality = [
        _lin(v, lo, hi)
        for v, lo, hi in (
            (roe, 0.04, 0.14),
            (earnings, -0.05, 0.08),
            (None if dilution is None else -dilution, -0.04, 0.02),
            (None if debt is None else -debt, -7.0, -3.0),
        )
        if v is not None
    ]
    cheap: list[float] = []
    if pe is not None:
        cheap.append(_lin(-pe, -25.0, -10.0) if pe > 0 else 0.0)
    if ev_ebitda is not None and ev_ebitda > 0:
        cheap.append(_lin(-ev_ebitda, -16.0, -7.0))
    if (paid := _dividend_leg(metrics, always=True)) is not None:
        cheap.append(paid)
    return Scores(
        quality=_mean(quality),
        cheapness=_mean(cheap),
        lens=UTILITY,
        cheap_reads=_cheap_reads(cheap),
        trailing_pe=trailing,
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
        cheap_reads=_cheap_reads(cheap),
    )


def _cautions(metrics: Mapping, s: Scores) -> list[str]:
    """Why two good scores still do not make an add or a buy (see the module
    docstring): the reasons the numbers behind them may not hold."""
    out: list[str] = []
    median = _num(metrics, "op_margin_median")
    change = _num(metrics, "op_margin_change")
    if s.stage == MATURE and s.lens == STANDARD:
        if _at_peak(metrics):
            out.append(R_PEAK_MARGIN)
        if (
            change is not None
            and median is not None
            and median > 0
            and change <= -MARGIN_SLIDE
            and -change >= MARGIN_SLIDE_SHARE * median
        ):
            out.append(R_MARGIN_FALLING)
    if s.stage == MATURE and s.lens != FINANCIAL:
        # A bank's "sales" are its interest and fees, which follow rates.
        paces = [
            g
            for g in (_num(metrics, "revenue_growth"), _num(metrics, "revenue_cagr"))
            if g is not None
        ]
        if paces and max(paces) < 0:
            out.append(R_SALES_FALLING)
    trailing = _num(metrics, "pe_ttm")
    forward = _num(metrics, "pe_fwd")
    if (
        trailing is not None
        and forward is not None
        and 0 < trailing <= forward * (1 - EARNINGS_DROP)
    ):
        out.append(R_EARNINGS_FALLING)
    debt = _num(metrics, "net_debt_ebitda")
    if (
        debt is not None
        and debt >= debt_line(metrics)
        and not s.fcf_float
        and s.lens != FINANCIAL
    ):
        out.append(R_DEBT)
    # A landlord paying out its earnings is the law; a lender's free cash
    # flow is not what pays it, and a utility's is net of the capex its
    # debt funds on purpose.
    payout = _num(metrics, "payout_ratio")
    covered = _num(metrics, "dividend_fcf")
    short_of_cash = (
        covered is not None
        and s.lens not in (FINANCIAL, UTILITY)
        and (
            covered > DIVIDEND_FCF_HARD
            or (covered > DIVIDEND_FCF_MAX and (payout is None or payout > PAYOUT_TIGHT))
        )
    )
    if (
        payout is not None and payout > PAYOUT_STRETCHED and s.lens != REAL_ESTATE
    ) or short_of_cash:
        out.append(R_PAYOUT_STRETCHED)
    if s.stage != EARLY and s.lens != REAL_ESTATE:
        # A landlord pays its earnings out by law and grows on new shares;
        # its lens scores the dilution instead.
        dilution = _num(metrics, "share_dilution")
        if dilution is not None and dilution >= HEAVY_DILUTION:
            out.append(R_HEAVY_DILUTION)
    if s.stage != EARLY and s.lens == STANDARD:
        # A lender's operating cash is its customers' money moving; a
        # landlord's and a utility's earnings sit under their cash on purpose.
        accruals = _num(metrics, "accruals")
        backed = _num(metrics, "cfo_ni")
        if (accruals is not None and accruals > ACCRUALS_HIGH) or (
            backed is not None and backed < CASH_BACKED_MIN
        ):
            out.append(R_EARNINGS_NOT_CASH)
    if s.stage != EARLY and s.lens != FINANCIAL:
        heavy = (_num(metrics, "goodwill_assets") or 0) > GOODWILL_ASSETS or (
            _num(metrics, "goodwill_equity") or 0
        ) > GOODWILL_EQUITY
        # The return with the premium paid left in: `_roic` takes it out.
        whole = _num(metrics, "roic")
        if heavy and whole is not None and whole < GOODWILL_ROIC:
            out.append(R_GOODWILL_HEAVY)
    turnover = _num(metrics, "turnover_usd")
    if turnover is not None and turnover < THIN_TURNOVER:
        out.append(R_THIN_TRADING)
    # Cheap on the average but on one input alone: that input may be the
    # feed's mistake or a one-off, and nothing else confirms the price.
    if s.cheapness is not None and s.cheapness >= CHEAP and s.cheap_reads < 2:
        out.append(R_ONE_READING)
    return out


def _business_reasons(metrics: Mapping, s: Scores) -> list[str]:
    """What about the company itself speaks for or against it, strongest first."""
    out: list[str] = []
    roic = _roic(metrics)
    moat = _num(metrics, "moat")
    # The cash actually leaving, not the owner's view: pay in shares is
    # `share_pay`, not a business that consumes cash.
    fcf = None if s.suspect else _num(metrics, "fcf_yield")
    pe, _ = _pe(metrics)
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
        elif 0.03 <= dilution < HEAVY_DILUTION:
            # Past it the caution (`R_HEAVY_DILUTION`) says it instead.
            out.append(R_DILUTION)
    insiders = _num(metrics, "insider_share")
    if insiders is not None and insiders >= INSIDERS_OWN:
        out.append(R_INSIDERS_OWN)
    share_pay = _num(metrics, "sbc_fcf")
    pay_sales = _num(metrics, "sbc_revenue")
    if (share_pay is not None and share_pay >= SHARE_PAY) or (
        pay_sales is not None and pay_sales >= SHARE_PAY_SALES
    ):
        out.append(R_SHARE_PAY)
    if debt is not None and debt >= debt_line(metrics):
        out.append(R_DEBT)
    roe = _num(metrics, "roe")
    if s.lens in (FINANCIAL, UTILITY) and roe is not None:
        if roe >= HIGH_ROE:
            out.append(R_HIGH_ROE)
        elif roe < LOW_ROE:
            out.append(R_LOW_ROE)
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
        pe, _ = _pe(metrics)
        if s.normal_pe:
            pe = _normal_pe(metrics, pe)
        peg = growth_pe(metrics, pe) if pe is not None and pe > 0 else None
        if peg is not None and peg <= PEG_CHEAP:
            out.append(R_CHEAP_FOR_GROWTH)
    # A long runway only matters to a company that needs one; a short one
    # matters to any company burning cash.
    out.extend(
        r for r in _runway_reasons(metrics) if r != R_LONG_RUNWAY or s.stage != MATURE
    )
    if metrics.get("industry") in PHARMA and s.stage != EARLY:
        out.append(R_PATENT_RISK)
    y = _num(metrics, "dividend_yield")
    if y is not None and y >= DIVIDEND_HIGH:
        out.append(R_DIVIDEND)
    if s.trailing_pe:
        out.append(R_TRAILING_PE)
    if s.book_priced:
        out.append(R_BOOK_PRICED)
    if hidden := _LENS_SUPPRESSED.get(s.lens):
        out = [r for r in out if r not in hidden]
        out.insert(0, _LENS_REASON[s.lens])
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
    #: For an add the sales do not pay for (`R_NEW_MONEY`): the weight new
    #: money would take it to. Not part of the plan; None otherwise.
    want: float | None = None


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
    #: Yahoo's country name (English), for `country_heavy`.
    country: str | None = None
    #: ISO quote currency, for `currency_heavy`.
    currency: str | None = None
    #: The plan's bucket (`portfolio.plan.BUCKETS`) and its target share, for
    #: `plan_over` / `plan_under`.
    bucket: str | None = None
    target: float | None = None


@dataclass(frozen=True)
class BookRow:
    """One held name as the book-level notes read it."""

    kind: str | None
    sector: str | None = None
    weight: float | None = None
    #: Yahoo's country name (English); None for a fund or unknown.
    country: str | None = None
    #: ISO quote currency, minor units folded (GBp is GBP); None if unknown.
    currency: str | None = None


@dataclass(frozen=True)
class Limits:
    """The lines the reader drew in their plan (`portfolio.plan`), where they
    replace the page's own; the defaults are the page's, so a book without a
    plan reads exactly as before. Fractions of the book.

    `position` is a cap on one company: set, it is the concentration line
    whatever the count (`concentration_line`), and no add takes a name past
    it. `speculative` is the most one early-stage bet may weigh. `crypto` is
    where coins are named, `cash` where idle money-market funds are.
    """

    position: float | None = None
    sector: float = SECTOR_LINE
    speculative: float = SPEC_MAX
    cash: float = CASH_LINE
    crypto: float = CRYPTO_LINE

    @property
    def drawn(self) -> bool:
        """True when any line is the reader's rather than the page's."""
        return self != PAGE_LINES

    @classmethod
    def from_plan(cls, plan, bets: int = 0) -> Limits:
        """The plan's caps as the engine reads them. The plan caps the
        speculative names together; that is shared over the `bets` the book
        holds, one bet's worth when it holds none yet. A mix sets where coins
        are named (their target plus the band), a reserve where cash is."""
        limits = plan.limits
        out = cls()
        if limits.max_position_pct is not None:
            out = replace(out, position=limits.max_position_pct / 100)
        if limits.max_sector_pct is not None:
            out = replace(out, sector=limits.max_sector_pct / 100)
        if limits.max_speculative_pct is not None:
            out = replace(
                out, speculative=limits.max_speculative_pct / 100 / max(1, bets)
            )
        if plan.mix is not None:
            out = replace(
                out, crypto=(plan.mix.targets.get("crypto", 0.0) + plan.mix.band_pp) / 100
            )
        if plan.reserve is not None and plan.reserve.max_pct is not None:
            out = replace(out, cash=plan.reserve.max_pct / 100)
        return out


# The page's own lines, as the default every function below reads.
PAGE_LINES = Limits()


def plan_notes(drifts) -> list[Note]:
    """One note per bucket outside the plan's band (`portfolio.plan.drift`),
    furthest first: the share it is against the share the plan gives it."""
    return [
        Note(
            N_PLAN_OVER if d.side == "over" else N_PLAN_UNDER,
            bucket=d.bucket,
            weight=d.actual_pct / 100,
            target=d.target_pct / 100,
        )
        for d in drifts
    ]


def cautions(metrics: Mapping) -> list[str]:
    """The review's warnings on a company alone (`_cautions`), for a page that
    shows the company rather than judges it: everything but the one that is
    about the review's own cheap call."""
    if str(metrics.get("quote_type") or "EQUITY").upper() != "EQUITY":
        return []
    return [r for r in _cautions(metrics, score(metrics)) if r != R_ONE_READING]


#: Shown only for the lens that reads them: a telecom's price to tangible
#: book is 30x and means nothing.
_FINANCIAL_ONLY = frozenset({"ptbv", "rotce"})


def _shown(metrics: Mapping | None) -> dict[str, float | None]:
    metrics = metrics or {}
    derived = {"growth_pe": growth_pe(metrics)}
    bank = lens(metrics) == FINANCIAL
    return {
        key: None
        if key in _FINANCIAL_ONLY and not bank
        else derived[key]
        if key in derived
        else _num(metrics, key)
        for key in SHOWN
    }


def _kind_verdict(kind: str | None, held: bool) -> Verdict | None:
    """Funds, cash and coins have no fundamentals to judge: a verdict by kind."""
    if kind == "money_market":
        return Verdict(CASH if held else UNRATED, (R_CASH,))
    if kind in FUND_KINDS:
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


def concentration_line(names: int | None, cap: float | None = None) -> float | None:
    """The weight from which one company is a concentration in a book of
    `names` companies; None when there are too few for it to be one
    position's fault. An unknown count reads as a wide book. The reader's own
    `cap` (`Limits.position`) is the line whatever the count."""
    if cap is not None:
        return cap
    if names is None:
        return CONCENTRATED
    if names < FEW_NAMES:
        return None
    return min(CONCENTRATED_MAX, max(CONCENTRATED, SPREAD / names))


def small_line(names: int | None) -> float:
    """The weight under which a held company is a crumb, in a book of
    `names` companies: `SMALL`, less in a book wide enough that an even
    share sits near it."""
    return SMALL if not names else min(SMALL, SMALL_SPREAD / names)


def add_line(names: int | None) -> float:
    """Where an add takes a mature company in a book of `names` companies:
    `ADD_TO` in a narrow book, twice an even share in a wide one."""
    return ADD_TO if not names else max(ADD_MIN, min(ADD_TO, ADD_SPREAD / names))


def _even_share(names: int | None, line: float) -> float:
    """Where a cut concentration is taken: an even share of the companies."""
    share = CONCENTRATED_TO if names is None else max(CONCENTRATED_TO, 1 / names)
    return min(share, line)


def book_notes(
    rows: list[BookRow], reporting: str | None = None, limits: Limits = PAGE_LINES
) -> list[Note]:
    """What the page says about the book as a whole, before any one row.

    One or two companies carrying the book, one sector carrying `SECTOR_LINE`
    of it across two companies or more, one country carrying `COUNTRY_LINE`
    across `COUNTRY_NAMES`, one quote currency other than `reporting`
    carrying `CURRENCY_LINE`, funds past `FUND_CORE_LINE` and coins past
    `CRYPTO_LINE` are each named once; a plan's `limits` move the sector and
    coin lines.
    """
    companies = [r for r in rows if company(r.kind)]
    names = len(companies)
    notes: list[Note] = []
    if (
        0 < names < FEW_NAMES
        and sum(r.weight or 0.0 for r in companies) >= FEW_NAMES_SHARE
    ):
        notes.append(Note(N_FEW_NAMES, count=names))
    if names >= FEW_NAMES:
        sectors = _grouped(companies, lambda r: r.sector)
        heavy = [
            Note(N_SECTOR_HEAVY, count=len(ws), sector=sector, weight=sum(ws))
            for sector, ws in sectors.items()
            if len(ws) >= 2 and sum(ws) >= limits.sector
        ]
        notes += sorted(heavy, key=lambda n: -(n.weight or 0.0))
    for country, ws in _grouped(companies, lambda r: r.country).items():
        if len(ws) >= COUNTRY_NAMES and sum(ws) >= COUNTRY_LINE:
            notes.append(
                Note(N_COUNTRY_HEAVY, count=len(ws), country=country, weight=sum(ws))
            )
    home = (reporting or "").upper()
    for currency, ws in _grouped(rows, lambda r: r.currency).items():
        if home and currency.upper() != home and sum(ws) >= CURRENCY_LINE:
            notes.append(
                Note(N_CURRENCY_HEAVY, count=len(ws), currency=currency, weight=sum(ws))
            )
    funds = sum(r.weight or 0.0 for r in rows if r.kind in FUND_KINDS)
    if funds >= FUND_CORE_LINE:
        notes.append(Note(N_FUND_CORE, count=names, weight=funds))
    coins = sum(r.weight or 0.0 for r in rows if r.kind == "crypto")
    if coins >= limits.crypto:
        notes.append(Note(N_CRYPTO_HEAVY, weight=coins))
    return notes


def _grouped(rows: list[BookRow], key) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in rows:
        if group := key(r):
            out.setdefault(group, []).append(r.weight or 0.0)
    return out


def cash_note(
    rows: list[BookRow],
    verdicts: list[str],
    waiting: int = 0,
    limits: Limits = PAGE_LINES,
) -> Note | None:
    """Money-market lines past `CASH_LINE` while the plan has names to add to
    or buy (`verdicts`, held and outside), or `waiting` adds the sales do not
    pay for (`R_NEW_MONEY`): the cash the proposals could use. A plan's
    reserve ceiling is the line instead (`limits.cash`)."""
    cash = sum(r.weight or 0.0 for r in rows if r.kind == "money_market")
    wanted = sum(v in (ADD, BUY) for v in verdicts) + waiting
    if cash < limits.cash or not wanted:
        return None
    return Note(N_CASH_HEAVY, count=wanted, weight=cash)


def judge_held(
    metrics: Mapping | None,
    *,
    weight: float | None,
    risk_share: float | None = None,
    kind: str | None = "stock",
    names: int | None = None,
    company_share: float = 1.0,
    was: str | None = None,
    limits: Limits = PAGE_LINES,
) -> Verdict:
    """The verdict on one name the book holds.

    `weight` is its share of the priced book (None when it could not be
    priced), `risk_share` its share of the book's volatility and `names` how
    many companies the book holds (`company`), which sets where a
    concentration starts (`concentration_line`), what a crumb is
    (`small_line`) and where an add goes (`add_line`). `company_share` is the
    companies' share of the book: beside an index fund they are satellites,
    and money freed fills one only to its even share of that slice. `was`
    is the move the page last proposed for it and still stands (the
    decision journal's open proposal): a sale or an add already on the table
    holds to the plain line, a new one has to clear `SELL_BELOW` or
    `ADD_MARGIN`. `limits` are the reader's plan's lines where they drew
    them: a cap on one company is the concentration line, and no add goes
    past it.
    """
    if by_kind := _kind_verdict(kind, held=True):
        return by_kind
    s = score(metrics or {})
    shown = _shown(metrics)
    line = concentration_line(names, limits.position)
    spec = limits.speculative
    if s.stage == EARLY:
        reasons = _early_reasons(metrics or {})
        if weight is not None and weight > spec:
            return Verdict(TRIM, (R_BET_HEAVY, *reasons), None, None, spec, shown)
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
    small = small_line(names)
    add_to = min(spec, add_line(names)) if s.stage == GROWTH else add_line(names)
    if limits.position is not None:
        add_to = min(add_to, limits.position)
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
    sell_bar = POOR if was == SELL else SELL_BELOW
    near_sell = q < POOR and c < POOR and not (q < sell_bar and c < sell_bar)
    add_clear = clean and (
        was == ADD or (q >= GOOD + ADD_MARGIN and c >= CHEAP + ADD_MARGIN)
    )
    # A position too small to move the book is worth its line in the ledger
    # only if it is good enough to grow into a real one.
    if (q < sell_bar and c < sell_bar) or (q < GOOD and w is not None and w < small):
        verdict, target = SELL, 0.0
        if w is not None and w < small:
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
    elif add_clear and w is not None and add_to - w >= small:
        verdict, target = ADD, add_to
        position.append(R_UNDERWEIGHT)
    # A hold a few points from a move says so first: that is why it holds.
    close = verdict == HOLD and (
        near_sell or (clean and not add_clear and w is not None and add_to - w >= small)
    )

    fill = None
    if verdict in (HOLD, ADD) and clean and w is not None:
        # With too few companies, money freed goes to new names, not to
        # the one or two already carrying the book.
        wide = line is not None and s.stage == MATURE
        even = company_share / names if names else 0.0
        fill = max(add_to, min(line, even)) if wide else add_to

    # The position's own reasons lead when they are why it moves; the
    # business ones lead otherwise.
    ordered = position + reasons if verdict == TRIM else reasons + position
    if close:
        ordered.insert(0, R_CLOSE_CALL)
    return Verdict(verdict, tuple(dict.fromkeys(ordered)), q, c, target, shown, fill)


def cap_small_sells(verdicts: list[Verdict]) -> list[Verdict]:
    """At most `SMALL_SELLS_MAX` crumbs sold in one pass, the weakest first:
    a wide book's tail is not cleared in a day of thirty orders. A crumb
    sold for being poor on both scores is sold whatever the count; the rest
    past the cap wait as Hold, still named small."""
    crumbs = [
        i
        for i, v in enumerate(verdicts)
        if v.verdict == SELL
        and R_SMALL in v.reasons
        and not ((v.quality or 0.0) < POOR and (v.cheapness or 0.0) < POOR)
    ]
    if len(crumbs) <= SMALL_SELLS_MAX:
        return list(verdicts)

    def worth(i: int) -> float:
        return (verdicts[i].quality or 0.0) + (verdicts[i].cheapness or 0.0)

    out = list(verdicts)
    for i in sorted(crumbs, key=worth)[SMALL_SELLS_MAX:]:
        out[i] = replace(verdicts[i], verdict=HOLD, target=None)
    return out


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


def hold_for_cost(verdict: Verdict, tax_share: float | None) -> Verdict:
    """A sale whose tax is more than `SALE_COST_MAX` of what it raises
    (`tax_share`) waits as a hold, unless the business scores under
    `COSTLY_FLOOR`: a verdict a few points from its line is not worth a tax
    paid today. A crumb's sale is left alone: its tax is crumbs too."""
    if (
        verdict.verdict != SELL
        or R_SMALL in verdict.reasons
        or tax_share is None
        or tax_share <= SALE_COST_MAX
        or verdict.quality is None
        or verdict.quality < COSTLY_FLOOR
    ):
        return verdict
    return replace(
        verdict, verdict=HOLD, target=None, reasons=(R_SALE_COSTLY, *verdict.reasons)
    )


def redeploy(
    book: list[tuple[float | None, Verdict]],
    sectors: list[str | None] | None = None,
    sector_line: float = SECTOR_LINE,
) -> list[Verdict]:
    """Where the money the sales free goes before it is left as cash.

    `book` is each held name's weight and verdict, `sectors` each one's
    sector (None where unknown). What the sales and trims free beyond the
    adds already planned is spread over the names good and cheap enough to
    add to, best first, each up to its `fill`; a top-up under `SMALL` of the
    book is not worth a trade. No add, planned or spread, takes a sector past
    `sector_line` (`SECTOR_LINE`, or the plan's cap). Adds are never funded
    with money the plan does not raise:
    the adds the sales cannot pay for wait as holds marked `R_NEW_MONEY`
    with the weight new money would take them to (`want`), and what has no
    home stays unplaced.
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
        return sector_line - after[sector] if sector else float("inf")

    # A planned add into a sector already past the line shrinks to fit it,
    # weakest first, or is held.
    adds = [i for i, v in enumerate(out) if v.verdict == ADD and book[i][0] is not None]

    def worth(i: int) -> float:
        return (out[i].quality or 0.0) + (out[i].cheapness or 0.0)

    for i in sorted(adds, key=worth):
        w, v, sector = book[i][0], out[i], sector_of[i]
        over = -room(i)
        if over <= 0 or v.target is None or w is None or sector is None:
            continue
        cut = min(over, v.target - w)
        after[sector] -= cut
        to = v.target - cut
        if to - w < SMALL:
            after[sector] -= to - w
            kept = tuple(r for r in v.reasons if r != R_UNDERWEIGHT)
            out[i] = replace(v, verdict=HOLD, target=None, reasons=(R_SECTOR_FULL, *kept))
        else:
            out[i] = replace(v, target=to)

    # Only what the sales and trims free pays for an add: the best adds
    # first, each to its mark; one the money does not reach waits as a hold
    # that says new money would buy it (`want`), never as a plan that spends
    # cash the reader may not have.
    budget = sum(
        w - v.target
        for (w, _), v in zip(book, out, strict=True)
        if w is not None and v.target is not None and v.target < w
    )
    for i in sorted(adds, key=lambda i: -worth(i)):
        w, v = book[i][0], out[i]
        if v.verdict != ADD or v.target is None or w is None:
            continue
        take = min(v.target - w, budget)
        if take >= SMALL:
            budget -= take
            if sector := sector_of[i]:
                after[sector] -= v.target - w - take
            short = w + take < v.target - SMALL / 2
            out[i] = replace(v, target=w + take, want=v.target if short else None)
            continue
        if sector := sector_of[i]:
            after[sector] -= v.target - w
        out[i] = replace(
            v, verdict=HOLD, target=None, want=v.target, reasons=(R_NEW_MONEY, *v.reasons)
        )
    if budget < SMALL:
        return out

    for i in sorted(range(len(book)), key=lambda i: -worth(i)):
        w, v = book[i][0], out[i]
        if w is None or v.fill is None or v.verdict not in (HOLD, ADD) or v.want:
            continue
        start = v.target if v.target is not None else w
        to = min(v.fill, start + budget, start + room(i))
        if to - start < SMALL:
            continue
        budget -= to - start
        if sector := sector_of[i]:
            after[sector] += to - start
        kept = tuple(r for r in v.reasons if r != R_CLOSE_CALL)
        reasons = kept if v.verdict == ADD else (R_REDEPLOY, *kept)
        out[i] = replace(v, verdict=ADD, target=to, reasons=reasons)
        if budget < SMALL:
            break
    return out


def place_outside(
    book: list[tuple[float | None, Verdict]],
    sectors: list[str | None],
    buys: list[tuple[Verdict, str | None]],
    sector_line: float = SECTOR_LINE,
) -> tuple[list[float | None], float]:
    """What the plan's sales free and the book's own adds leave, spread over
    the outside Buys, best first, each up to its `fill`; a sector already at
    `sector_line` takes none, and a position under `SMALL` is not opened.

    `book` and `sectors` are the held names after `redeploy`, `buys` each
    outside name's verdict and sector. Returns each outside name's target
    weight (None where it takes nothing) and the share of the book still
    without a home.
    """
    after: dict[str, float] = {}
    moved = 0.0
    for (w, v), sector in zip(book, sectors, strict=True):
        if w is None:
            continue
        kept = v.target if v.target is not None else w
        moved += kept - w
        if sector:
            after[sector] = after.get(sector, 0.0) + kept
    spare = max(0.0, -moved)
    targets: list[float | None] = [None] * len(buys)

    def worth(i: int) -> float:
        v = buys[i][0]
        return (v.quality or 0.0) + (v.cheapness or 0.0)

    for i in sorted(range(len(buys)), key=lambda i: -worth(i)):
        if spare < SMALL:
            break
        v, sector = buys[i]
        if v.verdict != BUY or v.fill is None:
            continue
        room = sector_line - after.get(sector, 0.0) if sector else float("inf")
        take = min(v.fill, spare, room)
        if take < SMALL:
            continue
        targets[i] = take
        spare -= take
        if sector:
            after[sector] = after.get(sector, 0.0) + take
    return targets, spare


def judge_candidate(
    metrics: Mapping | None,
    *,
    kind: str | None = "stock",
    names: int | None = None,
    was: str | None = None,
    limits: Limits = PAGE_LINES,
) -> Verdict:
    """The verdict on one name the book does not hold yet. A Buy's `fill` is
    the weight an add would take it to in a book of `names` companies, for
    `place_outside` to size it with what the sales leave. A new Buy clears
    GOOD and CHEAP by `ADD_MARGIN`; one already proposed (`was`) holds to
    the plain line."""
    if by_kind := _kind_verdict(kind, held=False):
        return by_kind
    s = score(metrics or {})
    shown = _shown(metrics)
    if s.stage == EARLY:
        return Verdict(BET, tuple(_early_reasons(metrics or {})), None, None, None, shown)
    if s.quality is None or s.cheapness is None:
        return _unscored(s, shown)
    q, c = s.quality, s.cheapness
    margin = 0.0 if was == BUY else ADD_MARGIN
    clean = q >= GOOD and c >= CHEAP and not s.suspect and not _cautions(metrics or {}, s)
    close = False
    if clean and q >= GOOD + margin and c >= CHEAP + margin:
        verdict = BUY
    elif q >= GOOD or (q >= WEAK and c >= CHEAP):
        verdict, close = WATCH, clean
    else:
        verdict = PASS
    reasons = tuple(_business_reasons(metrics or {}, s))
    if close:
        reasons = (*reasons, R_CLOSE_CALL)
    fill = None
    if verdict == BUY:
        fill = (
            min(limits.speculative, add_line(names))
            if s.stage == GROWTH
            else add_line(names)
        )
        if limits.position is not None:
            fill = min(fill, limits.position)
    return Verdict(verdict, reasons, q, c, None, shown, fill)


def sort_key(verdict: str, score_total: float | None, weight: float | None, held: bool):
    """Actions first; inside a verdict, the stronger case (or the heavier
    position, for funds) first. A missing number sinks."""
    order = HELD_ORDER if held else CANDIDATE_ORDER
    rank = order.index(verdict) if verdict in order else len(order)
    s = -score_total if score_total is not None else float("inf")
    if verdict in (SELL, TRIM, PASS):
        s = -s if score_total is not None else float("inf")
    return (rank, s, -(weight or 0.0))
