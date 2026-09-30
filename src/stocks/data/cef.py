"""Closed-end funds — the funds Yahoo files as ordinary shares.

A listed closed-end fund (MUA, PDI, UTF, NEA…) is a fund in every sense a
holder cares about: it owns a basket, it has a net asset value, it charges an
expense ratio and it pays a distribution. Yahoo labels it ``quoteType:
EQUITY`` and has no ``funds_data`` for it, so `stocks.data.funds` reads it as
a company and the ticker page prints revenue, margins, a moat and insider
flow for a trust that has none of them — the "not all the data shows up"
report this module answers.

**Detection** asks the SEC, which knows for certain: a closed-end fund files
N-CSR / N-CSRS shareholder reports and NPORT-P holdings under the 1940 Act,
and none of the forms an operating company or an open-end fund files (10-K,
10-Q, 20-F; 485BPOS, 24F-2NT). A BDC files 10-Qs and stays a company here — it
reports like one. Yahoo's own fields only gate the question (a symbol Yahoo
calls a technology company is not asked about) and stand in when EDGAR cannot
be reached: the fund's NAV line ``X{T}X`` existing as a mutual fund under the
same name, and last of all the words "closed-end" in its description. An
EDGAR answer, and a "no" from Yahoo's sector or industry, is written to
``data/closed_end.json``; a fallback guess is asked again next time.

**Figures** come from where they are filed, each one carrying its source and
date: NAV and premium/discount from Yahoo's NAV line against the listed
price on the same session, the expense ratio from the fund's XBRL fee table,
net assets, leverage and holdings from its latest N-PORT. Where EDGAR files a
figure Yahoo also prints (NAV per share, the premium to NAV) the two are
compared on EDGAR's date, like with like, and a disagreement is returned as
such rather than settled by picking one. A figure no source has says which
sources were asked.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from stocks import obs
from stocks.config import DATA_DIR
from stocks.data.funds import FundHolding
from stocks.formatting import finite

# symbol -> verdict, learned from EDGAR once and never expired: a listed
# closed-end fund converting to an ETF is rare enough to be a manual fix.
CEF_CACHE = DATA_DIR / "closed_end.json"

NPORT_NS = "{http://www.sec.gov/edgar/nport}"
NPORT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/primary_doc.xml"

# Detection sits on the page header's path, so it waits less than a filing
# fetch does; the profile's own requests get the archive's usual budget.
DETECT_TIMEOUT_S = 6.0
FILING_TIMEOUT_S = 20.0
# After EDGAR fails for a symbol, the fallbacks answer for this long before
# EDGAR is asked again — an outage must not cost every header six seconds.
RETRY_AFTER_S = 600.0

# Forms that make a filer something other than a closed-end fund: an
# operating company or BDC (periodic reports), or an open-end fund / ETF
# (continuous-offering registration and its annual fee notice). Plain 497 is
# NOT here: a closed-end fund with a shelf offering files 497 / 424B too.
OPERATING_FORMS = frozenset(
    {"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "20-F", "20-F/A", "40-F"}
)
OPEN_END_FORMS = frozenset({"24F-2NT", "485BPOS", "485APOS", "485BXT", "N-1A", "497K"})
REPORT_FORMS = frozenset({"N-CSR", "N-CSRS", "N-CSR/A", "N-CSRS/A"})
# A fund too new for its first shareholder report: registered on N-2 and
# already filing holdings.
SHELF_FORMS = frozenset({"N-2", "N-2/A", "N-2ASR", "N-2MEF", "N-2 POSASR"})

# Where Yahoo files every closed-end fund seen so far ("Financial Services" /
# "Asset Management"; older rows spell the industry "Closed-End Fund - Debt").
# A symbol Yahoo places anywhere else is not sent to EDGAR at all.
_SECTOR_HINT = ("financ",)
_INDUSTRY_HINT = ("asset management", "closed-end", "closed end")
_CLOSED_END_RE = re.compile(r"\bclosed[- ]end(ed)?\b", re.IGNORECASE)
_US_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")

# N-PORT asset categories (Form N-PORT, item C.4) folded into the labels the
# ETF profile already prints, so the two kinds of fund read the same way.
ASSET_CATEGORY_LABELS = {
    "DBT": "Bonds",
    "ABS-MBS": "Bonds",
    "ABS-ABCP": "Bonds",
    "ABS-CBDO": "Bonds",
    "ABS-O": "Bonds",
    "LON": "Loans",
    "EC": "Equity",
    "EP": "Preferred",
    "STIV": "Cash",
    "RA": "Cash",
}

# The sources a figure can name. The page spells each one out.
YAHOO = "yahoo"
YAHOO_NAV = "yahoo_nav"
EDGAR_XBRL = "edgar_xbrl"
EDGAR_NPORT = "edgar_nport"

# Two sources on the same date are allowed this far apart before the page
# calls it a disagreement: NAV per share relative, premium in points.
NAV_TOLERANCE = 0.01
PREMIUM_TOLERANCE = 0.01
# How far back from EDGAR's date a Yahoo row may sit and still count as that
# session (a month-end on a weekend is priced on the Friday).
SAME_SESSION_DAYS = 4


# ------------------------------------------------------------ classification


def classify_forms(forms) -> bool:
    """Whether a filer's form types are a closed-end fund's.

    Pure, so the rule is testable on its own: exclusions first (an operating
    company or an open-end fund also files N-CSR-shaped things), then the
    shareholder report, then the new-fund case of N-2 plus N-PORT.
    """
    seen = {str(form).upper().strip() for form in forms if form}
    if seen & OPERATING_FORMS or seen & OPEN_END_FORMS:
        return False
    if seen & REPORT_FORMS:
        return True
    return "NPORT-P" in seen and bool(seen & SHELF_FORMS)


def nav_symbol(ticker: str) -> str:
    """Yahoo's NAV line for a US closed-end fund: MUA -> XMUAX."""
    return f"X{ticker.upper()}X"


