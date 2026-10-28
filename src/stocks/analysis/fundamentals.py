"""Fundamental KPIs: computation from raw statements + source-of-truth map.

Pure functions over RawFundamentals so tests run offline.

Three reliability levels apply to every number shown downstream:
  fact       — verifiable in a primary source (SEC EDGAR 10-K/10-Q)
  consensus  — market/analyst aggregate (forward P/E, PEG)
  derived    — computed here from statements (ROIC, FCF yield, CAGRs)
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from stocks.analysis import ranking
from stocks.analysis.listing import quote_unit
from stocks.analysis.moat import moat_score
from stocks.data import fetch, fx
from stocks.data.fundamentals import RawFundamentals
from stocks.portfolio import consistency


@dataclass(frozen=True)
class KpiSource:
    label: str
    unit: str  # "x" multiple | "pct" | "money" | "ratio"
    level: str  # fact | consensus | derived
    loader: str  # where the toolkit loads it from
    verify: str  # where to cross-check before acting on it
    note: str = ""
    desc: str = ""  # plain-language definition, surfaced as help tooltips in the UI


# Ordered map: KPI key -> how it is loaded and where it must be verified.
# Verification hierarchy: SEC EDGAR (primary) > stockanalysis.com (10y ratios)
# > macrotrends (15-20y trends) > Koyfin/TIKR (multi-company comps).
KPI_SOURCES: dict[str, KpiSource] = {
    "price": KpiSource(
        "Price",
        "money",
        "fact",
        "yfinance info.currentPrice",
        "exchange quote / TradingView",
        desc="Latest traded price per share, in the listing currency.",
    ),
    "market_cap": KpiSource(
        "Market cap",
        "money",
        "fact",
        "yfinance info.marketCap",
        "stockanalysis.com",
        desc="Share price × shares outstanding — what the market says the equity is "
        "worth.",
    ),
    "ev": KpiSource(
        "Enterprise value",
        "money",
        "derived",
        "yfinance info.enterpriseValue",
        "stockanalysis.com",
        "cap + net debt; check debt against latest 10-Q on EDGAR",
        desc="Market cap plus debt minus cash — the price of the whole business, not "
        "just the equity.",
    ),
    "pe_ttm": KpiSource(
        "P/E (TTM)",
        "x",
        "fact",
        "yfinance info.trailingPE",
        "EDGAR EPS (10-K/10-Q) + spot price",
        "on normalized income when one-offs move the four quarters' profit by "
        "over a quarter",
        desc="Price / earnings per share over the trailing twelve months. Lower = "
        "cheaper per unit of current profit.",
    ),
    "pe_fwd": KpiSource(
        "P/E (fwd)",
        "x",
        "consensus",
        "yfinance info.forwardPE",
        "Koyfin/TIKR analyst consensus",
        desc="Price / next-year consensus EPS. Below the TTM P/E means analysts expect "
        "earnings to grow.",
    ),
    "peg": KpiSource(
        "P/E per growth",
        "x",
        "derived",
        "forward (else trailing) P/E / sustained sales growth per share",
        "Koyfin/TIKR consensus growth",
        "growth capped at 40%; blank without a positive P/E and positive growth",
        desc="P/E over sustained sales growth per share (net of dilution). 1x or under "
        "is cheap for its growth; 2.5x is dear.",
    ),
    "pb": KpiSource(
        "P/B",
        "x",
        "fact",
        "yfinance info.priceToBook",
        "EDGAR balance sheet equity",
        desc="Price / book (accounting) value per share. Most meaningful for banks and "
        "asset-heavy businesses.",
    ),
    "ev_ebitda": KpiSource(
        "EV/EBITDA",
        "x",
        "derived",
        "yfinance info.enterpriseToEbitda",
        "stockanalysis.com / TIKR",
        desc="Enterprise value / earnings before interest, tax, depreciation & "
        "amortisation — a P/E that ignores capital structure, comparable across "
        "leverage.",
    ),
    "ev_sales": KpiSource(
        "EV/Sales",
        "x",
        "derived",
        "yfinance info.enterpriseToRevenue",
        "stockanalysis.com / TIKR",
        desc="Enterprise value / revenue. The fallback multiple for high-growth or "
        "not-yet-profitable names where P/E breaks down.",
    ),
    "roe": KpiSource(
        "ROE",
        "pct",
        "fact",
        "yfinance info.returnOnEquity",
        "EDGAR NI / equity",
        desc="Return on equity: net income / shareholder equity. Profitability of the "
        "equity base — note leverage inflates it.",
    ),
    "roic": KpiSource(
        "ROIC",
        "pct",
        "derived",
        "computed: EBIT*(1-tax) / invested capital (yfinance statements)",
        "stockanalysis.com / macrotrends (definitions differ — compare method)",
        desc="Return on invested capital: after-tax operating profit / all capital "
        "employed (equity + debt). How well the whole business compounds; >15% sustained "
        "is a quality mark.",
    ),
    "gross_margin": KpiSource(
        "Gross margin",
        "pct",
        "fact",
        "yfinance info.grossMargins",
        "EDGAR income statement",
        desc="Revenue minus cost of goods sold, as % of revenue — pricing power on the "
        "product itself.",
    ),
    "op_margin": KpiSource(
        "Operating margin",
        "pct",
        "fact",
        "yfinance info.operatingMargins",
        "EDGAR income statement",
        desc="Operating profit as % of revenue — what the core business keeps after "
        "operating costs.",
    ),
    "net_margin": KpiSource(
        "Net margin",
        "pct",
        "fact",
        "yfinance info.profitMargins",
        "EDGAR income statement",
        desc="Net income as % of revenue — the bottom line after interest and tax.",
    ),
    "fcf": KpiSource(
        "FCF (last FY)",
        "money",
        "fact",
        "yfinance cashflow 'Free Cash Flow'",
        "EDGAR 10-K cash flow (CFO - capex)",
        desc="Free cash flow: operating cash flow minus capital expenditure — the cash "
        "left over to pay dividends, buy back shares or reinvest.",
    ),
    "fcf_yield": KpiSource(
        "FCF yield",
        "pct",
        "derived",
        "computed: FCF / market cap",
        "stockanalysis.com",
        desc="Free cash flow / market cap — the cash return you buy at today's price "
        "(the inverse of the FCF multiple).",
    ),
    "net_debt_ebitda": KpiSource(
        "Net debt / EBITDA",
        "x",
        "derived",
        "computed from yfinance balance + income",
        "EDGAR 10-K/10-Q debt notes",
        "negative = net cash",
        desc="Debt minus cash, divided by EBITDA — roughly the years of operating profit "
        "needed to repay the debt. <1 conservative, >3 heavy; negative = more cash than "
        "debt.",
    ),
    "cash_conversion": KpiSource(
        "Cash conversion (FCF/NI)",
        "x",
        "derived",
        "computed from yfinance statements",
        "EDGAR 10-K",
        ">1 sustained is a quality signal; <1 check accruals",
        desc="Free cash flow / net income — how much of accounting profit turns into "
        "actual cash.",
    ),
    "revenue_cagr": KpiSource(
        "Revenue CAGR (5y stmts)",
        "pct",
        "derived",
        "computed from yfinance annual income",
        "macrotrends (longer window)",
        desc="Compound annual growth rate of revenue over the last ~5 fiscal years of "
        "filed statements.",
    ),
    "net_income_cagr": KpiSource(
        "Net income CAGR (5y stmts)",
        "pct",
        "derived",
        "computed from yfinance annual income",
        "macrotrends",
        desc="Compound annual growth rate of net income over the last ~5 fiscal years.",
    ),
    "fcf_cagr": KpiSource(
        "FCF CAGR (5y stmts)",
        "pct",
        "derived",
        "computed from yfinance annual cashflow",
        "macrotrends",
        desc="Compound annual growth rate of free cash flow over the last ~5 fiscal "
        "years.",
    ),
    "share_dilution": KpiSource(
        "Diluted shares CAGR",
        "pct",
        "derived",
        "computed from yfinance 'Diluted Average Shares', annual to latest quarter",
        "EDGAR 10-K share counts",
        "positive = dilution (SBC), negative = net buybacks",
        desc="Yearly change in diluted share count. Positive = you're being diluted "
        "(usually stock comp); negative = net buybacks shrinking the share count.",
    ),
    "moat": KpiSource(
        "Moat score",
        "score",
        "derived",
        "computed: ROIC persistence, margin stability, growth, FCF, dilution "
        "(yfinance statements)",
        "your own qualitative judgement + Morningstar moat rating",
        "quant proxies only — cannot see brand, network effects or switching costs",
        desc="0-100 heuristic of how much moat *evidence* the filings show: "
        "persistent ROIC (35%), steady operating margins (25%), cash conversion "
        "(20%), durable growth (15%), no dilution (5%). ≥70 wide, 45-70 narrow, "
        "<45 no moat. A screen, not a verdict.",
    ),
    # The lens KPIs: read on the company grid of the business they judge, and
    # nowhere else (`_LENS_ONLY`). A bank's price to tangible book is its P/E;
    # a telecom's is 30x and means nothing.
    "ptbv": KpiSource(
        "P/TBV",
        "x",
        "derived",
        "market cap / Tangible Book Value (yfinance balance sheet)",
        "EDGAR equity less goodwill & intangibles",
        desc="Price / tangible book: book value without goodwill and intangibles. "
        "How a bank is priced; 1x is its net assets at cost.",
    ),
    "rotce": KpiSource(
        "ROTCE",
        "pct",
        "derived",
        "net income to common / Tangible Book Value (yfinance statements)",
        "EDGAR NI / tangible equity",
        desc="Return on tangible common equity: what a bank earns on the capital "
        "it could lose. Over 15% is a strong lender.",
    ),
    "dividend_yield": KpiSource(
        "Dividend yield",
        "pct",
        "fact",
        "yfinance info.dividendYield",
        "company dividend history",
        desc="Dividends of the last year over the price. What a landlord or a "
        "utility is mostly bought for.",
    ),
    "payout_ratio": KpiSource(
        "Payout",
        "pct",
        "fact",
        "yfinance info.payoutRatio",
        "EDGAR dividends paid / net income",
        desc="Share of the year's earnings paid out. A REIT pays most of them by "
        "law; anyone else over 100% pays from somewhere else.",
    ),
}

#: KPIs only one lens's grid reads. Out of `METRIC_ORDER`, so the comps table
#: and the sector screen do not grow a row every other company leaves blank.
_LENS_ONLY = frozenset({"ptbv", "rotce", "dividend_yield", "payout_ratio"})

METRIC_ORDER = [key for key in KPI_SOURCES if key not in _LENS_ONLY]


@dataclass(frozen=True)
class Tile:
    """One tile of the fundamentals grid a company page shows.

    `KPI_SOURCES` is every KPI this toolkit computes — 23 of them, most of
    which belong in a reference table rather than on a screen. This is the
    handful a reader is shown, in the order they are shown, and it is here
    rather than in a page because two front ends draw that grid now.

    `label` and `help` are i18n *key names*, not strings: which string a tile
    carries is a decision, the string itself is a translation, and a payload
    that travels between a Spanish reader and an English one must carry the
    first without picking the second. A client with no catalog entry falls
    back to `KpiSource.label`, which is English and is better than a slug.
    """

    key: str  # into KPI_SOURCES
    label: str  # i18n key for the tile's caption
    help: str | None = None  # i18n key overriding KpiSource.desc as the tooltip


# The company grid: valuation first, then returns, then the balance sheet, then
# what the share count has been doing. Nine tiles, because a grid somebody has
# to scan is a grid nobody reads.
FUNDAMENTAL_TILES: tuple[Tile, ...] = (
    Tile("pe_ttm", "ticker.kpi_pe_ttm"),
    Tile("pe_fwd", "ticker.kpi_pe_fwd"),
    # Ours, not Yahoo's: forward P/E over sustained per-share sales growth
    # (`review.growth_pe`). The tooltip says what it divides by.
    Tile("peg", "ticker.kpi_peg", "ticker.kpi_peg_help"),
    Tile("ev_ebitda", "ticker.kpi_ev_ebitda"),
    Tile("ev_sales", "ticker.kpi_ev_sales"),
    Tile("roic", "ticker.kpi_roic"),
    Tile("fcf_yield", "ticker.kpi_fcf_yield"),
    Tile("net_debt_ebitda", "ticker.kpi_net_debt_ebitda"),
    Tile("share_dilution", "ticker.kpi_dilution"),
)

# The same nine for a business another lens judges (`review.lens`). A bank has
# no EBITDA and its free cash flow is deposits moving: it is read on book and
# the return on it. A landlord and a utility are bought for the payout and
# carry debt on purpose, so EV/EBITDA and the yield replace sales and FCF.
_LENS_TILES: dict[str, tuple[Tile, ...]] = {
    "financial": (
        Tile("pe_ttm", "ticker.kpi_pe_ttm"),
        Tile("pe_fwd", "ticker.kpi_pe_fwd"),
        Tile("pb", "ticker.kpi_pb"),
        Tile("ptbv", "ticker.kpi_ptbv"),
        Tile("roe", "ticker.kpi_roe"),
        Tile("rotce", "ticker.kpi_rotce"),
        Tile("dividend_yield", "ticker.kpi_dividend_yield"),
        Tile("payout_ratio", "ticker.kpi_payout"),
        Tile("share_dilution", "ticker.kpi_dilution"),
    ),
    "real_estate": (
        Tile("pe_ttm", "ticker.kpi_pe_ttm"),
        Tile("pe_fwd", "ticker.kpi_pe_fwd"),
        Tile("pb", "ticker.kpi_pb"),
        Tile("ev_ebitda", "ticker.kpi_ev_ebitda"),
        Tile("dividend_yield", "ticker.kpi_dividend_yield"),
        Tile("payout_ratio", "ticker.kpi_payout"),
        Tile("roe", "ticker.kpi_roe"),
        Tile("net_debt_ebitda", "ticker.kpi_net_debt_ebitda"),
        Tile("share_dilution", "ticker.kpi_dilution"),
    ),
}
_LENS_TILES["utility"] = _LENS_TILES["real_estate"]


def fundamental_tiles(view: str) -> tuple[Tile, ...]:
    """The company grid for a business judged on `view` (`review.lens`)."""
    return _LENS_TILES.get(view, FUNDAMENTAL_TILES)


def cagr(start: float | None, end: float | None, years: float) -> float | None:
    """Compound annual growth rate; None when undefined (sign flips, zeros)."""
    if not start or not end or years <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


# One-offs (gains on securities, write-downs) moving the four quarters' profit
# by more than this share of the normalized one: the trailing P/E reads that.
ONE_OFF_SHARE = 0.25


def _row(df: pd.DataFrame, label: str) -> pd.Series | None:
    if df is None or df.empty or label not in df.index:
        return None
    row = df.loc[label].dropna()
    return row if not row.empty else None


def _latest(df: pd.DataFrame, label: str) -> float | None:
    """Most recent annual value (yfinance columns are newest-first)."""
    row = _row(df, label)
    return float(row.iloc[0]) if row is not None else None


def latest_net_debt(raw: RawFundamentals) -> float | None:
    """Debt less cash at the last balance sheet. Yahoo leaves "Net Debt" blank
    in a year when cash is the larger (Elastic, PDD), so the row's newest value
    was a year it had debt: net cash read as leverage. Rebuilt from the same
    column instead, and only past it from the quote's own figures."""
    bal = raw.balance
    if bal is not None and not bal.empty:
        col = pd.to_numeric(bal.iloc[:, 0], errors="coerce")

        def cell(label: str) -> float | None:
            v = col.get(label)
            return float(v) if v is not None and pd.notna(v) else None

        net = cell("Net Debt")
        if net is not None:
            return net
        debt = cell("Total Debt")
        cash = cell("Cash Cash Equivalents And Short Term Investments")
        if cash is None:
            cash = cell("Cash And Cash Equivalents")
        if debt is not None and cash is not None:
            return debt - cash
    debt, cash = raw.info.get("totalDebt"), raw.info.get("totalCash")
    return debt - cash if debt is not None and cash is not None else None


