"""The dashboard's "Daily action" — one AI briefing per account per day.

What the reader would otherwise ask the assistant every morning, answered
before they ask. With no brief of their own, in three sections in a fixed
order:

  - **Portfolio**: the book's day, week and month against the index, with the
    month drawn (`daily_book`). Computed, never written.
  - **Today's alerts**: the price alerts the latest session crossed
    (`signals.ALERT_HIT`). An alert is a fact, so the card lists every one
    that fired whether or not the model wrote a line about it.
  - **To watch**: the few triggers worth a decision today, written by the
    model from the computed candidates (`signals.candidates`).

A reader who wrote a brief (`learnings`, kind "routine": "what moved my book,
this week's events, my insiders, review my kill criteria") gets the card
they asked for instead: the alerts that fired, then one section per line of
the brief, written from the data fetched for it (`daily_routines`). Only a
model can write those sections; without one the default card stands, and the
client says why (`brief`).

The headline ties them together: the book against the index, then the one or
two things that matter. There is no prompt to write — the card is there when
the page loads, which is the point of putting the assistant on the dashboard.

Three properties shape everything here:

  - It changes once a day. `action_day()` turns the card over at 09:00 in the
    reader's own zone (CUTOFF_HOUR), before the European open and while the US
    premarket is quoting; until then the previous day's card stands, stamped
    with its own date so nobody mistakes it for this morning's. One LLM call
    writes every section, and the card spends at most FREE_UNITS of the
    account's free allowance a day (`spend_unit`): that is what makes an
    always-on card affordable on the free chain, so the stored copy
    (auth.load_action / save_action) is authoritative and a reload never
    regenerates.

  - It never blocks the dashboard. Generation runs through
    engine.complete_attempts, so a dead key, a rate limit or a hung provider
    falls through to the next candidate and finally to `computed()` — the same
    facts rendered without a model. The card is always on screen; only its
    prose is optional.

  - It reads the numbers the page already computed. `build_facts()` takes the
    frames Home loaded for its own cards (enriched positions, the basket
    history, the earnings calendar, the 52-week scan), so the briefing costs no
    extra network work.

Headless by construction: paths and language come in as arguments, and
stocks/api/briefing.py is the layer over it.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from stocks import obs
from stocks.chat import engine, signals
from stocks.chat.daily.card import (
    _LANG_NAME,
    _WINDOW_KEYS,
    ALERTS,
    ALERTS_MAX,
    BRIEF_MISSED,
    BRIEF_PENDING,
    BRIEF_STATES,
    BRIEF_WRITTEN,
    BULLET_CHARS,
    CUTOFF_HOUR,
    EARNINGS_DAYS,
    FOCUS_MAX,
    FREE_UNITS,
    HEADLINE_CHARS,
    LINE_MAX_CHARS,
    MAX_BULLETS,
    MAX_SECTIONS,
    MIN_BULLETS,
    MOVERS_SHOWN,
    NOTE_CHARS,
    NOTE_ROWS,
    PAST_DAYS,
    PAST_SHOWN,
    RECENT_KEPT,
    SECTION_LINES,
    TIMEOUT_S,
    TITLE_CHARS,
    TODAY_SECTIONS,
    UNITS_KEY,
    UPGRADE_AFTER_S,
    UPGRADE_TRIES,
    WATCH,
    WEIGHTS_SHOWN,
    DailyAction,
    _clip,
    action_day,
    is_fresh,
    keyed_actions,
    offered,
    section_of,
    seen,
    wants_upgrade,
)
from stocks.chat.daily.facts import (
    build_facts,
)
from stocks.chat.daily.fallback import (
    _PLAN_KINDS,
    _action_line,
    _bank,
    _criterion_key,
    _criterion_slots,
    _flag,
    _money,
    _plan_line,
    _rate,
    _short_date,
    _short_line,
    _when,
    computed,
    dressed,
    go_of,
    with_today,
)
from stocks.chat.daily.instructions import (
    _HOUSE_RULES,
    _KINDS,
    _SHAPE,
    _brief_rows,
    prompt,
    talked_names,
)
from stocks.chat.daily.number_audit import (
    _NUM,
    _matches,
    _numbers,
    audit,
    figures,
)
from stocks.chat.daily.reply import (
    _bare,
    _sourced,
    _today_notes,
    parse,
)
from stocks.formatting import fmt_num

__all__ = [
    "ALERTS",
    "ALERTS_MAX",
    "BRIEF_MISSED",
    "BRIEF_PENDING",
    "BRIEF_STATES",
    "BRIEF_WRITTEN",
    "BULLET_CHARS",
    "CUTOFF_HOUR",
    "DailyAction",
    "EARNINGS_DAYS",
    "FOCUS_MAX",
    "FREE_UNITS",
    "HEADLINE_CHARS",
    "LINE_MAX_CHARS",
    "MAX_BULLETS",
    "MAX_SECTIONS",
    "MIN_BULLETS",
    "MOVERS_SHOWN",
    "NOTE_CHARS",
    "NOTE_ROWS",
    "PAST_DAYS",
    "PAST_SHOWN",
    "RECENT_KEPT",
    "SECTION_LINES",
    "TIMEOUT_S",
    "TITLE_CHARS",
    "TODAY_SECTIONS",
    "UNITS_KEY",
    "UPGRADE_AFTER_S",
    "UPGRADE_TRIES",
    "WATCH",
    "WEIGHTS_SHOWN",
    "_HOUSE_RULES",
    "_KINDS",
    "_LANG_NAME",
    "_NUM",
    "_SHAPE",
    "_action_line",
    "_bare",
    "_clip",
    "_detail_line",
    "_matches",
    "_money",
    "_numbers",
    "_short_line",
    "_sourced",
    "_today_notes",
    "action_day",
    "audit",
    "build_facts",
    "card_path",
    "computed",
    "dressed",
    "figures",
    "filed",
    "generate",
    "go_of",
    "is_fresh",
    "keyed_actions",
    "offered",
    "parse",
    "past_lines",
    "prompt",
    "record",
    "remembered",
    "section_of",
    "seen",
    "spend_unit",
    "talked_names",
    "thread_text",
    "thread_title",
    "to_store",
    "wants_upgrade",
    "with_today",
]


def generate(
    prefs: dict,
    profile: dict,
    facts: dict,
    lang: str,
    day: date,
    *,
    recent: list[str] | None = None,
    past: list[dict] | None = None,
    history: list[str] | None = None,
    timeout_s: float = TIMEOUT_S,
    spend_free=None,
    chat_path=None,
) -> DailyAction | None:
    """One card from the first provider that answers usefully, or None.

    Never raises: every failure — no provider, a spent allowance, a timeout, a
    reply that is not JSON — comes back as None so the caller falls through to
    `computed()`. `spend_free` defaults to the per-account counter, since the
    live app owns prefs.json and the card is generated from a user session.

    `chat_path` is the account's chat.json: with it the card reads what the
    chat knows (`prompt`'s `memories` and `talk`), under the same switches
    that govern the chat. The brief is left out of that memory: it is in
    `facts["brief"]`, with the data fetched for it.

    Every free unit goes through `spend_unit`, so the card's share of the
    allowance holds however many times a day it is asked for.
    """
    known = _tickers(facts)
    try:
        memories, talk = engine.user_memory(
            prefs, chat_path, talked_names(facts), routines=False
        )
        system, messages = prompt(facts, profile, lang, recent or [], past or [],
                                  memories=memories, talk=talk,
                                  history=history or [])
    except Exception:
        return None
    spend = spend_free or engine.spend_free_quota
    return engine.complete_attempts(
        prefs,
        system,
        messages,
        timeout_s,
        spend_free=lambda p: spend_unit(p, day, spend),
        accept=lambda raw: parse(
            raw, day=day, lang=lang, known=known, facts=facts
        ),
    )


def spend_unit(prefs: dict, day: date, spend=None) -> bool:
    """Spend one free unit on `day`'s card: one of its FREE_UNITS and, through
    `spend`, one of the account's own. False, spending nothing, once the card
    has had its share — the rest of the allowance is the chat's.

    One key, overwritten each day, rather than a key per day: the API merges
    counters into prefs.json key by key, and a dated key would never leave.
    """
    raw = prefs.get(UNITS_KEY)
    used = 0
    if isinstance(raw, dict) and raw.get("day") == day.isoformat():
        try:
            used = int(raw.get("used") or 0)
        except (TypeError, ValueError):
            used = 0
    if used >= FREE_UNITS:
        return False
    if not (spend or engine.spend_free_quota)(prefs):
        return False
    prefs[UNITS_KEY] = {"day": day.isoformat(), "used": used + 1}
    return True


def _tickers(facts: dict) -> set[str]:
    """Every symbol the facts mention — the allowlist `parse` filters focus
    against."""
    out: set[str] = set()
    rows = [r for key in ("actions", "top_weights", "movers", "earnings_soon", "at_52w")
            for r in facts.get(key) or []]
    for row in [*rows, *_brief_rows(facts)]:
        symbol = str(row.get("ticker") or "").strip().upper()
        if symbol:
            out.add(symbol)
    return out




def remembered(
    previous: DailyAction | None, headline: str, day: date | None = None
) -> list[str]:
    """The `recent` list to store with a new card: this headline in front of
    the ones before it, so tomorrow's prompt can be told not to repeat them.

    A stored card already carries its own headline at the head of `recent`, so
    chaining through it keeps the whole short history with no extra state —
    except when it is today's own card being replaced (`day`), whose headline
    the new one supersedes rather than follows.
    """
    past = list(previous.recent) if previous else []
    if previous and day is not None and previous.day == day.isoformat() and past:
        past = past[1:] if past[0] == previous.headline else past
    kept = [headline] + [h for h in past if h != headline]
    return [h for h in kept if h][:RECENT_KEPT]


def past_lines(
    previous: DailyAction | None, action: DailyAction, day: date
) -> list[dict]:
    """The `past` list to store: this card's lines in front of the previous
    days' (today's earlier card, if any, replaced), `PAST_DAYS` deep."""
    today = day.isoformat()
    horizon = (day - timedelta(days=PAST_DAYS)).isoformat()
    mine = [
        {"day": today, "key": i["key"], "line": i["line"]}
        for i in action.entries
        if i.get("line")
    ]
    older = [
        p for p in (previous.past if previous else [])
        if p.get("day") and p["day"] != today and p["day"] >= horizon
    ]
    return mine + older


def to_store(
    previous: DailyAction | None, action: DailyAction, facts: dict
) -> dict:
    """The dict to write to daily_action.json for a card the reader was shown.

    Written for a computed card as much as for a model's: memory is about
    what the reader saw, whoever wrote it. The facts ride along for the
    analysis behind each line, and `tries` counts the stand-ins a day has produced so
    `wants_upgrade` can stop asking.
    """
    day = date.fromisoformat(action.day)
    card = action.to_dict()
    card["recent"] = remembered(previous, action.headline, day)
    keys = [i["key"] for i in action.entries if i.get("key")]
    from stocks.chat import today_sections

    card["shown"] = seen(previous, facts, day, keys,
                         today_sections.memory(action.today))
    card["past"] = past_lines(previous, action, day)
    card["facts"] = facts
    card["analysis"] = {}
    if not action.from_model:
        same_day = (
            previous is not None
            and previous.day == action.day
            and not previous.from_model
        )
        card["tries"] = (previous.tries if same_day else 0) + 1
    return card


# -------------------------------------------------------------- the thread
# Every card the reader is shown is also filed in the chat, as a thread of its
# own (`auth.save_card_thread`): it is one assistant, and what it said on Home
# is something it said. The thread is what the card's "Ask" opens, so a
# question about a line is asked with the line above it; it joins the list of
# the reader's conversations once they open or write in it; and it is indexed
# like them, so the chat can recall what a card said when
# a message names it.


def card_path(chat_path: Path) -> Path:
    """The account's stored card, from its chat file: the two sit side by
    side in every account's data dir (`accounts.UserPaths`), and the chat
    engine only ever holds the chat's."""
    return Path(chat_path).with_name("daily_action.json")


