"""Headless chat engine — the web assistant's brain, with no UI in it.

Everything the chat drawer (api/routes/chat/) and the headless callers
share lives here: the persona built from the investor
profile, the portfolio snapshot for the system prompt, skill routing, the
BYOK→free provider resolution (also used by notify/narrative.py), the free
-tier daily quota, and answer() — one complete chat turn against explicit
paths, no session state.

Write discipline: answer() saves chat.json only after a completed
user+assistant pair (matching the web panel), and mutates/saves prefs.json
only for the free-quota counter. A live web session writing the same files is
last-write-wins — accepted, the overlap window is a single turn.
"""

from __future__ import annotations

import functools
import hashlib
import json
import queue
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from stocks import obs
from stocks.chat import (
    a2ui,
    agent,
    allocation,
    charts,
    debate,
    guard,
    harvest,
    income,
    journal,
    learnings,
    market,
    memory,
    plan_builder,
    rebalance,
    reports,
    stopping,
    tokens,
    whatif,
)
from stocks.chat import brief as ticker_brief
from stocks.chat.engine.actions import (
    PAGE_TICKERS,
    _allocation,
    _chart,
    _chart_step,
    _harvest,
    _harvest_step,
    _income,
    _income_step,
    _mix_step,
    _pages,
    _plan_builder,
    _plan_step,
    _rebalance,
    _rebalance_step,
    _reports_ahead,
    _reports_step,
    _sale_step,
    _simulate_sale,
    _tax_year,
    _tr,
    action_context,
    action_reply,
    pasted_report,
)
from stocks.chat.engine.book import (
    book_snapshot,
    enriched_frame,
    held_in,
    portfolio_context,
    reporting_currency,
    sector_exposure,
    tax_rules,
)
from stocks.chat.engine.completion import (
    complete_attempts,
    spend_free_global,
)
from stocks.chat.engine.instructions import (
    CARD_OPENER,
    MAX_CONTEXT_MSGS,
    RULES,
    SCHEDULED_OPENERS,
    _brief_skills,
    language_rule,
    recent,
    resolve_skills,
    system_prompt,
)
from stocks.chat.engine.investor import (
    persona,
)
from stocks.chat.engine.parallel import (
    in_parallel,
)
from stocks.chat.engine.proposals import (
    ProposalError,
    _book_turn,
    _drafted_rules,
    _fill,
    _journal,
    _open_proposal,
    _proposal,
    _proposed,
    _rules_asked,
    _typed_verdict,
    settle_proposal,
    undo_proposal,
)
from stocks.chat.engine.providers import (
    BYOK_TTL,
    FREE_ELIGIBILITY,
    FREE_MIN_ACCOUNT_HOURS,
    account_age_hours,
    attempts,
    byok_alive,
    byok_days_left,
    byok_fields,
    can_store_keys,
    chain,
    decrypt_byok,
    forget_byok,
    free_allowlist,
    free_eligible,
    free_policy,
    in_free_trial,
    note_free_fallback,
    prune_byok,
    save_byok,
)
from stocks.chat.engine.quota import (
    DEEP_UNITS,
    FREE_CAP_ERRORS,
    FREE_DAILY_CAP,
    FREE_GLOBAL_DAILY_CAP,
    FREE_TRIAL_CAP,
    GLOBAL_FREE_FILE,
    UNLISTED_WORDS,
    _spend_global_free,
    free_account_left,
    free_cap_reason,
    free_daily_cap,
    free_global_daily_cap,
    free_global_left,
    free_left,
    free_trial_cap,
    refund_free_quota,
    spend_free_quota,
)
from stocks.chat.engine.recall import (
    CARD_DAYS,
    LEARN_GRACE,
    LEARN_TIMEOUT,
    MEMORY_USE,
    _unseen,
    card_block,
    criteria_block,
    earlier,
    learn,
    memory_block,
    memory_on,
    note_used,
    recall_on,
    remember,
    talk_about,
    used_by,
    user_memory,
)
from stocks.chat.engine.reply import (
    Reply,
    _keep_byok,
)
from stocks.chat.engine.search import (
    ASKED_TURNS,
    gather_evidence,
    ground_web,
    plan_web,
    topic_ticker,
    web_context,
    web_enabled,
)
from stocks.chat.engine.steps import (
    _merged_sources,
    _unlisted_step,
    live_step,
    trace,
)
from stocks.chat.engine.text import (
    _WRITTEN_CALL,
    CALL_HOLD_CHARS,
    _may_open_call,
    _only_calls,
    close_markdown,
    scrub_written_calls,
    strip_cite_marks,
)
from stocks.chat.engine.titles import (
    TITLE_MAX_CHARS,
    autotitle,
    title_for,
)
from stocks.chat.engine.turn import (
    MARKDOWN_CONTEXT,
    Turn,
    clean_focus,
    view_context,
)
from stocks.web import chat_web, llm, metering

if TYPE_CHECKING:
    from stocks.chat.checkpoint import Checkpoint
    from stocks.web.llm import Provider, ToolCall

__all__ = [
    "ANSWER_KEEP_S",
    "ASKED_TURNS",
    "BYOK_TTL",
    "CALL_HOLD_CHARS",
    "CARD_DAYS",
    "CARD_OPENER",
    "DEEP_UNITS",
    "FREE_CAP_ERRORS",
    "FREE_DAILY_CAP",
    "FREE_ELIGIBILITY",
    "FREE_GLOBAL_DAILY_CAP",
    "FREE_MIN_ACCOUNT_HOURS",
    "FREE_TRIAL_CAP",
    "GLOBAL_FREE_FILE",
    "LEARN_GRACE",
    "LEARN_TIMEOUT",
    "MARKDOWN_CONTEXT",
    "MAX_CONTEXT_MSGS",
    "MEMORY_USE",
    "PAGE_TICKERS",
    "ProposalError",
    "RULES",
    "Reply",
    "SCHEDULED_OPENERS",
    "TITLE_MAX_CHARS",
    "Turn",
    "UNLISTED_WORDS",
    "_answer_key",
    "_busy_siblings",
    "_charge",
    "_fill",
    "_journal",
    "_merged_sources",
    "_pages",
    "_proposed",
    "_routed",
    "_spend_global_free",
    "_thinking",
    "_tr",
    "account_age_hours",
    "action_context",
    "action_reply",
    "answer",
    "answer_stream",
    "answerable",
    "attempts",
    "autotitle",
    "book_snapshot",
    "byok_alive",
    "byok_days_left",
    "byok_fields",
    "can_store_keys",
    "card_block",
    "chain",
    "clean_focus",
    "close_markdown",
    "complete_attempts",
    "criteria_block",
    "decrypt_byok",
    "earlier",
    "enriched_frame",
    "forget_answers",
    "forget_byok",
    "free_account_left",
    "free_allowlist",
    "free_cap_reason",
    "free_daily_cap",
    "free_eligible",
    "free_global_daily_cap",
    "free_global_left",
    "free_left",
    "free_policy",
    "free_trial_cap",
    "gather_evidence",
    "ground_web",
    "in_free_trial",
    "in_parallel",
    "language_rule",
    "learn",
    "live_step",
    "memory_block",
    "memory_on",
    "note_used",
    "pasted_report",
    "persona",
    "plan_web",
    "portfolio_context",
    "prepare",
    "prune_byok",
    "recall_on",
    "recent",
    "refund_free_quota",
    "remember",
    "reporting_currency",
    "resolve_skills",
    "save_byok",
    "scrub_written_calls",
    "sector_exposure",
    "settle_proposal",
    "spend_free_global",
    "spend_free_quota",
    "strip_cite_marks",
    "system_prompt",
    "talk_about",
    "tax_rules",
    "title_for",
    "topic_ticker",
    "trace",
    "undo_proposal",
    "used_by",
    "user_memory",
    "view_context",
    "web_context",
    "web_enabled",
]


