"""A stored turn as the drawer reads it: its words, sources, steps and tool calls."""

from __future__ import annotations

from pydantic import BaseModel

from stocks.chat import a2ui, navigate, tools

# The tool call a proposal arrives as, and the reason its interrupt names.
CONFIRM_TOOL = "confirm_action"


# ------------------------------------------------------------------ schemas


class Source(BaseModel):
    """One web hit or app document that grounded an answer."""

    title: str = ""
    # An https URL for a web page; an in-app path ("/portfolio?tab=tax") for
    # one of the app's own documents, or "" when it is about no one screen.
    url: str = ""
    # The guided-tour step an app document is about, so the reader's own
    # language can title it. "" for a web page.
    step: str = ""


class Step(BaseModel):
    """One tool line behind an answer: what ran, on what, and what came back."""

    tool: str
    arg: str = ""
    out: str = ""


class ToolCallOut(BaseModel):
    """One frontend tool call on a stored turn.

    `navigate` with `{step}` is a walkthrough step the model offered
    (`guide_goto` on disk), with `{page, tab?, ticker?}` a page link (`nav`).
    `confirm_action` is a proposal (`proposal`), and `state` says whether it is
    still waiting ("pending") or was answered ("done", "cancelled"); a ledger
    edit taken back is "undone".
    """

    id: str
    name: str
    args: dict
    state: str | None = None


class DebateSide(BaseModel):
    """One analyst's case: `side` is "bull" or "bear". `failed` when that side
    did not arrive (an error or past its time), with no `text`."""

    side: str
    text: str
    failed: bool = False


class ActivityOut(BaseModel):
    """One AG-UI activity on a stored turn: `type` "a2ui" is a surface, and
    `content.messages` its A2UI v0.9 messages."""

    id: str
    type: str
    content: dict


class Learned(BaseModel):
    """One change a turn made to the saved memories: `op` is "added",
    "updated" or "deleted", and `id` the memory's (`/chat/memories/{id}`) —
    what the drawer needs to say so and to undo it. `auto` when it was learned
    without being asked; `before` is what an update replaced, its undo;
    `repeated` the days a question was asked on before it became a routine
    (`learnings.notice`), 0 otherwise. `related_id` / `related_text` name a
    kept memory an added one may clash with — the drawer offers to let the
    new one replace it."""

    op: str
    id: str
    text: str
    kind: str = "context"
    auto: bool = False
    before: str = ""
    repeated: int = 0
    related_id: str = ""
    related_text: str = ""


class Recalled(BaseModel):
    """One earlier conversation an answer was given (`engine.earlier`):
    enough to name it, date it and open it (`thread` is its id)."""

    thread: str
    title: str = ""
    when: str = ""
    snippet: str = ""


class ShareLink(BaseModel):
    """One public link an answer went out under (`web/shares.py`): `masked`
    when the reader's amounts were hidden on it."""

    id: str
    masked: bool


class Message(BaseModel):
    """One stored turn. `skills`, `web` and `steps` are what the answer was
    built from — the lens, the pages, and the tool trace."""

    role: str
    content: str
    skills: list[str] = []
    web: list[Source] = []
    steps: list[Step] = []
    # Set on a turn the engine answered by *doing* something (an import it
    # refused, a favorite it set) rather than by asking a model.
    action: str | None = None
    # Set on a turn the walkthrough wrote: `step` is the registry id the card
    # presents, `state` is "done" for a receipt and "end" for the last line.
    guide: dict[str, str] | None = None
    # The frontend tool calls the answer carried, as the stream handed them
    # over — so a reloaded turn draws the same buttons as the one watched.
    tool_calls: list[ToolCallOut] = []
    # A2UI surfaces drawn under the answer (`chat/a2ui.py`), as the AG-UI
    # activities the stream carried them in: a pending proposal's edit form.
    activities: list[ActivityOut] = []
    # The bull and bear cases argued before the answer (`chat/debate.py`).
    debate: list[DebateSide] = []
    # What the turn changed in the saved memories (`chat/learnings.py`).
    learned: list[Learned] = []
    # The earlier conversations quoted onto the question it answers.
    recalled: list[Recalled] = []
    # A model's answer carries the id a rating names it by
    # (`PUT /chat/turns/{id}/rating`), and the reader's thumbs once pressed.
    # "" on the user's turns and on answers written before turns had ids.
    id: str = ""
    rating: str | None = None
    # When a turn written in the background (a daily card, a scheduled run)
    # was filed; "" on the rest, whose clock only the session that wrote
    # them knew.
    at: str = ""
    # The links the answer was shared under, one per cut; and on an answer
    # that came in by a link (`from_share`), that share's id.
    shares: list[ShareLink] = []
    shared_from: str = ""


