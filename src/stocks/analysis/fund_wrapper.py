"""What the wrapper around a fund's basket is, read off its name and listing.

Two lines holding the same index are not the same purchase: one reinvests
its dividends and the other pays them out, one is Irish and loses 15 % of its
US dividends inside the fund while a Luxembourg one loses 30 %, one is hedged
to the euro, one trades in dollars on a market that sleeps while its stocks
trade. Yahoo files none of that as a field. The fund's own name does — issuers
write the share class, the hedge, the index and often the domicile into it,
because the regulator makes them tell the lines apart — so this reads the
name, and the ISIN where an import left one, and leaves a field None rather
than guessing it.

Replication (physical or swap) is only ever said when the name says "swap" or
"synthetic"; a name that says nothing proves nothing, and Yahoo does not
publish it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from stocks.analysis.sentiment import INDICES, Index

# Where the basket's companies are, by the words a fund name uses for it.
# First match wins, so the narrow regions sit above "world": an "MSCI EM"
# fund is not a world fund, and "World ex USA" is not a US one.
_EXPOSURE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("em", re.compile(r"emerging|\bEM\b|\bEEM\b", re.I)),
    ("china", re.compile(r"china|hang seng|hong kong|\bCSI\b", re.I)),
    ("japan", re.compile(r"japan|nikkei|topix", re.I)),
    ("nasdaq", re.compile(r"nasdaq", re.I)),
    ("world", re.compile(r"world|acwi|all[- ]country|global", re.I)),
    ("europe", re.compile(
        r"europe|stoxx|\bEMU\b|euro ?zone|\bDAX\b|\bCAC\b|\bIBEX\b", re.I)),
    ("us", re.compile(
        r"s&p|\bUSA?\b|u\.s\.|america|russell|dow jones|total stock market", re.I)),
)

# The index each exposure is read against: the market its stocks trade in,
# not the one the fund's own line happens to be quoted on (EIMI.L is not a
# FTSE 100 fund).
_EXPOSURE_INDEX = {
    "em": "EEM",
    "china": "^HSI",
    "japan": "^N225",
    "nasdaq": "^IXIC",
    "world": "ACWI",
    "europe": "^STOXX50E",
    "us": "^GSPC",
}
_BY_TICKER = {i.ticker: i for i in INDICES}

# Where the basket's stocks trade, as (zone, open, close). An emerging-markets
# basket is mostly Asia (Taiwan, China, India, Korea) and a world one mostly
# American, so each reads by its heaviest market.
_UNDERLYING_SESSION = {
    "em": ("Asia/Hong_Kong", time(9, 30), time(16, 0)),
    "china": ("Asia/Hong_Kong", time(9, 30), time(16, 0)),
    "japan": ("Asia/Tokyo", time(9, 0), time(15, 0)),
    "nasdaq": ("America/New_York", time(9, 30), time(16, 0)),
    "us": ("America/New_York", time(9, 30), time(16, 0)),
    "world": ("America/New_York", time(9, 30), time(16, 0)),
    "europe": ("Europe/Berlin", time(9, 0), time(17, 30)),
}
_LONDON = ("Europe/London", time(8, 0), time(16, 30))
_CONTINENT = ("Europe/Berlin", time(9, 0), time(17, 30))
_NEW_YORK = ("America/New_York", time(9, 30), time(16, 0))
_LISTING_SESSION = {
    ".L": _LONDON,
    **dict.fromkeys(
        (".DE", ".F", ".AS", ".PA", ".MI", ".MC", ".SW", ".BR", ".VI", ".LS"), _CONTINENT
    ),
}

_ACC = re.compile(r"\(acc\)|accumulat|\bacc\b|\b1C\b|\bthesaur", re.I)
_DIST = re.compile(r"\(dist\)|distribut|\bdist?\b|\(D\)|\(inc\)|\b1D\b", re.I)
_HEDGED = re.compile(
    r"\b([A-Z]{3})[ -]?(?:hedged|hdg)\b|\bhedged\s*\(?([A-Z]{3})\)?", re.I
)
_SYNTHETIC = re.compile(r"\bswap\b|synthetic", re.I)
_DOMICILE_TAG = re.compile(r"\((DE|IE|LU|FR)\)")
_UCITS = re.compile(r"\bUCITS\b", re.I)
# Issuers whose UCITS range is Irish: a German iShares line says "(DE)" in its
# name, which is read first. Xtrackers and Amundi split between Luxembourg,
# Ireland and France, so their names prove nothing.
_IRISH_ISSUERS = re.compile(r"^\s*(?:iShares|Vanguard|SPDR|Invesco)\b", re.I)
# An index name runs from its provider's name to the first word that is the
# wrapper's own ("UCITS", "ETF", a share-class bracket).
_INDEX = re.compile(
    r"\b((?:MSCI|FTSE|S&P|EURO STOXX|STOXX|NASDAQ|Russell|Dow Jones|Nikkei|TOPIX"
    r"|Solactive|Bloomberg|ICE|Morningstar|CSI|Hang Seng)\b.*?)"
    r"\s*(?=\bUCITS\b|\bETF\b|\bIndex\b|\bFund\b|\bTrust\b|\(|$)",
    re.I,
)
_WRAPPER_WORDS = re.compile(
    r"(?:\s+(?:[A-Z]{3}\s+)?(?:hedged|hdg)|\s+swap|\s+(?:USD|EUR|GBP|CHF|JPY))+$", re.I
)
# US lines whose name does not carry the index they track.
_KNOWN_INDEX = {
    "QQQ": "NASDAQ-100",
    "QQQM": "NASDAQ-100",
    "DIA": "Dow Jones Industrial Average",
    "VTI": "CRSP US Total Market",
    "VT": "FTSE Global All Cap",
}


@dataclass(frozen=True)
class Wrapper:
    share_class: str | None = None  # "acc" | "dist"
    domicile: str | None = None  # ISO country, from the ISIN or the name
    ucits: bool = False
    hedged: str | None = None  # the currency it is hedged to
    synthetic: bool = False
    tracks: str | None = None  # the index, as the name spells it
    exposure: str | None = None  # a key of `_EXPOSURE`
    benchmark: Index | None = None


def exposure(text: str) -> str | None:
    """Where a fund's basket trades, by the words its name and category use."""
    for key, pattern in _EXPOSURE:
        if pattern.search(text or ""):
            return key
    return None


