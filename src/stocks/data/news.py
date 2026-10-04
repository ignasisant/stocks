"""Company headlines — what the press said about a name in the last few days.

Yahoo's search endpoint carries a news list per query, each story tagged with
the tickers it touches. The tags are generous: a "five dividend stocks to buy"
column is tagged with every name it mentions, and a ticker's feed is mostly
that. So a story counts for a name only when its title names it — the symbol
or the company — and a quiet day is an empty list, not the week's listicles.

Non-US listings are thin on Yahoo under their symbol ("SAN.MC" finds none);
the company's name is searched instead when the symbol finds nothing.

Titles are third-party text. They are returned as data, cut to TITLE_CHARS,
and whoever puts them in a prompt says so.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime

TITLE_CHARS = 160
# Words a company name shares with every other: never enough to say a title
# is about this one.
_GENERIC = {
    "inc", "corp", "corporation", "company", "group", "holding", "holdings",
    "the", "plc", "ltd", "limited", "sa", "se", "ag", "nv", "co", "class",
    "banco", "bank", "international", "global", "technologies", "technology",
    "systems", "american", "first", "general", "united",
}


@dataclass(frozen=True)
class Headline:
    title: str
    publisher: str
    published: date
    url: str


def _fold(text: str) -> str:
    bare = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in bare if not unicodedata.combining(c))


def _marks(ticker: str, name: str | None) -> list[re.Pattern]:
    """What a title has to say to be about this name: its symbol (without
    the venue suffix), or the first distinctive word of its company name."""
    base = ticker.split(".")[0].split("-")[0].upper()
    marks = [re.compile(rf"\b{re.escape(base)}\b")] if len(base) > 1 else []
    for word in re.findall(r"\w+", _fold(name or "")):
        if len(word) >= 4 and word not in _GENERIC:
            marks.append(re.compile(rf"\b{re.escape(word)}", re.IGNORECASE))
            break
    return marks


def about(title: str, ticker: str, name: str | None = None) -> bool:
    """Does the title name this company?"""
    folded = _fold(title)
    return any(m.search(title if m.flags & re.IGNORECASE == 0 else folded)
               for m in _marks(ticker, name))


def _search(query: str, count: int) -> list[dict]:
    import yfinance as yf

    return list(yf.Search(query, news_count=count, max_results=1).news or [])


def parse(stories: list[dict], ticker: str, name: str | None, *,
          today: date, days: int, limit: int) -> list[Headline]:
    """The stories about this name, newest first, `days` back at most, each
    title once."""
    out: list[Headline] = []
    seen: set[str] = set()
    for story in sorted(stories, key=lambda s: s.get("providerPublishTime") or 0,
                        reverse=True):
        title = " ".join(str(story.get("title") or "").split())
        stamp = story.get("providerPublishTime")
        if not title or not isinstance(stamp, (int, float)):
            continue
        published = datetime.fromtimestamp(stamp, UTC).date()
        if not 0 <= (today - published).days <= days:
            continue
        key = _fold(title)
        if key in seen or not about(title, ticker, name):
            continue
        seen.add(key)
        out.append(Headline(
            title=title[:TITLE_CHARS],
            publisher=str(story.get("publisher") or "")[:60],
            published=published,
            url=str(story.get("link") or ""),
        ))
        if len(out) >= limit:
            break
    return out


def headlines(ticker: str, name: str | None = None, *, days: int = 3,
              limit: int = 3, today: date | None = None) -> list[Headline]:
    """Recent headlines that name `ticker`'s company. Raises on a network or
    Yahoo failure, so a caller can tell "no news" from "could not look"."""
    today = today or datetime.fromtimestamp(time.time(), UTC).date()
    found = parse(_search(ticker, 12), ticker, name, today=today, days=days,
                  limit=limit)
    if not found and name and "." in ticker:
        found = parse(_search(name, 12), ticker, name, today=today, days=days,
                      limit=limit)
    return found
