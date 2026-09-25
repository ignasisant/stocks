"""Broker running costs: explicit commissions plus an execution-spread estimate.

Explicit costs come straight off the ledger, grouped by broker (the first word
of each row's `note` — importers stamp "revolut", "degiro ...", "ibkr", ...):
the `fee` field on buy/sell rows (commission in native ccy) and standalone
`fee` rows (custody, account charges). Dividend rows are excluded — their
`fee` is withholding tax, handled in stocks.portfolio.dividends.

The spread estimate compares each execution price against the trade day's
session midpoint ((high+low)/2 of that day's bar). One trade against a daily
bar is mostly intraday noise, but summed over a book the noise cancels and the
systematic part that remains is the broker's spread/markup: buys print above
mid, sells below. `outside_range` is the portion that is definitely
markup — executions beyond the day's exchange high/low (typical of
market-maker markups on FX/crypto legs). Bars must be UNADJUSTED for
dividends (auto_adjust=False); split adjustment is replayed here from the
ledger's own `split` rows, so pre-split executions land on Yahoo's
split-adjusted scale before comparing.

The bars are not always in the execution's currency. A ledger ticker is priced
through watchlist.yaml `aliases`, and the listing it resolves to can trade on
another venue: a Revolut ``ASML`` fill is the US ADR in dollars, while the alias
points Yahoo at ``ASML.AS`` in euros. Comparing $720 against a €664 mid booked
an 8% "spread" on that one fill. `stamp_listing_currency` records each frame's
listing currency in ``df.attrs["currency"]`` and the day's high/low are
converted into the execution's currency before comparing.

An execution far outside the day's range is not a spread either — no broker
marks up 5% past the exchange's own high/low — it is a reference that does not
describe the fill: the wrong listing, an unrecorded split, a statement price
that never traded. Summed in, one such row swamps a book's worth of genuine
cents (the shipped sample statement's made-up prices read as 6% of volume), so
beyond `_BAND` the trade is counted as skipped rather than measured.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# `listing_currencies` is re-exported: the loaders of both front ends stamp
# their bars through `fees.listing_currencies`. The answer itself lives in
# stocks.analysis.listing, shared with every path that turns a close into money.
from stocks.analysis.listing import listing_currencies as listing_currencies
from stocks.analysis.listing import quote_unit
from stocks.data.fx import ToBase, converter, prefetch
from stocks.portfolio.ledger import Transaction

# How far past the day's high/low an execution may print and still be read as
# the broker's markup. Crypto and FX legs on retail brokers mark up a few
# percent at most; anything wider is a mismatched reference (see the module
# docstring) and is skipped.
_BAND = 0.05


@dataclass
class BrokerFees:
    broker: str
    trades: int = 0
    volume: float = 0.0  # gross executed value, buys + sells
    commission: float = 0.0  # fee field on buy/sell rows
    other_fees: float = 0.0  # standalone action="fee" rows

    @property
    def explicit(self) -> float:
        return self.commission + self.other_fees


@dataclass
class SpreadStats:
    broker: str
    measured: int = 0  # trades with a bar on the trade date
    skipped: int = 0  # no usable bar (not in `bars`, NaN, holiday) or out of `_BAND`
    measured_volume: float = 0.0
    spread: float = 0.0  # signed: + = paid above mid, - = beat the mid
    outside_range: float = 0.0  # executions beyond the day's high/low

    @property
    def spread_bps(self) -> float:
        """Average round-cost of measured executions, in basis points."""
        if not self.measured_volume:
            return 0.0
        return self.spread / self.measured_volume * 1e4


def broker_of(tx: Transaction) -> str:
    """Broker label for a ledger row: first word of the importer-stamped note
    ("revolut crypto BTC" -> "revolut"); hand-entered rows -> "manual"."""
    words = tx.note.split()
    return words[0].lower() if words else "manual"


def by_broker(
    transactions: list[Transaction],
    to_base: ToBase | None = None,
    base: str = "EUR",
) -> dict[str, BrokerFees]:
    """Explicit ledger costs per broker, valued at each row's own date."""
    rows = [t for t in transactions if t.action in ("buy", "sell", "fee")]
    if to_base is None:
        prefetch((t.date, t.currency) for t in rows)
        to_base = converter(base)
    out: dict[str, BrokerFees] = {}
    for tx in rows:
        bf = out.setdefault(broker_of(tx), BrokerFees(broker=broker_of(tx)))
        if tx.action == "fee":
            # Convention: amount in `fee`; tolerate rows that put it in `price`.
            bf.other_fees += to_base(tx.fee or tx.price, tx.currency, tx.date)
            continue
        bf.trades += 1
        bf.volume += to_base(tx.quantity * tx.price, tx.currency, tx.date)
        bf.commission += to_base(tx.fee, tx.currency, tx.date)
    return out


