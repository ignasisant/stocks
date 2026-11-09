"""What the assistant keeps about the user (chat/learnings.py). Written only
from the user's own words — a command typed into the chat, the memory
screen, or a message read for it in the background (`learn`) — and read into
every prompt while the account has it switched on.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from stocks import obs
from stocks.chat import (
    journal,
    learnings,
    market,
    memory,
)
from stocks.chat.engine.actions import (
    _tr,
)
from stocks.chat.engine.completion import (
    complete_attempts,
    spend_free_global,
)

if TYPE_CHECKING:

    pass


def memory_on(prefs: dict) -> bool:
    """Whether the account keeps saved memories and reads them into answers."""
    return prefs.get("chat_memory", True) is not False


def recall_on(prefs: dict) -> bool:
    """Whether an answer may search the account's earlier conversations."""
    return prefs.get("chat_recall", True) is not False


def memory_block(prefs: dict, chat_path: Path, *, routines: bool = True) -> str:
    """The prompt's saved-memories section, "" when off or empty.

    Every surface that writes to the user reads this same block — the chat,
    the digests, the daily card and its analyses, the
    walkthrough — so what the user told the assistant once steers all of
    them, not only the conversation it was said in. `routines=False` is the
    daily card's reading: it answers the routines from its own data
    (`daily_routines`), so the block's "never unprompted" must not reach it."""
    if not memory_on(prefs):
        return ""
    return learnings.block(learnings.load(learnings.path_for(chat_path)),
                           routines=routines)


def used_by(items: list[learnings.Learning], message: str,
            known: dict[str, str]) -> list[str]:
    """The ids of the saved memories `message` is about: its words, and every
    holding it names under any name it goes by ("Nvidia" touches the memory
    filed under NVDA)."""
    tickers = set(market.mentioned(message, known, lookup=lambda _name: ""))
    tickers |= {known[form.upper()] for form in
                market.aliases(market.named(message), message, known)
                if form.upper() in known}
    return learnings.relevant(items, message, tickers)


def note_used(prefs: dict, chat_path: Path, message: str,
              known: dict[str, str]) -> None:
    """Count the saved memories `message` is about (`learnings.relevant`) —
    on a thread of its own, since it is a write to the bucket and a count is
    never worth a slower answer. Nothing is written when none is touched."""
    from stocks.accounts import GuestIsReadOnly, writable

    path = learnings.path_for(chat_path)
    if not memory_on(prefs) or not path.exists():
        return
    try:
        writable(path)
    except GuestIsReadOnly:
        return

    def work() -> None:
        try:
            ids = used_by(learnings.load(path), message, known)
            if ids:
                learnings.note_used(path, ids)
        except Exception as exc:  # noqa: BLE001 — a count never costs a turn
            obs.warn("chat.memory.used_failed", error_type=type(exc).__name__,
                     error=str(exc)[:200])

    threading.Thread(target=work, name="chat-memory-used", daemon=True).start()


def talk_about(prefs: dict, chat_path: Path, names: list[str], *,
               exclude_thread: str = "",
               limit: int = memory.ABOUT_LIMIT,
               cards: bool = True) -> list[memory.Memory]:
    """The earlier conversations' turns about `names`, [] when recall is off.

    What `memory.about` finds, less the turns of a thread that is no longer
    in the book: deleting a conversation is the reader's way of saying it
    must not come back, and the index may not have caught up with that.
    `cards=False` also drops what the assistant said in a daily card's
    thread, and keeps what the user said there: the card reading its own
    past lines back as "the user talking to you" would be the card quoting
    itself — it has its own memory of those (`daily.past_lines`)."""
    from stocks.chat import conversations

    if not names or not recall_on(prefs) or not chat_path.exists():
        return []
    book = {c["id"]: c for c in conversations.list_conversations(chat_path)}
    # Over-fetched when some are going to be dropped, so the cap still counts
    # what is left.
    depth = limit if cards else limit * 3
    hits = [h for h in memory.about(conversations.memory_path(chat_path), names,
                                    limit=depth, exclude_thread=exclude_thread)
            if h.thread in book]
    if not cards:
        hits = [h for h in hits
                if not (book[h.thread]["daily"] and h.role == "assistant")]
    return hits[:limit]


