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

Looking back ("resultados semana pasada"), a print is more than EPS against
the consensus: the quarter's revenue and margin, the release's own outlook
and opening lines (`views.briefing.print_facts`), the exit rules the reader
wrote for the name, the book's own money over the same days against the
S&P 500 bought with it (and from the book's first day, as every index
comparison runs), and who reports next. Prod 2026-11-09: the reader showed
the answer they expected, and it was built from exactly these.
"""

from __future__ import annotations

import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
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
# A print's statement and press release (`print_facts`) take longer to read
# than a consensus: SEC and Yahoo, one name after another per worker.
FACTS_TIMEOUT_S = 12.0
# Held prints whose release is read; and of each, the opening quoted.
RELEASE_NAMES = 12
RELEASE_CHARS = 320
# Looking back, the dates coming up next are listed this far ahead.
NEXT_DAYS = 7
MONTH_DAYS = 30  # the book's month beside the window asked

# Matched with the accents folded away. Results being asked about...
_EARNINGS_RE = re.compile(
    r"\bresultados\b|\bearnings\b|\bpresenta[nr]?\b|\bpublica[nr]? (?:sus )?cuentas\b|"
    r"\breport(?:s|ed|ing)?\b|\bcuentas trimestrales\b|\btrimestrales\b|"
    r"\bpresentaron\b|\bhan presentado\b",
    re.IGNORECASE,
)
# ... over a span of the calendar, not one company's figures ("¿qué tal los
# resultados de Meta?").
_WHEN_RE = re.compile(
    r"\bcuando\b|\bwhen\b|\bproxim[oa]s?\b|\bnext\b|\bupcoming\b|\bsoon\b|"
    r"\bpronto\b|\besta semana\b|\bthis week\b|\beste mes\b|\bthis month\b|"
    r"\bdias?\b|\bdays?\b|\bsemanas?\b|\bweeks?\b|\bcalendario\b|\bcalendar\b|"
    r"\bfecha\b|\bdates?\b|\bmanana\b|\btomorrow\b|\bhoy\b|\btoday\b|"
    r"\bayer\b|\byesterday\b|\bmes pasado\b|\blast month\b",
    re.IGNORECASE,
)
# The span lies behind: the prints already out, not the dates ahead. Prod
# 2026-11-08: "resultados semana pasada de acciones en mi cartera" was read
# fourteen days forward and answered "no hay registros".
_PAST_RE = re.compile(
    r"\bpasad[oa]s?\b(?! manana)|\bultim[oa]s\b|\blast\b|\bpast\b|\bprevious\b|"
    r"\banterior\b|\bayer\b|\byesterday\b|\bpresentaron\b|\bhan presentado\b|"
    r"\breported\b",
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
    (re.compile(r"\bayer\b|\byesterday\b", re.IGNORECASE), 1),
    (re.compile(r"\bsemana pasada\b|\blast week\b|\bpast week\b", re.IGNORECASE), 7),
    (re.compile(r"\bmes pasado\b|\blast month\b|\bpast month\b", re.IGNORECASE), 31),
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


def looks_back(message: str) -> bool:
    """Whether the window asked about is behind today: the prints already out."""
    return bool(_PAST_RE.search(_fold(message)))


@dataclass(frozen=True)
class Due:
    ticker: str
    day: date
    in_days: int
    held: bool
    consensus: Consensus | None = None


@dataclass(frozen=True)
class Printed:
    ticker: str
    day: date
    days_ago: int
    held: bool
    reported_eps: float | None
    eps_estimate: float | None
    surprise_pct: float | None
    reaction: float | None = None  # % from the last close before to the first after
    # `print_facts`: revenue, revenue_yoy_pct, currency, operating_margin_pct,
    # release (the press release's text, US filers).
    facts: dict = field(default_factory=dict)
    rules: tuple[str, ...] = ()  # the reader's exit rules for the name

    def said(self) -> str:
        if self.reported_eps is None:
            figures = "the figures are not on file yet"
        else:
            figures = f"EPS {self.reported_eps:.2f} against " + (
                f"a consensus of {self.eps_estimate:.2f}"
                if self.eps_estimate is not None else "no consensus on file")
            if self.surprise_pct is not None:
                figures += f" (surprise {self.surprise_pct:+.1f}%)"
        facts = self.facts
        if (revenue := facts.get("revenue")) is not None:
            figures += f"; revenue {_money(revenue)} {facts.get('currency') or 'USD'}"
            if facts.get("revenue_yoy_pct") is not None:
                figures += f" ({facts['revenue_yoy_pct']:+.1f}% on the year)"
        if facts.get("operating_margin_pct") is not None:
            figures += f"; operating margin {facts['operating_margin_pct']:.1f}%"
        move = (f"shares {self.reaction:+.1f}% across the print"
                if self.reaction is not None else "no price move on file")
        return f"{figures}; {move}"

    def detail(self) -> list[str]:
        """The lines under a print's row: the release's outlook and opening,
        then the reader's exit rules for the name."""
        from stocks.chat import today_sections

        out = []
        release = _body(str(self.facts.get("release") or ""))
        opening = _opening(release)
        outlook = today_sections.guidance_of(release)
        # A headline run into the dateline reads as a sentence about the
        # quarter (AAPL 2026-11-02): an "outlook" the opening already quotes.
        if outlook and outlook.rstrip("…")[:60] not in opening:
            out.append(f'outlook in the release: "{outlook}"')
        if opening:
            out.append(f'release opens: "{opening}"')
        if self.held:
            out.extend(self.rules or ("no exit rule saved for it",))
        return out


