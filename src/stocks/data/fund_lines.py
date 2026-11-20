"""A fund's NAV line found by its price, for an ISIN Yahoo's search misses.

Yahoo keeps an open-end fund's daily NAV under a Morningstar id
(0P0000XMWU.F) and its ISIN search often cannot find it: "LU0270904781"
(Pictet-Security P EUR) answers nothing, or only the German floor quotes
(P3IE.SG). Those floors do carry a current price, close to the NAV, and
OpenFIGI names the fund and its class ("PICTET-SECURITY-PE"). So the fund's
NAV lines are searched by name, and the one whose price matches the floors'
is the line — accepted only when exactly one does.

A name alone is never enough: one fund has a dozen classes (P, I, Z, HI…) in
several currencies, each its own price, and picking a sibling would misvalue
the holding. Without a fresh floor price, or with two classes inside the
tolerance, the answer is None and the holding stays at cost. Every line
accepted also carries the fund house's name and the class letter.

None is a verdict. A step that could not ask (Yahoo's search or spark
cooling off, or this process's run budget spent) raises
`Unanswered` instead, so the caller records no miss and asks again later.
"""

from __future__ import annotations

import re
import statistics
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stocks.data import openfigi, symbols

if TYPE_CHECKING:
    from stocks.data.spark import Mark

# How far the NAV line may sit from the floors' median price. Floors quote a
# fund at its last NAV plus a dealer's few tenths of a percent; another class
# of the same fund is rarely this close.
TOLERANCE = 0.025
# A floor quote older than this is a dealer who stopped quoting.
STALE_S = 7 * 86400.0
# How much further the runner-up must sit than the match (see `_pick`).
MARGIN = 0.01
MAX_FLOORS = 6
MAX_QUERIES = 6
# One spark request carries twenty symbols.
MAX_CANDIDATES = 20
# Each run is up to seven Yahoo searches, and Yahoo's search cooldown is the
# whole host's search box: at most this many runs per window, one at a time.
MAX_RUNS = 6
RUN_WINDOW_S = 600.0

_CURRENCIES = ("EUR", "USD", "GBP", "CHF")
# OpenFIGI's names abbreviate: "EU" for EUR ("A EU AC"), and a single trailing
# initial on a class ("PE" is P EUR).
_SHORT = {"EU": "EUR", "US": "USD"}
_INITIAL = {"E": "EUR", "U": "USD", "G": "GBP", "C": "CHF"}
_CLASS_CCY = re.compile(r"^([A-Z]{1,2}\d?)(EUR|USD|GBP|CHF)$")
_CLASS = re.compile(r"^[A-Z]{1,2}\d?$")
_VARIANT = frozenset({"DY", "DIS", "DIST", "INC", "H", "HDG", "HEDGED"})
# What a floor's name adds to the fund's: share kind, legal form, padding.
_FLOOR_NOISE = re.compile(
    r"\b(namens-anteile?|inhaber-anteile?|anteile?|n|sicav|fcp|fund|act\.?)\b",
    re.IGNORECASE,
)


class Unanswered(Exception):
    """The lookup could not ask; no verdict on the ISIN."""


@dataclass(frozen=True)
class Found:
    symbol: str
    name: str
    currency: str = ""


_runs: deque[float] = deque()
_run_lock = threading.Lock()


@dataclass(frozen=True)
class ShareClass:
    """A class as OpenFIGI's name spells it: the fund's stem, the class
    letter(s), and the class currency when the name says one."""

    stem: str
    letter: str = ""
    currency: str = ""


def classes(name: str) -> list[ShareClass]:
    """Readings of an OpenFIGI fund name, the likeliest first.

    "PICTET-SECURITY-P EUR" is one; "PICTET-SECURITY-PE" two (P in EUR, or a
    class called PE); "COMGEST MONDE" names no class at all.
    """
    parts = [p.strip() for p in (name or "").upper().split("-") if p.strip()]
    if len(parts) < 2:
        return [ShareClass(" ".join(parts))]
    last, stem = parts[-1], parts[:-1]
    if last in _CURRENCIES and len(stem) >= 2 and _CLASS.match(stem[-1]):
        return [ShareClass(" ".join(stem[:-1]), stem[-1], last)]
    words = last.split()
    if len(words) > 1:
        ccy = next(
            (_SHORT.get(w, w) for w in words if _SHORT.get(w, w) in _CURRENCIES), ""
        )
        letter = (
            words[0] if _CLASS.match(words[0]) and words[0] not in _CURRENCIES else ""
        )
        if letter or ccy:
            return [ShareClass(" ".join(stem), letter, ccy)]
        return [ShareClass(" ".join(parts))]
    if m := _CLASS_CCY.match(last):
        return [ShareClass(" ".join(stem), m.group(1), m.group(2))]
    if _CLASS.match(last):
        out = []
        if len(last) >= 2 and last[-1] in _INITIAL:
            out.append(ShareClass(" ".join(stem), last[:-1], _INITIAL[last[-1]]))
        out.append(ShareClass(" ".join(stem), last))
        return out
    return [ShareClass(" ".join(parts))]