def _ttm(df: pd.DataFrame, label: str) -> float | None:
    """The last four quarters' sum, or None when any of them is missing: a
    gap would reach back to a fifth quarter and sum another year."""
    if df is None or df.empty or label not in df.index or df.shape[1] < 4:
        return None
    row = pd.to_numeric(df.loc[label].iloc[:4], errors="coerce")
    return float(row.sum()) if row.notna().all() else None


def _series_cagr(df: pd.DataFrame, label: str) -> float | None:
    """CAGR across available annual columns (newest-first)."""
    row = _row(df, label)
    if row is None or len(row) < 2:
        return None
    newest, oldest = float(row.iloc[0]), float(row.iloc[-1])
    return cagr(oldest, newest, years=len(row) - 1)


def _dilution(raw: RawFundamentals) -> float | None:
    """Diluted shares CAGR from the oldest filed year to the latest quarter.

    The annual series alone ends at the last 10-K, up to a year old, and a
    company issuing fast (CoreWeave: 487M to 551M shares in a year) read 2.5 %
    off a pre-IPO count restated flat. The newest quarter after that year is
    the end point when the feed has one; the span is then measured in days.
    """
    annual = _row(raw.income, "Diluted Average Shares")
    quarter = _row(raw.income_q, "Diluted Average Shares")
    if annual is None or quarter is None:
        return _series_cagr(raw.income, "Diluted Average Shares")
    newest, oldest = pd.to_datetime([quarter.index[0], annual.index[-1]], errors="coerce")
    last_year = pd.to_datetime(annual.index[0], errors="coerce")
    if pd.isna(newest) or pd.isna(oldest) or pd.isna(last_year) or newest <= last_year:
        return _series_cagr(raw.income, "Diluted Average Shares")
    years = (newest - oldest).days / 365.25
    return cagr(float(annual.iloc[-1]), float(quarter.iloc[0]), years=years)


