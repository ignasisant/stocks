"""The walkthrough's model half, with no Streamlit session under it.

`web/guide.py` walks a new account through the app inside the assistant
drawer, and most of it is deterministic: the registry decides the steps, the
copy comes from the catalogs, and nothing calls a provider. Three pieces are
not, and they are the ones that make the guide feel like an assistant rather
than a slideshow:

* **the fence** — while the reader is on the guide's own thread, the system
  prompt lists the steps that exist and forbids inventing any other. A model
  asked "where do I put my broker statement" will happily describe a Settings
  page, and a reader who has not seen the app yet cannot know it is wrong;
* **the jump marker** — the one steering channel the model gets. An answer may
  end in `[[goto:<step id>]]`, which is withheld from the text while it
  streams and becomes a "take me there" button once it is checked against the
  registry;
* **the narration** — one generated sentence about the account, on the second
  step, attempted once ever.

They used to live beside `st.session_state` and `auth.load_prefs()`, which the
HTTP API has neither of — so the React drawer's guide had no fence, printed the
marker verbatim, and never narrated. Everything here takes the account's prefs,
paths and language as arguments instead, and both front ends call it: the
Streamlit guide through thin wrappers that read the session, and
`api/routes/chat.py` / `api/routes/guide.py` with what the request resolved.

Every path through the model half degrades to silence rather than to an error:
a brand-new account is on the reduced trial allowance and may have no key of
its own, and the walkthrough is complete without any of this.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator

from stocks import obs
from stocks.chat import engine

# prefs.json keys, deliberately distinct from the modal tour's (`tour_done`,
# `tour_seen_version`): the two surfaces can be switched between with the
# GUIDE_SURFACE flag, and an account that took one must not read as having
# taken the other. `web/guide.py` re-exports them under the same names.
PREF_STEP = "guide_step"  # id of the step the account is on ("" = not started)
PREF_DONE = "guide_done"  # finished, skipped or walked out of
PREF_THREAD = "guide_thread"  # conversation the guide's turns live in
PREF_NARRATED = "guide_narrated"  # the opening line was attempted, once ever

# The one steering channel the model is given. It may end an answer with
# [[goto:<step id>]] to offer a jump; the id is checked against the registry
# before it becomes a button, so a step the model invented simply vanishes.
# Never parsed out of the *user's* text — only out of what a provider wrote.
MARKER_RE = re.compile(r"\[\[goto:\s*([a-z_]{1,32})\s*\]\]")
# How much of a stream's tail to hold back while a marker could still be
# forming. Longer than any marker, short enough that prose never visibly lags.
_HOLD = 48

NARRATE_TIMEOUT_S = 12.0
NARRATE_MAX_CHARS = 280

_LANG_NAME = {"en": "English", "es": "Spanish"}


# ------------------------------------------------------------------ the state


def _steps():
    from stocks.web import onboarding

    return onboarding.visible_steps()


def _by_id(step_id: str):
    from stocks.web import onboarding

    return onboarding.by_id(step_id)


def current(prefs: dict):
    """The step the account is on, or None when the guide is not running."""
    if prefs.get(PREF_DONE):
        return None
    return _by_id(str(prefs.get(PREF_STEP) or ""))


def index(step) -> int:
    """0-based position of a step, or -1."""
    if step is None:
        return -1
    return next((i for i, s in enumerate(_steps()) if s.id == step.id), -1)


def owns(conv_id: str | None, prefs: dict) -> bool:
    """Whether this conversation is the guide's own thread, still running.

    The fence and the marker filter are for the walkthrough and nothing else:
    a reader who asks the same question in a thread they started is asking
    the assistant, not the tour, and gets the unfenced answer.
    """
    return (
        current(prefs) is not None
        and bool(conv_id)
        and conv_id == prefs.get(PREF_THREAD)
    )


# ------------------------------------------------------------------ the fence


def prompt_fence(prefs: dict, conv_id: str | None, lang: str) -> str:
    """What the model is told while it is answering inside the walkthrough.

    Two jobs, and the first is the important one. During onboarding the reader
    has no way to know that a described menu does not exist, so the prompt
    carries the registry: these steps exist, and nothing else does. The second
    job is the jump marker, which is what lets an answer end in a button
    instead of in directions.

    Empty — and therefore free — for every conversation that is not the
    guide's own thread. Titles are given in the reader's language, the one
    their question arrived in, because that is what the model will quote back.
    """
    from stocks.web.i18n import translate

    if not owns(conv_id, prefs):
        return ""
    step = current(prefs)
    if step is None:
        return ""
    steps = _steps()
    listing = "\n".join(
        f"- {s.id}: {translate(f'tour.{s.id}_title', lang)}" for s in steps
    )
    return (
        "\n\nThe user is part-way through the app's guided walkthrough. They "
        f"are on step {index(step) + 1} of {len(steps)}, "
        f'"{translate(f"tour.{step.id}_title", lang)}".\n'
        "These are the only parts of the app that exist:\n"
        f"{listing}\n"
        "Answer questions about the app from that list alone. Never describe "
        "a page, tab, button or setting that is not on it, and never invent "
        "a menu path — say you are not sure instead. Keep walkthrough answers "
        "short.\n"
        "To offer to take them somewhere, end your reply with [[goto:<id>]] "
        "on its own line, using one id from the list exactly as written. At "
        "most one marker, and only when going there is genuinely the next "
        "thing to do. Never write the marker in any other form, and never "
        "explain that it exists.\n"
    )


# ---------------------------------------------------------------- the marker


class MarkerFilter:
    """A stream's text with any jump marker withheld, and the markers kept.

    The marker has to be invisible *while streaming*, not merely stripped from
    what gets stored: a client paints tokens as they arrive, and a marker shown
    for even one frame reads as the assistant glitching. So the tail is held
    back whenever it could still be the beginning of one — which costs a few
    characters of lag on prose containing "[", and nothing else.

    A class rather than a generator because the two callers hold the stream
    differently: Streamlit hands `st.write_stream` an iterator (`hide_markers`
    below), and the HTTP route forwards engine events one at a time and needs
    to push a chunk in and take the safe prefix out.
    """

    def __init__(self) -> None:
        self.found: list[str] = []
        self._held = ""

    def feed(self, chunk: str) -> str:
        """Take a chunk; return what can be shown now (possibly '')."""
        held = self._held + str(chunk)
        self.found.extend(hit.group(1) for hit in MARKER_RE.finditer(held))
        held = MARKER_RE.sub("", held)
        # The *earliest* bracket still close enough to the end to be a marker
        # forming, not the latest: "[[go" would otherwise emit its first
        # bracket and the reader would watch a marker assemble itself.
        cut = held.find("[", max(0, len(held) - _HOLD))
        if cut != -1:
            out, self._held = held[:cut], held[cut:]
        else:
            out, self._held = held, ""
        return out

    def close(self) -> str:
        """The stream ended: whatever was held, minus any marker in it."""
        held, self._held = self._held, ""
        self.found.extend(hit.group(1) for hit in MARKER_RE.finditer(held))
        return MARKER_RE.sub("", held)


def hide_markers(chunks: Iterable, found: list[str]) -> Iterator[str]:
    """Yield a provider's stream with any jump marker withheld, recording it."""
    gate = MarkerFilter()
    try:
        for chunk in chunks:
            out = gate.feed(str(chunk))
            if out:
                yield out
        tail = gate.close()
        if tail:
            yield tail
    finally:
        found.extend(gate.found)


