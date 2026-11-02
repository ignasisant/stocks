"""The calendar ahead and one past print in detail."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ------------------------------------------------------------ the next prints
# The watchlist's reporting calendar. Upcoming dates and past results come back
# together because one fetch produces both — asking for them separately would
# double the requests to say the same thing twice.


class CalendarEvent(BaseModel):
    ticker: str
    date: str | None = Field(default=None, description="Reporting date, ISO.")
    days_until: int | None = Field(
        default=None, description="Days from today; 0 is a print due today."
    )


class CalendarResult(BaseModel):
    ticker: str
    date: str
    eps_estimate: float | None = None
    reported_eps: float | None = None
    surprise_pct: float | None = None
    beat: bool | None = Field(
        default=None,
        description="Null when there was nothing to compare, never False.",
    )


class TaxDeadline(BaseModel):
    """A filing date the account's tax residence imposes."""

    key: str = Field(
        description=(
            "Catalog stem: `earnings.tax_<key>` names it and `…_body` explains "
            "it, with `{year}` slotted."
        )
    )
    date: str = Field(description="Deadline, ISO, weekend-rolled where the law rolls it.")
    days_until: int = Field(description="Days from today; negative once it has passed.")
    year: str = Field(description='The tax year it concerns: "2025", "2025/26".')
    approximate: bool = Field(
        default=False,
        description="True where the date varies (by département, by canton).",
    )
    remind: bool = Field(
        default=False,
        description="Inside the reminder window: due within the next 30 days.",
    )


class CalendarDividend(BaseModel):
    """An ex-dividend date on a name the book holds, or held at the time."""

    ticker: str
    date: str = Field(description="Ex-dividend date, ISO — not the pay date.")
    days_until: int = Field(description="Days from today; negative once it went ex.")
    per_share: float | None = Field(
        default=None,
        description=(
            "Per share in `currency`. Past: what was paid. Upcoming: the LAST "
            "payment, since Yahoo publishes the date before the amount."
        ),
    )
    shares: float | None = Field(
        default=None,
        description="Held the day before it went ex; today's position if upcoming.",
    )
    amount: float | None = Field(
        default=None, description="per_share × shares, gross, in `currency`."
    )
    currency: str | None = None
    projected: bool = Field(
        default=False,
        description=(
            "Not declared: last year's ex-date moved forward 52 weeks, at last "
            "year's amount (the latest one for a quarterly or faster payer)."
        ),
    )
    base_currency: str | None = Field(
        default=None, description="The account's reporting currency."
    )
    amount_base: float | None = Field(
        default=None,
        description=(
            "`amount` in `base_currency`: at the ex-date's rate once it went "
            "ex, at today's before — the only rate a future payment has."
        ),
    )
    withholding: float | None = Field(
        default=None,
        description=(
            "Share of the gross withheld at source (0.15 is 15%), read off this "
            "book's dividend rows that booked one — this name's, else others "
            "paid in the same currency. Null when none did."
        ),
    )
    withholding_basis: Literal["ticker", "currency"] | None = Field(
        default=None, description="Which rows `withholding` was read from."
    )


class RepurchaseWindow(BaseModel):
    """A loss sale a buy-back would still block, and the day it stops."""

    ticker: str
    sell_date: str = Field(description="When the loss was sold, ISO.")
    date: str = Field(
        description="The first day buying it back no longer blocks the loss, ISO."
    )
    days_until: int = Field(description="Days from today to `date`; 0 is today.")
    loss: float = Field(
        description=(
            "The loss still exposed, in `currency` — less any part an earlier "
            "repurchase already blocked."
        )
    )
    currency: str = Field(description="The jurisdiction's currency.")
    window: str = Field(
        description=(
            "The rule's label, as `Jurisdiction.repurchase_window`: "
            '"2m", "30d" or "28d".'
        )
    )


class CentralBankDecision(BaseModel):
    """A rate-decision day of the Fed or the ECB."""

    bank: str = Field(description='"fed" or "ecb".')
    date: str = Field(description="The decision day, ISO — the statement's.")
    days_until: int = Field(description="Days from today; negative once it passed.")


