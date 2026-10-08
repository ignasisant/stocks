"""Edits to the ledger asked for in the chat: drafted here, approved by the reader.

The classifier (`chat/tools.py` BOOK) only says what the reader means — which
rows, in their words, and what should become of them. Everything after that is
decided here, with the book in hand and no model in the loop:

* the rows are found (`edits.select`: a company however each broker spelled
  it, a broker, a day or a range, a row number the reader quoted);
* the edit is built as `stocks.portfolio.edits` operations, or taken whole
  from the doctor when the reader asks for the book to be checked;
* it is planned, so the turn can say what it does to the holdings and to each
  year's realized gain before anything is written.

The result is a `Draft`: words, and — when there is something to approve — the
ledger half of a proposal (`book`), which the engine files on the asking turn
exactly like a watchlist proposal. Approving it commits the plan under its
token (`apply`), so the book that is changed is the book that was shown; a
book that moved in between is refused and nothing is written.

Nothing here runs a model, and nothing here writes except `apply` and `undo`.
"""

from __future__ import annotations

import difflib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from stocks.chat import clock
from stocks.chat.tools import Action
from stocks.portfolio import demo, doctor, edits, ledger, transfers
from stocks.portfolio.ledger import Transaction

Translate = Callable[..., str]

SHOWN = 12  # rows a reply lists before it says how many more there are
MAX_ROWS = 50  # rows one chat edit may touch; more than that is an import's job
_FINDINGS = 5  # problems a book check lists


class Refused(Exception):
    """An approved edit that could not be written. `code` is the locale key."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Draft:
    """What a ledger request comes to: the words, and what to approve.

    `book` is None for an answer with nothing to approve — a listing, a
    question back ("which of these three?"), a healthy book. Otherwise it is
    the proposal's ledger payload: `ops` and the plan's `token`, or `undo`
    with a change id, plus the `summary` the journal files it under.
    """

    text: str
    book: dict | None = None


@dataclass(frozen=True)
class _Ctx:
    db: Path
    tr: Translate
    resolve: transfers.Resolver | None
    today: str
    currency: str


def resolver() -> transfers.Resolver:
    """The app's label lookup (ISIN or broker code -> Yahoo symbol), cached."""
    from stocks import identity

    return identity.yahoo_symbol


def draft(
    act: Action,
    *,
    db: Path,
    translate: Translate,
    resolve: transfers.Resolver | None = None,
    today: str | None = None,
    currency: str = "EUR",
) -> Draft:
    """What `act` would do to the book at `db`, put as the reader will read it."""
    ctx = _Ctx(db=db, tr=translate, resolve=resolve,
               today=today or clock.today().isoformat(), currency=currency)
    rows = demo.without(ledger.all_transactions(db))
    return _DRAFTS[act.kind](act, rows, ctx)


# ------------------------------------------------------------------ drafting


def _selector(act: Action) -> edits.Selector:
    a = act.args
    day = a.get("date", "")
    return edits.Selector(
        ticker=act.ticker,
        broker=a.get("broker", ""),
        action=a.get("trade", ""),
        since=day or a.get("since", ""),
        until=day or a.get("until", ""),
        quantity=a.get("quantity"),
        price=a.get("price"),
        ids=tuple(a.get("ids") or ()),
    )


