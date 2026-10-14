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

import json
import secrets
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from stocks import atomic, obs, storage

FILE = "decisions.json"

TYPES = ("proposal", "criterion", "event")
SOURCES = ("daily", "review", "chat")
STATES = ("open", "followed", "declined", "lapsed")

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
}
# The Today page's insider rows: a cluster of insiders buying is a name worth
# a look — the rest of the page (news, comparisons) is read, not decided.
TODAY_ACTIONS = {"insider_cluster": "consider"}
# Review verdicts that propose a move (held: sell, trim, add; outside: buy).
REVIEW_ACTIONS = ("sell", "trim", "add", "buy")
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
        ))
    return out


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
        settled = [e for e in entries if e.state != "open"]
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
                 if e.state == "open"}
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
            )
            if at is not None:
                entries[at] = _lapse(entries[at], now, entry.id)
                entry = replace(entry, links=(entries[at].id,))
            entries.append(entry)
            index[key] = len(entries) - 1
            changed += 1
        judged = set(judged)
        cutoff = (day - timedelta(days=LAPSE_DAYS)).isoformat()
        for i, e in enumerate(entries):
            if e.state != "open" or (e.source, e.subject) in seen:
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
            if e.source == shown.source and e.subject == shown.subject:
                entries[i] = replace(e, state=state, updated=now)
                _save(path, entries)
                return entries[i]
        entry = Entry(
            id=_new_id(), type="proposal", source=shown.source,
            action=shown.action, subject=shown.subject, ticker=shown.ticker,
            line=_text(shown.line, MAX_LINE),
            reasons=tuple(_text(r, 80) for r in shown.reasons[:MAX_REASONS]),
            snapshot=_scalars(shown.snapshot), state=state,
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
        snapshot = {k: v for k, v in data.items() if k not in ("key", "ticker")}
        out.append(Shown(source="daily", subject=key, action=action,
                         ticker=ticker, line=str(item.get("line") or ""),
                         reasons=(kind,), snapshot=snapshot))
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


def judged_in_review(rows: Iterable) -> list[str]:
    """The Review rows rated and found nothing to do about (`record`'s
    `judged`): a proposal open on one of them has been withdrawn."""
    return [f"review:{r.ticker}" for r in rows
            if r.verdict not in REVIEW_ACTIONS and r.verdict != "unrated"]


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
    span = entry.day if entry.last == entry.day else f"{entry.day}→{entry.last}"
    head = f"[{entry.id}] {span} {entry.source} · {entry.action}"
    if entry.ticker:
        head += f" {entry.ticker}"
    head += f" · {entry.state}"
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
    if entry.evidence:
        parts.append(f"  analysis: {entry.evidence}")
    if entry.links:
        parts.append("  linked: " + ", ".join(entry.links))
    return "\n".join(parts)
