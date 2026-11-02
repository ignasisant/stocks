"""`Reply`: one chat turn's outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from stocks.chat.engine.providers import (
    prune_byok,
)

if TYPE_CHECKING:

    pass


@dataclass(frozen=True)
class Reply:
    """One chat turn's outcome. `error` is a locale key when text is empty.
    `sources` are the {title, url} dicts of web hits that grounded the
    answer (also stored on the history turn under "web", like the panel)."""

    text: str = ""
    skills: tuple[str, ...] = ()
    sources: tuple[dict, ...] = ()
    provider_id: str = ""
    error: str | None = None
    # What ran to build the answer, as the panel's tool lines — {tool, arg,
    # out}. Also stored on the history turn under "steps", like the panel.
    steps: tuple[dict, ...] = ()
    # An app action put to the reader instead of run (`prepare` with
    # `confirm_actions`), or one the reader just settled: {id, kind, ticker,
    # args, state} with state "pending", "done" or "cancelled". Stored on the
    # assistant turn under "proposal" too, so a reload redraws the same card.
    proposal: dict | None = None
    # The surfaces the answer carries (`Turn.activities`), as stored.
    activities: tuple[dict, ...] = ()
    # The cases argued before it (`Turn.debate`), as stored.
    debate: tuple[dict, ...] = ()
    # What changed in the saved memories (`learnings.change`): {op, id, text,
    # kind} with op "added", "updated" or "deleted", plus `auto` when it was
    # learned unasked and `before` on an update — the drawer's "memory
    # updated" line and its undo. Stored on the turn under "learned" too.
    learned: tuple[dict, ...] = ()
    # The earlier conversations the answer was given (`earlier`), as
    # {thread, title, when, snippet} — the drawer's "based on N earlier
    # conversations" line. Stored on the turn under "recalled" too.
    recalled: tuple[dict, ...] = ()
    # A page button on a turn no model wrote (`navigate.target` args), which
    # the marker the model ends a written answer with cannot give it.
    nav: dict | None = None
    # The stored answer's id (`_record`), which a rating names it by. "" on a
    # turn no model wrote — a refusal, a deterministic confirmation.
    turn_id: str = ""


def _keep_byok(prefs: dict, prefs_path: Path) -> None:
    """After a served turn: drop the stored keys that have expired."""
    from stocks.web import auth

    if prune_byok(prefs):
        auth.save_prefs(prefs, prefs_path)