def _turn(raw: dict, lang: str = "en") -> Message:
    return Message(
        role=str(raw.get("role", "")),
        content=str(raw.get("content", "")),
        skills=list(raw.get("skills") or []),
        web=[Source(**s) for s in (raw.get("web") or []) if isinstance(s, dict)],
        steps=[
            Step(
                tool=str(s.get("tool", "")),
                arg=str(s.get("arg", "")),
                out=str(s.get("out", "")),
            )
            for s in (raw.get("steps") or [])
            if isinstance(s, dict)
        ],
        action=raw.get("action"),
        guide=(
            {k: str(v) for k, v in raw["guide"].items()}
            if isinstance(raw.get("guide"), dict)
            else None
        ),
        tool_calls=_calls(raw),
        activities=[ActivityOut(**a) for a in _activities(raw, lang)],
        debate=[
            DebateSide(side=str(d.get("side", "")), text=str(d.get("text", "")),
                       failed=d.get("failed") is True)
            for d in (raw.get("debate") or [])
            if isinstance(d, dict) and (d.get("text") or d.get("failed") is True)
        ],
        learned=[
            Learned(op=str(c.get("op", "")), id=str(c.get("id", "")),
                    text=str(c.get("text", "")),
                    kind=str(c.get("kind") or "context"),
                    auto=c.get("auto") is True,
                    before=str(c.get("before") or ""),
                    repeated=int(c.get("repeated") or 0),
                    related_id=str(c.get("related_id") or ""),
                    related_text=str(c.get("related_text") or ""))
            for c in (raw.get("learned") or [])
            if isinstance(c, dict) and c.get("id")
        ],
        recalled=[
            Recalled(thread=str(r.get("thread", "")),
                     title=str(r.get("title") or ""),
                     when=str(r.get("when") or ""),
                     snippet=str(r.get("snippet") or ""))
            for r in (raw.get("recalled") or [])
            if isinstance(r, dict) and r.get("thread")
        ],
        id=str(raw.get("id") or ""),
        rating=raw.get("rating") if raw.get("rating") in ("up", "down") else None,
        at=str(raw.get("at") or ""),
        shares=[ShareLink(id=str(k["id"]), masked=k.get("masked") is True)
                for k in (raw.get("shares") or [])
                if isinstance(k, dict) and k.get("id")],
        shared_from=str(raw.get("shared_from") or ""),
    )


def _activities(raw: dict, lang: str) -> list[dict]:
    """The surfaces a stored turn draws. Built from what the turn holds rather
    than stored beside it: a pending proposal's form is a pure function of the
    proposal, and a second copy on disk would be one more thing to go stale."""
    from stocks.web.i18n import translate

    stored = [
        a for a in (raw.get("activities") or [])
        if isinstance(a, dict) and a.get("id") and a.get("type") == a2ui.ACTIVITY_TYPE
        and isinstance(a.get("content"), dict)
    ]
    offer = raw.get("proposal")
    if not (isinstance(offer, dict) and offer.get("state") == "pending"
            and offer.get("id")):
        return stored
    if isinstance(offer.get("book"), dict) and "fill" in offer["book"]:
        form = a2ui.trade_form(offer, lambda key, **kw: translate(key, lang, **kw))
        return [*stored, a2ui.activity(f"form_{offer['id']}", form)]
    if isinstance(offer.get("book"), dict) and offer["book"].get("ops"):
        diff = a2ui.ledger_diff(offer, lambda key, **kw: translate(key, lang, **kw))
        return [*stored, a2ui.activity(f"diff_{offer['id']}", diff)]
    if offer.get("kind") not in tools.TOOLS:
        return stored
    form = a2ui.proposal_form(offer, lambda key: translate(key, lang))
    return [*stored, a2ui.activity(f"form_{offer['id']}", form)]


def _calls(raw: dict) -> list[ToolCallOut]:
    """A stored turn's buttons, as the `tool_calls` the stream sent for it."""
    out: list[ToolCallOut] = []
    if raw.get("guide_goto"):
        out.append(ToolCallOut(id="goto", name=navigate.TOOL_NAME,
                               args={"step": str(raw["guide_goto"])}))
    nav = raw.get("nav")
    if isinstance(nav, dict) and navigate.target(
        "/".join(str(nav.get(k, "")) for k in ("page", "tab", "ticker") if nav.get(k))
    ):
        out.append(ToolCallOut(id="nav", name=navigate.TOOL_NAME,
                               args={k: str(v) for k, v in nav.items()}))
    offer = raw.get("proposal")
    if isinstance(offer, dict) and offer.get("id") and offer.get("kind"):
        out.append(ToolCallOut(id=str(offer["id"]), name=CONFIRM_TOOL,
                               args=_call_args(offer),
                               state=str(offer.get("state") or "pending")))
    return out


def _call_args(offer: dict) -> dict:
    """A proposal as `confirm_action`'s arguments — what would run."""
    out = {"kind": offer["kind"], "ticker": offer["ticker"],
           "args": dict(offer.get("args") or {})}
    held = offer.get("book")
    if isinstance(held, dict):
        # A ledger edit: no form to edit, and once done a change to undo.
        out["book"] = {"summary": str(held.get("summary") or ""),
                       "change": held.get("change"),
                       # A trade still missing figures: its form, then Review.
                       **({"fill": True} if "fill" in held else {})}
    return out
