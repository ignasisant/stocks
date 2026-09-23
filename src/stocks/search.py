"""Ticker search: the tiers, their order, and the dedup between them — no UI.

The app has exactly one ticker picker, and its ranking is a real piece of
domain knowledge rather than a widget detail: the account's own list first
(matched by symbol, company name *or* tag group, favorites before the rest),
then coins, then the local fund catalog, then the SEC company map, then a
worldwide Yahoo lookup, with an "analyze this anyway" escape hatch for a
plausible symbol none of them knows.

It lives here, outside `stocks.web`, because two front ends now ask the same
question. Copying the tier order into the second one is how the two would drift
until the same query answered differently depending on which page you were on.

The three expensive tiers arrive as callables (`sec`, `world`, and the name
lookup for held-but-unlisted symbols) rather than being imported: each caller
already owns a cache keyed to its own runtime — `st.cache_data` on the pages,
`api.cache.ttl_cache` in the ASGI worker — and neither can use the other's.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from stocks.fuzzy import FUZZY_CUTOFF, MIN_QUERY, fuzzy_ratio

# A symbol the app is willing to try even though no catalog listed it. Shape
# only — Yahoo decides whether it quotes.
SYMBOL = re.compile(r"[A-Z0-9.\-]{1,12}")

# How close a SEC company name must be to the query to count as "nailed it".
# Above the general FUZZY_CUTOFF: this decides which group leads, so it should
# admit a typo ("SANDISC" vs "SANDISK" .86) but not a near-miss neighbour
# ("MIPS" vs "VIPSHOP" .55, "IWDA" vs "IDEA" .75).
STRONG_MATCH = 0.8

# What an own-list row is marked with. Names, not glyphs: the Streamlit rows
# draw Material icons and the React rows draw their own, and neither front end
# should be reading the other's alphabet out of the domain.
FAVORITE = "favorite"
HELD = "held"

# Tier names, as they travel to a caller that wants one flat list.
WATCH, CRYPTO, FUND, SEC, WORLD, ANALYZE = (
    "watch",
    "crypto",
    "fund",
    "sec",
    "world",
    "analyze",
)

Named = list[tuple[str, str]]
Marked = list[tuple[str, str, str]]
Located = list[tuple[str, str, str]]
Tiers = tuple[Marked, Named, Named, Named, Located, str | None]


@dataclass(frozen=True)
class Catalog:
    """What one account already knows about a symbol before any lookup runs.

    Built once per query from the watchlist plus the ledger's open positions,
    because all three of the own-list tests (symbol, name, tag) and both marks
    read from it.
    """

    labels: dict[str, str] = field(default_factory=dict)
    favorites: frozenset[str] = frozenset()
    held: frozenset[str] = frozenset()
    tags: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def mark(self, ticker: str) -> str:
        """FAVORITE, HELD or "" — starred beats held, as the dropdown draws it."""
        if ticker in self.favorites:
            return FAVORITE
        return HELD if ticker in self.held else ""

    @property
    def order(self) -> list[str]:
        """Own symbols, favorites first, insertion order within each half."""
        return [t for t in self.labels if t in self.favorites] + [
            t for t in self.labels if t not in self.favorites
        ]


def account_catalog(
    holdings: Iterable,
    held: Iterable[str] = (),
    title: Callable[[str], str | None] = lambda _t: None,
) -> Catalog:
    """Index one account's watchlist and open positions for searching.

    A held-but-unlisted symbol is folded in under its SEC name (`title`), not
    its bare code: without that, "oracle" cannot find an imported ORCL
    position, and the `t not in labels` dedup then drops the SEC row for it
    too — leaving the query answerable only by the analyze fallback.
    """
    labels: dict[str, str] = {}
    favorites: set[str] = set()
    tags: dict[str, tuple[str, ...]] = {}
    for holding in holdings:
        labels[holding.ticker] = holding.name or holding.ticker
        if holding.favorite:
            favorites.add(holding.ticker)
        if holding.tags:
            tags[holding.ticker] = tuple(holding.tags)
    held_set = frozenset(held)
    for ticker in sorted(held_set - set(labels)):
        labels[ticker] = title(ticker) or ticker
    return Catalog(labels, frozenset(favorites), held_set, tags)


def fuzzy_order(
    q: str,
    tickers: Sequence[str],
    labels: Mapping[str, str],
    tag_map: Mapping[str, Sequence[str]],
) -> list[str]:
    """Own symbols whose symbol, name or tag fuzzy-matches `q`, best score first.

    Typo fallback for the dropdown; call it only after exact substring
    matching came up empty, so fuzz never dilutes good exact results.
    """
    if len(q) < MIN_QUERY:
        return []
    scored = []
    for i, t in enumerate(tickers):  # ties keep list order (favorites first)
        score = max(
            fuzzy_ratio(q, t.upper()),
            fuzzy_ratio(q, labels[t].upper()),
            *(fuzzy_ratio(q, tag.upper()) for tag in tag_map.get(t, ())),
        )
        if score >= FUZZY_CUTOFF:
            scored.append((-score, i, t))
    return [t for _, _, t in sorted(scored)]


def own_matches(q: str, catalog: Catalog) -> Marked:
    """The account's own rows for `q`: `(symbol, name, mark)`, favorites first."""
    order, labels, tags = catalog.order, catalog.labels, catalog.tags
    hits = [
        t
        for t in order
        if q in t.upper()
        or q in labels[t].upper()
        or any(q in tag.upper() for tag in tags.get(t, ()))
    ]
    if not hits:
        # Typo fallback ("oracel"): fuzzy over the same three fields.
        hits = fuzzy_order(q, order, labels, tags)
    return [(t, labels[t], catalog.mark(t)) for t in hits]


