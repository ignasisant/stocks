"""A percentage or an amount in the card is a claim about the reader's money,
and the free chain runs on small models that will happily round a figure
into a new one ("about 5%") or carry one over from the example in the
prompt. Every such figure must be traceable to `facts`, so the audit below
is a hard gate: a card with an untraceable number is a provider miss, and
the next candidate — or `computed()` — writes the card instead.
"""

from __future__ import annotations

import re

# One written figure. A space belongs to the number only when it separates a
# group of exactly three digits, which is the one thing it can legitimately
# be — before that rule "the S&P 500 is 8.1% under its high" read as the
# single figure 5008.1, and a perfectly sourced card was rejected over an
# index whose name ends in a number. The grouped form is tried first and
# requires a group, so a bare "1234,5" still falls through to the plain form
# whole instead of being cut after its third digit.
_NUM = (
    r"[-+\u2212]?\d{1,3}(?:[.,\u00a0\u202f ]\d{3})+(?:[.,]\d+)?"
    r"|[-+\u2212]?\d+(?:[.,]\d+)?"
)
_PCT_RE = re.compile(rf"({_NUM})\s*%")
_MONEY_RE = re.compile(
    rf"[€$£¥]\s*({_NUM})"
    rf"|({_NUM})\s*(?:EUR|USD|GBP|CHF|JPY)\b"
)
_DMY_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")
_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TICKER_RE = re.compile(r"\b[A-Z][A-Z0-9.\-]{0,9}\b")
# What counts as the same number. Absolute for percentages (a 2-dp fact
# printed to 1 dp moves by at most 0.05); relative above 100, where the model
# prints a rounded amount ("€1,235" for 1234.56).
_ABS_TOL = 0.051
_REL_TOL = 0.005


def _readings(token: str) -> list[tuple[float, int]]:
    """Every (number, decimals written) a token could mean.

    The decimals say how coarsely the figure was rounded: "26" is anything
    from 25.5 to 26.5, which a 1-dp fact (26.4) honestly prints as.
    """
    body = re.sub(r"[\s\u00a0\u202f]", "", token).rstrip(".,")
    sign = -1.0 if body[:1] in ("-", "\u2212") else 1.0
    body = body.lstrip("+-\u2212")
    out = []
    for dec, group in ((".", ","), (",", ".")):
        if body.count(dec) <= 1:
            try:
                value = float(body.replace(group, "").replace(dec, "."))
            except ValueError:
                continue
            out.append((sign * value, len(body.rpartition(dec)[2]) if dec in body else 0))
    return out


def _values(token: str) -> list[float]:
    """Every number a written token could mean, decimal separator unknown.

    "45,99" is 45.99 to a Spanish reader and 4599 to an English one, and the
    card is written in either language: both readings are candidates, and a
    figure is accepted if *some* reading is in the facts.
    """
    return [value for value, _ in _readings(token)]


def figures(text: str) -> list[float]:
    """Every number written in `text`, both decimal readings — how a source
    that arrives as prose (a press release) joins the audit pool."""
    out: list[float] = []
    for match in re.finditer(_NUM, text or ""):
        out.extend(_values(match.group(0)))
    return out


def _numbers(node, ticker: str | None = None) -> tuple[set[float], dict]:
    """(figures with no ticker, {ticker: its figures}) from a facts tree.

    Split because a line that names exactly one holding is audited against
    that holding's numbers: it is what stops NVDA's move being printed under
    AMD's name, which a flat pool of every number in the book would allow.
    """
    loose: set[float] = set()
    owned: dict[str, set[float]] = {}

    def walk(node, owner: str | None) -> None:
        if isinstance(node, dict):
            owner = str(node.get("ticker") or owner or "").upper() or None
            for key, value in node.items():
                if key != "ticker":
                    walk(value, owner)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, owner)
        elif isinstance(node, bool) or node is None:
            return
        elif isinstance(node, (int, float)):
            bucket = owned.setdefault(owner, set()) if owner else loose
            bucket.update((float(node), abs(float(node))))

    walk(node, ticker)
    return loose, owned


def _matches(value: float, pool, decimals: int = 2) -> bool:
    """`value` is in `pool`, allowing for the rounding it was written with:
    a whole-number figure ("36 %", "€105") stands for anything within half a
    unit, since that is what rounding 35.6 or 104.6 prints."""
    slack = 0.5 + 1e-9 if decimals == 0 else _ABS_TOL
    return any(
        abs(value - known) <= max(slack, abs(known) * _REL_TOL) for known in pool
    )


def _written_in(token: str, pool) -> bool:
    return any(_matches(v, pool, d) for v, d in _readings(token))


def _dates(facts: dict) -> set[str]:
    """Every ISO date in the facts — what a printed date is checked against."""
    found = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
        elif isinstance(node, str) and _ISO_RE.fullmatch(node.strip()):
            found.add(node.strip())

    walk(facts)
    return found


def audit(lines: list[str], facts: dict) -> str | None:
    """The first figure in `lines` that is not in `facts`, or None when clean.

    Percentages, amounts and printed dates only: those are the card's claims.
    Bare counts ("in 7 days", "three positions") are left alone — they come
    from the same facts and are not worth a false rejection.
    """
    loose, owned = _numbers(facts)
    known_dates = _dates(facts)
    symbols = set(owned)
    for line in lines:
        named = {t for t in _TICKER_RE.findall(line) if t in symbols}
        # One holding named -> its own figures (plus the book-wide ones).
        # Zero or several -> every figure in the book, since a line comparing
        # two names legitimately quotes both.
        pool = loose | set().union(*(owned[t] for t in named or symbols), set())
        for match in _PCT_RE.finditer(line):
            if not _written_in(match.group(1), pool):
                return match.group(0).strip()
        for match in _MONEY_RE.finditer(line):
            token = match.group(1) or match.group(2) or ""
            if token and not _written_in(token, pool):
                return match.group(0).strip()
        for day, month, year in _DMY_RE.findall(line):
            # Either reading of an ambiguous date: cards are written in
            # languages that disagree about which number comes first.
            both = {
                f"{year}-{int(b):02d}-{int(a):02d}"
                for a, b in ((day, month), (month, day))
            }
            if known_dates and not (both & known_dates):
                return f"{day}/{month}/{year}"
    return None