def _tracks(ticker: str, name: str) -> str | None:
    if known := _KNOWN_INDEX.get(ticker):
        return known
    found = _INDEX.search(name or "")
    if not found:
        return None
    index = found.group(1).strip(" -,")
    # The wrapper's own words that sit inside the run: its hedge, its swap,
    # the currency of its share class.
    index = _WRAPPER_WORDS.sub("", index).strip(" -,")
    return index or None


def read(
    ticker: str, name: str, category: str | None = None, isin: str | None = None
) -> Wrapper:
    """The wrapper `name` describes; every field None where the name is silent."""
    code = (ticker or "").strip().upper()
    text = name or ""
    ucits = bool(_UCITS.search(text))
    domicile = None
    if isin and len(isin) == 12 and isin[:2].isalpha():
        domicile = isin[:2].upper()
    elif tag := _DOMICILE_TAG.search(text):
        domicile = tag.group(1)
    elif ucits and _IRISH_ISSUERS.search(text):
        domicile = "IE"
    elif not ucits and "." not in code:
        # A bare US code that is not a UCITS line is a US fund ('40 Act).
        domicile = "US"
    share_class = (
        "acc" if _ACC.search(text) else "dist" if _DIST.search(text) else None
    )
    if share_class is None and domicile == "US":
        # A US fund must pay its income out to stay untaxed itself.
        share_class = "dist"
    hedge = _HEDGED.search(text)
    tracks = _tracks(code, text)
    where = exposure(f"{text} {category or ''} {tracks or ''}")
    return Wrapper(
        share_class=share_class,
        domicile=domicile,
        ucits=ucits or domicile in ("IE", "LU", "DE", "FR"),
        hedged=(hedge.group(1) or hedge.group(2)).upper() if hedge else None,
        synthetic=bool(_SYNTHETIC.search(text)),
        tracks=tracks,
        exposure=where,
        benchmark=_BY_TICKER.get(_EXPOSURE_INDEX[where]) if where else None,
    )


def _span(session: tuple[str, time, time], day: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(session[0])
    return (
        datetime.combine(day, session[1], zone),
        datetime.combine(day, session[2], zone),
    )


def listing_session(ticker: str) -> tuple[str, time, time] | None:
    """The session `ticker`'s own line trades in, by its exchange suffix."""
    code = (ticker or "").strip().upper()
    if "." not in code:
        return _NEW_YORK
    return _LISTING_SESSION.get(code[code.rfind(".") :])


def trade_window(
    ticker: str, where: str | None, day: date
) -> tuple[datetime, datetime] | None | bool:
    """When on `day` the fund's line and its stocks are open at once.

    False when they never are (an Asian basket quoted in New York): the
    market maker prices off futures and proxies all session. None when the
    line's whole session is covered (nothing to say) or either side is
    unknown. Otherwise the shared stretch, in UTC-aware datetimes: that is
    when the spread is tightest.
    """
    listing = listing_session(ticker)
    underlying = _UNDERLYING_SESSION.get(where or "")
    if listing is None or underlying is None:
        return None
    open_, close = _span(listing, day)
    u_open, u_close = _span(underlying, day)
    start, end = max(open_, u_open), min(close, u_close)
    if start >= end:
        return False
    if start <= open_ and end >= close:
        return None
    return start, end