class CalendarTrade(BaseModel):
    """The book's buys or sells of one name on one day, fills summed."""

    ticker: str
    date: str = Field(description="Trade date as the statement booked it, ISO.")
    days_until: int = Field(description="Days from today; negative once it passed.")
    side: Literal["buy", "sell"]
    quantity: float = Field(description="Shares, every fill of the day added up.")
    price: float | None = Field(
        default=None, description="Average fill price in `currency`."
    )
    amount: float = Field(description="quantity × price, before fees, in `currency`.")
    fee: float = Field(default=0.0, description="Commissions, in `currency`.")
    currency: str
    gain: float | None = Field(
        default=None,
        description=(
            "Sells only: what the matched lots realised, in `base_currency`, "
            "under the book's share matching. Null on a buy."
        ),
    )
    base_currency: str | None = None


class CalendarPayment(BaseModel):
    """A dividend (or return of capital) the statements actually booked."""

    ticker: str
    date: str = Field(description="The day the cash was booked, ISO — the pay date.")
    days_until: int = Field(description="Days from today; negative once it passed.")
    gross: float = Field(description="Before withholding, in `currency`.")
    withheld: float = Field(default=0.0, description="Tax kept at source.")
    net: float = Field(description="gross − withheld: what reached the account.")
    currency: str
    capital: bool = Field(
        default=False,
        description="A return of capital: it lowers the shares' cost, no income.",
    )
    base_currency: str | None = None
    net_base: float | None = Field(
        default=None,
        description="`net` in `base_currency` at the pay date's rate; null if none.",
    )


class MarketHoliday(BaseModel):
    """A day an exchange the watchlist trades on is shut, or shuts early."""

    venue: str = Field(description='"us", "xetra", "bme" or "lse".')
    date: str
    days_until: int = Field(description="Days from today; negative once it passed.")
    kind: Literal["closed", "early"] = Field(
        description='"closed" all day, or "early": a half session.'
    )


class EarningsCalendar(BaseModel):
    upcoming: list[CalendarEvent] = Field(
        default_factory=list, description="Soonest first; a same-day print counts."
    )
    results: list[CalendarResult] = Field(
        default_factory=list, description="Newest first, strictly before today."
    )
    groups: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "The filter sets the calendar offers: `portfolio` (open positions), "
            "`favorites`, then one per watchlist tag. Empty sets are left out, "
            "so a client can draw a pill per key without checking each one."
        ),
    )
    skipped: list[str] = Field(
        default_factory=list,
        description="Watchlist names that never report: coins and funds.",
    )
    jurisdiction: str | None = Field(
        default=None, description="The tax residence the deadlines are for."
    )
    tax_deadlines: list[TaxDeadline] = Field(
        default_factory=list,
        description=(
            "That jurisdiction's filing dates, about two months back to a year "
            "ahead, soonest first. Independent of the watchlist."
        ),
    )
    dividends: list[CalendarDividend] = Field(
        default_factory=list,
        description=(
            "The ledger's ex-dividend dates: every one the shares were entitled "
            "to over the last two years, plus the next one Yahoo has declared "
            "for each open position, and — for the rest of the next 52 weeks — "
            "last year's schedule moved forward (`projected`). Oldest first. "
            "Funds included — they pay even though they never report. Empty "
            "when Yahoo is throttled."
        ),
    )
    repurchase_windows: list[RepurchaseWindow] = Field(
        default_factory=list,
        description=(
            "Loss sales whose repurchase window is still open under the "
            "account's jurisdiction, soonest to clear first. Empty where the "
            "country has no such rule."
        ),
    )
    central_banks: list[CentralBankDecision] = Field(
        default_factory=list,
        description=(
            "Every Fed and ECB decision day the calendar carries, oldest first. "
            "Independent of the watchlist."
        ),
    )
    trades: list[CalendarTrade] = Field(
        default_factory=list,
        description=(
            "The ledger's buys and sells over the same two years the past "
            "ex-dates reach, one row per name, day and side. Oldest first. "
            "Broker moves (transfer in/out) are not trades and are left out."
        ),
    )
    payments: list[CalendarPayment] = Field(
        default_factory=list,
        description=(
            "Dividends and returns of capital the statements booked, on the "
            "day the cash landed, over the same two years. Oldest first."
        ),
    )
    market_holidays: list[MarketHoliday] = Field(
        default_factory=list,
        description=(
            "Closures and half sessions of the exchanges the watchlist and "
            "the book trade on (`stocks.data.market_holidays`). Oldest first."
        ),
    )


