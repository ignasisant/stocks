"""The model's reply turned into a `DailyAction`, every figure audited
against the facts.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from datetime import date

from stocks import obs
from stocks.chat import daily_book, signals
from stocks.chat.daily.card import (
    _FIRED,
    _SOURCE_LLM,
    ALERTS,
    ALERTS_MAX,
    BRIEF_WRITTEN,
    FOCUS_MAX,
    HEADLINE_CHARS,
    LINE_MAX_CHARS,
    MAX_BULLETS,
    MAX_SECTIONS,
    MIN_BULLETS,
    NOTE_CHARS,
    SECTION_LINES,
    TITLE_CHARS,
    WATCH,
    DailyAction,
    _clip,
    _line,
    keyed_actions,
    section_of,
)
from stocks.chat.daily.fallback import (
    _action_line,
)
from stocks.chat.daily.instructions import (
    _today_facts,
)
from stocks.chat.daily.number_audit import (
    _NUM,
    _TICKER_RE,
    _matches,
    _numbers,
    _values,
    audit,
    figures,
)
from stocks.llm import structured


def parse(
    raw: str,
    *,
    day: date,
    lang: str,
    known: set[str] | None = None,
    facts: dict | None = None,
) -> DailyAction | None:
    """A completion turned into a card, or None when it is unusable.

    None is the reject signal for engine.complete_attempts: a provider that
    answered with something unparseable is a miss, and the next candidate —
    or the computed fallback — takes over.

    With `facts`, a card that prints a figure those facts do not contain is
    unusable too (see `audit`) — a wrong number on the dashboard costs the
    reader more than a plainer card does. A brief's lines are audited one
    by one instead (`_brief`): a bad line is dropped, not the card. A
    headline that misquotes gives way to the first line in both.

    Every alert that fired is on the card whatever the model wrote: one it
    left out gets its computed line, ahead of the model's.
    """
    try:
        data = structured.parse(raw, "WriteDailyCard")
    except structured.OffContract:
        return None
    facts_ = facts or {}
    actions = {
        str(a.get("key") or signals.key_of(str(a.get("kind") or ""), a)): a
        for a in facts_.get("actions") or []
        if isinstance(a, dict)
    }
    notes = _today_notes(data, facts_, lang, audited=facts is not None)
    if facts_.get("brief"):
        card = _brief(data, actions, day=day, lang=lang, known=known,
                      facts=facts_, audited=facts is not None)
        return replace(card, today=notes) if card is not None else None
    written = _parsed_items(data, actions, known)
    items = _alert_items(facts_, lang, {i["key"] for i in written}) + written
    if len(items) < MIN_BULLETS:
        return None
    bullets = [i["line"] for i in items]
    headline = _line(data.get("headline") or "", HEADLINE_CHARS)
    focus, seen = [], set()
    for tick in data.get("focus") or []:
        symbol = str(tick).strip().upper()
        # Only symbols the facts actually carried: a model that hallucinates a
        # ticker here would otherwise get a logo and a link to a page about a
        # company the user does not hold.
        if not symbol or symbol in seen or (known is not None and symbol not in known):
            continue
        seen.add(symbol)
        focus.append(symbol)
    if not focus:
        focus = list(dict.fromkeys(t for i in items for t in i["tickers"]))
    if facts is not None:
        bogus = audit([i["line"] for i in written], facts)
        if bogus:
            obs.warn("daily.figure_rejected", figure=bogus, lang=lang)
            return None
        headline = _sourced_headline(headline, facts, lang)
    headline = headline or _clip(bullets[0], HEADLINE_CHARS)
    return DailyAction(
        day=day.isoformat(),
        headline=headline,
        bullets=bullets,
        focus=focus[:FOCUS_MAX],
        as_of=str(facts_.get("session", {}).get("date") or ""),
        source=_SOURCE_LLM,
        lang=lang,
        generated=time.time(),
        items=items,
        book=daily_book.section(facts_),
        today=notes,
    )


def _sourced_headline(headline: str, facts: dict, lang: str) -> str:
    """`headline`, or "" when it prints a figure `facts` do not carry — the
    caller then heads the card with its first line, which passed the audit.

    Not a reason to drop the card: the lines under it stand on their own, and
    rejecting them sent the reader's own key's answer to the free chain
    (prod 11-01, one misquoted "-2,86%" over a clean brief).
    """
    if bogus := audit([headline], facts):
        obs.warn("daily.figure_rejected", figure=bogus, lang=lang, part="headline")
        return ""
    return headline


def _today_notes(data: dict, facts: dict, lang: str, *, audited: bool) -> list[dict]:
    """The model's notes on the Today sections, as {"id", "note"} — one per
    section that has rows, each audited on its own: a note with a figure the
    data does not carry is dropped, not the card. `with_today` lays them over
    the computed sections."""
    present = {sec["id"] for sec in _today_facts(facts)}
    sourced = _sourced(facts) if audited else facts
    out: dict[str, str] = {}
    for raw in data.get("today") or []:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id") or "").strip().lower()
        note = _line(raw.get("note") or "", NOTE_CHARS * 2)
        if sid not in present or sid in out or not note:
            continue
        if audited and (bogus := audit([note], sourced) or _bare(note, sourced)):
            obs.warn("daily.today_note_rejected", figure=bogus, section=sid, lang=lang)
            continue
        out[sid] = note
    return [{"id": k, "note": v} for k, v in out.items()]


def _alert_items(facts: dict, lang: str, have: set[str]) -> list[dict]:
    """The computed line of every alert and exit rule that fired and is not
    in `have`, the reader's own rules first."""
    out = []
    ccy = str(facts.get("currency") or "EUR")
    actions = keyed_actions(facts).items()
    for kind in _FIRED:
        for key, action in actions:
            if action.get("kind") != kind or key in have:
                continue
            line = _action_line(action, lang, ccy)
            if not line:
                continue
            ticker = str(action.get("ticker") or "")
            out.append({
                "key": key, "kind": kind, "line": line,
                "tickers": [ticker] if ticker else [],
            })
    return out[:ALERTS_MAX]


