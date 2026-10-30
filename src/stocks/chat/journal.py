"""The decision journal: what the assistant proposed, and what became of it.

Asking a reader why they bought NVIDIA five years ago gets no answer worth
keeping — they do not remember, or it was a hunch, and either way the question
is a chore that ends the feature. So the journal never asks. It records the
one side of a decision that always has a clear reason: the assistant's. Every
proposal the reader was *shown* — a line on the daily card, a sell or trim on
the Review page, an alert or watchlist change offered in the chat — is kept
with the figures it was made on, and its state follows what happened next:

* ``open`` — still being proposed.
* ``followed`` / ``declined`` — the reader said so (the chat's Approve and
  Cancel; later, a trade in the ledger that matches).
* ``lapsed`` — the assistant stopped proposing it: the Review verdict moved
  on, or a card line has not come back in LAPSE_DAYS. When another proposal
  about the same thing replaced it, the two are linked.

Beside the proposals sit the reader's exit rules — kill criteria — written
with the chat's help and approved like any other chat proposal: "sell NVDA if
it closes under 95", "re-read ASML if it falls 30 % from its high". They are
``criterion`` entries, one per rule, measured every morning against the same
closes and positions the daily card reads (`measured`):

* ``open`` — armed, the condition not met.
* ``hit`` — the condition was met on `snapshot["hit_day"]`; the card says so
  once, and the entry stays hit until the reader retires it or writes a new
  rule in its place.
* ``retired`` — the reader took it down, or a new rule on the same ticker and
  measure replaced it (the two linked).

Criteria never lapse: a rule is the reader's own, and stays until they say.

Only what was on screen is recorded. A signal computed and never shown is not
a decision anybody faced, and a journal of everything the engine considered
is noise the reader would scroll past. The same proposal shown again is the
same entry (`last`, `times`), not a new one — the Review page recomputes on
every visit, and a journal that grew per page view would bury the one change
that matters: the day a "hold" became a "sell".

One JSON file per account beside the chat, synced to the bucket like the
learnings (`accounts.USER_FILES`). Unlike the learnings it is never part of a
prompt: the chat reads it through a tool (`chat/toolbox.py`) when a question
is about it, so it can grow to MAX_ENTRIES without costing a turn anything.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import SupportsFloat

from stocks import atomic, obs, storage

FILE = "decisions.json"

TYPES = ("proposal", "criterion", "event")
SOURCES = ("daily", "review", "chat")
STATES = ("open", "followed", "declined", "lapsed", "hit", "retired")
# The states an entry is still live in, never pruned past MAX_ENTRIES.
LIVE = ("open", "hit")

# What an exit rule can measure. The price rules, each against a figure the
# card already has, every morning:
#   below         — the last close at or under `level`, in the quote currency
#                   (the currency an alert's level is typed in too);
#   drawdown_cost — the position down `level` % or more from its own cost;
#   drawdown_high — the last close `level` % or more under the year's high;
#   weight_above  — the position `level` % or more of the book.
PRICE_RULES = ("below", "drawdown_cost", "drawdown_high", "weight_above")
# The fundamental rules, off the quarterly income statement once a new
# quarter can be out (`fundamental_due`), each met when the last `quarters`
# quarters (1 to MAX_QUARTERS) all read under `level`, a percent that may be
# zero or negative:
#   revenue_growth_below   — revenue growth on the same quarter a year back;
#   gross_margin_below     — gross profit over revenue;
#   operating_margin_below — operating income over revenue.
FUNDAMENTAL_RULES = ("revenue_growth_below", "gross_margin_below",
                     "operating_margin_below")
# The event rules, with no level: met when the company's own filings or the
# news say it happened, as judged by a model asked that one closed question
# about a passage it must quote (`check_slow`):
#   ceo_change   — the chief executive leaves or is replaced;
#   guidance_cut — the company lowers or withdraws its own outlook;
#   dividend_cut — the dividend is cut, suspended or scrapped.
# A thesis or any other news condition ("if they lose the TSMC contract") is
# not a rule the app can check, so it rides along as the rule's `evidence`.
EVENT_RULES = ("ceo_change", "guidance_cut", "dividend_cut")
CRITERION_RULES = PRICE_RULES + FUNDAMENTAL_RULES + EVENT_RULES
# The rules read off a fetch the morning's card does not already make: they
# are checked on the card's background job (`check_slow`) and carried
# between checks on their snapshot.
SLOW_RULES = FUNDAMENTAL_RULES + EVENT_RULES
CRITERION_PERCENT = ("drawdown_cost", "drawdown_high", "weight_above")
MAX_QUARTERS = 4
# A quarter's figures are filed weeks after it ends: one this old has
# probably been followed by a newer one, so the statement is read again
# (daily, until it is).
QUARTER_DUE_DAYS = 80
# What an event rule still remembers having judged, so a headline seen on
# Monday's check is not paid for again on Tuesday's.
MAX_SEEN = 40
# A rule this close to its level (percent of price for `below`, points for the
# rest) is "near": worth a line before it fires.
CRITERION_NEAR = 3.0
# How long after its hit day a criterion is still news for the card.
CRITERION_FRESH_DAYS = 7
MAX_THESIS = 300

# The oldest settled entries go first past this; open ones are never dropped.
MAX_ENTRIES = 2000
# A card line not offered again for this long is no longer being proposed.
# Longer than the card's longest cooldown (signals._COOLDOWN, 14 days), so a
# standing condition that is merely resting between reminders stays open.
LAPSE_DAYS = 30
MAX_LINE = 400
MAX_REASONS = 6
MAX_EVIDENCE = 600

# The daily card's signal kinds that propose doing something. The rest —
# prints, rate decisions, deadlines, the tape — are news: worth a line on the
# card, not a decision anybody makes or declines.
DAILY_ACTIONS = {
    "alert_hit": "alert",
    "harvest": "harvest",
    "drawdown": "review",
    "concentration": "trim",
    "sector_tilt": "rebalance",
    "repurchase_clear": "rebuy",
    "low_52w": "consider",
    "criterion_hit": "exit",
    "filing_flag": "review",
}
# The Today page's insider rows: a cluster of insiders buying is a name worth
# a look — the rest of the page (news, comparisons) is read, not decided.
TODAY_ACTIONS = {"insider_cluster": "consider"}
# Review verdicts that propose a move (held: sell, trim, add; outside: buy).
REVIEW_ACTIONS = ("sell", "trim", "add", "buy")
# A Review plan with no move is advice too: the book stays as it is. It is
# one proposal about the whole book, not about any name.
REVIEW_STAY = "stay"
REVIEW_BOOK = "review:book"
# Chat proposals about what to own or watch. The ledger edits are bookkeeping
# — fixing what a statement said — not investment decisions.
CHAT_ACTIONS = {
    "set_alerts": "alert",
    "add_ticker": "watch",
    "remove_ticker": "unwatch",
}

# One account's file is written from a request and from a card's background
# job at once; every read-modify-write holds this.
_LOCK = threading.RLock()


def path_for(chat: Path) -> Path:
    """The account's journal, beside its chat history."""
    return chat.with_name(FILE)


