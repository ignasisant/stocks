"""The daily card's "Your routines": what the reader asks every day, answered.

A routine (`learnings`, kind "routine") is a question the reader puts to the
assistant every morning: "how is NVDA doing", "my portfolio against the S&P
this month". The chat answers it with live quotes (`market`) and, when asked
for one, a chart (`charts`). The card answers it with the same helpers before
the reader has typed anything, which is the point of keeping a routine.

The model gets data, not tools. Each routine's quotes and chart summary go
into the card's facts (`facts["routines"]`), so every figure an answer
prints has to pass the card's audit. The chart is drawn from the series
directly, never described by the model.

Bounded like the rest of the card: the routines are capped where they are
saved (`learnings.MAX_ROUTINES`), each one's fetches run concurrently, and the
whole lot shares one wall-clock budget. A throttled Yahoo costs the card a
routine's figures, not the card.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from stocks import obs
from stocks.chat import charts, engine, learnings, market

# The whole gather, every routine together. Runs before the model call, on
# the card's own thread, while the reader already has the computed card.
BUDGET_S = 8.0
# A routine names no window ("cómo va NVDA"): the month, which is what a
# morning question is about. The chat's own default is the year.
WINDOW = "1m"


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


def _one(routine: learnings.Learning, known: dict, db, base: str,
         lookup) -> tuple[dict, charts.Chart | None]:
    """One routine's facts and its chart (None when it asks for none)."""
    text = routine.text
    fact: dict = {"id": routine.id, "ask": text}
    chart = None
    if charts.wants(text):
        symbols = charts.targets(text, known, base=base, lookup=lookup)
        if symbols:
            chart = charts.build(
                symbols, charts.window_asked(text, default=WINDOW), base=base,
                book=charts.book_for(db, base) if charts.BOOK in symbols else None,
            )
    if chart is not None:
        fact["chart"] = chart_fact(chart)
    names = [*routine.tickers, *market.mentioned(text, known, lookup=lookup)]
    names = [n for n in dict.fromkeys(t.upper() for t in names if t)
             if n != charts.BOOK][: market.MAX_TICKERS]
    quotes = market.quotes(names) if names else []
    if quotes:
        fact["quotes"] = [quote_fact(q) for q in quotes]
    return fact, chart


def gather(
    routines: list[learnings.Learning],
    *,
    watchlist,
    db,
    base: str,
    translate=None,
    lookup=None,
    budget_s: float = BUDGET_S,
) -> tuple[list[dict], dict[str, dict]]:
    """(each routine's facts, {routine id: its chart as drawn}).

    A routine that ran out of time or failed keeps its question with no data,
    and the card says it could not answer it today rather than dropping it.
    """
    if not routines:
        return [], {}
    known = market.watchlist_names(Path(watchlist)) if watchlist else {}
    lookup = lookup or market._lookup
    deadline = time.monotonic() + budget_s
    pool = ThreadPoolExecutor(max_workers=len(routines))
    facts: list[dict] = []
    drawn: dict[str, dict] = {}
    try:
        futures = [pool.submit(_one, r, known, db, base, lookup) for r in routines]
        for routine, future in zip(routines, futures, strict=True):
            try:
                fact, chart = future.result(
                    timeout=max(0.0, deadline - time.monotonic()))
            except Exception as exc:  # noqa: BLE001 — one routine, not the card
                obs.warn("daily_action.routine_failed",
                         error_type=type(exc).__name__)
                fact, chart = {"id": routine.id, "ask": routine.text}, None
            facts.append(fact)
            if chart is not None:
                drawn[routine.id] = {
                    "window": chart.window,
                    "rebased": chart.rebased,
                    "series": charts.series(chart, translate),
                }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return facts, drawn


def seeded(routines: list[learnings.Learning]) -> list[dict]:
    """The routines' facts before anything was fetched: the questions alone,
    marked pending so the stand-in card shows them unanswered rather than
    saying it found no data (`daily.answered`)."""
    return [{"id": r.id, "ask": r.text, "pending": True} for r in routines]
