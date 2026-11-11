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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from stocks import obs
from stocks.chat import (
    clock,
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
    the briefings, the daily card and its analyses, the
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
# briefings and the walkthrough are the same assistant the user talks to, so
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

    The card, its analyses, the briefings and the walkthrough all write to the
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
    """The exit and buy rules the user saved per name (chat/journal.py), for the
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
        "in a filing or a headline (quoted on its line). A buy rule is the "
        "other side, a level they would buy or add at: a met one is their own "
        "entry reached, said plainly, never a recommendation. Offer "
        "set_criteria to change one only when they ask.\n"
        f"{lines}\n\n"
    )


_SNIPPET_CHARS = 140  # of a recalled turn, on the "based on" line


def _snippet(text: str) -> str:
    """A recalled turn's opening, without the markdown that dresses it."""
    plain = " ".join(re.sub(r"[*_#|`>]+", " ", text).split())
    return plain if len(plain) <= _SNIPPET_CHARS \
        else plain[:_SNIPPET_CHARS - 1].rstrip() + "…"


def earlier(prefs: dict, chat_path: Path, message: str,
            known: dict[str, str] | None = None, today: date | None = None,
            ) -> tuple[list[memory.Memory], list[dict], str]:
    """The earlier conversations `message` is about: (the turns to staple onto
    it, the conversations they came from as `Reply.recalled`, the line that
    says what the app made of a question about an earlier talk — "" for any
    other message).

    Two ways in. A message that asks back ("¿te acuerdas de lo que hablamos
    ayer?", `asked_back`) gets the conversations of that day, or the latest
    ones, whatever they named (`back`). Any other gets the turns about what it
    names (`about`). Both run on every turn, unasked, and not behind
    `web_enabled` — they read one local file and reach nothing. A turn from a
    thread that is no longer in the book is dropped even if the index still
    has it: deleting a conversation is the reader's way of saying it must not
    come back.
    `known` is the watchlist's names (`market.watchlist_names`): with it, a
    holding is found under every name it goes by (`market.aliases`), so
    "Nvidia" also brings back the turn that said "NVDA"."""
    from stocks.chat import conversations

    span = asked_back(message, today or clock.today())
    if span is not None:
        if not recall_on(prefs):
            return [], [], _BACK_OFF
        if not chat_path.exists():
            return [], [], _BACK_NONE
        current = conversations.active_conversation(chat_path)["id"]
        return back(chat_path, span, exclude_thread=current)
    names = market.named(message) if recall_on(prefs) else []
    if recall_on(prefs) and known:
        names = market.aliases(names, message, known)
    if not names or not chat_path.exists():
        return [], [], ""
    current = conversations.active_conversation(chat_path)["id"]
    hits = talk_about(prefs, chat_path, names, exclude_thread=current)
    if not hits:
        return [], [], ""
    book = {c["id"]: c for c in conversations.list_conversations(chat_path)}
    hits = [h for h in hits if h.thread in book]
    threads = _recalled(hits, book)
    if hits:
        obs.event("chat.memory_recalled", notes=len(hits), threads=len(threads))
    return hits, threads, ""


def _recalled(hits: list[memory.Memory], book: dict[str, dict]) -> list[dict]:
    """The conversations `hits` came from, once each, as `Reply.recalled`."""
    threads: dict[str, dict] = {}
    for h in hits:
        threads.setdefault(h.thread, {
            "thread": h.thread, "title": book[h.thread]["title"],
            "when": h.when, "snippet": _snippet(h.text)})
    return list(threads.values())


# ------------------------------------------------------------ asked back
# "¿Te acuerdas de lo que hablamos ayer?" names nothing, so `about` finds
# nothing, and the model's `recall` search has no topic to rank by: in prod
# (2026-11-11) the turn went out with no tool called and the answer was "No
# conservo el historial de conversaciones de días anteriores" — while the
# index held the day before word for word. A question about an earlier talk
# is a question about a day, or about the latest talk, and both are a lookup
# by date: no model, no ranking.
#
# Strict on purpose, since a hit staples whole conversations onto the
# message. Words about talking ("hablamos", "me dijiste", "we discussed") are
# always needed — "¿te acuerdas de cuando cayó el S&P en 2020?" and "la
# última vez que compré" are about the market and the book — and with them a
# day ("ayer", "el lunes", "last week") or a cue that the talk is not this one
# ("te acuerdas", "la última vez", "lo que hablamos"). "You said" with neither
# may be this very conversation, which is already in the prompt. Naming
# another conversation outright ("en otra conversación") is enough alone.


@dataclass(frozen=True)
class Span:
    """The days a question about an earlier talk points at, ISO, both ends
    kept. No days: the latest conversations, whenever they were."""

    since: str = ""
    until: str = ""

    @property
    def dated(self) -> bool:
        return bool(self.since)

    def said(self) -> str:
        if self.since == self.until:
            return f"on {self.since}"
        return f"from {self.since} to {self.until}"


_TALK_RE = re.compile(
    r"\b(?:"
    # es
    r"habl(?:amos|abamos|e|aste|ado)|coment(?:amos|e|aste|ado)|dijiste|"
    r"te dije|te (?:pregunte|conte|consulte)|me has dicho|"
    r"te he (?:dicho|preguntado|contado|comentado)|decidimos|quedamos|"
    r"conversacion(?:es)?|charlamos|"
    # en
    r"we (?:talk|talked|speak|spoke|discuss|discussed|chat|chatted|decide|"
    r"decided|agree|agreed|look at|looked at)|"
    r"you (?:said|told me|mentioned|suggested|recommended)|"
    r"i (?:told|asked) you|discussed|conversations?|"
    # it
    r"(?:ne )?abbiamo (?:parlato|discusso|deciso|visto)|mi hai detto|"
    r"ti ho (?:detto|chiesto)|conversazion[ei]|parlato"
    r")\b")
# Beside talk with no day: the talk is an earlier one.
_CUE_RE = re.compile(
    r"\b(?:"
    # es — "recuerdas", never "recuerda", which is a memory command
    r"te acuerdas|te acordas|recuerdas|la ultima vez|lo que|de que|"
    # en
    r"do you remember|remember (?:what|when|our)|last time|what (?:did )?we|"
    # it
    r"ti ricordi|ricordi|l ?ultima volta|di cosa|quello che"
    r")\b")
# Another conversation, named outright: enough alone.
_ELSEWHERE_RE = re.compile(
    r"\b(?:"
    r"(?:otra|la anterior|la ultima) conversacion|conversacion anterior|"
    r"(?:el otro|el anterior|el ultimo) chat|chat anterior|"
    r"(?:previous|earlier|last|other|another|our) (?:conversation|chat)|"
    r"(?:altra|ultima) (?:conversazione|chat)|"
    r"(?:conversazione|chat) (?:precedente|scorsa)"
    r")\b")

_NUMBERS = {
    "un": 1, "uno": 1, "una": 1, "one": 1, "a": 1,
    "dos": 2, "two": 2, "due": 2,
    "tres": 3, "three": 3, "tre": 3,
    "cuatro": 4, "four": 4, "quattro": 4,
    "cinco": 5, "five": 5, "cinque": 5,
    "seis": 6, "six": 6, "sei": 6,
    "siete": 7, "seven": 7, "sette": 7,
}
_NUMBER = r"(\d{1,2}|" + "|".join(_NUMBERS) + r")"
_WEEKDAYS = {
    0: ("lunes", "monday", "lunedi"),
    1: ("martes", "tuesday", "martedi"),
    2: ("miercoles", "wednesday", "mercoledi"),
    3: ("jueves", "thursday", "giovedi"),
    4: ("viernes", "friday", "venerdi"),
    5: ("sabado", "saturday", "sabato"),
    6: ("domingo", "sunday", "domenica"),
}


def _days(message: str, today: date) -> tuple[date, date] | None:
    """The days `message` names, as (first, last) — None when it names none.
    Folded text; the more specific phrase first ("anteayer" holds "ayer")."""
    def back_by(n: int) -> tuple[date, date]:
        day = today - timedelta(days=n)
        return day, day

    if re.search(r"\b(?:anteayer|antier|antes de ayer|day before yesterday|"
                 r"altroieri|l ?altro ieri|avantieri)\b", message):
        return back_by(2)
    if re.search(r"\b(?:ayer|yesterday|ieri)\b", message):
        return back_by(1)
    if m := re.search(rf"\bhace {_NUMBER} dias?\b|\b{_NUMBER} days? ago\b|"
                      rf"\b{_NUMBER} giorni fa\b", message):
        word = next(g for g in m.groups() if g)
        n = int(word) if word.isdigit() else _NUMBERS[word]
        return back_by(n) if 0 < n <= 31 else None
    if re.search(r"\b(?:el otro dia|hace unos dias|the other day|a few days ago|"
                 r"l ?altro giorno|qualche giorno fa)\b", message):
        return today - timedelta(days=7), today - timedelta(days=1)
    monday = today - timedelta(days=today.weekday())
    if re.search(r"\b(?:la semana pasada|last week|la settimana scorsa)\b",
                 message):
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if re.search(r"\b(?:esta semana|this week|questa settimana)\b", message):
        return monday, today
    first = today.replace(day=1)
    if re.search(r"\b(?:el mes pasado|last month|il mese scorso)\b", message):
        return (first - timedelta(days=1)).replace(day=1), first - timedelta(days=1)
    if re.search(r"\b(?:este mes|this month|questo mese)\b", message):
        return first, today
    for weekday, names in _WEEKDAYS.items():
        if re.search(r"\b(?:" + "|".join(names) + r")\b", message):
            # The last one before today: on a Monday, "el lunes" is a week ago.
            return back_by((today.weekday() - weekday - 1) % 7 + 1)
    if re.search(r"\b(?:hoy|esta manana|today|this morning|earlier today|"
                 r"oggi|stamattina|stamani)\b", message):
        return today, today
    return None


def asked_back(message: str, today: date) -> Span | None:
    """The days `message` asks about an earlier conversation from — a `Span`
    with none when it asks about the latest one — or None when it does not
    ask about an earlier conversation at all."""
    folded = " ".join(re.sub(r"[^\w]+", " ", memory._fold(message or "")).split())
    if not folded:
        return None
    talk = _TALK_RE.search(folded) is not None
    elsewhere = _ELSEWHERE_RE.search(folded) is not None
    if not (talk or elsewhere):
        return None
    days = _days(folded, today)
    if days is not None:
        return Span(days[0].isoformat(), days[1].isoformat())
    if elsewhere or _CUE_RE.search(folded):
        return Span()
    return None


BACK_THREADS = 3  # conversations quoted for a question about an earlier talk
_BACK_ASKED = 3  # of each, the user's turns quoted
_BACK_ASKED_CHARS = 300

_BACK_OFF = (
    "The user is asking about an earlier conversation, but they switched off "
    "\"Use earlier conversations to answer\" in the chat's settings, so none "
    "is quoted here. Say so in one line and that switching it on brings them "
    "back. Never say you cannot keep a history of conversations."
)
_BACK_NONE = (
    "The user is asking about an earlier conversation, and there is none: "
    "conversations are kept for 30 days after their last message. Say so in "
    "one line. Never say you cannot keep a history of conversations."
)
_BACK_FOUND = (
    "The user is asking about an earlier conversation{when}. The ones below "
    "are from then, newest first. Say what the most recent one was about and "
    "where it was left, from these lines only; name the others by their title "
    "in one line, in case they meant one of those."
)
_BACK_MISSED = (
    "The user is asking about an earlier conversation {when}, and nothing was "
    "said in another conversation then. Say so in one line, then say what the "
    "most recent conversation below was about and where it was left, and name "
    "the others by their title."
)


def back(chat_path: Path, span: Span, *, exclude_thread: str = "",
         ) -> tuple[list[memory.Memory], list[dict], str]:
    """The conversations a question about an earlier talk points at, in
    `earlier`'s shape: up to BACK_THREADS of them, newest first, each as the
    user's opening turns and where the assistant left it.

    The days of `span`, or the latest conversations when it names none — and
    also when the days hold none, with the line saying so, since "nothing
    yesterday" is half an answer and the latest talk is usually the rest.
    The index only says which conversations were had on which day: it keeps
    no turn under `memory.MIN_CHARS`, and "¿Qué es el PEG?" is the kind of
    opening that says what a talk was about, so the turns are read from the
    thread itself. A conversation counts only where the user wrote in it: a
    daily card nobody answered is the app talking, not a conversation they
    had. Never raises — a lookup that fails is the line saying none was
    found."""
    from stocks.chat import conversations

    try:
        book = {c["id"]: c for c in conversations.load_book(chat_path)
                ["conversations"] if c["id"] != exclude_thread}
        days: dict[str, str] = {}
        if span.dated:
            index = conversations.memory_path(chat_path)
            for row in memory.between(index, span.since, span.until,
                                      exclude_thread=exclude_thread):
                days.setdefault(row.thread, row.when)
        picked = _talks(list(days), book)
        missed = span.dated and not picked
        if not span.dated or missed:
            days = {c["id"]: _day(c["updated"]) for c in sorted(
                book.values(), key=lambda c: c["updated"], reverse=True)}
            picked = _talks(list(days), book)
    except Exception as exc:  # noqa: BLE001 — recall never costs a turn
        obs.warn("chat.memory.back_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        return [], [], _BACK_NONE
    obs.event("chat.memory_asked_back", dated=span.dated, missed=missed,
              threads=len(picked))
    if not picked:
        return [], [], _BACK_NONE
    hits: list[memory.Memory] = []
    for thread, turns in picked:
        title, when = book[thread]["title"], days[thread]
        asked = [t for t in turns if t["role"] == "user"][:_BACK_ASKED]
        answers = [t for t in turns if t["role"] == "assistant"]
        quoted = [(t, _BACK_ASKED_CHARS) for t in asked]
        if answers:
            quoted.append((answers[-1], memory._QUOTE_CHARS))
        hits += [memory.Memory(
            thread=thread, role=t["role"], when=when, title=title, rank=0,
            text=_cut(" ".join(str(t["content"]).split()), limit))
            for t, limit in quoted]
    if missed:
        lead = _BACK_MISSED.format(when=span.said())
    else:
        lead = _BACK_FOUND.format(when=f" {span.said()}" if span.dated else "")
    return hits, _recalled(hits, book), lead


def _talks(order: list[str], book: dict[str, dict],
           ) -> list[tuple[str, list[dict]]]:
    """The conversations of `order` (newest first) the user wrote in, as
    (thread, its turns), BACK_THREADS at most — only those still in the book:
    deleting a conversation is the reader's way of saying it must not come
    back, even while the index still has it."""
    talks = []
    for thread in order:
        if thread not in book:
            continue
        turns = [m for m in book[thread]["messages"]
                 if m.get("role") in ("user", "assistant")
                 and not m.get("guide") and str(m.get("content") or "").strip()]
        if any(t["role"] == "user" for t in turns):
            talks.append((thread, turns))
        if len(talks) == BACK_THREADS:
            break
    return talks


def _day(stamp: str) -> str:
    """A thread's UTC stamp as the reader's day."""
    try:
        return datetime.fromisoformat(stamp).astimezone(clock.ZONE).date() \
            .isoformat()
    except ValueError:
        return stamp[:10]


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


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
