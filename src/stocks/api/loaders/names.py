"""What a ticker is called and looks like: its symbol, name and logo."""

from __future__ import annotations

from pathlib import Path

from stocks import identity
from stocks.api.cache import ttl_cache
from stocks.api.loaders.bars import price_bars
from stocks.api.loaders.search import sec_title
from stocks.portfolio.ledger import all_transactions

# What a ticker is called and what it looks like. All three reach the network
# on a cold path and none of them changes within a day.

_IDENTITY_TTL = 86400.0


@ttl_cache(_IDENTITY_TTL, max_entries=512)
def display_symbol(ticker: str) -> str:
    """The Yahoo symbol a stored broker label resolves to."""
    return identity.yahoo_symbol(ticker)


def listed(ticker: str) -> bool | None:
    """Whether Yahoo quotes `ticker` at all — None when it could not say.

    False only on two agreeing answers: a profile that came back cleanly with
    no quoteType (Yahoo's 404 for a symbol it has never heard of) and no year
    of bars. A throttle raises instead, and that is None: a page must never
    call a real company missing because the feed was busy. Both reads are the
    ones the page makes anyway, so asking costs nothing extra.
    """
    from stocks.data import asset_kind as kinds
    from stocks.data import fetch
    from stocks.data.crypto import is_crypto
    from stocks.data.funds import quote_type

    if is_crypto(ticker) or kinds.known(ticker) or quote_type(ticker, fetch=False):
        return True
    if fetch.retired(ticker):
        return None
    try:
        if fetch.info(ticker).get("quoteType"):
            return True
        return not price_bars(ticker, "1y").empty
    except Exception:
        return None


def missing(ticker: str, db: str, name: str | None) -> bool:
    """Whether `ticker` is no symbol at all, for this account.

    `name` is `company_name`'s answer, which the caller already holds. A name
    from any source (the account's own list first), or a row in the book,
    makes it somebody's: a delisted line held at cost is still a page worth
    opening. Only then is Yahoo asked, and only its sure "no" counts. The
    ledger is read uncached: only a symbol nothing knows gets this far.
    """
    if name:
        return False
    if listed(display_symbol(ticker)) is not False:
        return False
    try:
        return not any(t.ticker == ticker for t in all_transactions(Path(db)))
    except Exception:
        return False


@ttl_cache(_IDENTITY_TTL, max_entries=512)
def _company_name(ticker: str, watchlist: str) -> str | None:
    return identity.company_name(ticker, watchlist)


def company_name(ticker: str, watchlist: str) -> str | None:
    """Human name for a ticker.

    `watchlist` is in the key, not just the arguments: a custom name one
    account set on its own list must never render for another.

    A miss is not held for the day like a hit: it asks the two memos again,
    which costs two dict reads. A name the page header (`listing_name`) or a
    peer list (`listing_names`) learns after the miss would otherwise leave
    every list drawing "2330.TW" while the header above says TSMC.
    """
    if name := _company_name(ticker, watchlist):
        return name
    from stocks.data import profiles

    symbol = display_symbol(ticker)
    return (profiles.known(symbol) or {}).get("name") or learned_name(symbol)


def listing_name(symbol: str) -> str | None:
    """Yahoo's own name for a listing, asked when no local source has one.

    `company_name` never reaches Yahoo for it: the bulk routes (search, the
    profiles batch) call it per row, and a quoteSummary each is what the
    profile memo exists to avoid. The page header is one symbol, and a non-US
    listing nobody holds — "005930.KS", which is Samsung — has no other source,
    so the header asks here once. The blob lands in the profile memo, so the
    next `company_name` miss finds it. Not memoized: a refused fetch must be
    asked again, not held as "no name" for a day.
    """
    from stocks.data import profiles
    from stocks.data.fetch import info

    if name := (profiles.known(symbol) or {}).get("name"):
        return name
    try:
        blob = info(symbol)
    except Exception:
        return None
    return blob.get("longName") or blob.get("shortName") or None


