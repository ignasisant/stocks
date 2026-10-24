"""The Today page's personal sections: news, insiders, comparisons.

Every row here is computed — a headline as Yahoo printed it, an 8-K's items,
a print's EPS against the estimate with the quarter's revenue, the release's
outlook and the price's move across it, an insider tally, a holding's month,
half-year and year against its sector ETF and the index with the Review
page's verdict beside it. The model writes at most one note per section
(`daily.prompt`), never a row, so a day the free chain is down still has
the whole page.

Which sections a book gets depends on what it holds (`shape`): a book of
index funds has no company to read news or insiders for, and a book that is
one big position reads that name's news first. The comparisons stand for
every book with a position — a fund against the index, a coin against it too.

What the reader saw is remembered like the card's lines (`memory`, through
`daily.seen`): a headline is said once, an insider tally comes back only
when a new trade lands or its size moves (`signals.NEWS`, `signals.INSIDER`).

A headline is data, never an instruction: it travels as a quoted field of
the user turn, cleaned of links, handles and markup (`clean_title`), and the
prompt says so.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from stocks import obs
from stocks.chat import signals
from stocks.formatting import finite, fmt_num

if TYPE_CHECKING:
    from stocks.data.earnings import EarningsResult

# What kind of book the sections are chosen for.
EMPTY = "empty"
FUND_ONLY = "fund_only"
CRYPTO_ONLY = "crypto_only"
CONCENTRATED = "concentrated"
DIVIDEND = "dividend"
MIXED = "mixed"
SHAPES = (EMPTY, FUND_ONLY, CRYPTO_ONLY, CONCENTRATED, DIVIDEND, MIXED)
# A card whose sections could not be gathered — read, so not asked for again.
UNREAD = "unread"

NEWS, INSIDERS, COMPARE = "news", "insiders", "compare"

# A book this much funds (or coins) is read as only that.
ONLY_SHARE = 0.9
# One company this big makes the book a bet on it.
CONCENTRATED_SHARE = 0.25

NEWS_NAMES = 5  # largest companies whose news is read, alert names first
NEWS_PER_NAME = 2
NEWS_DAYS = 3
FILING_DAYS = 7
NEWS_ROWS = 8
TITLE_CHARS = 120
TITLE_MIN = 12

INSIDER_US = 6
INSIDER_EU = 3
INSIDER_DAYS = 30

COMPARE_NAMES = 8
# A gap to the sector this wide (`LINE_SPAN`, points) is worth the model's note.
NOTABLE_PP = 5.0

BUDGET_S = 15.0
# Each source's budget runs from when a worker picks it up, not from when the
# pool opened: up to ~20 reads share WORKERS, and the insiders, queued behind
# the news and filings, timed out having waited most of their 15 s for a
# thread (prod 10-22 → 10-23). The pool as a whole stops at twice the budget.
# The Review rows are a whole Review computed, not one feed read: its p90 in
# prod is ~21s and a cold book reaches ~43s (2026-10-20 triage, ERR-01), so on
# the shared budget the first card of the day lost its comparisons. It gets
# its own, and starts first so the feeds cannot queue it behind them. 45 s
# still lost it on a cold instance (2026-10-24 triage, ERR-04: right after a
# deploy, and at night); nobody waits on it, the card is a background job.
VERDICTS_BUDGET_S = 60.0
WORKERS = 8

INDEX = "SPY"
CRYPTO_KIND = "crypto"  # asset_kind.CRYPTO, unimported at module load
INDEX_NAME = "S&P 500"
RESULTS_ITEM = "2.02"
# A print's own figures (`Sources.print`) are fetched after the feeds, for the
# names that printed: their own budget, so a slow statement never costs the
# news, and a slow feed never costs the print its revenue.
PRINT_BUDGET_S = 10.0
# A calendar print this close to the 8-K's filing day is the same print.
PRINT_SLACK_DAYS = 3
GUIDANCE_CHARS = 160
_GUIDE_RE = re.compile(
    r"\b(outlook|guidance|expects?|expected|anticipates?|forecasts?|projects?|"
    r"fiscal (?:year )?20\d\d|full[- ]year|next quarter|"
    r"(?:first|second|third|fourth)[- ]quarter)\b", re.I)
_NOT_GUIDE_RE = re.compile(
    r"conference call|webcast|forward-looking|safe harbor|press release|"
    r"reconciliation|investor relations", re.I)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")
# The 8-K items a row can name, each with a `today.item_<code>` label.
ITEM_TOPICS = ("1.01", "1.02", "1.03", "1.05", "2.01", "2.02", "2.03", "2.04", "2.05",
               "2.06", "3.01", "3.02", "3.03", "4.01", "4.02", "5.01", "5.02", "5.03",
               "5.07", "7.01", "8.01")


@dataclass(frozen=True)
class Sources:
    """What the sections are read from, handed in by the API so its caches
    serve the page too. A None loader is a source this caller lacks: its
    section is listed as missing it.

    `verdicts` is the Review page's held rows, {ticker: {"verdict", "sector",
    "quality", "cheapness", "weight"}}; `closes` the held names' closes with
    the index and the sector ETFs beside them.

    `results` is the prints the earnings calendar knows for the followed
    names (`data.earnings.EarningsResult`: reported EPS, the estimate, the
    surprise); `print(ticker, iso_day)` what one print's row quotes beyond
    EPS — the quarter's `revenue` and `revenue_yoy_pct` in `currency`, and
    the `release` text the outlook is read from (`api.briefing._print_source`).
    Neither is a section's source: without them a results row still stands,
    with fewer figures."""

    news: Callable[[str], list] | None = None
    filings: Callable[[str], list] | None = None
    insiders: Callable[[str], list] | None = None
    eu_insiders: Callable[[str], list] | None = None
    verdicts: Callable[[], dict[str, dict]] | None = None
    closes: Callable[[], dict] | None = None
    results: Callable[[], list] | None = None
    print: Callable[[str, str], dict] | None = None


# ------------------------------------------------------------------- shape


def kind_of(ticker: str) -> str:
    """The ticker's kind from what is already on disk — never a request: the
    shape is decided before anything is fetched. Unknown reads as a share."""
    from stocks.data import asset_kind as kinds
    from stocks.data.crypto import is_crypto

    if is_crypto(ticker):
        return kinds.CRYPTO
    try:
        if hit := kinds.known(ticker):
            return hit
        from stocks.data.funds import is_fund

        if is_fund(ticker, fetch=False):
            return kinds.EQUITY_FUND
    except Exception:  # noqa: BLE001 — a share is the safe guess
        pass
    return kinds.STOCK


def _company(kind: str) -> bool:
    from stocks.data import asset_kind as kinds

    return kind == kinds.STOCK


def shape(weights: dict[str, float], kinds: dict[str, str], profile: dict | None) -> str:
    """Which of `SHAPES` the book is, from its weights and kinds."""
    from stocks.data import asset_kind as k

    weights = {t: w for t, w in weights.items() if (finite(w) or 0) > 0}
    total = sum(weights.values())
    if not total:
        return EMPTY

    def share(pred) -> float:
        return sum(w for t, w in weights.items() if pred(kinds.get(t) or k.STOCK)) / total

    if share(lambda kind: kind in k.FUND_KINDS or kind == k.INDEX) >= ONLY_SHARE:
        return FUND_ONLY
    if share(lambda kind: kind == k.CRYPTO) >= ONLY_SHARE:
        return CRYPTO_ONLY
    # An income focus is the reader's own word for the book, so it wins over
    # concentration: five payers drift past a quarter each without the book
    # becoming a bet on one of them.
    if "dividends_value" in ((profile or {}).get("focus") or []):
        return DIVIDEND
    companies = [w for t, w in weights.items() if _company(kinds.get(t) or k.STOCK)]
    if companies and max(companies) / total >= CONCENTRATED_SHARE:
        return CONCENTRATED
    return MIXED


def sections_for(book: str) -> tuple[str, ...]:
    """The sections a book of this shape reads, in the order it reads them:
    a concentrated book its big name's news first, an income book how its
    names hold up before what was said about them."""
    if book == EMPTY:
        return ()
    if book in (FUND_ONLY, CRYPTO_ONLY):
        return (COMPARE,)
    if book == DIVIDEND:
        return (COMPARE, NEWS, INSIDERS)
    return (NEWS, COMPARE, INSIDERS)


# -------------------------------------------------------------------- news

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
_HANDLE_RE = re.compile(r"(?<!\w)[@#]\w+")
_TAG_RE = re.compile(r"<[^>]*>")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f​-‏ -‮⁦-⁩]")
_TAIL_RE = re.compile(r"\s+[-–—|]\s+[^-–—|]{1,40}$")


def clean_title(raw) -> str:
    """A headline as it may be shown and quoted: no links, handles, markup or
    control characters, no trailing " - Publisher", whitespace collapsed,
    `TITLE_CHARS` at most (cut at a word). "" when too little is left to be a
    headline."""
    text = _CTRL_RE.sub(" ", str(raw or ""))
    text = _TAG_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _HANDLE_RE.sub(" ", text)
    text = " ".join(text.split())
    text = _TAIL_RE.sub("", text).strip()
    if len(text) > TITLE_CHARS:
        cut = text[: TITLE_CHARS - 1].rsplit(" ", 1)[0].rstrip(",;:-–— ")
        text = f"{cut}…"
    return text if len(text) >= TITLE_MIN else ""


def _hash(text: str) -> str:
    return hashlib.sha1(text.casefold().encode()).hexdigest()[:8]


def news_rows(ticker: str, headlines: list, reports: list, day: date,
              tr) -> list[dict]:
    """One name's news: its last `NEWS_PER_NAME` headlines over `NEWS_DAYS`,
    then its latest 8-K over `FILING_DAYS` — a results filing read as such."""
    rows: list[dict] = []
    seen: set[str] = set()
    since = day - timedelta(days=NEWS_DAYS)
    for h in headlines or []:
        published = getattr(h, "published", None)
        if not isinstance(published, date) or published < since or published > day:
            continue
        title = clean_title(getattr(h, "title", ""))
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        rows.append({
            "key": f"news:{ticker}:{_hash(title)}",
            "kind": "news",
            "line": title,
            "tickers": [ticker],
            "source": "yahoo",
            "url": _http(getattr(h, "url", "")),
            "date": published.isoformat(),
            "data": {"publisher": clean_title(getattr(h, "publisher", ""))[:40]
                     or str(getattr(h, "publisher", "") or "")[:40]},
        })
        if len(rows) >= NEWS_PER_NAME:
            break
    cutoff = day - timedelta(days=FILING_DAYS)
    for r in reports or []:
        filed = getattr(r, "filed", None)
        # Only the items with a topic: 9.01 is the exhibits list, not news.
        items = tuple(i for i in getattr(r, "items", ()) or () if i in ITEM_TOPICS)
        if not isinstance(filed, date) or filed < cutoff or filed > day or not items:
            continue
        results = RESULTS_ITEM in items
        # A results filing already says "results": its other items follow.
        topics = [tr(f"today.item_{i.replace('.', '_')}") for i in items
                  if not (results and i == RESULTS_ITEM)]
        if not results:
            template = "today.filing_row"
        else:
            template = "today.results_row_more" if topics else "today.results_row"
        rows.append({
            "key": f"filing:{ticker}:{filed.isoformat()}",
            "kind": "results" if results else "filing",
            "line": tr(template, ticker=ticker, topics=", ".join(topics)),
            "tickers": [ticker],
            "source": "8k",
            "url": _http(getattr(r, "url", "")),
            "date": filed.isoformat(),
            "data": {"items": ",".join(items)},
        })
        break
    return rows


def _http(url) -> str:
    text = str(url or "").strip()
    return text if text.startswith("https://") else ""


# ------------------------------------------------------------------- prints


def guidance_of(text: str) -> str:
    """The first sentence of a release that looks ahead — a figure for the
    next quarter or the year — cut to `GUIDANCE_CHARS` at a word; "" when
    none. The call's logistics and the safe-harbour boilerplate, which name
    the future too, are skipped."""
    for sentence in _SENTENCE_RE.split(" ".join(str(text or "").split())):
        line = sentence.strip()
        if (len(line) < 30 or not _GUIDE_RE.search(line) or _NOT_GUIDE_RE.search(line)
                or not re.search(r"\d", line)):
            continue
        if len(line) > GUIDANCE_CHARS:
            cut = line[: GUIDANCE_CHARS - 1].rsplit(" ", 1)[0].rstrip(",;:-–— ")
            line = f"{cut}…"
        return line
    return ""


def reaction(series, when: date) -> float | None:
    """% move across the print: the last close before `when` to the first
    after it. The print's hour is unknown (before the open, after the close),
    so the window spans the day itself; None until a session after it exists.
    """
    if series is None:
        return None
    closes: dict[date, float] = {}
    try:
        for idx, value in series.dropna().items():
            day = idx.date() if hasattr(idx, "date") else idx
            if isinstance(day, date) and finite(value) is not None:
                closes[day] = float(value)
    except Exception:  # noqa: BLE001 — not a series of closes
        return None
    before = [d for d in closes if d < when]
    after = [d for d in closes if d > when]
    if not before or not after or not closes[max(before)]:
        return None
    return (closes[min(after)] / closes[max(before)] - 1) * 100


def print_data(result, source: dict | None, series, when: date) -> dict:
    """The figures a print's row carries: EPS against the estimate (`result`,
    the calendar's), the quarter's revenue and the release's outlook
    (`source`, `Sources.print`) and the price's move across the print
    (`series`). Only what is known is there."""
    data: dict = {"date": when.isoformat()}
    if result is not None:
        eps = finite(getattr(result, "reported_eps", None))
        estimate = finite(getattr(result, "eps_estimate", None))
        surprise = finite(getattr(result, "surprise_pct", None))
        if surprise is None and eps is not None and estimate:
            surprise = (eps / estimate - 1) * 100 if estimate > 0 else None
        if eps is not None:
            data["reported_eps"] = round(eps, 2)
        if estimate is not None:
            data["eps_estimate"] = round(estimate, 2)
        if surprise is not None:
            data["surprise_pct"] = round(surprise, 1)
        if eps is not None and estimate is not None:
            data["beat"] = eps >= estimate
    source = source or {}
    if (revenue := finite(source.get("revenue"))) is not None:
        data["revenue"] = round(revenue, 2)
        data["currency"] = str(source.get("currency") or "USD")
        if (yoy := finite(source.get("revenue_yoy_pct"))) is not None:
            data["revenue_yoy_pct"] = round(yoy, 1)
    if guidance := guidance_of(str(source.get("release") or "")):
        data["guidance"] = guidance
    if (move := reaction(series, when)) is not None:
        data["reaction_pct"] = round(move, 1)
    return data


def _money(value: float, sign: str, tr, lang: str) -> str:
    """Millions as millions in the reader's language: "$314,6 M" reads,
    "$314.582.260" is counted."""
    value = abs(value)
    for div, key in ((1e9, "today.billions"), (1e6, "today.millions")):
        if value >= div:
            return tr(key, value=f"{sign}{fmt_num(value / div, 1, lang)}")
    return f"{sign}{fmt_num(value, 0, lang)}"


def print_line(ticker: str, data: dict, topics: list[str], tr, lang: str) -> str:
    """A print row's line from its figures — EPS against the estimate, the
    revenue and its year, the move across the print, whichever are known;
    "" when none is, so the caller keeps the filing's own line."""
    from stocks.config import currency_symbol

    def pct(value) -> str:
        return f"{fmt_num(float(value), 1, lang, signed=True)}%"

    parts: list[str] = []
    eps, estimate = data.get("reported_eps"), data.get("eps_estimate")
    if eps is not None:
        if estimate is not None and data.get("surprise_pct") is not None:
            parts.append(tr("today.print_eps_vs", eps=fmt_num(float(eps), 2, lang),
                            estimate=fmt_num(float(estimate), 2, lang),
                            surprise=pct(data["surprise_pct"])))
        elif estimate is not None:
            parts.append(tr("today.print_eps_plain", eps=fmt_num(float(eps), 2, lang),
                            estimate=fmt_num(float(estimate), 2, lang)))
        else:
            parts.append(tr("today.print_eps", eps=fmt_num(float(eps), 2, lang)))
    if data.get("revenue") is not None:
        revenue = _money(float(data["revenue"]),
                         currency_symbol(str(data.get("currency") or "USD")), tr, lang)
        if data.get("revenue_yoy_pct") is not None:
            parts.append(tr("today.print_revenue_yoy", revenue=revenue,
                            yoy=pct(data["revenue_yoy_pct"])))
        else:
            parts.append(tr("today.print_revenue", revenue=revenue))
    if data.get("reaction_pct") is not None:
        parts.append(tr("today.print_reaction", move=pct(data["reaction_pct"])))
    if not parts:
        return ""
    key = "today.print_row_more" if topics else "today.print_row"
    return tr(key, ticker=ticker, parts=", ".join(parts), topics=", ".join(topics))