@dataclass(frozen=True)
class Entry:
    """One proposal (later: a kill criterion, or an event that tested one).

    `subject` is what makes two showings the same proposal: the card's
    trigger key, "review:<ticker>", or the chat proposal's id. `snapshot` is
    the figures it was first made on and is never updated — it is what the
    proposal is judged against later. `day`/`last` are the first and the
    latest day it was on screen; `times` how many distinct days."""

    id: str
    type: str
    source: str
    action: str
    subject: str
    ticker: str = ""
    line: str = ""
    reasons: tuple[str, ...] = ()
    snapshot: dict = field(default_factory=dict)
    evidence: str = ""
    state: str = "open"
    day: str = ""
    last: str = ""
    times: int = 1
    links: tuple[str, ...] = ()
    updated: str = ""
    # How a followed or declined entry got there: "chat" for a button the
    # reader pressed, "ledger:<date>" for a trade found in the book. "" for
    # the states the app sets on its own (open, lapsed).
    settled: str = ""
    # The price read back after the fact (`mark_outcomes`): "then", the
    # close on the first day shown, and "d30"/"d90", the % move from it a
    # month and a quarter on. Empty until a mark is due.
    outcome: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = asdict(self)
        out["reasons"] = list(self.reasons)
        out["links"] = list(self.links)
        return out


@dataclass(frozen=True)
class Shown:
    """A proposal as one surface put it on screen, before it is matched."""

    source: str
    subject: str
    action: str
    ticker: str = ""
    line: str = ""
    reasons: tuple[str, ...] = ()
    snapshot: dict = field(default_factory=dict)
    links: tuple[str, ...] = ()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _new_id() -> str:
    return "d_" + secrets.token_hex(5)


def _text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _scalars(data: dict) -> dict:
    """The snapshot kept: numbers, short strings and flags, nothing nested —
    what a line was made on, not a copy of the facts it was made from."""
    out = {}
    for key, value in (data or {}).items():
        if isinstance(value, bool) or value is None:
            out[key] = value
        elif isinstance(value, int | float):
            out[key] = round(value, 4) if isinstance(value, float) else value
        elif isinstance(value, str) and len(value) <= 80:
            out[key] = value
    return out


# -------------------------------------------------------------------- store


