"""An app action the reader is asked about before it runs. The proposal is a
field on the assistant turn that asked, so the thread on disk is the only
place it lives: a reload redraws the same card in the same state, and there
is no second store to fall out of step with the conversation.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from stocks import obs
from stocks.chat import (
    agent,
    journal,
    market,
    toolbox,
)
from stocks.chat.engine.actions import (
    _tr,
    action_reply,
)
from stocks.chat.engine.reply import (
    Reply,
)

if TYPE_CHECKING:

    from stocks.chat.tools import Action
    from stocks.llm import Provider


def _proposal(act: Action) -> dict:
    return {"id": f"act_{secrets.token_hex(6)}", "kind": act.kind,
            "ticker": act.ticker, "args": dict(act.args), "state": "pending"}


def _proposed(evidence: agent.Evidence) -> dict | None:
    """The card a `propose_action` call in the research drafted, or None.

    Read back from the call's own arguments by the rule the tool checked them
    with (`tools.proposed`), so what the model was told it drafted and what
    the reader is shown are one change. The first that parses: the tool tells
    the model one per answer. `by` marks it as the answer's, which keeps its
    analysis when it is settled (`settle_proposal`)."""
    from stocks.chat import tools

    for call in evidence.calls:
        # A refusal (`toolbox._unwarranted`) is what the model read back, so
        # no card: only a call the tool drafted becomes one.
        if (call.name == "propose_action"
                and str(call.result or "").startswith(toolbox.DRAFTED)):
            act = tools.proposed(dict(call.args or {}))
            if act is not None:
                return {**_proposal(act), "by": "agent"}
    return None


def _rules_asked(message: str, watchlist: Path, focus: str) -> str:
    """The ticker a question asks exit rules for, or "" when it asks none.

    The symbol the reader typed wins over the page they typed it on; the
    journal's button names both the key and the company ("RCF
    (Teleperformance SE)"), and the key is what a rule is filed under."""

    if not toolbox.asks_rules(message):
        return ""
    typed = market.mentioned(message, market.watchlist_names(watchlist),
                             lookup=lambda _name: "")
    return (typed[0] if typed else focus).strip().upper()


def _drafted_rules(ticker: str, text: str, provider: Provider,
                   key: str) -> dict | None:
    """The card for the exit rules an answer wrote out but never proposed.

    The reader asked for rules and the answer drafted them in prose ("copy
    into your notes"): the research model skipped `propose_action`, which a
    fallback model often does. Read back with the same router a typed "save
    these rules" goes through, so the card holds only measures the journal
    can check; the reader still approves it, so nothing is saved unseen.
    None when the answer drafted none (it asked a question back instead)."""
    from stocks.chat import tools

    act = tools.detect(provider, key,
                       f"Save these exit rules for {ticker}:\n{text[:_DRAFT_CHARS]}")
    if act is None or act.kind != "set_criteria":
        return None
    # Filed under the key that was asked about, whatever the prose called it.
    act = tools.proposed({**act.args, "action": "set_criteria", "ticker": ticker})
    if act is None:
        return None
    obs.event("chat.rules_drafted", ticker=ticker,
              rules=len(act.args.get("criteria") or []))
    return {**_proposal(act), "by": "agent"}


_DRAFT_CHARS = 6000  # of the answer handed to the router for its rules


def _open_proposal(history: list[dict]) -> int | None:
    """Index of the last turn when it is an assistant turn still asking."""
    if not history:
        return None
    last = history[-1]
    offer = last.get("proposal")
    if last.get("role") == "assistant" and isinstance(offer, dict) \
            and offer.get("state") == "pending":
        return len(history) - 1
    return None