def _printed(results, names: list[str], day: date) -> dict[str, EarningsResult]:
    """{ticker: its newest print over `FILING_DAYS`} among `names`, off the
    calendar's results."""
    cutoff = day - timedelta(days=FILING_DAYS)
    out: dict[str, EarningsResult] = {}
    for result in results or []:
        ticker = str(getattr(result, "ticker", "") or "")
        when = getattr(result, "date", None)
        if (ticker not in names or not isinstance(when, date) or when < cutoff
                or when > day):
            continue
        held = out.get(ticker)
        if held is None or when > held.date:
            out[ticker] = result
    return out


def print_rows(rows: list[dict], printed: dict[str, EarningsResult],
               sources: dict[str, dict],
               closes: dict, day: date, tr, lang: str) -> list[dict]:
    """`rows` with every results row carrying its print's figures and a
    results row for each print in `printed` that filed no 8-K the rows know
    (a name outside the SEC), prints first: they are the day's most material
    rows and the cap on the section must not cost them."""
    out: list[dict] = []
    covered: set[str] = set()
    for row in rows:
        if row.get("kind") != "results":
            out.append(row)
            continue
        ticker = str(row["tickers"][0])
        covered.add(ticker)
        filed = date.fromisoformat(row["date"])
        result = printed.get(ticker)
        when = filed
        if result is not None:
            if abs((result.date - filed).days) <= PRINT_SLACK_DAYS:
                when = result.date
            else:
                result = None
        data = print_data(result, sources.get(ticker), closes.get(ticker), when)
        items = str(row["data"].get("items") or "")
        topics = [tr(f"today.item_{i.replace('.', '_')}") for i in items.split(",")
                  if i and i != RESULTS_ITEM]
        line = print_line(ticker, data, topics, tr, lang)
        out.append(row | {"line": line or row["line"],
                          "data": {**row["data"], **data}})
    for ticker, result in printed.items():
        if ticker in covered:
            continue
        data = print_data(result, sources.get(ticker), closes.get(ticker), result.date)
        line = print_line(ticker, data, [], tr, lang)
        if not line:
            continue
        out.append({
            "key": f"print:{ticker}:{result.date.isoformat()}",
            "kind": "results",
            "line": line,
            "tickers": [ticker],
            "source": "earnings",
            "url": "",
            "date": result.date.isoformat(),
            "data": data,
        })
    return sorted(out, key=lambda r: r.get("kind") != "results")