def answerable(prefs: dict, atts: list[tuple[Provider, str, str]],
               ) -> list[tuple[Provider, str, str]]:
    """The attempts that could still answer today: the free chain drops out
    once this account's allowance, or the shared pot, is gone.

    `prepare` makes model calls of its own before `_charge` is ever consulted
    -- the action classifier, the skill router, the web planner, the title --
    all on the head of the chain. Left in place, a capped account kept
    spending four to seven operator-funded calls per message and was only
    then told no; the daily cap bounded the answers, not the bill. Checked
    here, not charged: those calls are the cost of a turn the cap already
    priced, and the reader who is out today makes none of them.
    """

    # A key the provider refused minutes ago goes to the back rather than out:
    # the research runs on the head of this list, and leading with a dead key
    # costs the turn its search. Kept at all so a reader with nothing else
    # still gets the provider's own refusal, not a silent "no provider".
    good = [a for a in atts if not llm.rejected(a[0], a[1])]
    atts = good + [a for a in atts if a not in good]
    if not any(p.id == "free" for p, _k, _m in atts):
        return atts
    if free_eligible(prefs) and free_left(prefs) > 0:
        return atts
    return [a for a in atts if a[0].id != "free"]


def prepare(*, prefs: dict, prefs_path: Path, chat_path: Path, watchlist: Path,
            db: Path, message: str, lang: str = "en",
            context: str = "",
            timeout_s: float = 90.0,
            staged_import: str = "",
            on_phase: Callable[[str], None] | None = None,
            view: str = "",
            focus: str = "",
            fence: str = "",
            session_keys: dict[str, str] | None = None,
            confirm_actions: bool = False,
            on_tool: Callable[[dict], None] | None = None,
            on_subagent: Callable[[dict], None] | None = None,
            draws: bool = False,
            thread: str | None = None,
            depth: str = "",
            turn_id: str = "",
            on_plan: Callable[[list[dict]], None] | None = None,
            checkpoint: Checkpoint | None = None,
            brief: str = "",
            ) -> tuple[Turn | None, Reply | None]:
    """Everything before the model: history, provider chain, prompt, evidence.

    Returns the prepared turn, or the Reply that already settles it — an import
    request and an app action (favorite, alert, group) are answered without a
    main-model call at all, and an exhausted provider chain is answered without
    one too. Exactly one of the two is not None.

    `view` is the rendered "Current view" sentence (`view_context`) and `focus`
    the symbol behind it: the first goes into the prompt, the router and the
    action parser — "add this to favourites" has to know what "this" is — and
    the second into the quote lookup and the gather, which fetch what the
    reader is looking at even when the message never names it. `fence` closes
    the prompt's context for a turn on the walkthrough's thread
    (`guide_ai.prompt_fence`). `session_keys` are keys held for this request
    only; see `attempts`.

    `on_tool` is told about the research while it happens, as the tool lines
    `trace` will file: `{id, tool, arg, args}` when a call starts and the same
    with `out` when it returns (`live_step`). The model's own calls are told
    as they run; the fixed pre-flight's, once both have come back.
    `on_plan` is told a deep gather's plan, `[{text, done}]`, each time the
    model sets it.

    `on_subagent` turns on the bull/bear debate (`chat/debate.py`) for a
    question that asks for a decision, and is told each side's lifecycle as it
    runs. Only a caller that can show the two cases passes one: they are two
    more model calls, and a reader who cannot see them should not pay for them.

    `confirm_actions` asks before an app action runs rather than after: the
    detected action is filed as a pending proposal (`Reply.proposal`) and
    nothing is written to the watchlist until the reader approves it — with
    the drawer's button (`settle_proposal`) or by answering "yes" in words,
    which this function settles itself. Off for a headless caller, whose reader
    has no card to press and already said what they wanted.

    `draws` says the caller shows the turn's surfaces, so a message asking for
    a chart gets one drawn under the answer (`chat/charts.py`) and the model is
    told it is there. Off for a headless caller, which has nowhere to draw it.

    `thread` pins the turn to the conversation it was asked in: its history is
    read from there and everything it files is written there, wherever the
    active pointer has moved in the meantime. None is the active one.

    `depth` is how far the research goes (`agent.profile_for`): "fast" or
    "deep" when the reader chose, "" to let the message decide.

    `brief` is the angle the ticker page's "Analyse with AI" asked for
    (`chat/brief.py`) on `focus`: the server writes the instructions the
    button's short sentence stands for — the company's lenses, the reader's
    position, the report dates, the answer's structure — onto the outgoing
    turn, and a full analysis or a bear case runs deep and argued. "" is a
    typed question.
    """
    from stocks.chat import tools
    from stocks.web import auth, llm

    history = auth.load_chat(chat_path, thread)
    history.append({"role": "user", "content": message})

    # A proposal waiting on the turn above, answered in words: "sí" is the
    # button pressed, not a question for a model that would cheerfully reply
    # "done" without having done anything.
    # A ledger proposal is asked on every surface, so it is answered on every
    # surface too; on a headless one ("sí" written) that is the only way to answer.
    held = _open_proposal(history[:-1])
    if held is not None and (confirm_actions
                             or isinstance(history[held]["proposal"].get("book"), dict)):
        said = tools.verdict(message)
        if said is not None:
            return None, _typed_verdict(history, held, said, prefs=prefs,
                                        thread=thread,
                                        chat_path=chat_path,
                                        watchlist=watchlist, lang=lang, db=db,
                                        source="chat")

    # Asked to import: there is nothing to execute and nothing worth asking a
    # model, since the statement itself is what an import needs and this
    # surface cannot receive one. Answered before a provider is even resolved
    # — the model is never given the chance to describe an import that did
    # not happen (the same ban system_prompt states).
    if tools.wants_import(message):
        from stocks.web.i18n import translate

        # `staged_import` names a statement the client is already showing a
        # preview of. Then the step that does work is the button under it, not
        # attaching the file again. A stateless caller has to pass it in.
        note = (
            translate("chat.import_pending_hint", lang, filename=staged_import)
            if staged_import
            else translate("chat.import_needs_file", lang)
        )
        nav = {"page": "import"}
        history.append({"role": "assistant", "content": note,
                        "action": "import", "nav": nav})
        auth.save_chat(history, chat_path, thread)
        return None, Reply(text=note, nav=nav)

    # "Recuerda que…" / "olvida lo de…": the user editing the memory in words.
    # Carried out here, before a provider is even resolved, for the reason the
    # import is: it is a write the app makes, and a model must never be the
    # one saying it happened. A question after the command ("recuerda que
    # tengo 40 años, ¿cuánto en bonos?") still goes on to be answered, with
    # the change carried on the answer.
    learned: list[dict] = []
    order = learnings.command(message)
    if order is not None:
        note, learned = remember(order, prefs=prefs, chat_path=chat_path,
                                 watchlist=watchlist, lang=lang)
        if not order.rest:
            done: dict = {"role": "assistant", "content": note,
                          "action": "memory"}
            if learned:
                done["learned"] = learned
            history.append(done)
            auth.save_chat(history, chat_path, thread)
            return None, Reply(text=note, learned=tuple(learned))

    def settled(reply: Reply) -> tuple[None, Reply]:
        # An early answer below still tells the reader what was saved.
        return None, replace(reply, learned=tuple(learned)) if learned else reply

    def stored(entry: dict) -> dict:
        if learned:
            entry["learned"] = learned
        return entry

    atts = chain(prefs, session_keys)
    if not atts:
        return settled(Reply(error="chat.free_exhausted"))
    # Everything below runs models on `live[0]`; `atts` still goes out whole
    # so `answer` charges and reports the walls exactly as before.
    live = answerable(prefs, atts)
    if not live:
        return settled(_exhausted(prefs, atts, capped=True))
    provider, key, model = live[0]

    # App actions first (favorite / alerts / groups): a deterministic
    # localized confirmation — no main-model call, no free-quota spend.
    above = history[:-1]
    if tools.maybe_action(message) or tools.continues(message, above):
        act = tools.detect(provider, key, message,
                           "\n".join(filter(None, (
                               view + action_context(watchlist),
                               tools.earlier_turns(above)))),
                           fallbacks=[(p, k) for p, k, _m in live[1:]])
        if (act is not None and act.kind in tools.PROPOSABLE
                and tools.asks_more(message)):
            # A question rides on the request: the answer takes both, and its
            # research drafts the same card (`propose_action`) under it.
            act = None
        if act is not None and tools.is_book(act.kind):
            reply = _book_turn(act, history=history, prefs=prefs, db=db,
                               chat_path=chat_path, lang=lang,
                               typed=not confirm_actions, stored=stored,
                               thread=thread)
            if not reply.error:
                autotitle(chat_path, provider, key, history, lang, thread)
                _keep_byok(prefs, prefs_path)
                return settled(replace(reply, provider_id=provider.id))
            act = None
        if act is not None and confirm_actions:
            offer = _proposal(act)
            note = tools.proposal(act, lambda k, **kw: _tr(k, lang, **kw))
            tid = turn_id or secrets.token_hex(6)
            history.append(stored({"role": "assistant", "content": note,
                                   "action": act.kind, "proposal": offer,
                                   "id": tid, "provider": provider.id}))
            auth.save_chat(history, chat_path, thread)
            autotitle(chat_path, provider, key, history, lang, thread)
            _keep_byok(prefs, prefs_path)
            obs.event("chat.action_proposed", action=act.kind)
            return settled(Reply(text=note, provider_id=provider.id,
                                 proposal=dict(offer), turn_id=tid))
        if act is not None:
            try:
                tools.execute(act, watchlist,
                              journal_path=journal.path_for(chat_path))
            except Exception as exc:
                obs.warn("chat.engine.action_failed", action=act.kind,
                         error_type=type(exc).__name__, error=str(exc)[:300])
                act = None
        if act is not None:
            note = action_reply(act, lang)
            # Rateable like an answer (`_book_turn` says why).
            tid = turn_id or secrets.token_hex(6)
            history.append(stored({"role": "assistant", "content": note,
                                   "action": act.kind, "id": tid,
                                   "provider": provider.id}))
            auth.save_chat(history, chat_path, thread)
            autotitle(chat_path, provider, key, history, lang, thread)
            _keep_byok(prefs, prefs_path)
            return settled(Reply(text=note, provider_id=provider.id,
                                 turn_id=tid))

    # Skill routing and the lookup are independent, so they run at the same
    # time rather than stacking their latencies. The lookup is the model's own
    # when the provider has tool use (chat/agent.py) and the fixed
    # search+quotes guess otherwise — or when the gather never got to run.
    # The phases the panel names while a turn is built (`chat.work_*`). Told
    # to the caller rather than drawn: this is the engine, and only a caller
    # knows whether "gathering" is a line in a bubble, a frame on a stream or
    # nothing at all.
    say = on_phase or (lambda _phase: None)
    told = on_tool or (lambda _step: None)

    def watch(cid: str, call: ToolCall, done: bool) -> None:
        told(live_step(cid, call, lang, done))

    # Started before the research and never waited on here: it reads only the
    # user's words, and the answer does not need it (`learn`). A memory
    # command already wrote what the message asked to keep.
    learning = None if order is not None else learn(
        prefs, chat_path, history, watchlist, session_keys)
    # Beside the research too, and waited for only once it is back
    # (`chat/guard.py`): a question in scope pays nothing for the check.
    vetting = guard.start(provider, key, message)

    def watching() -> None:
        if vetting is not None:
            vetting.check()
        stopping.check()

    msgs = recent(history)
    # The button's brief rides on the turn before the research starts, so the
    # gather reads which KPIs the answer will need.
    asked_for = None
    if brief and focus:
        try:
            asked_for = ticker_brief.build(brief, focus, watchlist=watchlist,
                                           db=db, currency=reporting_currency(prefs))
        except Exception as exc:  # noqa: BLE001 — a press with less context is still a question
            obs.warn("chat.brief_failed", angle=brief, ticker=focus,
                     error_type=type(exc).__name__, error=str(exc)[:200])
    if asked_for is not None:
        msgs[-1]["content"] += asked_for.text
        # Filed on the stored turn, so a regenerate asks the same brief.
        history[-1]["brief"] = {"angle": asked_for.angle, "ticker": focus}
        obs.event("chat.brief", angle=asked_for.angle, ticker=focus,
                  skills=",".join(asked_for.skills) or "-",
                  dossier="kept" if asked_for.dossier else
                  "draft" if asked_for.needs_dossier else "-")
    say("gathering")
    # A question that is research gets the deep gather: more rounds, the
    # answering model choosing what to read, the app's engines as tools. It
    # sets the wait for everything that runs beside it, since the turn cannot
    # go on before the research is back.
    # A caller's `timeout_s` has always bounded the quick gather too; a deep
    # one may take longer than that, and the lookups beside it wait as long.
    profile = agent.profile_for(
        message, depth or ("deep" if asked_for is not None and asked_for.deep
                           else ""))
    if (profile is agent.DEEP and provider.id == "free"
            and free_account_left(prefs) < DEEP_UNITS):
        # The research runs before the answer is charged, so what it may
        # cost is settled here: a reader with one unit left gets the quick
        # gather and is charged one, not a deep one the wall then refuses.
        profile = agent.FAST
        obs.event("chat.deep_downgraded", left=free_account_left(prefs))
    researched = max(timeout_s, profile.timeout)
    known = market.watchlist_names(watchlist)
    # Read once, and before the gather only when a typed symbol needs it.
    book = functools.cache(
        lambda: portfolio_context(watchlist, db, reporting_currency(prefs)))
    # A short question about a symbol nobody lists has nothing to research:
    # the gather would search for two minutes and find nothing (ZXQW took
    # 1 m 58 s). One search says so, and the answer goes out on that alone.
    nowhere = ({} if focus or asked_for is not None
               or len(message.split()) > UNLISTED_WORDS
               else market.unlisted(message, known, book))
    if nowhere:
        obs.event("chat.unlisted", symbols=",".join(nowhere))
        told({"id": "tool_unlisted", **_unlisted_step(nowhere, lang), "args": {}})
    try:
        # A pasted list asks about all of it; the one-trade cards stay off.
        one = not pasted_report(message)
        (skills, evidence, sale, chart, mix, losses, moved, ahead, paid,
         planned, drafted) = in_parallel(
            lambda: (_brief_skills(prefs, asked_for) if asked_for is not None
                     else resolve_skills(prefs, provider, key, history,
                                         context=context + view)),
            lambda: None if nowhere else gather_evidence(
                prefs, provider, key, msgs, watchlist, db, chat_path,
                timeout=researched, focus=focus,
                on_tool=watch if on_tool else None, profile=profile,
                model=model, prefs_path=prefs_path, proposes=confirm_actions,
                on_plan=on_plan, checkpoint=checkpoint),
            lambda: (_simulate_sale(message, watchlist, db, prefs_path, focus,
                                    lang, told) if one else None),
            lambda: (_chart(message, prefs, watchlist, db, focus, lang, told)
                     if draws and one else None),
            lambda: (_allocation(message, prefs, db, lang, told)
                     if draws and one else None),
            lambda: _harvest(message, db, prefs_path, lang, told) if one else None,
            lambda: (_rebalance(message, watchlist, db, prefs_path, focus, lang,
                                told) if one else None),
            lambda: _reports_ahead(message, watchlist, db, lang, told),
            lambda: _income(message, db, prefs_path, lang, told),
            lambda: _plan_builder(message, prefs, db, lang, told) if one else None,
            # A company met for the first time this month gets its notes
            # drafted beside the research, on the cheapest model.
            lambda: (ticker_brief.draft_dossier(provider, key, asked_for.facts)
                     if asked_for is not None and asked_for.needs_dossier
                     else None),
            timeout=researched + 5.0,
            # A stopped turn stops waiting here (`chat/stopping.py`); the gather
            # beside it has already stopped starting things. So does a message
            # the guard refused.
            tick=watching,
        )
        hard = getattr(skills, "hard", None)
        skills = skills or []
        evidence = evidence or agent.Evidence(ok=False)
        hits, quotes, pages = [], [], ""
        # The reader's own report dates or dividends are the app's to give:
        # the web has nothing to add to them and a search costs the turn its
        # slowest seconds (local review 2026-10-30: three and a half minutes
        # for the earnings calendar, its search "BKNG ¿Qué empresas…").
        # So is a plan built from the reader's own answers.
        own = (isinstance(ahead, reports.Ahead) or isinstance(paid, income.Income)
               or isinstance(planned, plan_builder.Known))
        if nowhere:
            pass
        elif not evidence.ok:
            if not own:
                say("searching")
            # The lookup may have just found the head's key refused: the planner
            # then runs on the next candidate that is not, or it fails the same
            # way and the search falls to keywords.
            scout, scout_key = next(
                ((p, k) for p, k, _m in live if not llm.rejected(p, k)),
                (provider, key))
            from stocks.chat import knowledge

            hits, quotes, docs = in_parallel(
                lambda: [] if own else ground_web(prefs, scout, scout_key,
                                                  history, view),
                lambda: market.lookup_for(message, watchlist, focus=focus,
                                          lang=lang, earlier=above),
                # The app's own documents: with no tool loop the model never
                # reached them, and "how do I undo an import?" was answered
                # with a delete button that does not exist (prod eval
                # 2026-10-29). The search abstains on anything else.
                lambda: knowledge.lookup(message),
                timeout=timeout_s,
                tick=watching,
            )
            hits, quotes = hits or [], quotes or []
            if docs:
                # Filed as the gather's own lookup would be, so the material,
                # the steps and the cited sources all read it the same way.
                evidence.calls.append(llm.ToolCall(
                    "lookup_knowledge", {"query": message}, knowledge.block(docs)))
            if losses is None and (owed := _tax_year(
                    message, watchlist, db, prefs, prefs_path)):
                evidence.calls.append(owed)
            # No loop to watch here: the search and the quotes are told once
            # both have landed, already finished.
            for n, line in enumerate(trace(evidence, hits, quotes, lang)):
                told({"id": f"tool_pre{n}", **line, "args": {}})
            pages = _pages(message, quotes, watchlist, db, prefs, lang, told,
                           timeout_s, watching)
        else:
            # Searching is the default, and the model's own lookup skipped it.
            # Keywords decide instead — no second planner call — so small talk,
            # a definition or a question about the reader's own book still goes
            # without, and everything else reads the web.
            queries = (chat_web.heuristic_queries(message, web_context(history, view))
                       if web_enabled() and not own and not any(
                           c.name in ("search_web", "read_page")
                           for c in evidence.calls) else [])
            # So is a price: "Dámelos" after "the prices are wrong" went out
            # with no tool called and four prices from memory (prod
            # 2026-11-02). The fixed lookup quotes what it is about.
            quoting = not any(c.name == "get_quotes" for c in evidence.calls)
            if queries:
                say("searching")
            if queries or quoting:
                hits, quotes = in_parallel(
                    lambda: chat_web.collect(queries, message) if queries else [],
                    lambda: (market.lookup_for(message, watchlist, focus=focus,
                                               lang=lang, earlier=above)
                             if quoting else []),
                    timeout=timeout_s, tick=watching)
                hits, quotes = hits or [], quotes or []
                for n, line in enumerate(trace(None, hits, quotes, lang)):
                    told({"id": f"tool_pre{n}", **line, "args": {}})
        if vetting is not None and (said := vetting.refusal()):
            raise guard.Blocked(said)
    except guard.Blocked as refused:
        return settled(_refused(refused.refusal, history, chat_path, thread,
                                turn_id, lang, provider.id))
    recalled_notes, recalled = earlier(prefs, chat_path, message, known)
    note_used(prefs, chat_path, message, known)
    system = system_prompt(
        auth.load_profile(prefs),
        # The turn's own part: where the reader is, what the surface draws
        # for them, and — on the walkthrough's thread only — the fence.
        context + view + (charts.PROMPT if draws else "") + fence,
        skills,
        lang,
        memories=memory_block(prefs, chat_path) + card_block(chat_path)
        + criteria_block(chat_path),
        # What they hold and how it is taxed: its own cache part, since it
        # changes when prices do and the view changes when the reader moves.
        book=book() + tax_rules(prefs),
        # The reader's own key runs a large model, and the large models keep a
        # rule wherever it is said; the free chain's are told it last.
        rules_first=bool(getattr(provider, "needs_key", False)),
    )
    # Everything fetched rides on the outgoing copy of the user turn, not the
    # system prompt — the stored history keeps the user's own text.
    if evidence:
        msgs[-1]["content"] = evidence.augment(msgs[-1]["content"])
    msgs[-1]["content"] = memory.augment(msgs[-1]["content"], recalled_notes)
    if hits:
        msgs[-1]["content"] = chat_web.augment(msgs[-1]["content"], hits)
    if quotes:
        msgs[-1]["content"] = market.augment(msgs[-1]["content"], quotes, lang,
                                             held=held_in(book()))
    msgs[-1]["content"] += pages
    msgs[-1]["content"] += market.unlisted_block(nowhere)
    if asked_for is not None:
        notes = asked_for.dossier or (
            drafted if isinstance(drafted, ticker_brief.Dossier) else None)
        msgs[-1]["content"] += ticker_brief.dossier_block(notes)
    if isinstance(sale, whatif.Scenario):
        msgs[-1]["content"] += sale.line(lang)
    if isinstance(chart, charts.Chart):
        msgs[-1]["content"] += chart.line()
    for found in (mix, losses, moved, ahead, paid, planned):
        if isinstance(found, (allocation.Mix, harvest.Harvest, rebalance.Reweigh,
                              reports.Ahead, income.Income, plan_builder.Known)):
            msgs[-1]["content"] += found.line(lang)
    # Last, after augmentation: the page extracts and quotes just stapled onto
    # the newest turn are the biggest thing in the request (chat/tokens.py).
    msgs = tokens.fit(msgs, system=system)

    # Argued off the fitted messages — the analysts read what the answer
    # reads, and a cheap model's window is the smaller one — then the cases
    # join the question and the whole is fitted again.
    sides: list[dict] = []
    stopping.check()
    if on_subagent is not None and (
            debate.wants(message) or (asked_for is not None and asked_for.debate)):
        say("debating")
        sides = debate.run(provider, key, msgs, lang, on_event=on_subagent,
                           timeout=min(timeout_s, debate.TIMEOUT))
        if sides:
            msgs[-1]["content"] += debate.brief(sides)
            msgs = tokens.fit(msgs, system=system)

    routed = _routed(atts, live[0], profile=profile, hard=hard,
                     argued=bool(sides) or asked_for is not None)
    say("writing")
    steps = trace(evidence, hits, quotes, lang)
    if nowhere:
        steps.append(_unlisted_step(nowhere, lang))
    activities: list[dict] = []
    if isinstance(sale, whatif.Scenario):
        steps.append(_sale_step(sale, lang))
        activities.append(a2ui.activity(
            whatif.SURFACE_ID,
            whatif.surface(sale, lambda k, **kw: _tr(k, lang, **kw), lang),
        ))
    if isinstance(chart, charts.Chart):
        steps.append(_chart_step(chart, lang))
        activities.append(a2ui.activity(
            charts.SURFACE_ID,
            charts.surface(chart, lambda k, **kw: _tr(k, lang, **kw), lang),
        ))
    if isinstance(mix, allocation.Mix):
        steps.append(_mix_step(mix, lang))
        activities.append(a2ui.activity(
            allocation.SURFACE_ID,
            allocation.surface(mix, lambda k, **kw: _tr(k, lang, **kw), lang),
        ))
    if isinstance(ahead, reports.Ahead):
        steps.append(_reports_step(ahead, lang))
    if isinstance(paid, income.Income):
        steps.append(_income_step(paid, lang))
    if isinstance(losses, harvest.Harvest):
        steps.append(_harvest_step(losses, lang))
        # Nothing to draw when there is nothing to realise: the prose says so.
        if losses.candidates:
            activities.append(a2ui.activity(
                harvest.SURFACE_ID,
                harvest.surface(losses, lambda k, **kw: _tr(k, lang, **kw)),
            ))
    if isinstance(moved, rebalance.Reweigh):
        steps.append(_rebalance_step(moved, lang))
        activities.append(a2ui.activity(
            rebalance.SURFACE_ID,
            rebalance.surface(moved, lambda k, **kw: _tr(k, lang, **kw), lang),
        ))
    if isinstance(planned, plan_builder.Known):
        steps.append(_plan_step(planned, lang))
        activities.append(a2ui.activity(
            plan_builder.SURFACE_ID,
            plan_builder.surface(planned, lambda k, **kw: _tr(k, lang, **kw)),
        ))
    offered = _proposed(evidence) if confirm_actions else None
    return Turn(
        history=history,
        attempts=routed or atts,
        system=system,
        messages=msgs,
        skills=list(skills),
        sources=_merged_sources(chat_web.sources(hits), evidence.sources()),
        steps=steps,
        lang=lang,
        activities=activities,
        debate=sides,
        learned=learned,
        recalled=recalled,
        learning=learning,
        thread=thread,
        profile=profile.name,
        route="light" if routed else "",
        id=turn_id or secrets.token_hex(6),
        proposal=offered,
        rules_for=(_rules_asked(message, watchlist, focus)
                   if confirm_actions and offered is None else ""),
    ), None