def load(path: Path) -> list[Entry]:
    """Every entry, oldest first. Missing or unreadable reads as empty."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception as exc:  # noqa: BLE001 — a corrupt file is an empty journal
        obs.warn("journal.read_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        return []
    out = []
    for item in (raw.get("entries") if isinstance(raw, dict) else None) or []:
        if not isinstance(item, dict) or not item.get("id") or not item.get("subject"):
            continue
        out.append(Entry(
            id=str(item["id"]),
            type=item.get("type") if item.get("type") in TYPES else "proposal",
            source=str(item.get("source") or ""),
            action=str(item.get("action") or ""),
            subject=str(item["subject"]),
            ticker=str(item.get("ticker") or ""),
            line=str(item.get("line") or ""),
            reasons=tuple(str(r) for r in item.get("reasons") or ()),
            snapshot=item["snapshot"] if isinstance(item.get("snapshot"), dict) else {},
            evidence=str(item.get("evidence") or ""),
            state=item.get("state") if item.get("state") in STATES else "open",
            day=str(item.get("day") or ""),
            last=str(item.get("last") or item.get("day") or ""),
            times=int(item.get("times") or 1),
            links=tuple(str(x) for x in item.get("links") or ()),
            updated=str(item.get("updated") or ""),
            settled=str(item.get("settled") or ""),
            outcome=_outcome(item.get("outcome")),
        ))
    return out


def _outcome(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {k: float(v) for k, v in raw.items()
            if k in OUTCOME_KEYS and isinstance(v, int | float)
            and not isinstance(v, bool)}


def writable(path: Path) -> bool:
    """False for the shared guest directory, where nothing is kept."""
    from stocks import accounts

    try:
        accounts.writable(path)
    except accounts.GuestIsReadOnly:
        return False
    return True


def _save(path: Path, entries: list[Entry]) -> None:
    from stocks import accounts

    accounts.writable(path)
    if len(entries) > MAX_ENTRIES:
        settled = [e for e in entries if e.state not in LIVE]
        drop = {e.id for e in settled[: len(entries) - MAX_ENTRIES]}
        entries = [e for e in entries if e.id not in drop]
    atomic.write_json(path, {"version": 1, "entries": [e.as_dict() for e in entries]},
                      indent=1, ensure_ascii=False)
    try:
        storage.persist(path)
    except Exception as exc:  # noqa: BLE001 — the local copy is good
        obs.warn("journal.persist_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])


def _lapse(entry: Entry, now: str, link: str = "") -> Entry:
    links = entry.links + ((link,) if link and link not in entry.links else ())
    return replace(entry, state="lapsed", links=links, updated=now)


def record(path: Path, shown: Iterable[Shown], day: date, *,
           judged: Iterable[str] = ()) -> int:
    """Put what a surface just showed into the journal; return how many
    entries changed.

    A proposal already open under the same source and subject is the same
    entry: its `last` and `times` move on (once a day) and nothing else does.
    One about the same subject with a different action replaces it — the old
    one lapses, and the two are linked both ways.

    `judged` are the subjects the surface weighed this time and found nothing
    to propose about — the Review page's names with a hold, watch or pass
    verdict — so an open proposal among them lapses: the verdict moved on. A
    name it could not rate is not in it; a flaky fundamentals pull must not
    close a sell the data still supports. Anything else open lapses once it
    has not been shown for LAPSE_DAYS: the card shows a few lines a day, and
    a name sold or dropped from the watchlist is simply never judged again.

    Writes only when something changed: a page reloaded twice in a day costs
    one read.
    """
    shown = [s for s in shown if s.source in SOURCES and s.subject and s.action]
    iso, now = day.isoformat(), _now()
    with _LOCK:
        entries = load(path)
        index = {(e.source, e.subject): i for i, e in enumerate(entries)
                 if e.state == "open" and e.type == "proposal"}
        changed = 0
        seen: set[tuple[str, str]] = set()
        for s in shown:
            key = (s.source, s.subject)
            if key in seen:
                continue
            seen.add(key)
            at = index.get(key)
            if at is not None and entries[at].action == s.action:
                old = entries[at]
                if old.last != iso:
                    entries[at] = replace(old, last=iso, times=old.times + 1,
                                          line=_text(s.line, MAX_LINE) or old.line,
                                          updated=now)
                    changed += 1
                continue
            entry = Entry(
                id=_new_id(), type="proposal", source=s.source, action=s.action,
                subject=s.subject, ticker=s.ticker, line=_text(s.line, MAX_LINE),
                reasons=tuple(_text(r, 80) for r in s.reasons[:MAX_REASONS]),
                snapshot=_scalars(s.snapshot), day=iso, last=iso, updated=now,
                links=tuple(x for x in s.links if x),
            )
            if at is not None:
                entries[at] = _lapse(entries[at], now, entry.id)
                entry = replace(entry, links=(*entry.links, entries[at].id))
            entries.append(entry)
            index[key] = len(entries) - 1
            changed += 1
        judged = set(judged)
        cutoff = (day - timedelta(days=LAPSE_DAYS)).isoformat()
        for i, e in enumerate(entries):
            # A criterion is the reader's own rule: it never lapses.
            if (e.state != "open" or e.type != "proposal"
                    or (e.source, e.subject) in seen):
                continue
            if e.subject in judged or e.last < cutoff:
                entries[i] = _lapse(e, now)
                changed += 1
        if changed:
            _save(path, entries)
        return changed


def settle(path: Path, shown: Shown, state: str, day: date) -> Entry | None:
    """A proposal the reader answered on the spot — the chat's Approve or
    Cancel. Recorded already settled: it was shown and decided in one go."""
    if state not in ("followed", "declined") or not shown.subject:
        return None
    now = _now()
    with _LOCK:
        entries = load(path)
        for i, e in enumerate(entries):
            if (e.type == "proposal" and e.source == shown.source
                    and e.subject == shown.subject):
                entries[i] = replace(e, state=state, settled="chat", updated=now)
                _save(path, entries)
                return entries[i]
        entry = Entry(
            id=_new_id(), type="proposal", source=shown.source,
            action=shown.action, subject=shown.subject, ticker=shown.ticker,
            line=_text(shown.line, MAX_LINE),
            reasons=tuple(_text(r, 80) for r in shown.reasons[:MAX_REASONS]),
            snapshot=_scalars(shown.snapshot), state=state, settled="chat",
            day=day.isoformat(), last=day.isoformat(), updated=now,
        )
        entries.append(entry)
        _save(path, entries)
        return entry


def attach(path: Path, source: str, subject: str, evidence: str) -> bool:
    """Keep the analysis the reader opened behind a proposal (the card's
    "Ver análisis") on its open entry. False when there is none to attach to."""
    evidence = _text(evidence, MAX_EVIDENCE)
    if not evidence:
        return False
    with _LOCK:
        entries = load(path)
        for i in range(len(entries) - 1, -1, -1):
            e = entries[i]
            if e.source == source and e.subject == subject and e.state == "open":
                if e.evidence == evidence:
                    return False
                entries[i] = replace(e, evidence=evidence, updated=_now())
                _save(path, entries)
                return True
    return False


def safely(fn, *args, **kwargs):
    """Run a journal write from a surface whose own job comes first: a card,
    a page, a chat answer must never fail because the journal could not be
    written. The guest directory is skipped without a word."""
    try:
        target = args[0] if args else kwargs.get("path")
        if isinstance(target, Path) and not writable(target):
            return None
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — the journal is a side record
        obs.warn("journal.write_failed", op=getattr(fn, "__name__", "?"),
                 error_type=type(exc).__name__, error=str(exc)[:200])
        return None


# -------------------------------------------------------------- the ledger

# What a recorded trade settles. A proposal to let go of a name is answered
# by a sale of it; one to take more, by a buy. The rest — an alert, a look,
# a stay — has no trade that would mean "done".
SELL_SIDE = frozenset({"sell", "trim", "harvest"})
BUY_SIDE = frozenset({"add", "buy", "rebuy"})
# A trade this long after the proposal was last on screen still counts as
# taking it: the same window after which an unshown proposal lapses.
SETTLE_DAYS = LAPSE_DAYS


def side_of(action: str) -> str:
    """The ledger action that would mean `action` was taken, or ""."""
    if action in SELL_SIDE:
        return "sell"
    return "buy" if action in BUY_SIDE else ""


def same_name(a: str, b: str) -> bool:
    """ASML and ASML.AS are one company; the journal writes what the surface
    showed, the ledger what the statement said."""
    a, b = a.strip().upper(), b.strip().upper()
    return bool(a) and bool(b) and (a == b or a.split(".")[0] == b.split(".")[0])


def settle_from_ledger(path: Path, trades: Iterable, day: date) -> int:
    """Mark followed the proposals the reader acted on, read off the ledger.

    The reader is never asked whether they took a proposal: a sale of a name
    the app said to sell, trim or harvest — a buy of one it said to add or
    buy back — dated from the proposal's first day to SETTLE_DAYS after its
    last showing, is the answer. Open and lapsed entries settle this way (a
    name sold is never judged again, so its sell proposal lapses before
    anyone looks); followed and declined ones stand. `trades` are ledger
    rows (`date`, `ticker`, `action`, `quantity`, `price`), as
    `transfers.normalize` leaves them. Returns how many entries changed.
    """
    rows = [(str(t.date)[:10], str(t.ticker), str(t.action).lower(), t)
            for t in trades if str(t.action).lower() in ("buy", "sell")]
    if not rows:
        return 0
    now = _now()
    with _LOCK:
        entries = load(path)
        changed = 0
        for i, e in enumerate(entries):
            side = side_of(e.action)
            if not side or not e.ticker or e.state not in ("open", "lapsed"):
                continue
            until = (date.fromisoformat(e.last) + timedelta(days=SETTLE_DAYS)
                     ).isoformat() if e.last else ""
            hit = next((t for when, ticker, action, t in rows
                        if action == side and same_name(ticker, e.ticker)
                        and e.day <= when <= until), None)
            if hit is None:
                continue
            entries[i] = replace(e, state="followed", updated=now,
                                 settled=f"ledger:{str(hit.date)[:10]}")
            changed += 1
        if changed:
            _save(path, entries)
            obs.event("journal.settled_from_ledger", n=changed)
        return changed


def settle_from_db(path: Path, db: Path | None, day: date) -> int:
    """`settle_from_ledger` over the account's book. Nothing is read from the
    book when no entry could settle, which is most accounts most days."""
    if db is None or not Path(db).exists():
        return 0
    if not any(side_of(e.action) and e.state in ("open", "lapsed")
               for e in load(path)):
        return 0
    from stocks.portfolio import transfers
    from stocks.portfolio.ledger import all_transactions

    return settle_from_ledger(path, transfers.normalize(all_transactions(Path(db))),
                              day)


# ------------------------------------------------------------- the outcome
# A month and a quarter after a move was first shown, its price is read back:
# did the name go the way the move bet on? A sell, trim or harvest bets on
# it falling (or at least not rising), an add, buy or rebuy on it rising.
# Read for every sided proposal whatever the reader did with it — a declined
# sale that then fell 20 % is the record too.

MARKS = (30, 90)
OUTCOME_KEYS = ("then", *(f"d{m}" for m in MARKS))
# Names priced per pass: each is one cached download, and the card job that
# runs this should never wait on dozens of them. The rest are due next pass.
MAX_MARKED = 12

# (ticker, [day, ...]) -> the close on or before each day, None where the
# listing had no price yet — `api.briefing._closes_on`, off `window_closes`.
ClosesOn = Callable[[str, list[date]], list[float | None]]


def _due(e: Entry, day: date) -> list[int]:
    """The marks `e` has reached on `day` and not yet been read at."""
    if (e.type != "proposal" or not e.ticker or not side_of(e.action)
            or not e.day):
        return []
    try:
        first = date.fromisoformat(e.day)
    except ValueError:
        return []
    return [m for m in MARKS
            if f"d{m}" not in e.outcome and first + timedelta(days=m) <= day]


def mark_outcomes(path: Path, closes: ClosesOn, day: date) -> int:
    """Read the price back for every sided proposal a mark has come due on.

    Prices are fetched outside the lock — a download can take seconds — and
    written back under it onto the entries as they are then. A name whose
    price cannot be read keeps its mark due for the next pass. Returns how
    many entries gained a mark."""
    due = {e.id: (e, marks) for e in load(path) if (marks := _due(e, day))}
    if not due:
        return 0
    names = list(dict.fromkeys(e.ticker for e, _ in due.values()))[:MAX_MARKED]
    found: dict[str, dict] = {}
    for entry_id, (e, marks) in due.items():
        if e.ticker not in names:
            continue
        first = date.fromisoformat(e.day)
        try:
            got = closes(e.ticker, [first, *(first + timedelta(days=m) for m in marks)])
        except Exception as exc:  # noqa: BLE001 — due again next pass
            obs.warn("journal.outcome_failed", ticker=e.ticker,
                     error_type=type(exc).__name__)
            continue
        then = e.outcome.get("then") or (got[0] if got else None)
        if not then or then <= 0:
            continue
        marked = {f"d{m}": round((px / then - 1) * 100, 1)
                  for m, px in zip(marks, got[1:], strict=False) if px and px > 0}
        if marked:
            found[entry_id] = {"then": round(then, 4), **marked}
    if not found:
        return 0
    with _LOCK:
        entries = load(path)
        for i, e in enumerate(entries):
            if e.id in found:
                entries[i] = replace(e, outcome={**e.outcome, **found[e.id]})
        _save(path, entries)
    obs.event("journal.outcomes_marked", n=len(found))
    return len(found)


def latest_mark(entry: Entry) -> tuple[int, float] | None:
    """(days, % move) at the furthest mark read, or None before the first."""
    for m in reversed(MARKS):
        if (pct := entry.outcome.get(f"d{m}")) is not None:
            return m, pct
    return None


def went_its_way(entry: Entry) -> bool | None:
    """Whether the name moved the way the move bet on, at its latest mark:
    down after a sell-side move, up after a buy-side one. None unmarked."""
    mark = latest_mark(entry)
    side = side_of(entry.action)
    if mark is None or not side:
        return None
    return mark[1] < 0 if side == "sell" else mark[1] > 0


def since_line(entry: Entry) -> str:
    """"−12.0 % 30 days on, +3.1 % 90 days on", or "" before the first mark."""
    parts = [f"{entry.outcome[f'd{m}']:+.1f} % {m} days on"
             for m in MARKS if f"d{m}" in entry.outcome]
    return ", ".join(parts).replace("-", "−")


# -------------------------------------------------------------- the record


def track_record(entries: Iterable[Entry]) -> dict:
    """What became of the proposals, counted: made, followed, declined,
    lapsed, still open — over the journal and per source. A stay is advice
    to do nothing and is left out of "made". `marked` counts the moves whose
    price has been read back (`mark_outcomes`) and `its_way` those that went
    the way the move bet on, at their latest mark."""
    rows = [e for e in entries if e.type == "proposal" and e.action != REVIEW_STAY]

    def count(scope: list[Entry]) -> dict:
        out = {"proposed": len(scope), **{s: 0 for s in STATES},
               "marked": 0, "its_way": 0}
        for e in scope:
            out[e.state] = out.get(e.state, 0) + 1
            if (way := went_its_way(e)) is not None:
                out["marked"] += 1
                out["its_way"] += int(way)
        return out

    return {**count(rows),
            "by_source": {s: count([e for e in rows if e.source == s])
                          for s in SOURCES}}


HISTORY_DAYS = 90  # how far back a surface looks before proposing again
HISTORY_LINES = 8


def history_for(path: Path, tickers: Iterable[str], day: date, *,
                limit: int = HISTORY_LINES) -> list[str]:
    """What was proposed about `tickers` lately and what came of it, one
    plain line each, newest first — for a surface to read before it
    proposes again. A move the reader declined or let lapse is not worth
    the same words twice; one they followed is done."""
    want = [t for t in dict.fromkeys(str(t).strip().upper() for t in tickers) if t]
    if not want:
        return []
    since = (day - timedelta(days=HISTORY_DAYS)).isoformat()
    hits = [e for e in load(path)
            if e.type == "proposal" and e.ticker and e.last >= since
            and e.day < day.isoformat()
            and any(same_name(e.ticker, t) for t in want)]
    hits.sort(key=lambda e: (e.last, e.updated), reverse=True)
    return [history_line(e) for e in hits[:limit]]


def history_line(entry: Entry) -> str:
    """`history_for`'s line: name, move, where and when, and the outcome."""
    when = entry.day if entry.last == entry.day else f"{entry.day} to {entry.last}"
    shown = f", shown {entry.times} days" if entry.times > 1 else ""
    fate = {
        "followed": "the user did it",
        "declined": "the user declined",
        "lapsed": "it lapsed",
        "open": "still open",
    }.get(entry.state, entry.state)
    if entry.settled.startswith("ledger:"):
        fate += f" (trade on {entry.settled[7:]})"
    if since := since_line(entry):
        fate += f" · price {since}"
    return f"{entry.ticker}: {entry.action} ({entry.source}, {when}{shown}) · {fate}"


