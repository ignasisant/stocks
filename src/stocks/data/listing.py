"""Which currency a ledger ticker's *price series* is quoted in.

A ledger row carries the currency the trade settled in; the close series the
app values it with carries the currency of whatever listing Yahoo resolved the
ticker to. Those are the same thing only until watchlist.yaml ``aliases`` point
a broker code at another venue. Revolut's ``ASML`` is the US ADR, bought in
dollars; the alias prices it off ``ASML.AS``, in euros. Converting that euro
close at the dollar's rate — the ledger row's currency — misstated the holding
by the whole EUR/USD gap, and every figure built on it (market value, P/L,
weights, the value history and its TWR, the risk inputs) inherited the error.

So the rule everywhere a close is turned into money: **a price converts at its
own listing's rate**, and the trade currency only ever converts what was paid.
This module is the one place that answers "what is this series quoted in",
shared by the valuation paths (stocks.analysis.portfolio) and the fee-spread
estimate (stocks.portfolio.fees).

Two quirks it owns:

* Some venues quote in minor units — London in pence (``GBp``), Johannesburg
  in cents. `quote_unit` turns those into (ISO code, scale) so a price is
  scaled to the major unit before any FX: the rate tables know GBP, not GBp,
  and a pence close read as pounds is a hundredfold overstatement.
* The lookup answers from the on-disk profile memo (stocks.data.profiles),
  which costs nothing, and only asks Yahoo about a name the memo has never
  seen *and* that could plausibly differ from its ledger row — an aliased code
  or a venue-suffixed symbol. A bare, unaliased symbol nobody has profiled yet
  is taken at the ledger's word: the valuation paths run on every render and
  from the notification cron, and a `.info` request per unseen name is the
  burst Yahoo's rate limiter punishes. The allocation profile fills the memo
  for every held name the first time the Portfolio page draws, after which the
  answer is exact.

Any failure is "unknown", never an exception, and unknown falls back to the
ledger row's currency — which is what every caller did before this existed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor

# Yahoo's minor-unit codes -> (ISO currency, units of it per quoted unit).
MINOR_UNITS: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 0.01),
    "GBX": ("GBP", 0.01),
    "ZAc": ("ZAR", 0.01),
    "ILA": ("ILS", 0.01),
}


def quote_unit(code: str | None) -> tuple[str | None, float]:
    """(ISO currency, scale) for a quoted currency code: ``"GBp"`` -> (GBP, 0.01).

    Checked before upper-casing on purpose — ``GBp`` and ``GBP`` differ only in
    case, and a hundredfold.
    """
    if not code:
        return None, 1.0
    code = str(code).strip()
    if code in MINOR_UNITS:
        return MINOR_UNITS[code]
    return code.upper(), 1.0


def _lookup(ticker: str) -> str | None:
    """The quoted currency of `ticker`'s priced listing, or None when unknown.

    Crypto pairs answer from their own symbol (BTC-EUR is quoted in euros).
    Everything else asks the profile memo about the *resolved* symbol, and
    Yahoo only for the names the module docstring says can differ.
    """
    from stocks.data.crypto import split_pair
    from stocks.data.fetch import info, resolve
    from stocks.data.profiles import known

    if pair := split_pair(ticker):
        return pair[1]
    symbol = resolve(ticker)
    stored = known(symbol)
    if stored:
        return stored.get("currency") or None
    if symbol.upper() == ticker.upper() and "." not in symbol:
        return None
    try:
        # `data.fetch.info` records the blob in the profile memo, so this is a
        # one-time cost per name, not a per-render one.
        return info(ticker).get("currency") or None
    except Exception:
        return None


def listing_currencies(
    tickers: Iterable[str], max_workers: int = 8
) -> dict[str, str | None]:
    """ledger ticker -> the currency code its priced listing is quoted in.

    The raw Yahoo code (``GBp`` stays ``GBp``); `quote_unit` turns it into
    something FX can convert. A name nothing could answer for maps to None.
    """
    names = sorted({str(t) for t in tickers if t})
    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(names))) as pool:
        return dict(zip(names, pool.map(_safe_lookup, names), strict=True))


def _safe_lookup(ticker: str) -> str | None:
    try:
        return _lookup(ticker)
    except Exception:
        return None


def price_units(
    tickers: Iterable[str], fallback: Mapping[str, str | None]
) -> dict[str, tuple[str, float]]:
    """ticker -> (ISO currency, scale) its closes are in, ready to convert.

    `fallback` is each ticker's ledger currency, used where the listing is
    unknown. ``close * scale`` is then an amount in the ISO currency, and
    that currency — not the trade's — is the one to look a rate up for.
    """
    names = [str(t) for t in tickers]
    listed = listing_currencies(names)
    out: dict[str, tuple[str, float]] = {}
    for t in names:
        iso, scale = quote_unit(listed.get(t))
        if iso is None:
            iso, scale = quote_unit(fallback.get(t))
        if iso is not None:
            out[t] = (iso, scale)
    return out