def _routed(atts: list[tuple[Provider, str, str]],
            head: tuple[Provider, str, str], *, profile: agent.Profile,
            hard: bool | None, argued: bool) -> list[tuple[Provider, str, str]]:
    """The chain with the head provider's cheapest model asked first, when the
    question is an easy one; [] to leave it as it is.

    The reader's model is a ceiling, not a floor: a figure, a definition or a
    quick look-up reads the same from the small model, in seconds instead of
    the minute a large one spends thinking (prod 2026-10-29: flash 94-164 s,
    lite 5-20 s), and the reader's model is still next when it fails. Only on
    the router's own word (`chat_skills.Pick.hard` is False): a router that
    failed or said nothing, a deep gather, a debate or a ticker brief keeps
    the reader's model. The keyless chain picks its own models."""
    provider, key, model = head
    light = getattr(provider, "classifier_model", "")
    if (hard is not False or argued or profile is not agent.FAST
            or not getattr(provider, "needs_key", False) or not light
            or light == (model or provider.default_model)):
        return []
    return [(provider, key, light)] + list(atts)


def _light(turn: Turn, provider: Provider, model: str) -> bool:
    """Whether this attempt is the cheap model `_routed` put first: when it
    fails, the reader's own model is next anyway, not the provider's others."""
    if not turn.route or not turn.attempts:
        return False
    first, _key, light = turn.attempts[0]
    return first is provider and light == model


