"""Money in versus value: shares held per day, the injected-capital curve,
external flows, time- and money-weighted returns, and sleeve projections.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from stocks import obs
from stocks.analysis.portfolio.stats import (
    annualized_return,
    annualized_volatility,
    portfolio_returns,
)
from stocks.data.fx import ToBase, converter
from stocks.data.listing import price_units
from stocks.frames import naive_dates
from stocks.portfolio import consistency, transfers

# (amount, currency, iso_date) -> the reporting currency, injectable so tests
# skip the network. The live one is stocks.data.fx.converter(base).
ToBaseFn = ToBase | None


def shares_frame(transactions, end: str | None = None) -> pd.DataFrame:
    """Daily shares held per ticker, replaying buys/sells in ledger order.

    Split-adjusted throughout: price history is back-adjusted, so a trade's
    quantity is scaled by every split that came after it and the split itself
    is not a step in the path. Stepping shares up on the split date instead
    would leave the pre-split stretch valued at post-split prices — the
    position reads ~1/ratio of its real size and its buys look like instant
    losses in the flow-adjusted return.

    Calendar-daily index from the first transaction to `end` (default today),
    forward-filled between events; 0 before a ticker's first buy. Moving shares
    between brokers changes no share count, so a matched pair of transfer legs
    nets out before the replay and only an unmatched arrival steps the path
    (see stocks.portfolio.transfers).
    """
    txs = sorted(transfers.normalize(transactions), key=lambda t: (t.date, t.id or 0))
    if not txs:
        return pd.DataFrame()
    splits: dict[str, list[tuple[str, float]]] = {}
    for t in txs:
        if t.action == "split" and t.quantity > 0:
            splits.setdefault(t.ticker, []).append((t.date, t.quantity))

    def adjusted(t) -> float:
        """Quantity in today's shares: splits strictly after the trade date.
        A split shares its date with post-split trades, which need no scaling."""
        return t.quantity * math.prod(
            ratio for day, ratio in splits.get(t.ticker, ()) if day > t.date
        )

    qty: dict[str, float] = {}
    snap: dict[str, dict[str, float]] = {}
    for t in txs:
        if t.action == "buy":
            qty[t.ticker] = qty.get(t.ticker, 0.0) + adjusted(t)
        elif t.action == "sell":
            qty[t.ticker] = qty.get(t.ticker, 0.0) - adjusted(t)
        else:
            continue
        snap.setdefault(t.date, {})[t.ticker] = qty[t.ticker]
    frame = pd.DataFrame.from_dict(snap, orient="index").sort_index()
    frame.index = pd.to_datetime(frame.index)
    idx = pd.date_range(frame.index[0], end or pd.Timestamp.today().normalize(), freq="D")
    return frame.reindex(idx).ffill().fillna(0.0).clip(lower=0.0)


def injected_series(
    transactions, to_base: ToBaseFn = None, base: str = "EUR"
) -> pd.Series:
    """Cumulative net cash put in, in `base` at each transaction date's rate.

    Buys add cost incl. commission; sells subtract net proceeds. Dividends and
    standalone fees don't move contributed capital, and neither does a transfer
    between brokers — only shares arriving from a book that never held them
    count, at the basis their statement reports. Index = transaction dates.
    """
    to_base = to_base or converter(base)
    flows: dict[str, float] = {}
    for t in sorted(transfers.normalize(transactions), key=lambda t: (t.date, t.id or 0)):
        if t.action == "buy":
            amt = to_base(t.quantity * t.price + t.fee, t.currency, t.date)
        elif t.action == "sell":
            amt = -to_base(t.quantity * t.price - t.fee, t.currency, t.date)
        else:
            continue
        flows[t.date] = flows.get(t.date, 0.0) + amt
    if not flows:
        return pd.Series(dtype=float)
    s = pd.Series(flows).sort_index()
    s.index = pd.to_datetime(s.index)
    return s.cumsum()


def _close_matches_trades(px: pd.Series, ticker: str, ccy: str, transactions) -> bool:
    """False when a ticker's own fills read this close off by an order of magnitude.

    A close series is keyed on a bare ticker string, and more than one
    instrument answers to a short one — a memecoin's symbol is cheap real
    estate among thousands of them. A collided "CAT-EUR" once priced a ~500
    EUR position at 900k+ for over a year, because nothing checked the close
    against what the book actually paid for it. The book's own fills are
    ground truth for what a name costs; a series whose price near a fill date
    sits a magnitude off is the wrong instrument, not a real move, and is
    rejected rather than trusted for the whole history.

    Each fill is first restated across the book's own split rows: the closes
    are split-adjusted and a fill is as-traded, so a 1:30 reverse split the
    book does carry read every earlier buy 30x under its close (BYND, prod
    2026-10-16). A split the book lacks still fails, as it should — its share
    count is off by the same factor.
    """
    ratios = [off for _, off in _fill_ratios(px, ticker, ccy, transactions)]
    return _plausible_ratio(ratios)


def _plausible_ratio(ratios: list[float]) -> bool:
    """Whether the median close/fill ratio is within an order of magnitude."""
    if not ratios:
        return True
    ratios = sorted(ratios)
    return 0.1 <= ratios[len(ratios) // 2] <= 10.0


def _fill_ratios(
    px: pd.Series, ticker: str, ccy: str, transactions
) -> list[tuple[str, float]]:
    """(date, close / price) for each of `ticker`'s fills in `ccy`.

    The close is the last one on or before the fill's day, the price the fill
    restated across the book's own split rows (`_close_matches_trades`).
    """
    from stocks.portfolio.corporate import on_market_scale, split_factors

    factors = split_factors(transactions)
    out = []
    for t in transactions:
        if t.ticker != ticker or t.action not in ("buy", "sell"):
            continue
        if t.currency.upper() != ccy or t.price <= 0:
            continue
        near = px[px.index <= pd.Timestamp(t.date)].dropna()
        if near.empty:
            continue
        price, _ = on_market_scale(t, factors)
        out.append((t.date, float(near.iloc[-1]) / price))
    return out


def _off_calendar(px: pd.Series, ticker: str, transactions) -> list[str]:
    """Days `ticker` was bought or sold on which its market printed no bar.

    Only inside the series' own span: before the first bar is history the
    feed does not carry, not a holiday. A Saturday fill counts on Friday's
    bar, since a US after-hours fill is stamped the next day in UTC; a market
    open every day — crypto — never lands here.
    """
    from datetime import date, timedelta

    bars = px.dropna().index
    if bars.empty:
        return []
    have = {d.date() for d in bars}
    first, last = min(have), max(have)
    out = []
    for t in transactions:
        if t.ticker != ticker or t.action not in ("buy", "sell"):
            continue
        day = date.fromisoformat(t.date[:10])
        if not first <= day <= last:
            continue
        if day.weekday() == 5:
            day -= timedelta(days=1)
        if day not in have:
            out.append(t.date)
    return sorted(out)


def complete_download(
    closes: dict[str, pd.Series], tickers: list[str]
) -> dict[str, pd.Series]:
    """`closes`, or `YFRateLimitError` when the bulk download came back gutted.

    `yf.download` drops a symbol Yahoo refused without saying so, and the
    book's download is cached for a quarter hour (an hour under the TWR). A
    throttled burst cached as-is read 46 of 51 positions n/d and the book at
    30k instead of 145k. A few absentees are delisted names (always missing);
    more than a quarter is Yahoo refusing, and raising keeps it out of every
    cache so the next request tries again.

    Names Yahoo said it has no symbol for (`fetch.unlisted`) are not counted:
    they will be missing on every attempt, so counting them turned a book of
    unresolved broker codes into a permanent "rate limited" — nothing ever
    cached, and every page 503'd for good. They read unpriced, held at cost.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.fetch import unlisted

    disowned = unlisted(tickers)
    listed = set(tickers) - disowned
    missing = len(listed - set(closes))
    if missing > max(3, len(listed) // 4):
        obs.warn(
            "portfolio.bulk_prices_missing",
            missing=missing,
            requested=len(tickers),
            priced=len(closes),
            unlisted=len(disowned),
        )
        raise YFRateLimitError
    return closes


def plausible_closes(
    closes: dict[str, pd.Series],
    transactions,
    units: dict[str, tuple[str, float]] | None = None,
) -> dict[str, pd.Series]:
    """`closes` less the series the book's own fills say are another instrument.

    Applied where the book's prices are downloaded, so the live table, the
    basket and the history all see a collided name as unpriced (carried at
    cost) instead of each valuing it off the wrong asset.
    """
    ccy_of = {t.ticker: t.currency for t in transactions if t.action in ("buy", "sell")}
    if units is None:
        units = price_units(list(closes), ccy_of)
    out: dict[str, pd.Series] = {}
    for ticker, s in closes.items():
        ccy, scale = units.get(ticker) or (ccy_of.get(ticker) or "", 1.0)
        px = s.copy()
        px.index = naive_dates(px.index)
        fills = _fill_ratios(px * scale, ticker, ccy.upper(), transactions)
        if _plausible_ratio([off for _, off in fills]):
            out[ticker] = s
            _audit_fills(px, ticker, fills, transactions)
        else:
            obs.warn_once("portfolio.price_ticker_mismatch", ticker, ticker=ticker)
            offs = sorted(off for _, off in fills)
            median = offs[len(offs) // 2]
            if consistency.unit_slip(median):
                # The whole series a hundred off the fills: the feed quotes
                # this name in minor units and `price_units` does not know.
                consistency.report(
                    "currency_off",
                    source="replay",
                    ticker=ticker,
                    key="series",
                    off=round(median, 3),
                    n=len(offs),
                )
    return out


def _audit_fills(px: pd.Series, ticker: str, fills, transactions) -> None:
    """Say what a kept series' fills contradict: their unit, their calendar.

    The series matched the book as a whole; a few fills a hundred off it are
    pence booked as pounds (or the reverse), and a fill on a day the market
    printed nothing is a date a parser shifted. One line per name for each.
    """
    slips = sorted(day for day, off in fills if consistency.unit_slip(off))
    if slips:
        consistency.report(
            "currency_off",
            source="replay",
            ticker=ticker,
            key="fills",
            n=len(slips),
            first=slips[0],
        )
    if off_days := _off_calendar(px, ticker, transactions):
        consistency.report(
            "trade_off_calendar",
            source="replay",
            ticker=ticker,
            key="fills",
            n=len(off_days),
            first=off_days[0],
        )


@dataclass(frozen=True)
class Leg:
    """One ticker's share of the value path, kept for `attribution`.

    `px` is the close in its ISO currency (pence already scaled), `rate` the
    daily rate into `base`, both None when the name never had a usable series
    (carried at cost throughout). `marked` is True on days both exist.
    """

    shares: pd.Series
    value: pd.Series
    px: pd.Series | None
    rate: pd.Series | None
    marked: pd.Series


class Legs(dict):
    """ticker -> Leg, riding in `DataFrame.attrs`.

    pandas deep-copies `attrs` on every slice; the legs are read-only, so the
    copy hands back the same object instead of cloning every series.
    """

    def __deepcopy__(self, memo):
        return self

    def __copy__(self):
        return self


def injected_vs_value(
    transactions,
    closes: dict[str, pd.Series],
    fx: dict[str, pd.Series] | None = None,
    to_base: ToBaseFn = None,
    base: str = "EUR",
    units: dict[str, tuple[str, float]] | None = None,
) -> pd.DataFrame:
    """Daily injected capital vs mark-to-market value of the book, in `base`.

    `closes` = native-currency close series per ticker; `fx` = daily
    currency->`base` rate series (the base currency itself implied 1.0).
    `units` = ticker -> (ISO currency, scale) each close series is quoted in
    (stocks.data.listing.price_units); a ticker missing from it is taken
    to be quoted in its ledger rows' currency. The distinction is the whole
    point: an alias can price a dollar trade off a euro listing, and the close
    converts at the listing's rate — the trade currency only converts the
    cash, in `injected_series`. `fx` must carry every currency `units` names. Held
    days without a usable close/FX quote — ticker absent, delisted mid-hold, or
    (like a delisted ORGN) a stray quote outside the holding window — are
    carried at cost (cumulative net invested): no fake loss, no mark-to-market
    either.
    Columns: injected, value, pnl_pct. Tickers ever carried at cost
    while held are listed in df.attrs['carried_at_cost'].

    `base` is the reporting currency and is read, not assumed: this used to
    test each holding's currency against a literal "EUR", which for a book
    reported in anything else valued its own base-currency names at a rate of
    1.0 and left every *other* name without a series — carried at cost, flat,
    and listed as unpriced. A USD book of two names both up 20% read +4.8%.
    """
    shares = shares_frame(transactions)
    if shares.empty:
        return pd.DataFrame()
    idx = shares.index
    fx = fx or {}
    base = base.upper()
    # Normalised like `shares_frame` above, and for the same reason: a holding
    # that only ever arrived — an opening snapshot, shares moved in kind — has
    # no trade row to read a currency from, and falling back to the base
    # prices a USD position as if its closes were already in EUR.
    ccy_of = {
        t.ticker: t.currency
        for t in transfers.normalize(transactions)
        if t.action in ("buy", "sell")
    }
    units = units or {}

    value = pd.Series(0.0, index=idx)
    carried: list[str] = []
    legs: dict[str, Leg] = {}
    for ticker in shares.columns:
        held = shares[ticker] > 0
        mtm = None
        leg_px = leg_rate = None
        px = closes.get(ticker)
        if px is not None and not px.empty:
            px = px.copy()
            px.index = naive_dates(px.index)
            px = px.reindex(idx).ffill()
            ccy, scale = units.get(ticker) or ((ccy_of.get(ticker) or base), 1.0)
            ccy = ccy.upper()
            px = px * scale
            if not _close_matches_trades(px, ticker, ccy, transactions):
                obs.warn_once("portfolio.price_ticker_mismatch", ticker, ticker=ticker)
            else:
                rate = pd.Series(1.0, index=idx) if ccy == base else fx.get(ccy)
                if rate is not None:
                    rate = rate.copy()
                    rate.index = pd.to_datetime(rate.index)
                    rate = rate.reindex(idx).ffill().bfill()
                    mtm = shares[ticker] * px * rate
                    leg_px, leg_rate = px, rate
        # Held days with no quote fall back to cost, never below zero.
        gap = held if mtm is None else (mtm.isna() & held)
        part = pd.Series(0.0, index=idx)
        if gap.any():
            proxy = (
                injected_series(
                    [t for t in transactions if t.ticker == ticker], to_base, base
                )
                .reindex(idx)
                .ffill()
                .fillna(0.0)
            )
            part += proxy.where(gap, 0.0).clip(lower=0.0)
            carried.append(ticker)
        if mtm is not None:
            part += mtm.fillna(0.0)
        value += part
        legs[ticker] = Leg(
            shares=shares[ticker],
            value=part,
            px=leg_px,
            rate=leg_rate,
            marked=(
                mtm.notna() & leg_px.notna() & leg_rate.notna()
                if mtm is not None and leg_px is not None and leg_rate is not None
                else pd.Series(False, index=idx)
            ),
        )

    injected = (
        injected_series(transactions, to_base, base).reindex(idx).ffill().fillna(0.0)
    )
    pct = pd.Series(float("nan"), index=idx)
    mask = injected > 0
    pct[mask] = value[mask] / injected[mask] - 1
    df = pd.DataFrame({"injected": injected, "value": value, "pnl_pct": pct})
    df.attrs["carried_at_cost"] = carried
    df.attrs["legs"] = Legs(legs)
    return df


def flow_series(
    transactions,
    to_base: ToBaseFn = None,
    tickers: set[str] | None = None,
    base: str = "EUR",
) -> pd.Series:
    """Net external cash flow per date in `base`: buys +, sells −.

    A dividend is deliberately NOT a flow here, and that is the opposite of
    what the textbook says — because the value path these flows are measured
    against is not a textbook one. `load_closes` fetches `auto_adjust=True`
    bars, so every close before an ex-date is scaled down by that dividend:
    the series is already a total return, and the payment shows up in it as a
    drop that never happens rather than as cash leaving. Counting it as a
    withdrawal on top credited it twice — measured on a real book, a KO close
    six months back sits 1.25% under its traded price, and a year of that is a
    year of return nobody earned. A broker transfer is not cash at
    all: matched legs net out (stocks.portfolio.transfers) so the
    return is untouched by the move, and an unmatched arrival reads as the
    contribution it is. Leave `tickers` unset when
    the value path carries unpriced names at cost (injected_vs_value); only
    restrict it when those names are absent from the value entirely, otherwise
    their buys read as instant losses in the TWR.
    """
    to_base = to_base or converter(base)
    flows: dict[str, float] = {}
    for t in transfers.normalize(transactions):
        if tickers is not None and t.ticker not in tickers:
            continue
        if t.action == "buy":
            amt = to_base(t.quantity * t.price + t.fee, t.currency, t.date)
        elif t.action == "sell":
            amt = -to_base(t.quantity * t.price - t.fee, t.currency, t.date)
        else:
            continue
        flows[t.date] = flows.get(t.date, 0.0) + amt
    s = pd.Series(flows, dtype=float).sort_index()
    s.index = pd.to_datetime(s.index)
    return s


def time_weighted_returns(value: pd.Series, flows: pd.Series) -> pd.Series:
    """Daily time-weighted returns from a value path and external flows.

    r_t = (V_t - F_t) / V_{t-1} - 1, flows treated as arriving at day-t close.
    Days with no prior value (before the first buy, or after the book was
    emptied) drop out; performance is unaffected by deposit/withdrawal timing.

    Days pricing below -100% also drop out, their dates listed in
    .attrs['dropped_days']: a long-only book cannot lose more than everything,
    so r <= -1 means the day's flow never landed in the value path (an
    unrecorded split, a corporate action, a ticker with no history). One such
    sample drives the cumulative path negative and takes the annualised
    return, volatility and drawdown down with it.
    """
    if value.empty:
        return pd.Series(dtype=float)
    f = flows.reindex(value.index, fill_value=0.0) if not flows.empty else 0.0
    prev = value.shift(1)
    r = (value - f) / prev - 1
    r = r[prev > 1e-9]
    impossible = r.index[r <= -1]
    if len(impossible):
        r = r.drop(impossible)
    r.attrs["dropped_days"] = list(impossible)
    return r


def money_weighted_return(
    value: pd.Series,
    flows: pd.Series,
    start: pd.Timestamp | None = None,
    *,
    annual: bool = True,
) -> float:
    """Annualised money-weighted return (IRR) of the book over [start, end].

    Investor cash flows: the book's value at the window start counts as the
    buy-in, every external flow inside the window lands on its date (`flows`
    uses the flow_series convention — buys +, sells/dividends −), and the
    final value is the terminal payoff. Unlike the TWR, deposit/withdrawal
    *timing* moves this number: it answers "how did my money do", not "how
    did the strategy do". `start` before the first value falls back to the
    full history. NaN when the window is empty, has no time span, or no rate
    in (-99.99%, 1000%) prices the flows to zero.

    `annual=False` is the same IRR over the window as a whole rather than per
    year — each flow's time counted as a share of the window, not in years —
    so a book a few months old reads what it made over them, not that pace
    stretched to a year. The two are equal on a window exactly a year long.
    """
    value = value.dropna()
    if value.empty:
        return float("nan")
    if start is not None:
        clipped = value[value.index >= start]
        if not clipped.empty:
            value = clipped
    t0, t_end = value.index[0], value.index[-1]
    unit = 365.25 if annual else (t_end - t0).days
    if unit <= 0:
        return float("nan")
    years = (t_end - t0).days / unit
    if years <= 0:
        return float("nan")
    # Flows arrive at day-t close (time_weighted_returns convention), so the
    # opening value already contains any day-t0 flow; count strictly later ones.
    cash = [(0.0, -float(value.iloc[0]))]
    if not flows.empty:
        inside = flows[(flows.index > t0) & (flows.index <= t_end)]
        cash += [((ts - t0).days / unit, -float(f)) for ts, f in inside.items()]
    cash.append((years, float(value.iloc[-1])))

    def npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** t for t, cf in cash)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if math.isnan(f_lo) or math.isnan(f_hi) or (f_lo > 0) == (f_hi > 0):
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        if (npv(mid) > 0) == (f_lo > 0):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def flow_matched_curves(
    value: pd.Series,
    flows: pd.Series,
    axis: pd.DatetimeIndex,
    returns: dict[str, pd.Series],
) -> tuple[pd.Series, pd.Series, dict[str, pd.Series]]:
    """The book and each alternative, fed the book's own cash on its own dates.

    Rebasing an index to the window's first day invests the whole book there
    on day one, which is not what happened: a book built up over two years
    had a fraction of its money at work for the early rally, and an index
    credited with all of it reads years ahead of anything the account could
    have earned. So each alternative here is a shadow account instead. It
    opens at the book's own value on the first day of `axis` (zero when the
    window starts before the first trade), then takes every flow the book
    took — a buy puts the same euros in, a sale takes the same euros out —
    and grows by its own daily return in between: S_t = S_{t-1}(1 + r_t) + F_t.
    A sale larger than what the shadow holds empties it, never below zero.

    Flows land on the first `axis` day on or after their date (a weekend
    trade waits for Monday's close) and arrive at that day's close, like
    `time_weighted_returns`, so the first day's own flows are already inside
    the opening value.

    Every line is then read the same way: value over net money put in (the
    opening value plus the flows so far), minus one — "what my euros became"
    against "what the same euros would have become there". NaN while nothing
    is in. Returns (invested, book line, {name: shadow line}), all on `axis`.
    """
    axis = pd.DatetimeIndex(naive_dates(axis))
    if axis.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, {}
    start = axis[0]
    value = value.dropna()
    value.index = naive_dates(value.index)
    before = value[value.index <= start]
    opening = float(before.iloc[-1]) if not before.empty else 0.0

    if not flows.empty:
        flows = flows.copy()
        flows.index = naive_dates(flows.index)
    later = flows[flows.index > start] if not flows.empty else flows
    slot = axis.searchsorted(pd.DatetimeIndex(later.index), side="left")
    keep = slot < len(axis)
    daily = (
        pd.Series(later.to_numpy()[keep], index=axis[slot[keep]])
        .groupby(level=0)
        .sum()
        .reindex(axis, fill_value=0.0)
        if len(later)
        else pd.Series(0.0, index=axis)
    )
    invested = opening + daily.cumsum()
    live = invested > 1e-9

    def line(path: pd.Series) -> pd.Series:
        return (path / invested - 1).where(live)

    book = line(value.reindex(axis))
    shadows: dict[str, pd.Series] = {}
    for name, rets in returns.items():
        r = rets.copy()
        r.index = naive_dates(r.index)
        r = r[~r.index.duplicated(keep="last")].reindex(axis).fillna(0.0)
        held, path = opening, []
        for day, f in daily.items():
            if day != start:
                held = max(held * (1 + float(r[day])) + float(f), 0.0)
            path.append(held)
        shadows[name] = line(pd.Series(path, index=axis))
    return invested, book, shadows


@dataclass
class Sleeve:
    """One block of the book the projection moves on its own."""

    key: str
    value: float
    growth: float  # median compound annual return
    volatility: float  # annual
    share: float  # of each monthly contribution


def sleeve_stats(
    returns: pd.DataFrame,
    weights: dict[str, float],
    groups: dict[str, list[str]],
    since: dict[str, pd.Timestamp] | None = None,
) -> tuple[dict[str, float], float | None, dict[str, float]]:
    """Annual volatility per group of names, the correlation of the first two,
    and each group's own compound annual growth.

    Each group is weighted as the basket is (`portfolio_returns`, weights
    renormalised per date, each name clipped to when it was first bought) and
    measured on its own calendar: crypto trades every day, stocks five, and a
    weekend of stock "returns" would read as five zero-move days a fortnight.
    The correlation is taken on weekly returns for the same reason — the two
    calendars only agree on a week.

    Growth is the group's geometric return annualised over the span it covers
    — the median compound rate the projection reads, as the holdings actually
    did it. Only a year or more is annualised: three good months raised to a
    year is a number nobody earned.
    """
    vols: dict[str, float] = {}
    growth: dict[str, float] = {}
    weekly: dict[str, pd.Series] = {}
    for key, names in groups.items():
        cols = [c for c in names if c in returns.columns]
        sub = {c: weights[c] for c in cols if weights.get(c)}
        if not sub:
            continue
        series = portfolio_returns(returns[cols], sub, since=since).dropna()
        if len(series) < 20:
            continue
        vols[key] = annualized_volatility(series)
        series.index = naive_dates(series.index)
        if (series.index[-1] - series.index[0]).days >= 365:
            rate = annualized_return(series)
            if math.isfinite(rate):
                growth[key] = rate
        weekly[key] = (1 + series).resample("W").prod() - 1
    corr = None
    if len(weekly) >= 2:
        a, b = list(weekly.values())[:2]
        both = pd.concat([a, b], axis=1, sort=True).dropna()
        if len(both) >= 10:
            corr = float(both.corr().iloc[0, 1])
    return vols, corr, growth


def project_sleeves(
    sleeves: list[Sleeve],
    corr: float = 0.0,
    monthly: float = 0.0,
    years: int = 5,
    inflation: float = 0.0,
    paths: int = 4000,
    seed: int = 7,
) -> tuple[pd.DataFrame, np.ndarray]:
    """A range for what the book could be worth, month by month, `years` out.

    Not a forecast — a spread of outcomes under stated assumptions, one set per
    sleeve (stocks, crypto): a growth rate read as the *median* compound
    annual return, the rate a reader means by "4% a year", and an annual
    volatility. Monthly log-returns are drawn normal at drift ln(1 + g) / 12
    and sigma = vol / sqrt(12), correlated across sleeves by `corr`. Each
    sleeve compounds on its own, so a crypto rally grows the crypto weight the
    way it would in the account; the monthly contribution is split by each
    sleeve's `share` and added at the month's end. The fixed seed draws the
    same fan for the same inputs on every reload.

    `inflation` > 0 deflates every figure to today's money.

    Returns (frame, finals): the frame has p10, p25, p50, p75, p90 and
    `contributed` (today's value plus contributions so far), one row per
    month, row 0 = today; `finals` is every path's last value, for a
    probability of reaching a target.
    """
    months = years * 12
    k = len(sleeves)
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(size=(paths, months, k))
    if k == 2 and corr:
        c = max(min(corr, 0.999), -0.999)
        z[:, :, 1] = c * z[:, :, 0] + math.sqrt(1 - c * c) * z[:, :, 1]
    total = np.zeros((paths, months + 1))
    for n, sl in enumerate(sleeves):
        sigma = max(sl.volatility, 0.0) / math.sqrt(12)
        drift = math.log1p(sl.growth) / 12
        growth = np.exp(drift + sigma * z[:, :, n])
        v = np.empty((paths, months + 1))
        v[:, 0] = sl.value
        add = monthly * sl.share
        for m in range(months):
            v[:, m + 1] = np.maximum(v[:, m] * growth[:, m] + add, 0.0)
        total += v
    contributed = sum(sl.value for sl in sleeves) + monthly * np.arange(months + 1)
    if inflation:
        deflator = (1 + inflation) ** (np.arange(months + 1) / 12)
        total = total / deflator
        contributed = contributed / deflator
    q = np.percentile(total, [10, 25, 50, 75, 90], axis=0)
    frame = pd.DataFrame(
        {
            "p10": q[0],
            "p25": q[1],
            "p50": q[2],
            "p75": q[3],
            "p90": q[4],
            "contributed": contributed,
        }
    )
    return frame, total[:, -1]