_lock = threading.Lock()
_verdicts: dict[str, bool] | None = None
_failed_at: dict[str, float] = {}
_subs_memo: dict[str, tuple[float, dict]] = {}
_SUBS_TTL_S = 86400.0


def _read_cache() -> dict[str, bool]:
    try:
        data = json.loads(CEF_CACHE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).upper(): bool(v) for k, v in data.items() if isinstance(v, bool)}


def _known() -> dict[str, bool]:
    global _verdicts
    with _lock:
        if _verdicts is None:
            _verdicts = _read_cache()
        return _verdicts


def _remember(key: str, verdict: bool) -> None:
    """Keep an EDGAR-backed verdict; best-effort on a read-only disk."""
    known = _known()
    with _lock:
        if known.get(key) == verdict:
            return
        known[key] = verdict
        stored = _read_cache() | {key: verdict}
    try:
        CEF_CACHE.write_text(json.dumps(stored, indent=0, sort_keys=True))
    except OSError:
        pass


def _key(ticker: str) -> str:
    key = (ticker or "").upper().strip()
    if not key:
        return ""
    try:
        from stocks.data.fetch import resolve

        return resolve(key).upper()
    except Exception:
        return key


# Seams the tests replace; each is one network hop.


def _info(symbol: str) -> dict:
    from stocks.data.fetch import info

    return info(symbol)


def _cik(ticker: str) -> str | None:
    from stocks.data.edgar import cik_for

    return cik_for(ticker)


def _get_json(url: str, timeout: float) -> dict:
    from stocks.data.edgar import _user_agent
    from stocks.data.http import get_json

    return get_json(url, user_agent=_user_agent(), timeout=timeout)


def _get_bytes(url: str, timeout: float) -> bytes:
    from stocks.data.edgar import _user_agent
    from stocks.data.http import get_bytes

    return get_bytes(url, user_agent=_user_agent(), timeout=timeout)


