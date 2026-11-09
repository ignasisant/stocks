"""What a press on an answer does: undo a proposal, act on an A2UI surface."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from stocks import accounts, obs
from stocks.accounts import UserPaths
from stocks.api.deps import SurfaceAction, Writer
from stocks.api.routes.chat.preferences import _prefs
from stocks.chat import charts, engine, plan_builder, rebalance, whatif

router = APIRouter(prefix="/chat", tags=["chat"])


class Undone(BaseModel):
    """A ledger proposal taken back: the line that says so and its new state."""

    text: str
    proposal: dict


@router.post("/proposals/{pid}/undo", response_model=Undone,
             summary="Take back a ledger edit the chat made")
def undo(pid: str, paths: Writer, lang: str | None = None) -> Undone:
    """Undo a ledger proposal that was approved (`engine.undo_proposal`).

    The change is reversed through the book's journal, exactly as an undo
    from the portfolio API, and the thread gets a line saying so. A proposal
    this thread does not hold is a 404; one that is not an applied ledger edit
    (a watchlist action, a pending or already undone one) or whose rows were
    changed again since is a 409 naming why.
    """
    lang = (lang or _prefs(paths).get("language") or "en").strip().lower()
    try:
        reply = engine.undo_proposal(chat_path=paths.chat, db=paths.db,
                                     proposal_id=pid, lang=lang)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no proposal {pid} on this thread",
        ) from exc
    except engine.ProposalError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=exc.code) from exc
    return Undone(text=reply.text, proposal=dict(reply.proposal or {}))


# ---------------------------------------------------------- surface actions


class SurfacePress(BaseModel):
    """A2UI's client-to-server action, as its spec words it."""

    model_config = {"extra": "forbid"}

    name: str = Field(max_length=40)
    surfaceId: str = Field(max_length=80)  # noqa: N815 — A2UI's own field names
    sourceComponentId: str = Field(default="", max_length=80)  # noqa: N815
    timestamp: str = Field(default="", max_length=40)
    context: dict = {}

    @field_validator("context")
    @classmethod
    def _small(cls, value: dict) -> dict:
        if len(json.dumps(value, default=str)) > 2000:
            raise ValueError("an action's context is at most 2000 characters")
        return value


class ActionBody(BaseModel):
    model_config = {"extra": "forbid"}

    action: SurfacePress
    lang: str | None = Field(default=None, max_length=8)


class SurfaceUpdate(BaseModel):
    """What the surface should apply: A2UI v0.9 server messages."""

    messages: list[dict]


@router.post("/actions", response_model=SurfaceUpdate,
             summary="Press something on a surface the assistant drew")
def press(body: ActionBody, paths: SurfaceAction) -> SurfaceUpdate:
    """An A2UI action from a surface in the drawer, answered with the messages
    that update it. No model is asked, and nothing is stored but the one thing
    a button says it stores: a slider moving is the reader exploring, and the
    answer above it still says what it said.

    Four surfaces answer here: the what-if sale's slider (`chat/whatif.py`),
    re-run through the tax engine for the shares it now names; the rebalance
    slider (`chat/rebalance.py`), sized and taxed again for the weight it now
    names; a price chart's window chips (`chat/charts.py`), fetched again
    over the window picked; and the plan builder (`chat/plan_builder.py`),
    whose chips redraft the plan and whose Save stores it as the reader's
    plan, the one write here. An action this server has no handler for is a
    404, not a guess.
    """
    press_ = body.action
    lang = (body.lang or _prefs(paths).get("language") or "en").strip().lower()
    from stocks.i18n import translate

    def tr(key: str, **kw) -> str:
        return translate(key, lang, **kw)

    handler = {
        (whatif.SURFACE_ID, whatif.ACTION): _resell,
        (charts.SURFACE_ID, charts.ACTION): _rechart,
        (rebalance.SURFACE_ID, rebalance.ACTION): _reweigh,
        (plan_builder.SURFACE_ID, plan_builder.DRAFT): _redraft,
        (plan_builder.SURFACE_ID, plan_builder.SAVE): _keep_plan,
    }.get((press_.surfaceId, press_.name))
    if handler is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no action {press_.name} on {press_.surfaceId}",
        )
    return SurfaceUpdate(messages=handler(press_.context, paths, tr, lang))


def _resell(context: dict, paths: UserPaths, tr, lang: str) -> list[dict]:
    """The what-if sale again, for the shares the slider now names."""
    symbol = engine.clean_focus(str(context.get("ticker") or ""))
    try:
        shares = float(context.get("shares", ""))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="shares must be a number",
        ) from exc
    sale = whatif.simulate(db=paths.db, prefs_path=paths.prefs, ticker=symbol,
                           shares=shares) if symbol else None
    if sale is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"nothing of {symbol or 'that'} to sell, or no price for it",
        )
    return whatif.moved(sale, tr, lang)