# -------------------------------------------------------------- the export


def to_markdown(entries: Iterable[Entry], day: date, *, name: str = "decisions") -> str:
    """The journal as one Markdown file a notes app reads whole: frontmatter,
    the record, then an entry per section with Obsidian's block id (`^id`)
    so the links between entries resolve (`[[name#^id]]`), and tags for its
    ticker, state and source so a notes app's search filters it the way
    the Diario tab does."""
    rows = sorted(entries, key=lambda e: (e.last, e.updated), reverse=True)
    record = track_record(rows)
    out = [
        "---",
        "title: Decision journal",
        f"exported: {day.isoformat()}",
        f"entries: {len(rows)}",
        "---",
        "",
        "# Decision journal",
        "",
        "What the app proposed and showed, with the figures each was made on "
        "and what became of it. Written by the app, never by hand.",
        "",
        f"Proposed {record['proposed']} · followed {record['followed']} · "
        f"declined {record['declined']} · lapsed {record['lapsed']} · "
        f"open {record['open']}"
        + (f" · went its way {record['its_way']} of {record['marked']} priced"
           if record["marked"] else ""),
        "",
    ]
    for e in rows:
        head = f"## {e.day} · {e.source} · {e.action}"
        if e.ticker:
            head += f" {e.ticker}"
        out.append(f"{head} · {e.state}")
        out.append("")
        tags = [f"#state/{e.state}", f"#source/{e.source}", f"#move/{e.action}"]
        if e.ticker:
            tags.insert(0, f"#ticker/{e.ticker.replace('.', '-')}")
        out.append(" ".join(tags) + f" ^{e.id}")
        out.append("")
        if e.line:
            out.append(f"> {e.line}")
            out.append("")
        when = e.day if e.last == e.day else f"{e.day} → {e.last}"
        out.append(f"- **Shown:** {when}" + (f", {e.times} days" if e.times > 1 else ""))
        fate = e.state
        if e.settled == "chat":
            fate += " (answered in the chat)"
        elif e.settled.startswith("ledger:"):
            fate += f" (trade on {e.settled[7:]})"
        out.append(f"- **State:** {fate}")
        if e.reasons:
            out.append("- **Why:** " + ", ".join(e.reasons))
        figures = ", ".join(f"{k} {v}" for k, v in e.snapshot.items() if v is not None)
        if figures:
            out.append(f"- **Figures then:** {figures}")
        if since := since_line(e):
            out.append(f"- **Price since:** {since} (close {e.outcome['then']:g} "
                       f"on {e.day})")
        if e.evidence:
            out.append(f"- **Analysis:** {e.evidence}")
        if e.links:
            out.append("- **Linked:** " + ", ".join(f"[[{name}#^{x}]]" for x in e.links))
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------ the surfaces