def tiers(
    raw: str,
    catalog: Catalog,
    *,
    crypto: Callable[[str], Named],
    funds: Callable[[str], Named],
    sec: Callable[[str], Named],
    world: Callable[[str], Located],
) -> Tiers:
    """Every tier for `raw`, deduped: `(watch, crypto, funds, sec, world, analyze)`.

    Worldwide runs on every query, not just when the tiers above came up empty:
    their fuzzy fallbacks always produce SOMETHING, so "nothing found locally"
    is not a usable trigger — "MIPS" pulls VIPS/CMPS/MVIS out of the SEC map
    and would have suppressed the one real answer (MIPS.ST). It is deduped
    against them instead, and `world_first` decides which of the two leads.
    """
    q = raw.strip().upper()
    if not q:
        return [], [], [], [], [], None

    labels = catalog.labels
    watch = own_matches(q, catalog)
    coins = [(t, n) for t, n in crypto(q) if t not in labels]
    # The fund catalog is local, so this tier is the one that still answers
    # "where is my ETF" while Yahoo has the deploy's egress IP in timeout.
    baskets = [(t, n) for t, n in funds(q) if t not in labels]
    filers = [(t, n) for t, n in sec(q) if t not in labels]
    seen = (
        set(labels)
        | {t for t, _ in coins}
        | {t for t, _ in baskets}
        | {t for t, _ in filers}
    )
    venues = [(t, n, x) for t, n, x in world(q) if t not in seen]
    known = seen | {t for t, _, _ in venues}
    analyze = q if (q not in known and SYMBOL.fullmatch(q)) else None
    return watch[:8], coins[:4], baskets[:4], filers[:6], venues[:3], analyze


@dataclass(frozen=True)
class Match:
    """One flattened row, for a caller that draws a single list."""

    ticker: str
    name: str
    kind: str
    mark: str = ""
    exchange: str = ""


def ranked(
    raw: str,
    catalog: Catalog,
    *,
    crypto: Callable[[str], Named],
    funds: Callable[[str], Named],
    sec: Callable[[str], Named],
    world: Callable[[str], Located],
    limit: int = 20,
) -> list[Match]:
    """`tiers`, flattened into the exact order the dropdown draws them.

    Including the SEC/worldwide swap, which is the one part of the order that
    depends on the answers rather than on the tier — see `world_first`.
    """
    watch, coins, baskets, filers, venues, analyze = tiers(
        raw, catalog, crypto=crypto, funds=funds, sec=sec, world=world
    )
    rows = [Match(t, n, WATCH, mark=m) for t, n, m in watch]
    rows += [Match(t, n, CRYPTO) for t, n in coins]
    rows += [Match(t, n, FUND) for t, n in baskets]
    groups = (
        [Match(t, n, WORLD, exchange=x) for t, n, x in venues],
        [Match(t, n, SEC) for t, n in filers],
    )
    if not world_first(raw.strip().upper(), filers):
        groups = groups[::-1]
    for group in groups:
        rows += group
    if analyze:
        rows.append(Match(analyze, "", ANALYZE))
    return rows[:limit]