# How a surface that is not the chat reads `user_memory`. The card, the
# digests and the walkthrough are the same assistant the user talks to, so
# they pull the same way: what the user said they want, keep or avoid shapes
# what leads and how it is put. Their audits check figures against their own
# data only, so a figure lifted from a memory would be rejected — or worse,
# be stale — and the clause on figures is what keeps it out.
MEMORY_USE = (
    "WHAT THE USER TOLD YOU. The saved memories above, and any earlier "
    "conversations quoted after the data, are this user talking to you in "
    "the chat. Keep what you write going their way: lead with what they said "
    "matters to them, frame it by their stated goals and limits, and build on "
    "a decision instead of re-raising it — a position they said they keep is "
    "not a reason to suggest selling it again; say what changed since, if "
    "anything did. They are context, not data: never quote a figure, a price "
    "or a date from them — every figure comes from the data only."
)


def user_memory(prefs: dict, chat_path: Path | None, names: Iterable[str] = (),
                *, routines: bool = True) -> tuple[str, list[memory.Memory]]:
    """What the chat knows about this user, for a surface that is not the
    chat: (`memory_block`, the earlier conversations' turns about `names`).

    The card, its analyses, the digests and the walkthrough all write to the
    same person the chat talks to, and read them through here so they pull
    the same way. The turns leave out what earlier daily cards said
    (`talk_about(cards=False)`): every one of these surfaces is written from
    its own data, and an old card line is neither the user nor the data.
    Never raises — a memory that cannot be read is a line written without
    it, never a line that is not written."""
    if chat_path is None:
        return "", []
    try:
        block = memory_block(prefs, chat_path, routines=routines)
    except Exception as exc:
        obs.warn("chat.memory.block_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        block = ""
    try:
        talk = talk_about(prefs, chat_path, list(names), cards=False)
    except Exception as exc:
        obs.warn("chat.memory.talk_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        talk = []
    return block, talk


CARD_DAYS = 3  # a card older than this is not "the card" any more
_CARD_CHARS = 1500


def card_block(chat_path: Path, today: date | None = None) -> str:
    """Home's latest daily card, for the chat's prompt — "" when there is
    none from the last CARD_DAYS days.

    The card is this assistant talking too: what it told the user this
    morning is something a question in the drawer may be
    about ("why does the card say to sell?"), and a message that names
    nothing would not find it through the index. Its figures are as of the
    session it was written from, so the context below wins on anything
    current."""
    from stocks.chat import daily

    try:
        raw = json.loads(daily.card_path(chat_path).read_text())
    except (OSError, ValueError):
        return ""
    card = daily.DailyAction.from_dict(raw)
    if card is None:
        return ""
    try:
        age = ((today or date.today()) - date.fromisoformat(card.day)).days
    except ValueError:
        return ""
    if not 0 <= age <= CARD_DAYS:
        return ""
    text = daily.thread_text(card)[:_CARD_CHARS]
    session = f", from the session of {card.as_of}" if card.as_of else ""
    return (
        f"Home's daily card — what you told the user on the app's Home page "
        f"for {card.day}{session}. When they ask about \"the card\" or "
        f"today's action, this is it; for any current figure, the context "
        f"below wins.\n{text}\n\n"
    )


_CRITERIA_LINES = 30  # live rules in the prompt, newest first


def criteria_block(chat_path: Path) -> str:
    """The exit rules the user saved per holding (chat/journal.py), for the
    chat's prompt — "" when there are none.

    Their own words, kept so an answer about selling or holding one of those
    tickers starts from the line they drew, not from a fresh opinion. Every
    live rule rides along, not only the ones the message names: there are a
    handful, they change when the user writes one, and a block that did not
    vary per message keeps the cached prompt prefix intact."""
    rows = journal.criteria(journal.load(journal.path_for(chat_path)))
    live = rows[::-1][:_CRITERIA_LINES]
    if not live:
        return ""
    lines = "\n".join(journal.line_for(e) for e in live)
    return (
        "The user's own exit rules, saved per holding with their thesis. "
        "When an answer is about selling, trimming or holding one of these "
        "tickers, start from the rule: say whether it is met and hold them "
        "to it, or ask what changed. A hit rule is one already met: by the "
        "price, by the latest quarter's figures, or by an event the app read "
        "in a filing or a headline (quoted on its line). Offer set_criteria "
        "to change one only when they ask.\n"
        f"{lines}\n\n"
    )


_SNIPPET_CHARS = 140  # of a recalled turn, on the "based on" line


def _snippet(text: str) -> str:
    """A recalled turn's opening, without the markdown that dresses it."""
    plain = " ".join(re.sub(r"[*_#|`>]+", " ", text).split())
    return plain if len(plain) <= _SNIPPET_CHARS \
        else plain[:_SNIPPET_CHARS - 1].rstrip() + "…"


def earlier(prefs: dict, chat_path: Path, message: str,
            known: dict[str, str] | None = None,
            ) -> tuple[list[memory.Memory], list[dict]]:
    """The earlier conversations about what `message` names: (the turns to
    staple onto it, the conversations they came from as `Reply.recalled`).

    Run on every turn, unasked, and not behind `web_enabled` — it reads one
    local file and reaches nothing. What it finds and why it is strict about
    it is `memory.about`'s business. A turn from a thread that is no longer
    in the book is dropped even if the index still has it: deleting a
    conversation is the reader's way of saying it must not come back.
    `known` is the watchlist's names (`market.watchlist_names`): with it, a
    holding is found under every name it goes by (`market.aliases`), so
    "Nvidia" also brings back the turn that said "NVDA"."""
    from stocks.chat import conversations

    names = market.named(message) if recall_on(prefs) else []
    if recall_on(prefs) and known:
        names = market.aliases(names, message, known)
    if not names or not chat_path.exists():
        return [], []
    current = conversations.active_conversation(chat_path)["id"]
    hits = talk_about(prefs, chat_path, names, exclude_thread=current)
    if not hits:
        return [], []
    book = {c["id"]: c for c in conversations.list_conversations(chat_path)}
    hits = [h for h in hits if h.thread in book]
    threads: dict[str, dict] = {}
    for h in hits:
        threads.setdefault(h.thread, {
            "thread": h.thread, "title": book[h.thread]["title"],
            "when": h.when, "snippet": _snippet(h.text)})
    if hits:
        obs.event("chat.memory_recalled", notes=len(hits), threads=len(threads))
    return hits, list(threads.values())


def _thread_id(chat_path: Path) -> str:
    """The active conversation's id. A first turn's thread has no id on disk
    yet — every read of a missing chat.json makes up a new one — so it is
    pinned before it is named."""
    from stocks.accounts import writable
    from stocks.chat import conversations

    if chat_path.exists():
        return conversations.active_conversation(chat_path)["id"]
    return conversations.new_conversation(writable(chat_path))


def remember(order: learnings.Command, *, prefs: dict, chat_path: Path,
             watchlist: Path, lang: str) -> tuple[str, list[dict]]:
    """Carry out a memory command: (the note that says what happened, the
    changes as `Reply.learned` files them — empty when nothing changed)."""
    from stocks.accounts import GuestIsReadOnly

    if not memory_on(prefs):
        return _tr("chat.memory_off", lang), []
    if order.everything:
        # Not from a sentence: the one irreversible thing here waits for the
        # button that says what it does, a press away in Settings.
        return _tr("chat.memory_forget_all", lang), []
    path = learnings.path_for(chat_path)
    try:
        if order.op == "forget":
            hit = learnings.match(learnings.load(path), order.text)
            if hit is None:
                return _tr("chat.memory_no_match", lang, text=order.text), []
            learnings.drop(path, hit.id)
            obs.event("chat.memory_forgot", via="chat")
            return (_tr("chat.memory_forgot", lang, text=hit.text),
                    [learnings.change("deleted", hit)])
        tickers = market.mentioned(order.text,
                                   market.watchlist_names(watchlist),
                                   lookup=lambda _name: "")
        done = learnings.save(path, order.text, kind=order.kind or None,
                              tickers=tickers, thread=_thread_id(chat_path))
    except learnings.RoutinesFull:
        return _tr("chat.routines_full", lang, max=learnings.MAX_ROUTINES), []
    except learnings.Full:
        # Full is the user's to settle, but not blind: name the memory that
        # earns its place least, so the choice is one word away.
        items = learnings.load(path)
        least = learnings.suggest_drop(items, learnings.usage(path))
        if least is None:
            return _tr("chat.memory_full", lang, max=learnings.MAX_ITEMS), []
        return _tr("chat.memory_full_suggest", lang, max=learnings.MAX_ITEMS,
                   text=least.text), []
    except GuestIsReadOnly:
        return _tr("chat.memory_off", lang), []
    item = done.item
    if done.op == "known":
        return _tr("chat.memory_known", lang, text=item.text), []
    if done.op == "updated":
        obs.event("chat.memory_corrected", via="chat", kind=item.kind)
        return (_tr("chat.memory_corrected", lang, text=item.text,
                    before=done.before),
                [learnings.change("updated", item, before=done.before)])
    obs.event("chat.memory_saved", via="chat", kind=item.kind,
              related=done.related is not None)
    saved = "chat.routine_saved" if item.kind == "routine" else "chat.memory_saved"
    note = _tr(saved, lang, text=item.text)
    extra: dict = {}
    if done.related is not None:
        note += " " + _tr("chat.memory_related", lang, text=done.related.text)
        extra = {"related_id": done.related.id,
                 "related_text": done.related.text}
    return note, [learnings.change("added", item, **extra)]


LEARN_TIMEOUT = 45.0  # one provider's go at an extraction
LEARN_GRACE = 2.0  # what a finished answer waits for an extraction still out
_LEARN_EARLIER = 3  # earlier user messages handed over, for "that" and "it"


def learn(prefs: dict, chat_path: Path, history: list[dict], watchlist: Path,
          session_keys: dict[str, str] | None = None,
          ) -> threading.Event | None:
    """Read the newest message for something worth remembering about the
    user, unasked — on a thread of its own. Returns the event set once it has
    finished; None when there was nothing to read it for.

    A question is also logged for the daily routines (`learnings.notice`):
    asked on enough days, it is added to the daily card. No model in that,
    but a write to the bucket, which is why it is on this thread too.

    In the background because the free chain takes twenty-odd seconds, and a
    memory is never worth a slower answer. What it changes is announced by
    the stored turn (`_unseen`): this one if it finished in time, the next one
    if not. Only messages that sound like the user talking about themselves
    are read (`learnings.worth_learning`), and only the user's messages are
    handed over — never a page, a tool result or an answer. A free-chain
    extraction spends the shared pot, not the account's allowance: the reader
    never asked for it and must not find a message missing because of it.
    """
    from stocks.accounts import GuestIsReadOnly, writable

    said = [str(m.get("content") or "") for m in history
            if m.get("role") == "user"]
    if not said or not memory_on(prefs):
        return None
    extract = learnings.worth_learning(said[-1])
    question = learnings.asks(said[-1])
    if not (extract or question):
        return None
    path = learnings.path_for(chat_path)
    try:
        writable(path)
        thread = _thread_id(chat_path)
    except GuestIsReadOnly:
        return None
    newest, earlier = said[-1], said[-1 - _LEARN_EARLIER:-1]
    names = market.watchlist_names(watchlist)
    asked = dict(prefs)  # the turn charges its own copy on its own thread
    done = threading.Event()

    def work() -> None:
        try:
            if question:
                _notice(path, newest, thread, names,
                        opener=len(said) == 1 and not history[0].get("daily"))
            if not extract:
                return
            items = learnings.load(path)
            kept = complete_attempts(
                asked, *learnings.lesson_call(items, newest, earlier),
                LEARN_TIMEOUT,
                spend_free=spend_free_global,
                accept=lambda raw: learnings.lessons(
                    raw, items, newest, "\n".join([*earlier, newest])),
                session_keys=session_keys,
            )
            made = learnings.apply(
                path, kept or [], thread=thread,
                tickers=lambda text: market.mentioned(
                    text, names, lookup=lambda _name: ""))
            if made:
                obs.event("chat.memory_learned",
                          ops=[c["op"] for c in made])
        except Exception as exc:  # noqa: BLE001 — a memory never costs a turn
            obs.warn("chat.engine.learn_failed", error_type=type(exc).__name__,
                     error=str(exc)[:300])
        finally:
            done.set()

    threading.Thread(target=work, name="chat-learn", daemon=True).start()
    return done


def _notice(path: Path, newest: str, thread: str, names: dict,
            *, opener: bool) -> None:
    """Log the question for the daily routines; a failure costs nothing but
    the log entry."""
    try:
        made = learnings.notice(
            path, newest, day=datetime.now(UTC).date().isoformat(),
            thread=thread, opener=opener,
            tickers=market.mentioned(newest, names, lookup=lambda _name: ""))
    except Exception as exc:  # noqa: BLE001
        obs.warn("chat.engine.notice_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        return
    if made:
        obs.event("chat.routine_noticed", days=made.get("repeated"))


def _unseen(chat_path: Path) -> list[dict]:
    """The unasked memory changes no turn has said yet, for the one about to
    be stored to say."""
    try:
        return learnings.take_unseen(learnings.path_for(chat_path))
    except Exception as exc:  # noqa: BLE001 — the answer is stored regardless
        obs.warn("chat.engine.unseen_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        return []