def _thinking(turn: Turn, provider: Provider, model: str) -> str:
    """How long the answering model reasons before it writes (`llm.thinking`):
    the least on the cheapest model, a little on a quick turn, more on a deep
    one, whose evidence takes weighing. Never the model's own default, which
    on Gemini's flash is the slow part of the turn."""
    if model == getattr(provider, "classifier_model", ""):
        return "minimal"
    return "medium" if turn.profile == "deep" else "low"


def _charge(prefs: dict, prefs_path: Path, provider: Provider,
            units: int = 1) -> bool:
    """Take this attempt's free units up front. False when today's are gone.

    Charged before the call rather than after it because the shared pot is
    what a runaway caller drains, and a unit taken for a call that then fails
    is refunded by `_refund` — the same order the web panel uses.
    """
    if provider.id != "free":
        return True
    from stocks import accounts
    from stocks.web import auth

    # Checked against the file, not the dict this turn read minutes ago, and
    # under the file's lock: two turns of one account racing for the last unit
    # would otherwise both see it free.
    with accounts.prefs_lock(prefs_path):
        _fresh_free_count(prefs, prefs_path)
        if not spend_free_quota(prefs, units):
            return False
        auth.save_prefs(prefs, prefs_path)
    return True


def _fresh_free_count(prefs: dict, prefs_path: Path) -> None:
    """Bring today's counter in `prefs` up to what the file holds now."""
    from stocks import accounts

    key = f"free_msgs::{time.strftime('%Y-%m-%d')}"
    try:
        held = int(accounts.stored_prefs(prefs_path).get(key, 0) or 0)
    except (TypeError, ValueError):
        return
    prefs[key] = held
    if isinstance(prefs, accounts.LoadedPrefs):
        prefs.base[key] = held