# ------------------------------------------------------------ one past print
# The result dialog a past chip opens. The calendar payload carries the three
# EPS figures; everything under them — revenue, margins, the GAAP result, the
# surprise record, next quarter's consensus — is per ticker, three Yahoo
# payloads deep, and only worth fetching for the one print somebody clicked.
# Ratios are FRACTIONS (0.183 is 18.3%) as `stocks.data.earnings` computes them;
# the one exception is `price_reaction`, a percentage like `surprise_pct`.


class QuarterFigures(BaseModel):
    """One fiscal quarter as filed (GAAP), plus the ratios derived from it."""

    end: str = Field(description="Fiscal quarter end, ISO — not the report date.")
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    pretax_income: float | None = None
    tax_provision: float | None = None
    rnd: float | None = None
    diluted_eps: float | None = None
    diluted_shares: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    rnd_intensity: float | None = Field(default=None, description="R&D / revenue.")
    tax_rate: float | None = Field(
        default=None, description="Tax provision / pretax income."
    )
    revenue_yoy: float | None = Field(
        default=None,
        description="vs the same fiscal quarter a year back; null on a negative base.",
    )
    revenue_qoq: float | None = Field(
        default=None, description="vs the quarter immediately before."
    )


class QuarterBreakdown(BaseModel):
    """The reported quarter, with every comparison the dialog's tiles print."""

    quarter: QuarterFigures
    revenue_ttm: float | None = Field(
        default=None,
        description="Sum of the last four quarters; null unless all four are known.",
    )
    net_income_yoy: float | None = None
    shares_yoy: float | None = Field(
        default=None,
        description="Diluted share count vs a year back. Up is dilution — the bad way.",
    )
    gross_margin_bps: float | None = Field(
        default=None, description="Margin move vs the year-ago quarter, basis points."
    )
    operating_margin_bps: float | None = None
    net_margin_bps: float | None = None


class ConsensusPeriod(BaseModel):
    """Sell-side consensus for one period. Never company guidance."""

    period: str = Field(description='yfinance label: "0q", "+1q", "0y" or "+1y".')
    eps_avg: float | None = None
    eps_low: float | None = None
    eps_high: float | None = None
    eps_growth: float | None = None
    eps_analysts: int | None = None
    rev_avg: float | None = None
    rev_low: float | None = None
    rev_high: float | None = None
    rev_growth: float | None = None
    rev_analysts: int | None = None
    currency: str | None = None
    currency_prefix: str = Field(
        default="", description='What a figure is printed behind: "$", "€", "CHF ".'
    )


class EarningsResultDetail(BaseModel):
    ticker: str
    name: str = Field(default="", description='"" when no catalog knows the name.')
    logo: str | None = None
    date: str = Field(description="The report date asked about, ISO.")
    result: CalendarResult | None = Field(
        default=None,
        description="The print on that date; null when the feed has no figures for it.",
    )
    price_reaction: float | None = Field(
        default=None,
        description=(
            "% move across the print: last close before the date vs first close "
            "after, so it always contains the gap whatever the report's timing."
        ),
    )
    quarter_state: str = Field(
        default="none",
        description=(
            "`matched` — the income statement for the reported quarter is out; "
            "`pending` — statements exist but this quarter's is not published "
            "yet; `none` — the feed has no quarterly statement for the name."
        ),
    )
    currency: str | None = Field(
        default=None, description="Currency the income statement is filed in."
    )
    currency_prefix: str = ""
    breakdown: QuarterBreakdown | None = None
    trend: list[QuarterFigures] = Field(
        default_factory=list,
        description="Up to five most recent quarters, newest first.",
    )
    eps_gaap_gap: float | None = Field(
        default=None,
        description="Headline EPS minus the filed GAAP diluted EPS: the adjustment.",
    )
    history: list[CalendarResult] = Field(
        default_factory=list,
        description="Every reported print the feed carries for the name, newest first.",
    )
    outlook: ConsensusPeriod | None = Field(
        default=None, description="Next quarter's consensus; null when nobody covers it."
    )
    outlook_periods: list[ConsensusPeriod] = Field(
        default_factory=list,
        description=(
            "The quarter in flight, next quarter and both fiscal years, where known."
        ),
    )
    unavailable: bool = Field(
        default=False,
        description=(
            "The statement or estimate fetch failed this time (usually a rate "
            "limit). The headline still stands; the sections are missing, not empty."
        ),
    )