def _show(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    sel = _selector(act)
    found = edits.select(rows, sel, ctx.resolve) if not sel.empty() else rows
    if not found:
        return Draft(ctx.tr("chat.book_none"))
    return Draft("\n".join([ctx.tr("chat.book_rows", count=len(found)),
                            *_listing(found, ctx)]))


def _edit(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    a = act.args
    fields = {name: a[f"new_{name}"] for name in ("date", "quantity", "price", "fee")
              if f"new_{name}" in a}
    if not fields:
        return Draft(ctx.tr("chat.book_edit_what"))
    found = _found(act, rows, ctx)
    if isinstance(found, Draft):
        return found
    if len(found) > 1:
        return Draft("\n".join([ctx.tr("chat.book_which", count=len(found)),
                                *_listing(found, ctx)]))
    (tx,) = found
    summary = ctx.tr("chat.book_summary_edit", id=tx.id, ticker=tx.ticker)
    return _planned([{"op": "update", "id": tx.id, "fields": fields}], summary, ctx)


def _delete(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    found = _found(act, rows, ctx)
    if isinstance(found, Draft):
        return found
    summary = ctx.tr("chat.book_summary_delete", count=len(found),
                     ticker=_names(found))
    return _planned([{"op": "delete", "ids": [t.id for t in found]}], summary, ctx)


def _add(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    a = act.args
    if not {"trade", "quantity", "price"} <= set(a):
        return Draft(ctx.tr("chat.book_add_what", ticker=act.ticker))
    same = [t.currency for t in rows if t.ticker == act.ticker]
    currency = a.get("currency") or (
        Counter(same).most_common(1)[0][0] if same else ctx.currency
    )
    row = {
        "date": a.get("date") or ctx.today,
        "ticker": act.ticker,
        "action": a["trade"],
        "quantity": a["quantity"],
        "price": a["price"],
        "currency": currency,
        "fee": a.get("fee", 0.0),
        "note": a.get("broker", ""),
    }
    summary = ctx.tr("chat.book_summary_add", trade=_trade(a["trade"], ctx),
                     quantity=_n(a["quantity"]), ticker=act.ticker,
                     price=_n(a["price"]), currency=currency, date=row["date"])
    return _planned([{"op": "add", "row": row}], summary, ctx)


def _rename(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    to = act.args.get("to", "")
    if not to:
        return Draft(ctx.tr("chat.book_rename_what", ticker=act.ticker))
    broker = act.args.get("broker", "")
    # The label as stored first: renaming "SAN" must not sweep up "SAN.PA"
    # because the two share a root. The generous match is the fallback for a
    # reader who named the company rather than the label.
    found = [t for t in rows if t.ticker == act.ticker
             and (not broker or transfers._broker(t) == broker)]
    if not found:
        found = edits.select(rows, edits.Selector(ticker=act.ticker, broker=broker),
                             ctx.resolve)
    found = [t for t in found if t.ticker != to]
    if not found:
        return Draft(ctx.tr("chat.book_none"))
    if len(found) > MAX_ROWS:
        return Draft(ctx.tr("chat.book_too_many", count=len(found), most=MAX_ROWS))
    summary = ctx.tr("chat.book_summary_rename", count=len(found),
                     ticker=_names(found), to=to)
    return _planned([{"op": "relabel", "ids": [t.id for t in found], "to": to}],
                    summary, ctx)


def _transfer(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    want = act.ticker
    broker = act.args.get("broker", "")
    to_broker = act.args.get("to_broker", "")
    for f in doctor.scan(rows, ctx.resolve):
        if f.kind != "transfer":
            continue
        d = f.detail
        named = {d["ticker_out"], d["ticker_in"]}
        if want not in named and want.split(".")[0] not in {
            n.split(".")[0] for n in named
        }:
            continue
        if broker and d["broker_out"] != broker:
            continue
        if to_broker and d["broker_in"] != to_broker:
            continue
        return _planned(f.fix, _finding_summary(f, ctx), ctx)
    return Draft(ctx.tr("chat.book_no_transfer", ticker=want))


def _move(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    a = act.args
    source, target = a.get("broker", ""), a.get("to_broker", "")
    if not source or not target or source == target:
        return Draft(ctx.tr("chat.book_move_what", ticker=act.ticker))
    there = edits.select(rows, edits.Selector(ticker=act.ticker, broker=source),
                         ctx.resolve)
    held = {k: s for k, s in edits._replay(there).items() if s.held > 1e-9}
    if len(held) != 1:
        return Draft(ctx.tr("chat.book_nothing_held", ticker=act.ticker,
                            broker=source))
    ((label, currency), state), = held.items()
    quantity = min(a.get("quantity") or state.held, state.held)
    basis = state.cost / state.held
    day = a.get("date") or ctx.today

    def leg(action: str, broker: str) -> dict:
        return {"op": "add", "row": {
            "date": day, "ticker": label, "action": action, "quantity": quantity,
            "price": round(basis, 6), "currency": currency, "fee": 0.0,
            "note": broker,
        }}

    summary = ctx.tr("chat.book_summary_move", quantity=_n(quantity), ticker=label,
                     broker=source, to_broker=target, date=day)
    return _planned([leg("transfer_out", source), leg("transfer_in", target)],
                    summary, ctx)


def _fee_in_coins_for(
    ticker: str, rows: list[Transaction], ctx: _Ctx
) -> Draft | None:
    """The part of the doctor's fee-in-coins fix that empties `ticker`, or
    None when its leftover is not the fees' coins."""
    mine = {t.id for t in edits.select(rows, edits.Selector(ticker=ticker),
                                       ctx.resolve)}
    for f in doctor.scan(rows, ctx.resolve):
        if f.kind != "fee_in_coins":
            continue
        labels = [lb for lb in f.detail["closed"]
                  if any(t.ticker == lb and t.id in mine for t in rows)]
        ops = [op for op in f.fix if op["id"] in mine]
        if labels and ops:
            summary = ctx.tr("chat.book_summary_fee_in_coins", count=len(ops),
                             tickers=", ".join(labels))
            return _planned(ops, summary, ctx)
    return None


def _close(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    """A position the reader emptied that the book still holds some of.

    The leftover is booked as sold: on the day and at the price of the sale
    that emptied it (the reader's, else the book's last sale after its last
    purchase), so the realized gain moves by what that remainder really was.
    The rows that put it there stay as they are — a sale is what happened at
    the broker, and the card shows its effect on the year before it is kept.

    Unless the doctor knows where the leftover came from: Revolut crypto buys
    booked with the fee's coins still in them. Then the fix is to those buys
    (`doctor._fee_in_coins`), which corrects the cost too, not a sale that
    never happened.
    """
    fee = _fee_in_coins_for(act.ticker, rows, ctx)
    if fee is not None:
        return fee
    found = edits.select(rows, edits.Selector(ticker=act.ticker), ctx.resolve)
    # A remainder in float noise is no position: 44M coins bought and sold
    # leave 4e-9 behind, which no sale can take without "exceeding" it.
    bought = sum(t.quantity for t in found if t.action in ("buy", "transfer_in"))
    held = {k: s for k, s in edits._replay(found).items()
            if s.held > 1e-12 * max(bought, 1000.0)}
    if not found:
        # Not "the book has none": the name may be spelled another way there.
        return Draft(ctx.tr("chat.book_close_unknown", ticker=act.ticker,
                            near=_nearest(act.ticker, rows)))
    if not held:
        return Draft(ctx.tr("chat.book_nothing_left", ticker=act.ticker))
    a = act.args
    ops: list[dict] = []
    for (label, currency), state in held.items():
        mine = [t for t in found if t.currency == currency]
        last_buy = max((t.date for t in mine if t.action in ("buy", "transfer_in")),
                       default="")
        sale = next((t for t in sorted(mine, key=lambda t: (t.date, t.id or 0),
                                       reverse=True)
                     if t.action == "sell" and t.date >= last_buy), None)
        price = a.get("price", sale.price if sale else None)
        if price is None:
            return Draft(ctx.tr("chat.book_close_what", ticker=label))
        ops.append({"op": "add", "row": {
            "date": a.get("date") or (sale.date if sale else ctx.today),
            "ticker": label, "action": "sell", "quantity": state.held,
            "price": price, "currency": currency, "fee": 0.0,
            "note": sale.note if sale else "",
        }})
    summary = ctx.tr("chat.book_summary_close", ticker=_names(found),
                     quantity=_n(sum(s.held for s in held.values())))
    return _planned(ops, summary, ctx)


def _nearest(ticker: str, rows: list[Transaction], limit: int = 5) -> str:
    """The held symbols closest to what the reader typed, as a list to read.

    Falls back to the first few held ones when nothing resembles it."""
    held = sorted({label for (label, _cur), s in edits._replay(rows).items()
                   if s.held > 1e-9})
    if not held:
        return "—"
    want = ticker.strip().upper()
    root = edits._root(want)
    near = [h for h in held if root in h or edits._root(h) in want]
    near += [h for h in difflib.get_close_matches(want, held, n=limit, cutoff=0.5)
             if h not in near]
    return ", ".join((near or held)[:limit])


def _check(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    found = doctor.scan(rows, ctx.resolve)
    if act.ticker:
        ids = {t.id for t in edits.select(
            rows, edits.Selector(ticker=act.ticker), ctx.resolve)}
        found = [f for f in found if ids & set(f.ids)]
    if not found:
        return Draft(ctx.tr("chat.book_healthy"))
    lines = [ctx.tr("chat.book_found", count=len(found))]
    lines += [f"- {_finding_line(f, ctx)}" for f in found[:_FINDINGS]]
    fixable = next((f for f in found if f.fix), None)
    if fixable is None:
        return Draft("\n".join(lines))
    planned = _planned(fixable.fix, _finding_summary(fixable, ctx), ctx)
    return Draft("\n".join([*lines, "", planned.text]), planned.book)


def _undo(act: Action, rows: list[Transaction], ctx: _Ctx) -> Draft:
    last = edits.last_undoable(ctx.db)
    if last is None:
        return Draft(ctx.tr("chat.book_nothing_to_undo"))
    summary = ctx.tr("chat.book_summary_undo",
                     summary=last.summary or ctx.tr("chat.book_change", id=last.id),
                     when=last.at[:10])
    lines = [ctx.tr("chat.propose_book", summary=summary),
             *_changes(last.changes, ctx, undoing=True)]
    return Draft("\n".join(lines), {"undo": last.id, "summary": summary})


_DRAFTS: dict[str, Callable[[Action, list[Transaction], _Ctx], Draft]] = {
    "show_transactions": _show,
    "edit_transaction": _edit,
    "delete_transactions": _delete,
    "add_transaction": _add,
    "rename_security": _rename,
    "mark_transfer": _transfer,
    "move_position": _move,
    "close_position": _close,
    "check_book": _check,
    "undo_change": _undo,
}


def _found(act: Action, rows: list[Transaction], ctx: _Ctx) -> list[Transaction] | Draft:
    """The rows a singular or plural edit names, or the reply that says why not."""
    sel = _selector(act)
    if sel.empty():
        return Draft(ctx.tr("chat.book_say_which"))
    found = edits.select(rows, sel, ctx.resolve)
    if not found:
        return Draft(ctx.tr("chat.book_none"))
    if len(found) > MAX_ROWS:
        return Draft(ctx.tr("chat.book_too_many", count=len(found), most=MAX_ROWS))
    return found


def _planned(ops: list[dict], summary: str, ctx: _Ctx) -> Draft:
    """The edit planned on the book as it is now, worded with its impact."""
    try:
        plan = edits.plan(ops, ctx.db)
    except edits.EditError as err:
        return Draft(ctx.tr("chat.book_refused", reason=str(err)))
    if not plan.changes:
        return Draft(ctx.tr("chat.book_no_change"))
    if plan.problems:
        return Draft(ctx.tr("chat.book_breaks", reason=plan.problems[0]))
    lines = [ctx.tr("chat.propose_book", summary=summary),
             *_changes(plan.changes, ctx), "", *_impact(plan, ctx)]
    return Draft("\n".join(lines), {
        "ops": plan.ops,
        "token": plan.token,
        "summary": summary,
        "impact": impact(plan),
    })


# ------------------------------------------------------------------- applying


def apply(offer: dict, *, db: Path, source: str, translate: Translate) -> str:
    """Write an approved proposal's edit; return the line that says it is done.

    Records the change's id on the offer (`book.change`) so the card can offer
    its undo. Raises Refused, writing nothing, when the book moved since the
    plan or the change to undo has been built on since.
    """
    book = offer["book"]
    if "undo" in book:
        try:
            edits.undo(int(book["undo"]), path=db)
        except edits.Conflict as err:
            raise Refused("chat.book_undo_conflict", str(err)) from err
        except (LookupError, edits.EditError) as err:
            raise Refused("chat.action_gone", str(err)) from err
        return translate("chat.book_undone", summary=book.get("summary", ""))
    try:
        done = edits.commit(book["ops"], book["token"], source=source,
                            summary=book.get("summary", ""), path=db)
    except edits.Stale as err:
        raise Refused("chat.book_stale", str(err)) from err
    except edits.EditError as err:
        raise Refused("chat.action_invalid", str(err)) from err
    book["change"] = done.id
    return translate("chat.book_done", summary=book.get("summary", ""))


def undo(offer: dict, *, db: Path, translate: Translate) -> str:
    """Take back an applied proposal's change; return the line that says so."""
    change = (offer.get("book") or {}).get("change")
    if change is None:
        raise Refused("chat.action_gone")
    try:
        edits.undo(int(change), path=db)
    except edits.Conflict as err:
        raise Refused("chat.book_undo_conflict", str(err)) from err
    except (LookupError, edits.EditError) as err:
        raise Refused("chat.action_gone", str(err)) from err
    return translate("chat.book_undone", summary=offer["book"].get("summary", ""))


# -------------------------------------------------------------------- wording


def impact(plan: edits.Plan) -> dict:
    """The plan's effect as the card's figures: positions, and gain per year."""
    realized: dict[str, dict[str, float]] = {}
    for e in plan.effects:
        for year in sorted(set(e.realized_before) | set(e.realized_after)):
            delta = e.realized_after.get(year, 0.0) - e.realized_before.get(year, 0.0)
            if abs(delta) >= 0.005:
                per = realized.setdefault(year, {})
                per[e.currency] = round(per.get(e.currency, 0.0) + delta, 2)
    return {
        "positions": [plan.positions_before, plan.positions_after],
        "realized": realized,
        "held": [
            {"ticker": e.ticker, "before": e.held_before, "after": e.held_after}
            for e in plan.effects
            if abs(e.held_before - e.held_after) > 1e-6
        ],
    }


def _impact(plan: edits.Plan, ctx: _Ctx) -> list[str]:
    figures = impact(plan)
    lines = []
    before, after = figures["positions"]
    if before != after:
        lines.append(ctx.tr("chat.book_impact_positions", before=before, after=after))
    for h in figures["held"]:
        lines.append(ctx.tr("chat.book_impact_held", ticker=h["ticker"],
                            before=_n(h["before"]), after=_n(h["after"])))
    for year, per in figures["realized"].items():
        for currency, delta in per.items():
            lines.append(ctx.tr("chat.book_impact_realized", year=year,
                                delta=f"{delta:+,.2f}", currency=currency))
    return lines or [ctx.tr("chat.book_impact_none")]


def _n(value: float) -> str:
    return format(value, ".10g")


def _trade(action: str, ctx: _Ctx) -> str:
    return ctx.tr(f"import.action_{action}")


def _names(rows: list[Transaction]) -> str:
    return ", ".join(sorted({t.ticker for t in rows}))


def _line(row: dict, ctx: _Ctx, tx_id: int | None) -> str:
    broker = str(row.get("note") or "").split(" ")[0]
    head = f"#{tx_id} · " if tx_id is not None and tx_id > 0 else ""
    fee = f" (+{_n(row['fee'])})" if row.get("fee") else ""
    return (f"{head}{row['date']} · {_trade(row['action'], ctx)} "
            f"{_n(row['quantity'])} {row['ticker']} × {_n(row['price'])} "
            f"{row['currency']}{fee}" + (f" · {broker}" if broker else ""))


def _listing(rows: list[Transaction], ctx: _Ctx) -> list[str]:
    shown = rows[-SHOWN:]
    lines = [f"- {_line(edits._fields(t), ctx, t.id)}" for t in shown]
    if len(rows) > SHOWN:
        lines.insert(0, ctx.tr("chat.book_more", count=len(rows) - SHOWN))
    return lines


def _changes(changes: list[edits.RowChange], ctx: _Ctx, *,
             undoing: bool = False) -> list[str]:
    """One line per row an edit touches; an undo reads each one backwards."""
    lines = []
    for c in changes[:SHOWN]:
        before, after = (c.after, c.before) if undoing else (c.before, c.after)
        if before is None and after is not None:
            lines.append(f"+ {_line(after, ctx, None)}")
        elif after is None and before is not None:
            lines.append(f"− {_line(before, ctx, c.id)}")
        elif before is not None and after is not None:
            moved = [
                f"{ctx.tr(f'chat.book_field_{k}')} {_value(k, before[k], ctx)} → "
                f"{_value(k, after[k], ctx)}"
                for k in edits.FIELDS if before.get(k) != after.get(k)
            ]
            lines.append(f"~ #{c.id} {before['ticker']}: " + ", ".join(moved))
    if len(changes) > SHOWN:
        lines.append(ctx.tr("chat.book_more", count=len(changes) - SHOWN))
    return lines


def _value(key: str, value, ctx: _Ctx) -> str:
    if key == "action":
        return _trade(str(value), ctx)
    if isinstance(value, float):
        return _n(value)
    return str(value) if value not in ("", None) else "—"


def _finding_line(f: doctor.Finding, ctx: _Ctx) -> str:
    d = f.detail
    if f.kind == "fee_in_coins":
        return ctx.tr("chat.book_finding_fee_in_coins", count=d["buys"],
                      tickers=", ".join(d["coins"]))
    if f.kind == "transfer":
        return ctx.tr("chat.book_finding_transfer", ticker=f.ticker,
                      broker_out=d["broker_out"], broker_in=d["broker_in"],
                      gain=f"{d['phantom_gain']:,.2f}", currency=d["currency"])
    if f.kind == "two_labels":
        return ctx.tr("chat.book_finding_two_labels", labels=", ".join(d["labels"]))
    if f.kind == "duplicate":
        return ctx.tr("chat.book_finding_duplicate", ticker=f.ticker, date=d["date"],
                      broker=d["broker_dropped"])
    return ctx.tr("chat.book_finding_oversold", ticker=f.ticker)


def _finding_summary(f: doctor.Finding, ctx: _Ctx) -> str:
    d = f.detail
    if f.kind == "fee_in_coins":
        return ctx.tr("chat.book_summary_fee_in_coins", count=d["buys"],
                      tickers=", ".join(d["coins"]))
    if f.kind == "transfer":
        return ctx.tr("chat.book_summary_transfer", ticker=f.ticker,
                      broker_out=d["broker_out"], broker_in=d["broker_in"])
    if f.kind == "two_labels":
        return ctx.tr("chat.book_summary_rename", count=len(f.ids),
                      ticker=", ".join(d["labels"][1:]), to=f.ticker)
    return ctx.tr("chat.book_summary_duplicate", ticker=f.ticker, date=d["date"],
                  broker=d["broker_dropped"])
