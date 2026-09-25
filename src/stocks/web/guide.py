"""The guided tour as a conversation — the assistant walks the account in.

Same registry as the modal tour (`onboarding.STEPS`), same copy keys, a
different stage: the steps are appended to a real thread in the assistant
panel instead of being drawn inside `st.dialog`. Four things follow from that
choice, and they are the whole reason this module exists:

1. **The drawer is not a dialog.** Streamlit allows one open modal per run,
   which is why `onboarding.maybe_open()` has to claim the run and stand
   `auth.maybe_prompt_profile()` down. A guide living in the panel spends none
   of that budget — it can sit beside the "what's new" modal, and it survives
   the page switch that kills a dialog.
2. **A step is a stored turn.** `{"role": "assistant", …, "guide": {"step":
   "import"}}` — the same extra-key convention `action`, `files` and `sources`
   already ride on. So the walkthrough is scrollable, survives a reload, and
   the reader can go back and re-read what they were told. The modal forgets
   everything the moment it closes.
3. **The registry drives it, not a model.** Order, targets and copy come from
   `onboarding.STEPS` and `tour.<id>_*`. An account with no LLM (a brand-new
   one is not free-chain eligible for 24h, see `chat.engine.free_eligible`)
   gets the identical walkthrough, minus prose. Nothing here calls a provider.
4. **It advances on what the account actually did.** `sync()` re-evaluates
   each step's `done` predicate on every run of the panel, so importing a
   statement in another tab is enough — come back and the guide has already
   moved on and says so. That is the part a modal cannot do at all.

Navigation is not implemented here: advancing a step (on desktop) and "take
me there" both queue the step on `onboarding._GOTO`, and the next full run is
handled by `onboarding.consume_goto` in app.py, which already knows how to
switch page, seed session state and drop widget keys. One navigation path, not
two.

Progress lives in prefs.json, and only for signed-in accounts — the guest data
dir is shared by every anonymous visitor (`onboarding._save`), and the panel is
signed-in only anyway.
"""

from __future__ import annotations

import streamlit as st

from stocks import obs

# `engine` is kept on this module's namespace: the guide's tests reach the
# provider chain as `guide.engine`, the same module `guide_ai` calls into.
from stocks.chat import engine, guide_ai  # noqa: F401
from stocks.secrets_env import secret
from stocks.web import auth, i18n, onboarding, skeletons
from stocks.web.ds import is_mobile
from stocks.web.i18n import t as tr

# ------------------------------------------------------------- prefs / state
# prefs.json keys, deliberately distinct from the modal tour's (`tour_done`,
# `tour_seen_version`): the two surfaces can be switched between with the flag
# below, and an account that took one must not read as having taken the other.
PREF_STEP = guide_ai.PREF_STEP  # id of the step the account is on ("" = none)
PREF_DONE = guide_ai.PREF_DONE  # finished, skipped or walked out of
PREF_THREAD = guide_ai.PREF_THREAD  # conversation the guide's turns live in
PREF_OPENS = "guide_opens"  # sessions the panel has been popped open on

# Session keys.
_SEEN = "_guide_auto_seen"  # auto-start evaluated once per session
_PARKED = "_guide_parked"  # panel collapsed after a jump (phones): show strip

# How many sessions may auto-open the panel before it goes quiet. An
# onboarding that reopens itself forever is a nag; the guide stays resumable
# by hand (the Profile launcher, `?guide=1`) after this.
MAX_AUTO_OPENS = 3


def surface() -> str:
    """Which onboarding surface this deploy serves: "chat" or "modal".

    The modal tour is kept whole behind this flag for one release — it is the
    rollback, and it is also the reference rendering of the same registry when
    something looks wrong in the conversation.
    """
    got = (secret("GUIDE_SURFACE", "guide", "surface") or "").strip().lower()
    return got if got in ("chat", "modal") else "chat"


def steps() -> tuple[onboarding.Step, ...]:
    return onboarding.visible_steps()


def _index(step: onboarding.Step | None) -> int:
    """0-based position of a step, or -1. Used for progress and telemetry."""
    if step is None:
        return -1
    return next((i for i, s in enumerate(steps()) if s.id == step.id), -1)


def _next(step: onboarding.Step | None) -> onboarding.Step | None:
    """The step after this one, or None when it is the last."""
    all_steps = steps()
    idx = _index(step)
    if idx < 0 or idx + 1 >= len(all_steps):
        return None
    return all_steps[idx + 1]