def _refund(prefs: dict, prefs_path: Path, provider: Provider,
            units: int = 1) -> None:
    """Give back the units taken for a call that never answered."""
    if provider.id != "free":
        return
    from stocks.web import auth

    refund_free_quota(prefs, units)
    auth.save_prefs(prefs, prefs_path)


def _provider_failed(exc: Exception, provider: Provider, model: str,
                     key: str = "") -> None:
    """Logged because the user only ever sees chat.api_error; without this the
    reason for a dead chain (retired model, free tier gone paid) is
    unrecoverable. A refused key is also remembered (`llm.note_failure`), so
    the next turn's research skips it."""

    llm.note_failure(provider, key, exc)
    obs.warn("chat.provider_failed", provider=provider.id, model=model,
             error_type=type(exc).__name__, error=str(exc)[:300])


def _busy_siblings(exc: Exception, provider: Provider, key: str,
                   tried: set[tuple[str, str]],
                   ) -> list[tuple[Provider, str, str]]:
    """The provider's other models on the same key, when `exc` says the one
    asked is saturated (`chat.provider_busy`) — tried before the next provider.

    Prod 2026-10-29: gemini-flash-latest answered 503 "high demand" while
    gemini-3.6-flash and flash-lite answered the same key at once; the turn
    went to the free chain instead, another model the reader never picked and
    a unit of an allowance they may not have left. Only saturation: a refused
    key or an empty balance is refused by every model alike, and a timeout
    already spent the turn's patience. `tried` holds the (provider, model)
    pairs asked or queued this turn, so a sibling that is busy too never
    queues one twice; the ones returned are added to it.
    """
    if not getattr(provider, "needs_key", False) or not key:
        return []
    try:
        busy = provider.error_key(exc) == "chat.provider_busy"
    except Exception:  # an SDK missing on this host: no verdict, no siblings
        return []
    if not busy:
        return []
    out = [(provider, key, m) for m in getattr(provider, "models", ())
           if (provider.id, m) not in tried]
    tried.update((provider.id, m) for _p, _k, m in out)
    if out:
        obs.warn("chat.provider_busy_sibling", provider=provider.id,
                 models=[m for _p, _k, m in out])
    return out