def _sourced(facts: dict) -> dict:
    """`facts` with the figures written in words counted as sourced: the
    brief's own ("is ASML above 700?" answered "not yet, 690 against your
    700"), the notes it quotes ("sell below 150"), the headlines it reports
    ("the $2.4 trillion chipmaker"), the index's name."""
    brief = facts.get("brief") or {}
    words = [a.get("ask") or "" for a in brief.get("asks") or []]
    words += [n.get("text") or "" for n in (brief.get("exits") or {}).get("notes") or []]
    words += [r.get("thesis") or ""
              for r in (brief.get("exits") or {}).get("rules") or []]
    words += [h.get("title") or "" for row in brief.get("news") or []
              if isinstance(row, dict) for h in row.get("headlines") or []]
    return {**facts, "asked": figures(" \n ".join(words)),
            "named": figures(daily_book.INDEX_NAME)}


def _brief(data: dict, actions: dict, *, day: date, lang: str,
           known: set[str] | None, facts: dict, audited: bool) -> DailyAction | None:
    """A brief's card from the reply: its sections, each line audited on its
    own — a line with a figure the data does not carry is dropped, a section
    left with none goes with it — and the alerts that fired above them. None
    when no section stands; a headline that misquotes gives way to the first
    line (`_sourced_headline`)."""
    asked = {a.get("n"): str(a.get("ask") or "")
             for a in facts["brief"].get("asks") or []}
    sourced = _sourced(facts)
    sections: list[dict] = []
    used: set[str] = set()
    for raw in (data.get("sections") or [])[:MAX_SECTIONS]:
        if not isinstance(raw, dict):
            continue
        asks = [n for n in raw.get("asks") or [] if isinstance(n, int) and n in asked]
        lines = []
        for entry in (raw.get("lines") or [])[:SECTION_LINES]:
            line = _line((entry or {}).get("line") or "", LINE_MAX_CHARS)
            if not line:
                continue
            if audited and (bogus := audit([line], sourced) or _bare(line, sourced)):
                obs.warn("daily.brief_line_rejected", figure=bogus, lang=lang)
                continue
            # Only an exact key: a brief's line is about whatever the reader
            # asked, and guessing which trigger it meant would open the
            # wrong analysis behind it.
            key = str((entry or {}).get("key") or "").strip()
            action = actions.get(key) if key not in used else None
            tickers = [t for t in _TICKER_RE.findall(line) if known and t in known]
            if action and action.get("ticker"):
                tickers.insert(0, str(action["ticker"]))
            if action:
                used.add(key)
            lines.append({
                "key": key if action else f"brief:{len(sections)}:{len(lines)}",
                "kind": str((action or {}).get("kind") or ""),
                "line": line,
                "tickers": list(dict.fromkeys(tickers)),
            })
        if not lines:
            continue
        title = _line(raw.get("title") or "", TITLE_CHARS) or _clip(
            asked.get(asks[0], "") if asks else "", TITLE_CHARS)
        sections.append({"title": title, "asks": asks, "lines": lines, "chart": None})
    if not sections:
        return None
    alerts = _alert_items(facts, lang, used)
    flat = [*alerts, *(ln for sec in sections for ln in sec["lines"])]
    headline = _line(data.get("headline") or "", HEADLINE_CHARS)
    if audited:
        headline = _sourced_headline(headline, sourced, lang)
    headline = headline or _clip(flat[0]["line"], HEADLINE_CHARS)
    return DailyAction(
        day=day.isoformat(),
        headline=headline,
        bullets=[i["line"] for i in flat],
        as_of=str(facts.get("session", {}).get("date") or ""),
        source=_SOURCE_LLM,
        lang=lang,
        generated=time.time(),
        items=alerts,
        book=daily_book.section(facts),
        sections=sections,
        brief=BRIEF_WRITTEN,
        brief_sig=str(facts["brief"].get("sig") or ""),
    )