class ProposalError(Exception):
    """A proposal that cannot be settled. `code` is the locale key that says why
    — or, for a trade form the book turns down (`_fill`), the book's own
    sentence, which the drawer shows as it shows a key it has no copy for."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _apply(offer: dict, approve: bool, *, watchlist: Path, lang: str,
           ticker: str | None = None, args: dict | None = None,
           form: dict | None = None, db: Path | None = None,
           source: str = "chat", journal_path: Path | None = None) -> str:
    """Run (or drop) one proposal in place; return the line that says so.

    Mutates `offer` — its state, and on approval the symbol and fields the
    reader may have edited — and raises ProposalError without touching it when
    the edit does not parse or the write fails, so the card stays up and
    pressable rather than claiming a change that never happened.

    A ledger proposal (`offer["book"]`, from `chat/book.py`) is committed
    exactly as planned: it has no form to edit, and a book that moved since
    the plan refuses it rather than applying something nobody was shown.
    """
    from stocks.chat import book, tools

    if not approve:
        offer["state"] = "cancelled"
        obs.event("chat.action_cancelled", action=offer.get("kind"))
        return _tr("chat.action_cancelled", lang)
    if isinstance(offer.get("book"), dict) and "fill" in offer["book"]:
        return _fill(offer, form, db=db, lang=lang)
    if isinstance(offer.get("book"), dict):
        if db is None:
            raise ProposalError("chat.action_failed")
        try:
            note = book.apply(offer, db=db, source=source,
                              translate=lambda k, **kw: _tr(k, lang, **kw))
        except book.Refused as exc:
            obs.warn("chat.engine.book_refused", action=offer.get("kind"),
                     code=exc.code, error=exc.detail[:300])
            raise ProposalError(exc.code) from exc
        offer["state"] = "done"
        obs.event("chat.action_approved", action=offer.get("kind"), edited=False)
        return note
    base = tools.Action(str(offer.get("kind")), str(offer.get("ticker") or ""),
                        dict(offer.get("args") or {}))
    if base.kind not in tools.TOOLS:
        raise ProposalError("chat.action_invalid")
    if form is not None:
        # The card's A2UI form: its fields, as the tool's own arguments.
        ticker = str(form.get("ticker") or base.ticker)
        args = tools.args_from_form(base.kind, form)
    act = tools.revise(base, ticker, args)
    if act is None:
        raise ProposalError("chat.action_invalid")
    try:
        tools.execute(act, watchlist, journal_path=journal_path)
    except Exception as exc:
        obs.warn("chat.engine.action_failed", action=act.kind,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        raise ProposalError("chat.action_failed") from exc
    offer.update({"ticker": act.ticker, "args": dict(act.args),
                  "state": "done"})
    obs.event("chat.action_approved", action=act.kind,
              edited=act != base)
    return action_reply(act, lang)


def _fill(offer: dict, form: dict | None, *, db: Path | None, lang: str) -> str:
    """A trade form sent back filled: the trade planned, the card now asking it.

    The offer stays pending and keeps its id — it turns from the form into the
    ledger proposal (`book.ops`, `token`, the impact), exactly as a trade told
    whole in one message would have been offered — so the reader goes form,
    then the transaction with its figures, then Confirm, on one card.
    """
    from stocks.chat import book, tools

    args = tools.trade_args(form or {})
    if args is None or db is None:
        raise ProposalError("chat.book_fill_missing")
    held = offer["book"]["fill"]
    # A sale of everything ("close_position") is booked like any reported
    # trade once its figures are in, under the label the book holds it by.
    ticker = str(held.get("ticker") or offer.get("ticker") or "")
    act = tools.Action("add_transaction", ticker, {
        **{k: v for k, v in (offer.get("args") or {}).items()
           if k in ("currency", "fee", "broker")},
        **args,
    })
    drafted = book.draft(act, db=db, resolve=book.resolver(),
                         translate=lambda k, **kw: _tr(k, lang, **kw),
                         currency=str(held.get("currency") or "EUR"),
                         market=book.market_close)
    if drafted.book is None:
        raise ProposalError(drafted.text)
    offer.update({"kind": act.kind, "ticker": ticker, "args": dict(act.args),
                  "book": drafted.book})
    obs.event("chat.action_filled", action=act.kind)
    return drafted.text


def _journal(offer: dict, chat_path: Path, asked: str) -> None:
    """Keep an answered proposal about what to own or watch in the decision
    journal (chat/journal.py), with the words it was offered in."""
    from stocks.chat import journal

    shown = journal.from_chat(offer, asked)
    if shown is None or offer.get("state") not in ("done", "cancelled"):
        return
    state = "followed" if offer["state"] == "done" else "declined"
    journal.safely(journal.settle, journal.path_for(chat_path), shown, state,
                   date.today())


def settle_proposal(*, chat_path: Path, watchlist: Path, proposal_id: str,
                    approve: bool, lang: str = "en", ticker: str | None = None,
                    args: dict | None = None, form: dict | None = None,
                    db: Path | None = None) -> Reply:
    """The reader pressed Approve or Cancel on a proposal card.

    The asking turn is rewritten in place — its words become the confirmation
    (or the "nothing changed" line) and its proposal records the outcome — so
    the thread reads as a question that was answered, and the model reading it
    back next turn sees what actually happened rather than an open question.

    Raises LookupError for an id this thread does not hold, and ProposalError
    for one already settled or an edit that does not parse.
    """
    from stocks.chat import conversations

    history = conversations.load_chat(chat_path)
    for entry in reversed(history):
        offer = entry.get("proposal")
        if isinstance(offer, dict) and offer.get("id") == proposal_id:
            break
    else:
        raise LookupError(proposal_id)
    if offer.get("state") != "pending":
        raise ProposalError("chat.action_gone")
    asked = str(entry.get("content") or "")
    note = _apply(offer, approve, watchlist=watchlist, lang=lang,
                  ticker=ticker, args=args, form=form, db=db,
                  journal_path=journal.path_for(chat_path))
    _journal(offer, chat_path, asked)
    # A card under an answer (`_proposed`): the answer stays, and the outcome
    # is its last line. Every other card was only the question, so its words
    # become the outcome.
    if offer.get("by") == "agent":
        note = f"{asked}\n\n{note}"
    entry["content"] = note
    if offer["state"] == "done":
        entry["action"] = offer["kind"]
    conversations.save_chat(history, chat_path)
    return Reply(text=note, proposal=dict(offer))


def _typed_verdict(history: list[dict], index: int, approve: bool, *,
                   prefs: dict, chat_path: Path, watchlist: Path,
                   lang: str, db: Path | None = None,
                   source: str = "chat", thread: str | None = None) -> Reply:
    """A "yes" or "no" typed under a proposal: the same as the button.

    Unlike the button, the reader's words are part of the thread — so the
    asking turn keeps its question, and the outcome is a new answer under the
    "yes" rather than a rewrite above it.
    """
    from stocks.chat import conversations

    offer = history[index]["proposal"]
    try:
        note = _apply(offer, approve, watchlist=watchlist, lang=lang, db=db,
                      source=source, journal_path=journal.path_for(chat_path))
    except ProposalError as exc:
        return Reply(error=exc.code)
    _journal(offer, chat_path, str(history[index].get("content") or ""))
    entry: dict = {"role": "assistant", "content": note}
    if offer["state"] == "done":
        entry["action"] = offer["kind"]
    history.append(entry)
    conversations.save_chat(history, chat_path, thread)
    return Reply(text=note, proposal=dict(offer))


def undo_proposal(*, chat_path: Path, db: Path, proposal_id: str,
                  lang: str = "en") -> Reply:
    """The reader pressed Undo on a ledger proposal that already went through.

    The change is taken back through the journal (`edits.undo`), and the
    thread says so in a new answer — the turn above keeps saying it was done,
    which it was. Raises LookupError for an id this thread does not hold and
    ProposalError for one that is not an applied ledger edit, or whose rows
    something has changed since.
    """
    from stocks.chat import book, conversations

    history = conversations.load_chat(chat_path)
    for entry in reversed(history):
        offer = entry.get("proposal")
        if isinstance(offer, dict) and offer.get("id") == proposal_id:
            break
    else:
        raise LookupError(proposal_id)
    if offer.get("state") != "done" or not isinstance(offer.get("book"), dict):
        raise ProposalError("chat.action_gone")
    try:
        note = book.undo(offer, db=db, translate=lambda k, **kw: _tr(k, lang, **kw))
    except book.Refused as exc:
        raise ProposalError(exc.code) from exc
    offer["state"] = "undone"
    history.append({"role": "assistant", "content": note, "action": "undo_change"})
    conversations.save_chat(history, chat_path)
    obs.event("chat.action_undone", action=offer.get("kind"))
    return Reply(text=note, proposal=dict(offer))


def _book_turn(act: Action, *, history: list[dict], prefs: dict, db: Path,
               chat_path: Path, lang: str, typed: bool,
               stored: Callable[[dict], dict] = lambda e: e,
               thread: str | None = None) -> Reply:
    """A ledger request (`chat/book.py`): drafted with the book in hand, and
    put to the reader whenever it would change anything — on every surface.

    `typed` is a surface with no card to press (a headless caller), so the
    question ends by saying how to answer it in words.
    """
    from stocks.chat import book, conversations

    try:
        drafted = book.draft(act, db=db, resolve=book.resolver(),
                             translate=lambda k, **kw: _tr(k, lang, **kw),
                             currency=str(prefs.get("currency") or "EUR"),
                             market=book.market_close)
    except Exception as exc:
        obs.warn("chat.engine.book_failed", action=act.kind,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return Reply(error="chat.action_failed")
    # An id, like any answer: the classifier read the message, and a misread
    # ("añádelas" adding one of six) is what the thumbs are there to catch.
    entry: dict = {"role": "assistant", "content": drafted.text,
                   "action": act.kind, "id": secrets.token_hex(6)}
    offer = None
    if drafted.fill is not None and not typed:
        # A trade missing a figure: the drawer asks for it with a form (its
        # Review turns the card into the trade itself); the bot, in words.
        offer = {**_proposal(act), "book": {"fill": drafted.fill}}
        entry["proposal"] = offer
        obs.event("chat.action_asked", action=act.kind)
    elif drafted.book is not None:
        offer = {**_proposal(act), "book": drafted.book}
        if typed:
            entry["content"] += "\n\n" + _tr("chat.book_reply_yes", lang)
        entry["proposal"] = offer
        obs.event("chat.action_proposed", action=act.kind)
    if offer is not None:
        # A trade form still open above, answered in words instead ("100 a
        # 26,17"): this card is its answer, so the form is put away.
        for earlier in history:
            shown = earlier.get("proposal")
            if (isinstance(shown, dict) and shown.get("state") == "pending"
                    and isinstance(shown.get("book"), dict)
                    and "fill" in shown["book"]):
                shown["state"] = "cancelled"
    history.append(stored(entry))
    conversations.save_chat(history, chat_path, thread)
    return Reply(text=entry["content"], proposal=dict(offer) if offer else None,
                 turn_id=entry["id"])