def _norm_name(s: str) -> str:
    return "".join(c for c in s.upper() if c.isalnum())


def world_first(q: str, sec: Named) -> bool:
    """Whether the worldwide group should render above the SEC group.

    The SEC tier degrades as it goes: after its exact and prefix hits it falls
    back to substrings and then to fuzz, so "MIPS" answers with VIPS, CMPS and
    MVIS — six wrong US tickers that would bury the one real match (MIPS.ST).
    It keeps the top slot only when it actually nailed the query.

    "Nailed it" is an exact symbol, a company name starting with the query, or
    a company name whose OPENING words are a near-match for it. Only the
    opening words, because the query being buried anywhere in a longer name
    proves nothing — "hermes" scores .92 against "Federated Hermes, Inc." and
    would hand the lead to an asset manager over Hermès itself. Matching word
    for word from the start instead keeps "sandisc" on Sandisk Corp and
    "nvidia" on Nvidia Corp (above the leveraged NVDA ETFs Yahoo returns),
    while "bank of amrica" still lands on BANK OF AMERICA CORP.
    """
    key = _norm_name(q)
    for t, n in sec:
        if t == q or (key and _norm_name(n).startswith(key)):
            return False
        words = re.sub(r"[^A-Z0-9 ]", " ", n.upper()).split()
        head = " ".join(words[: len(q.split())])
        if head and fuzzy_ratio(q, head) >= STRONG_MATCH:
            return False
    return True


# ------------------------------------------------------------- adder lookup
# The dropdown navigates; the Watchlist tab's adder puts a symbol on the list.
# Both want the same tiers, so the catalog walk lives here once too.


def candidates(
    query: str,
    holdings: Iterable,
    *,
    crypto: Callable[[str], Named],
    funds: Callable[[str], Named],
    sec: Callable[[str], Named],
    world: Callable[[str], Located],
    limit: int = 8,
) -> list[dict]:
    """What typing `query` could put on the watchlist, best tier first.

    Rows are `{"ticker", "name", "kind", "listed"}` where `kind` names the
    tier and `listed` says the account already follows the symbol — surfaced
    rather than filtered, so a duplicate query answers "you have this"
    instead of coming up empty. `raw` is the escape hatch the dropdown spells
    "Analyze <SYMBOL>": a plausible symbol no catalog knows, which the account
    may still want to track.
    """
    q = query.strip().upper()
    if not q:
        return []
    listed = {h.ticker.upper(): (h.name or "") for h in holdings}
    tag_map = {h.ticker.upper(): h.tags for h in holdings}
    rows: list[dict] = []
    seen: set[str] = set()

    def push(ticker: str, name: str, kind: str) -> None:
        t = str(ticker).strip().upper()
        if not t or t in seen:
            return
        seen.add(t)
        rows.append(
            {
                "ticker": t,
                "name": (name or listed.get(t) or "").strip(),
                "kind": kind,
                "listed": t in listed,
            }
        )

    for t, name in listed.items():
        if (
            q in t
            or q in name.upper()
            or any(q in tag.upper() for tag in tag_map.get(t, ()))
        ):
            push(t, name, WATCH)
    for t, name in crypto(q):
        push(t, name, CRYPTO)
    for t, name in funds(q):
        push(t, name, FUND)
    for t, name in sec(q):
        push(t, name, SEC)
    for t, name, exch in world(q):
        push(t, f"{name} · {exch}" if exch else name, WORLD)
    if q not in seen and SYMBOL.fullmatch(q):
        push(q, "", "raw")
    return rows[:limit]