def from_card(items: Iterable[dict], facts: dict) -> list[Shown]:
    """The card lines that propose something, with the trigger behind each.

    `items` are the lines as shown (`DailyAction.entries`); `facts["actions"]`
    the signals they were written from, keyed the same way — which is where
    the figures come from, since a line is prose."""
    by_key = {a.get("key"): a for a in (facts or {}).get("actions") or []
              if isinstance(a, dict)}
    out = []
    for item in items:
        key = str(item.get("key") or "")
        kind = str(item.get("kind") or key.split(":", 1)[0])
        action = DAILY_ACTIONS.get(kind)
        if not key or action is None:
            continue
        data = dict(by_key.get(key) or {})
        tickers = item.get("tickers") or []
        ticker = str(data.get("ticker") or (tickers[0] if tickers else ""))
        snapshot = {k: v for k, v in data.items() if k not in ("key", "ticker", "id")}
        # A fired exit rule links to the rule itself, so the journal shows
        # which of the reader's criteria the card was answering.
        links = (str(data["id"]),) if kind == "criterion_hit" and data.get("id") else ()
        out.append(Shown(source="daily", subject=key, action=action,
                         ticker=ticker, line=str(item.get("line") or ""),
                         reasons=(kind,), snapshot=snapshot, links=links))
    return out


def from_today(sections: Iterable[dict]) -> list[Shown]:
    """The Today rows that propose something: an insider cluster buy. The
    comparisons' verdicts are the Review page's (`from_review`), and a
    headline proposes nothing."""
    out = []
    for sec in sections or []:
        for row in sec.get("rows") or []:
            data = row.get("data") or {}
            if row.get("kind") != "insider" or not data.get("cluster_buy"):
                continue
            tickers = row.get("tickers") or []
            out.append(Shown(
                source="daily", subject=str(row.get("key") or ""),
                action=TODAY_ACTIONS["insider_cluster"],
                ticker=str(tickers[0]) if tickers else "",
                line=str(row.get("line") or ""), reasons=("insider_cluster",),
                snapshot={k: v for k, v in data.items()
                          if k in ("buyers", "buy_value", "net_value", "currency",
                                   "latest")}))
    return [s for s in out if s.subject]


def from_review(rows: Iterable) -> list[Shown]:
    """The Review rows that propose a move: a held name's sell, trim or add,
    an outside name's buy."""
    out = []
    for r in rows:
        if r.verdict not in REVIEW_ACTIONS:
            continue
        snapshot = {
            "verdict": r.verdict, "quality": r.quality, "cheapness": r.cheapness,
            "weight": r.weight, "target_weight": r.target_weight,
            "pnl_pct": r.pnl_pct, "value": r.value, "held": r.held,
        }
        out.append(Shown(source="review", subject=f"review:{r.ticker}",
                         action=r.verdict, ticker=r.ticker,
                         reasons=tuple(r.reasons), snapshot=snapshot))
    return out


def stay_in_review(total: float | None, currency: str) -> Shown:
    """The Review plan that moves nothing, as one proposal on the book."""
    return Shown(source="review", subject=REVIEW_BOOK, action=REVIEW_STAY,
                 snapshot={"value": total, "currency": currency})


def judged_in_review(rows: Iterable) -> list[str]:
    """The Review rows rated and found nothing to do about (`record`'s
    `judged`): a proposal open on one of them has been withdrawn. A plan
    that moves something withdraws an open stay."""
    rows = list(rows)
    judged = [f"review:{r.ticker}" for r in rows
              if r.verdict not in REVIEW_ACTIONS and r.verdict != "unrated"]
    if any(r.verdict in REVIEW_ACTIONS for r in rows):
        judged.append(REVIEW_BOOK)
    return judged


def open_in_review(path: Path) -> dict[str, str]:
    """The moves the Review page proposed and still stand, by ticker: the
    engine holds them to the plain line rather than the one a new proposal
    has to clear, so a name a point either side does not flip daily."""
    return {e.ticker.upper(): e.action for e in load(path)
            if e.source == "review" and e.state == "open"
            and e.ticker and e.action in REVIEW_ACTIONS}


def from_chat(offer: dict, line: str) -> Shown | None:
    """A chat proposal the reader answered, when it is about what to own or
    watch (`CHAT_ACTIONS`)."""
    action = CHAT_ACTIONS.get(str(offer.get("kind") or ""))
    if action is None or not offer.get("id"):
        return None
    raw = offer.get("args")
    args = raw if isinstance(raw, dict) else {}
    return Shown(source="chat", subject=str(offer["id"]), action=action,
                 ticker=str(offer.get("ticker") or ""), line=line,
                 snapshot=_scalars({k: v for k, v in args.items()
                                    if not isinstance(v, list | dict)}))


# ---------------------------------------------------------------- criteria


def criterion_subject(ticker: str, rule: str) -> str:
    """One live rule per ticker and measure: a new one replaces it."""
    return f"criterion:{ticker.strip().upper()}:{rule}"


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (SupportsFloat, str)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _signed(value: object) -> float | None:
    if isinstance(value, str):
        value = value.replace(",", ".").strip().rstrip("%").strip()
    return _finite(value)


def _level(value: object) -> float | None:
    out = _signed(value)
    return out if out is not None and out > 0 else None


def _quarters(value: object) -> int:
    n = _finite(value)
    return min(max(int(n), 1), MAX_QUARTERS) if n is not None else 1