def _record(turn: Turn, text: str, provider: Provider, model: str, key: str, *,
            prefs: dict, prefs_path: Path, chat_path: Path,
            polish: Callable[[dict], None] | None = None,
            grace: float | None = None) -> Reply:
    """Store a served answer and build the Reply both callers hand back.

    `polish` edits the entry before it is written — the walkthrough's jump
    marker is scrubbed out of the text and filed as `guide_goto` there
    (chat/guide_ai.py). Before the write, not after: a second save to move a
    marker would race the next turn, and the Reply is built from what was
    stored, so the client and a reload read the same words.

    `grace` is how long the answer waits for this question's memory read
    (`learn`) still out — LEARN_GRACE unless the caller can afford more.
    """
    from stocks.web import auth

    # What was learned unasked rides on the answer: this question's if its
    # read is done (a moment's grace, it is usually ahead of the answer), and
    # an earlier one's that finished after its own answer was stored.
    if turn.learning is not None:
        turn.learning.wait(LEARN_GRACE if grace is None else grace)
    turn.learned = [*turn.learned, *_unseen(chat_path)]
    # `id` is what a rating names the turn by (`rate_turn`); `provider` is who
    # wrote it, which a thumbs-down needs and the turn never said before.
    text = scrub_written_calls(strip_cite_marks(text))
    if guard.leaked(text, system_prompt({}, "")):
        # The fixed instructions, repeated back (`chat/guard.py`). Under
        # `block` the stored and finished answer is the refusal instead; the
        # words already streamed are replaced by it on the reader's screen.
        obs.warn("chat.guard_leak", provider=provider.id, model=model)
        if guard.mode() == "block":
            text = _tr("chat.guard_refusal", turn.lang)
    entry: dict = {"role": "assistant", "content": text,
                   "id": turn.id, "provider": provider.id}
    if turn.skills:
        entry["skills"] = list(turn.skills)
    if turn.sources:
        entry["web"] = turn.sources
    if turn.steps:
        entry["steps"] = list(turn.steps)
    if turn.activities:
        entry["activities"] = list(turn.activities)
    if turn.debate:
        entry["debate"] = list(turn.debate)
    if turn.learned:
        entry["learned"] = list(turn.learned)
    if turn.recalled:
        entry["recalled"] = list(turn.recalled)
    if turn.proposal is None and turn.rules_for:
        try:
            turn.proposal = _drafted_rules(turn.rules_for, text, provider, key)
        except Exception as exc:  # a card is extra; the answer still lands
            obs.warn("chat.rules_draft_failed", error_type=type(exc).__name__,
                     error=str(exc)[:300])
    if turn.proposal is not None:
        entry["proposal"] = turn.proposal
        obs.event("chat.action_proposed", action=turn.proposal["kind"],
                  by="agent")
    if polish is not None:
        polish(entry)
        text = str(entry.get("content") or "")
    turn.history.append(entry)
    auth.save_chat(turn.history, chat_path, turn.thread)
    autotitle(chat_path, provider, key, turn.history, turn.lang, turn.thread)
    _keep_byok(prefs, prefs_path)
    obs.event("chat.answered", provider=provider.id, model=model,
              chars=len(text), skills=list(turn.skills),
              web_sources=len(turn.sources))
    return Reply(text=text, skills=tuple(turn.skills),
                 sources=tuple(turn.sources), provider_id=provider.id,
                 steps=tuple(turn.steps), activities=tuple(turn.activities),
                 debate=tuple(turn.debate), learned=tuple(turn.learned),
                 recalled=tuple(turn.recalled), turn_id=entry["id"],
                 proposal=dict(turn.proposal) if turn.proposal else None)


def _refused(text: str, history: list[dict], chat_path: Path,
             thread: str | None, turn_id: str, lang: str,
             provider_id: str) -> Reply:
    """File and return the guard's refusal (`chat/guard.py`) as the answer:
    the reader sees why nothing else came, and the thread keeps it."""
    from stocks.web import auth

    text = text or _tr("chat.guard_refusal", lang)
    tid = turn_id or secrets.token_hex(6)
    history.append({"role": "assistant", "content": text, "action": "refused",
                    "id": tid, "provider": provider_id})
    auth.save_chat(history, chat_path, thread)
    obs.event("chat.refused")
    return Reply(text=text, provider_id=provider_id, turn_id=tid)


# ------------------------------------------------------------- kept answers

# The same question asked again on the same book: the reader sent it twice,
# opened a new thread to ask it there, or the bot and the web asked it a
# minute apart. A prompt that is byte for byte the last one — persona, book
# at the same prices, the same evidence — gets the answer it got then,
# without a model call. Minutes, not hours: a repeat later than that is
# asking because something moved.
ANSWER_KEEP_S = 600.0
_KEPT_ANSWERS_MAX = 64
# key -> (kept at, owner, provider id, model, text)
_kept_answers: OrderedDict[str, tuple[float, str, str, str, str]] = OrderedDict()
_kept_lock = threading.Lock()


