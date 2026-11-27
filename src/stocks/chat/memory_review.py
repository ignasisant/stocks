"""The weekly tidy-up of saved memories: proposed to the user, never done.

A list that only grows turns into noise: two memories that say the same
thing, one the user has since contradicted, one about a plan that ended. Once
a week (REVIEW_DAYS), when the daily card is built, the list is read against
what the user said lately and a few changes are *proposed* — merge these two,
drop that one, reword this — for the user to apply or wave away on the memory
screen. Nothing here edits the list on its own: what the user said is
evidence, and a summary of it written by a model drifts from it every time it
is rewritten. The chat history stays whole (`chat/memory.py`) whatever is
merged here.

Two sources of proposals. Without a model: a memory past its end (`until`),
one no question touched in UNUSED_DAYS (`learnings.idle`), two that say the
same thing (`learnings._same`). With one: merges and rewordings it reads in
the list and the user's recent messages, kept only where they hold up — known
ids, the user's own words (`learnings._grounded`), at most MAX_PROPOSALS.

A third source needs no model either and runs every day, not every week:
the book. A memory about a holding (`tickers`) said before a sale that closed
that position, or before a buy that opened one, may no longer hold — "tengo 50
NVDA" after selling them all. The proposal is to retire it (`retire`): it ends
on the day of the trade and stays listed, saying why, so the reader keeps the
evidence rather than a gap. Only a position opened or closed counts, never a
figure: a memory's numbers are the user's words, and the app does not reword
them (`learnings._grounded`).

Stored beside the list (`review`), with the proposals the user dismissed
(`dismissed`, for DISMISS_DAYS) so the same advice is not repeated next week.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from stocks import obs, userstore
from stocks.chat import learnings
from stocks.llm import structured

REVIEW_DAYS = 7  # between two reviews of one account
RECENT_DAYS = 14  # of the user's messages read against the list
MAX_PROPOSALS = 5
DISMISS_DAYS = 30
MIN_ITEMS = 3  # a shorter list has nothing to tidy
REVIEW_TIMEOUT = 45
_SAID_CHARS = 400  # of each recent message handed over
_SAID_MAX = 30

ACTIONS = ("drop", "merge", "reword", "retire")
# Why a proposal was made: all but "model" are worked out here and worded by
# the app; "model" carries the model's own reason, "book" its trade (`ticker`,
# `event` one of EVENTS, `on` its day).
REASONS = ("expired", "idle", "same", "model", "book")
EVENTS = ("closed", "opened")
# What a position held, planned or aimed at; constraints and preferences stay.
TRADED = frozenset({"context", "decision", "goal"})
_EMPTY = 1e-9  # shares below this are none: float dust from a full sale

_RUNNING: set[str] = set()
_RUNNING_LOCK = threading.Lock()


@dataclass(frozen=True)
class Proposal:
    """One change offered: `drop` the memories in `ids`, `merge` them into
    one saying `text` (kept in the first id), or `reword` the one in `ids` to
    `text`. `sid` names it for apply / dismiss, and is the same whenever the
    same change is proposed again."""

    sid: str
    action: str
    ids: tuple[str, ...]
    reason: str
    text: str = ""
    note: str = ""  # the model's reason, for reason "model"
    # The trade behind a "book" proposal: its ticker, "closed" or "opened",
    # and its day.
    ticker: str = ""
    event: str = ""
    on: str = ""

    def as_dict(self) -> dict:
        out = asdict(self)
        out["ids"] = list(self.ids)
        return out


def _sid(action: str, ids: tuple[str, ...], text: str, evidence: str = "") -> str:
    parts = [action, *sorted(ids), learnings._fold(text)]
    if evidence:
        # A trade is its own advice: waving away "idle" must not mute "you
        # sold it all", nor one sale the next.
        parts.append(evidence)
    key = "\x00".join(parts)
    return "r_" + hashlib.sha256(key.encode()).hexdigest()[:12]


def proposal(action: str, ids: tuple[str, ...], reason: str, text: str = "",
             note: str = "", *, ticker: str = "", event: str = "",
             on: str = "") -> Proposal:
    evidence = f"{reason}:{ticker}:{event}:{on}" if reason == "book" else ""
    return Proposal(_sid(action, ids, text, evidence), action, ids, reason,
                    text, note, ticker, event, on)


# ------------------------------------------------------------- deterministic


def plain(items: list[learnings.Learning], used: dict[str, dict],
          day: str) -> list[Proposal]:
    """What needs no model: memories past their end, memories nothing
    touched in UNUSED_DAYS, and pairs that say the same thing."""
    out: list[Proposal] = []
    facts = [i for i in items if i.kind != "routine"]
    for item in facts:
        if item.expired(day):
            out.append(proposal("drop", (item.id,), "expired"))
        elif learnings.idle(item, used, day):
            out.append(proposal("drop", (item.id,), "idle"))
    paired: set[str] = set()
    for n, a in enumerate(facts):
        for b in facts[n + 1:]:
            if a.id in paired or b.id in paired or a.kind != b.kind:
                continue
            if learnings._same(a.text, b.text) or learnings._same(b.text, a.text):
                # The newer wording is the one kept: the user said it last.
                keep, gone = (b, a) if b.updated >= a.updated else (a, b)
                out.append(proposal("merge", (keep.id, gone.id), "same",
                                    text=keep.text))
                paired |= {a.id, b.id}
    return out


# -------------------------------------------------------------------- book


def book_events(transactions: list) -> dict[str, list[tuple[str, str]]]:
    """{ticker: [(day, event)]}, oldest first: the days a position was
    "opened" (a buy from none) or "closed" (a sale down to none), read at the
    end of each day. Shares moving between brokers are neither: the ledger's
    transfer legs are netted first (`transfers.normalize`), and a day is
    read whole, so a same-day sell and buy-back is no event at all."""
    from stocks.portfolio import transfers
    from stocks.portfolio.positions import replay_order

    held: dict[str, float] = {}
    out: dict[str, list[tuple[str, str]]] = {}
    day_trades: dict[str, set[str]] = {}
    before: dict[str, float] = {}
    current = ""

    def close_day() -> None:
        for tk, actions in day_trades.items():
            was, now = before.get(tk, 0.0) > _EMPTY, held.get(tk, 0.0) > _EMPTY
            if was and not now and "sell" in actions:
                out.setdefault(tk, []).append((current, "closed"))
            elif now and not was and "buy" in actions:
                out.setdefault(tk, []).append((current, "opened"))
        day_trades.clear()
        before.clear()

    for tx in sorted(transfers.normalize(list(transactions)), key=replay_order):
        if tx.date != current:
            close_day()
            current = tx.date
        tk = tx.ticker.upper()
        if tx.action not in ("buy", "sell", "split"):
            continue
        before.setdefault(tk, held.get(tk, 0.0))
        if tx.action == "buy":
            held[tk] = held.get(tk, 0.0) + tx.quantity
        elif tx.action == "sell":
            held[tk] = held.get(tk, 0.0) - tx.quantity
        else:
            held[tk] = held.get(tk, 0.0) * (tx.quantity or 1.0)
        day_trades.setdefault(tk, set()).add(tx.action)
    close_day()
    return out


def _book_ticker(ticker: str, books: set[str]) -> str:
    """The book's label for a memory's `ticker`: the same; else, for a bare
    symbol ("SAN"), the one listing of it ("SAN.MC"); for a coin pair
    ("BTC-USD"), the one pair of that coin ("BTC-EUR"). A listing names its
    venue, so "SAN.MC" never stands for "SAN.PA" — another company. "" when
    none fits, or two would."""
    tk = ticker.upper()
    if tk in books:
        return tk
    if "." in tk:
        return ""
    coin, pair = tk.split("-")[0], "-" in tk
    fits = {b for b in books
            if (b.startswith(f"{coin}-") if pair else b.split(".")[0] == tk)}
    return fits.pop() if len(fits) == 1 else ""


def from_book(items: list[learnings.Learning],
              events: dict[str, list[tuple[str, str]]],
              day: str) -> list[Proposal]:
    """Retire the memories the book has overtaken: about a holding
    (`tickers`), and said before a trade that opened or closed it. The
    trade must fall after the day the memory was last said — a memory saved
    on the day of a sale may be about that sale — and not after `day`. Only
    the kinds a trade can overtake (`TRADED`): a rule or a taste ("never
    more than 10 % in NVDA") outlives the sale. One proposal per memory, for
    its latest trade."""
    books = set(events)
    out: list[Proposal] = []
    for item in items:
        if item.kind not in TRADED or item.expired(day) or not item.tickers:
            continue
        said = (item.updated or item.created)[:10]
        latest: tuple[str, str, str] | None = None
        for tk in item.tickers:
            label = _book_ticker(tk, books)
            for on, event in events.get(label, ()) if label else ():
                if said < on <= day and (latest is None or on > latest[0]):
                    latest = (on, event, tk.upper())
        if latest is not None:
            on, event, tk = latest
            out.append(proposal("retire", (item.id,), "book", ticker=tk,
                                event=event, on=on))
    return out


def _ledger(db: Path) -> list:
    """The account's ledger, [] when it has none — never a fresh empty db
    created just to be read."""
    from stocks.portfolio import ledger

    return ledger.all_transactions(db) if db.exists() else []


# ------------------------------------------------------------------- model


def review_prompt(items: list[learnings.Learning]) -> str:
    saved = "\n".join(
        f"- {i.id}: ({i.kind}{', until ' + i.until if i.until else ''}) "
        f"{learnings.one_line(i.text)}" for i in items if i.kind != "routine")
    return (
        "You tidy a short list of facts one investor asked their financial "
        "assistant to remember. Read the list and the user's recent "
        "messages, and propose changes only where the list is clearly "
        "worse without them:\n"
        "- merge: two or three items that say overlapping things — ids, and "
        "one text that says all of them\n"
        "- drop: one item the user's recent messages contradict, or that "
        "plainly no longer holds — its id\n"
        "- reword: one item the user's recent messages changed — its id and "
        "the new text\n"
        "Every text is a short first-person statement in the language of the "
        "list, made of the user's own words, tickers and numbers, at most "
        f"{learnings.LESSON_CHARS} characters. Never add a fact that is not in "
        "the list or the messages. `reason` is one short sentence, in the "
        "language of the list, the user will read.\n\n"
        f"Saved list:\n{saved}\n\n"
        f"At most {MAX_PROPOSALS} changes. Most weeks the list is fine: then "
        "reply with an empty `ops` list."
    )


def review_request(said: list[str]) -> str:
    if not said:
        return "Recent messages from the user: (none)"
    return "Recent messages from the user, newest first:\n" + "\n".join(
        f"- {learnings._quote(m, _SAID_CHARS)}" for m in said[:_SAID_MAX])


def review_call(items: list[learnings.Learning],
                said: list[str]) -> tuple[str, list[dict]]:
    return structured.render("ReviewMemories", review_prompt(items),
                             review_request(said))


def proposals(raw: str, items: list[learnings.Learning],
              said: str) -> list[Proposal] | None:
    """The model's proposals that hold up, or None when the reply is not the
    JSON asked for. `said` is everything a new wording may be made of: the
    user's recent messages and the list itself (the user's words too)."""
    try:
        body = structured.parse(raw, "ReviewMemories")
    except structured.OffContract:
        return None
    ops = body.get("ops")
    if not isinstance(ops, list) or (ops and not any(op.get("action") for op in ops)):
        return None
    known = {i.id: i for i in items if i.kind != "routine"}
    out: list[Proposal] = []
    for op in ops:
        if len(out) >= MAX_PROPOSALS:
            break
        action = op.get("action")
        ids = tuple(dict.fromkeys(str(i) for i in op.get("ids") or ()))
        if action not in ACTIONS or not ids or any(i not in known for i in ids):
            continue
        if (action == "merge") != (len(ids) > 1) or len(ids) > 3:
            continue
        text = ""
        if action in ("merge", "reword"):
            text = learnings._clean(str(op.get("text") or ""))
            was = learnings._fold(known[ids[0]].text)
            if (len(text) < learnings.MIN_CHARS
                    or not learnings._grounded(text, said)
                    or (action == "reword" and learnings._fold(text) == was)):
                continue
        note = learnings._cut(" ".join(str(op.get("reason") or "").split()), 160)
        out.append(proposal(action, ids, "model", text=text, note=note))
    return out


# ------------------------------------------------------------------- store


def _dismissed(path: Path, day: str) -> dict[str, dict]:
    """{sid: entry} of the proposals waved away: for DISMISS_DAYS, or for
    good when it was a trade's (`book`) — "it still holds after that sale"
    is an answer, and the sale will not change to make it wrong."""
    since = (date.fromisoformat(day) - timedelta(days=DISMISS_DAYS)).isoformat()
    raw = learnings.side(path, "dismissed")
    return {str(e["sid"]): e
            for e in (raw if isinstance(raw, list) else [])
            if isinstance(e, dict) and e.get("sid")
            and (e.get("book") or str(e.get("day") or "") >= since)}


def _stored(path: Path) -> tuple[str, list[Proposal]]:
    raw = learnings.side(path, "review")
    if not isinstance(raw, dict):
        return "", []
    out = []
    for p in raw.get("items") or []:
        try:
            action = str(p["action"])
            if action not in ACTIONS:
                continue  # written by a newer release: not ours to show
            out.append(Proposal(str(p["sid"]), action,
                                tuple(str(i) for i in p["ids"]),
                                str(p.get("reason") or "model"),
                                str(p.get("text") or ""),
                                str(p.get("note") or ""),
                                str(p.get("ticker") or ""),
                                str(p.get("event") or ""),
                                str(p.get("on") or "")))
        except (KeyError, TypeError):
            continue
    return str(raw.get("day") or ""), out


def _checked(path: Path) -> str:
    """The day the book was last read against the list."""
    raw = learnings.side(path, "review")
    return str(raw.get("book") or "") if isinstance(raw, dict) else ""


def pending(path: Path, day: str | None = None) -> list[Proposal]:
    """The proposals still open: about memories that are all still kept, and
    not dismissed."""
    day = day or learnings._today()
    ids = {i.id for i in learnings.load(path)}
    gone = _dismissed(path, day)
    return [p for p in _stored(path)[1]
            if p.sid not in gone and all(i in ids for i in p.ids)]


def due(path: Path, day: str) -> bool:
    """Whether this account's list is due a review on `day`."""
    last = _stored(path)[0]
    if last and last > (date.fromisoformat(day)
                        - timedelta(days=REVIEW_DAYS)).isoformat():
        return False
    return len(learnings.load(path)) >= MIN_ITEMS