_BARE_FREE = 100  # under this, a plain number is a count: "3 months", "top 5"
# A figure scaled by the word after it: "28,3 k USD", "550 M USD". Read only
# to accept one — an unscaled reading still has to stand on its own.
_SCALE_RE = re.compile(r"\s?(k|K|mil|M|mill|B|bn)\b")
_SCALES = {"k": 1e3, "K": 1e3, "mil": 1e3, "M": 1e6, "mill": 1e6, "B": 1e9, "bn": 1e9}


def _bare(line: str, facts: dict) -> str | None:
    """The first plain number in `line` that is not in `facts`, or None.

    `audit` leaves a number with no % or currency alone, which suits the
    card's lines. A brief's lines are mostly prices, printed bare ("NVDA at
    182.50"), so there a bare figure is a claim too. Still left alone: counts
    under _BARE_FREE, a year, and a number glued to letters (a ticker such as
    7203.T, "Q3"). A thousand or million after it scales it: "28,3 k" is
    28,257.35 rounded.
    """
    loose, owned = _numbers(facts)
    pool = loose.union(*owned.values())
    for match in re.finditer(_NUM, line):
        token, start, end = match.group(0), match.start(), match.end()
        scale = _SCALE_RE.match(line, end)
        if scale and any(_matches(v * _SCALES[scale.group(1)], pool)
                         for v in _values(token)):
            continue
        if (start and line[start - 1].isalpha()) or re.match(r"\.?[A-Za-z]", line[end:]):
            continue
        values = _values(token)
        if not values:
            continue
        if not re.search(r"[.,]", token.lstrip("+-")):
            whole = abs(values[0])
            if whole < _BARE_FREE or 1900 <= whole <= 2100:
                continue
        if not any(_matches(v, pool) for v in values):
            return token.strip()
    return None


def _parsed_items(data: dict, actions: dict, known: set[str] | None) -> list[dict]:
    """The reply's lines, each tied to the action it is about.

    The model is asked to copy each action's key; a small one forgets, or
    invents one, so a key that is not in the facts is recovered from the line
    itself — the one action whose ticker it names — and a line that matches
    none keeps a placeholder key: it is still shown, just never remembered.
    Two lines on one trigger are one line: the second is dropped. Alerts and
    the rest are capped apart (ALERTS_MAX, MAX_BULLETS), as the card lists them.
    """
    out: list[dict] = []
    used: set[str] = set()
    room = {ALERTS: ALERTS_MAX, WATCH: MAX_BULLETS}
    for entry in data.get("items") or []:
        key = entry.get("key")
        line = _line(entry.get("line") or "", LINE_MAX_CHARS)
        if not line:
            continue
        key = str(key or "").strip()
        if key not in actions:
            key = _infer_key(line, actions, used)
        if key and key in used:
            continue
        action = actions.get(key) or {}
        # Only symbols the facts carry — "REVIEW" and "EPS" match the pattern.
        tickers = [t for t in _TICKER_RE.findall(line) if known and t in known]
        if action.get("ticker"):
            tickers.insert(0, str(action["ticker"]))
        item = {
            "key": key or f"line:{len(out)}",
            "kind": str(action.get("kind") or ""),
            "line": line,
            "tickers": list(dict.fromkeys(tickers)),
        }
        section = section_of(item)
        if room[section] <= 0:
            continue
        room[section] -= 1
        if key:
            used.add(key)
        out.append(item)
        if room[WATCH] <= 0 and room[ALERTS] <= 0:
            break
    return out


def _infer_key(line: str, actions: dict, used: set[str]) -> str:
    """The key of the single unused action whose ticker `line` names, or ""."""
    named = set(_TICKER_RE.findall(line))
    hits = [
        key for key, action in actions.items()
        if key not in used and action.get("ticker") and str(action["ticker"]) in named
    ]
    return hits[0] if len(hits) == 1 else ""
