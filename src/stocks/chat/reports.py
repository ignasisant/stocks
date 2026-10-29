"""Which of my companies report soon? The earnings calendar, over the reader's book.

"¿Qué empresas de mi cartera presentan resultados en 7 días?" has an answer
the app already prints on the calendar page (`api.routes.earnings`): the
report dates of what the reader holds and follows. A model asked it with no
such figures answered "dime qué tickers tienes" (local review 2026-10-29),
and a provider with no tool loop (Gemini) has no way to look them up at all.
So the dates are read here, from the same cached calendar, and ride on the
question the way the allocation's weights do (`chat/allocation.py`).

Coins and funds never report and are left out before the lookup, as the
calendar page leaves them out; they are named so the answer can say why.

Each date carries the street's consensus (`earnings.consensus`): asked for
the estimates with dates alone, the model filled them from memory with
quarters two years old (local review 2026-10-30).
"""

from __future__ import annotations

import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from stocks import obs

if TYPE_CHECKING:
    from stocks.data.earnings import Consensus

# The window when the message names none: a fortnight covers "pronto" and
# "this week" read loosely, and is the calendar page's own first screen.
DEFAULT_DAYS = 14
MAX_DAYS = 120
# Dates quoted to the model at most; the soonest first.
MAX_ROWS = 25
# The consensus lookups, all at once; a name still out after this many
# seconds is quoted without one rather than holding the answer.
CONSENSUS_TIMEOUT_S = 8.0
CONSENSUS_WORKERS = 8
CONSENSUS_TTL_S = 6 * 3600  # the calendar's own cache

# Matched with the accents folded away. Results being asked about...
_EARNINGS_RE = re.compile(
    r"\bresultados\b|\bearnings\b|\bpresenta[nr]?\b|\bpublica[nr]? (?:sus )?cuentas\b|"
    r"\breport(?:s|ing)?\b|\bcuentas trimestrales\b|\btrimestrales\b",
    re.IGNORECASE,
)
# ... as dates, not as figures already out ("¿qué tal los resultados de Meta?").
_WHEN_RE = re.compile(
    r"\bcuando\b|\bwhen\b|\bproxim[oa]s?\b|\bnext\b|\bupcoming\b|\bsoon\b|"
    r"\bpronto\b|\besta semana\b|\bthis week\b|\beste mes\b|\bthis month\b|"
    r"\bdias?\b|\bdays?\b|\bsemanas?\b|\bweeks?\b|\bcalendario\b|\bcalendar\b|"
    r"\bfecha\b|\bdates?\b|\bmanana\b|\btomorrow\b|\bhoy\b|\btoday\b",
    re.IGNORECASE,
)
# ... of the reader's own names, not of one company the message names.
_MINE_RE = re.compile(
    r"\b(?:mi|mis|my) (?:cartera|portfolio|portafolio|book|inversiones|"
    r"investments|holdings|posiciones|positions|acciones|shares|empresas|"
    r"companies|valores|favoritos|watchlist|seguimiento)\b|"
    r"\btengo\b|\bi hold\b|\bi own\b|\bi have\b|\bdo i\b",
    re.IGNORECASE,
)
_WINDOW_RE = re.compile(
    r"\b(\d{1,3})\s*(dias?|days?|semanas?|weeks?|mes(?:es)?|months?)\b",
    re.IGNORECASE,
)
_NAMED_WINDOWS = (
    (re.compile(r"\bhoy\b|\btoday\b", re.IGNORECASE), 0),
    (re.compile(r"\bmanana\b|\btomorrow\b", re.IGNORECASE), 1),
    (re.compile(r"\besta semana\b|\bthis week\b|\bproxima semana\b|\bnext week\b",
                re.IGNORECASE), 7),
    (re.compile(r"\beste mes\b|\bthis month\b|\bproximo mes\b|\bnext month\b",
                re.IGNORECASE), 31),
)


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(ch))


def wants(message: str) -> bool:
    """Whether the message asks when the reader's own companies report."""
    text = _fold(message)
    return all(p.search(text) for p in (_EARNINGS_RE, _WHEN_RE, _MINE_RE))


def days_asked(message: str) -> int:
    """The window the message names, in days, or `DEFAULT_DAYS`."""
    text = _fold(message)
    if m := _WINDOW_RE.search(text):
        n, unit = int(m.group(1)), m.group(2).lower()
        scale = 7 if unit.startswith(("sem", "week")) else (
            30 if unit.startswith(("mes", "month")) else 1)
        return max(0, min(n * scale, MAX_DAYS))
    return next((days for pattern, days in _NAMED_WINDOWS if pattern.search(text)),
                DEFAULT_DAYS)


@dataclass(frozen=True)
class Due:
    ticker: str
    day: date
    in_days: int
    held: bool
    consensus: Consensus | None = None


_WHEN = {"bmo": "before the open", "amc": "after the close"}


def _money(value: float) -> str:
    for scale, unit in ((1e9, "B"), (1e6, "M")):
        if abs(value) >= scale:
            return f"{value / scale:.2f}{unit}"
    return f"{value:,.0f}"


