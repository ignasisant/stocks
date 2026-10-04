"""The data behind the reader's brief: what the daily card is asked to say.

The brief is the reader's own text for the card (`learnings`, kind "routine";
a few older accounts keep it as several routines, read here as one): "a
summary of what moved my book, the events this week, my insiders, review my
kill criteria". Each line is one thing to cover, and the card answers the
brief section by section instead of its fixed sections (`daily`).

What each line needs fetched is the brief's recipe (`routine_plan`), and this
module fetches it before the model writes a word, into `facts["brief"]`:

- `quotes` / `markets` / `earnings`: the instruments it names, the market
  groups it asks about, company results reported lately or coming up;
- `charts`: one per line that asks for a chart (`charts`), drawn from the
  series directly and only described to the model;
- `events`: the next AHEAD_DAYS days for the reader's own names — results,
  ex-dividend dates — plus the Fed's and ECB's decisions and the tax
  calendar's deadlines;
- `insiders`: open-market trades by the insiders of the reader's largest US
  positions (SEC Form 4), INSIDER_DAYS back, and of their German ones off
  BaFin's register;
- `news`: the last days' headlines naming the companies the brief names or
  the reader holds most of — third-party titles, data for the card to
  report, never to follow;
- `filings`: the 8-Ks those US companies filed this week, each as the kinds
  of news its items report (a deal, a departure, results);
- `holders`: the big investors in them — the largest funds, their stakes and
  how much each added or cut over the last reported quarter (13F, so a
  quarter old, and dated);
- `exits`: the reader's price alerts, with the price now, and the decisions,
  goals and limits they saved — the closest thing the app keeps to kill
  criteria.

The model gets data, not tools, so every figure the card prints has to pass
its audit. A source that failed or ran out of time is listed in `missing`,
and the card says it has no data for that line today rather than "nothing
happened" — an empty list from a source that answered is the other thing.

Bounded like the rest of the card: one wall-clock budget for every fetch,
per-name lookups for a handful of names at most, and a throttled Yahoo
costs the card a source, not the card.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from stocks import obs
from stocks.chat import charts, engine, learnings, market, routine_plan

# The whole gather, every source together. Runs before the model call, on
# the card's own thread, while the reader already has the computed card.
BUDGET_S = 20.0
# A routine names no window ("cómo va NVDA"): the month, which is what a
# morning question is about. The chat's own default is the year.
WINDOW = "1m"
# Results: a print this many days back is still news (Monday's card reads
# Friday's), and one this many days ahead is worth a heads-up.
RECENT_DAYS = 4
AHEAD_DAYS = 7
MAX_PRINTS = 6
# Form 4 is one SEC request per name: the largest positions only, a month
# back, and the latest few trades each.
MAX_INSIDER_NAMES = 6
INSIDER_DAYS = 30
INSIDER_TRADES = 3
# German positions BaFin is asked about: one register search each.
MAX_EU_INSIDER_NAMES = 3
# Headlines: one Yahoo search per name, a few titles each.
MAX_NEWS_NAMES = 5
# 8-Ks: the week's, off the same SEC feed the insiders read.
FILING_DAYS = 7
MAX_FILINGS = 3
# Big investors: the funds that moved the most of the top holders.
MAX_HOLDER_NAMES = 4
HOLDER_ROWS = 3
MAX_EVENTS = 8
MAX_ALERTS = 10
MAX_NOTES = 8
NOTE_KINDS = ("decision", "goal", "constraint")
# A line of the brief, as the reader may have listed it: "- ", "• ", "3) ".
_GLYPH_RE = re.compile(r"^\s*(?:[-•*·]+|\d{1,2}[.)])\s*")
# A list typed on one line — "mis movimientos - eventos - insiders" — is a
# list all the same. A dash between words is prose ("S&P 500 - Nasdaq"), so
# a line splits only at two or more of them.
_INLINE_RE = re.compile(r"\s+[-–•]\s+(?=\S)")

# (upcoming events, past results) for a tuple of tickers — the earnings
# calendar's shape (`data.earnings.calendar_events`).
Calendar = Callable[[tuple[str, ...]], tuple[list, list]]


@dataclass(frozen=True)
class Sources:
    """What the brief is answered from besides quotes, handed in by the API
    so its caches serve the card too. A None loader is a source this caller
    does not have: its part of the brief is listed as missing.

    `held` is the reader's positions, largest first; `followed` their
    reporting names (held and followed); `entries` the watchlist's holdings,
    whose `alerts` are the exits; `notes` their saved decisions and goals."""

    calendar: Calendar | None = None
    insiders: Callable[[str], list] | None = None
    eu_insiders: Callable[[str], list] | None = None
    news: Callable[[str], list] | None = None
    filings: Callable[[str], list] | None = None
    holders: Callable[[str], object] | None = None
    ex_dividends: Callable[[tuple[str, ...]], list] | None = None
    tax_code: str | None = None
    held: tuple[str, ...] = ()
    followed: tuple[str, ...] = ()
    entries: tuple = ()
    notes: tuple = ()


def load(prefs: dict, chat_path) -> list[learnings.Learning]:
    """The account's routines, oldest first; [] when memory is off."""
    if chat_path is None or not engine.memory_on(prefs or {}):
        return []
    try:
        found = learnings.load(learnings.path_for(Path(chat_path)))
    except Exception:  # noqa: BLE001 — a card without routines still stands
        return []
    return [i for i in found if i.kind == "routine"][: learnings.MAX_ROUTINES]