def _print_day(rows: list[dict], printed: dict[str, EarningsResult]) -> dict[str, str]:
    """{ticker: the ISO day its print is read as} for every name with a
    results row or a calendar print — what `Sources.print` is asked for."""
    out = {t: r.date.isoformat() for t, r in printed.items()}
    for row in rows:
        if row.get("kind") == "results":
            out.setdefault(str(row["tickers"][0]), str(row["date"]))
    return out


# ---------------------------------------------------------------- insiders


def _name(text) -> str:
    """An insider's name, kept to letters and a few marks: it is printed."""
    return re.sub(r"[^A-Za-zÀ-ÿ .'-]", "", str(text or "")).strip()[:40]


def _eu_register(ticker: str) -> str:
    """The regulator whose Art. 19 MAR register speaks for a European listing."""
    from stocks.data.cnmv import spanish_listing

    return "cnmv" if spanish_listing(ticker) else "bafin"


def insider_row(ticker: str, txs: list, day: date, tr, lang: str,
                source: str = "sec") -> dict | None:
    """One name's open-market insider trades over `INSIDER_DAYS`, as a row;
    None when there were none."""
    from stocks.config import currency_symbol
    from stocks.data.insiders import summarize

    summary = summarize(txs or [], ref=day, within_days=INSIDER_DAYS)
    if not summary.has_activity:
        return None
    cutoff = day - timedelta(days=INSIDER_DAYS)
    trades = sorted((t for t in txs if t.is_open_market and t.date and t.date >= cutoff),
                    key=lambda t: t.date, reverse=True)
    latest = trades[0].date.isoformat() if trades else ""
    ccy = next((t.currency for t in trades), "USD")
    sign = currency_symbol(ccy)

    def money(v: float) -> str:
        return _money(v, sign, tr, lang)

    def who(key: str, n: int) -> str:
        return f"{key}_one" if n == 1 else key

    if summary.buy_count and not summary.sell_count:
        line = tr(who("today.insider_buy_row", summary.buyers), ticker=ticker,
                  n=summary.buyers, value=money(summary.buy_value), days=INSIDER_DAYS)
    elif summary.sell_count and not summary.buy_count:
        line = tr(who("today.insider_sell_row", summary.sellers), ticker=ticker,
                  n=summary.sellers, value=money(summary.sell_value), days=INSIDER_DAYS)
    else:
        line = tr("today.insider_mixed_row", ticker=ticker,
                  buy=money(summary.buy_value), sell=money(summary.sell_value),
                  days=INSIDER_DAYS)
    insider = _name(trades[0].insider) if trades else ""
    return {
        "key": f"insider:{ticker}",
        "kind": "insider",
        "line": line,
        "tickers": [ticker],
        "source": source,
        "url": "",
        "date": latest,
        "data": {
            "buys": summary.buy_count,
            "sells": summary.sell_count,
            "buyers": summary.buyers,
            "sellers": summary.sellers,
            "buy_value": round(summary.buy_value, 2),
            "sell_value": round(summary.sell_value, 2),
            "net_value": round(summary.net_value, 2),
            "cluster_buy": summary.cluster_buy,
            "currency": ccy,
            "latest": latest,
            "insider": insider,
            "role": _name(trades[0].relationship) if trades else "",
        },
    }