def _expected(c: Consensus | None) -> str:
    if c is None:
        return "no consensus on file"
    parts = [f"consensus EPS {c.eps:.2f}" if c.eps is not None else "no EPS consensus",
             f"revenue {_money(c.revenue)}" if c.revenue is not None
             else "no revenue consensus"]
    if c.hour in _WHEN:
        parts.insert(0, _WHEN[c.hour])
    return ", ".join(parts)


@dataclass(frozen=True)
class Ahead:
    """The report dates inside the window, for the names the reader has."""

    days: int
    due: tuple[Due, ...]
    checked: int  # names looked up
    held: int  # of them, open positions
    undated: tuple[str, ...]  # looked up, no date announced yet
    skipped: tuple[str, ...]  # coins and funds: they never report

    def line(self, lang: str = "en") -> str:
        """The prompt's paragraph: every date in the window, quoted."""
        rows = [
            f"- {d.ticker} ({'held' if d.held else 'followed, not held'}): "
            f"{d.day.isoformat()}, "
            + ("today" if d.in_days == 0 else f"in {d.in_days} days")
            + f"; {_expected(d.consensus)}"
            for d in self.due[:MAX_ROWS]
        ]
        found = "\n".join(rows) if rows else (
            "- none of them has a report date inside the window")
        tail = []
        if self.undated:
            tail.append("no date announced yet for "
                        + ", ".join(self.undated[:12]))
        if self.skipped:
            tail.append("left out because coins and funds do not report: "
                        + ", ".join(self.skipped[:12]))
        return (
            "\n\n---\nThe app's earnings calendar for the reader's own names "
            f"(the {self.checked} companies they hold or follow, {self.held} of "
            f"them held), report dates in the next {self.days} days, soonest "
            "first. Answer from these dates, held names first; do not ask the "
            "reader which tickers they own. The EPS and revenue estimates are "
            "the street's consensus for that print, revenue in the currency the "
            "company reports in: quote only these, and where a row has none say "
            "there is none — never fill one in from memory or from an earlier "
            "quarter:\n" + found
            + ("\n- " + "; ".join(tail) if tail else "")
        )


_consensus_cache: dict[tuple[str, date], tuple[float, Consensus | None]] = {}


def _with_consensus(due: list[Due]) -> list[Due]:
    """`due` with each quoted row's consensus, looked up at once and kept
    `CONSENSUS_TTL_S`; a lookup that fails or overruns leaves the row bare."""
    from stocks.data import earnings

    now = time.monotonic()
    rows = due[:MAX_ROWS]
    fresh = {(d.ticker, d.day): hit[1] for d in rows
             if (hit := _consensus_cache.get((d.ticker, d.day)))
             and now - hit[0] < CONSENSUS_TTL_S}
    missing = [d for d in rows if (d.ticker, d.day) not in fresh]
    if missing:
        pool = ThreadPoolExecutor(max_workers=min(CONSENSUS_WORKERS, len(missing)))
        try:
            futures = {pool.submit(earnings.consensus, d.ticker, d.day): d
                       for d in missing}
            done, _ = wait(list(futures), timeout=CONSENSUS_TIMEOUT_S)
            for future in done:
                d = futures[future]
                got = future.result() if future.exception() is None else None
                fresh[(d.ticker, d.day)] = got
                _consensus_cache[(d.ticker, d.day)] = (now, got)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    looked = [replace(d, consensus=fresh.get((d.ticker, d.day))) for d in rows]
    return looked + due[MAX_ROWS:]


def build(watchlist: Path, db: Path, days: int = DEFAULT_DAYS,
          today: date | None = None) -> Ahead | None:
    """The calendar over the reader's names, or None when they have none."""
    from stocks.api import loaders
    from stocks.config import load_watchlist
    from stocks.data.crypto import is_crypto
    from stocks.data.funds import is_fund

    holdings = load_watchlist(watchlist) if watchlist.exists() else []
    held = set(loaders.held(str(db), loaders.db_mtime(str(db)))) if db.exists() else set()
    held |= {h.ticker for h in holdings if h.is_position}
    names = sorted(held | {h.ticker for h in holdings})
    if not names:
        return None
    # Cache-only fund test, as the calendar page: a cold cache keeps the name.
    skipped = tuple(t for t in names if is_crypto(t) or is_fund(t, fetch=False))
    reporting = tuple(t for t in names if t not in skipped)
    events, _results = loaders.earnings_calendar(reporting)
    when = {e.ticker: e for e in events}
    today = today or date.today()
    due = []
    for e in events:
        if e.date is None:
            continue
        ahead = (e.date - today).days
        if 0 <= ahead <= days:
            due.append(Due(e.ticker, e.date, ahead, e.ticker in held))
    due.sort(key=lambda d: (d.in_days, not d.held, d.ticker))
    due = _with_consensus(due)
    undated = tuple(t for t in reporting
                    if when.get(t) is None or when[t].date is None)
    obs.event("chat.reports_ahead", days=days, names=len(reporting), due=len(due))
    return Ahead(days=days, due=tuple(due), checked=len(reporting),
                 held=sum(1 for t in reporting if t in held),
                 undated=undated, skipped=skipped)