def _split_factors(transactions: list[Transaction]) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    for t in transactions:
        if t.action == "split" and t.quantity > 0:
            out.setdefault(t.ticker, []).append((t.date, t.quantity))
    return out


def _day_bars(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """ISO date -> (high, low) for one ticker's daily OHLC frame."""
    if df is None or df.empty or "High" not in df or "Low" not in df:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for ts, high, low in zip(df.index, df["High"], df["Low"], strict=True):
        if pd.notna(high) and pd.notna(low):
            out[ts.date().isoformat()] = (float(high), float(low))
    return out


def stamp_listing_currency(
    bars: dict[str, pd.DataFrame], currencies: dict[str, str | None]
) -> dict[str, pd.DataFrame]:
    """Record each frame's listing currency in ``df.attrs["currency"]``.

    `currencies` is ledger ticker -> the currency Yahoo quotes the resolved
    listing in (the allocation profile's ``currency``); a ticker missing from
    it is left unstamped and `spread_by_broker` then assumes the execution's
    own currency, which is what it did before this existed. Stamped on the
    frames rather than passed alongside so the answer travels with the cached
    bars in both front ends' loaders.
    """
    for ticker, df in bars.items():
        ccy = currencies.get(ticker)
        if ccy and df is not None:
            df.attrs["currency"] = str(ccy)
    return bars


def _bar_currency(df: pd.DataFrame | None) -> tuple[str | None, float]:
    """(ISO currency, unit scale) the frame's prices are quoted in.

    Minor units (London in pence) scale to the major one before any FX:
    `fx` knows GBP, not GBp (stocks.analysis.listing.quote_unit).
    """
    return quote_unit(df.attrs.get("currency") if df is not None else None)


def spread_by_broker(
    transactions: list[Transaction],
    bars: dict[str, pd.DataFrame],
    to_base: ToBase | None = None,
    base: str = "EUR",
) -> dict[str, SpreadStats]:
    """Execution-vs-midpoint cost per broker from daily unadjusted OHLC bars."""
    trades = [
        t for t in transactions
        if t.action in ("buy", "sell") and t.quantity > 0 and t.price > 0
    ]
    bar_ccy = {tk: _bar_currency(df) for tk, df in bars.items()}
    if to_base is None:
        prefetch(
            [(t.date, t.currency) for t in trades]
            + [(t.date, ccy) for t in trades
               if (ccy := bar_ccy.get(t.ticker, (None,))[0])],
            quote=base,
        )
        to_base = converter(base)
    splits = _split_factors(transactions)
    day_bars = {tk: _day_bars(df) for tk, df in bars.items()}
    out: dict[str, SpreadStats] = {}
    for tx in trades:
        st = out.setdefault(broker_of(tx), SpreadStats(broker=broker_of(tx)))
        bar = day_bars.get(tx.ticker, {}).get(tx.date)
        if bar is None:
            st.skipped += 1
            continue
        # Bring the bar into the execution's currency (module docstring): the
        # listing's unit scale first, then the day's cross rate via `base`.
        ccy, scale = bar_ccy.get(tx.ticker, (None, 1.0))
        rate = scale
        if ccy and ccy != tx.currency.upper():
            try:
                per_tx = to_base(1.0, tx.currency, tx.date)
                rate *= to_base(1.0, ccy, tx.date) / per_tx
            except Exception:
                rate = 0.0
        high, low = bar[0] * rate, bar[1] * rate
        mid = (high + low) / 2
        if mid <= 0:
            st.skipped += 1
            continue
        # Yahoo bars are split-adjusted; scale pre-split executions to match.
        # price/qty scale inversely, so converted values are unchanged by `ratio`.
        ratio = 1.0
        for day, r in splits.get(tx.ticker, []):
            if day > tx.date:
                ratio *= r
        price, qty = tx.price / ratio, tx.quantity * ratio
        if price > high * (1 + _BAND) or price < low * (1 - _BAND):
            st.skipped += 1  # not a markup: a reference that misses the fill
            continue
        diff = price - mid if tx.action == "buy" else mid - price
        outside = max(0.0, price - high) if tx.action == "buy" else max(0.0, low - price)
        st.measured += 1
        st.measured_volume += to_base(tx.quantity * tx.price, tx.currency, tx.date)
        st.spread += to_base(diff * qty, tx.currency, tx.date)
        st.outside_range += to_base(outside * qty, tx.currency, tx.date)
    return out