def _answer_key(turn: Turn, chat_path: Path) -> str:
    """What a kept answer is found by; "" when this turn's answer is not one
    to keep: it proposes a change, draws a card, carries a debate, or was
    taught something — each its own event, never a repeat."""
    if (turn.proposal or turn.activities or turn.debate or turn.learned
            or turn.rules_for):
        return ""
    blob = json.dumps([str(chat_path), str(turn.system), turn.messages],
                      ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _kept_answer(turn: Turn, kept_key: str
                 ) -> tuple[Provider, str, str, str] | None:
    """(provider, key, model, text) of the answer this very prompt got
    minutes ago, when its provider is still on this turn's chain."""
    if not kept_key:
        return None
    with _kept_lock:
        hit = _kept_answers.get(kept_key)
        if hit is None:
            return None
        if time.monotonic() - hit[0] >= ANSWER_KEEP_S:
            del _kept_answers[kept_key]
            return None
    _at, _owner, pid, model, text = hit
    for provider, key, _m in turn.attempts:
        if provider.id == pid:
            obs.event("chat.answer_kept", provider=pid, model=model,
                      age_s=round(time.monotonic() - hit[0]))
            return provider, key, model, text
    return None


def _keep_answer(kept_key: str, chat_path: Path, provider: Provider,
                 model: str, text: str) -> None:
    if not kept_key:
        return
    with _kept_lock:
        _kept_answers.pop(kept_key, None)
        _kept_answers[kept_key] = (time.monotonic(), str(chat_path),
                                   provider.id, model, text)
        while len(_kept_answers) > _KEPT_ANSWERS_MAX:
            _kept_answers.popitem(last=False)


def forget_answers(chat_path: Path) -> None:
    """Drop the answers kept for this account's chat: a regenerate asks the
    same prompt again precisely to get another answer."""
    owner = str(chat_path)
    with _kept_lock:
        for k in [k for k, v in _kept_answers.items() if v[1] == owner]:
            del _kept_answers[k]


def _exhausted(prefs: dict, atts: list[tuple[Provider, str, str]],
               capped: bool, learned: tuple[dict, ...] = ()) -> Reply:
    """The Reply for a chain that ran out — and which wall it hit.

    `learned` is a memory command the turn already carried out: it stands
    whether or not anybody answered the question after it, so the refusal
    still says what was saved (and still offers the undo)."""
    obs.warn("chat.failed", reason="free_cap" if capped else "api_error",
             providers=[p.id for p, _k, _m in atts])
    if not capped:
        return Reply(error="chat.api_error", learned=learned)
    # Which wall: this account's allowance (back tomorrow), the shared pot
    # (everyone's, and possibly back within the hour), or a policy that never
    # let this account near the chain — telling that last reader they spent
    # messages they never sent is how a refusal becomes a bug report.
    return Reply(error=FREE_CAP_ERRORS[free_cap_reason(prefs)], learned=learned)


def _log_cost(meter: metering.Meter, turn: Turn | None) -> None:
    """One line per turn with what its model calls spent: tokens by step and
    dollars (None when a model on it is unpriced). The question it answers is
    what a deep turn costs against a fast one:
        stocks logs stats --event chat.cost --by profile
    and, with the skills the turn loaded (names only), `stocks logs skills`
    crosses it with the thumbs: which skill costs and which one is liked."""
    if not meter.uses:
        return
    obs.event("chat.cost", profile=turn.profile if turn else "",
              route=turn.route if turn else "",
              skills=list(turn.skills) if turn else [],
              models=meter.models(), tokens=meter.tokens(),
              cached=meter.cached(), cache_write=meter.cache_write(),
              steps=meter.by_step(), usd=meter.usd())


def answer(*, prefs: dict, prefs_path: Path, chat_path: Path,
           watchlist: Path, db: Path, message: str, lang: str = "en",
           context: str = "", timeout_s: float = 90.0,
           staged_import: str = "", view: str = "", focus: str = "",
           fence: str = "", session_keys: dict[str, str] | None = None,
           polish: Callable[[dict], None] | None = None,
           learn_grace: float | None = None) -> Reply:
    """One complete chat turn: load history, resolve provider/skills, ask,
    append the completed pair, save. Mirrors the web panel's turn logic.

    On any failure the history is left unsaved (no dangling user turn) and
    the Reply carries a locale key: chat.free_cap, chat.free_exhausted or
    chat.api_error. `learn_grace` overrides how long the answer waits for
    what the message is teaching the memory (`_record`).
    """
    meter = metering.Meter()
    turn = None
    turn_id = secrets.token_hex(6)
    try:
        with metering.metered(meter), obs.context(turn=turn_id):
            turn, reply = _answer(
                prefs=prefs, prefs_path=prefs_path, chat_path=chat_path,
                watchlist=watchlist, db=db, message=message, lang=lang,
                context=context, timeout_s=timeout_s,
                staged_import=staged_import, view=view, focus=focus,
                fence=fence, session_keys=session_keys, polish=polish,
                learn_grace=learn_grace, turn_id=turn_id)
            return reply
    finally:
        with obs.context(turn=turn_id):
            _log_cost(meter, turn)


def _answer(*, prefs: dict, prefs_path: Path, chat_path: Path,
            watchlist: Path, db: Path, message: str, lang: str,
            context: str, timeout_s: float, staged_import: str, view: str,
            focus: str, fence: str, session_keys: dict[str, str] | None,
            polish: Callable[[dict], None] | None,
            learn_grace: float | None,
            turn_id: str) -> tuple[Turn | None, Reply]:
    """`answer`'s body, handing back the turn it built for the cost line."""
    turn, settled = prepare(prefs=prefs, prefs_path=prefs_path,
                            chat_path=chat_path, watchlist=watchlist, db=db,
                            message=message, lang=lang, context=context,
                            timeout_s=timeout_s, staged_import=staged_import,
                            view=view, focus=focus, fence=fence,
                            session_keys=session_keys, turn_id=turn_id)
    if turn is None:
        assert settled is not None
        return None, settled

    kept_key = _answer_key(turn, chat_path)
    if (kept := _kept_answer(turn, kept_key)) is not None:
        provider, key, model, text = kept
        return turn, _record(turn, text, provider, model, key, prefs=prefs,
                             prefs_path=prefs_path, chat_path=chat_path,
                             polish=polish, grace=learn_grace)
    capped = False
    pending = list(turn.attempts)
    tried: set[tuple[str, str]] = set()
    missed: list[str] = []  # for `llm.byok_to_free`
    while pending:
        provider, key, model = pending.pop(0)
        model = model or provider.default_model
        tried.add((provider.id, model))
        if not _charge(prefs, prefs_path, provider, turn.units):
            capped = True
            continue
        # No `with`: executor shutdown would block on a hung worker and defeat
        # the timeout. The thread dies with the short-lived process.
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            with llm.thinking(_thinking(turn, provider, model)):
                ask = metering.bound(provider.complete, step="answer")
            future = pool.submit(ask, key, model, turn.system, turn.messages)
            text = (future.result(timeout=timeout_s) or "").strip()
        except Exception as exc:
            # timeout, bad key, rate limit — next candidate. The unit was taken
            # before the call that never answered, so it goes back.
            _provider_failed(exc, provider, model, key)
            missed.append(f"{provider.id}:{type(exc).__name__}")
            _refund(prefs, prefs_path, provider, turn.units)
            if not _light(turn, provider, model):
                pending[:0] = _busy_siblings(exc, provider, key, tried)
            continue
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if _only_calls(text, provider, model):
            missed.append(f"{provider.id}:rejected")
            _refund(prefs, prefs_path, provider, turn.units)
            continue
        if text:
            if provider.id == "free":
                note_free_fallback("chat", prefs, turn.attempts, missed)
            _keep_answer(kept_key, chat_path, provider, model, text)
            return turn, _record(turn, text, provider, model, key, prefs=prefs,
                                 prefs_path=prefs_path, chat_path=chat_path,
                                 polish=polish, grace=learn_grace)

    return turn, _exhausted(prefs, turn.attempts, capped, tuple(turn.learned))


def answer_stream(*, prefs: dict, prefs_path: Path, chat_path: Path,
                  watchlist: Path, db: Path, message: str, lang: str = "en",
                  context: str = "",
                  timeout_s: float = 90.0,
                  staged_import: str = "", view: str = "", focus: str = "",
                  fence: str = "",
                  session_keys: dict[str, str] | None = None,
                  polish: Callable[[dict], None] | None = None,
                  confirm_actions: bool = False,
                  debating: bool = False,
                  draws: bool = False,
                  thread: str | None = None,
                  depth: str = "",
                  checkpoint: Checkpoint | None = None,
                  brief: str = "",
                  ) -> Iterator[tuple[str, object]]:
    """The same turn, handed over as the model writes it.

    Yields `("phase", key)` while the turn is being built — `gathering`,
    `searching`, `writing`, the panel's own `chat.work_*` lines — and
    `("tool", step)` for each piece of research as it starts and returns
    (`live_step`), `("plan", [{text, done}])` each time a deep gather sets
    its plan, `("subagent", event)` for the bull/bear debate when
    `debating` (`chat/debate.py`) — and, when `draws`, a price chart among
    the turn's surfaces for a message that asks for one (`prepare`) —
    `("recalled", [...])` once the turn is built if earlier conversations
    were quoted onto it (`earlier`), then
    `("meta", {...})` once a provider has actually started answering,
    then `("text", chunk)` per piece, and always exactly one `("done", Reply)`
    last — so a caller can render progressively and still get the same Reply
    `answer()` would have returned, including its error key.

    A provider that dies *before* its first chunk falls through to the next
    candidate, exactly as `answer()` does. One that dies *after* does not: the
    reader has already seen those words, and swapping in another model's
    answer mid-paragraph reads as corruption. What arrived is kept and stored,
    so the thread does not lose it.

    `thread`, `depth` and `brief` are `prepare`'s: the conversation the
    answer is stored in, how far its research goes, and the ticker page's
    requested angle.
    """
    meter = metering.Meter()
    built: dict = {}
    turn_id = secrets.token_hex(6)
    # Set however this stream ends — finished, failed, or closed by Stop or a
    # reader's abort — so research still running for it stops starting
    # things (`chat/stopping.py`).
    halt = threading.Event()
    try:
        yield from metering.iterate(_answer_stream(
            prefs=prefs, prefs_path=prefs_path, chat_path=chat_path,
            watchlist=watchlist, db=db, message=message, lang=lang,
            context=context, timeout_s=timeout_s, staged_import=staged_import,
            view=view, focus=focus, fence=fence, session_keys=session_keys,
            polish=polish, confirm_actions=confirm_actions, debating=debating,
            draws=draws, thread=thread, depth=depth, built=built,
            turn_id=turn_id, halt=halt, checkpoint=checkpoint, brief=brief,
        ), meter=meter, fields={"turn": turn_id})
    finally:
        halt.set()
        with obs.context(turn=turn_id):
            _log_cost(meter, built.get("turn"))


def _answer_stream(*, prefs: dict, prefs_path: Path, chat_path: Path,
                   watchlist: Path, db: Path, message: str, lang: str,
                   context: str, timeout_s: float, staged_import: str,
                   view: str, focus: str, fence: str,
                   session_keys: dict[str, str] | None,
                   polish: Callable[[dict], None] | None,
                   confirm_actions: bool, debating: bool, draws: bool,
                   thread: str | None, depth: str, built: dict,
                   turn_id: str, halt: threading.Event,
                   checkpoint: Checkpoint | None = None,
                   brief: str = "",
                   ) -> Iterator[tuple[str, object]]:
    """`answer_stream`'s body; the turn it builds goes in `built`."""
    # In the stream's own context, which the prepare worker below copies.
    stopping.arm(halt)
    # `prepare` runs on a worker so its phases can be handed over *while* it
    # works: routing, the gather and the web search are most of the wait
    # before the first token, and a stream that says nothing for fifteen
    # seconds reads as a dead one. The worker's own failure is re-raised here,
    # on the stream's thread, where the caller's handler can see it.
    phases: queue.SimpleQueue[tuple[str, object] | None] = queue.SimpleQueue()
    box: dict = {}

    def work() -> None:
        try:
            box["out"] = prepare(
                prefs=prefs, prefs_path=prefs_path, chat_path=chat_path,
                watchlist=watchlist, db=db, message=message, lang=lang,
                context=context, timeout_s=timeout_s,
                staged_import=staged_import,
                on_phase=lambda phase: phases.put(("phase", phase)),
                on_tool=lambda step: phases.put(("tool", step)),
                on_plan=lambda plan: phases.put(("plan", plan)),
                on_subagent=(
                    (lambda said: phases.put(("subagent", said))) if debating else None
                ),
                view=view, focus=focus, fence=fence, session_keys=session_keys,
                confirm_actions=confirm_actions, draws=draws, thread=thread,
                depth=depth, turn_id=turn_id, checkpoint=checkpoint,
                brief=brief,
            )
        except BaseException as exc:  # noqa: BLE001 — re-raised just below
            box["exc"] = exc
        finally:
            phases.put(None)

    worker = threading.Thread(target=metering.bound(work), name="chat-prepare",
                              daemon=True)
    worker.start()
    while (said := phases.get()) is not None:
        yield said
    worker.join()
    if "exc" in box:
        raise box["exc"]
    turn, settled = box["out"]
    built["turn"] = turn
    if turn is None:
        assert settled is not None
        yield ("done", settled)
        return
    # Said before the model starts, not with the answer: the reader is told
    # which earlier conversations it was handed while it is still writing.
    if turn.recalled:
        yield ("recalled", list(turn.recalled))

    from stocks.web.i18n import translate
    from stocks.web.llm import Cut

    capped = False
    # A run picked up after a restart that had already paid for its answer
    # (`chat/checkpoint.py`) is not charged for it again.
    prepaid = checkpoint.prepaid if checkpoint is not None else ""
    kept_key = _answer_key(turn, chat_path)
    if (kept := _kept_answer(turn, kept_key)) is not None:
        provider, key, model, text = kept
        yield ("meta", {"provider": provider.id, "model": model,
                        "skills": list(turn.skills),
                        "sources": list(turn.sources)})
        yield ("text", text)
        yield ("done", _record(turn, text, provider, model, key, prefs=prefs,
                               prefs_path=prefs_path, chat_path=chat_path,
                               polish=polish))
        return
    pending = list(turn.attempts)
    tried: set[tuple[str, str]] = set()
    missed: list[str] = []  # for `llm.byok_to_free`
    while pending:
        provider, key, model = pending.pop(0)
        model = model or provider.default_model
        tried.add((provider.id, model))
        if prepaid and provider.id == prepaid:
            prepaid = ""
        elif not _charge(prefs, prefs_path, provider, turn.units):
            capped = True
            continue
        elif checkpoint is not None and provider.id == "free":
            checkpoint.charged(provider.id)
        parts: list[str] = []
        cut = False
        # The opening words, kept back while they may be a written tool call
        # (`_may_open_call`); None once they are shown.
        held: str | None = ""
        try:
            with llm.thinking(_thinking(turn, provider, model)):
                streamed = provider.stream(key, model, turn.system,
                                           turn.messages)
            for chunk in metering.iterate(streamed, step="answer"):
                if isinstance(chunk, Cut):
                    cut = True
                    continue
                if not chunk:
                    continue
                if held is not None:
                    held += chunk
                    if _may_open_call(held) and (
                            len(held) < CALL_HOLD_CHARS
                            or _WRITTEN_CALL.search(held)):
                        continue
                    chunk, held = held, None
                if not parts:
                    # Held until the first real chunk: a caller that showed
                    # "answering with X" for a provider that then failed over
                    # would have named the wrong one.
                    yield ("meta", {"provider": provider.id, "model": model,
                                    "skills": list(turn.skills),
                                    "sources": list(turn.sources)})
                parts.append(chunk)
                yield ("text", chunk)
        except Exception as exc:
            _provider_failed(exc, provider, model, key)
            if not parts:
                missed.append(f"{provider.id}:{type(exc).__name__}")
                _refund(prefs, prefs_path, provider, turn.units)
                if checkpoint is not None:
                    checkpoint.charged("")
                if not _light(turn, provider, model):
                    pending[:0] = _busy_siblings(exc, provider, key, tried)
                continue
            cut = True  # the stream died mid-answer: what arrived is a stub
        if held:
            # The whole reply stayed held: a written call and nothing else is
            # no answer, so it fails over like a provider that said nothing.
            if _only_calls(held.strip(), provider, model):
                missed.append(f"{provider.id}:rejected")
                _refund(prefs, prefs_path, provider, turn.units)
                if checkpoint is not None:
                    checkpoint.charged("")
                continue
            held = scrub_written_calls(held)
            if not parts:
                yield ("meta", {"provider": provider.id, "model": model,
                                "skills": list(turn.skills),
                                "sources": list(turn.sources)})
            parts.append(held)
            yield ("text", held)
        text = "".join(parts).strip()
        if text and cut:
            closed = close_markdown(text) + "\n\n" + translate(
                "chat.cut_off", turn.lang or "en")
            yield ("text", closed[len(text):])
            text = closed
        if text:
            if provider.id == "free":
                note_free_fallback("chat", prefs, turn.attempts, missed)
            if not cut:
                _keep_answer(kept_key, chat_path, provider, model, text)
            yield ("done", _record(turn, text, provider, model, key,
                                   prefs=prefs, prefs_path=prefs_path,
                                   chat_path=chat_path, polish=polish))
            return

    yield ("done", _exhausted(prefs, turn.attempts, capped, tuple(turn.learned)))