def annual_financials(raw: RawFundamentals) -> pd.DataFrame:
    """Annual Revenue, Net Income, Diluted EPS for charting — oldest-first.

    Columns present only when the underlying row exists. Index is the fiscal
    year (int). Empty DataFrame when the income statement is unavailable.
    """
    income = raw.income
    if income is None or income.empty:
        return pd.DataFrame()
    eps_label = next(
        (lbl for lbl in ("Diluted EPS", "Basic EPS") if lbl in income.index), None
    )
    wanted = [("Total Revenue", "Revenue"), ("Net Income", "Net Income")]
    if eps_label:
        wanted.append((eps_label, "EPS"))
    present = [(src, dst) for src, dst in wanted if src in income.index]
    if not present:
        return pd.DataFrame()
    df = income.loc[[src for src, _ in present]].T
    df.columns = [dst for _, dst in present]
    df.index = [getattr(c, "year", c) for c in df.index]  # period-end -> fiscal year
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.iloc[::-1]  # yfinance is newest-first; charts read left-to-right


def quarterly_eps(raw: RawFundamentals) -> pd.DataFrame:
    """Quarterly Diluted (fallback Basic) EPS for charting — oldest-first.

    Index is a "YYYYQn" period label. Empty DataFrame when the quarterly
    income statement or an EPS row is unavailable.
    """
    income = raw.income_q
    if income is None or income.empty:
        return pd.DataFrame()
    eps_label = next(
        (lbl for lbl in ("Diluted EPS", "Basic EPS") if lbl in income.index), None
    )
    if eps_label is None:
        return pd.DataFrame()
    df = income.loc[[eps_label]].T
    df.columns = ["EPS"]
    df.index = [
        f"{c.year}Q{c.quarter}" if hasattr(c, "quarter") else str(c) for c in df.index
    ]
    df = df.apply(pd.to_numeric, errors="coerce")
    return df.iloc[::-1]  # yfinance is newest-first; charts read left-to-right


def _statement_fx(info: dict) -> float | None:
    """Units of the quote currency per unit of the filing currency.

    Statements are filed in `financialCurrency`, the price is quoted in
    `currency`, and an ADR mixes the two: Novo Nordisk files in DKK and trades
    in USD, Alibaba files in CNY. 1.0 when they agree or either is unknown
    (case folded, so a London line quoted in GBp against GBP filings is not a
    mismatch); None when they differ and no rate could be had, so a ratio is
    left blank rather than computed across two currencies.
    """
    filed, quoted = info.get("financialCurrency"), info.get("currency")
    if not filed or not quoted or str(filed).upper() == str(quoted).upper():
        return 1.0
    try:
        return fx.spot(str(filed), str(quoted))[0]
    except Exception:  # noqa: BLE001 - the ECB does not quote every currency
        pass
    # TWD (TSMC) is not an ECB currency; Yahoo quotes the pair itself.
    try:
        quote = fetch.info(f"{filed}{quoted}=X")
        rate = quote.get("regularMarketPrice") or quote.get("previousClose")
        return float(rate) if rate else None
    except Exception:  # noqa: BLE001 - an unquoted pair is a blank, not a crash
        return None


def _dividend(
    info: dict,
    owner_fcf: float | None,
    paid: float | None = None,
    *,
    symbol: str = "",
) -> dict:
    """Yield, payout and the dividend against the owner's free cash flow
    (`paid` and `owner_fcf` over the same years, see `_dividend_cover`).

    The yield is Yahoo's `dividendYield`, which yfinance answers in percent
    and which reads true across listings. Without it, the rate over the
    price, else Yahoo's trailing yield, but only where the dividend and the
    price share a unit: London's pence carry a rate in the dividend's major
    currency (HSBC's dollars over a price in pence), and an ADR's rate and
    trailing yield come in the filing currency (TSMC's TWD over a dollar
    price read 5.9% for a 1% payer). Out-of-range figures are the feed's,
    not a payer's, and read as missing.
    """
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    rate = info.get("dividendRate")
    pct = info.get("dividendYield")
    quoted = info.get("currency")
    filed = info.get("financialCurrency")
    one_unit = quote_unit(quoted)[1] == 1.0 and filed in (None, quoted)
    if isinstance(pct, (int, float)):
        y = pct / 100
    elif not one_unit:
        y = None
    elif rate and price:
        y = rate / price
    else:
        y = info.get("trailingAnnualDividendYield")
    payout = info.get("payoutRatio")
    out = {
        "dividend_yield": y if isinstance(y, (int, float)) and 0 < y < 0.25 else None,
        "payout_ratio": (
            payout if isinstance(payout, (int, float)) and 0 < payout < 5 else None
        ),
        "dividend_fcf": None,
    }
    for field, raw, kept in (
        ("yield", y, out["dividend_yield"]),
        ("payout", payout, out["payout_ratio"]),
    ):
        if isinstance(raw, (int, float)) and raw > 0 and kept is None:
            consistency.report(
                "feed_dividend",
                source="feed",
                ticker=symbol,
                key=field,
                field=field,
                value=round(float(raw), 3),
            )
    if paid is not None and paid < 0 and owner_fcf and owner_fcf > 0:
        out["dividend_fcf"] = -paid / owner_fcf
    return out