def clean_rules(rules: Iterable[dict]) -> list[dict]:
    """The rules worth keeping, the last one per measure winning: a price
    rule with a level above zero (a percent one under 100), a fundamental
    rule with a percent level in range and its `quarters`, an event rule
    alone."""
    out: dict[str, dict] = {}
    for item in rules or ():
        if not isinstance(item, dict):
            continue
        rule = str(item.get("rule") or "").strip().lower()
        if rule in EVENT_RULES:
            out[rule] = {"rule": rule}
            continue
        if rule in FUNDAMENTAL_RULES:
            level = _signed(item.get("level"))
            top = 1000 if rule == "revenue_growth_below" else 100
            if level is None or not -100 < level < top:
                continue
            out[rule] = {"rule": rule, "level": round(level, 4),
                         "quarters": _quarters(item.get("quarters"))}
            continue
        level = _level(item.get("level"))
        if rule not in PRICE_RULES or level is None:
            continue
        if rule in CRITERION_PERCENT and level >= 100:
            continue
        out[rule] = {"rule": rule, "level": round(level, 4)}
    return list(out.values())


def add_criteria(path: Path, ticker: str, rules: Iterable[dict], day: date,
                 thesis: str = "") -> list[Entry]:
    """Write the reader's exit rules for `ticker`; return the entries written.

    A live rule on the same ticker and measure is retired and linked to the
    one that replaces it: the reader moved their line, and the journal keeps
    where it was. `thesis` is the why in the reader's words (or the chat's
    draft they approved), kept on every rule written with it."""
    ticker = ticker.strip().upper()
    rules = clean_rules(rules)
    if not ticker or not rules:
        return []
    iso, now = day.isoformat(), _now()
    thesis = _text(thesis, MAX_THESIS)
    written: list[Entry] = []
    with _LOCK:
        entries = load(path)
        for item in rules:
            subject = criterion_subject(ticker, item["rule"])
            entry = Entry(
                id=_new_id(), type="criterion", source="chat", action=item["rule"],
                subject=subject, ticker=ticker,
                snapshot=dict(item),
                evidence=thesis, day=iso, last=iso, updated=now,
            )
            for i, e in enumerate(entries):
                if e.type == "criterion" and e.subject == subject and e.state in LIVE:
                    entries[i] = replace(e, state="retired", links=(*e.links, entry.id),
                                         updated=now)
                    entry = replace(entry, links=(*entry.links, e.id))
            entries.append(entry)
            written.append(entry)
        _save(path, entries)
    return written


def retire(path: Path, entry_id: str) -> Entry | None:
    """Take one of the reader's rules down. None when there is no live
    criterion with that id."""
    with _LOCK:
        entries = load(path)
        for i, e in enumerate(entries):
            if e.id == entry_id and e.type == "criterion" and e.state in LIVE:
                entries[i] = replace(e, state="retired", updated=_now())
                _save(path, entries)
                return entries[i]
    return None


def criteria(entries: Iterable[Entry], ticker: str = "") -> list[Entry]:
    """The live exit rules (armed or hit), oldest first; one ticker's alone
    when `ticker` is given."""
    want = ticker.strip().upper()
    return [e for e in entries
            if e.type == "criterion" and e.state in LIVE
            and (not want or e.ticker.upper() == want)]


def _row(tbl, ticker: str):
    if tbl is None or getattr(tbl, "empty", True):
        return None
    try:
        return tbl.loc[ticker] if ticker in tbl.index else None
    except Exception:  # noqa: BLE001 — a duplicated index is no row
        return None


def measure_rule(rule: str, level: float, prices: list,
                 row) -> tuple[float, float, bool] | None:
    """(value, gap, met) for one rule, or None when its figure is missing.

    `value` is what the rule reads: a price for `below`, a signed percent for
    the rest (a drawdown is negative). `gap` is how far it still is from the
    level, in percent of price for `below` and in points for the rest, and
    negative once past it."""
    last = _finite(prices[-1]) if prices else None
    if rule == "below":
        if last is None or not level:
            return None
        return round(last, 4), round((last / level - 1) * 100, 2), last <= level
    if rule == "drawdown_high":
        seen = [v for v in (_finite(p) for p in prices) if v is not None]
        high = max(seen) if seen else None
        if last is None or not high:
            return None
        value = (last / high - 1) * 100
        return round(value, 2), round(value + level, 2), value <= -level
    if row is None:
        return None
    if rule == "drawdown_cost":
        pnl = _finite(row.get("pnl_pct"))
        if pnl is None:
            return None
        value = pnl * 100
        return round(value, 2), round(value + level, 2), value <= -level
    if rule == "weight_above":
        weight = _finite(row.get("weight"))
        if weight is None:
            return None
        value = weight * 100
        return round(value, 2), round(level - value, 2), value >= level
    return None


def quarter_figure(rule: str, quarters: list, q) -> float | None:
    """What a fundamental rule reads on one quarter, in percent: revenue
    growth on the same quarter a year back, or a margin. None when the
    statement does not carry it."""
    from stocks.data.earnings import pct_change, year_ago

    if rule == "revenue_growth_below":
        back = year_ago(quarters, q)
        growth = pct_change(q.revenue, back.revenue if back else None)
        return None if growth is None else growth * 100
    margin = q.gross_margin if rule == "gross_margin_below" else q.operating_margin
    return None if margin is None else margin * 100


def measure_fundamental(rule: str, level: float, n: int,
                        quarters: list) -> dict | None:
    """One fundamental rule on a quarterly statement (`earnings.Quarter`s,
    any order): {value, gap, met, quarter_end}, or None when the last `n`
    quarters do not all carry the figure.

    `value` is the latest quarter's, `gap` how far it still is above the
    level in points (negative once under it), and `met` whether each of the
    last `n` quarters read under the level — one bad quarter is noise the
    reader can ask for by writing 1."""
    ordered = sorted(quarters or (), key=lambda q: q.end, reverse=True)
    if len(ordered) < n:
        return None
    figures = [f for q in ordered[:n]
               if (f := quarter_figure(rule, ordered, q)) is not None]
    if len(figures) < n:
        return None
    value = round(figures[0], 2)
    return {"value": value, "gap": round(value - level, 2),
            "met": all(f < level for f in figures),
            "quarter_end": ordered[0].end.isoformat()}


def _stored_row(e: Entry, rule: str) -> dict | None:
    """A slow rule as its last check left it (`check_slow`); None before its
    first one, unless it has already been hit."""
    snap = e.snapshot
    if "checked" not in snap and e.state != "hit":
        return None
    level = _finite(snap.get("level"))
    return {
        "id": e.id, "ticker": e.ticker, "rule": rule, "level": level,
        "value": _finite(snap.get("value")), "gap_pct": _finite(snap.get("gap")),
        "state": e.state, "met": e.state == "hit",
        "hit_day": str(snap.get("hit_day") or ""),
        **({"quarters": int(snap.get("quarters") or 1)}
           if rule in FUNDAMENTAL_RULES else {}),
        **{k: str(snap[k]) for k in ("quote", "source", "source_day")
           if snap.get(k)},
    }