# ------------------------------------------------------------- comparisons


#: The spans a comparison measures, as `evidence.perf` names them. The line
#: and the notable test read `LINE_SPAN`: a month is noise against a sector,
#: a year outlives the reason a name is held.
SPANS = {"m1": "m1_pct", "m6": "m6_pct", "y1": "y1_pct"}
LINE_SPAN = "m6"


def compare_rows(weights: dict[str, float], kinds: dict[str, str],
                 verdicts: dict[str, dict], closes: dict, tr, lang: str) -> list[dict]:
    """The largest `COMPARE_NAMES` positions, each measured over one month,
    six months and a year against its sector's ETF and the index, with the
    Review page's verdict. A span the history is too short for is None; a
    name without even a month is left out."""
    from stocks.analysis import sentiment as sm
    from stocks.api.evidence import perf

    index = perf(closes.get(INDEX))
    # A coin is measured against bitcoin when the book holds it — the price
    # every other coin moves with — and against the index otherwise.
    btc = next((t for t in weights if t.upper().startswith("BTC-") and closes.get(t)
                is not None), None)
    rows = []
    ranked = sorted(weights.items(), key=lambda kv: -(finite(kv[1]) or 0.0))
    for ticker, weight in ranked[:COMPARE_NAMES]:
        own = perf(closes.get(ticker))
        if own.get("m1_pct") is None:
            continue
        verdict = verdicts.get(ticker) or {}
        sector = verdict.get("sector")
        company = _company(kinds.get(ticker) or "stock")
        coin = kinds.get(ticker) == CRYPTO_KIND
        etf = (sm.SECTOR_ETFS.get(sector) if company
               else btc if coin and btc != ticker else None)
        # A fund that is the benchmark has no gap to it, not a gap of zero.
        if etf == ticker:
            etf = None
        bench = perf(closes.get(etf)) if etf else {}
        vs_index_of = {} if ticker == INDEX else index
        data: dict = {
            "weight": _round(weight * 100 if weight is not None else None, 1),
            "sector": sector,
            "sector_etf": etf,
        }
        for span, key in SPANS.items():
            data[span] = own.get(key)
            data[f"vs_sector_{span}"] = _gap(own.get(key), bench.get(key))
            data[f"vs_index_{span}"] = _gap(own.get(key), vs_index_of.get(key))
        # The span the line is written over: six months when the history
        # reaches that far, else the month.
        span = LINE_SPAN if data[LINE_SPAN] is not None else "m1"
        vs_sector, vs_index = data[f"vs_sector_{span}"], data[f"vs_index_{span}"]
        data |= {"vs_sector": vs_sector, "vs_index": vs_index,
                 # Review never values a coin: "unrated" on each says nothing.
                 "verdict": None if coin else verdict.get("verdict"),
                 "quality": _round(verdict.get("quality"), 0),
                 "cheapness": _round(verdict.get("cheapness"), 0)}
        move = f"{fmt_num(data[span], 1, lang, signed=True)}%"
        when = tr(f"today.span_{span}")
        if vs_sector is not None:
            line = tr("today.compare_row_coin" if coin else "today.compare_row",
                      ticker=ticker, move=move, span=when, etf=etf,
                      gap=fmt_num(vs_sector, 1, lang, signed=True))
        elif vs_index is not None:
            line = tr("today.compare_row_index", ticker=ticker, move=move, span=when,
                      index=INDEX_NAME, gap=fmt_num(vs_index, 1, lang, signed=True))
        else:
            line = tr("today.compare_row_alone", ticker=ticker, move=move, span=when)
        rows.append({
            "key": f"compare:{ticker}",
            "kind": "compare",
            "line": line,
            "tickers": [ticker],
            "source": "computed",
            "url": "",
            "date": "",
            "data": data,
        })
    return rows