def scrub(text: str) -> str:
    """The text with every marker removed, trailing space trimmed."""
    return MARKER_RE.sub("", str(text or "")).rstrip()


def claim_goto(turn: dict, found: list[str]) -> str | None:
    """Attach a validated jump to a finished answer; returns the step id.

    The last marker wins — a stream that fell down to a second provider can
    carry one from each. An id that is not a step in the registry is dropped
    without a trace: the answer stands, it just ends in prose instead of a
    button. Also scrubs the text, for the marker that arrived in a shape the
    filter could not withhold — and it reads the text itself too, so a caller
    that never ran the filter still gets its button.
    """
    raw = str(turn.get("content") or "")
    seen = [*found, *(hit.group(1) for hit in MARKER_RE.finditer(raw))]
    turn["content"] = scrub(raw)
    for sid in reversed(seen):
        if _by_id(sid) is not None:
            turn["guide_goto"] = sid
            obs.event("guide.jump_offered", step=sid)
            return sid
    return None


# --------------------------------------------------------------- the opening


def facts(prefs: dict, paths: object | None = None, *,
          signed_in: bool | None = None) -> str:
    """The little the opening line is allowed to know about the account.

    Counts, not holdings: the free chain is operator-funded and shared, and a
    welcome message is the last place worth sending someone's book through it
    (the normal turn already carries the snapshot — that one the reader asked
    for). Everything here is cheap and non-identifying.
    """
    from stocks.config import load_watchlist
    from stocks.web import onboarding

    try:
        where = getattr(paths, "watchlist", None)
        if where is None:
            from stocks.web import auth

            where = auth.watchlist_path()
        tickers = len(load_watchlist(where))
    except Exception:
        tickers = 0
    try:
        imported = onboarding.setup_state(prefs, paths, signed_in=signed_in).get(
            "import"
        )
    except Exception:
        imported = False
    return f"watchlist_tickers={tickers}; has_imported_ledger={imported}"


