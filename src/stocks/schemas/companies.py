"""Who a company is, its peers, and finding one: profile, comparables,
search.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Profile(BaseModel):
    """Who the reader is looking at, before any number is fetched."""

    ticker: str = Field(description="As asked for — the label the ledger stores.")
    symbol: str = Field(
        description=(
            "What it resolves to. An ISIN-keyed holding reads as its ticker "
            "here; the ledger and every link keep the original label."
        )
    )
    name: str = Field(
        default="",
        description=(
            "The account's own watchlist name first, then the coin map, the "
            "fund catalog and the SEC map. Empty when no source knows one — "
            "print the symbol, never invent."
        ),
    )
    logo: str | None = Field(
        default=None,
        description=(
            "This host's mirror where there is one, the source URL otherwise. "
            "Mirrored so the logo CDNs never see a request per viewer naming "
            "which tickers somebody looks at."
        ),
    )
    is_crypto: bool = False
    is_fund: bool = False
    asset: str | None = Field(
        default=None,
        description=(
            "stock | equity_fund | bond_fund | money_market | closed_end | "
            "crypto | index — what the page lays itself out by and labels. "
            "`fund` where only the quoteType is known yet (a table of "
            "profiles never fetches); None for a future, a currency, or a "
            "symbol nothing is known about."
        ),
    )
    found: bool = Field(
        default=True,
        description=(
            "False when no such symbol exists: Yahoo has no quote and no "
            "history for it, and neither this account's book nor any name "
            "source knows it. True when it could not be told — a throttled "
            "feed is not a missing company."
        ),
    )
    sector: str | None = Field(
        default=None,
        description=(
            "Yahoo's sector as the profile memo holds it. Only the bulk "
            "`/market/profiles` fills it, from cache — null when never seen, "
            "which is not the same as having none."
        ),
    )


class Peer(BaseModel):
    ticker: str
    name: str = ""
    source: Literal["rival", "watched"] = Field(
        "rival",
        description=(
            "rival: the sector screen's same-industry cohort. watched: Yahoo's "
            "people-also-watch list, kept only where it shares the industry."
        ),
    )


class Peers(BaseModel):
    ticker: str
    related: list[Peer] = Field(
        default_factory=list,
        description=(
            "Rivals, then same-industry names Yahoo readers also watch, minus "
            "the name itself. Suggestions for the comps picker — nothing is "
            "compared until a caller picks."
        ),
    )


class Comparables(BaseModel):
    tickers: list[str]
    labels: list[str] = Field(description="KPI row labels, in the app's order.")
    rows: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Ticker to its formatted column, aligned to `labels`.",
    )
    medals: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Ticker to 🥇/🥈/🥉 for the three best composite ranks. Empty below "
            "three qualifying names — a two-horse race has no podium."
        ),
    )
    peer_median: list[str] = Field(
        default_factory=list,
        description=(
            "The rivals' median per row (every ticker but the first), aligned "
            "to `labels`. Empty where the row is size or price, or fewer than "
            "three rivals report it."
        ),
    )
    peer_range: list[str] = Field(
        default_factory=list,
        description="The rivals' P25 – P75 per row, aligned to `labels`; empty as above.",
    )
    outliers: dict[str, list[int]] = Field(
        default_factory=dict,
        description=(
            "Ticker to the row indexes where it sits over 3 robust sigmas from "
            "the median of the other names."
        ),
    )


class SearchMatch(BaseModel):
    ticker: str
    name: str = ""
    kind: str = Field(
        description=(
            "Which tier answered: watch | crypto | fund | sec | world | analyze. "
            "`analyze` is not a match — it is a plausible symbol no catalog "
            "knows, offered so the reader can try it anyway."
        )
    )
    mark: str = Field(
        default="",
        description="favorite | held | '' — only own-list rows carry one.",
    )
    exchange: str = Field(default="", description="Venue, worldwide rows only.")
    asset: str | None = Field(
        default=None,
        description=(
            "The row's asset kind as `Profile.asset`, from what this host "
            "already knows — never a fetch per keystroke, so a fund no page "
            "has opened reads `fund` and an unknown symbol None."
        ),
    )


class SearchResults(BaseModel):
    query: str
    matches: list[SearchMatch] = Field(
        default_factory=list,
        description="Already in the order to draw, tiers included.",
    )
    world_down: bool = Field(
        False,
        description=(
            "The worldwide (Yahoo) tier was asked and could not answer: the "
            "rows are local only, and a listing may be missing from them."
        ),
    )


class Recents(BaseModel):
    tickers: list[str] = Field(
        default_factory=list, description="Newest first, capped, deduped."
    )
    names: dict[str, str] = Field(
        default_factory=dict,
        description="Company name per ticker, where one is known.",
    )
