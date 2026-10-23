"""Why the book moved: the change in its value over a window, taken apart.

TWR and IRR say how much. This says where it came from, in the reporting
currency and in bars that add up exactly to `end - start`:

* contributions — net cash put in (buys incl. commission, minus sale proceeds),
  the ledger's own flows, the same ones the TWR and IRR strip out;
* price — each holding's move in its own currency, on the shares held the day
  before, at the previous day's rate (a trade day's close-versus-fill gap
  belongs here too);
* currency — the same shares' move from the rate alone;
* dividends — gross income booked in the window (tax withheld never reaches
  the value path, so it is not a bar of its own);
* fees — trade commissions (a buy's cash includes it, the shares' value does not);
* other — whatever the steps above cannot place: a name carried at cost
  (no usable price) moves only by its flows, and anything else lands here
  instead of being buried in the price bar. Zero on a clean book.

The value path is built from adjusted closes (`load_closes` auto-adjusts), so
a dividend is already inside it as price. The dividend bar shows it and takes
the gross amount back out of the price bar, so nothing is counted twice and the
sum is unchanged. A name without a usable price is carried at cost: its
dividends are not in the path, so they are not in the bar either.

A pure function over `injected_vs_value`'s own legs and the ledger — no fetches.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stocks.data.fx import ToBase, converter
from stocks.portfolio import transfers

# Below this (in base currency) an "other" residual is rounding, not a bar.
OTHER_FLOOR = 0.5


@dataclass
class Attribution:
    start: str
    end: str
    start_value: float = 0.0
    contributions: float = 0.0
    price: float = 0.0
    fx: float = 0.0
    dividends: float = 0.0
    fees: float = 0.0
    other: float = 0.0
    end_value: float = 0.0
    # ticker -> price + currency + income + costs (contributions excluded)
    movers: dict[str, float] = field(default_factory=dict)

    @property
    def residual(self) -> float:
        """end - (start + every bar): zero by construction, kept as the check."""
        return self.end_value - (
            self.start_value
            + self.contributions
            + self.price
            + self.fx
            + self.dividends
            + self.fees
            + self.other
        )


def _ledger_arrays(transactions, idx: pd.DatetimeIndex, base: str, to_base: ToBase):
    """ticker -> dict of per-day arrays (flow, fee, dividend) in `base`."""
    out: dict[str, dict[str, np.ndarray]] = {}
    n = len(idx)
    for t in transfers.normalize(transfers.relabel(list(transactions))):
        if t.action not in ("buy", "sell", "dividend"):
            continue
        pos = idx.get_indexer([pd.Timestamp(t.date)])[0]
        if pos < 0:
            continue
        row = out.setdefault(
            t.ticker, {k: np.zeros(n) for k in ("flow", "fee", "div")}
        )
        if t.action == "buy":
            row["flow"][pos] += to_base(t.quantity * t.price + t.fee, t.currency, t.date)
            row["fee"][pos] += to_base(t.fee, t.currency, t.date)
        elif t.action == "sell":
            row["flow"][pos] -= to_base(t.quantity * t.price - t.fee, t.currency, t.date)
            row["fee"][pos] += to_base(t.fee, t.currency, t.date)
        else:
            row["div"][pos] += to_base(t.price, t.currency, t.date)
    return out


def attribution(
    hist: pd.DataFrame,
    transactions,
    start: pd.Timestamp | None = None,
    base: str = "EUR",
    to_base: ToBase | None = None,
) -> Attribution | None:
    """Decompose the book's value change from `start` (or inception) to the last day.

    `hist` is `book_history`'s frame, whose `attrs["legs"]` carry each name's
    shares, price and rate. `start` opens the window at that day's close (the
    first day on or after it), exactly as `/portfolio/performance` anchors its
    buy-in; a window reaching back before the first trade is inception.
    None when there is nothing to take apart.
    """
    legs = hist.attrs.get("legs") if not hist.empty else None
    if not legs:
        return None
    to_base = to_base or converter(base)
    idx = pd.DatetimeIndex(hist.index)
    n = len(idx)
    first = 0  # first step; the opening value is the day before it
    if start is not None and start > idx[0]:
        after = int(np.searchsorted(idx.to_numpy(), start.to_datetime64()))
        if after < n:
            first = after + 1
        # else: the window starts past the data; fall back to inception
    steps = np.arange(first, n)
    if not len(steps):
        return None
    ledger = _ledger_arrays(transactions, idx, base, to_base)

    total = hist["value"].to_numpy(dtype=float)
    result = Attribution(
        start=str(idx[first - 1 if first else 0].date()),
        end=str(idx[-1].date()),
        start_value=float(total[first - 1]) if first else 0.0,
        end_value=float(total[-1]),
    )
    zeros = np.zeros(n)
    for ticker, leg in legs.items():
        v = leg.value.to_numpy(dtype=float)
        q = leg.shares.to_numpy(dtype=float)
        marked = leg.marked.to_numpy(dtype=bool)
        px = leg.px.to_numpy(dtype=float) if leg.px is not None else np.full(n, np.nan)
        rt = (
            leg.rate.to_numpy(dtype=float) if leg.rate is not None else np.full(n, np.nan)
        )
        led = ledger.get(ticker, {})
        flow = led.get("flow", zeros)
        fee = led.get("fee", zeros)
        div = led.get("div", zeros)

        k = steps
        prev = k - 1
        has_prev = prev >= 0
        p = np.where(has_prev, prev, 0)
        v_prev = np.where(has_prev, v[p], 0.0)
        ok_prev = has_prev & marked[p]
        with np.errstate(invalid="ignore"):
            price_part = np.where(ok_prev, q[p] * (px[k] - px[p]) * rt[p], 0.0)
            fx_part = np.where(ok_prev, q[p] * px[k] * (rt[k] - rt[p]), 0.0)
        price_part = np.nan_to_num(price_part)
        fx_part = np.nan_to_num(fx_part)
        dv = v[k] - v_prev
        m = marked[k]
        resid = dv - flow[k] + fee[k] - price_part - fx_part

        price = np.where(m, price_part + resid - div[k], 0.0)
        fx = np.where(m, fx_part, 0.0)
        divs = np.where(m, div[k], 0.0)
        costs = np.where(m, -fee[k], 0.0)
        other = np.where(m, 0.0, dv - flow[k])

        result.contributions += float(flow[k].sum())
        result.price += float(price.sum())
        result.fx += float(fx.sum())
        result.dividends += float(divs.sum())
        result.fees += float(costs.sum())
        result.other += float(other.sum())
        effect = float((price + fx + divs + costs + other).sum())
        if effect:
            result.movers[ticker] = effect

    if abs(result.other) < OTHER_FLOOR:
        result.price += result.other
        result.other = 0.0
    return result