def _company_facts(ticker: str) -> dict | None:
    from stocks.data.edgar import company_facts

    return company_facts(ticker)


def _daily_closes(symbol: str) -> dict[str, float]:
    """A year of unadjusted daily closes, {YYYY-MM-DD: close}; {} on any miss.

    Unadjusted on both legs of the premium: a dividend adjustment rescales
    the past of one series by its own distributions, which is exactly the
    ratio being measured.
    """
    import yfinance as yf
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.fetch import retry, throttle_remaining

    if throttle_remaining():
        return {}
    try:
        frame = retry(
            lambda: yf.Ticker(symbol).history(
                period="1y", interval="1d", auto_adjust=False
            )
        )
    except YFRateLimitError:
        return {}
    except Exception as exc:
        obs.warn("cef.closes_failed", ticker=symbol, error=str(exc)[:300])
        return {}
    if frame is None or frame.empty or "Close" not in frame:
        return {}
    out: dict[str, float] = {}
    for when, value in frame["Close"].items():
        close = finite(value)
        if close is not None and close > 0:
            day = when.date() if hasattr(when, "date") else when
            out[str(day)[:10]] = close
    return out


def _submissions(cik: str, timeout: float) -> dict:
    """EDGAR's filing index for `cik`, memoized for a day in-process."""
    now = time.monotonic()
    with _lock:
        hit = _subs_memo.get(cik)
        if hit is not None and now - hit[0] < _SUBS_TTL_S:
            return hit[1]
    from stocks.data.edgar import SUBMISSIONS_URL

    subs = _get_json(SUBMISSIONS_URL.format(cik=cik), timeout)
    with _lock:
        _subs_memo[cik] = (time.monotonic(), subs)
        if len(_subs_memo) > 64:
            _subs_memo.pop(next(iter(_subs_memo)))
    return subs


def _forms(subs: dict) -> list[str]:
    recent = (subs.get("filings") or {}).get("recent") or {}
    return [str(form) for form in recent.get("form") or []]


def _yahoo_says_elsewhere(info: dict) -> bool:
    """Yahoo places the symbol somewhere no closed-end fund has been seen."""
    sector = str(info.get("sector") or "").lower()
    industry = str(info.get("industry") or "").lower()
    if sector and not any(hint in sector for hint in _SECTOR_HINT):
        return True
    return bool(industry) and not any(hint in industry for hint in _INDUSTRY_HINT)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _fallback(key: str, info: dict) -> bool:
    """EDGAR could not be asked: Yahoo's NAV line, then the description."""
    name = str(info.get("longName") or info.get("shortName") or "")
    try:
        nav = _info(nav_symbol(key))
    except Exception:
        nav = {}
    if str(nav.get("quoteType") or "").upper() == "MUTUALFUND":
        # Same fund under both symbols, not a mutual fund whose five letters
        # happen to spell X{T}X.
        mine, theirs = _words(name), _words(str(nav.get("longName") or ""))
        if mine and theirs and len(mine & theirs) / len(mine | theirs) >= 0.6:
            return True
    text = " ".join(
        str(info.get(field) or "") for field in ("longBusinessSummary", "longName")
    )
    return bool(_CLOSED_END_RE.search(text))