def _num(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def quote_fact(q: market.Quote) -> dict:
    """One quote as the facts carry it. `change_pct` is against the previous
    close, which is what "today" means in the prompt."""
    out: dict = {"ticker": q.ticker}
    if q.name:
        out["name"] = q.name
    for key, value in (("price", q.price), ("year_high", q.year_high),
                       ("year_low", q.year_low)):
        if (n := _num(value)) is not None:
            out[key] = round(n, 4)
    if q.currency:
        out["currency"] = q.currency
    if q.day_pct is not None:
        out["change_pct"] = round(q.day_pct * 100, 2)
    return out


def chart_fact(chart: charts.Chart) -> dict:
    """A chart as the facts carry it: each line's window and its figures.
    The book's line is a growth index, so only its change is a figure."""
    lines = []
    for ln in chart.lines:
        row: dict = {"portfolio": True} if ln.index else {"ticker": ln.symbol}
        row |= {
            "currency": ln.currency,
            "first_on": ln.first_on[:10],
            "last_on": ln.last_on[:10],
            "change_pct": round(ln.change * 100, 2),
        }
        if not ln.index:
            row |= {
                "first": round(ln.first, 4),
                "last": round(ln.last, 4),
                "high": round(ln.high, 4),
                "low": round(ln.low, 4),
            }
        lines.append(row)
    return {"window": chart.window, "lines": lines}


def _calendar(names: tuple[str, ...]) -> tuple[list, list]:
    """The earnings calendar, uncached — the API hands its cached one in."""
    from stocks.config import Holding
    from stocks.data.earnings import calendar_events

    return calendar_events([Holding(ticker=t) for t in names]) if names else ([], [])


def _scope_names(scope: str, named: list[str], followed: tuple[str, ...]) -> list[str]:
    if scope == "named":
        return named
    if scope == "large":
        return [*followed, *routine_plan.LARGE]
    return list(followed) or list(routine_plan.LARGE)


def earnings_fact(scope: str, names: list[str], followed: tuple[str, ...], *,
                  day: date, calendar: Calendar) -> dict:
    """Results for `names`: printed in the last RECENT_DAYS, newest first,
    with the session's move, and due in the next AHEAD_DAYS, soonest first.
    `mine` marks the reader's own names."""
    names = list(dict.fromkeys(n.upper() for n in names if n))
    out: dict = {"scope": scope, "reported": [], "upcoming": []}
    if not names:
        return out
    upcoming, printed = calendar(tuple(sorted(names)))
    own = {t.upper() for t in followed}
    for r in sorted(printed, key=lambda r: r.date, reverse=True):
        ago = (day - r.date).days
        if not 0 <= ago <= RECENT_DAYS or len(out["reported"]) >= MAX_PRINTS:
            continue
        row: dict = {"ticker": r.ticker, "date": r.date.isoformat(), "days_ago": ago,
                     "mine": r.ticker.upper() in own}
        for key in ("reported_eps", "eps_estimate", "surprise_pct"):
            if (n := _num(getattr(r, key, None))) is not None:
                row[key] = round(n, 4)
        if r.beat is not None:
            row["beat"] = r.beat
        out["reported"].append(row)
    for e in upcoming:
        if (e.date is None or e.days_until is None
                or not 0 <= e.days_until <= AHEAD_DAYS
                or len(out["upcoming"]) >= MAX_PRINTS):
            continue
        out["upcoming"].append({"ticker": e.ticker, "date": e.date.isoformat(),
                                "in_days": e.days_until,
                                "mine": e.ticker.upper() in own})
    moved = {q.ticker: q for q in market.quotes(
        [r["ticker"] for r in out["reported"]], limit=MAX_PRINTS)}
    for row in out["reported"]:
        q = moved.get(row["ticker"].upper())
        if q is not None and q.day_pct is not None:
            row["change_pct"] = round(q.day_pct * 100, 2)
    return out


def _items(raw: str) -> list[str]:
    """One written line as the things it asks: itself, or the items of a
    list typed inline, each with its glyph dropped."""
    parts = _INLINE_RE.split(raw)
    if len(parts) < 3:
        parts = [raw]
    return [item for part in parts if (item := _GLYPH_RE.sub("", part).strip())]


def asks(routines: list[learnings.Learning]) -> list[dict]:
    """The brief's lines, numbered from 1: {"n", "ask"}. Each non-empty line
    is one thing to cover — each item, for a list typed on one line."""
    out: list[dict] = []
    for routine in routines:
        for raw in routine.text.splitlines():
            for line in _items(raw):
                if len(out) < learnings.MAX_ROUTINE_LINES:
                    out.append({"n": len(out) + 1, "ask": line})
    return out


def symbols(names, known: dict[str, str]) -> list[str]:
    """The ticker-shaped words of a brief that are worth quoting. A capital on
    its own in a paragraph is a placeholder ("vender X, comprar Y"), not a
    listing: a one-letter symbol counts only when the reader follows it."""
    followed = set(known.values())
    return [n for n in names if n and (len(n) > 1 or n in followed)]


def recipe_of(routines: list[learnings.Learning]) -> routine_plan.Recipe:
    """Every routine's recipe in one: the brief fetches what any line asks."""
    out = routine_plan.Recipe()
    for routine in routines:
        out = out.widened(routine_plan.current(routine))
    return out


def signature(routines: list[learnings.Learning]) -> str:
    """A short hash of the brief's wording, "" with none: a card written for
    other words — or for no brief at all — no longer stands."""
    if not routines:
        return ""
    text = "\n".join(r.text for r in routines)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def seeded(routines: list[learnings.Learning]) -> dict:
    """The brief before anything was fetched: its lines alone, marked pending
    so the stand-in card says the brief is being written rather than that it
    found no data."""
    if not routines:
        return {}
    return {"asks": asks(routines), "sig": signature(routines), "pending": True}


def _quotes(text: str, tickers, recipe: routine_plan.Recipe, known: dict,
            lookup) -> list[dict]:
    # A brief about the market or about results names things in words ("la
    # Bolsa", "Wall Street") that a Yahoo name search turns into some
    # unrelated listing; its recipe already says what to fetch.
    planned = bool(recipe.markets or recipe.earnings or recipe.symbols or recipe.topics)
    said = market.mentioned(text, known, lookup=(lambda _name: "") if planned else lookup)
    names = symbols([*tickers, *recipe.symbols, *said], known)
    names = [n for n in dict.fromkeys(t.upper() for t in names if t)
             if n != charts.BOOK][: routine_plan.MAX_SYMBOLS]
    quotes = market.quotes(names, limit=routine_plan.MAX_SYMBOLS) if names else []
    return [quote_fact(q) for q in quotes]


def _markets(recipe: routine_plan.Recipe) -> list[dict]:
    pairs = recipe.market_quotes()
    if not pairs:
        return []
    named = dict(pairs)
    got = market.quotes([s for s, _ in pairs], limit=len(pairs))
    return [{**quote_fact(q), "name": named.get(q.ticker, q.ticker)} for q in got]


def _chart(ask: str, known: dict, db, base: str, lookup) -> charts.Chart | None:
    if not charts.wants(ask):
        return None
    symbols = charts.targets(ask, known, base=base, lookup=lookup)
    if not symbols:
        return None
    return charts.build(
        symbols, charts.window_asked(ask, default=WINDOW), base=base,
        book=charts.book_for(db, base) if charts.BOOK in symbols else None,
    )


def events_fact(sources: Sources, day: date) -> dict:
    """The next AHEAD_DAYS days: the reader's names reporting and going
    ex-dividend, the central banks deciding, the tax deadlines falling due.
    Each list soonest first; a list that could not be read is left out."""
    from stocks.data import macro_calendar
    from stocks.portfolio.tax import deadlines

    names = tuple(sorted(sources.followed))
    out: dict = {"days": AHEAD_DAYS}
    if sources.calendar is not None:
        try:
            upcoming, _ = sources.calendar(names) if names else ([], [])
            out["earnings"] = sorted(
                ({"ticker": e.ticker, "date": e.date.isoformat(), "in_days": e.days_until}
                 for e in upcoming
                 if e.date is not None and e.days_until is not None
                 and 0 <= e.days_until <= AHEAD_DAYS),
                key=lambda r: r["in_days"])[:MAX_EVENTS]
        except Exception as exc:  # noqa: BLE001 — one source, not the brief
            obs.warn("daily_action.brief_source_failed", source="earnings",
                     error_type=type(exc).__name__)
    if sources.ex_dividends is not None:
        try:
            found = sources.ex_dividends(names) if names else []
            rows = []
            for d in sorted(found, key=lambda d: d.days_until):
                if not 0 <= d.days_until <= AHEAD_DAYS:
                    continue
                row: dict = {"ticker": d.ticker, "date": d.ex_date.isoformat(),
                             "in_days": d.days_until}
                if (n := _num(d.per_share)) is not None:
                    row |= {"per_share": round(n, 4), "currency": d.currency or ""}
                rows.append(row)
            out["ex_dividends"] = rows[:MAX_EVENTS]
        except Exception as exc:  # noqa: BLE001
            obs.warn("daily_action.brief_source_failed", source="ex_dividends",
                     error_type=type(exc).__name__)
    banks = []
    for bank in (macro_calendar.FED, macro_calendar.ECB):
        when = macro_calendar.next_decision(bank, day)
        if when is not None and (when - day).days <= AHEAD_DAYS:
            banks.append({"bank": bank, "date": when.isoformat(),
                          "in_days": (when - day).days})
    out["central_banks"] = banks
    if sources.tax_code:
        try:
            out["tax"] = [
                {"deadline": d.key, "year": d.year_label, "date": d.date.isoformat(),
                 "in_days": d.days_until(day)}
                for d in deadlines.due_soon(sources.tax_code, day, within=AHEAD_DAYS)
            ]
        except Exception as exc:  # noqa: BLE001
            obs.warn("daily_action.brief_source_failed", source="tax",
                     error_type=type(exc).__name__)
    return out


def _companies(names) -> list[str]:
    """The names a company source can speak for: no coins, indices or
    futures. Each once, in the order given."""
    from stocks.data.crypto import is_crypto

    return [t for t in dict.fromkeys(names)
            if t and "=" not in t and not t.startswith("^") and not is_crypto(t)]


def _sec_names(held, cap: int = MAX_INSIDER_NAMES) -> list[str]:
    """The positions the SEC can speak for: US listings, no coins or funds."""
    return [t for t in _companies(held) if "." not in t][:cap]


def _german_names(held) -> list[str]:
    from stocks.data.bafin import german_listing

    return [t for t in _companies(held) if german_listing(t)][:MAX_EU_INSIDER_NAMES]


def news_fact(ticker: str, headlines: list) -> dict:
    """One name's headlines, newest first. Listed with none: it was checked."""
    return {"ticker": ticker, "headlines": [
        {"date": h.published.isoformat(), "publisher": h.publisher, "title": h.title}
        for h in headlines]}


def filings_fact(ticker: str, reports: list, day: date) -> dict:
    """One name's 8-Ks over FILING_DAYS, each as the news its items report."""
    cutoff = day - timedelta(days=FILING_DAYS)
    return {"ticker": ticker, "window_days": FILING_DAYS, "filings": [
        {"date": r.filed.isoformat(), "form": r.form, "items": r.topics}
        for r in reports if r.filed >= cutoff][:MAX_FILINGS]}


def holders_fact(ticker: str, found) -> dict:
    """One name's big investors: the share funds hold, the largest stakes,
    and the funds among them that added or cut the most last quarter."""
    out: dict = {"ticker": ticker}
    if found is None:
        return out

    def row(h) -> dict:
        return {"holder": h.name, "pct_held": h.pct_held, "change_pct": h.change_pct}

    out["as_of"] = found.as_of.isoformat() if found.as_of else None
    if found.institutions_pct is not None:
        out["institutions_pct"] = found.institutions_pct
    if found.insiders_pct is not None:
        out["insiders_pct"] = found.insiders_pct
    out["top"] = [row(h) for h in found.holders[:HOLDER_ROWS]]
    out["adding"] = [row(h) for h in sorted(found.adding, key=lambda h: -h.change_pct)
                     [:HOLDER_ROWS]]
    out["cutting"] = [row(h) for h in sorted(found.cutting, key=lambda h: h.change_pct)
                      [:HOLDER_ROWS]]
    return out


def insider_fact(ticker: str, txs: list, day: date) -> dict:
    """One name's open-market insider trades over INSIDER_DAYS: the totals,
    and the latest few. A name with none is still listed — it was checked."""
    from stocks.data.insiders import summarize

    summary = summarize(txs, ref=day, within_days=INSIDER_DAYS)
    out: dict = {"ticker": ticker, "window_days": INSIDER_DAYS,
                 "buys": summary.buy_count, "sells": summary.sell_count}
    if not summary.has_activity:
        return out
    cutoff = day - timedelta(days=INSIDER_DAYS)
    out |= {
        "buy_value": round(summary.buy_value, 2),
        "sell_value": round(summary.sell_value, 2),
        "net_value": round(summary.net_value, 2),
        "buyers": summary.buyers,
        "sellers": summary.sellers,
        "cluster_buy": summary.cluster_buy,
        "currency": next((t.currency for t in txs if t.is_open_market), "USD"),
    }
    latest = sorted((t for t in txs if t.is_open_market and t.date and t.date >= cutoff),
                    key=lambda t: t.date, reverse=True)[:INSIDER_TRADES]
    out["latest"] = [
        {"date": t.date.isoformat(), "insider": t.insider,
         "role": t.relationship, "side": "buy" if t.acquired else "sell",
         "shares": round(t.shares, 2),
         **({"price": round(t.price, 4)} if t.price is not None else {})}
        for t in latest
    ]
    return out


def exits_fact(sources: Sources) -> dict:
    """The reader's own exit levels: each alert with the price now and how
    far it is, and the decisions, goals and limits they saved."""
    alerts = []
    for holding in sources.entries:
        for alert in getattr(holding, "alerts", None) or []:
            row: dict = {"ticker": holding.ticker, "type": alert.type}
            for key in ("price", "pct", "level", "window"):
                if (value := getattr(alert, key, None)) is not None:
                    row[key] = value
            alerts.append(row)
    alerts = alerts[:MAX_ALERTS]
    priced = list(dict.fromkeys(a["ticker"] for a in alerts if "price" in a))
    now = {q.ticker: q for q in market.quotes(priced, limit=MAX_ALERTS)} if priced else {}
    for row in alerts:
        q = now.get(str(row["ticker"]).upper())
        price = _num(q.price) if q is not None else None
        if price is None:
            continue
        row["now"] = round(price, 4)
        if (level := _num(row.get("price"))) and level > 0:
            row["distance_pct"] = round((level / price - 1) * 100, 2)
    notes = [
        {"kind": n.kind, "text": learnings.one_line(n.text), "tickers": list(n.tickers)}
        for n in sources.notes if n.kind in NOTE_KINDS
    ][:MAX_NOTES]
    return {"alerts": alerts, "notes": notes}


def gather(
    routines: list[learnings.Learning],
    *,
    watchlist,
    db,
    base: str,
    translate=None,
    lookup=None,
    budget_s: float = BUDGET_S,
    day: date | None = None,
    sources: Sources | None = None,
) -> tuple[dict, dict[int, dict]]:
    """(the brief's facts, {line n: its chart as drawn}).

    Every source runs at once under one wall-clock budget. One that failed
    or ran late is named in `missing`, so the card can tell "no data today"
    from "nothing happened".
    """
    if not routines:
        return {}, {}
    sources = sources or Sources()
    day = day or date.today()
    lines = asks(routines)
    recipe = recipe_of(routines)
    text = "\n".join(r.text for r in routines)
    known = market.watchlist_names(Path(watchlist)) if watchlist else {}
    tickers = symbols(list(dict.fromkeys(t for r in routines for t in r.tickers)), known)
    lookup = lookup or market._lookup
    calendar = sources.calendar or _calendar

    tasks: dict[str, Callable[[], object]] = {
        "quotes": lambda: _quotes(text, tickers, recipe, known, lookup),
    }
    if recipe.markets:
        tasks["markets"] = lambda: _markets(recipe)
    if recipe.earnings:
        names = [*tickers, *recipe.symbols]
        tasks["earnings"] = lambda: earnings_fact(
            recipe.earnings, _scope_names(recipe.earnings, names, sources.followed),
            sources.followed, day=day, calendar=calendar)
    if "events" in recipe.topics:
        tasks["events"] = lambda: events_fact(sources, day)
    if "exits" in recipe.topics:
        tasks["exits"] = lambda: exits_fact(sources)
    # Per-name sources: (where the rows land, task prefix, names, one name's
    # fact). The brief's own names first, then the largest positions.
    named = _companies([*tickers, *recipe.symbols, *sources.held])
    per_name: list[tuple[str, str, list[str], Callable[[str], dict]]] = []
    if "insiders" in recipe.topics and (insiders := sources.insiders) is not None:
        per_name.append(("insiders", "insider", _sec_names(sources.held), lambda t: (
            insider_fact(t, insiders(t) or [], day))))
    if "insiders" in recipe.topics and (eu_insiders := sources.eu_insiders) is not None:
        per_name.append(("insiders", "eu_insider", _german_names(sources.held),
                         lambda t: {**insider_fact(t, eu_insiders(t) or [], day),
                                    "source": "BaFin"}))
    if "news" in recipe.topics and (news := sources.news) is not None:
        per_name.append(("news", "news", named[:MAX_NEWS_NAMES],
                         lambda t: news_fact(t, news(t) or [])))
    if "filings" in recipe.topics and (filings := sources.filings) is not None:
        per_name.append(("filings", "filing", _sec_names(named), lambda t: (
            filings_fact(t, filings(t) or [], day))))
    if "holders" in recipe.topics and (holders := sources.holders) is not None:
        per_name.append(("holders", "holders", _sec_names(named, MAX_HOLDER_NAMES),
                         lambda t: holders_fact(t, holders(t))))
    for _key, prefix, names, fact in per_name:
        for ticker in names:
            tasks[f"{prefix}:{ticker}"] = lambda t=ticker, f=fact: f(t)
    for line in lines:
        if charts.wants(line["ask"]):
            tasks[f"chart:{line['n']}"] = (
                lambda a=line["ask"]: _chart(a, known, db, base, lookup))

    out: dict = {"asks": lines, "sig": signature(routines)}
    drawn: dict[int, dict] = {}
    missing: list[str] = []
    for topic in ("insiders", "news", "filings", "holders"):
        if topic in recipe.topics and getattr(sources, topic) is None:
            missing.append(topic)
    deadline = time.monotonic() + budget_s
    pool = ThreadPoolExecutor(max_workers=min(len(tasks), 12))
    try:
        futures = {name: pool.submit(task) for name, task in tasks.items()}
        found: dict[str, object] = {}
        for name, future in futures.items():
            try:
                found[name] = future.result(timeout=max(0.0, deadline - time.monotonic()))
            except Exception as exc:  # noqa: BLE001 — one source, not the brief
                obs.warn("daily_action.brief_source_failed",
                         source=name.split(":")[0], error_type=type(exc).__name__)
                missing.append(name)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    for key in ("quotes", "markets", "earnings", "events", "exits"):
        if found.get(key):
            out[key] = found[key]
    for key, prefix, names, _fact in per_name:
        if not names:
            continue
        rows = [found[f"{prefix}:{t}"] for t in names if f"{prefix}:{t}" in found]
        out.setdefault(key, []).extend(rows)
        if len(rows) < len(names):
            missing = [m for m in missing if not m.startswith(f"{prefix}:")] + [key]
    drawn_facts = []
    for line in lines:
        chart = found.get(f"chart:{line['n']}")
        if isinstance(chart, charts.Chart):
            drawn_facts.append({"n": line["n"], **chart_fact(chart)})
            drawn[line["n"]] = {
                "window": chart.window,
                "rebased": chart.rebased,
                "series": charts.series(chart, translate),
            }
    if drawn_facts:
        out["charts"] = drawn_facts
    if missing:
        out["missing"] = sorted({m.split(":")[0] for m in missing})
    return out, drawn