def book_due(path: Path, day: str) -> bool:
    """Whether the book is still to be read against the list on `day`: once
    a day, and only for a list with a memory about a holding — however
    short, since one stale fact is as wrong in a list of one."""
    if _checked(path) >= day:
        return False
    return any(i.tickers and i.kind != "routine" for i in learnings.load(path))


def keep(path: Path, found: list[Proposal], day: str, *,
         week: str | None = None, book: bool = False) -> list[Proposal]:
    """Store `found` as the open proposals (deduplicated, dismissed ones out,
    at most MAX_PROPOSALS; the first about a memory wins), as the review of
    `week` (`day` by default). `book` says the book was read on `day`.
    Returns what was kept."""
    with userstore.lock(path):
        gone = _dismissed(path, day)
        seen: set[str] = set()
        touched: set[str] = set()
        out: list[Proposal] = []
        for p in found:
            if p.sid in gone or p.sid in seen or touched & set(p.ids):
                continue
            seen.add(p.sid)
            touched |= set(p.ids)
            out.append(p)
            if len(out) >= MAX_PROPOSALS:
                break
        checked = _checked(path)
        learnings.set_side(path, review={
            "day": day if week is None else week,
            "book": max(checked, day) if book else checked,
            "items": [p.as_dict() for p in out]})
        return out