def _dividend_cover(cashflow: pd.DataFrame) -> tuple[float | None, float | None]:
    """Owner's free cash flow and dividends paid, each summed over the filed
    years that carry both: one year's dip (Coca-Cola's 2024 tax deposit) is
    not a payout the business cannot keep. Both in the filing currency."""
    paid = _row(cashflow, "Cash Dividends Paid")
    if paid is None:
        paid = _row(cashflow, "Common Stock Dividend Paid")
    fcf = _row(cashflow, "Free Cash Flow")
    if paid is None or fcf is None:
        return None, None
    sbc = _row(cashflow, "Stock Based Compensation")
    years = [y for y in paid.index if y in fcf.index]
    if not years:
        return None, None
    owner = 0.0
    for y in years:
        pay = float(sbc[y]) if sbc is not None and y in sbc.index else 0.0
        owner += float(fcf[y]) - max(pay, 0.0)
    return owner, float(sum(float(paid[y]) for y in years))


def _turnover_usd(info: dict, price: float | None) -> float | None:
    """Not a KPI: what trades in a day, in dollars, over the last three
    months (price times average volume). The review's "can you get in and
    out" test; a small cap's spread and price impact live here."""
    volume = info.get("averageVolume") or info.get("averageDailyVolume10Day")
    iso, scale = quote_unit(info.get("currency"))
    if not price or not volume or not iso:
        return None
    try:
        rate = 1.0 if iso == "USD" else fx.spot(iso, "USD")[0]
    except Exception:  # noqa: BLE001 - an unquoted currency is a blank
        return None
    return float(price) * float(volume) * scale * rate


def _cash_backing(raw: RawFundamentals) -> float | None:
    """Operating cash flow over net income, each summed over the filed years
    that carry both: one year's working-capital swing is not a habit. None
    when the summed earnings are not a profit."""
    cfo = _row(raw.cashflow, "Operating Cash Flow")
    earned = _row(raw.income, "Net Income")
    if cfo is None or earned is None:
        return None
    years = [y for y in earned.index if y in cfo.index]
    profit = float(sum(float(earned[y]) for y in years))
    if len(years) < 2 or profit <= 0:
        return None
    return float(sum(float(cfo[y]) for y in years)) / profit