def measured(entries: Iterable[Entry], closes: dict | None, tbl) -> list[dict]:
    """Every live rule against today's figures: `closes` a year of closes per
    ticker, oldest first (the card's own), `tbl` the positions frame
    (`pnl_pct` and `weight` as fractions). A rule whose figure is missing
    today (a throttled download, a name sold) is left out, not judged. A
    slow rule reads as its last check left it (`check_slow` measures it)."""
    out = []
    for e in criteria(entries):
        rule = str(e.snapshot.get("rule") or e.action)
        if rule in SLOW_RULES:
            row = _stored_row(e, rule)
            if row is not None:
                out.append(row)
            continue
        level = _finite(e.snapshot.get("level"))
        if rule not in PRICE_RULES or not level:
            continue
        got = measure_rule(rule, level, list((closes or {}).get(e.ticker) or []),
                           _row(tbl, e.ticker))
        if got is None:
            continue
        value, gap, met = got
        out.append({
            "id": e.id, "ticker": e.ticker, "rule": rule, "level": level,
            "value": value, "gap_pct": gap, "state": e.state, "met": met,
            "hit_day": str(e.snapshot.get("hit_day") or ""),
        })
    return out


# ------------------------------------------------------------- slow rules
# Fundamental and event rules need a fetch the morning card does not make (a
# quarterly statement, a month of 8-Ks and the news), and an event rule a
# model's reading. So they are checked on the card's background job, once a
# day at most, and what each check found is kept on the rule's snapshot:
# `checked` the day, `value`/`gap`/`quarter_end` a statement's reading,
# `seen` the passages an event rule has judged, `quote`/`source` the one it
# was met on. `measured` reads them back between checks.

# A passage has to say this much before a model is asked about it: a
# keyword sieve, so a quiet morning costs no call at all.
EVENT_WORDS = {
    "ceo_change": (r"\b(ceo|chief executive|consejer[oa] delegad[oa])\b",
                   r"(step(s|ped)? down|resign|depart|leav|exit|replac|succeed|successor|"
                   r"appoint|nam(es|ed)|ousted|fired|retir|interim|dimit|sustitu|"
                   r"nombra|relev|abandon|sale\b|cese)"),
    "guidance_cut": (r"(guidance|outlook|forecast|previsi|perspectiv|objetivo)",
                     r"(cut|lower|reduc|slash|withdr|suspend|trim|below|miss|"
                     r"rebaj|recort|baj|retir)"),
    "dividend_cut": (r"(dividend|dividendo|payout)",
                     r"(cut|lower|reduc|slash|suspend|halt|eliminat|scrap|omit|"
                     r"recort|rebaj|suprim|cancel)"),
}


# The two words have to sit this close: an earnings release says "guidance"
# and "lower" somewhere almost every quarter.
EVENT_NEAR = 240
# What the judge reads of one passage: the stretch around the words, since a
# release runs to pages and the cut can sit on the last one.
EXCERPT_CHARS = 2000


def _says(rule: str, text: str) -> int | None:
    """Where `text` first says what `rule` watches for (its two words within
    EVENT_NEAR of each other), or None."""
    pair = EVENT_WORDS.get(rule)
    if not pair:
        return None
    folded = text.casefold()
    for found in re.finditer(pair[0], folded):
        near = folded[max(found.start() - EVENT_NEAR, 0):found.end() + EVENT_NEAR]
        if re.search(pair[1], near):
            return found.start()
    return None


