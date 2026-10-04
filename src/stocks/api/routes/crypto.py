"""A coin's page, past the stats every pair shares: cycle, crowd, your coin.

Three reads, three sources, three cache lives:

* `/crypto/cycle` — market-wide figures from last night's scan (Fear & Greed,
  bitcoin dominance) plus the coin's own price history (volatility, Mayer
  multiple, 200-week average, strength against bitcoin).
* `/crypto/positioning` — the coin's perpetual swap, read live from the
  derivatives venues (`stocks.data.crypto_market`).
* `/crypto/holding` — the coin in this account's book: its share of the crypto
  sleeve, the sleeve's share of the book, where it sits, and what selling it
  at a loss would save in tax this year.

Every route answers a share with an empty body rather than an error, as
`/crypto` does: a client asking is not making a mistake.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime

import pandas as pd
from fastapi import APIRouter

from stocks import obs
from stocks.analysis import crypto_market as cm
from stocks.analysis.portfolio import value_weights
from stocks.api import loaders
from stocks.api.deps import Account, Base, reporting_currency
from stocks.api.routes.ticker import _GENERIC_BROKERS, Symbol
from stocks.api.schemas import (
    Banded,
    CoinHarvest,
    CryptoCycle,
    CryptoHolding,
    CryptoPositioning,
    HalvingPhase,
)
from stocks.data.crypto import STABLECOINS, is_crypto, split_pair
from stocks.portfolio import platforms
from stocks.portfolio.custody import mix as custody_mix

router = APIRouter(prefix="/ticker", tags=["ticker"])

# The share of a book a crypto sleeve is usually held at, by the allocators
# who hold one at all: under 2% barely moves the book, over 10% lets one asset
# class's 70% drawdowns set the whole book's.
SLEEVE = (0.02, 0.10)


def _banded(value: float | None, band: cm.Band | None) -> Banded | None:
    if value is None:
        return None
    return Banded(value=value, band=band.key if band else None,
                  tone=band.tone if band else None)


@router.get("/{symbol}/crypto/cycle", response_model=CryptoCycle,
            summary="Where a coin sits in the cycle")
def cycle(symbol: Symbol) -> CryptoCycle:
    """Sentiment, dominance and the coin's own stretch against its averages.

    A stablecoin gets the market-wide half only: its own price is a peg.
    """
    ticker = symbol.strip().upper()
    pair = split_pair(ticker)
    if pair is None:
        return CryptoCycle(ticker=ticker, quote="USD")
    coin, quote = pair
    scan = loaders.crypto_scan()

    fg = [(str(d), int(v)) for d, v in scan.get("fear_greed") or []]
    today_fg = fg[-1][1] if fg else None
    week_fg = fg[-8][1] if len(fg) >= 8 else None
    market = scan.get("global") or {}
    out = CryptoCycle(
        ticker=ticker,
        quote=quote,
        fear_greed=_banded(today_fg, cm.fear_greed_band(today_fg)),
        fear_greed_week=week_fg,
        fear_greed_history=fg[-90:],
        btc_dominance=market.get("btc_dominance"),
        total_mcap=(market.get("total_mcap") or {}).get(quote.lower()),
        scan_date=scan.get("saved"),
    )
    if coin in STABLECOINS:
        return out

    close = loaders.daily_closes(ticker)
    mayer = cm.mayer_multiple(close)
    r200 = cm.ratio_200w(close)
    out.vol30 = cm.realized_vol(close, 30)
    out.mayer = _banded(mayer, cm.mayer_band(mayer))
    out.ratio_200w = _banded(r200, cm.ratio_200w_band(r200))
    if coin == "BTC":
        # Bitcoin's yardstick is the risk asset it trades with: the Nasdaq 100,
        # in the dollars both are quoted in.
        usd = close if quote == "USD" else loaders.daily_closes("BTC-USD")
        out.vs_nasdaq_90d = cm.relative_return(usd, loaders.daily_closes("QQQ", "2y"), 90)
    else:
        out.vs_btc_90d = cm.relative_return(
            close, loaders.daily_closes(f"BTC-{quote}"), 90)
    if (phase := cm.halving_phase()) is not None:
        out.halving = HalvingPhase(**asdict(phase))
    return out


@router.get("/{symbol}/crypto/positioning", response_model=CryptoPositioning | None,
            summary="The coin's perpetual swap: funding and open interest")
def positioning(symbol: Symbol) -> CryptoPositioning | None:
    """Null for a share, a stablecoin, a coin no venue lists, or every venue
    down — the page hides the card in each case."""
    ticker = symbol.strip().upper()
    pair = split_pair(ticker)
    if pair is None or pair[0] in STABLECOINS:
        return None
    try:
        got = loaders.crypto_positioning(pair[0])
    except Exception as exc:
        obs.warn("api.crypto_positioning_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None
    if got is None:
        return None
    now_8h = cm.per_8h(got.funding, got.interval_h)
    week_8h = cm.per_8h(got.funding_7d, got.interval_h)
    return CryptoPositioning(
        ticker=ticker,
        venue=got.venue,
        symbol=got.symbol,
        funding_8h=_banded(now_8h, cm.funding_band(now_8h)),
        funding_7d_8h=_banded(week_8h, cm.funding_band(week_8h)),
        annualized=cm.annualized_funding(week_8h),
        oi_usd=got.oi_usd,
        oi_change_7d=got.oi_change_7d,
        as_of=datetime.now(UTC).isoformat(timespec="minutes"),
    )


def _sizing(share: float | None) -> str | None:
    if share is None:
        return None
    low, high = SLEEVE
    return "under" if share < low else "within" if share <= high else "over"


@router.get("/{symbol}/crypto/holding", response_model=CryptoHolding,
            summary="The coin in this account's book")
def holding(symbol: Symbol, account: Account, base: Base = None) -> CryptoHolding:
    """Its share of the crypto sleeve, the sleeve's share of the book, where it
    is held, and — held at a loss — what selling it today saves in tax.

    The harvest line is the tax engine's own replay (`chat.whatif`), the one
    the assistant quotes; it prints the engine's answer, repurchase rule
    included, rather than a second opinion.
    """
    ticker = symbol.strip().upper()
    if not is_crypto(ticker):
        return CryptoHolding(ticker=ticker, held=False)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    ccy = reporting_currency(account, base)
    try:
        table = loaders.positions_table(db, mtime, ccy)
    except Exception as exc:
        obs.warn("api.crypto_holding_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return CryptoHolding(ticker=ticker, held=False)
    if table.empty or ticker not in table.index:
        return CryptoHolding(ticker=ticker, held=False)

    weights = value_weights(table)
    coins = [t for t in table.index if is_crypto(str(t))]
    sleeve = float(sum(w for t in coins if pd.notna(w := weights.get(t))))
    own = weights.get(ticker)
    crypto_weight = (float(own) / sleeve
                     if own is not None and pd.notna(own) and sleeve > 0 else None)
    crypto_share = sleeve if sleeve > 0 else None

    brokers = loaders.custody(db, mtime).get(ticker, {})
    custody = [platforms.broker_label(key) for key, _ in custody_mix(brokers)
               if key not in _GENERIC_BROKERS]

    return CryptoHolding(
        ticker=ticker,
        held=True,
        crypto_weight=crypto_weight,
        crypto_share=crypto_share,
        sizing=_sizing(crypto_share),
        custody=custody,
        harvest=_harvest(account, db, mtime, ticker, table, ccy),
    )


def _harvest(account, db: str, mtime: float, ticker: str,
             table: pd.DataFrame, ccy: str) -> CoinHarvest | None:
    """Selling the whole coin today, replayed; None unless it books a loss."""
    pnl = pd.to_numeric(pd.Series([table.at[ticker, "pnl"]]), errors="coerce").iloc[0]
    if pd.isna(pnl) or pnl >= 0:
        return None
    prefs = str(account.prefs)
    try:
        book = loaders.crypto_replay(db, mtime, prefs, loaders.db_mtime(prefs))
        if book is None or (held := book.held(ticker)) is None:
            return None
        priced = table if book.currency == ccy else loaders.positions_table(
            db, mtime, book.currency)
        shares = float(priced.at[ticker, "shares"] or 0)
        value = float(priced.at[ticker, "value"])
        if shares <= 0 or not value > 0:
            return None
        sale = book.scenario(held.ticker, held.quantity, value / shares, book.currency)
    except Exception as exc:  # noqa: BLE001 — the card goes on without the line
        obs.warn("api.crypto_harvest_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None
    # The table's P/L is against average cost; the replay matches lots, and on
    # the lots this sale would match it may not be a loss at all.
    if sale is None or sale.gain >= 0:
        return None
    from stocks.portfolio.tax.base import window_end

    window = book.jurisdiction.repurchase_window or None
    clear = window_end(date.fromisoformat(book.day), window) if window else None
    return CoinHarvest(
        loss=sale.gain,
        saving=max(0.0, -sale.extra_tax),
        currency=book.currency,
        blocked=sale.blocked > 0,
        window=window,
        clear_on=clear.isoformat() if clear else None,
    )