def compute_metrics(raw: RawFundamentals) -> dict[str, float | str | None]:
    """All KPIs for one ticker. Missing data -> None, never invented."""
    info = raw.info
    m: dict[str, float | str | None] = {"ticker": raw.ticker}
    m["currency"] = info.get("currency")
    # Yahoo's instrument kind (EQUITY / ETF / MUTUALFUND). Not a KPI and not in
    # METRIC_ORDER, so it never reaches a screen column — it is here because
    # this is the one place that already holds `info`, and cross-sectional
    # callers need to know a row is a fund whose every ratio will be blank.
    m["quote_type"] = info.get("quoteType")
    m["price"] = info.get("currentPrice") or info.get("regularMarketPrice")
    m["turnover_usd"] = _turnover_usd(info, m["price"])
    # Not a KPI: the share the company's own people hold (Yahoo's, any market).
    m["insider_share"] = info.get("heldPercentInsiders")
    m["market_cap"] = info.get("marketCap")
    m["ev"] = info.get("enterpriseValue")
    m["pe_ttm"] = info.get("trailingPE")
    m["pe_fwd"] = info.get("forwardPE")
    m["pb"] = info.get("priceToBook")
    m["ev_ebitda"] = info.get("enterpriseToEbitda")
    m["ev_sales"] = info.get("enterpriseToRevenue")
    m["roe"] = info.get("returnOnEquity")
    m["gross_margin"] = info.get("grossMargins")
    m["op_margin"] = info.get("operatingMargins")
    m["net_margin"] = info.get("profitMargins")
    # Not KPIs (no catalog entry, no screen column): the facts the review
    # engine needs to tell a business still building its product — a
    # clinical-stage biotech — from one that has stopped earning.
    m["industry"] = info.get("industry")
    revenue = _latest(raw.income, "Total Revenue")
    m["revenue"] = revenue
    if not revenue:
        # Yahoo answers a margin of 0 on no sales; there is no margin to read.
        m["gross_margin"] = m["op_margin"] = m["net_margin"] = None

    # -- derived from statements --
    ebit = _latest(raw.income, "EBIT")
    tax_rate = _latest(raw.income, "Tax Rate For Calcs")
    invested = _latest(raw.balance, "Invested Capital")
    m["roic"] = (
        ebit * (1 - tax_rate) / invested
        if ebit is not None and tax_rate is not None and invested
        else None
    )
    # Not a KPI: the return on the capital the business runs on, for the
    # review engine. An acquirer's invested capital carries the premium it
    # paid (goodwill) and its operating profit the write-down of what it
    # bought (amortisation of intangibles); neither is the business's own.
    goodwill = _latest(raw.balance, "Goodwill")
    amortised = _latest(raw.income, "Amortization Of Intangibles Income Statement")
    own = invested - goodwill if invested and goodwill and goodwill > 0 else None
    m["roic_ex_goodwill"] = (
        (ebit + (amortised or 0.0)) * (1 - tax_rate) / own
        if own is not None and own > 0 and ebit is not None and tax_rate is not None
        else None
    )

    fcf = _latest(raw.cashflow, "Free Cash Flow")
    m["fcf"] = fcf
    rate = _statement_fx(info)
    if rate is None:
        consistency.report(
            "feed_currency",
            source="feed",
            ticker=raw.ticker,
            filed=str(info.get("financialCurrency")),
            quoted=str(info.get("currency")),
        )
    cap = m["market_cap"]
    # Yahoo drops the trailing P/E on a loss but keeps a negative forward one,
    # so a loss-maker (CoreWeave) read n/a beside "Loss"; it also drops it on
    # some foreign listings that earn (Samsung, 005930.KS). Cap over the last
    # four quarters' net income (filing currency, hence the rate) is that reading.
    ttm_net = info.get("netIncomeToCommon")
    if m["pe_ttm"] is None and ttm_net and cap and rate:
        m["pe_ttm"] = cap / (ttm_net * rate)
    # Yahoo's trailing P/E counts one-offs as earnings: Alphabet's revalued
    # private stakes (149B of its 244B over four quarters) read it at 16x,
    # the business alone at 32x, and the review then saw earnings falling.
    # Past `ONE_OFF_SHARE` of the profit, the P/E is on normalized income.
    reported = _ttm(raw.income_q, "Net Income")
    normal = _ttm(raw.income_q, "Normalized Income")
    m["one_off_share"] = (
        (reported - normal) / normal
        if reported is not None and normal is not None and normal > 0
        else None
    )
    if (
        m["one_off_share"] is not None
        and abs(m["one_off_share"]) > ONE_OFF_SHARE
        and reported is not None
        and normal is not None
        and reported > 0
        and cap
        and rate
    ):
        # Not a KPI: the reported one, for the page to show beside it.
        m["pe_ttm_reported"] = m["pe_ttm"]
        m["pe_ttm"] = cap / (normal * rate)
    m["fcf_yield"] = fcf * rate / cap if fcf and cap and rate else None
    # Yahoo's FCF adds share-based pay back as if it cost nothing; for a
    # software house it can be most of the figure (HubSpot: 528M of 577M).
    # Paid in shares is still paid: the owner's FCF takes it off again.
    sbc = _latest(raw.cashflow, "Stock Based Compensation")
    owner = fcf - sbc if fcf is not None and sbc and sbc > 0 else fcf
    m["sbc_fcf"] = sbc / fcf if sbc and sbc > 0 and fcf and fcf > 0 else None
    m["owner_fcf_yield"] = owner * rate / cap if owner and cap and rate else None
    m["fcf_margin"] = owner / revenue if owner is not None and revenue else None
    # Last quarter's sales against a year before: the growth a decelerating
    # name has now, which a four-year CAGR still remembers as its best years.
    m["revenue_growth"] = info.get("revenueGrowth")

    ebitda = _latest(raw.income, "EBITDA")
    net_debt = latest_net_debt(raw)
    # Over a loss the ratio flips sign: net cash over a negative EBITDA reads as
    # leverage (Revolution Medicines showed 2.5x). No earnings, no multiple.
    has_ebitda = ebitda is not None and ebitda > 0
    m["net_debt_ebitda"] = (
        net_debt / ebitda if net_debt is not None and has_ebitda else None
    )
    # Free cash flow far above EBITDA is not the business's cash: a lender's
    # loan book or a payments float runs through operating cash flow.
    m["fcf_ebitda"] = owner / ebitda if owner is not None and has_ebitda else None
    # Price to sales in one currency: an ADR's filed sales converted, like
    # the yields above. The review's "no sales to speak of" test reads it.
    # Over the last four quarters when the feed has them: a name growing 4x
    # a year (Nebius) is not pre-revenue at 35x sales because its last
    # filed year, ten months old, made 89x of them.
    sales = info.get("totalRevenue") or revenue
    m["ps"] = cap / (sales * rate) if cap and sales and sales > 0 and rate else None
    if rate == 1.0:
        # Yahoo leaves the EV multiples out for many European small caps;
        # quote and filings share a currency here, so they are rebuilt.
        ev = m["ev"]
        if ev is None and cap and net_debt is not None:
            ev = m["ev"] = cap + net_debt
        if m["ev_ebitda"] is None and ev and has_ebitda:
            m["ev_ebitda"] = ev / ebitda
        if m["ev_sales"] is None and ev and revenue and revenue > 0:
            m["ev_sales"] = ev / revenue
    if rate != 1.0:
        # Yahoo adds a market cap in one currency to a net debt in the other,
        # and its EV multiples divide by statements in the filing currency —
        # Novo read at 1.5x EBITDA. Rebuilt in the quote currency, or blank.
        ev = cap + net_debt * rate if rate and cap and net_debt is not None else None
        m["ev"] = ev
        m["ev_ebitda"] = ev / (ebitda * rate) if ev and ebitda and rate else None
        m["ev_sales"] = ev / (revenue * rate) if ev and revenue and rate else None
        # Its P/B is off the same way (TSMC read 94x): cap over filed equity.
        equity = _latest(raw.balance, "Stockholders Equity")
        book = equity * rate if equity and equity > 0 and rate else None
        m["pb"] = cap / book if cap and book else None

    # Years of cash at the last year's burn, for a business that burns it.
    # Both sides are the filer's own currency, so no rate is involved.
    cash_now = info.get("totalCash") or _latest(
        raw.balance, "Cash Cash Equivalents And Short Term Investments"
    )
    burn = -fcf if fcf is not None and fcf < 0 else None
    m["runway_years"] = cash_now / burn if burn and cash_now else None

    m.update(_dividend(info, *_dividend_cover(raw.cashflow), symbol=raw.ticker))

    net_income = _latest(raw.income, "Net Income")
    m["cash_conversion"] = fcf / net_income if fcf and net_income else None
    # Not KPIs: whether the earnings are cash, for the review's cautions.
    # Accruals (Sloan): profit the cash flow does not show, over the assets;
    # past a tenth, earnings tend to fall back. Both in the filing currency.
    assets = _latest(raw.balance, "Total Assets")
    cfo = _latest(raw.cashflow, "Operating Cash Flow")
    m["accruals"] = (
        (net_income - cfo) / assets
        if net_income is not None and cfo is not None and assets and assets > 0
        else None
    )
    m["cfo_ni"] = _cash_backing(raw)
    # What an acquirer paid over book, against what it owns and what is the
    # owners': an impairment comes off both.
    equity_now = _latest(raw.balance, "Stockholders Equity")
    has_goodwill = goodwill is not None and goodwill > 0
    m["goodwill_assets"] = (
        goodwill / assets if has_goodwill and assets and assets > 0 else None
    )
    m["goodwill_equity"] = (
        goodwill / equity_now if has_goodwill and equity_now and equity_now > 0 else None
    )
    # Not KPIs: a bank's book without the premium it paid for others' (the
    # goodwill and intangibles a crisis writes off first), what is paid for
    # it, and what it earns. Book and profit in the filing currency, the cap
    # in the quote's.
    # Tangible *common* equity: the preferred stock is the preferred holders'
    # claim, not the common owners' book (CFR's 145M, JPM's 27B).
    tangible = _latest(raw.balance, "Tangible Book Value")
    if tangible is None:
        common = _latest(raw.balance, "Common Stock Equity")
        common = common if common is not None else equity_now
        if common is not None:
            intangible = _latest(raw.balance, "Goodwill And Other Intangible Assets")
            tangible = common - (intangible or 0.0)
    has_tangible = tangible is not None and tangible > 0
    m["ptbv"] = (
        cap / (tangible * rate) if has_tangible and cap and rate else None
    )
    # ...earned for the common owners: after the preferred dividends.
    earned_common = _latest(raw.income, "Net Income Common Stockholders")
    if earned_common is None:
        earned_common = net_income
    m["rotce"] = (
        earned_common / tangible if has_tangible and earned_common is not None else None
    )
    m["sbc_revenue"] = (
        sbc / revenue if sbc and sbc > 0 and revenue and revenue > 0 else None
    )

    m["revenue_cagr"] = _series_cagr(raw.income, "Total Revenue")
    m["net_income_cagr"] = _series_cagr(raw.income, "Net Income")
    m["fcf_cagr"] = _series_cagr(raw.cashflow, "Free Cash Flow")
    m["share_dilution"] = _dilution(raw)
    moat = moat_score(raw)
    m["moat"] = moat.score
    # Not KPIs: the operating margin over the filed years, so the review can
    # tell a margin at a cyclical peak, or one sliding for years, from today's.
    history = next(
        (p.facts for p in moat.pillars if p.kind in ("op_margin", "op_margin_loss")), {}
    )
    m["op_margin_median"] = history.get("margin")
    m["op_margin_change"] = history.get("change")
    # Years sales fell: the cycle's signature, which steady compounders lack.
    sales = next((p.facts for p in moat.pillars if p.key == "growth"), {})
    years, up = sales.get("years"), sales.get("up")
    m["revenue_down_years"] = years - up if years is not None and up is not None else None
    # Our own P/E per growth, never the feed's: Yahoo's PEG is unreliable and
    # the review already scores this one, so the ticker, the sector screen and
    # the review read the same number.
    from stocks.analysis.review import growth_pe

    m["peg"] = growth_pe(m)
    return m