def is_closed_end(ticker: str, *, fetch: bool = True) -> bool:
    """True when `ticker` is a US-listed closed-end fund.

    Cache first; `fetch=False` answers from the cache alone. Anything that
    cannot be settled is False — a company must never lose its fundamentals
    to a failed lookup, the same rule `funds.is_fund` keeps.
    """
    key = _key(ticker)
    if not key or not _US_SYMBOL_RE.match(key):
        return False
    hit = _known().get(key)
    if hit is not None:
        return hit
    if not fetch:
        return False

    from stocks.data import profiles
    from stocks.data.funds import quote_type

    kind = quote_type(key)
    if kind != "EQUITY":
        return False  # a fund already, or unknown; either way not asked here
    stored = profiles.known(key) or {}
    sector = str(stored.get("sector") or "").lower()
    if sector and not any(hint in sector for hint in _SECTOR_HINT):
        return False  # AAPL, and every other name outside finance: no request
    try:
        cik = _cik(key)
    except Exception:
        cik = None
    if not cik:
        return False  # not a US filer; nothing to ask
    try:
        info = _info(key)
    except Exception:
        info = {}
    if _yahoo_says_elsewhere(info):
        _remember(key, False)
        return False

    failed = _failed_at.get(key)
    if failed is None or time.monotonic() - failed > RETRY_AFTER_S:
        try:
            verdict = classify_forms(_forms(_submissions(cik, DETECT_TIMEOUT_S)))
        except Exception as exc:
            _failed_at[key] = time.monotonic()
            obs.warn(
                "cef.edgar_unreachable",
                ticker=key,
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )
        else:
            _failed_at.pop(key, None)
            _remember(key, verdict)
            return verdict
    return _fallback(key, info)


# ------------------------------------------------------------------- filings


@dataclass(frozen=True)
class NPort:
    """What one NPORT-P says about the fund, as of its report date."""

    report_date: str | None
    name: str
    total_assets: float | None
    total_liabilities: float | None
    net_assets: float | None
    preferred: float | None  # liquidation preference of preferred shares
    holdings: tuple[FundHolding, ...]  # largest issuers, weight vs net assets
    holdings_count: int
    asset_mix: tuple[tuple[str, float], ...]  # share of positive investments

    @property
    def leverage(self) -> float | None:
        """Liabilities as a share of total assets.

        Borrowings, preferred shares carried as debt and tender-option bonds
        are in there — and so are payables for trades in flight, so read it as
        a ceiling on leverage rather than the fund's own "effective leverage".
        """
        if not self.total_assets or self.net_assets is None or self.total_assets <= 0:
            return None
        return max(0.0, 1.0 - self.net_assets / self.total_assets)