def add_book(path: Path, found: list[Proposal], day: str) -> list[Proposal]:
    """Put the book's proposals before the week's, without making it a new
    week: the review's day stays, so the weekly one is still owed when due.
    Returns what is open after."""
    with userstore.lock(path):
        week, stored = _stored(path)
        return keep(path, [*found, *stored], day, week=week, book=True)


def settle(path: Path, sid: str, action: str,
           day: str | None = None) -> dict | None:
    """Apply or dismiss one open proposal. Returns {"op", "changes"} — the
    changes as `learnings.change` files them — or None when there is no such
    open proposal (gone, settled, or about a memory since deleted)."""
    day = day or learnings._today()
    with userstore.lock(path):
        found = next((p for p in pending(path, day) if p.sid == sid), None)
        if found is None:
            return None
        stored_day, stored = _stored(path)
        rest = [p.as_dict() for p in stored if p.sid != sid]
        made: list[dict] = []
        if action == "apply":
            made = _apply(path, found)
            obs.event("chat.memory_review.applied", action=found.action,
                      reason=found.reason)
        else:
            obs.event("chat.memory_review.dismissed", action=found.action,
                      reason=found.reason)
        dismissed = list(_dismissed(path, day).values())
        if action != "apply":
            dismissed.append({"sid": sid, "day": day,
                              **({"book": True} if found.reason == "book" else {})})
        learnings.set_side(path, review={"day": stored_day,
                                         "book": _checked(path), "items": rest},
                           dismissed=dismissed)
        return {"op": action, "changes": made}