def _gap(a, b) -> float | None:
    a, b = finite(a), finite(b)
    return None if a is None or b is None else round(a - b, 1)


def _round(value, digits: int) -> float | None:
    out = finite(value)
    return None if out is None else round(out, digits)


def notable(row: dict) -> bool:
    """Whether a comparison is worth the model's remark: a wide gap to the
    sector, or a verdict that proposes a move."""
    data = row.get("data") or {}
    gap = finite(data.get("vs_sector"))
    return (gap is not None and abs(gap) >= NOTABLE_PP) or data.get("verdict") in (
        "trim", "add", "sell")


# ------------------------------------------------------------------ memory


def _memory_kind(row: dict) -> str | None:
    kind = row.get("kind")
    if kind in ("news", "filing"):
        return signals.NEWS
    if kind == "results":
        return signals.RESULTS
    if kind == "insider":
        return signals.INSIDER
    return None


def memory(sections: list[dict]) -> dict[str, tuple[str, dict]]:
    """{row key: (signal kind, its figures)} for the rows that are
    remembered once shown — `daily.seen` stamps them like the card's lines."""
    out = {}
    for sec in sections or []:
        for row in sec.get("rows") or []:
            kind = _memory_kind(row)
            if kind and row.get("key"):
                out[str(row["key"])] = (kind, dict(row.get("data") or {}))
    return out


