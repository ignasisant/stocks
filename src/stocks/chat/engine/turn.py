"""`Turn`: what prepare() resolves for one question, and the view it was
asked from.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import TYPE_CHECKING

from stocks.chat.engine.quota import (
    DEEP_UNITS,
)

if TYPE_CHECKING:

    from stocks.web.llm import Provider


# Prepended for a surface that renders markdown — the web assistant panel and
# the React drawer. It renders tables, but in a 420px drawer or on a phone, so
# a table of sentences is a sideways scroll: steer prose into lists at the
# source. The drawer still wraps and stacks whatever table arrives anyway.
MARKDOWN_CONTEXT = (
    "Answers render as markdown in a narrow panel, often on a phone. Use a "
    "table only for short values side by side (tickers, figures, dates): at "
    "most four columns and a few words per cell. Anything that takes a "
    "sentence to say goes in a list instead, one bullet per item with its "
    "name in bold. Never put <br> or line breaks inside a table cell. "
    "No LaTeX or $ math: the panel prints it raw, so write a formula in "
    "plain words and symbols (neto = bruto × (1 − 19 %)).\n\n"
)

# A focused symbol as the drawer may name it: letters, digits and the four
# punctuation marks real tickers carry (BRK.B, BTC-EUR, ^GSPC, EURUSD=X). It
# lands in a system prompt, so anything longer or stranger is dropped rather
# than escaped — a "ticker" with a sentence in it is an instruction, not a
# symbol.
_FOCUS_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^=")
_FOCUS_MAX = 20


def clean_focus(raw: str | None) -> str:
    """A ticker fit for the prompt, upper-cased, or '' when it is not one."""
    sym = (raw or "").strip().upper()
    if not sym or len(sym) > _FOCUS_MAX or not set(sym) <= _FOCUS_CHARS:
        return ""
    return sym


def view_context(page: str = "", focus: str = "", tab: str = "",
                 about: str = "") -> str:
    """What the reader is looking at, from values the caller already resolved.

    "Is this a good entry?" means nothing without the page it was asked on,
    so the model is told which page and which ticker; the client passes them
    in. `page` is a human page name (already localized), `tab` the open tab's
    own label on a page that has tabs (so "what is this column?" asked on the
    Fees tab is about fees), `focus` a symbol that has been through
    `clean_focus`. `about` is that ticker's sector and industry ("Energy ·
    Uranium"), when known: the skill router reads this context too, and
    without it a company is routed by its name.
    """
    bits = []
    if page and tab:
        bits.append(f"The user is currently on the {page} page, {tab} tab.")
    elif page:
        bits.append(f"The user is currently on the {page} page.")
    if focus:
        bits.append(f"The ticker in focus is {focus}"
                    + (f" ({about})." if about else ".")
                    + ' It is what "this" and "it" mean; a question that names'
                    " other symbols, the user's own portfolio or a concept is"
                    " not about it.")
    return ("Current view: " + " ".join(bits) + "\n\n") if bits else ""


@dataclass
class Turn:
    """A turn resolved up to the point where a model has to speak.

    `answer` and `answer_stream` differ only in how the text arrives and how it
    is handed back; everything before that — the provider chain, the routed
    skills, the evidence stapled onto the newest message — is one decision, so
    it is made once here instead of twice, slightly differently, in two loops
    that then drift.
    """

    history: list[dict]
    attempts: list[tuple[Provider, str, str]]
    system: str
    messages: list[dict]
    skills: list[str]
    sources: list[dict]
    steps: list[dict] = dc_field(default_factory=list)
    #: The account's locale — the thread title's fallback language.
    lang: str = "en"
    #: A2UI surfaces the answer carries (`chat/a2ui.py`), as AG-UI activities
    #: {id, type, content} — a simulated sale's slider. Stored on the answer.
    activities: list[dict] = dc_field(default_factory=list)
    #: The bull and bear cases argued before the answer (`chat/debate.py`),
    #: as {side, text}. Stored on the answer.
    debate: list[dict] = dc_field(default_factory=list)
    #: The memory command at the head of the question, already carried out
    #: (`Reply.learned`) — `_record` adds what was learned unasked. Stored on
    #: the answer.
    learned: list[dict] = dc_field(default_factory=list)
    #: The earlier conversations quoted onto the question (`earlier`), as
    #: `Reply.recalled`. Stored on the answer.
    recalled: list[dict] = dc_field(default_factory=list)
    #: Set once the question's background read for memories (`learn`) is
    #: done; None when none was started.
    learning: threading.Event | None = None
    #: The conversation the question was asked in, which is where the answer
    #: is stored even if the active one has moved since (`auth.save_chat`).
    #: None is the active one, as the bot has always meant it.
    thread: str | None = None
    #: The gather's `agent.Profile` name, "fast" or "deep": what the turn's
    #: cost line (`_log_cost`) is broken down by.
    profile: str = "fast"
    #: "light" when the router read the question as easy and the cheapest
    #: model answers first (`_routed`), "" when the reader's own model does.
    #: On the turn's cost line.
    route: str = ""
    #: What the stored answer is named by (`rate_turn`), and the `turn` field
    #: on the turn's log lines: a thumbs-down finds its tools and its cost.
    id: str = dc_field(default_factory=lambda: secrets.token_hex(6))
    #: A change the research put to the reader (`_proposed`), filed as a
    #: pending card under the answer; None when it proposed nothing.
    proposal: dict | None = None
    #: The ticker the question asked exit rules for, when the research
    #: proposed none: `_record` drafts the card from the answer's own words
    #: (`_drafted_rules`). "" otherwise.
    rules_for: str = ""

    @property
    def units(self) -> int:
        """Free units this turn costs: a deep gather reads for several."""
        return DEEP_UNITS if self.profile == "deep" else 1