_WHEN = {"bmo": "before the open", "amc": "after the close"}


def _money(value: float) -> str:
    for scale, unit in ((1e9, "B"), (1e6, "M")):
        if abs(value) >= scale:
            return f"{value / scale:.2f}{unit}"
    return f"{value:,.0f}"


# What some filers put before the release's own first words.
_EXHIBIT_RE = re.compile(r"^\s*Exhibit\s+\d+(?:\.\d+)?\s*", re.I)


def _body(release: str) -> str:
    """A release's text past the EDGAR wrapper and the exhibit label."""
    from stocks.chat import today_sections

    text = today_sections.EDGAR_HEAD_RE.sub("", " ".join(release.split()))
    return _EXHIBIT_RE.sub("", text).strip()


def _opening(text: str) -> str:
    """The release's first `RELEASE_CHARS` (`_body`), cut at a word; "" without
    one."""
    if len(text) <= RELEASE_CHARS:
        return text
    return text[: RELEASE_CHARS - 1].rsplit(" ", 1)[0].rstrip(",;:-–— ") + "…"


def _rule_lines(entries, ticker: str) -> tuple[str, ...]:
    """The reader's live exit rules for `ticker`, one line each: the rule,
    whether it is met, and a thesis pillar the daily check is watching."""
    from stocks.chat import journal

    out = []
    for e in journal.criteria(entries, ticker):
        snap = e.snapshot
        line = f"exit rule: {journal.criterion_text(e)}"
        if e.state == "hit":
            line += f" — met on {snap.get('hit_day') or e.last}"
            if snap.get("pillar"):
                line += f" ({snap.get('verdict') or 'damaged'}: {snap['pillar']})"
        else:
            pillars = journal.pillars_of(snap.get("pillars"))
            for w in snap.get("watch") or ():
                i, _, on = str(w).partition(":")
                if i.isdigit() and int(i) < len(pillars):
                    line += f"; pillar on watch since {on}: {pillars[int(i)]}"
        out.append(line)
    return tuple(out)


@dataclass(frozen=True)
class Book:
    """The book's own money over each window, beside the S&P 500 bought with
    that same money on the same days (`portfolio.same_money`): rows of
    (days, own %, gain in `currency`, index %), the last from the book's
    first day `since`."""

    currency: str
    rows: tuple[tuple[int, float | None, float | None, float | None], ...]
    since: str = ""  # the book's first day, ISO

    def line(self) -> str:
        def pct(v: float | None) -> str:
            return "not available" if v is None else f"{v * 100:+.2f}%"

        out = []
        for days, own, gain, index in self.rows:
            span = (f"since the book's first day ({self.since})"
                    if self.since and days == self.rows[-1][0]
                    else f"over the last {days} days")
            money = "" if gain is None else f" ({gain:+,.0f} {self.currency})"
            out.append(f"- the book {span}: {pct(own)}{money}; the S&P 500 "
                       f"bought with the same money: {pct(index)}")
        return "\n".join(out)