# Why a KPI `compute_metrics` left blank is blank. The company's own reasons
# first — a loss has no P/E per growth, no estimates no forward P/E — then the
# feed's: no statements, too few years, no rate between two currencies, or a
# Yahoo field that never came.
MissingReason = Literal[
    "loss", "no_growth", "no_estimates", "no_statements", "short_history", "fx", "feed"
]
_FROM_STATEMENTS = {
    "roic": "income",
    "roic_ex_goodwill": "income",
    "fcf_yield": "cashflow",
    "owner_fcf_yield": "cashflow",
    "net_debt_ebitda": "income",
    "share_dilution": "income",
    "revenue_cagr": "income",
    "net_income_cagr": "income",
    "fcf_cagr": "cashflow",
    "cash_conversion": "cashflow",
    "ptbv": "balance",
    "rotce": "balance",
}
_FROM_SERIES = frozenset(
    {"share_dilution", "revenue_cagr", "net_income_cagr", "fcf_cagr"})
_CONVERTED = frozenset(
    {"fcf_yield", "owner_fcf_yield", "ev_ebitda", "ev_sales", "pb", "ptbv"})
_ON_EBITDA = frozenset({"net_debt_ebitda", "ev_ebitda"})


def missing_reasons(
    raw: RawFundamentals, metrics: Mapping, keys: Iterable[str]
) -> dict[str, MissingReason]:
    """KPI -> why it is blank, for each of `keys` `metrics` has no value for."""
    from stocks.analysis.review import per_share_growth

    info = raw.info
    ebitda = _latest(raw.income, "EBITDA")
    split = str(info.get("financialCurrency") or "").upper() != str(
        info.get("currency") or ""
    ).upper()
    out: dict[str, MissingReason] = {}
    for key in keys:
        if metrics.get(key) is not None:
            continue
        statement = getattr(raw, _FROM_STATEMENTS.get(key, ""), None)
        if key == "peg":
            pe = metrics.get("pe_fwd")
            pe = metrics.get("pe_ttm") if pe is None else pe
            if pe is not None and pe <= 0:
                out[key] = "loss"
            elif pe is not None or per_share_growth(metrics) is None:
                out[key] = "no_growth"
            else:
                out[key] = "feed"
        elif key in _ON_EBITDA and ebitda is not None and ebitda <= 0:
            out[key] = "loss"
        elif key == "pe_fwd" and info.get("forwardEps") is None:
            out[key] = "no_estimates"
        elif isinstance(statement, pd.DataFrame) and statement.empty:
            out[key] = "no_statements"
        elif key in _FROM_SERIES:
            out[key] = "short_history"
        elif key in _CONVERTED and split and _statement_fx(info) is None:
            out[key] = "fx"
        else:
            out[key] = "feed"
    return out


# A year's statements reach the feed weeks after it closes: a 10-K is due
# 60 to 90 days out. A day before that still read the year before's.
FILING_LAG_DAYS = 90
# How many years back `filed_history` goes: the review's longest window is two.
PAST_FILINGS = 3

# What `compute_metrics` reads from `info` that is not about the statements
# or the price, carried as it is: identity, and the dividend, which a price
# replay (`review.at_price`) moves on its own.
_KEPT_INFO = (
    "currency",
    "financialCurrency",
    "quoteType",
    "industry",
    "currentPrice",
    "regularMarketPrice",
    "dividendYield",
    "dividendRate",
    "trailingAnnualDividendYield",
    "payoutRatio",
)


def _years(df: pd.DataFrame | None, newest: pd.Timestamp, oldest: pd.Timestamp):
    """`df`'s annual columns between `oldest` and `newest`, give or take the
    few weeks one statement's year-end differs from another's."""
    if df is None or df.empty:
        return df
    slack = pd.Timedelta(days=45)
    dates = pd.to_datetime(df.columns, errors="coerce")
    keep = [(d >= oldest - slack) and (d <= newest + slack) for d in dates]
    return df.loc[:, keep]


def _filed_info(info: dict, raw: RawFundamentals, shares_now: float | None) -> dict:
    """An `info` built from `raw`'s statements alone, at today's share price.

    Yahoo's own ratios (trailing P/E, margins, ROE, EV) are today's, off the
    last four quarters; a past year's have to come from that year's filing.
    The market cap follows the share count the year reported, so buybacks
    and dilution count. Forward estimates have no past and are left out.
    """
    out = {key: info.get(key) for key in _KEPT_INFO}
    rate = _statement_fx(info)
    cap = info.get("marketCap")
    shares = _latest(raw.income, "Diluted Average Shares")
    if cap and shares and shares_now:
        cap = cap * shares / shares_now
    out["marketCap"] = cap
    revenue = _latest(raw.income, "Total Revenue")
    net = _latest(raw.income, "Net Income")
    equity = _latest(raw.balance, "Stockholders Equity")

    def share(part: float | None) -> float | None:
        return part / revenue if part is not None and revenue else None

    out["grossMargins"] = share(_latest(raw.income, "Gross Profit"))
    out["operatingMargins"] = share(_latest(raw.income, "Operating Income"))
    out["profitMargins"] = share(net)
    positive = equity is not None and equity > 0
    out["returnOnEquity"] = net / equity if net is not None and positive else None
    out["trailingPE"] = (
        cap / (net * rate) if cap and net is not None and net > 0 and rate else None
    )
    out["priceToBook"] = cap / (equity * rate) if cap and positive and rate else None
    sales = _row(raw.income, "Total Revenue")
    out["revenueGrowth"] = (
        float(sales.iloc[0]) / float(sales.iloc[1]) - 1
        if sales is not None and len(sales) >= 2 and float(sales.iloc[1]) > 0
        else None
    )
    out["totalDebt"] = _latest(raw.balance, "Total Debt")
    out["totalCash"] = _latest(
        raw.balance, "Cash Cash Equivalents And Short Term Investments"
    )
    return out


def _as_filed(raw: RawFundamentals, first: int, count: int, dates) -> dict:
    """`compute_metrics` over `count` annual years from the `first`-newest
    on, every ratio read off those statements at today's share price."""
    newest, oldest = dates[first], dates[first + count - 1]
    cut = RawFundamentals(
        ticker=raw.ticker,
        income=_years(raw.income, newest, oldest),
        balance=_years(raw.balance, newest, oldest),
        cashflow=_years(raw.cashflow, newest, oldest),
    )
    shares_now = _latest(raw.income, "Diluted Average Shares")
    cut.info = _filed_info(raw.info, cut, shares_now)
    return compute_metrics(cut)


