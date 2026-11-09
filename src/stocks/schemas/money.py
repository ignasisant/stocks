"""What the book costs, pays and owes: fees, dividends, tax."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ------------------------------------------------------------- the cost of it
# What a trade cost beyond the ticket: the commission the broker charged, and
# the spread it charged without saying so. The two are kept apart everywhere —
# one is a ledger fact, the other an estimate against the day's bars, and
# adding them into a single "fees" number would hide which is which.


class BrokerCost(BaseModel):
    broker: str = Field(description="Ledger note prefix: revolut, clicktrade, manual.")
    trades: int
    volume: float = Field(description="Traded value in the reporting currency.")
    commission: float = Field(description="Explicit commission, from the ledger.")
    other_fees: float = Field(
        default=0.0, description="Standalone fee rows: custody, FX, platform."
    )
    spread: float | None = Field(
        default=None,
        description=(
            "Estimated cost against the trade day's mid — signed, so a negative "
            "figure means the execution beat the mid. Null when no bar could be "
            "read for this broker's trades."
        ),
    )
    spread_bps: float | None = Field(
        default=None, description="`spread` over measured volume, in basis points."
    )
    measured: int = Field(
        default=0, description="Trades with a usable bar on the trade date."
    )
    skipped: int = Field(
        default=0, description="Trades the spread pass could not measure."
    )
    outside_range: float = Field(
        default=0.0,
        description="Executions beyond the day's high/low — a data smell, not a cost.",
    )
    total: float | None = Field(
        default=None, description="Commission + other fees + spread, when measured."
    )
    cost_pct: float | None = Field(
        default=None, description="`total` over this broker's volume."
    )


class Fees(BaseModel):
    base: str
    brokers: list[BrokerCost] = Field(default_factory=list)
    explicit: float = Field(
        default=0.0, description="Commission and fees across every broker."
    )
    spread: float | None = Field(
        default=None,
        description="Estimated spread across every broker; null when unmeasured.",
    )
    cost: float | None = Field(
        default=None,
        description=(
            "Commission plus each broker's spread paid; a broker that beat the "
            "mid adds nothing, never less. Null when unmeasured."
        ),
    )
    volume: float = Field(default=0.0)
    cost_pct: float | None = Field(
        default=None, description="Total cost over traded volume; null with no volume."
    )
    spread_measured: bool = Field(
        default=False,
        description=(
            "Whether the trade-day bars came back at all. False means every "
            "spread field is null because Yahoo was unreachable, NOT that the "
            "book traded at the mid."
        ),
    )


# --------------------------------------------------------------- what it pays
# Two different things with the same unit, so they never share a field: what
# the ledger was paid (a receipt) and what the shares were entitled to (an
# estimate from Yahoo's per-share history). A book whose import carried no
# dividend rows still has an estimate, and it must not read as income received.


class DividendYear(BaseModel):
    year: int
    gross: float
    withheld: float
    net: float
    creditable: float = Field(
        description="Foreign tax creditable at home, capped at the treaty rate."
    )
    reclaimable: float = Field(
        description="Withholding above the cap — reclaim from the source country."
    )
    estimated_gross: float | None = Field(
        default=None, description="What the shares were entitled to that year."
    )
    unrecorded: float | None = Field(
        default=None,
        description="Entitlement with no ledger row behind it: a gap in the import.",
    )


class ForwardHolding(BaseModel):
    ticker: str
    shares: float
    per_share: float = Field(description="Summed over the trailing 12 months.")
    payments: int = Field(description="Ex-dates in those 12 months; 4 = quarterly.")
    currency: str
    gross: float = Field(description="`per_share` * `shares`, in that currency.")
    gross_base: float | None = Field(
        default=None, description="The same, in the reporting currency."
    )
    last_ex: str | None = None


class Dividends(BaseModel):
    base: str
    years: list[DividendYear] = Field(default_factory=list)
    booked_total: float = Field(default=0.0, description="Gross ever booked.")
    booked_ytd: float = Field(default=0.0)
    estimated_total: float | None = None
    estimated_ytd: float | None = None
    forward_annual: float | None = Field(
        default=None,
        description="Next year's income at the trailing 12m rate, if nothing is sold.",
    )
    forward: list[ForwardHolding] = Field(default_factory=list)
    estimates_available: bool = Field(
        default=False,
        description=(
            "Whether the entitlement pass ran. False leaves every estimate null "
            "— the book may still pay, nobody could check."
        ),
    )


class UnbookedDividend(BaseModel):
    ticker: str
    ex_date: str = Field(
        description="Entitlement day — the cash lands weeks later, on a pay date "
        "this estimate does not know."
    )
    per_share: float = Field(description="Split-adjusted, in `currency`.")
    shares: float = Field(description="Held at the close before the ex-date.")
    currency: str
    gross: float = Field(description="`per_share` * `shares`, before withholding.")
    amount: float | None = Field(
        default=None,
        description="`gross` in the reporting currency at the ex-date's rate; "
        "null when that day has no rate.",
    )


class UnbookedDividends(BaseModel):
    base: str
    total: int = Field(default=0, description="Payments found, before `limit`.")
    payments: list[UnbookedDividend] = Field(
        default_factory=list,
        description=(
            "Newest first. Estimates, never receipts: a client listing them "
            "beside ledger rows has to mark each one as such."
        ),
    )
    available: bool = Field(
        default=False,
        description=(
            "Whether the entitlement pass ran. False with no payments means "
            "nobody could check, not that nothing is owed."
        ),
    )


# ------------------------------------------------------------------ what it owes
# The jurisdiction is not a parameter of this endpoint: it is the account's own
# setting, and the ledger is replayed *at* that jurisdiction's currency and
# matching rule rather than converted afterwards. A US filer's basis is USD at
# each trade date, which is two rates and not one.


class TaxKpi(BaseModel):
    name: str = Field(description="Jurisdiction-neutral key, e.g. net_taxable.")
    value: float
    help: str = Field(default="", description="i18n key for the explanation.")


class TaxPeriod(BaseModel):
    period: str = Field(description='ISO prefix: "2024" for a year, "2024-03" a month.')
    realized_gain: float
    realized_loss: float
    disallowed_loss: float = Field(
        default=0.0, description="Blocked this period by the repurchase rule."
    )
    recovered_loss: float = Field(
        default=0.0, description="Earlier blocked losses that became deductible now."
    )
    deductible_loss: float = 0.0
    dividends: float = Field(
        default=0.0,
        description=(
            "Gross dividends paid in the period, where the jurisdiction taxes "
            "them in this base (Spain's base del ahorro) and so in `net_taxable`; "
            "0 everywhere else."
        ),
    )
    net_taxable: float
    estimated_tax: float
    carryforward_loss: float = 0.0
    sales: int = Field(default=0, description="Matched parcels in the period.")
    kpis: list[TaxKpi] = Field(default_factory=list)
    year_label: str = Field(
        default="",
        description=(
            'How the jurisdiction writes this tax year — "2025", or "2025/26" '
            "for a UK or Australian year that opens mid-calendar. Empty for a "
            "month. `period` stays the sortable key; this is what to print."
        ),
    )
    notes: list[TaxNote] = Field(
        default_factory=list,
        description=(
            "The sentences the jurisdiction appends under this period's "
            "figures (deferred losses, allowances used, a rate year borrowed), "
            "as catalog keys the client resolves the same way the KPI names "
            "are — `portfolio.<code>_<key>` first, then `portfolio.<key>`."
        ),
    )


class TaxNote(BaseModel):
    """One localized sentence under a period's figures: a key and its slots.

    Language-neutral on purpose, like `TaxKpi`: the number slots arrive already
    formatted (`"1,240"`), so a client only substitutes and never re-derives.
    """

    key: str
    kwargs: dict[str, str] = Field(default_factory=dict)


class TaxFlag(BaseModel):
    """A foreign-asset reporting threshold — Modelo 720, FBAR, Form 8938…

    `reportable` means the threshold is crossed, not that a filing is due:
    whether it applies depends on where the assets actually sit, which the
    ledger does not know. Hence a flag the client words as "may apply", never
    a verdict.
    """

    name: str = Field(description="i18n suffix: modelo_720, fbar, form_8938…")
    reportable: bool
    total_value: float = Field(
        description="The open book priced (cost where unpriced), in `currency`."
    )
    threshold: float = Field(description="The line, in the jurisdiction's currency.")


class TaxAllYears(BaseModel):
    """Every finished tax year added up — a history, not a taxable base.

    Deliberately NOT a `TaxPeriod`, and the difference is the whole reason this
    model exists: allowances reset, brackets restart and a loss only crosses a
    year boundary as a carryforward, so there is no such thing as "net taxable
    over five years". Replaying the ledger as one long period would run five
    years of gains up a single progressive scale and invent a tax nobody owes;
    summing the years' own figures cannot, which is why the totals arrive as
    `kpis` — each year's engine computed its own, and these are those, added.
    """

    years: list[int] = Field(description="The tax years summed, oldest first.")
    realized_gain: float
    realized_loss: float
    disallowed_loss: float = 0.0
    recovered_loss: float = 0.0
    deductible_loss: float = 0.0
    dividends: float = 0.0
    sales: int = Field(default=0, description="Matched parcels across them all.")
    kpis: list[TaxKpi] = Field(
        default_factory=list,
        description="Each year's KPIs summed by key, in first-seen order.",
    )


class TaxSale(BaseModel):
    ticker: str
    buy_date: str = Field(
        description="Acquisition; for a pooled holding, the earliest still held."
    )
    sell_date: str
    quantity: float
    cost: float
    proceeds: float
    gain: float
    matched: str = Field(description="fifo | lifo | average | s104 | pool.")
    term: str | None = Field(
        default=None,
        description=(
            '"long" or "short" where the jurisdiction taxes the two holding '
            "periods differently (US, AU, PT); null where it does not — Spain "
            "taxes a gain the same after a week or a decade, and a column "
            "saying so would be noise."
        ),
    )


class TaxReport(BaseModel):
    jurisdiction: str = Field(description="ES, US, UK… — the account's own setting.")
    resolved: str = Field(
        description=(
            "How that was arrived at: chosen | region | unmodelled | unknown. "
            "`unmodelled` means the caller's country is not modelled and these "
            "are somebody else's rules — a client has to say so."
        )
    )
    currency: str = Field(description="The jurisdiction's currency, not `base`.")
    matching: str = Field(description="Share-matching rule this replay used.")
    years: list[TaxPeriod] = Field(default_factory=list)
    all_years: TaxAllYears | None = Field(
        default=None,
        description=(
            "Those years added together, for a book that has more than one. "
            "Null when there is only one — it is already all of them, and an "
            "option that repeats the view below it is a control that does "
            "nothing."
        ),
    )
    months: list[TaxPeriod] = Field(
        default_factory=list,
        description=(
            "The same result by month booked. A breakdown, never a taxable base: "
            "every jurisdiction here nets over its own tax year."
        ),
    )
    sales: list[TaxSale] = Field(default_factory=list)
    funds_classified: bool = Field(
        default=False,
        description=(
            "Whether fund holdings were identified (DE exempts 30% of a fund's "
            "result). False = nobody checked, so no exemption was applied."
        ),
    )
    flags: list[TaxFlag] = Field(
        default_factory=list,
        description=(
            "Foreign-asset reporting thresholds measured against today's open "
            "book, converted to the jurisdiction's currency at spot — a "
            "threshold check, not a basis. Empty when the book could not be "
            "priced or the rate could not be fetched: no line beats a wrong one."
        ),
    )
