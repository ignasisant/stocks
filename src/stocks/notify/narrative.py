"""Optional LLM lines for the notification jobs — digest highlight, alert note.

Provider resolution, first success wins:
  1. The user's own BYOK key (Fernet-encrypted in prefs.json, same sliding
     90-day TTL the chat honours) — their key, their billing, their provider
     choice. The crons only *read* the key: they never slide the window, so
     an account that stopped chatting still goes cold on schedule.
  2. The operator's free chain ([free_llm] secrets / FREE_LLM_* env), spent
     against the process-wide daily pot (see _complete).
  3. None — the notification ships computed-only.

Everything here is sandboxed: any exception or a hard timeout falls through
to the next step. A digest or an alert must never fail, or even stall,
because of an LLM.
"""

from __future__ import annotations

import json
import re

from stocks.chat import engine

_TTL = engine.BYOK_TTL  # the shared "remembered for 90 days, sliding" promise
_LANG_NAME = {"en": "English", "es": "Spanish"}
MAX_CHARS = 300
# How many alerts the narration call is shown. A watchlist that fires twenty
# rules at once is a market-wide day, not twenty stories — the first few carry
# the point and the rest only cost tokens.
ALERTS_SHOWN = 8

# BYOK decryption and provider resolution live in the shared chat engine now
# (stocks/chat/engine.py); these names stay for the callers and tests.
_decrypt_byok = engine.decrypt_byok
_attempts = engine.attempts


# ------------------------------------------------------------------ prompts


def _persona(lang: str, task: str) -> str:
    return (
        "You are the portfolio assistant for TopStocks, a stock-tracking app. "
        f"{task} in {_LANG_NAME.get(lang, 'English')}. Plain text only: no "
        "markdown, no emoji, no preamble."
    )


def _prompt(data, lang: str, recent: list[str]) -> tuple[str, list[dict]]:
    system = _persona(
        lang, "Given today's portfolio numbers, write exactly 1-2 sentences of insight"
    ) + (
        " Lead with what moved the book in money terms (contribution_to_day),"
        " not with the biggest percentage, and say how the day compares to the"
        " benchmark when one is given. Mention anything worth watching."
    )
    if recent:
        # Cheaper than any dedupe after the fact: the model that can see what it
        # already said usually says something else. _similar() is the backstop.
        system += (
            " You wrote these lines on previous days — say something new, and do"
            " not restate them: " + " | ".join(recent)
        )
    # Ranked by money, not by percent: the line should be about what moved the
    # book, and the biggest percentage is regularly the smallest position.
    contributions = sorted(
        getattr(data, "contrib", {}).items(), key=lambda kv: abs(kv[1]), reverse=True
    )
    facts = {
        "currency": getattr(data, "currency", "EUR"),
        "date": data.date.isoformat(),
        "total": data.total,
        "day_change": data.day and {"eur": round(data.day[0], 2),
                                    "pct": round(data.day[1] * 100, 2)},
        "week_change": data.week and {"eur": round(data.week[0], 2),
                                      "pct": round(data.week[1] * 100, 2)},
        "session_moves_pct": {t: round(v * 100, 2) for t, v in data.movers[:10]},
        "contribution_to_day": {t: round(v, 2) for t, v in contributions[:10]},
        "benchmark": _benchmark_facts(data),
        "currency_effect_on_day": getattr(data, "fx_effect", None),
        "just_reported": [
            {
                "ticker": r.ticker,
                "date": r.date.isoformat(),
                "beat": r.beat,
                "reported_eps": r.reported_eps,
                "eps_estimate": r.eps_estimate,
                "move_pct": getattr(data, "result_moves", {}).get(r.ticker),
            }
            for r in getattr(data, "results", [])
        ],
        "earnings_next_7d": [
            {"ticker": e.ticker, "date": e.date.isoformat(), "in_days": e.days_until}
            for e in data.earnings
            if e.date
        ],
        "ex_dividends_next_7d": [
            {
                "ticker": e.ticker,
                "date": e.ex_date.isoformat(),
                "in_days": e.days_until,
                "estimated_cash": round(cash, 2)
                if (cash := getattr(data, "dividend_cash", {}).get(e.ticker))
                else None,
            }
            for e in getattr(data, "ex_dividends", [])
        ],
        "dividends_received_7d": getattr(data, "dividends_received", None)
        and {
            "amount": round(data.dividends_received[0], 2),
            "payments": data.dividends_received[1],
        },
    }
    return system, [{"role": "user", "content": json.dumps(facts)}]


def _benchmark_facts(data) -> dict | None:
    """The index leg of the prompt: how the book did *relative* to the market.

    A -1.2% day reads very differently when the index is -2.5%, and the line is
    only worth writing if it can tell those apart.
    """
    bench = getattr(data, "benchmark", None)
    if not bench:
        return None
    from stocks.notify.digest import BENCHMARK_LABEL

    day, week = bench
    return {
        "name": BENCHMARK_LABEL,
        "day_pct": None if day is None else round(day * 100, 2),
        "week_pct": None if week is None else round(week * 100, 2),
    }


