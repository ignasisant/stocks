"""The card itself: its limits, the `DailyAction` record, the day it
belongs to, and the keys of the triggers it carried.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as wall
from typing import Final, Literal
from zoneinfo import ZoneInfo

from stocks.chat import signals

# Where the day turns over: after the US close, New York time, so the card is
# written from settled closes and read the next morning. 45 minutes past the
# bell lets the day's bars land; New York's own zone keeps the hour across
# daylight-saving changes, which a fixed UTC hour does not (3 weeks a year
# Europe and the US are an hour apart from usual).
CLOSE_ZONE = ZoneInfo("America/New_York")
BRIEF_AT = wall(16, 45)

MIN_BULLETS = 1
MAX_BULLETS = 4  # "To watch" lines; the day's alerts are listed on their own
# signals caps the alert family at three a day, and the exit rules at three
ALERTS_MAX = 6
HEADLINE_CHARS = 90
BULLET_CHARS = 120  # what the prompt asks a line to fit in
# What a line is cut at: only a runaway one. A line the model wrote a little
# over the ask is shown whole — an ellipsis mid-sentence on the card reads
# as broken, and the figure it was building to is usually at the end.
LINE_MAX_CHARS = 400
FOCUS_MAX = 4
# A Today section's note: one or two sentences over its computed rows.
NOTE_CHARS = 200
# Rows of a Today section the model is shown: enough to see a theme.
NOTE_ROWS = 6
# A brief's sections: one per line asked, a few words of title, a few lines.
MAX_SECTIONS = 12
SECTION_LINES = 4
TITLE_CHARS = 48
# The sections a line is filed under (`section_of`).
ALERTS: Final = "alerts"
WATCH: Final = "watch"
# The kinds filed under today's alerts: the reader's own triggers, fired, then
# a held name's red-flag filing — each on the card whatever the model wrote.
_FIRED: Final = (signals.CRITERION_HIT, signals.ALERT_HIT, signals.FILING_FLAG)
# Where a brief stands on a card (`DailyAction.brief`): "" no brief; pending,
# its data still being fetched; written, its sections on the card; missed, no
# model wrote it and the default card stands in.
BRIEF_PENDING: Final = "pending"
BRIEF_WRITTEN: Final = "written"
BRIEF_MISSED: Final = "missed"
BRIEF_STATES: Final = ("", BRIEF_PENDING, BRIEF_WRITTEN, BRIEF_MISSED)
# The card's share of the account's free allowance (engine.free_daily_cap), a
# day: the morning's card and one more try (a Regenerate, or an upgrade of a
# computed stand-in). Past it the card stays computed and the units stay the
# chat's. A provider the account brought its own key for is not counted.
FREE_UNITS = 2
UNITS_KEY = "daily_units"
# How long each provider gets to write the card. Nobody waits on it: the job
# runs on its own thread (`api/briefing.py`) while Home shows the stand-in and
# polls. A ~12k-token prompt asking for the whole card as JSON ran past the
# old 25 s on both providers tried (prod, 10-20 → 10-24), and the card fell
# back to the computed one. The free chain's answer did come, 88–163 s in
# (trimmed on groq, written by openrouter), and was thrown away: the cap sits
# above that, not at the median.
TIMEOUT_S = 180.0
# Past headlines kept with the card, shown to the next day's call so it does
# not re-emit yesterday's line with new numbers (the trick notify/narrative.py
# uses for the digest highlight).
RECENT_KEPT = 5
# The lines themselves, kept for this many days: what the model is shown as
# "already said", key by key, so a trigger that is back because its figure
# moved is written as what changed rather than as news.
PAST_DAYS = 7
PAST_SHOWN = 16

# A computed card is stored too — it is what the reader saw, so it is what the
# card must remember — but it is a stand-in: a later visit may try the model
# again, this long after the last attempt and at most this many times a day,
# so a dead provider costs a handful of attempts rather than one per visit.
UPGRADE_AFTER_S = 1800.0
UPGRADE_TRIES = 3

# What the facts block carries, so a briefing stays proportional to the book.
MOVERS_SHOWN = 6
WEIGHTS_SHOWN = 6
EARNINGS_DAYS = 14

_LANG_NAME = {"en": "English", "es": "Spanish", "it": "Italian"}
# Repurchase-window tokens the card knows how to phrase (tax.Jurisdiction
# .repurchase_window). An unknown token is dropped rather than printed raw.
_WINDOW_KEYS = ("2m", "30d", "28d")
_SOURCE_LLM = "llm"
_SOURCE_COMPUTED = "computed"
# `build_facts` takes a parameter named after the signals module.
_VS_BENCH = signals.VS_BENCH


@dataclass(frozen=True)
class DailyAction:
    """One day's card. `day` is the action day it was stamped for (not the
    moment it was written), which is what freshness is judged on."""

    day: str
    headline: str
    bullets: list[str]
    focus: list[str] = field(default_factory=list)
    # The trading session the card's figures are from — usually the day
    # before `day`, since the card is written before the market opens. Kept so
    # a new close makes the card stale (`is_fresh`), which the calendar date
    # alone cannot see.
    as_of: str = ""
    source: str = _SOURCE_LLM
    lang: str = "en"
    generated: float = 0.0
    recent: list[str] = field(default_factory=list)  # past headlines, newest first
    # Which triggers this card was built from, and for how many days running:
    # {"harvest:NVDA": {"last": "2026-09-17", "run": 3, "v": {"offset": 900}}}.
    # Read back by signals.repeat() — a trigger already shown whose figure has
    # not moved stays off the next card — and by signals.decay(). Headlines
    # alone cannot do this: the model rewords the same trigger every day and
    # `recent` sees two different lines.
    shown: dict = field(default_factory=dict)
    # The lines, each with the trigger it is about: {"key", "kind", "line",
    # "tickers"}. `bullets` is the same lines as plain text, kept for readers
    # of the card that predate the keys.
    items: list[dict] = field(default_factory=list)
    # Previous days' lines, newest first: {"day", "key", "line"}.
    past: list[dict] = field(default_factory=list)
    # How many generation attempts ended in this computed card today.
    tries: int = 0
    # What the card was written from, kept for the analysis behind each line
    # — it must be about the same figures as the line it opens.
    facts: dict = field(default_factory=dict)
    # {key: analysis}, each written on the reader's first opening of that line
    # (chat/daily_analysis.record) and read from here after that.
    analysis: dict = field(default_factory=dict)
    # The chat thread the card is filed in (`record`) — what the card's "Ask"
    # opens. "" for a card that was never filed.
    thread: str = ""
    # The Portfolio section (`daily_book.section`): {"index", "currency",
    # "rows": [{"window", "pct", "amount", "index_pct"}], "attribution"}, and
    # the month drawn under "chart" once the caller has attached it (`dressed`).
    book: dict = field(default_factory=dict)
    # The reader's brief, answered: {"title", "asks", "lines", "chart"}, each
    # line an item like `items`' and `chart` the one drawn for an ask the
    # section answers ({"window", "rebased", "series"}) or None. `items` then
    # holds only the alerts that fired.
    sections: list[dict] = field(default_factory=list)
    brief: str = ""
    # The wording it was written for (`daily_routines.signature`).
    brief_sig: str = ""
    # The Today page's computed sections (`today_sections`): news, insiders
    # and comparisons, each {"id", "title", "rows", "note", "missing"} with
    # rows carrying their source, link and figures. The model only adds the
    # one `note` per section; the rows are always the computed ones.
    today: list[dict] = field(default_factory=list)
    # What kind of book the sections were chosen for (`today_sections.shape`).
    shape: str = ""

    @property
    def from_model(self) -> bool:
        return self.source == _SOURCE_LLM

    @property
    def entries(self) -> list[dict]:
        """The card's lines as items — its own and its sections', or for a
        card stored before items existed, its bullets with no trigger
        attached."""
        if self.items or self.sections:
            return [dict(i) for i in self.items] + [
                dict(line) for sec in self.sections for line in sec["lines"]]
        return [
            {"key": f"line:{n}", "kind": "", "line": b, "tickers": []}
            for n, b in enumerate(self.bullets)
        ]

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "headline": self.headline,
            "bullets": list(self.bullets),
            "focus": list(self.focus),
            "as_of": self.as_of,
            "source": self.source,
            "lang": self.lang,
            "generated": self.generated,
            "recent": list(self.recent),
            "shown": dict(self.shown),
            "items": [dict(i) for i in self.items],
            "past": [dict(p) for p in self.past],
            "tries": self.tries,
            "facts": dict(self.facts),
            "analysis": dict(self.analysis),
            "thread": self.thread,
            "book": dict(self.book),
            "sections": [dict(s) for s in self.sections],
            "brief": self.brief,
            "brief_sig": self.brief_sig,
            "today": [dict(s) for s in self.today],
            "shape": self.shape,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> DailyAction | None:
        """A stored card, or None when the file is missing or unusable. Never
        raises: a corrupt card must degrade to "generate a new one", never to a
        broken dashboard."""
        if not isinstance(raw, dict):
            return None
        day, headline = str(raw.get("day") or ""), str(raw.get("headline") or "")
        bullets = [str(b) for b in (raw.get("bullets") or []) if str(b).strip()]
        if not day or not bullets:
            return None
        # Bound once: a stored card is whatever JSON was on disk, so `shown`
        # has to be *seen* to be a dict, not asked twice and assumed.
        shown = raw.get("shown")
        facts = raw.get("facts")
        analysis = raw.get("analysis")
        try:
            tries = int(raw.get("tries") or 0)
        except (TypeError, ValueError):
            tries = 0
        return cls(
            day=day,
            as_of=str(raw.get("as_of") or ""),
            headline=headline,
            bullets=bullets,
            focus=[str(t) for t in (raw.get("focus") or [])],
            source=str(raw.get("source") or _SOURCE_LLM),
            lang=str(raw.get("lang") or "en"),
            generated=float(raw.get("generated") or 0.0),
            recent=[str(h) for h in (raw.get("recent") or []) if str(h).strip()],
            shown=shown if isinstance(shown, dict) else {},
            items=_items(raw.get("items")),
            past=[
                {"day": str(p.get("day") or ""), "key": str(p.get("key") or ""),
                 "line": str(p.get("line") or "")}
                for p in (raw.get("past") or [])
                if isinstance(p, dict) and p.get("line")
            ],
            tries=tries,
            facts=facts if isinstance(facts, dict) else {},
            analysis={
                str(k): v for k, v in analysis.items() if isinstance(v, dict)
            } if isinstance(analysis, dict) else {},
            thread=str(raw.get("thread") or ""),
            book=_book(raw.get("book")),
            sections=_sections(raw.get("sections")),
            brief=str(raw.get("brief") or ""),
            brief_sig=str(raw.get("brief_sig") or ""),
            today=_today(raw.get("today")),
            shape=str(raw.get("shape") or ""),
        )


def _book(raw) -> dict:
    """A stored Portfolio section, kept only in the shape the card renders."""
    if not isinstance(raw, dict) or not isinstance(raw.get("rows"), list):
        return {}
    rows = [r for r in raw["rows"] if isinstance(r, dict) and r.get("window")]
    if not rows:
        return {}
    out = {
        "index": str(raw.get("index") or ""),
        "currency": str(raw.get("currency") or ""),
        "rows": rows,
    }
    chart = raw.get("chart")
    if isinstance(chart, list) and chart:
        out["chart"] = [line for line in chart if isinstance(line, dict)]
    return out


def _sections(raw) -> list[dict]:
    """Stored brief sections, each checked to be the shape the card renders."""
    out = []
    for sec in raw if isinstance(raw, list) else []:
        if not isinstance(sec, dict):
            continue
        lines = _items(sec.get("lines"))
        if not lines:
            continue
        chart = sec.get("chart")
        out.append({
            "title": str(sec.get("title") or ""),
            "asks": [n for n in (sec.get("asks") or []) if isinstance(n, int)],
            "lines": lines,
            "chart": chart if isinstance(chart, dict) else None,
        })
    return out


TODAY_SECTIONS = ("news", "insiders", "compare")
_ROW_DATA = (str, int, float, bool, type(None))


def _today(raw) -> list[dict]:
    """Stored Today sections, each checked to be the shape the page renders.

    A card stored before the Today page existed has no such field and reads as
    no sections; a section of an unknown id is dropped rather than drawn.
    """
    out = []
    for sec in raw if isinstance(raw, list) else []:
        if not isinstance(sec, dict) or sec.get("id") not in TODAY_SECTIONS:
            continue
        rows = []
        for row in sec.get("rows") if isinstance(sec.get("rows"), list) else []:
            if not isinstance(row, dict) or not str(row.get("line") or "").strip():
                continue
            data = row.get("data")
            rows.append({
                "key": str(row.get("key") or ""),
                "kind": str(row.get("kind") or ""),
                "line": str(row["line"]),
                "tickers": [str(t) for t in (row.get("tickers") or [])],
                "source": str(row.get("source") or ""),
                "url": str(row.get("url") or ""),
                "date": str(row.get("date") or ""),
                "data": {
                    str(k): v for k, v in data.items() if isinstance(v, _ROW_DATA)
                } if isinstance(data, dict) else {},
            })
        out.append({
            "id": str(sec["id"]),
            "title": str(sec.get("title") or ""),
            "rows": rows,
            "note": str(sec.get("note") or ""),
            "missing": [str(m) for m in (sec.get("missing") or [])],
        })
    return out


def section_of(item: dict) -> Literal["alerts", "watch"]:
    """The section a line is filed under: an alert or an exit rule that
    fired, or the rest."""
    return ALERTS if item.get("kind") in _FIRED else WATCH


def _items(raw) -> list[dict]:
    """Stored items, each checked to be the shape the card renders."""
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not str(item.get("line") or "").strip():
            continue
        out.append({
            "key": str(item.get("key") or ""),
            "kind": str(item.get("kind") or ""),
            "line": str(item["line"]),
            "tickers": [str(t) for t in (item.get("tickers") or [])],
        })
    return out


def action_day(now: datetime) -> date:
    """Which day's card is current at `now` (zone-aware, any zone).

    The card for a day is written the evening before, `BRIEF_AT` New York
    time: Monday's close turns the card over to Tuesday, which a reader in
    Madrid opens at 08:00 with every figure settled. Through Tuesday the card
    stands — the European open and the US session do not rewrite it — until
    Tuesday's close turns it over to Wednesday. Weekends turn over too, with
    Friday's figures, so "today" on the card is always the day it is read.
    """
    ny = now.astimezone(CLOSE_ZONE)
    return ny.date() + timedelta(days=1) if ny.time() >= BRIEF_AT else ny.date()


def card_session(day: date) -> date:
    """The US session the card for action day `day` is written from: the last
    weekday before it that New York traded. Monday's card is Friday's close;
    the card after Thanksgiving is the Wednesday's."""
    from stocks.data import market_holidays as mh

    shut = mh.DAYS.get(mh.US, {})
    day -= timedelta(days=1)
    while day.weekday() >= 5 or shut.get(day) == mh.CLOSED:
        day -= timedelta(days=1)
    return day