def _excerpt(text: str, at: int) -> str:
    """The EXCERPT_CHARS of `text` around position `at`, a third before it."""
    if len(text) <= EXCERPT_CHARS:
        return text
    start = min(max(at - EXCERPT_CHARS // 3, 0), len(text) - EXCERPT_CHARS)
    return text[start:start + EXCERPT_CHARS]


def _seen_key(item: dict) -> str:
    raw = f"{item.get('source')}|{item.get('day')}|{item.get('text', '')[:120]}"
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def fundamental_due(entry: Entry, day: date) -> bool:
    """Whether a fundamental rule's statement is worth reading again today:
    never read, or its latest quarter old enough for a newer one to be out."""
    snap = entry.snapshot
    if snap.get("checked") == day.isoformat():
        return False
    try:
        end = date.fromisoformat(str(snap.get("quarter_end") or ""))
    except ValueError:
        return True
    return (day - end).days > QUARTER_DUE_DAYS


def event_due(entry: Entry, day: date) -> bool:
    return entry.snapshot.get("checked") != day.isoformat()


# (rule, ticker, passages) -> {"met", "item", "quote"}, or None when no model
# answered (the passages are then judged on the next check).
Judge = Callable[[str, str, list[dict]], dict | None]


def _judged(rule: str, ticker: str, fresh: list[dict], judge: Judge) -> dict | None:
    """The judge's verdict on `fresh`, held to what it was shown: a hit names
    a passage that exists and quotes words that passage holds."""
    verdict = judge(rule, ticker, fresh)
    if not isinstance(verdict, dict):
        return None
    if not verdict.get("met"):
        return {"met": False}
    index = verdict.get("item")
    quote = " ".join(str(verdict.get("quote") or "").split())
    if not isinstance(index, int) or not 0 <= index < len(fresh) or not quote:
        return {"met": False}
    if quote.casefold() not in " ".join(fresh[index]["text"].split()).casefold():
        return {"met": False}
    return {"met": True, "item": fresh[index], "quote": quote[:200]}


def check_slow(path: Path, day: date, *, quarters_of: Callable[[str], list],
               passages_of: Callable[[str, date], list[dict]],
               judge: Judge, budget_s: float = 20.0) -> list[dict]:
    """Check every slow rule that is due, write what was found back on the
    rules, and return the rows (as `measured` would) of those met today.

    `quarters_of(ticker)` is the quarterly statement; `passages_of(ticker,
    since)` the filings and headlines since a day, each {"source", "day",
    "text"}; `judge` the model's reading. A fetch that fails leaves its rule
    unchecked for the next card; `budget_s` stops the round before the card
    waits too long on it. Never raises."""
    start = time.monotonic()
    found: dict[str, dict] = {}
    for e in criteria(load(path)):
        if time.monotonic() - start > budget_s:
            obs.event("journal.slow_budget_spent", checked=len(found))
            break
        rule = str(e.snapshot.get("rule") or e.action)
        if e.state != "open":  # met already: it stays met until retired
            continue
        try:
            if rule in FUNDAMENTAL_RULES and fundamental_due(e, day):
                level = _finite(e.snapshot.get("level"))
                if level is None:
                    continue
                got = measure_fundamental(rule, level,
                                          int(e.snapshot.get("quarters") or 1),
                                          list(quarters_of(e.ticker) or []))
                found[e.id] = {"checked": day.isoformat(), **(
                    {} if got is None else
                    {"value": got["value"], "gap": got["gap"],
                     "quarter_end": got["quarter_end"],
                     "_met": got["met"]})}
            elif rule in EVENT_RULES and event_due(e, day):
                found_event = _check_event(e, rule, day, passages_of, judge)
                if found_event is not None:
                    found[e.id] = found_event
        except Exception as exc:  # noqa: BLE001 — a throttled fetch, next card
            obs.warn("journal.slow_check_failed", rule=rule,
                     error_type=type(exc).__name__)
    return _write_checks(path, found, day)


def _check_event(e: Entry, rule: str, day: date, passages_of, judge) -> dict | None:
    """What one event rule's check found, for `_write_checks`; None when it
    could not be judged today (the passages wait for the next check)."""
    try:
        since = date.fromisoformat(e.day)
    except ValueError:
        since = day
    seen = list(e.snapshot.get("seen") or [])
    fresh = [p for p in passages_of(e.ticker, since) or ()
             if isinstance(p, dict) and str(p.get("text") or "").strip()
             and str(p.get("day") or "") >= since.isoformat()
             and _seen_key(p) not in seen]
    asked = [{**p, "text": _excerpt(str(p["text"]), at)} for p in fresh
             if (at := _says(rule, str(p["text"]))) is not None][:6]
    out: dict = {"checked": day.isoformat()}
    if asked:
        verdict = _judged(rule, e.ticker, asked, judge)
        if verdict is None:
            return None
        if verdict["met"]:
            item = verdict["item"]
            out |= {"_met": True, "quote": verdict["quote"],
                    "source": str(item.get("source") or ""),
                    "source_day": str(item.get("day") or "")}
    out["seen"] = (seen + [_seen_key(p) for p in fresh])[-MAX_SEEN:]
    return out


def _write_checks(path: Path, found: dict[str, dict], day: date) -> list[dict]:
    """Stamp each check on its rule and move the met ones to ``hit``; return
    the met rows as `measured` reads them."""
    if not found:
        return []
    iso, now = day.isoformat(), _now()
    fired: list[Entry] = []
    with _LOCK:
        entries = load(path)
        for i, e in enumerate(entries):
            got = found.get(e.id)
            if got is None or e.type != "criterion" or e.state not in LIVE:
                continue
            met = got.get("_met") and e.state == "open"
            snapshot = {**e.snapshot, **{k: v for k, v in got.items()
                                         if not k.startswith("_")}}
            if met:
                snapshot |= {"hit_day": iso, "hit_value": snapshot.get("value")}
                entries[i] = replace(e, state="hit", last=iso, snapshot=snapshot,
                                     updated=now)
                fired.append(entries[i])
            else:
                entries[i] = replace(e, snapshot=snapshot, updated=now)
        _save(path, entries)
    rows = [_stored_row(e, str(e.snapshot.get("rule") or e.action)) for e in fired]
    return [r for r in rows if r is not None]


def mark_hit(path: Path, rows: Iterable[dict], day: date) -> list[dict]:
    """Move each armed rule `measured` found met to ``hit``, stamping the day
    and the figure; return the rows as they now stand. A rule hit already
    keeps its first hit day: it fired once, and the card says so once."""
    rows = [dict(r) for r in rows]
    fired = {r["id"]: r for r in rows if r.get("met") and r.get("state") == "open"}
    if not fired:
        return rows
    iso, now = day.isoformat(), _now()
    with _LOCK:
        entries = load(path)
        changed = False
        for i, e in enumerate(entries):
            r = fired.get(e.id)
            if r is None or e.state != "open":
                continue
            snapshot = {**e.snapshot, "hit_day": iso, "hit_value": r["value"]}
            entries[i] = replace(e, state="hit", last=iso, snapshot=snapshot,
                                 updated=now)
            changed = True
        if changed:
            _save(path, entries)
    for r in rows:
        if r["id"] in fired:
            r.update(state="hit", hit_day=iso)
    return rows


def criterion_text(entry: Entry) -> str:
    """The rule in plain English: "closes at or below 95", "down 30% from
    cost"."""
    rule = str(entry.snapshot.get("rule") or entry.action)
    raw = entry.snapshot.get("level")
    level = f"{raw:g}" if isinstance(raw, int | float) else str(raw)
    n = int(entry.snapshot.get("quarters") or 1)
    run = "" if n <= 1 else f", {n} quarters running"
    return {
        "below": f"closes at or below {level}",
        "drawdown_cost": f"down {level}% or more from cost",
        "drawdown_high": f"down {level}% or more from its 52-week high",
        "weight_above": f"{level}% or more of the book",
        "revenue_growth_below": f"revenue growth under {level}% a year{run}",
        "gross_margin_below": f"gross margin under {level}%{run}",
        "operating_margin_below": f"operating margin under {level}%{run}",
        "ceo_change": "the CEO leaves or is replaced",
        "guidance_cut": "the company cuts or withdraws its guidance",
        "dividend_cut": "the dividend is cut or suspended",
    }.get(rule, f"{rule} {level}")


# ------------------------------------------------------------------ reading


def query(entries: list[Entry], *, ticker: str = "", type: str = "",
          state: str = "", source: str = "", since: str = "") -> list[Entry]:
    """Entries matching every filter given, newest first."""
    want = ticker.strip().upper()
    out = [
        e for e in entries
        if (not want or e.ticker.upper() == want
            or e.ticker.upper().split(".")[0] == want.split(".")[0])
        and (not type or e.type == type)
        and (not state or e.state == state)
        and (not source or e.source == source)
        and (not since or e.last >= since)
    ]
    out.sort(key=lambda e: (e.last, e.updated), reverse=True)
    return out


def line_for(entry: Entry) -> str:
    """One plain-English line per entry, for the chat tool and the connector:
    what was proposed, when, on which figures, and what became of it."""
    if entry.type == "criterion":
        head = (f"[{entry.id}] {entry.day} exit rule {entry.ticker}: "
                f"{criterion_text(entry)} · {entry.state}")
        snap = entry.snapshot
        if snap.get("hit_day"):
            head += f" on {snap['hit_day']}"
            if snap.get("hit_value") is not None:
                head += f" (at {snap.get('hit_value')})"
        elif snap.get("value") is not None:
            head += f" (last read {snap['value']}"
            head += f", quarter to {snap['quarter_end']})" if snap.get(
                "quarter_end") else ")"
        lines = [head]
        if snap.get("quote"):
            lines.append(f"  met on: {snap.get('source') or ''} "
                         f"{snap.get('source_day') or ''} \"{snap['quote']}\"")
        if entry.evidence:
            lines.append(f"  thesis: {entry.evidence}")
        if entry.links:
            lines.append("  linked: " + ", ".join(entry.links))
        return "\n".join(lines)
    span = entry.day if entry.last == entry.day else f"{entry.day}→{entry.last}"
    head = f"[{entry.id}] {span} {entry.source} · {entry.action}"
    if entry.ticker:
        head += f" {entry.ticker}"
    head += f" · {entry.state}"
    if entry.settled.startswith("ledger:"):
        head += f" (trade on {entry.settled[7:]})"
    if entry.times > 1:
        head += f" (shown {entry.times} days)"
    parts = [head]
    if entry.line:
        parts.append(f"  said: {entry.line}")
    if entry.reasons:
        parts.append("  reasons: " + ", ".join(entry.reasons))
    figures = ", ".join(f"{k}={v}" for k, v in entry.snapshot.items() if v is not None)
    if figures:
        parts.append(f"  figures then: {figures}")
    if since := since_line(entry):
        parts.append(f"  price since: {since}")
    if entry.evidence:
        parts.append(f"  analysis: {entry.evidence}")
    if entry.links:
        parts.append("  linked: " + ", ".join(entry.links))
    return "\n".join(parts)
