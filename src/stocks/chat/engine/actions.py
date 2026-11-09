"""What the chat runs inline before answering (sale simulation, charts,
income, reports, harvest, rebalance, plan) and the step line each leaves.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from stocks import llm, obs
from stocks.chat import (
    allocation,
    charts,
    clock,
    harvest,
    income,
    market,
    plan_builder,
    rebalance,
    reports,
    toolbox,
    whatif,
)
from stocks.chat.engine.book import (
    enriched_frame,
    reporting_currency,
)
from stocks.chat.engine.parallel import (
    in_parallel,
)

if TYPE_CHECKING:

    from stocks.chat.tools import Action
    from stocks.llm import ToolCall


def action_context(watchlist: Path) -> str:
    """What the action parser needs, headless: the watchlist (resolves
    company names to symbols) and existing groups. No 'current view' — there
    is none headless."""
    from stocks import watchlist as wl
    from stocks.config import load_watchlist

    bits = [f"Today: {clock.today().isoformat()}"]
    holds = load_watchlist(watchlist)
    if holds:
        bits.append("Watchlist: " + ", ".join(
            f"{h.ticker} ({h.name})" if h.name else h.ticker for h in holds))
    tags = wl.all_tags(watchlist)
    if tags:
        bits.append("Existing groups: " + ", ".join(tags))
    return "\n".join(bits)


def action_reply(act: Action, lang: str) -> str:
    """Localized confirmation line for an executed action (explicit lang).

    The per-tool wording lives with the tools (chat/tools.py); this only
    binds the recipient's language to the translator they hand it."""
    from stocks.chat import tools
    from stocks.i18n import translate

    return tools.reply(act, lambda key, **kw: translate(key, lang, **kw))


# A line carrying a percentage, as a pasted list's rows do.
_PCT_LINE_RE = re.compile(r"\d\s*%")


def pasted_report(message: str) -> bool:
    """The message is a list the reader pasted (the Review page's "Pregunta a
    la IA", a screener dump), not a one-thing question: three or more of its
    lines carry a percentage. The one-trade cards (sale, chart, mix, harvest,
    rebalance) read the first ticker and the first percentage they meet, so
    on a list they answer a question nobody asked — the 2026-10-20 triage
    (IA-02) found a Review critique turned into "rebalance FISV 42%"."""
    return sum(bool(_PCT_LINE_RE.search(line))
               for line in message.splitlines()) >= 3