def is_fresh(
    action: DailyAction | None, day: date, lang: str, as_of: str | None = None
) -> bool:
    """Whether a stored card still stands for `day` in `lang`.

    Language is part of it: the card is prose, and a reader who just switched
    the app to Spanish should not be left with yesterday's English briefing
    until tomorrow.

    So is the session, when one is given: a card whose `as_of` is older than
    it quotes a session that has since closed. A stored card with no `as_of`
    at all (written before the field existed) cannot be shown to be current,
    so it is rewritten once.
    """
    if not (action and action.day == day.isoformat() and action.lang == lang):
        return False
    return not (as_of and action.as_of < as_of)


def wants_upgrade(action: DailyAction | None, now: float | None = None) -> bool:
    """Whether a card that stands is a computed stand-in worth one more try.

    A computed card is stored like a written one — the reader saw it, and
    tomorrow's card has to know what it said — but storing it must not end the
    day's chances of a real briefing: the allowance resets, a provider comes
    back. So a later visit tries again, `UPGRADE_AFTER_S` after the last
    attempt and at most `UPGRADE_TRIES` times a day.
    """
    if action is None or action.from_model:
        return False
    if action.tries >= UPGRADE_TRIES:
        return False
    return (now if now is not None else time.time()) - action.generated >= UPGRADE_AFTER_S