def _clean_floor_name(name: str) -> str:
    raw = name or ""
    # A floor's short name is thirty characters and the share kind in the
    # thirty-first, glued on when the name fills them ("…TransitionN").
    if len(raw) == 31 and raw[29] != " ":
        raw = raw[:30]
    text = _FLOOR_NOISE.sub(" ", raw)
    words = text.replace(" - ", "-").split()
    # A floor pads the name and ends it with the share kind ("… Fund   A").
    if len(words) > 2 and len(words[-1]) == 1:
        words = words[:-1]
    return " ".join(words).strip(" -")


def _queries(reads: list[ShareClass], bases: Iterable[str]) -> list[str]:
    """Search strings, most specific first, capped at MAX_QUERIES: every
    base with letter and currency, then with the letter, then bare."""
    bases = list(dict.fromkeys([*bases, *(r.stem for r in reads if r.stem)]))
    suffixes = [
        *(f"{r.letter} {r.currency}" for r in reads if r.letter and r.currency),
        *(r.letter for r in reads if r.letter),
        "",
    ]
    out: dict[str, str] = {}
    for suffix in dict.fromkeys(suffixes):
        for base in bases:
            flat = base.upper().replace("-", " ")
            text = base if flat.endswith(f" {suffix}".upper()) else f"{base} {suffix}"
            text = " ".join(text.split())
            if len(text) >= 4:
                out.setdefault(text.upper(), text)
    return list(out.values())[:MAX_QUERIES]


def _marks(syms: list[str]) -> dict[str, Mark]:
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.spark import marks

    try:
        return marks(syms, strict=True)
    except YFRateLimitError as exc:
        raise Unanswered("spark") from exc


def _search(query: str, count: int, *, min_len: int) -> list[dict]:
    """`symbols._quotes`, refusing to read a cooling-off search as "nothing"."""
    rows = symbols._quotes(query, count, min_len=min_len)
    if not rows and not symbols.reachable():
        raise Unanswered("search")
    return rows


def _fresh(marks: dict[str, Mark], now: float) -> dict[str, Mark]:
    return {s: m for s, m in marks.items() if now - m.when <= STALE_S}


def _morningstar_id(symbol: str) -> str:
    return symbol.split(".", 1)[0].upper()


def variants(name: str) -> frozenset[str]:
    """The words that set a class apart from its sibling at the same price:
    distributing ("dy") and currency-hedged ("H")."""
    return frozenset(_words(name) & _VARIANT)


def _words(name: str) -> set[str]:
    return set(re.split(r"[^A-Z0-9]+", (name or "").upper())) - {""}


def _house(texts: Iterable[str]) -> set[str]:
    """The fund house as the names lead with it ("PICTET", "BGF")."""
    out = set()
    for text in texts:
        first = re.split(r"[^A-Z0-9&]+", (text or "").upper().strip())[0]
        if len(first) >= 2:
            out.add(first)
    return out


def _named(name: str, house: set[str], letters: set[str]) -> bool:
    """Whether a NAV line's name is this fund's house and class: a price
    within tolerance on an unrelated fund is a coincidence, not a match."""
    words = _words(name)
    return bool(words & house) and (not letters or bool(words & letters))


def _pick(
    priced: dict[str, float],
    anchor: float,
    *,
    names: dict[str, str],
    letters: set[str],
    variant: frozenset[str],
    figi_name: str = "",
) -> tuple[str | None, bool]:
    """(the symbol that matches `anchor`, whether any came close).

    A match is within TOLERANCE and clear of the runner-up: a distributing
    class sits a dividend or two from the accumulating one (Pictet-Water P
    dy EUR was 2.2 % under P EUR), so the next one must be at least MARGIN
    further away and three times as far. When it is not (Pictet-Security P
    USD and P dy USD a cent apart), the class's letter and variant words in
    the name settle it; failing those, the one line named word for word as
    OpenFIGI names the ISIN ("DWS TOP DIVIDENDE LD" over its LDQ sibling,
    whose codes no rule here reads), or nothing does.
    """
    ranked = sorted((abs(p / anchor - 1), s) for s, p in priced.items())
    if not ranked or ranked[0][0] > TOLERANCE:
        return None, False
    best, symbol = ranked[0]
    if len(ranked) == 1:
        return symbol, True
    second = ranked[1][0]
    if second - best >= MARGIN and second >= 3 * best:
        return symbol, True
    near = [
        s
        for d, s in ranked
        if d <= TOLERANCE
        and (not letters or _words(names[s]) & letters)
        and variants(names[s]) == variant
    ]
    if len(near) > 1 and figi_name:
        near = [s for s in near if _words(names[s]) == _words(figi_name)] or near
    return (near[0] if len(near) == 1 else None), True


