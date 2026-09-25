"""What a ticker *is*: the symbol it resolves to, its name, and its mark.

The ledger keeps whatever the broker wrote — an ISIN ("US4131971040"), a local
Revolut code ("RCF") — because that string is the audit trail and the key
positions are booked under. It is also unreadable, so every screen prints the
resolved symbol and a company name instead. That resolution is the same three
questions wherever it is asked, and it is asked from two front ends now.

Nothing here is cached and nothing here imports a UI framework. Both are on
purpose: every function below reaches the network on a cold path, and the
caller owns the cache because the two runtimes cannot share one —
`st.cache_data` needs a script run, `api.cache.ttl_cache` does not have one.
"""

from __future__ import annotations

from pathlib import Path

from stocks.config import load_watchlist
from stocks.data.logo import logo_url, mirror_logo

# Where Streamlit serves `web/static` from, relative to the document. Relative
# on purpose: the app is served at "/" locally, at "/~/+/" behind Streamlit
# Cloud's shell iframe, and at "/<prefix>/" under server.baseUrlPath, and only
# a relative URL lands on the right mount in all three.
STATIC_PREFIX = "app/static/logos/"

# Where the mirrored images actually sit. Named here, beside the prefix that
# serves them, because two runtimes now mirror into the same directory and a
# second copy of this path is a second chance to get it wrong. It points into
# `web/` because that is the directory Streamlit serves; `logo_src` still takes
# it as an argument, so nothing is forced to use this one.
STATIC_LOGO_DIR = Path(__file__).parent / "web" / "static" / "logos"


def yahoo_symbol(ticker: str) -> str:
    """The Yahoo symbol a stored broker label stands for (itself, unmapped).

    Two tiers, cheapest first: watchlist.yaml `aliases`, the hand-written map
    that covers the local codes Revolut prints; then, for a label that is
    ISIN-shaped and unmapped, Yahoo's own ISIN lookup — one search per ISIN
    ever, cached on disk (`stocks.data.symbols.symbol_for_isin`). Without the
    second tier a DEGIRO import reads as twelve rows of "US81762P1021" until
    somebody hand-edits a mapping file, which is not a thing to ask of a
    reader looking at their own trades.

    Never raises and never blocks a render on a dead Yahoo: an unresolvable
    label comes back exactly as it was stored.
    """
    try:
        from stocks.data.fetch import resolve

        resolved = resolve(ticker)
    except Exception:
        return ticker
    if resolved.upper() != ticker.upper():
        return resolved
    try:
        from stocks.data.symbols import is_isin, symbol_for_isin

        if is_isin(resolved) and (symbol := symbol_for_isin(resolved)):
            return symbol
    except Exception:
        pass
    return resolved


def company_name(ticker: str, watchlist: Path | str) -> str | None:
    """Human name for a ticker, or None when no source knows one.

    The account's own watchlist entry wins — a name someone set by hand is the
    name they meant — and it is matched under both the stored label and the
    resolved symbol, so a custom name set on a broker code is not lost by
    resolving past it. Then the coin map, then the local fund catalog (which
    covers the UCITS lines a EUR investor holds and the SEC map does not), then
    the SEC ticker map.

    `watchlist` is a parameter rather than a lookup because a custom name one
    account set must never render for another. A caller that caches this must
    key on it.

    The fallbacks hit the network on a cold cache, and a throttled endpoint
    degrades to "no name" — callers print the symbol — rather than raising.
    """
    resolved = yahoo_symbol(ticker)
    wanted = {ticker.upper(), resolved.upper()}
    for holding in load_watchlist(Path(watchlist)):
        if holding.ticker.upper() in wanted and holding.name:
            return holding.name
    try:
        from stocks.data.crypto import crypto_name

        if name := crypto_name(resolved):
            return name
        from stocks.data.funds import fund_name

        if name := fund_name(resolved):
            return name
        from stocks.data.edgar import title_for

        return title_for(resolved)
    except Exception:
        return None


def logo_src(
    ticker: str,
    static_dir: Path | None = None,
    prefix: str = STATIC_PREFIX,
) -> str | None:
    """URL for a ticker's logo: this host's mirror first, the source second.

    Images are mirrored into `static/logos/` and served by this app, so the
    logo hosts never see a request per viewer revealing which tickers someone
    displays. The external URL is the fallback for an image this host could not
    validate or download — logo CDNs block datacenter IPs, so the browser gets
    a chance instead. None when no source knows the ticker.

    Resolved first: every logo source keys on the symbol, so a row the ledger
    stores as an ISIN would otherwise probe with a string no source knows.
    """
    symbol = yahoo_symbol(ticker)
    if name := mirror_logo(symbol, static_dir or STATIC_LOGO_DIR):
        return f"{prefix}{name}"
    return logo_url(symbol)
