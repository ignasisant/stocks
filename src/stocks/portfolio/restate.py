"""A ledger restated in the quote of the listing its chart is drawn from.

The listing's quote itself is answered by stocks.data.listing; this is the
ledger side of the same rule — a holding drawn against its own price chart has
its fills, average cost and P/L in that chart's unit.
"""

from __future__ import annotations

from stocks.data.listing import quote_unit


def restate_trades(transactions, ticker: str, code: str | None) -> list:
    """The ledger, relabelled, with `ticker`'s rows priced in its listing's quote.

    For the screens that draw a holding against its own price chart (the
    ticker page, both front ends). The chart is the listing's series, so the
    fills plotted on it, the average-cost line and the value and P/L beside it
    must be in the listing's unit too — a dollar basis against a euro close
    reads the FX gap as a gain or a loss. Each row converts at its own trade
    date's rate (price and fee alike), minor units scaled up so a pence chart
    gets pence, which leaves the P/L a holder of that listing actually has.

    Relabelled first: the page speaks the unified label a broker transfer
    gives a holding (ISIN and symbol as one), the raw rows do not — see
    corporate.own_fills. Every other ticker's rows pass through untouched, and
    a split row keeps its ratio. When the listing is unknown or a rate cannot
    be had the rows stay in their trade currency: a half-converted history is
    worse than an unconverted one.
    """
    from dataclasses import replace

    from stocks.data.fx import rate_on
    from stocks.portfolio import transfers

    rows = transfers.relabel(list(transactions))
    iso, scale = quote_unit(code)
    if iso is None:
        return rows
    out = []
    try:
        for t in rows:
            if t.ticker != ticker or t.action == "split":
                out.append(t)
                continue
            same = t.currency.upper() == iso
            if same and scale == 1.0:
                out.append(t)
                continue
            rate = (1.0 if same else rate_on(t.date, t.currency, iso)) / scale
            out.append(replace(t, price=t.price * rate, fee=t.fee * rate,
                               currency=iso))
    except Exception:
        return rows
    return out


def restate_position(position, transactions, code: str | None):
    """`position` with its native cost in the listing's quote (`restate_trades`).

    A replay of the restated rows with identity FX, so each lot keeps the rate
    of its own trade date. Returned unchanged when there is nothing to restate
    (listing unknown, or already the trade currency); `currency` becomes the
    listing's code as the chart prints it (``GBp`` for a pence chart).
    """
    from dataclasses import replace

    from stocks.portfolio.positions import build

    iso, scale = quote_unit(code)
    if position is None or iso is None:
        return position
    if iso == str(position.currency).upper() and scale == 1.0:
        return position
    rows = restate_trades(transactions, position.ticker, code)
    mine = [t for t in rows if t.ticker == position.ticker]
    if any(t.currency.upper() != iso for t in mine if t.action != "split"):
        return position  # a rate was missing: keep the trade-currency figures
    try:
        replay, _ = build(mine, to_base=lambda amount, ccy, day: amount)
    except Exception:
        return position
    hit = next((p for p in replay if p.ticker == position.ticker), None)
    if hit is None:
        return position
    # `cost` (the reporting-currency basis) is untouched: only the native
    # side moves onto the chart's unit.
    return replace(position, cost_native=hit.cost_native, currency=str(code))