def thread_title(day: str, lang: str) -> str:
    """"Daily action · 3 Oct" — the card's day, in the card's language."""
    from stocks.web.i18n import translate

    when = date.fromisoformat(day)
    return translate(
        "chat.daily_thread_title", lang,
        day=when.day, month=translate(f"home.month_{when.month}", lang),
    )


def thread_text(action: DailyAction) -> str:
    """The card as the chat turn it is filed as: headline, its lines, then
    each section of the brief under its title — so a follow-up in the thread
    can build on it."""
    lines = [f"- {i['line']}" for i in action.items] if action.sections else [
        f"- {e['line']}" for e in action.entries]
    for sec in action.sections:
        if lines:
            lines.append("")
        if sec.get("title"):
            lines.append(f"**{sec['title']}**")
        lines += [f"- {ln['line']}" for ln in sec["lines"]]
    head = action.headline.strip()
    return "\n".join([f"**{head}**", "", *lines] if head else lines)


def record(chat_path, action: DailyAction) -> str:
    """File `action` in the account's chat; the thread's id, "" on failure.

    Never raises: a card that could not be filed is still the card, and its
    "Ask" falls back to opening the assistant on whatever thread is active."""
    from stocks.web import auth

    try:
        return auth.save_card_thread(
            action.day, thread_title(action.day, action.lang),
            thread_text(action), chat_path,
        )
    except Exception as exc:  # noqa: BLE001
        obs.warn("daily_action.thread_unsaved", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        return ""


def filed(previous: DailyAction | None, action: DailyAction, chat_path) -> str:
    """The thread to store with a card about to be written — `record`'s, or
    when filing failed, the one the same day's card was already filed in."""
    cid = record(chat_path, action)
    if not cid and previous is not None and previous.day == action.day:
        return previous.thread
    return cid


# ------------------------------------------------------------------ see more
#
# The paragraph that says what happened behind one line, in templates. The
# analysis behind a line (chat/daily_analysis.py) opens with it when no model
# answers, and it is what "what happened" means there.


def _detail_line(action: dict, source: dict, lang: str, ccy: str) -> str:
    """One action's computed "what happened" paragraph."""
    from stocks.formatting import compact_money
    from stocks.web.i18n import has, translate

    kind = str(action.get("kind") or "")
    ticker = str(action.get("ticker") or "")
    key = f"home.daily_more_{kind}"

    def money(value) -> str:
        return _money(abs(float(value or 0.0)), ccy, lang).replace("+", "")

    def num(name: str, spec: str = ",.2f") -> str:
        return format(float(action.get(name) or 0.0), spec)

    if kind in (signals.CRITERION_HIT, signals.CRITERION_NEAR):
        return translate(_criterion_key(key, action), lang,
                         **_criterion_slots(action, lang))
    if kind in (signals.ALERT_HIT, signals.ALERT_NEAR):
        return translate(
            key, lang, ticker=ticker,
            rule=translate(f"home.daily_rule_{action.get('rule') or 'below'}", lang),
            level=num("level"), price=num("price"),
            gap=f"{fmt_num(float(action.get('gap_pct') or 0), 1, lang)}%",
        )
    if kind in _PLAN_KINDS:
        return _plan_line(action, lang, ccy) + " " + translate(key, lang)
    if kind == signals.FILING_FLAG:
        return translate(key, lang, ticker=ticker, form=action.get("form") or "",
                         date=_short_date(action.get("date")),
                         what=_flag(action, lang))
    if kind == signals.HARVEST:
        text = translate(
            key, lang, ticker=ticker, loss=money(action.get("loss")),
            pct=f"{fmt_num(float(action.get('pnl_pct') or 0), 1, lang, signed=True)}%",
            gain=money(action.get("gain_ytd")), offset=money(action.get("offset")),
        )
        window = str(action.get("repurchase_window") or "")
        if window in _WINDOW_KEYS:
            text += " " + translate(f"home.daily_window_{window}", lang)
        return text
    if kind == signals.EARNINGS:
        return translate(
            key if action.get("held", True) else f"{key}_watched", lang,
            ticker=ticker, when=_when(action.get("in_days"), lang),
            date=_short_date(action.get("date")),
        )
    if kind == signals.EARNINGS_RESULT:
        text = _action_line(action, lang, ccy)
        if source.get("revenue") is not None:
            symbol = _currency_sign(str(source.get("currency") or "USD"))
            text += " " + translate(
                "home.daily_more_earnings_result_revenue", lang,
                revenue=compact_money(float(source["revenue"]), symbol),
                yoy=(
                    f"{fmt_num(float(source['revenue_yoy_pct']), 1, lang, signed=True)}%"
                    if source.get("revenue_yoy_pct") is not None else "—"
                ),
            )
        if source.get("operating_margin_pct") is not None:
            text += " " + translate(
                "home.daily_more_earnings_result_margin", lang,
                margin=f"{fmt_num(float(source['operating_margin_pct']), 1, lang)}%",
            )
        return text + " " + translate(key, lang)
    if kind == signals.MACRO_EVENT:
        text = translate(
            key, lang, bank=_bank(action, lang),
            when=_when(action.get("in_days"), lang),
            date=_short_date(action.get("date")), rate=_rate(action, lang),
        )
        return _with_history(text, source, lang)
    if kind == signals.MACRO_RESULT:
        text = _action_line(action, lang, ccy) + " " + translate(key, lang)
        return _with_history(text, source, lang)
    if kind == signals.TAX_DEADLINE:
        body = f"earnings.tax_{action.get('deadline') or ''}_body"
        text = translate(body, lang, year=action.get("year") or "") if has(body) else ""
        return " ".join(
            t for t in (
                text,
                translate(
                    key, lang, when=_when(action.get("in_days"), lang),
                    date=_short_date(action.get("date")),
                ),
            ) if t
        )
    if kind == signals.TAX_YEAR_END:
        return translate(
            key, lang, end=_short_date(action.get("end")),
            when=_when(action.get("days_left"), lang),
            gain=_money(float(action.get("gain_ytd") or 0.0), ccy, lang),
            losses=money(action.get("open_losses")),
            gains=money(action.get("open_gains")),
        )
    if kind == signals.TAX_BRACKET:
        return translate(
            key, lang, rate=f"{fmt_num(float(action.get('rate_pct') or 0), 0, lang)}%",
            next=f"{fmt_num(float(action.get('next_rate_pct') or 0), 0, lang)}%",
            threshold=money(action.get("threshold")),
            gain=money(action.get("gain_ytd")), room=money(action.get("room")),
        )
    if kind == signals.REPURCHASE_CLEAR:
        return translate(
            key, lang, ticker=ticker, loss=money(action.get("loss")),
            sold=_short_date(action.get("sell_date")),
            date=_short_date(action.get("clear_date")),
        )
    if kind == signals.DRAWDOWN:
        return translate(
            key, lang, ticker=ticker,
            pct=f"{fmt_num(float(action.get('pnl_pct') or 0), 1, lang, signed=True)}%",
            amount=money(action.get("pnl")),
        )
    if kind == signals.CONCENTRATION:
        return translate(
            key, lang, ticker=ticker,
            weight=f"{fmt_num(float(action.get('weight_pct') or 0), 0, lang)}%",
        )
    if kind == signals.LOW_52W:
        return translate(
            key, lang, ticker=ticker, price=num("price"),
            gap=f"{fmt_num(float(action.get('gap_pct') or 0), 1, lang)}%",
        )
    if kind in (signals.MARKET, signals.SECTOR_TILT, signals.VS_BENCH, signals.FX):
        return _action_line(action, lang, ccy) + " " + translate(key, lang)
    return ""


def _with_history(text: str, source: dict, lang: str) -> str:
    """A rate paragraph with the bank's last move appended, when known."""
    from stocks.web.i18n import translate

    history = source.get("history") or []
    if len(history) < 2:
        return text
    last, before = history[-1], history[-2]
    return text + " " + translate(
        "home.daily_more_rate_history", lang,
        date=_short_date(last.get("date")),
        before=f"{fmt_num(float(before.get('rate') or 0), 2, lang)}%",
        rate=f"{fmt_num(float(last.get('rate') or 0), 2, lang)}%",
    )


def _currency_sign(code: str) -> str:
    from stocks.config import currency_symbol

    return currency_symbol(code)