def _simulate_sale(message: str, watchlist: Path, db: Path, prefs_path: Path,
                   focus: str, lang: str, told: Callable[[dict], None]) -> object:
    """A sale the message is contemplating, run through the tax engine
    (`chat/whatif.py`) — or None for a message that is not about selling
    something the reader holds. Told as a tool line while it runs: it is a
    replay of the whole ledger, and the wait should say what it is. A sale
    to offset gains, or to take a position to a weight, is the harvest's or
    the rebalance's question, sized and taxed there."""
    if (not whatif.wants(message) or harvest.wants(message)
            or rebalance.wants(message)):
        return None
    symbol = whatif.target(message, watchlist, focus)
    if not symbol:
        return None
    cid = f"tool_sale_{secrets.token_hex(4)}"
    told({"id": cid, "tool": "simulate_sale", "arg": symbol, "args": {"ticker": symbol}})
    try:
        sale = whatif.simulate(
            db=db, prefs_path=prefs_path, ticker=symbol,
            shares=lambda held: whatif.shares_asked(message, held),
        )
    except Exception as exc:  # noqa: BLE001 — the answer goes on without it
        obs.warn("chat.whatif_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        sale = None
    told({"id": cid, "tool": "simulate_sale", "arg": symbol,
          "args": {"ticker": symbol},
          "out": _sale_step(sale, lang)["out"] if sale else "-"})
    return sale


def _chart(message: str, prefs: dict, watchlist: Path, db: Path, focus: str,
           lang: str, told: Callable[[dict], None]) -> object:
    """The price chart the message asks for (`chat/charts.py`), or None for a
    message that asks for none or names nothing that could be priced. Told as
    a tool line while the closes download, like the what-if sale. The reader's
    own book is one of the lines when the message measures it ("¿cómo voy
    contra el S&P?"), priced from the ledger in the reporting currency. A
    pie of the book is the allocation donut's, not a price chart."""
    if not charts.wants(message) or allocation.wants(message):
        return None
    base = reporting_currency(prefs)
    symbols = charts.targets(message, market.watchlist_names(watchlist), focus,
                             base=base)
    if not symbols:
        return None
    window = charts.window_asked(message)
    cid = f"tool_chart_{secrets.token_hex(4)}"
    arg = _chart_arg(symbols, lang)
    args = {"symbols": symbols, "window": window}
    told({"id": cid, "tool": "price_chart", "arg": arg, "args": args})
    try:
        chart = charts.build(
            symbols, window, base=base,
            book=charts.book_for(db, base) if charts.BOOK in symbols else None)
    except Exception as exc:  # noqa: BLE001 — the answer goes on without it
        obs.warn("chat.chart_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        chart = None
    told({"id": cid, "tool": "price_chart", "arg": arg, "args": args,
          "out": _chart_step(chart, lang)["out"] if chart else "-"})
    return chart


def _allocation(message: str, prefs: dict, db: Path, lang: str,
                told: Callable[[dict], None]) -> object:
    """The book's split the message asks about (`chat/allocation.py`), or
    None. Told as a tool line: the sectors and countries of every fund are
    looked up, and the wait should say what it is."""
    if not allocation.wants(message) or not db.exists():
        return None
    by = allocation.dimension_asked(message)
    cid = f"tool_mix_{secrets.token_hex(4)}"
    told({"id": cid, "tool": "allocation", "arg": by, "args": {"by": by}})
    base = reporting_currency(prefs)
    try:
        mix = allocation.build(enriched_frame(db, base), by, base)
    except Exception as exc:  # noqa: BLE001 — the answer goes on without it
        obs.warn("chat.allocation_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        mix = None
    told({"id": cid, "tool": "allocation", "arg": by, "args": {"by": by},
          "out": _mix_step(mix, lang)["out"] if mix else "-"})
    return mix


def _reports_ahead(message: str, watchlist: Path, db: Path, lang: str,
                   told: Callable[[dict], None], journal: Path | None = None,
                   currency: str = "") -> object:
    """The report dates of the reader's names (`chat/reports.py`), or None
    for a message that does not ask when they report. Told as a tool line.
    Looking back, `journal` and `currency` add the exit rules and the book
    against the index (`reports.build`)."""
    if not reports.wants(message):
        return None
    days = reports.days_asked(message)
    back = reports.looks_back(message)
    cid = f"tool_reports_{secrets.token_hex(4)}"
    args = {"days": days, "past": True} if back else {"days": days}
    told({"id": cid, "tool": "upcoming_earnings", "arg": str(days), "args": args})
    try:
        ahead = reports.build(watchlist, db, days, back=back,
                              journal=journal, currency=currency)
    except Exception as exc:  # noqa: BLE001 — the answer goes on without it
        obs.warn("chat.reports_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        ahead = None
    told({"id": cid, "tool": "upcoming_earnings", "arg": str(days), "args": args,
          "out": _reports_step(ahead, lang)["out"] if ahead else "-"})
    return ahead


def _income(message: str, db: Path, prefs_path: Path, lang: str,
            told: Callable[[dict], None]) -> object:
    """The reader's dividend years (`chat/income.py`), or None for a message
    that does not ask about their dividends. Told as a tool line."""
    if not income.wants(message):
        return None
    cid = f"tool_income_{secrets.token_hex(4)}"
    told({"id": cid, "tool": "income_report", "arg": "", "args": {}})
    try:
        found = income.build(db, prefs_path)
    except Exception as exc:  # noqa: BLE001 — the answer goes on without it
        obs.warn("chat.income_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        found = None
    told({"id": cid, "tool": "income_report", "arg": "", "args": {},
          "out": _income_step(found, lang)["out"] if found else "-"})
    return found


def _income_step(found: income.Income, lang: str) -> dict:
    return {"tool": "income_report", "arg": "",
            "out": _tr("chat.step_income", lang, count=len(found.years))}


def _reports_step(ahead: reports.Ahead, lang: str) -> dict:
    if ahead.back:
        out = _tr("chat.step_reports_past", lang, count=len(ahead.printed),
                  days=ahead.days)
    else:
        out = _tr("chat.step_reports", lang, count=len(ahead.due), days=ahead.days)
    return {"tool": "upcoming_earnings", "arg": str(ahead.days), "out": out}


# Companies whose ticker page rides on a weighing question on the fixed path.
PAGE_TICKERS = 2
# A question that weighs a company: its multiple, its value, against another,
# or what the analysts make of it.
_WEIGHS_RE = re.compile(
    r"\bp/?e\b|\bper\b|\bpe ratio\b|valora|valuat|\bvalue[ds]?\b|\bvalor\b|"
    r"barat|cheap|\bcar[ao]s?\b|expensive|compar|\bvs\.?\b|\bversus\b|frente a|"
    r"m[uú]ltiplo|multiple|\bdcf\b|margen|margin|\bfcf\b|flujo de caja|"
    r"cash flow|analiz|analy[sz]|fundamental|\broic\b|\beps\b|\bbpa\b|"
    r"comprar|\bbuy\b|\bupside\b|potencial|"
    # What the analysts say is on the page too: asked without it, MSFT's
    # target came out ~580 against a 605 mean (prod eval 2026-10-29).
    r"precio objetivo|\btargets?\b|analista|analyst|consens|recomendaci|"
    r"recommendation|\bratings?\b",
    re.IGNORECASE,
)


def _pages(message: str, quotes: list, watchlist: Path, db: Path, prefs: dict,
           lang: str, told: Callable[[dict], None], timeout: float,
           tick: Callable[[], None] | None = None) -> str:
    """The ticker page's own figures (`toolbox._ticker_data`) for the
    companies a weighing question names, on the fixed path.

    A provider with no tool loop (Gemini) answered "MSFT vs GOOGL" and Meta's
    P/E from web ranges alone, with a quote and nothing else from the app
    (local review 2026-10-29): it never saw the KPI grid, the P/E history,
    the DCF or what the trailing year's earnings carry. The quoted names are
    the ones the message is about, so their pages ride on it, as the
    allocation's weights do. '' when the question does not weigh a company."""
    if not quotes or not _WEIGHS_RE.search(message):
        return ""
    from stocks.data.crypto import is_crypto

    codes = [q.ticker for q in quotes if not is_crypto(q.ticker)][:PAGE_TICKERS]
    if not codes:
        return ""
    run = toolbox.executor(toolbox.Context(
        watchlist=watchlist, db=db, currency=reporting_currency(prefs)))

    def one(n: int, code: str) -> str:
        cid, args = f"tool_page{n}", {"ticker": code}
        told({"id": cid, "tool": "ticker_data", "arg": code, "args": args})
        text = run("ticker_data", args)
        told({"id": cid, "tool": "ticker_data", "arg": code, "args": args,
              "out": _tr("chat.step_chars", lang, n=len(text))})
        return text

    found = in_parallel(*(lambda n=n, c=c: one(n, c) for n, c in enumerate(codes)),
                        timeout=timeout, tick=tick)
    blocks = [text for text in found if text]
    return ("\n\n---\n" + "\n\n".join(blocks)) if blocks else ""


# What this year's sales cost in tax, asked of the reader's own book.
_OWES_TAX_RE = re.compile(r"\b(?:hacienda|irpf|impuestos?|tributa\w*|tax(?:es)?|cgt)\b",
                          re.IGNORECASE)
_OWES_WHEN_RE = re.compile(
    r"\beste a[nñ]o\b|\bthis (?:tax )?year\b|\bventas?\b|\bvendid|"
    r"\bplusval|\bganancias\b|\bgains?\b|\bsales?\b|\bsold\b|\bpag|"
    r"\bdebo\b|\bowe\b|\bpay\b",
    re.IGNORECASE,
)


def _tax_year(message: str, watchlist: Path, db: Path, prefs: dict,
              prefs_path: Path) -> ToolCall | None:
    """This tax year's realised gains and estimated tax, on the fixed path,
    for a message that asks what the reader owes — the harvest tool's figures
    without its card, which answers another question.

    Prod eval 2026-10-29: "¿Cuánto tengo que pagar a Hacienda por mis ventas
    de este año?" came back as the IRPF brackets and "see the tax tab", with
    the 231 € the tab shows never reaching the model. None when the message
    does not ask. Told with the search and the quotes, as the lookup it is."""
    if not (_OWES_TAX_RE.search(message) and _OWES_WHEN_RE.search(message)):
        return None
    run = toolbox.executor(toolbox.Context(
        watchlist=watchlist, db=db, currency=reporting_currency(prefs),
        prefs_path=prefs_path))
    return llm.ToolCall("harvest_losses", {}, run("harvest_losses", {}))


def _harvest(message: str, db: Path, prefs_path: Path, lang: str,
             told: Callable[[dict], None]) -> object:
    """The losses that would offset this year's gains (`chat/harvest.py`), or
    None for a message that does not ask. A replay per candidate, told."""
    if not harvest.wants(message):
        return None
    cid = f"tool_harvest_{secrets.token_hex(4)}"
    told({"id": cid, "tool": "harvest_losses", "arg": "", "args": {}})
    try:
        book = whatif.replay(db=db, prefs_path=prefs_path)
        found = harvest.build(
            book, enriched_frame(db, book.currency) if book else None)
    except Exception as exc:  # noqa: BLE001 — the answer goes on without it
        obs.warn("chat.harvest_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        found = None
    told({"id": cid, "tool": "harvest_losses", "arg": "", "args": {},
          "out": _harvest_step(found, lang)["out"] if found else "-"})
    return found


def _rebalance(message: str, watchlist: Path, db: Path, prefs_path: Path,
               focus: str, lang: str, told: Callable[[dict], None]) -> object:
    """The trade that takes a held position to the weight the message names
    (`chat/rebalance.py`), taxed like the what-if sale, or None."""
    if not rebalance.wants(message):
        return None
    symbol = whatif.target(message, watchlist, focus)
    if not symbol:
        return None
    target = rebalance.target_asked(message)
    cid = f"tool_rebalance_{secrets.token_hex(4)}"
    args = {"ticker": symbol, "target": target}
    told({"id": cid, "tool": "rebalance", "arg": symbol, "args": args})
    try:
        book = whatif.replay(db=db, prefs_path=prefs_path)
        moved = rebalance.build(
            book, enriched_frame(db, book.currency) if book else None, symbol, target)
    except Exception as exc:  # noqa: BLE001 — the answer goes on without it
        obs.warn("chat.rebalance_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        moved = None
    told({"id": cid, "tool": "rebalance", "arg": symbol, "args": args,
          "out": _rebalance_step(moved, lang)["out"] if moved else "-"})
    return moved


def _plan_builder(message: str, prefs: dict, db: Path, lang: str,
                  told: Callable[[dict], None]) -> object:
    """What the app knows toward the reader's plan, for the interview the
    message asks for (`chat/plan_builder.py`), or None. Today's mix by
    asset type is read off the Home frame, so the card does not ask how the
    book leans."""
    if not plan_builder.wants(message):
        return None
    from stocks.portfolio import plan as plans

    cid = f"tool_plan_{secrets.token_hex(4)}"
    told({"id": cid, "tool": "plan_builder", "arg": "", "args": {}})
    base = reporting_currency(prefs)
    shares: dict[str, float] = {}
    try:
        tbl = enriched_frame(db, base) if db.exists() else None
        if tbl is not None and not tbl.empty and "weight" in tbl:
            from stocks import loaders

            shares = plans.buckets(tbl["weight"].to_dict(), loaders.asset_kind)
    except Exception as exc:  # noqa: BLE001 — the card asks without today's mix
        obs.warn("chat.plan_builder_mix_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
    known = plan_builder.known(prefs, shares, base)
    obs.event("chat.plan_builder", asked=len(plan_builder.questions(known)),
              priced=bool(shares), replaces=known.replaces)
    told({"id": cid, "tool": "plan_builder", "arg": "", "args": {},
          "out": _plan_step(known, lang)["out"]})
    return known


def _plan_step(known: plan_builder.Known, lang: str) -> dict:
    return {"tool": "plan_builder", "arg": "",
            "out": _tr("chat.step_plan", lang,
                       count=len(plan_builder.questions(known)))}


def _mix_step(mix: allocation.Mix, lang: str) -> dict:
    return {"tool": "allocation", "arg": mix.by,
            "out": _tr("chat.step_mix", lang, count=mix.positions,
                       effective=f"{mix.effective:.1f}")}


def _harvest_step(found: harvest.Harvest, lang: str) -> dict:
    return {"tool": "harvest_losses", "arg": "",
            "out": _tr("chat.step_harvest", lang, count=len(found.candidates),
                       saving=f"{found.saving:,.0f} {found.currency}")}


def _rebalance_step(moved: rebalance.Reweigh, lang: str) -> dict:
    return {"tool": "rebalance", "arg": f"{moved.ticker} {moved.target:g}%",
            "out": _tr("chat.step_rebalance", lang,
                       amount=f"{moved.amount:+,.0f} {moved.currency}")}


def _chart_arg(symbols: list[str], lang: str) -> str:
    return " ".join(_tr("chat.chart_book", lang) if s == charts.BOOK else s
                    for s in symbols)


def _chart_step(chart: charts.Chart, lang: str) -> dict:
    return {"tool": "price_chart", "arg": _chart_arg(chart.symbols, lang),
            "out": _tr("chat.step_chart", lang,
                       window=_tr(f"chat.chart_window_{chart.window}", lang))}


def _sale_step(sale: whatif.Scenario, lang: str) -> dict:
    return {"tool": "simulate_sale", "arg": f"{sale.shares:g} {sale.ticker}",
            "out": _tr("chat.step_whatif", lang,
                       tax=f"{sale.extra_tax:+,.0f} {sale.currency}")}


def _tr(key: str, lang: str, **slots) -> str:
    from stocks.i18n import translate

    return translate(key, lang, **slots)