def _clip(text: str, limit: int) -> str:
    """`text` cut to `limit` characters at a word boundary, with an ellipsis
    when anything was cut — never halfway through a word or a figure."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:·—-") + "…"


def _line(text: str, limit: int) -> str:
    """One display line: whitespace collapsed, leading bullet glyph dropped
    (the card renders its own), clipped to `limit` at a word boundary."""
    line = " ".join(str(text).split()).lstrip("-•*· ").strip()
    return _clip(line, limit)


def keyed_actions(facts: dict) -> dict[str, dict]:
    """{key: action} for the facts' actions — the key each one carries, or
    the one it would have (facts stored before actions carried their key)."""
    out: dict[str, dict] = {}
    for action in (facts or {}).get("actions") or []:
        if not isinstance(action, dict) or not action.get("kind"):
            continue
        key = str(action.get("key") or signals.key_of(str(action["kind"]), action))
        out.setdefault(key, action)
    return out


def offered(facts: dict) -> list[str]:
    """The `signals.Signal.key` of every trigger that reached the card."""
    return list(keyed_actions(facts))


def seen(
    previous: DailyAction | None,
    facts: dict,
    day: date,
    keys: list[str] | None = None,
    more: dict[str, tuple[str, dict]] | None = None,
) -> dict:
    """The `shown` map to store with a new card: every trigger it showed,
    stamped today with the figures it showed it with and its run of
    consecutive days.

    `keys` is what the card actually put on screen (its items' keys); None
    means every trigger it was offered. Only a shown trigger is remembered —
    an action the model left out was never read, and must not be held back
    tomorrow as if it had been.

    A trigger shown yesterday and again today has its run extended; one shown
    earlier today (a stand-in card upgraded, a Regenerate) keeps the run it
    had; any other starts over at one. Keys nobody has seen for
    `signals.MEMORY_DAYS` are dropped, so the file is a memory and not a log.

    `more` is the Today page's rows ({key: (kind, figures)},
    `today_sections.memory`): always shown when the card is, so remembered
    alongside.
    """
    past = (previous.shown if previous else None) or {}
    actions = dict(keyed_actions(facts))
    wanted = list(actions) if keys is None else [k for k in keys if k in actions]
    for key, (kind, data) in (more or {}).items():
        actions[key] = {**data, "kind": kind}
        wanted.append(key)
    today, yesterday = day.isoformat(), (day - timedelta(days=1)).isoformat()
    out: dict = {}
    for key in dict.fromkeys(wanted):
        before = past.get(key)
        if not isinstance(before, dict):
            before = {}
        run = int(before.get("run") or 0)
        if before.get("last") == today:
            run = max(run, 1)
        elif before.get("last") == yesterday:
            run += 1
        else:
            run = 1
        action = actions[key]
        out[key] = {
            "last": today,
            "run": run,
            "v": signals.measure(str(action.get("kind") or ""), action),
        }
    # Triggers that did not come up today keep their stamp for a while — a
    # condition that flickers in and out must not read as fresh every time,
    # and an event said once must not be said again next week.
    for key, value in past.items():
        if key in out or not isinstance(value, dict):
            continue
        try:
            last = date.fromisoformat(str(value.get("last") or ""))
        except ValueError:
            continue
        if (day - last).days <= signals.MEMORY_DAYS:
            out[key] = value
    return out