def listing_country(symbol: str) -> str | None:
    """The company's home country, as Yahoo spells it — `listing_name`'s
    sibling: the profile memo first, one `.info` when it has none."""
    from stocks.data import profiles
    from stocks.data.fetch import info

    if country := (profiles.known(symbol) or {}).get("country"):
        return country
    try:
        return info(symbol).get("country") or None
    except Exception:
        return None


# What `listing_names` has learned, per process. Names only, never written
# into the profile memo: a blob there with a name and no sector would read
# as a company with no sector to the allocation donuts that trust it.
_LISTING_NAMES: dict[str, str] = {}
_LISTING_NAMES_CAP = 4096


def listing_names(symbols: list[str]) -> dict[str, str]:
    """`{symbol: name}` for a list of other companies — peers, compare lines.

    The SEC map and the profile memo first, then one spark request for every
    twenty still unnamed (`spark.names`), where `.info` would be one each. A
    non-US peer has no other source: without this "Valores relacionados" on
    Sony read "7974.T", "8306.T". Only names found are kept, so a refused
    request is asked again next time rather than held as "no name".
    """
    from stocks.data import profiles
    from stocks.data.spark import names

    out: dict[str, str] = {}
    cold: list[str] = []
    for symbol in dict.fromkeys(symbols):
        name = (
            sec_title(symbol)
            or (profiles.known(symbol) or {}).get("name")
            or _LISTING_NAMES.get(symbol)
        )
        if name:
            out[symbol] = name
        else:
            cold.append(symbol)
    if cold:
        found = names(cold)
        if len(_LISTING_NAMES) + len(found) > _LISTING_NAMES_CAP:
            _LISTING_NAMES.clear()
        _LISTING_NAMES.update(found)
        out.update(found)
    return out


def learned_name(symbol: str) -> str | None:
    """A name `listing_names` already found, without asking anybody."""
    return _LISTING_NAMES.get(symbol)


@ttl_cache(_IDENTITY_TTL, max_entries=512)
def logo(ticker: str) -> str | None:
    """Same-origin logo URL, absolute.

    Absolute, not relative: a relative path would resolve against whatever
    route the reader happens to be on.
    """
    return identity.logo_src(ticker, prefix="/" + identity.STATIC_PREFIX)


def mirrored_logo(ticker: str) -> str | None:
    """`logo`, from this host's mirror only — never a network call. Not
    memoized: a stat per row, and a miss must see the file once it lands."""
    return identity.logo_src(ticker, prefix="/" + identity.STATIC_PREFIX, fetch=False)


@ttl_cache(_IDENTITY_TTL, max_entries=64)
def brand_logo(broker: str) -> str | None:
    """Same-origin logo for a broker brand — the custody marks in the header.

    Mirrored into the same directory ticker logos are, for the same reason: the
    brand's CDN never sees a request per viewer telling it who banks where. The
    external URL is the fallback for an image this host could not fetch, and
    None is the honest answer for a key that declares no domain at all — a
    hand-entered row has no brand, and the client draws a name pill instead.
    """
    from stocks.portfolio import platforms

    return _brand_src(broker, platforms.broker_domain(broker))


@ttl_cache(_IDENTITY_TTL, max_entries=16)
def provider_logo(provider: str, domain: str | None) -> str | None:
    """Same-origin logo for a chat provider — the marks on the settings tiles.

    Mirrored under an `ai-` key so a provider can never take a broker's file,
    and None for the keyless chain, which is this app's own and has no brand
    domain to ask for.
    """
    return _brand_src(f"ai-{provider}", domain)


def _brand_src(key: str, domain: str | None) -> str | None:
    from stocks.data.logo import brand_logo_url, mirror_brand

    if not domain:
        return None
    if name := mirror_brand(key, domain, identity.STATIC_LOGO_DIR):
        return "/" + identity.STATIC_PREFIX + name
    return brand_logo_url(domain)