def filed_history(raw: RawFundamentals) -> list[dict]:
    """The business as each of its last filings showed it, for the review's
    map to place a name where it sat when a window opened.

    One entry per year back (`PAST_FILINGS`, newest first): `filed` is the
    first day the feed could have had that year (`FILING_LAG_DAYS` past its
    close); `then` is `compute_metrics` over the statements up to that year,
    `base` the same over the newest years, as many of them. Both are read the
    same way — statements only, at today's price — so what separates them is
    the business, not two methods or two lengths of history: `then` against
    `base` is what moved, to add to today's real score. A replay at that
    day's price (`review.at_price`) puts the price in.

    Empty with no annual statements, or with filings in a currency there is
    no rate for (every yield would be blank on both sides).
    """
    if raw.income is None or raw.income.empty or _statement_fx(raw.info) is None:
        return []
    dates = [
        d for d in pd.to_datetime(raw.income.columns, errors="coerce") if pd.notna(d)
    ]
    dates.sort(reverse=True)
    out: list[dict] = []
    for first in range(min(len(dates), PAST_FILINGS + 1)):
        count = len(dates) - first
        then = _as_filed(raw, first, count, dates)
        base = then if first == 0 else _as_filed(raw, 0, count, dates)
        filed = (dates[first] + pd.Timedelta(days=FILING_LAG_DAYS)).date()
        out.append({"filed": filed.isoformat(), "then": then, "base": base})
    return out


def format_value(key: str, value: float | str | None) -> str:
    """Human string with explicit units; 'n/a' when data is missing."""
    if value is None:
        return "n/a"
    unit = KPI_SOURCES[key].unit if key in KPI_SOURCES else "ratio"
    if unit == "pct":
        return f"{value * 100:.1f}%"
    if unit == "x":
        return f"{value:.1f}x"
    if unit == "score":
        return f"{float(value):.0f}/100"
    if unit == "money":
        v = float(value)
        for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
            if abs(v) >= div:
                return f"{v / div:,.2f}{suffix}"
        return f"{v:,.2f}"
    return f"{value}"


# Rule-of-thumb interpretation bands per KPI: value-ascending
# (upper_bound_exclusive, label, color name). The color already encodes the
# verdict, so metrics where higher is better (ROIC, FCF yield) simply end green
# and multiples where lower is cheaper end red — no direction flag needed. Bands
# are rough and sector-agnostic: a fast visual cue, never the comps table.
# Percentage metrics carry fraction values (0.15 == 15%), so bands match.
_VERDICT_BANDS: dict[str, list[tuple[float, str, str]]] = {
    # valuation multiples — lower is cheaper
    "pe_ttm": [(15, "cheap", "green"), (25, "fair", "orange"),
               (40, "expensive", "red"), (float("inf"), "very expensive", "red")],
    "pe_fwd": [(15, "cheap", "green"), (25, "fair", "orange"),
               (40, "expensive", "red"), (float("inf"), "very expensive", "red")],
    "peg": [(1, "cheap", "green"), (2, "fair", "orange"),
            (float("inf"), "expensive", "red")],
    "pb": [(1.5, "cheap", "green"), (4, "fair", "orange"),
           (float("inf"), "expensive", "red")],
    "ev_ebitda": [(10, "cheap", "green"), (16, "fair", "orange"),
                  (float("inf"), "expensive", "red")],
    "ev_sales": [(3, "cheap", "green"), (8, "fair", "orange"),
                 (float("inf"), "expensive", "red")],
    "ptbv": [(1, "cheap", "green"), (2.5, "fair", "orange"),
             (float("inf"), "expensive", "red")],
    # quality / returns — higher is better (fraction values)
    "rotce": [(0.10, "weak", "red"), (0.15, "decent", "orange"),
              (float("inf"), "strong", "green")],
    "roic": [(0.08, "weak", "red"), (0.15, "decent", "orange"),
             (float("inf"), "strong", "green")],
    "roe": [(0.10, "weak", "red"), (0.20, "decent", "orange"),
            (float("inf"), "strong", "green")],
    "fcf_yield": [(0.02, "low", "red"), (0.05, "decent", "orange"),
                  (float("inf"), "high", "green")],
    # leverage — lower is safer; below zero is net cash
    "net_debt_ebitda": [(0, "net cash", "green"), (1, "low", "green"),
                        (3, "moderate", "orange"), (float("inf"), "high", "red")],
    # dilution CAGR — negative = buybacks (good), positive = dilution
    "share_dilution": [(-0.005, "buybacks", "green"), (0.005, "flat", "gray"),
                       (0.02, "dilutive", "orange"),
                       (float("inf"), "heavy dilution", "red")],
    # momentum — RSI(14): <30 oversold, 30-70 neutral, >70 overbought
    "rsi": [(30, "oversold", "green"), (70, "neutral", "gray"),
            (float("inf"), "overbought", "red")],
    # moat evidence score — thresholds mirror stocks.analysis.moat
    "moat": [(45, "no moat", "red"), (70, "narrow", "orange"),
             (float("inf"), "wide", "green")],
}


# A multiple at or under zero is no reading at all (EV/EBITDA on a loss, P/B on
# negative equity): banded, it came out "cheap". A P/E there is a loss, which
# is a reading, and the worst one a P/E has.
_VERDICT_POSITIVE_ONLY = frozenset({"peg", "pb", "ptbv", "ev_ebitda", "ev_sales"})
_VERDICT_LOSS = frozenset({"pe_ttm", "pe_fwd"})


def verdict(key: str, value: float | str | None) -> tuple[str, str] | None:
    """Cheap/fair/expensive read on a KPI: (label, color name).

    None when there is no band for `key` or the value is missing / non-numeric.
    Booleans are rejected too (they are int subclasses but never real KPIs).
    NaN falls through every band and returns None, so callers get a blank cue
    rather than a wrong one.
    """
    bands = _VERDICT_BANDS.get(key)
    if bands is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0 and key in _VERDICT_LOSS:
        return "loss", "red"
    if value <= 0 and key in _VERDICT_POSITIVE_ONLY:
        return None
    for upper, label, color in bands:
        if value < upper:
            return label, color
    return None


def lens_verdict(
    key: str, value: float | str | None, metrics: dict
) -> tuple[str, str] | None:
    """`verdict`, read the way the company's own lens (`review.lens`) reads it.

    Net debt is heavy from the industry's line (`review.debt_line`: a landlord
    and a utility borrow on purpose), and a landlord's new shares are how it
    grows, so they read as a fact rather than a warning. Its P/E carries the
    depreciation FFO adds back, so the generic bands would call every landlord
    dear: the rivals' median is the only fair read of it.
    """
    from stocks.analysis.review import REAL_ESTATE, debt_line, lens

    banded = verdict(key, value)
    if banded is None or isinstance(value, str) or value is None:
        return banded
    if key == "net_debt_ebitda" and value >= 1:
        line = debt_line(metrics)
        return ("moderate", "orange") if value < line else ("high", "red")
    if key in _VERDICT_LOSS and value > 0 and lens(metrics) == REAL_ESTATE:
        return None
    if key == "share_dilution" and lens(metrics) == REAL_ESTATE and value > 0:
        return banded[0], "gray"
    return banded


def verdict_md(key: str, value: float | str | None) -> str:
    """Colored Streamlit-markdown chip for a KPI verdict, or "" when none."""
    v = verdict(key, value)
    return f":{v[1]}[{v[0]}]" if v else ""


def comparables_table(metrics: list[dict]) -> pd.DataFrame:
    """KPIs as rows, tickers as columns — the framework's comps table."""
    cols = {}
    for m in metrics:
        cols[str(m["ticker"])] = [format_value(k, m.get(k)) for k in METRIC_ORDER]
    labels = [KPI_SOURCES[k].label for k in METRIC_ORDER]
    return pd.DataFrame(cols, index=labels)