def _fresh(row: dict, shown: dict | None, day: date) -> bool:
    kind = _memory_kind(row)
    if kind is None:
        return True
    return not signals.repeat_key(kind, row["key"], row.get("data") or {}, shown, day)


# ------------------------------------------------------------------ gather


def _listed(found: dict[str, object], key: str) -> list:
    """A source's answer when it came back as a list, else nothing."""
    value = found.get(key)
    return value if isinstance(value, list) else []


def _await(future, started: dict[str, float], name: str, budget_s: float,
           ceiling: float):
    """`future`'s result once it has run `budget_s` from its own start, or
    TimeoutError; past `ceiling` (monotonic) it is late whether it started
    or not. `started[name]` is set by the task itself when a worker runs it."""
    while not future.done():
        now = time.monotonic()
        begun = started.get(name)
        end = ceiling if begun is None else min(ceiling, begun + budget_s)
        if now >= end:
            raise TimeoutError
        # Still queued: look again shortly, its clock may start meanwhile.
        wait([future], timeout=end - now if begun is not None
             else min(end - now, 0.25))
    return future.result()


def _timed(started: dict[str, float], name: str, fn: Callable[[], object]):
    def run():
        started[name] = time.monotonic()
        return fn()
    return run


def _late(started: dict[str, float], name: str, begun: float) -> dict:
    """How long a late source waited for a worker, for its warning: the next
    triage can tell a slow upstream from a full queue."""
    at = started.get(name)
    return {"queued_ms": None if at is None else round((at - begun) * 1000)}