def _book(db: Path, currency: str, days: int) -> Book | None:
    """The book against the S&P 500 over `days`, a month and from its first
    day (as the Friday email reads it), or None without a history."""
    from stocks import loaders
    from stocks.analysis.portfolio import index_change, money_change
    from stocks.chat import daily_book
    from stocks.chat.today_sections import book_start, reaching
    from stocks.frames import naive_series
    from stocks.views.briefing import closes_since

    hist = loaders.history(str(db), loaders.db_mtime(str(db)), currency)[0]
    start = book_start(hist)
    if start is None:
        return None
    since = int((naive_series(hist["value"]).index[-1] - start).days)
    windows = [d for d in sorted({days, MONTH_DAYS}) if d < since] + [since]
    index = daily_book.index_in_currency(closes_since(start), currency)
    # Read from the book's first day, or its first close a few days after.
    if index is not None and (reached := reaching(index, start)) is not None:
        index = reached
    rows = []
    for d in windows:
        own = money_change(hist, d)
        same = index_change(hist, index, d) if index is not None else None
        rows.append((d, None if own is None else own[1],
                     None if own is None else own[0],
                     None if same is None else same[1]))
    return Book(currency=currency, rows=tuple(rows),
                since=start.date().isoformat())


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
    # Looking back instead: the prints of the last `days` days, newest first.
    back: bool = False
    printed: tuple[Printed, ...] = ()
    book: Book | None = None
    coming: tuple[Due, ...] = ()  # looking back: the next `NEXT_DAYS` days' dates

    def line(self, lang: str = "en") -> str:
        """The prompt's paragraph: every date in the window, quoted."""
        if self.back:
            return self._behind()
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

    def _behind(self) -> str:
        rows = []
        for p in self.printed[:MAX_ROWS]:
            rows.append(
                f"- {p.ticker} ({'held' if p.held else 'followed, not held'}): "
                f"{p.day.isoformat()}, "
                + ("yesterday" if p.days_ago == 1 else f"{p.days_ago} days ago")
                + f"; {p.said()}")
            rows.extend(f"  {line}" for line in p.detail())
        found = "\n".join(rows) if rows else (
            "- none of them reported inside the window")
        tail = ("\n- left out because coins and funds do not report: "
                + ", ".join(self.skipped[:12])) if self.skipped else ""
        book = ("\nThe book over the same days, on the same money as the index "
                "(open the answer with it, both spans):\n"
                + self.book.line()) if self.book else ""
        coming = ""
        if self.coming:
            coming = (f"\nReporting in the next {NEXT_DAYS} days: " + ", ".join(
                f"{d.ticker} {d.day.isoformat()}"
                + ("" if d.held else " (followed)") for d in self.coming[:MAX_ROWS]))
        return (
            "\n\n---\nThe app's earnings calendar for the reader's own names "
            f"(the {self.checked} companies they hold or follow, {self.held} of "
            f"them held), the results they reported in the last {self.days} "
            "days, newest first. Answer from these, held names first, one short "
            "verdict per print — beat or miss, what grew, the outlook, how the "
            "shares took it — then the followed names in one line; do not ask "
            "the reader which tickers they own. Each row is the EPS reported "
            "against the street's consensus for that print, the quarter's "
            "revenue and margin, and the share price from the last close "
            "before it to the first close after; under it, the press release's "
            "own words and the reader's exit rules for the name. Say whether a "
            "print bears on a rule, and name the held names that reported with "
            "no rule saved. Quote only these figures, and where a row has none "
            "say there is none — never fill one in from memory. A name not "
            "listed did not report inside the window:\n" + found + tail
            + book + coming
        )


_consensus_cache: dict[tuple[str, date], tuple[float, Consensus | None]] = {}
_reaction_cache: dict[tuple[str, date], tuple[float, float | None]] = {}


def _looked_up(keys: list[tuple[str, date]], fetch, cache: dict,
               timeout: float = CONSENSUS_TIMEOUT_S) -> dict:
    """`fetch(ticker, day)` for every key, all at once and kept
    `CONSENSUS_TTL_S` in `cache`; a lookup that fails or overruns `timeout`
    is left out."""
    now = time.monotonic()
    fresh = {k: hit[1] for k in keys
             if (hit := cache.get(k)) and now - hit[0] < CONSENSUS_TTL_S}
    missing = [k for k in keys if k not in fresh]
    if missing:
        pool = ThreadPoolExecutor(max_workers=min(CONSENSUS_WORKERS, len(missing)))
        try:
            futures = {pool.submit(fetch, *k): k for k in missing}
            done, _ = wait(list(futures), timeout=timeout)
            for future in done:
                k = futures[future]
                got = future.result() if future.exception() is None else None
                fresh[k] = got
                cache[k] = (now, got)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    return fresh


