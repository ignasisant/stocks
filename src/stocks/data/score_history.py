"""Where each name sat on the review's map on the days it was judged.

The map draws a name at its quality and cheapness today; its trail starts
where the name was a window ago. The engine is pure and the feed only ever
gives today's statements, so the past is kept here: every review that scores
a name records the two scores against the day, the first read of a day
standing for it. Scores are facts about a listing, not about a reader, so the
file is global and holds symbols only — no account, no weight.

Daily for `DAILY_DAYS`, which covers the shortest window with room either
side; one a week (the first of its ISO week) after that, out to `KEEP_DAYS`:
a six-month trail does not need a day's precision, and three hundred names
at one point a day for two years is megabytes rewritten on every visit.

Mirrored to the bucket like `stocks.revocation`. Nothing here raises into a
request: an unreadable file starts empty, a failed mirror is a warning.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from datetime import date, timedelta

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR

DIR = DATA_DIR / "scores"
NAME = "history.json"

DAILY_DAYS = 45
KEEP_DAYS = 800

_lock = threading.Lock()
# {symbol: {iso day: [quality, cheapness]}}
_state: dict[str, dict[str, list[float]]] | None = None


def _load() -> dict[str, dict[str, list[float]]]:
    global _state
    if _state is not None:
        return _state
    try:
        storage.restore_once(DIR, (DIR / NAME,))
    except Exception as exc:  # noqa: BLE001 — start from disk, say so
        obs.warn("scores.history_restore_failed", error_type=type(exc).__name__)
    data: object = {}
    try:
        data = json.loads((DIR / NAME).read_text())
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        obs.error("scores.history_unreadable", error_type=type(exc).__name__)
    state: dict[str, dict[str, list[float]]] = {}
    for symbol, days in (data if isinstance(data, dict) else {}).items():
        if not isinstance(days, dict):
            continue
        state[str(symbol)] = {
            str(day): [float(point[0]), float(point[1])]
            for day, point in days.items()
            if isinstance(point, list) and len(point) == 2
        }
    _state = state
    return _state


def thin(days: Mapping[str, list[float]], today: date) -> dict[str, list[float]]:
    """`days` with what is past `KEEP_DAYS` dropped and what is past
    `DAILY_DAYS` cut to the first record of each ISO week."""
    daily = (today - timedelta(days=DAILY_DAYS)).isoformat()
    oldest = (today - timedelta(days=KEEP_DAYS)).isoformat()
    out: dict[str, list[float]] = {}
    weeks: set[tuple[int, int]] = set()
    for day in sorted(days):
        if day < oldest:
            continue
        if day < daily:
            week = date.fromisoformat(day).isocalendar()[:2]
            if week in weeks:
                continue
            weeks.add(week)
        out[day] = days[day]
    return out


def record(points: Mapping[str, tuple[float, float]], today: date | None = None) -> None:
    """Keep `points` ({symbol: (quality, cheapness)}) as `today`'s, for every
    symbol that has none for today yet. Written only when one is new."""
    day = today or date.today()
    key = day.isoformat()
    with _lock:
        state = _load()
        fresh = False
        for symbol, (quality, cheapness) in points.items():
            days = state.setdefault(symbol.upper(), {})
            if key in days:
                continue
            days[key] = [round(float(quality), 1), round(float(cheapness), 1)]
            fresh = True
        if not fresh:
            return
        for symbol in list(state):
            state[symbol] = thin(state[symbol], day)
            if not state[symbol]:
                del state[symbol]
        try:
            DIR.mkdir(parents=True, exist_ok=True)
            atomic.write_json(DIR / NAME, state, separators=(",", ":"), sort_keys=True)
        except OSError as exc:
            obs.warn("scores.history_write_failed", error_type=type(exc).__name__)
            return
    try:
        storage.persist(DIR / NAME)
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        obs.warn("scores.history_persist_failed", error_type=type(exc).__name__)


def near(
    days: Mapping[str, list[float]], target: date, slack: int
) -> tuple[float, float] | None:
    """The record closest to `target` within `slack` days either side, the
    earlier one on a tie; None when there is none that close."""
    best: tuple[int, str] | None = None
    for day in days:
        gap = (date.fromisoformat(day) - target).days
        if abs(gap) > slack:
            continue
        rank = (abs(gap), day)
        if best is None or rank < best:
            best = rank
    if best is None:
        return None
    quality, cheapness = days[best[1]]
    return quality, cheapness


def at(symbol: str, target: date, slack: int) -> tuple[float, float] | None:
    """`symbol`'s recorded scores nearest `target` (`near`)."""
    with _lock:
        days = dict(_load().get(symbol.upper(), {}))
    return near(days, target, slack)


def clear() -> None:
    """Forget the in-process copy (tests swapping the data dir)."""
    global _state
    with _lock:
        _state = None