def _print_sources(get, days: dict[str, str],
                   budget_s: float | None = None) -> dict[str, dict]:
    """{ticker: what its print's row quotes beyond EPS} for the names in
    `days`, all at once under `PRINT_BUDGET_S`; a name whose source failed
    or ran late is left out, and its row stands on the calendar's figures."""
    if get is None or not days:
        return {}
    budget_s = PRINT_BUDGET_S if budget_s is None else budget_s
    out: dict[str, dict] = {}
    begun = time.monotonic()
    started: dict[str, float] = {}
    errors: list[str] = []
    pool = ThreadPoolExecutor(max_workers=min(len(days), WORKERS))
    try:
        futures = {t: pool.submit(_timed(started, t, lambda t=t, iso=iso: get(t, iso)))
                   for t, iso in days.items()}
        for ticker, future in futures.items():
            try:
                found = _await(future, started, ticker, budget_s,
                               begun + 2 * budget_s)
            except Exception as exc:  # noqa: BLE001 — one print, not the page
                errors.append(type(exc).__name__)
                continue
            if isinstance(found, dict):
                out[ticker] = found
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if errors:
        # One line per book, not per name: the names of one book share the
        # pool, and a slow statement host makes them all late together.
        obs.warn("today.source_failed", source="print", error_type=errors[0],
                 count=len(errors), of=len(days))
    return out