def _apply(path: Path, p: Proposal) -> list[dict]:
    if p.action == "drop":
        return [learnings.change("deleted", gone) for lid in p.ids
                if (gone := learnings.drop(path, lid)) is not None]
    if p.action == "retire":
        done = learnings.retire(
            path, p.ids[0], day=p.on or learnings._today(), why="book",
            note={"ticker": p.ticker, "event": p.event, "on": p.on})
        return [learnings.change("updated", done)] if done else []
    keep_id, *others = p.ids
    before = next((i.text for i in learnings.load(path) if i.id == keep_id), "")
    kept = (learnings.edit(path, keep_id, text=p.text, why="review",
                           note={"reason": p.reason})
            if p.text else None)
    made = [learnings.change("updated", kept, before=before)] if kept else []
    for old in others:
        done = learnings.supersede(path, keep_id, old)
        if done is not None:
            made.append(learnings.change("deleted", done[1]))
    return made


# --------------------------------------------------------------------- run


def start(prefs: dict, chat_path: Path, *, day: str | None = None,
          session_keys: dict[str, str] | None = None) -> threading.Event | None:
    """Review this account's list on a thread of its own, when it is due:
    the book every day (`book_due`, no model), the whole list every week
    (`due`). Returns the event set once done; None when there was nothing to
    do.

    A free-chain call spends the shared pot (`spend_free_global`), like the
    unasked learning: the user never asked for it."""
    from stocks.accounts import GuestIsReadOnly, writable
    from stocks.chat import conversations, engine, memory

    if not engine.memory_on(prefs):
        return None
    path = learnings.path_for(chat_path)
    # Beside chat.json, for the owner's paths and a data dir's alike.
    db = chat_path.with_name("portfolio.db")
    day = day or learnings._today()
    key = str(path)
    try:
        writable(path)
        weekly = due(path, day)
        book = db.exists() and book_due(path, day)
        if not (weekly or book):
            return None
    except GuestIsReadOnly:
        return None
    with _RUNNING_LOCK:
        if key in _RUNNING:
            return None
        _RUNNING.add(key)
    asked = dict(prefs)
    done = threading.Event()

    def work() -> None:
        try:
            items = learnings.load(path)
            # A trade is the strongest evidence the list has: first in line.
            traded = from_book(items, book_events(_ledger(db)), day)
            if not weekly:
                kept = add_book(path, traded, day)
                obs.event("chat.memory_review.book", proposed=len(traded),
                          open=len(kept))
                return
            found = [*traded, *plain(items, learnings.usage(path), day)]
            since = (date.fromisoformat(day)
                     - timedelta(days=RECENT_DAYS)).isoformat()
            said = (memory.said_since(conversations.memory_path(chat_path), since)
                    if engine.recall_on(prefs) else [])
            words = "\n".join([*said, *(i.text for i in items)])
            model = engine.complete_attempts(
                asked, *review_call(items, said), REVIEW_TIMEOUT,
                spend_free=engine.spend_free_global,
                accept=lambda raw: proposals(raw, items, words),
                session_keys=session_keys,
            )
            kept = keep(path, [*found, *(model or [])], day, book=True)
            obs.event("chat.memory_review.done", proposed=len(kept),
                      model=model is not None)
        except Exception as exc:  # noqa: BLE001 — a tidy-up never costs a card
            obs.warn("chat.memory_review.failed", error_type=type(exc).__name__,
                     error=str(exc)[:300])
        finally:
            with _RUNNING_LOCK:
                _RUNNING.discard(key)
            done.set()

    threading.Thread(target=obs.carried(work), name="memory-review",
                     daemon=True).start()
    return done