def _text(node, path: str) -> str | None:
    found = node.find(path)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def parse_nport(raw: bytes, top: int = 10) -> NPort:
    """An NPORT-P ``primary_doc.xml`` reduced to the figures the page shows.

    Holdings are folded by issuer: a municipal fund holds the same authority
    through a dozen bond lines, and "the ten biggest lines" would then name
    three issuers and understate how concentrated the book is.
    """
    head = raw[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError("refusing an N-PORT document with a DTD")
    root = ET.fromstring(raw)
    ns = NPORT_NS
    gen = root.find(f".//{ns}genInfo")
    fund = root.find(f".//{ns}fundInfo")
    name = ""
    report = None
    if gen is not None:
        name = _text(gen, f"{ns}seriesName") or _text(gen, f"{ns}regName") or ""
        report = _text(gen, f"{ns}repPdDate") or _text(gen, f"{ns}repPdEnd")

    def money(tag: str) -> float | None:
        return finite(_text(fund, f"{ns}{tag}")) if fund is not None else None

    issuers: dict[str, list] = {}
    mix: dict[str, float] = {}
    count = 0
    for sec in root.iter(f"{ns}invstOrSec"):
        count += 1
        value = finite(_text(sec, f"{ns}valUSD")) or 0.0
        pct = finite(_text(sec, f"{ns}pctVal")) or 0.0
        category = _text(sec, f"{ns}assetCat")
        if category is None:
            conditional = sec.find(f"{ns}assetConditional")
            category = conditional.get("assetCat") if conditional is not None else None
        if value > 0:
            label = ASSET_CATEGORY_LABELS.get(str(category or "").upper(), "Other")
            mix[label] = mix.get(label, 0.0) + value
        issuer = _text(sec, f"{ns}name") or _text(sec, f"{ns}title") or ""
        if not issuer or pct <= 0:
            continue
        slot = issuers.setdefault(issuer.casefold(), [issuer, 0.0])
        slot[1] += pct / 100.0  # pctVal is a percent of net assets
    ranked = sorted(issuers.values(), key=lambda row: row[1], reverse=True)[:top]
    invested = sum(mix.values())
    return NPort(
        report_date=report,
        name=name,
        total_assets=money("totAssets"),
        total_liabilities=money("totLiabs"),
        net_assets=money("netAssets"),
        preferred=money("liquidPref"),
        holdings=tuple(
            FundHolding(symbol="", name=label, weight=weight) for label, weight in ranked
        ),
        holdings_count=count,
        asset_mix=tuple(
            sorted(
                ((label, value / invested) for label, value in mix.items()),
                key=lambda row: row[1],
                reverse=True,
            )
        )
        if invested > 0
        else (),
    )


def latest_nport(subs: dict) -> tuple[str, str | None] | None:
    """(accession, report date) of the newest NPORT-P, amendments included."""
    recent = (subs.get("filings") or {}).get("recent") or {}
    rows = zip(
        recent.get("form") or [],
        recent.get("accessionNumber") or [],
        recent.get("reportDate") or [],
        recent.get("filingDate") or [],
        strict=False,
    )
    best = None
    for form, accession, report, filed in rows:
        if str(form).upper() not in {"NPORT-P", "NPORT-P/A"} or not accession:
            continue
        rank = (str(report or ""), str(filed or ""))
        if best is None or rank > best[0]:
            best = (rank, str(accession), report or None)
    return (best[1], best[2]) if best else None


def xbrl_latest(
    facts: dict | None, namespace: str, tag: str, unit: str
) -> tuple[str, float, str] | None:
    """(end date, value, form) of the most recent fact for one XBRL tag."""
    if not facts:
        return None
    rows = (
        ((facts.get("facts") or {}).get(namespace) or {}).get(tag, {}).get("units", {})
    ).get(unit) or []
    best = None
    for row in rows:
        value = finite(row.get("val"))
        end = str(row.get("end") or "")
        if value is None or not end:
            continue
        rank = (end, str(row.get("filed") or ""))
        if best is None or rank > best[0]:
            best = (rank, value, str(row.get("form") or ""))
    return (best[0][0], best[1], best[2]) if best else None


# ------------------------------------------------------------------- profile


@dataclass(frozen=True)
class Figure:
    """One number and where it came from.

    `tried` names the sources asked that had nothing: on a figure with no
    value it is the whole list, on one with a value it is the second opinion
    that could not be had.
    """

    value: float | None = None
    source: str | None = None
    as_of: str | None = None
    tried: tuple[str, ...] = ()


@dataclass(frozen=True)
class Check:
    """EDGAR's filed figure against Yahoo's on EDGAR's own date.

    `market` is None when Yahoo has no row for that session, and `agree` is
    then None too: nothing was compared, which is not the same as agreeing.
    """

    metric: str  # "nav" | "premium"
    as_of: str
    official: float
    official_source: str
    market: float | None
    market_source: str
    agree: bool | None
    tolerance: float


@dataclass(frozen=True)
class ClosedEndProfile:
    ticker: str
    name: str
    currency: str | None
    nav_symbol: str
    nav: Figure
    price: Figure
    premium: Figure
    distribution_rate: Figure
    expense_ratio: Figure
    net_assets: Figure
    total_assets: Figure
    leverage: Figure
    holdings: tuple[FundHolding, ...] = ()
    holdings_count: int | None = None
    holdings_as_of: str | None = None
    asset_classes: tuple[tuple[str, float], ...] = ()
    checks: tuple[Check, ...] = ()
    description: str = ""

    @property
    def disclosed_weight(self) -> float:
        return float(sum(h.weight for h in self.holdings))

    @property
    def is_bond_fund(self) -> bool:
        return dict(self.asset_classes).get("Bonds", 0.0) > 0.5


def _on_or_before(series: dict[str, float], day: str) -> float | None:
    """The close for `day`'s session: that date or up to four days before."""
    from datetime import date, timedelta

    try:
        end = date.fromisoformat(day[:10])
    except ValueError:
        return None
    for back in range(SAME_SESSION_DAYS + 1):
        hit = series.get((end - timedelta(days=back)).isoformat())
        if hit is not None:
            return hit
    return None


def _check(
    metric: str,
    filed: tuple[str, float, str] | None,
    market: float | None,
    tolerance: float,
) -> Check | None:
    if filed is None:
        return None
    day, official, _ = filed
    agree = None
    if market is not None:
        gap = (
            abs(market / official - 1.0)
            if metric == "nav" and official
            else abs(market - official)
        )
        agree = gap <= tolerance
    return Check(
        metric=metric,
        as_of=day,
        official=official,
        official_source=EDGAR_XBRL,
        market=market,
        market_source=YAHOO_NAV,
        agree=agree,
        tolerance=tolerance,
    )


def build_profile(
    ticker: str,
    info: dict,
    *,
    price_closes: dict[str, float],
    nav_closes: dict[str, float],
    facts: dict | None,
    nport: NPort | None,
) -> ClosedEndProfile:
    """Every figure with its source, and the cross-checks. Pure: no network.

    NAV and premium lead with Yahoo's NAV line because it is the only daily
    one; EDGAR's filed figures are weeks or months old, which makes them the
    check rather than the headline. Either stands in for the other when it
    is all there is.
    """
    key = ticker.upper()
    nav_filed = xbrl_latest(facts, "us-gaap", "NetAssetValuePerShare", "USD/shares")
    premium_filed = xbrl_latest(facts, "cef", "LatestPremiumDiscountToNavPercent", "pure")
    fees_filed = xbrl_latest(facts, "cef", "TotalAnnualExpensesPercent", "pure")

    # Today's pair: the last session both series have. The listed line prints
    # a live row before the NAV for that day exists, so "last of each" would
    # divide a price by yesterday's NAV.
    common = sorted(set(price_closes) & set(nav_closes))
    if nav_closes:
        day = max(nav_closes)
        nav = Figure(
            nav_closes[day],
            YAHOO_NAV,
            day,
            () if nav_filed else (EDGAR_XBRL,),
        )
    elif nav_filed:
        nav = Figure(nav_filed[1], EDGAR_XBRL, nav_filed[0], (YAHOO_NAV,))
    else:
        nav = Figure(tried=(YAHOO_NAV, EDGAR_XBRL))

    if common:
        day = common[-1]
        price = Figure(price_closes[day], YAHOO, day)
        premium = Figure(
            price_closes[day] / nav_closes[day] - 1.0,
            YAHOO_NAV,
            day,
            () if premium_filed else (EDGAR_XBRL,),
        )
    else:
        latest = max(price_closes) if price_closes else None
        price = (
            Figure(price_closes[latest], YAHOO, latest)
            if latest
            else Figure(tried=(YAHOO,))
        )
        premium = (
            Figure(premium_filed[1], EDGAR_XBRL, premium_filed[0], (YAHOO_NAV,))
            if premium_filed
            else Figure(tried=(YAHOO_NAV, EDGAR_XBRL))
        )

    quote = (
        finite(info.get("regularMarketPrice"))
        or finite(info.get("currentPrice"))
        or price.value
    )
    rate = finite(info.get("dividendRate")) or finite(
        info.get("trailingAnnualDividendRate")
    )
    distribution = (
        Figure(rate / quote, YAHOO) if rate and quote else Figure(tried=(YAHOO,))
    )

    expense = (
        Figure(fees_filed[1], EDGAR_XBRL, fees_filed[0])
        if fees_filed
        else Figure(tried=(EDGAR_XBRL,))
    )

    def filed_money(value: float | None) -> Figure:
        if nport is None or value is None:
            return Figure(tried=(EDGAR_NPORT,))
        return Figure(value, EDGAR_NPORT, nport.report_date)

    checks = tuple(
        check
        for check in (
            _check(
                "nav",
                nav_filed,
                _on_or_before(nav_closes, nav_filed[0]) if nav_filed else None,
                NAV_TOLERANCE,
            ),
            _check(
                "premium",
                premium_filed,
                _same_session_premium(price_closes, nav_closes, premium_filed[0])
                if premium_filed
                else None,
                PREMIUM_TOLERANCE,
            ),
        )
        if check is not None
    )

    return ClosedEndProfile(
        ticker=key,
        name=str(
            info.get("longName")
            or info.get("shortName")
            or (nport.name if nport else "")
            or key
        ),
        currency=info.get("currency") or "USD",
        nav_symbol=nav_symbol(key),
        nav=nav,
        price=price,
        premium=premium,
        distribution_rate=distribution,
        expense_ratio=expense,
        net_assets=filed_money(nport.net_assets if nport else None),
        total_assets=filed_money(nport.total_assets if nport else None),
        leverage=filed_money(nport.leverage if nport else None),
        holdings=nport.holdings if nport else (),
        holdings_count=nport.holdings_count if nport else None,
        holdings_as_of=nport.report_date if nport else None,
        asset_classes=nport.asset_mix if nport else (),
        checks=checks,
        description=str(info.get("longBusinessSummary") or ""),
    )


def _same_session_premium(
    price_closes: dict[str, float], nav_closes: dict[str, float], day: str
) -> float | None:
    """Yahoo's premium on EDGAR's date, both legs from the same session."""
    from datetime import date, timedelta

    try:
        end = date.fromisoformat(day[:10])
    except ValueError:
        return None
    for back in range(SAME_SESSION_DAYS + 1):
        stamp = (end - timedelta(days=back)).isoformat()
        price, nav = price_closes.get(stamp), nav_closes.get(stamp)
        if price is not None and nav:
            return price / nav - 1.0
    return None


def _nport(cik: str, subs: dict, key: str) -> NPort | None:
    latest = latest_nport(subs)
    if latest is None:
        return None
    accession, _ = latest
    url = NPORT_URL.format(cik=int(cik), folder=accession.replace("-", ""))
    try:
        return parse_nport(_get_bytes(url, FILING_TIMEOUT_S))
    except Exception as exc:
        obs.warn(
            "cef.nport_failed",
            ticker=key,
            accession=accession,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return None


def closed_end_profile(ticker: str) -> ClosedEndProfile | None:
    """The fund's own numbers, or None when `ticker` is not a closed-end fund.

    At most three EDGAR requests (filing index, the N-PORT, XBRL facts) and
    two Yahoo history pulls (the listed line and its NAV line). Each source
    fails on its own: a missing N-PORT leaves NAV and premium standing, a
    throttled Yahoo leaves the filed figures, and every gap names what was
    asked.
    """
    key = _key(ticker)
    if not is_closed_end(key):
        return None
    try:
        info = _info(key)
    except Exception:
        info = {}
    cik = _cik(key)
    subs: dict = {}
    if cik:
        try:
            subs = _submissions(cik, FILING_TIMEOUT_S)
        except Exception as exc:
            obs.warn("cef.submissions_failed", ticker=key, error=str(exc)[:300])
    nport = _nport(cik, subs, key) if cik and subs else None
    try:
        facts = _company_facts(key)
    except Exception as exc:
        obs.warn("cef.facts_failed", ticker=key, error=str(exc)[:300])
        facts = None
    return build_profile(
        key,
        info,
        price_closes=_daily_closes(key),
        nav_closes=_daily_closes(nav_symbol(key)),
        facts=facts,
        nport=nport,
    )