def gather(
    weights: dict[str, float],
    *,
    kinds: dict[str, str] | None = None,
    profile: dict | None = None,
    alerts: list[str] | tuple[str, ...] = (),
    day: date,
    lang: str,
    shown: dict | None = None,
    sources: Sources | None = None,
    budget_s: float = BUDGET_S,
    verdicts_budget_s: float = VERDICTS_BUDGET_S,
) -> dict:
    """{"shape", "sections", "missing"} for one book.

    Every source runs at once under one wall-clock budget; one that failed or
    ran late is named in its section's `missing`, so the page can say "no
    news from Yahoo today" rather than "nothing happened".
    """
    from stocks.web.i18n import translate

    started = time.monotonic()
    sources = sources or Sources()
    weights = {str(t): float(w) for t, w in weights.items() if finite(w) is not None}
    kinds = dict(kinds or {})
    for ticker in weights:
        kinds.setdefault(ticker, kind_of(ticker))
    book = shape(weights, kinds, profile)
    wanted = sections_for(book)

    def tr(key: str, **kw) -> str:
        return translate(key, lang, **kw)

    companies = [t for t, _ in sorted(weights.items(), key=lambda kv: -kv[1])
                 if _company(kinds[t])]
    alerted = [t for t in alerts if _company(kinds.get(t) or kind_of(t))]
    news_names = list(dict.fromkeys([*alerted, *companies]))[:NEWS_NAMES]
    us = [t for t in companies if "." not in t and "-" not in t][:INSIDER_US]
    try:
        from stocks.data.bafin import german_listing
        from stocks.data.cnmv import spanish_listing

        german = [t for t in companies
                  if german_listing(t) or spanish_listing(t)][:INSIDER_EU]
    except Exception:  # noqa: BLE001
        german = []

    tasks: dict[str, Callable[[], object]] = {}
    missing: dict[str, list[str]] = {s: [] for s in wanted}
    if NEWS in wanted:
        if (news := sources.news) is None:
            missing[NEWS].append("yahoo")
        else:
            for t in news_names:
                tasks[f"news:{t}"] = lambda t=t, get=news: get(t)
        if (filings := sources.filings) is not None:
            for t in [n for n in news_names if "." not in n]:
                tasks[f"filing:{t}"] = lambda t=t, get=filings: get(t)
        else:
            missing[NEWS].append("edgar")
        if sources.results is not None:
            tasks["results"] = sources.results
    if INSIDERS in wanted:
        if (insiders := sources.insiders) is None:
            missing[INSIDERS].append("sec")
        else:
            for t in us:
                tasks[f"insider:{t}"] = lambda t=t, get=insiders: get(t)
        if (eu_insiders := sources.eu_insiders) is not None:
            for t in german:
                tasks[f"eu_insider:{t}"] = lambda t=t, get=eu_insiders: get(t)
    if COMPARE in wanted:
        if sources.closes is None:
            missing[COMPARE].append("prices")
        else:
            tasks["closes"] = sources.closes
        if sources.verdicts is not None:
            tasks["verdicts"] = sources.verdicts
        else:
            missing[COMPARE].append("review")

    found: dict[str, object] = {}
    failed: set[str] = set()
    if tasks:
        begun = time.monotonic()
        ran: dict[str, float] = {}
        pool = ThreadPoolExecutor(max_workers=min(len(tasks), WORKERS))
        try:
            futures = {name: pool.submit(_timed(ran, name, tasks[name]))
                       for name in sorted(tasks, key=lambda n: n != "verdicts")}
            for name, future in futures.items():
                own = (max(budget_s, verdicts_budget_s) if name == "verdicts"
                       else budget_s)
                ceiling = begun + max(own, 2 * budget_s)
                try:
                    found[name] = _await(future, ran, name, own, ceiling)
                except Exception as exc:  # noqa: BLE001 — one source, not the page
                    obs.warn("today.source_failed", source=name.split(":")[0],
                             error_type=type(exc).__name__,
                             **_late(ran, name, begun))
                    failed.add(name.split(":")[0])
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    out_sections = []
    for sid in wanted:
        rows: list[dict] = []
        if sid == NEWS:
            for t in news_names:
                rows += news_rows(t, _listed(found, f"news:{t}"),
                                  _listed(found, f"filing:{t}"), day, tr)
            printed = _printed(_listed(found, "results"), companies, day)
            closes = found.get("closes")
            rows = print_rows(rows, printed, _print_sources(
                sources.print, _print_day(rows, printed)),
                closes if isinstance(closes, dict) else {}, day, tr, lang)
            rows = [r for r in rows if _fresh(r, shown, day)][:NEWS_ROWS]
            missing[sid] += [s for src, s in (("news", "yahoo"), ("filing", "edgar"))
                             if src in failed]
        elif sid == INSIDERS:
            for t in us:
                if row := insider_row(t, _listed(found, f"insider:{t}"), day, tr, lang):
                    rows.append(row)
            for t in german:
                if row := insider_row(t, _listed(found, f"eu_insider:{t}"), day, tr,
                                      lang, source=_eu_register(t)):
                    rows.append(row)
            # Clusters first, then by the money that changed hands.
            rows.sort(key=lambda r: (not r["data"]["cluster_buy"],
                                     -abs(r["data"]["net_value"])))
            rows = [r for r in rows if _fresh(r, shown, day)]
            missing[sid] += [s for src, s in (("insider", "sec"), ("eu_insider", "eu"))
                             if src in failed]
            if "eu" in missing[sid]:
                missing[sid].remove("eu")
                missing[sid] += sorted({_eu_register(t) for t in german})
        elif sid == COMPARE:
            closes = found.get("closes")
            verdicts = found.get("verdicts")
            if isinstance(closes, dict):
                rows = compare_rows(weights, kinds,
                                    verdicts if isinstance(verdicts, dict) else {},
                                    closes, tr, lang)
            if "closes" in failed:
                missing[sid].append("prices")
            if "verdicts" in failed:
                missing[sid].append("review")
        out_sections.append({
            "id": sid,
            "title": tr(f"today.section_{sid}"),
            "rows": rows,
            "note": "",
            "missing": sorted(set(missing[sid])),
        })
    every = sorted({m for sid in wanted for m in missing[sid]})
    obs.event("today.gather", shape=book, missing=every,
              rows={s["id"]: len(s["rows"]) for s in out_sections},
              ms=round((time.monotonic() - started) * 1000))
    return {"shape": book, "sections": out_sections, "missing": every}