def _reweigh(context: dict, paths: UserPaths, tr, lang: str) -> list[dict]:
    """The rebalance again, for the weight the slider now names."""
    symbol = engine.clean_focus(str(context.get("ticker") or ""))
    try:
        target = float(context.get("target", ""))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="target must be a number",
        ) from exc
    if not 0 <= target <= rebalance.CEILING:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"target must be 0 to {rebalance.CEILING:g}",
        )
    book = whatif.replay(db=paths.db, prefs_path=paths.prefs) if symbol else None
    tbl = engine.enriched_frame(paths.db, book.currency) if book else None
    moved = rebalance.build(book, tbl, symbol, target)
    if moved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no priced holding of {symbol or 'that'} to reweigh",
        )
    return rebalance.moved(moved, tr, lang)


def _plan_known(paths: UserPaths) -> plan_builder.Known:
    """What the plan builder knows of this account, read again on every press:
    a plan saved in another tab since the card was drawn is the one replaced."""
    from stocks.api.deps import reporting_currency
    from stocks.api.routes.prefs import _actual

    return plan_builder.known(_prefs(paths), _actual(paths), reporting_currency(paths))


def _redraft(context: dict, paths: UserPaths, tr, lang: str) -> list[dict]:
    """The draft again, for the answers the chips now hold."""
    return plan_builder.moved(_plan_known(paths), context, tr)


def _keep_plan(context: dict, paths: UserPaths, tr, lang: str) -> list[dict]:
    """Store the draft as the reader's plan, recomputed here from the answers.

    The plan is never read off the surface: the answers are, each checked
    against its choices, and `plan.suggest` turns them into the figures, so a
    client cannot save a plan the rule would not have drawn. Written through
    the form's own model (`PlanWrite`) and merge. Risk and horizon asked
    because the profile was never saved are kept there too: the reader just
    answered them.
    """
    import dataclasses
    from datetime import date

    from stocks.api.routes.prefs import PlanWrite
    from stocks.portfolio import plan as plans
    from stocks.portfolio.plan import PREFS_KEY
    from stocks.userprefs import load_profile

    for q, choices in plan_builder.CHOICES.items():
        if context.get(q) not in choices:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{q} must be one of {', '.join(choices)}",
            )
    try:
        plan_builder.amount_of(context.get(plan_builder.AMOUNT))
        plan_builder.cash_amount(context.get(plan_builder.INVESTABLE))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="amount must be a number",
        ) from exc
    prefs = _prefs(paths)
    known = _plan_known(paths)
    body = PlanWrite.model_validate(plan_builder.draft(known, context))
    raw = body.model_dump()
    # The draft states only the cash typed here; the emergency fund and the
    # rate saved in the form stay, and the block is dated as the form dates it.
    old = plans.load(prefs).cash
    kept = dataclasses.asdict(old) if old else {}
    raw["cash"] = plans.stamp_cash(
        {**kept, **{k: v for k, v in (raw.get("cash") or {}).items() if v is not None}},
        old,
        date.today(),
    )
    changes: dict = {PREFS_KEY: {**raw, "set": True}}
    profile = load_profile(prefs)
    if not profile["set"]:
        profile.pop("plan", None)
        changes["investor_profile"] = {
            **profile,
            plan_builder.RISK: context[plan_builder.RISK],
            plan_builder.HORIZON: context[plan_builder.HORIZON],
            "set": True,
        }
    accounts.update_prefs(paths.prefs, changes)
    obs.event("chat.plan_saved", replaced=known.replaces,
              profile=not profile["set"], contribution=body.contribution is not None)
    return plan_builder.saved(raw, tr)


def _rechart(context: dict, paths: UserPaths, tr, lang: str) -> list[dict]:
    """The chart's symbols again, over the window the chip picked.

    The symbols come back from the surface, so they are screened here as any
    other input: a symbol's own characters, or the book's own marker, at most
    the three a chart draws.
    """
    window = str(context.get("window") or "")
    if window not in charts.WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"window must be one of {', '.join(charts.WINDOWS)}",
        )
    raw = context.get("symbols")
    symbols = [
        charts.BOOK if str(s) == charts.BOOK else engine.clean_focus(str(s))
        for s in raw
    ] if isinstance(raw, list) else []
    symbols = [s for s in dict.fromkeys(symbols) if s]
    if not symbols or len(symbols) > charts.MAX_SERIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"symbols must be 1 to {charts.MAX_SERIES} tickers",
        )
    # The reader's own book is one of them when the chart was "how am I doing
    # against the S&P": priced again from this account's ledger, in its
    # reporting currency, never from anything the surface sent.
    base = engine.reporting_currency(_prefs(paths))
    book = charts.book_for(paths.db, base) if charts.BOOK in symbols else None
    chart = charts.build(symbols, window, book=book, base=base)
    if chart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no prices for {' '.join(symbols)} over {window}",
        )
    return charts.moved(chart, tr, lang)