def accept(raw: str | None) -> str | None:
    """Keep a usable opening line, or None so the next provider gets a turn.

    Rejects rather than repairs the shapes that mean the model ignored the
    brief — a link, a marker, a wall of text — and trims the merely long,
    because one sentence that runs over is still a good sentence.
    """
    line = " ".join(str(raw or "").split())
    if not line or "[[" in line or "](" in line or "http" in line:
        return None
    if len(line) > NARRATE_MAX_CHARS * 2:
        return None
    if len(line) > NARRATE_MAX_CHARS:
        line = line[:NARRATE_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return line


def generate(prefs: dict, step, lang: str, *, save: Callable[[dict], None],
             account_facts: str,
             session_keys: dict[str, str] | None = None) -> str | None:
    """One sentence about the step just reached, or None. Never raises.

    Goes through `engine.complete_attempts`, so a dead key, a spent allowance
    or a hung provider falls to the next candidate and finally to None — the
    same sandbox the daily briefing runs in. A free unit spent on an attempt
    that answered nothing is handed back: the guide is not what should cost a
    new account one of its five trial messages. `save` writes prefs for the
    caller that owns them (the Streamlit session's file, or the request's).
    """
    from stocks.web.i18n import translate

    spent: list[int] = []

    def _spend(p: dict) -> bool:
        if not engine.spend_free_quota(p):
            return False
        spent.append(1)
        save(p)
        return True

    system = (
        "You are the assistant built into TopStocks, a personal "
        "stock-portfolio app, walking a new user through it. They have just "
        f'reached the step "{translate(f"tour.{step.id}_title", lang)}", '
        "which the app has already described to them. Write ONE sentence of "
        f"at most 200 characters, in {_LANG_NAME.get(lang, 'English')}, that "
        "adds something useful about this step for THIS user given the facts "
        "below — why it matters to them, or what to do first. Do not repeat "
        "the description, do not greet them, and invent nothing about the "
        "app. Plain text only: no markdown, no links, no lists, no emoji, no "
        "quotation marks."
    )
    try:
        line = engine.complete_attempts(
            prefs, system, [{"role": "user", "content": account_facts}],
            NARRATE_TIMEOUT_S, spend_free=_spend, accept=accept,
            **({"session_keys": session_keys} if session_keys else {}),
        )
    except Exception as exc:  # complete_attempts never raises; belt and braces
        obs.warn("guide.narration_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        line = None
    if line is None and spent:
        engine.refund_free_quota(prefs, sum(spent))
        save(prefs)
    return line


def due_narration(prefs: dict):
    """The step owed its one generated line, or None.

    Held back until the reader has pressed something (so, the second step),
    and attempted once per account whether or not it works: an account that
    gets silence here has a provider problem, and retrying on every advance
    would turn that into a stall on every advance.
    """
    step = current(prefs)
    if step is None or prefs.get(PREF_NARRATED) or index(step) < 1:
        return None
    return step


def note_turn(step, line: str) -> dict:
    """The stored turn a narration becomes: a note under the step's card."""
    return {"role": "assistant", "content": line,
            "guide": {"step": step.id, "state": "note"}}