def nav_line(
    isin: str,
    *,
    floors: Iterable[str] = (),
    floor_names: Iterable[str] = (),
    marks: Callable[[list[str]], dict[str, Mark]] | None = None,
    now: float | None = None,
) -> Found | None:
    """The NAV line of an open-end fund `isin`, verified by price, or None.

    `floors` / `floor_names` are what Yahoo's ISIN search already answered
    (floor quotes and their names); OpenFIGI's listings add to them. Raises
    `Unanswered` when it could not ask, and nothing else.
    """
    # One run at a time, and a caller that finds one going is not kept
    # waiting behind its searches: it hears "not asked" and comes back.
    if not _run_lock.acquire(blocking=False):
        raise Unanswered("busy")
    try:
        clock = time.monotonic()
        while _runs and clock - _runs[0] > RUN_WINDOW_S:
            _runs.popleft()
        if len(_runs) >= MAX_RUNS:
            raise Unanswered("budget")
        _runs.append(clock)
        return _nav_line(isin, list(floors), list(floor_names), marks or _marks, now)
    except Unanswered:
        raise
    except Exception:  # noqa: BLE001 — a label on screen, never a crash
        return None
    finally:
        _run_lock.release()


def _nav_line(
    isin: str,
    floors: list[str],
    floor_names: list[str],
    marks: Callable[[list[str]], dict[str, Mark]],
    now: float | None,
) -> Found | None:
    # OpenFIGI unreachable is taken as "not a fund we can tell": the miss
    # lasts the process, as it did before funds were looked up by price.
    sec = openfigi.security(isin)
    if sec is None or not sec.open_end:
        return None
    now = time.time() if now is None else now
    listed = [item.symbol for item in sec.listings if symbols.on_floor(item.symbol)]
    floors = list(dict.fromkeys([*floors, *listed]))[:MAX_FLOORS]
    if not floors:
        return None

    quoted = _fresh(marks(floors), now)
    if not quoted:
        return None
    floor_ccy = Counter(m.currency for m in quoted.values()).most_common(1)[0][0]
    anchor = statistics.median(
        m.price for m in quoted.values() if m.currency == floor_ccy
    )

    names = [n for n in floor_names if n]
    if not names:
        base = floors[0].split(".", 1)[0]
        for row in _search(base, 12, min_len=1):
            if row.get("symbol") in floors:
                names += [str(row.get(k) or "") for k in ("longname", "shortname")]
    bases = list(dict.fromkeys(c for n in names if len(c := _clean_floor_name(n)) >= 4))

    reads = classes(sec.name)
    letters = {r.letter for r in reads if r.letter}
    variant = variants(sec.name)
    house = _house([*bases, *(r.stem for r in reads)])
    queries = _queries(reads, bases)
    with ThreadPoolExecutor(max_workers=3) as pool:
        answers = list(pool.map(lambda q: symbols._quotes(q, 25), queries))
    if not symbols.reachable():
        # A query refused part-way: the class may be in the answer not had.
        raise Unanswered("search")
    found: dict[str, str] = {}
    by_id: set[str] = set()
    for rows in answers:
        for row in rows:
            sym = str(row.get("symbol") or "").strip().upper()
            if row.get("quoteType") != "MUTUALFUND" or not symbols.is_nav_line(sym):
                continue
            # 0P0000XMWU and 0P0000XMWU.F are one NAV: twice would be a tie.
            if _morningstar_id(sym) in by_id:
                continue
            name = str(row.get("longname") or row.get("shortname") or sym)
            if not _named(name, house, letters):
                continue
            by_id.add(_morningstar_id(sym))
            found[sym] = name
    if not found:
        return None
    candidates = list(found)[:MAX_CANDIDATES]
    priced = _fresh(marks(candidates), now)
    if not priced:
        return None

    # The class's own currency first: an unhedged class in another currency
    # is the same fund at the exchange rate, and would tie after converting.
    wanted = next((r.currency for r in reads if r.currency), "") or floor_ccy
    target = anchor
    if wanted != floor_ccy:
        rate = _rate(floor_ccy, wanted, marks, now)
        if rate is None:
            return None
        target = anchor * rate
    same = {s: m.price for s, m in priced.items() if m.currency == wanted}
    pick, close = _pick(
        same, target, names=found, letters=letters, variant=variant, figi_name=sec.name
    )
    if pick or close:
        return Found(pick, found[pick], wanted) if pick else None

    # No line in the class's currency (BGF World Technology A2 EUR has only
    # its floor quotes): the same class in another currency, unhedged, is the
    # same portfolio at the exchange rate — named with the class's letter.
    others = {
        m.currency
        for m in priced.values()
        if m.currency != wanted and m.currency in _CURRENCIES
    }
    rates = {c: _rate(c, wanted, marks, now) for c in others}
    converted = {
        s: m.price * rate for s, m in priced.items() if (rate := rates.get(m.currency))
    }
    pick, _ = _pick(
        converted,
        target,
        names=found,
        letters=letters,
        variant=variant,
        figi_name=sec.name,
    )
    return Found(pick, found[pick], priced[pick].currency) if pick else None


def _rate(
    src: str,
    dst: str,
    marks: Callable[[list[str]], dict[str, Mark]],
    now: float,
) -> float | None:
    """Units of `dst` per unit of `src`, from Yahoo's FX line."""
    if src == dst:
        return 1.0
    pair = f"{src}{dst}=X"
    got = _fresh(marks([pair]), now).get(pair)
    return got.price if got else None