# Comps ranking direction per KPI. Size (market cap, EV), price and raw FCF
# say nothing about who screens better, so they stay out of the score.
_RANK_LOWER_BETTER = frozenset(
    {"pe_ttm", "pe_fwd", "peg", "pb", "ev_ebitda", "ev_sales",
     "net_debt_ebitda", "share_dilution"}
)
_RANK_HIGHER_BETTER = frozenset(
    {"roe", "roic", "gross_margin", "op_margin", "net_margin", "fcf_yield",
     "cash_conversion", "revenue_cagr", "net_income_cagr", "fcf_cagr"}
)
# A ticker missing most KPIs can't win on the two it happens to have.
_RANK_MIN_METRICS = 5


# A multiple at or under zero is no reading: EV/EBITDA on a loss, P/B on
# negative equity, EV/Sales on a negative EV. Ranked as "lower is better" it
# came out the cheapest of the cohort. A P/E at or under zero is a loss, the
# worst reading a P/E has, as in the review.
_RANK_POSITIVE_ONLY = ("peg", "pb", "ptbv", "ev_ebitda", "ev_sales")
_RANK_LOSS_LAST = ("pe_ttm", "pe_fwd")


# KPIs that say nothing about a business judged on another lens (the review's
# `lens`): a bank has no gross margin or EBITDA and its FCF is deposits
# moving; a landlord's FCF and a utility's are capex-shaped. Left in, a bank
# ranked on EV/EBITDA against an insurance broker. Blanked, it ranks only on
# what its own lens reads, against the names that report the same.
_LENS_BLANK = {
    "financial": frozenset(
        {"ev_ebitda", "ev_sales", "gross_margin", "op_margin", "fcf_yield",
         "cash_conversion", "fcf_cagr", "net_debt_ebitda", "roic", "peg"}
    ),
    "real_estate": frozenset(
        {"fcf_yield", "cash_conversion", "fcf_cagr", "roic", "gross_margin",
         "ev_sales", "peg"}
    ),
    "utility": frozenset(
        {"fcf_yield", "cash_conversion", "fcf_cagr", "roic", "gross_margin",
         "ev_sales", "peg"}
    ),
}


def _rankable(row: dict) -> dict:
    from stocks.analysis.review import lens

    out = dict(row)
    for key in _LENS_BLANK.get(lens(row), ()):
        out[key] = None
    for key in _RANK_POSITIVE_ONLY + _RANK_LOSS_LAST:
        value = out.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value <= 0:
            out[key] = math.inf if key in _RANK_LOSS_LAST else None
    return out


def comp_scores(metrics: list[dict]) -> dict[str, float]:
    """Composite comps score per ticker in [0, 1] — cross-sectional, not banded.

    Each rankable KPI contributes a normalized average rank across the tickers
    that report it (best = 1, worst = 0, ties share); a ticker's score is the
    mean over its ranked KPIs. Tickers ranked on fewer than _RANK_MIN_METRICS
    KPIs are dropped — too sparse to compare fairly.
    """
    return ranking.percentile_rank_scores(
        [_rankable(row) for row in metrics],
        _RANK_LOWER_BETTER,
        _RANK_HIGHER_BETTER,
        _RANK_MIN_METRICS,
    )


def comp_medals(metrics: list[dict]) -> dict[str, str]:
    """Medal emoji for the 3 best composite comps scores (skipped when fewer
    than 3 tickers qualify — a 2-horse race has no podium)."""
    return ranking.podium_from_scores(comp_scores(metrics))


# The peer band is read on ratios and rates only: market cap, EV, price and
# raw FCF have no "normal" across companies of different size.
_BAND_KEYS = _RANK_LOWER_BETTER | _RANK_HIGHER_BETTER
# ...and the lens KPIs, which a company grid reads but the comps table has no
# row for (`_LENS_ONLY`).
GRID_BAND_KEYS = _BAND_KEYS | _LENS_ONLY
# Fewer reporting rivals than this and a median is one name's figure.
_BAND_MIN_PEERS = 3
# A cell this many robust sigmas (1.4826 x MAD) from the others' median is
# flagged. The comps-sheet rule is 2 sigma, but five rivals give a jumpy MAD:
# at 2 a semis set flagged a quarter of its cells and the mark meant nothing.
# The scale never drops under half that median either, so a cohort that
# happens to agree to the decimal does not flag a P/E of 23 against 20.
_OUTLIER_SIGMAS = 3.0
_OUTLIER_FLOOR = 0.5
# ...nor under a unit's smallest gap worth a mark: a median near zero has no
# half worth the name, and 0.4x of net debt against 0.0x is no outlier.
_OUTLIER_MIN_SCALE = {"x": 1.0, "pct": 0.05}


def _band_value(row: dict, key: str) -> float | None:
    """`key` of a `_rankable` row as a finite number, or None."""
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _band_values(rows: list[dict], key: str) -> list[float]:
    values = (_band_value(row, key) for row in rows)
    return [v for v in values if v is not None]


def peer_band(
    metrics: list[dict], keys: Iterable[str] | None = None
) -> dict[str, tuple[float, float, float]]:
    """KPI -> (P25, median, P75) of the rivals: every row but the first.

    The subject is left out so its own figure is read against the others,
    never against a middle it pulled. A KPI fewer than `_BAND_MIN_PEERS`
    rivals report has no band. `keys` defaults to the comps table's rows.
    """
    out: dict[str, tuple[float, float, float]] = {}
    rivals = [_rankable(row) for row in metrics[1:]]
    for key in METRIC_ORDER if keys is None else keys:
        if key not in GRID_BAND_KEYS:
            continue
        values = _band_values(rivals, key)
        if len(values) < _BAND_MIN_PEERS:
            continue
        low, mid, high = statistics.quantiles(values, n=4, method="inclusive")
        out[key] = (low, mid, high)
    return out


def comp_outliers(metrics: list[dict]) -> dict[str, list[str]]:
    """Ticker -> the KPIs where it sits far from everyone else in the set.

    Leave-one-out: each name against the median and spread of the others, so
    one wild figure cannot widen the spread that should flag it.
    """
    ranked = [_rankable(row) for row in metrics]
    out: dict[str, list[str]] = {}
    for i, mine in enumerate(ranked):
        others = ranked[:i] + ranked[i + 1 :]
        for key in METRIC_ORDER:
            value = _band_value(mine, key) if key in _BAND_KEYS else None
            if value is None:
                continue
            values = _band_values(others, key)
            if len(values) < _BAND_MIN_PEERS:
                continue
            mid = statistics.median(values)
            mad = statistics.median(abs(v - mid) for v in values)
            unit = KPI_SOURCES[key].unit
            scale = max(
                1.4826 * mad,
                _OUTLIER_FLOOR * abs(mid),
                _OUTLIER_MIN_SCALE.get(unit, 0.0),
            )
            if scale and abs(value - mid) > _OUTLIER_SIGMAS * scale:
                out.setdefault(str(mine["ticker"]), []).append(key)
    return out


def sources_table() -> pd.DataFrame:
    """KPI -> load source, verification source, reliability level."""
    return pd.DataFrame(
        {
            "KPI": [s.label for s in KPI_SOURCES.values()],
            "Level": [s.level for s in KPI_SOURCES.values()],
            "Loaded from": [s.loader for s in KPI_SOURCES.values()],
            "Verify against": [s.verify for s in KPI_SOURCES.values()],
            "Note": [s.note for s in KPI_SOURCES.values()],
        }
    )