def _weekly_prompt(data, lang: str) -> tuple[str, list[dict]]:
    system = _persona(
        lang,
        "Given this week's portfolio numbers, write exactly 1-2 sentences of "
        "review",
    ) + (
        " Say what the week came down to and what the coming week sets up."
        " The figures are already in the message above yours, so interpret"
        " rather than restate them. Never recommend buying, selling or holding"
        " anything."
    )
    facts = {
        "currency": data.currency,
        "date": data.date.isoformat(),
        "total": data.total,
        "week": data.week and {"amount": round(data.week[0], 2),
                               "pct": round(data.week[1] * 100, 2)},
        "month": data.month and {"amount": round(data.month[0], 2),
                                 "pct": round(data.month[1] * 100, 2)},
        "ytd": data.ytd and {"amount": round(data.ytd[0], 2),
                             "pct": round(data.ytd[1] * 100, 2)},
        "benchmark_pct": {
            str(days): None if pct is None else round(pct * 100, 2)
            for days, pct in (data.benchmark or {}).items()
        },
        "best_of_week": [
            {"ticker": t, "amount": round(v, 2),
             "pct": None if p is None else round(p * 100, 2)}
            for t, v, p in data.best
        ],
        "worst_of_week": [
            {"ticker": t, "amount": round(v, 2),
             "pct": None if p is None else round(p * 100, 2)}
            for t, v, p in data.worst
        ],
        "top5_weight_pct": None if data.top_weight is None
        else round(data.top_weight * 100, 1),
        "top5_weight_drift_pts": None if data.drift is None
        else round(data.drift * 100, 1),
        "earnings_next_week": [
            {"ticker": e.ticker, "in_days": e.days_until} for e in data.earnings
        ],
        "ex_dividends_next_week": [
            {"ticker": e.ticker, "in_days": e.days_until} for e in data.ex_dividends
        ],
    }
    return system, [{"role": "user", "content": json.dumps(facts)}]


def _alerts_prompt(hits, lang: str) -> tuple[str, list[dict]]:
    system = _persona(
        lang,
        "The user's own price alerts just fired. Write exactly 1-2 sentences on "
        "what they have in common and what to watch next",
    ) + (
        " The numbers are already in the message above yours, so do not repeat"
        " them. Never recommend buying, selling or holding anything."
    )
    facts = {
        "alerts": [
            {
                "ticker": h.ticker,
                "rule": h.type,
                "detail": h.message,
                "value": None if h.value is None else round(float(h.value), 4),
            }
            for h in hits[:ALERTS_SHOWN]
        ],
        "total_fired": len(hits),
    }
    return system, [{"role": "user", "content": json.dumps(facts)}]


# ------------------------------------------------------------- post-checks


def _sanitize(text: str) -> str | None:
    line = " ".join(text.split()).strip()
    if not line:
        return None
    return line[:MAX_CHARS].rstrip() if len(line) > MAX_CHARS else line


_WORD_RE = re.compile(r"[\w%€$.]+", re.UNICODE)


def _words(line: str) -> set[str]:
    return {w for w in _WORD_RE.findall(line.lower()) if len(w) > 2}


def _similar(line: str, previous: list[str], threshold: float = 0.6) -> bool:
    """Whether `line` is a near-repeat of anything in `previous` (Jaccard).

    Deliberately not embeddings: the cron runs from a bare checkout, and
    downloading 124MB of static-embedding weights to compare two sentences
    would cost more than the call this guards. Token overlap is enough for the
    failure it exists for — a model that ignored the "say something new"
    instruction and re-emitted yesterday's sentence with new numbers.
    """
    words = _words(line)
    if not words:
        return False
    for old in previous:
        prev = _words(old)
        if prev and len(words & prev) / len(words | prev) >= threshold:
            return True
    return False


# ----------------------------------------------------------------- the call


def _complete(
    prefs: dict, system: str, messages: list[dict], timeout_s: float
) -> str | None:
    """One sandboxed completion over the resolved providers, or None.

    Free-chain attempts are charged to the process-wide daily pot, never to the
    account's own counter: these jobs must not write prefs.json (the live app
    owns that file), and the per-account counter lives there. The global cap is
    the one that matters for a fan-out anyway — it grows with the roster, and
    the shared free-tier keys are the operator's, not the user's. A BYOK
    attempt is the user's own billing and is never charged.
    """
    return engine.complete_attempts(
        prefs, system, messages, timeout_s,
        spend_free=engine.spend_free_global,
        accept=_sanitize,
    )


def highlight(
    data,
    prefs: dict,
    lang: str,
    timeout_s: float = 45.0,
    recent: list[str] | None = None,
) -> str | None:
    """1-2 sentence narrative for the digest, or None. Never raises.

    `recent` is the account's last few highlights: they go into the prompt, and
    a reply that echoes one anyway is dropped rather than re-rolled. Dropping
    costs nothing; a second call costs another unit of the free pot, and a
    digest without the line is still a digest.
    """
    try:
        system, messages = _prompt(data, lang, recent or [])
    except Exception:
        return None
    out = _complete(prefs, system, messages, timeout_s)
    if out and recent and _similar(out, recent):
        return None
    return out


def weekly_line(data, prefs: dict, lang: str, timeout_s: float = 45.0) -> str | None:
    """1-2 sentence review line for the weekly message, or None. Never raises.

    No repetition guard, unlike the daily `highlight`: this runs once a week
    over a different set of numbers each time, so the failure that guard exists
    for — yesterday's sentence with today's figures — has no room to happen.
    """
    try:
        system, messages = _weekly_prompt(data, lang)
    except Exception:
        return None
    return _complete(prefs, system, messages, timeout_s)


def alerts_line(hits, prefs: dict, lang: str, timeout_s: float = 45.0) -> str | None:
    """1-2 sentences of context for the alerts that just fired, or None.

    Called once per account per alerts run, only when something is actually
    being sent — the rising-edge/cooldown state in notify/state.py is what
    keeps that rare enough to put on a free tier.
    """
    if not hits:
        return None
    try:
        system, messages = _alerts_prompt(hits, lang)
    except Exception:
        return None
    return _complete(prefs, system, messages, timeout_s)