def _with_consensus(due: list[Due]) -> list[Due]:
    """`due` with each quoted row's consensus; a lookup that fails or
    overruns leaves the row bare."""
    from stocks.data import earnings

    rows = due[:MAX_ROWS]
    fresh = _looked_up([(d.ticker, d.day) for d in rows], earnings.consensus,
                       _consensus_cache)
    looked = [replace(d, consensus=fresh.get((d.ticker, d.day))) for d in rows]
    return looked + due[MAX_ROWS:]


_facts_cache: dict[tuple[str, date], tuple[float, dict | None]] = {}


def _print_facts(ticker: str, day: date) -> dict | None:
    """`views.briefing.print_facts` for one print; the release is read only
    where EDGAR can be asked at all, as the Today page reads it."""
    import os

    from stocks.views import briefing

    return briefing.print_facts({"ticker": ticker, "date": day.isoformat()},
                                release=bool(os.environ.get("EDGAR_USER_AGENT")))


def _with_facts(printed: list[Printed]) -> list[Printed]:
    """`printed` with the held prints' revenue, margin and release; a lookup
    that fails or overruns leaves the row with its EPS alone."""
    keys = [(p.ticker, p.day) for p in printed if p.held][:RELEASE_NAMES]
    fresh = _looked_up(keys, _print_facts, _facts_cache, FACTS_TIMEOUT_S)
    return [replace(p, facts=fresh.get((p.ticker, p.day)) or {}) for p in printed]


def _with_reaction(printed: list[Printed]) -> list[Printed]:
    """`printed` with each quoted row's move across the print, the calendar
    dialog's own (`earnings.price_reaction`)."""
    from stocks.data import earnings

    rows = printed[:MAX_ROWS]
    fresh = _looked_up([(p.ticker, p.day) for p in rows], earnings.price_reaction,
                       _reaction_cache)
    looked = [replace(p, reaction=fresh.get((p.ticker, p.day))) for p in rows]
    return looked + printed[MAX_ROWS:]


def build(watchlist: Path, db: Path, days: int = DEFAULT_DAYS,
          today: date | None = None, back: bool = False,
          journal: Path | None = None, currency: str = "") -> Ahead | None:
    """The calendar over the reader's names, or None when they have none.
    `back` reads the window behind today: the prints already out, with the
    exit rules in `journal` (`chat/journal.py`) and, given the reader's
    `currency`, the book against the index over the same days."""
    from stocks import loaders
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
    events, results = loaders.earnings_calendar(reporting)
    when = {e.ticker: e for e in events}
    today = today or date.today()
    checked, held_n = len(reporting), sum(1 for t in reporting if t in held)
    if back:
        printed, seen = [], set()
        for r in results:  # newest first
            ago = (today - r.date).days
            if r.ticker in seen or not 0 <= ago <= days:
                continue
            seen.add(r.ticker)
            printed.append(Printed(r.ticker, r.date, ago, r.ticker in held,
                                   r.reported_eps, r.eps_estimate, r.surprise_pct))
        printed.sort(key=lambda p: (not p.held, p.days_ago, p.ticker))
        printed = _with_facts(_with_reaction(printed))
        if journal is not None and journal.exists():
            from stocks.chat import journal as decisions

            entries = decisions.load(journal)
            printed = [replace(p, rules=_rule_lines(entries, p.ticker))
                       if p.held else p for p in printed]
        book = None
        if currency and db.exists():
            try:
                book = _book(db, currency, days)
            except Exception as exc:  # noqa: BLE001 — the prints still stand
                obs.warn("chat.reports_book_failed", error_type=type(exc).__name__)
        coming = sorted(
            (Due(e.ticker, e.date, (e.date - today).days, e.ticker in held)
             for e in events
             if e.date is not None and 0 <= (e.date - today).days <= NEXT_DAYS),
            key=lambda d: (d.in_days, not d.held, d.ticker))
        obs.event("chat.reports_behind", days=days, names=checked,
                  printed=len(printed),
                  facts=sum(1 for p in printed if p.facts))
        return Ahead(days=days, due=(), checked=checked, held=held_n,
                     undated=(), skipped=skipped, back=True,
                     printed=tuple(printed), book=book, coming=tuple(coming))
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
    return Ahead(days=days, due=tuple(due), checked=checked, held=held_n,
                 undated=undated, skipped=skipped)