def current(prefs: dict | None = None) -> onboarding.Step | None:
    """The step the account is on, or None when the guide is not running."""
    p = prefs if prefs is not None else auth.load_prefs()
    if p.get(PREF_DONE):
        return None
    return onboarding.by_id(str(p.get(PREF_STEP) or ""))


def active(prefs: dict | None = None) -> bool:
    """Whether the guide is started and not finished."""
    return current(prefs) is not None


def owns(conv: dict, prefs: dict | None = None) -> bool:
    """Whether this conversation is the guide's own thread, still running.

    Read by the panel before `sync()`: the guide writes into one thread and
    must never append a step card to a conversation the user started.
    """
    p = prefs if prefs is not None else auth.load_prefs()
    return active(p) and conv.get("id") == p.get(PREF_THREAD)


# ------------------------------------------------------------ start / finish
def _ensure_thread(prefs: dict) -> None:
    """Point the panel at the guide's thread, creating it the first time.

    Best-effort: an unreadable or half-written chat.json must cost the guide,
    not the app. `new_conversation` reuses an empty active conversation, so a
    brand-new account gets its one blank thread titled rather than a second.
    """
    try:
        cid = str(prefs.get(PREF_THREAD) or "")
        known = {c["id"] for c in auth.list_conversations()}
        if cid and cid in known:
            auth.set_active_conversation(cid)
            return
        prefs[PREF_THREAD] = auth.new_conversation(title=tr("guide.thread_title"))
    except Exception as exc:  # noqa: BLE001 — the guide is never worth a crash
        obs.warn("guide.thread_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])


def _open(prefs: dict, step_id: str, *, counts: bool) -> None:
    """Put the guide on `step_id` and show it, in the panel, this run.

    `counts` distinguishes the automatic pop (which spends one of the three)
    from one the user asked for (the launcher, `?guide=`), which never does.
    """
    started = not prefs.get(PREF_STEP)
    prefs[PREF_STEP] = step_id
    prefs[PREF_DONE] = False
    if counts:
        prefs[PREF_OPENS] = int(prefs.get(PREF_OPENS) or 0) + 1
    _ensure_thread(prefs)
    onboarding._save(prefs)
    # Read by chat_core._panel_is_open on this same run, so the panel is
    # already open when app.py reaches render_side_panel below.
    st.session_state["chat_panel_open"] = True
    st.session_state["chat_drawer_view"] = "thread"
    st.session_state[_PARKED] = False
    if started:
        obs.event("guide.start", step=step_id)


def start(step_id: str | None = None) -> None:
    """Open the guide by hand — the Profile launcher, the Home setup card.

    Starts from the top like the modal launcher does: someone who asks for the
    tutorial wants the tutorial, not the step they walked out of last month.
    """
    prefs = auth.load_prefs()
    _open(prefs, step_id or steps()[0].id, counts=False)


def _consume_params(prefs: dict) -> bool:
    """`?guide=1` (or `?guide=<step id>`) opens the guide, once per URL value.

    Deleted as it is read so the next rerun doesn't reopen what was just
    closed — same one-shot handling as `?tour=` and the landing CTAs. `?tour=`
    is left alone on purpose: it still drives the modal, which is the
    reference rendering while both surfaces exist.
    """
    raw = str(st.query_params.get("guide") or "").strip().lower()
    if not raw:
        return False
    del st.query_params["guide"]
    if raw in {"1", "true", "yes"}:
        _open(prefs, steps()[0].id, counts=False)
        return True
    if onboarding.by_id(raw) is not None:
        _open(prefs, raw, counts=False)
        return True
    return False


def maybe_start() -> bool:
    """Auto-start on the session's first run; True while the guide owns
    onboarding this run.

    app.py reads the return value the way it read `onboarding.maybe_open()`:
    True means neither "what's new" nor the investor-profile nudge should fire
    over a walkthrough in progress (the profile is one of the guide's own
    steps). Unlike the modal, the reason is politeness rather than Streamlit's
    one-dialog rule — the panel and a dialog can coexist.

    Guests never auto-start: nothing is persisted for them and the panel is
    signed-in only.
    """
    if surface() != "chat" or not auth.is_logged_in():
        return False
    prefs = auth.load_prefs()
    if st.session_state.get(_SEEN):
        return active(prefs)
    st.session_state[_SEEN] = True
    if _consume_params(prefs):
        return True
    if prefs.get(PREF_DONE):
        return False
    if int(prefs.get(PREF_OPENS) or 0) >= MAX_AUTO_OPENS:
        # Out of automatic pops. The guide is still running — the strip and
        # the launcher can resume it — it just stops opening itself.
        return active(prefs)
    _open(prefs, str(prefs.get(PREF_STEP) or steps()[0].id), counts=True)
    return True


def _finish(prefs: dict, reason: str) -> None:
    """End the guide for good, and record where it was left.

    The step someone walks out on is the only feedback the walkthrough gives
    about itself, and `reason` separates the ways out — finishing is not the
    same signal as skipping from step two.
    """
    step = current(prefs)
    obs.event("guide.exit", reason=reason, step=step.id if step else "",
              index=_index(step) + 1, of=len(steps()))
    prefs[PREF_DONE] = True
    prefs[PREF_STEP] = ""
    # Someone just walked through everything has no "what's new" to catch up
    # on, and has plainly seen the tour — stamp both so neither modal fires.
    prefs[onboarding.PREF_DONE] = True
    prefs[onboarding.PREF_SEEN_VERSION] = onboarding.CURRENT_VERSION
    onboarding._save(prefs)
    st.session_state[_PARKED] = False


def finish(reason: str = "finished") -> None:
    _finish(auth.load_prefs(), reason)


# ------------------------------------------------------------------- turns
def turn_for(step: onboarding.Step) -> dict:
    """The stored assistant turn that presents one step.

    The `guide` key is what `chat_core._render_turn` dispatches on, and what
    `sync` reads back to know which cards a thread already carries. Content is
    plain markdown so an old card still reads correctly if this module (or the
    card renderer) ever goes away.
    """
    return {
        "role": "assistant",
        "content": (
            f":material/{step.icon}: **{tr(f'tour.{step.id}_title')}**\n\n"
            + tr(f"tour.{step.id}_body")
        ),
        "guide": {"step": step.id},
    }


def _done_turn(step: onboarding.Step) -> dict:
    """The line that acknowledges a step the account has already switched on."""
    return {
        "role": "assistant",
        "content": tr("guide.step_done", title=tr(f"tour.{step.id}_title")),
        "guide": {"step": step.id, "state": "done"},
    }


def _has_card(history: list[dict], step_id: str) -> bool:
    """Whether this thread already presents that step (its acknowledgement
    line doesn't count — that one is a receipt, not a card)."""
    return any(
        m.get("guide", {}).get("step") == step_id
        and not m.get("guide", {}).get("state")
        for m in history
    )


def sync(history: list[dict]) -> bool:
    """Bring the thread up to date with what the account has actually done.

    Called by the panel before it draws the history, so anything appended here
    renders on this same run — no rerun, no flash of a stale card. Two jobs:

    * walk past every step whose `done` predicate now holds, leaving one
      acknowledgement line each. This is what makes an import done in another
      tab show up as progress instead of as a step the reader has to re-read;
    * make sure the current step's card is in the thread.

    Returns whether anything changed. Mutates `history` in place — it is the
    session-state list the panel is about to render — and persists it.
    """
    prefs = auth.load_prefs()
    step = current(prefs)
    if step is None:
        return False

    changed = False
    # Bounded by the registry length: a `done` predicate that somehow always
    # answers True must not spin.
    for _ in range(len(steps())):
        if step is None or step.done is None or not step.done(prefs):
            break
        # Separate signal from `advance`: a step nobody had to be walked
        # through is the guide working, and it is invisible from the exits.
        obs.event("guide.step", step=step.id, index=_index(step) + 1,
                  of=len(steps()), auto=True)
        history.append(_done_turn(step))
        step = _next(step)
        changed = True

    if step is None:
        _finish(prefs, "completed")
        history.append({"role": "assistant", "content": tr("guide.finished"),
                        "guide": {"step": "", "state": "end"}})
        auth.save_chat(history)
        return True

    if changed:
        prefs[PREF_STEP] = step.id
    if not _has_card(history, step.id):
        history.append(turn_for(step))
        changed = True
    if changed:
        auth.save_chat(history)
        onboarding._save(prefs)
    return changed


# ------------------------------------------------------------------ actions
def advance() -> None:
    """Move to the next step and, on desktop, take the reader with it.

    The card itself appears on the rerun, via `sync` — this moves the marker
    and queues the jump `onboarding.consume_goto` makes early in app.py.

    Walking the reader over is the difference between a walkthrough and a
    leaflet: a card describing Pulso while the account is still looking at
    Home is describing something that is not on screen, and the reader has to
    work out that the button under the text was not optional. The card keeps
    its "take me there" — for re-following an older step, and for the jump
    this one declines to make.

    Phones decline it: there the panel *is* the viewport, so `goto` parks the
    tour to uncover the page (see its docstring), and an automatic jump on
    every Next would spend the walkthrough reopening the drawer. On desktop
    the panel is a rail beside the page, which is the entire point.
    """
    prefs = auth.load_prefs()
    step = current(prefs)
    if step is None:
        return
    obs.event("guide.step", step=step.id, index=_index(step) + 1,
              of=len(steps()))
    nxt = _next(step)
    if nxt is None:
        _finish(prefs, "finished")
        return
    prefs[PREF_STEP] = nxt.id
    onboarding._save(prefs)
    if not is_mobile():
        goto(nxt)


def goto(step: onboarding.Step) -> None:
    """Send the reader to the step's own page.

    The jump itself belongs to `onboarding.consume_goto`, which runs early in
    app.py — before the topbar and the panel — and already handles switching
    page, seeding session state and dropping widget keys. Here we only queue it.

    On a phone the panel is the full viewport, so staying open would hide the
    very page the reader was sent to look at: collapse it to the launcher and
    leave the strip behind. On desktop the panel is a rail beside the page,
    which is the entire point, so it stays.
    """
    st.session_state[onboarding._GOTO] = step.id
    if is_mobile():
        st.session_state["chat_panel_open"] = False
        st.session_state[_PARKED] = True


# ---------------------------------------------------------------- rendering
def _cta_label(step: onboarding.Step) -> str:
    key = f"tour.{step.id}_cta"
    return tr(key) if i18n.has(key) else tr("guide.goto")


def render_card(ns: str, msg: dict, index: int) -> None:
    """The controls under one step's turn.

    Only the step the account is *on* carries the ones that move the guide:
    clicking Next on a card five turns up would walk it backwards and the
    reader would never see why. "Take me there" is the exception and stays
    live on every card — navigation changes nothing about where the guide is,
    and a thread you cannot re-follow is worse than the modal it replaced,
    which at least had a Back button.
    """
    sid = str(msg.get("guide", {}).get("step") or "")
    step = onboarding.by_id(sid)
    if step is None or msg.get("guide", {}).get("state"):
        return
    prefs = auth.load_prefs()
    cur = current(prefs)
    live = cur is not None and cur.id == sid
    idx = _index(step)

    if live:
        if step.done is not None:
            st.markdown(
                f":green-badge[:material/check: {tr('tour.active')}]"
                if step.done(prefs)
                else f":gray-badge[{tr('tour.pending')}]"
            )
        st.caption(tr("guide.progress", n=idx + 1, total=len(steps())))

    row = st.container(horizontal=True, vertical_alignment="center")
    if (step.page or step.session) and row.button(
        _cta_label(step), key=f"{ns}_guide_goto_{index}", type="secondary",
        icon=":material/open_in_new:",
    ):
        goto(step)
        st.rerun()  # full run: consume_goto navigates before the panel redraws
    if not live:
        return
    last = idx + 1 >= len(steps())
    if row.button(
        tr("guide.finish") if last
        else tr("guide.done_it") if step.done is not None
        else tr("guide.next"),
        key=f"{ns}_guide_next_{index}", type="primary",
        icon=":material/check:" if last else ":material/chevron_right:",
    ):
        advance()
        st.rerun()
    if not last and st.button(tr("guide.skip"), key=f"{ns}_guide_skip_{index}",
                              type="tertiary"):
        _finish(prefs, "skipped")
        st.rerun()


def render_strip() -> None:
    """The parked guide: one line above the page body, on phones.

    Drawn from app.py beside `onboarding.render`. Only appears after a jump
    collapsed the panel — on desktop the panel itself is the strip's job.
    """
    if not st.session_state.get(_PARKED):
        return
    prefs = auth.load_prefs()
    step = current(prefs)
    if step is None or st.session_state.get("chat_panel_open"):
        st.session_state[_PARKED] = False
        return
    with st.container(border=True):
        row = st.container(horizontal=True, vertical_alignment="center")
        row.markdown(
            f":material/{step.icon}: "
            + tr("guide.strip_progress", n=_index(step) + 1,
                 total=len(steps()), title=tr(f"tour.{step.id}_title"))
        )
        if row.button(tr("guide.strip_open"), key="guide_strip_open",
                      icon=":material/forum:"):
            _open(prefs, step.id, counts=False)
            st.rerun()
        if row.button(tr("guide.strip_exit"), key="guide_strip_exit",
                      type="tertiary"):
            _finish(prefs, "abandoned_strip")
            st.rerun()


# ------------------------------------------------------------ the model half
# Everything above works with no provider at all, and must keep working: a
# brand-new account is on the reduced trial allowance (chat.engine, policy
# "trial") and may have no key of its own. What follows is the layer on top —
# a personal opening line, and answers to whatever the reader asks mid-tour —
# and every path through it degrades to silence rather than to an error.
#
# The logic itself lives in `stocks.chat.guide_ai`, headless, so the HTTP API
# serves the React drawer the same fence, the same marker and the same opening
# line. What stays here is only the part that reads this Streamlit session.

PREF_NARRATED = guide_ai.PREF_NARRATED  # the opening line was attempted, once
NARRATE_TIMEOUT_S = guide_ai.NARRATE_TIMEOUT_S
NARRATE_MAX_CHARS = guide_ai.NARRATE_MAX_CHARS

hide_markers = guide_ai.hide_markers
claim_goto = guide_ai.claim_goto
_accept = guide_ai.accept


def prompt_fence() -> str:
    """The walkthrough's fence for the conversation this session has open —
    `guide_ai.prompt_fence`, read off the session's prefs and thread. Empty,
    and therefore free, for every conversation that is not the guide's own.
    """
    try:
        conv = auth.active_conversation()
    except Exception:  # an unreadable chat book is not worth a failed turn
        return ""
    return guide_ai.prompt_fence(auth.load_prefs(), conv.get("id"),
                                 i18n.active_language())


def render_jump(ns: str, msg: dict, index: int) -> None:
    """The button an answer earned by ending in a valid marker.

    Deliberately a button and not a navigation: the model proposes, the reader
    decides. Drawn under normal answers, so it is `chat_core`'s turn renderer
    that calls this, not the step-card renderer above.
    """
    step = onboarding.by_id(str(msg.get("guide_goto") or ""))
    if step is None:
        return
    if st.button(_cta_label(step), key=f"{ns}_guide_jump_{index}",
                 type="secondary", icon=":material/open_in_new:"):
        goto(step)
        st.rerun()


# ------------------------------------------------------------------ opening
def _generate(prefs: dict, step: onboarding.Step) -> str | None:
    """One sentence about the step just reached, or None. Never raises."""
    return guide_ai.generate(
        prefs, step, i18n.active_language(),
        save=lambda p: auth.save_prefs(p),
        account_facts=guide_ai.facts(prefs),
    )


def narrate(ns: str, history: list[dict], box) -> bool:
    """The one generated turn in the walkthrough: a line of its own about the
    step the reader has just reached.

    Held back until they have pressed something (so, the second step), for two
    reasons. It is a moment where a wait is expected, so a few seconds of
    thinking reads as the assistant answering rather than as the app being
    slow — whereas the panel's very first paint happens before `page.run()`,
    where a blocked run would delay the whole page behind it. And a scripted
    step followed by a sentence that is visibly about *this* account is the
    cheapest possible proof that the thing talking is not a slideshow.

    Attempted once per account, whether or not it works: an account that gets
    silence here has a provider problem, and retrying on every rerun would
    turn that into a stall on every rerun.
    """
    prefs = auth.load_prefs()
    step = guide_ai.due_narration(prefs)
    if step is None:
        return False
    # The deferred-slot pattern the rest of the app loads with (web/skeletons):
    # a shimmer in the shape of what is coming, cleared to nothing when it does
    # not come — which is what a failed attempt has to look like.
    slot = skeletons.reserve("text", lines=2, container=box)
    line = _generate(prefs, step)
    prefs[PREF_NARRATED] = True
    onboarding._save(prefs)
    if not line:
        slot.clear()
        obs.event("guide.narration_skipped")
        return False
    turn = guide_ai.note_turn(step, line)
    # Appended, never inserted: the card above is already on screen at its own
    # index this run, and moving it would repaint it under different widget
    # keys on the next one — the reader would watch the step jump.
    history.append(turn)
    auth.save_chat(history)
    with slot.container(), st.chat_message("assistant"):
        st.markdown(line)
    return True
