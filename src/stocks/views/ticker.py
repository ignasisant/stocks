"""The ticker page's reads that the chat and the connector share with it.

A quote, the KPI grid, the P/E history, the DCF, the analysts, the options
and the trend, each shaped as the page's response model. The routes in
`api.routes.ticker` are these behind a path and a checked `?base=`; the
chat's toolbox calls them directly, so an answer quotes the figure the page
draws.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from typing import cast

import pandas as pd
from yfinance.exceptions import YFRateLimitError

from stocks import loaders, obs
from stocks.analysis import dcf as dcf_model
from stocks.analysis import review
from stocks.analysis import trend as trend_model
from stocks.analysis.fundamentals import (
    KPI_SOURCES,
    METRIC_ORDER,
    compute_metrics,
    format_value,
    fundamental_tiles,
    lens_verdict,
    missing_reasons,
    peer_band,
    verdict,
)
from stocks.analysis.pe_history import DISPLAY_WINDOWS, window_stats
from stocks.analysis.portfolio import market_live, session_quote
from stocks.cache import carried
from stocks.data.asset_kind import BOND_FUND, FUND_KINDS, MONEY_MARKET
from stocks.data.crypto import is_crypto
from stocks.data.estimates import (
    MIN_COVERAGE,
    consensus,
    eps_revisions,
    rating_trend,
    target_dispersion,
)
from stocks.jsonsafe import num as _num
from stocks.jsonsafe import scalar as _scalar
from stocks.portfolio import consistency
from stocks.schemas import (
    AnalystMonth,
    Analysts,
    AnalystTargets,
    Dcf,
    EpsRevisionRow,
    Kpi,
    Metrics,
    MetricTile,
    OptionsView,
    PeerScope,
    Quote,
    RatingChange,
    TickerJudged,
    Valuation,
    ValuationWindow,
)


def read_trend(ticker: str) -> trend_model.TrendRead:
    """`trend`'s read, for the chat and the connector to share with the page."""
    kind = loaders.asset_kind(ticker)
    if kind in (MONEY_MARKET, BOND_FUND):
        return trend_model.TrendRead()
    bench = _fund_benchmark(ticker) if kind in FUND_KINDS else None
    if bench is None:
        # The company's country only matters on a German floor, where APC.DE
        # is Apple and the DAX says nothing about it; elsewhere it is not asked.
        country = (
            loaders.listing_country(ticker)
            if trend_model.on_german_floor(ticker)
            else None
        )
        bench = trend_model.benchmark_for(ticker, country)
    with ThreadPoolExecutor(max_workers=2) as pool:
        bars = pool.submit(loaders.daily_bars, ticker)
        index = pool.submit(loaders.daily_closes, bench.ticker, "2y") if bench else None
        return trend_model.trend_read(
            bars.result(), index.result() if index else None, bench
        )


def _fund_benchmark(ticker: str):
    """The index of the market a fund's basket trades in, or None.

    EIMI.L is an emerging-markets fund quoted in London: against the FTSE 100
    it reads as a bet on Britain. Its name says where its stocks are
    (`fund_wrapper`); the profile is the one the page's fund card asked for.
    A fund that is its own exposure's index line (EEM) keeps the listing's.
    """
    from stocks.analysis import fund_wrapper

    profile = loaders.fund_profile(ticker)
    if profile is None:
        return None
    bench = fund_wrapper.read(ticker, profile.name, profile.category).benchmark
    return bench if bench is not None and bench.ticker != ticker else None


def quote(symbol: str, base: str | None = None) -> Quote:
    """The live quote. `base` is a currency code already checked, or None:
    the price is restated in it only when one is asked for."""
    ticker = symbol.strip().upper()
    snapshot = session_quote(ticker) or {}
    price = snapshot.get("price")
    ccy = base
    currency = price_base = rate = as_of = None
    # Only when `?base=` asks for the conversion. The quote row names its own
    # currency; the fundamentals pull — seconds on a name the page has not
    # loaded yet, and this header is the first thing it draws — is asked only
    # when that row did not.
    if ccy and not is_crypto(ticker):
        currency = cast(str | None, snapshot.get("currency")) or cast(
            str | None, loaders.fundamentals(ticker).info.get("currency")
        )
        if price is not None and currency:
            price_base, rate, as_of = _price_in(ticker, price, currency, ccy)
    return Quote(
        ticker=ticker,
        price=price,
        pct=snapshot.get("pct"),
        session=snapshot.get("session"),
        as_of=snapshot.get("as_of"),
        market_open=market_live(ticker),
        currency=currency,
        price_base=price_base,
        fx_rate=rate,
        fx_as_of=as_of,
        base=ccy,
        high_52w=snapshot.get("high_52w"),
        low_52w=snapshot.get("low_52w"),
    )


def _price_in(
    ticker: str, price: float, native: str, base: str
) -> tuple[float | None, float | None, str | None]:
    """`price` restated in `base`, minor units (GBp) resolved first.

    Nothing when the two already agree, and nothing when the rate cannot be
    fetched — the same refusal `_market_cap_in` makes, generalised past
    dollars: a listing's own quote currency can be anything, not just USD.
    """
    from stocks.data.fx import spot
    from stocks.data.listing import quote_unit

    iso, scale = quote_unit(native)
    if iso is None or iso == base:
        return None, None, None
    try:
        rate, as_of = spot(iso, base)
    except Exception as exc:
        obs.warn("api.quote_fx_failed", ticker=ticker, native=iso, base=base,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None, None, None
    return price * scale * rate, rate, as_of


def live_prices(tickers: list[str]) -> dict[str, float]:
    """The price the page header prints for each of `tickers`, off the
    five-minute quote memo (`loaders.quotes`, one request for all of them).

    The snapshot's `price`, extended hours included, because that is the
    figure the header shows. Names Yahoo did not quote are absent; a failed
    request is an empty answer, never a failed card.
    """
    out: dict[str, float] = {}
    if not tickers:
        return out
    with obs.swallow("ticker.live_prices", tickers=len(tickers)):
        snaps = loaders.quotes(tuple(sorted(set(tickers))))
        for ticker in tickers:
            price = _num((snaps.get(ticker) or {}).get("price"))
            if price is not None and price > 0:
                out[ticker] = price
    return out


def at_live(computed: dict, price: float | None) -> dict:
    """`computed` read at `price`, the business unchanged (`review.at_price`).

    The fundamentals pull is cached for hours, so its price trails the quote
    drawn beside it: prod 2026-11-23, NVDA's header quoted 167.82 (+33.7 %)
    over a DCF, a target range and a comps row all priced at Friday's 125.53.
    No live price, or one about a hundred times the pull's (pence against
    pounds, `consistency.unit_slip`), leaves the pull's own.
    """
    taken = _num(computed.get("price"))
    if not price or not taken or price <= 0 or taken <= 0 or price == taken:
        return computed
    if consistency.unit_slip(price / taken):
        return computed
    out = review.at_price(computed, price / taken)
    out["price"] = price
    return out


def _fundamentals_and_price(ticker: str, price: float | None):
    """The fundamentals pull and the live price, side by side: the quote is a
    request of its own on a cold memo and should not queue behind a cold pull."""
    if price is not None:
        return loaders.fundamentals(ticker), price
    with ThreadPoolExecutor(max_workers=1) as pool:
        live = pool.submit(carried(live_prices), [ticker])
        raw = loaders.fundamentals(ticker)
        return raw, live.result().get(ticker)


def metrics(
    symbol: str, base: str | None = None, price: float | None = None
) -> Metrics:
    """The KPI grid, every price-bound KPI read at the live price: `price`
    when the caller holds one, else the quote memo's (`at_live`). `base` is a
    currency code already checked, or None.

    The fundamentals pull is cached for hours, so its price trails the quote
    (prod 2026-11-09: NVDA quoted 178.25 over a grid priced at 173.97). The
    multiples are read at the price on the same screen; the business is the
    one the filings describe either way (`review.at_price`).
    """
    ticker = symbol.strip().upper()
    raw, live = _fundamentals_and_price(ticker, price)
    computed = at_live(compute_metrics(raw), live)
    # No account dependency: every figure here is the company's, not the
    # reader's, and a route that demanded one would stop answering the scripts
    # that hold a token and name nobody. The single per-reader line — the market
    # cap in their own money — is asked for explicitly with `?base=`.
    ccy = base
    cap, rate, as_of = _market_cap_in(computed, ccy) if ccy else (None, None, None)
    equity = str(computed.get("quote_type") or "EQUITY").upper() == "EQUITY"
    view = review.lens(computed)
    tiles = fundamental_tiles(view) if equity else fundamental_tiles(review.STANDARD)
    keys = list(dict.fromkeys([*METRIC_ORDER, *(tile.key for tile in tiles)]))
    scope, band = (
        _peer_band(ticker, computed, raw, [tile.key for tile in tiles])
        if equity
        else (None, {})
    )
    normal = review.peak_pe(computed) if equity else None
    if equity:
        _log_missing(ticker, raw, computed, view, [tile.key for tile in tiles])
    return Metrics(
        ticker=ticker,
        currency=cast(str | None, computed.get("currency")),
        quote_type=cast(str | None, computed.get("quote_type")),
        kpis=[_kpi(key, computed.get(key), computed, band.get(key)) for key in keys],
        grid=[
            MetricTile(key=tile.key, label_key=tile.label, help_key=tile.help)
            for tile in tiles
        ],
        lens=view,
        peers=scope,
        normal_pe=normal,
        reported_pe=_num(computed.get("pe_ttm_reported")),
        cautions=review.cautions(computed) if equity else [],
        judged=_judged(computed) if equity else None,
        market_cap_base=cap,
        market_cap_base_formatted=(
            format_value("market_cap", cap) if cap is not None else None
        ),
        fx_rate=rate,
        fx_as_of=as_of,
        base=ccy,
    )


def _judged(computed: dict) -> TickerJudged:
    """`review.judge_candidate` on the grid's own metrics: no request of its
    own, and the verdict the Review page gives the name as an outside row."""
    verdict = review.judge_candidate(computed, kind="stock")
    return TickerJudged(
        verdict=verdict.verdict,
        reasons=list(verdict.reasons),
        quality=_num(verdict.quality),
        cheapness=_num(verdict.cheapness),
        implied_growth=_num(review.implied_growth(computed)),
        past_growth=_num(review.past_growth(computed)),
    )


def _log_missing(ticker: str, raw, computed: dict, view: str, keys: list[str]) -> None:
    """One `data.missing` line per blank tile, once a window per ticker.

    `stocks logs stats --event data.missing --by reason` tells the gaps a
    company has (a loss has no P/E per growth) from the ones the feed left
    (no statements, a Yahoo field that never came), and `--by kpi` which tile
    goes blank most. A log line never fails the grid.
    """
    with obs.swallow("data.missing_failed", ticker=ticker):
        for key, reason in missing_reasons(raw, computed, keys).items():
            if obs.first_sighting("data.missing", (ticker, key)):
                obs.event("data.missing", ticker=ticker, kpi=key, reason=reason,
                          lens=view)


def _peer_band(
    ticker: str, computed: dict, raw, keys: list[str]
) -> tuple[PeerScope | None, dict[str, tuple[float, float, float]]]:
    """The rivals' P25/median/P75 per KPI, off the nightly sector scan.

    The scan, never a fetch: forty rivals' fundamentals would be the slowest
    thing on the page, and a night-old middle is the same middle. Nothing on
    any failure — a reference line must never be what fails the grid.
    """
    from stocks.analysis.sectors import peer_rows

    try:
        industry = cast(str | None, computed.get("industry"))
        sector = raw.info.get("sector")
        if not industry and not sector:
            return None, {}
        found = peer_rows(loaders.sector_scans(), ticker, industry, sector)
    except Exception as exc:
        obs.warn("api.peer_band_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None, {}
    if found is None:
        return None, {}
    kind, name, rows = found
    scope = PeerScope(kind=kind, name=name, count=len(rows))
    return scope, peer_band([computed, *rows], keys)


def _market_cap_in(
    computed: dict, base: str
) -> tuple[float | None, float | None, str | None]:
    """Market cap restated in the reporting currency, when that says something.

    Only for a company quoting in dollars, which is what the page converts: a
    market cap is the one figure on this grid a reader compares against their
    own book, and the book is in their currency. Nothing when the two already
    agree, and nothing when the rate cannot be fetched — a page that cannot
    price it says so rather than printing an unconverted number as converted.
    """
    cap = computed.get("market_cap")
    if not cap or computed.get("currency") != "USD" or base == "USD":
        return None, None, None
    try:
        from stocks.data.fx import spot

        rate, as_of = spot("USD", base)
    except Exception as exc:
        obs.warn("api.market_cap_fx_failed", ticker=computed.get("ticker"),
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None, None, None
    return float(cap) * rate, rate, as_of


def _kpi(
    key: str,
    value,
    metrics: dict,
    band: tuple[float, float, float] | None = None,
) -> Kpi:
    """One KPI row, with its band's label AND the tone that band carries.

    Both, because the labels are a growing set — "net cash", "buybacks",
    "heavy dilution" — and a client colouring by label shows every band it has
    not heard of as neutral. Banded on the company's own lens
    (`lens_verdict`), and with its rivals' middle when the scan has one.
    """
    banded = lens_verdict(key, value, metrics)
    return Kpi(
        key=key,
        label=KPI_SOURCES[key].label,
        value=_scalar(value),
        formatted=format_value(key, value),
        unit=KPI_SOURCES[key].unit,
        level=KPI_SOURCES[key].level,
        verdict=banded[0] if banded else None,
        verdict_tone=banded[1] if banded else None,
        desc=KPI_SOURCES[key].desc,
        peer_band=list(band) if band else None,
    )


def valuation(symbol: str) -> Valuation:
    """Today's P/E against its own past, over the page's four ranges."""
    ticker = symbol.strip().upper()
    result = loaders.valuation(ticker)
    series = result.get("pe")
    # The page's four ranges, not the domain's default set: half a year of a
    # company's own history cannot answer "is this expensive for this company",
    # and the app offers 1y/3y/5y/10y for exactly that reason. Recomputed here
    # rather than re-fetched — it is a pandas pass over a series already held.
    # Counted back from the last close, not the series' last point: a 20-F
    # filer's line can stop months before today, and a "1y" ending there is
    # not the last year.
    as_of = result.get("as_of")
    stats = (
        window_stats(series, windows=DISPLAY_WINDOWS, end=as_of)
        if series is not None and not series.empty
        else result.get("stats")
    )

    windows = [
        ValuationWindow(
            window=str(label),
            days=DISPLAY_WINDOWS.get(str(label), 0),
            mean=_num(row.get("mean")),
            median=_num(row.get("median")),
            low=_num(row.get("low")),
            high=_num(row.get("high")),
            percentile=_num(row.get("percentile")),
            premium=_num(row.get("premium")),
        )
        for label, row in stats.iterrows()
    ] if stats is not None and not stats.empty else []

    current = _num(result.get("current"))
    # Banded here, like every other verdict: a client picking its own P/E
    # thresholds is a second place for "expensive" to mean something else.
    banded = verdict("pe_ttm", current)
    dates: list[str] = []
    pe: list[float | None] = []
    if series is not None and not series.empty:
        dates = [str(pd.Timestamp(ts).date()) for ts in series.index]
        pe = [_num(v) for v in series]
        # A line that stops before the last close runs on blank to it, so a
        # client trimming to "the last N days" counts them from today and the
        # gap reads as no figure, not as a chart that ends today.
        if as_of is not None and pd.Timestamp(as_of) > series.index.max():
            tail = pd.bdate_range(
                series.index.max() + pd.Timedelta(days=1), pd.Timestamp(as_of)
            )
            dates += [str(ts.date()) for ts in tail]
            pe += [None] * len(tail)
    return Valuation(
        ticker=ticker,
        source=result.get("source"),
        basis=result.get("basis"),
        current=current,
        current_verdict=banded[0] if banded else None,
        current_tone=banded[1] if banded else None,
        dates=dates,
        pe=pe,
        windows=windows,
    )


def dcf(symbol: str) -> Dcf:
    """The five-year DCF with every input, or the reason there is none.

    Its upside against the live price, the one the header prints (`at_live`):
    the value per share is the cash flows', the price is today's."""
    ticker = symbol.strip().upper()
    raw, live = _fundamentals_and_price(ticker, None)
    out = dcf_model.compute(raw, at_live(compute_metrics(raw), live))
    return Dcf(
        ticker=ticker,
        reason=out.reason,
        currency=out.currency,
        price=_num(out.price),
        fcf=_num(out.fcf),
        net_debt=_num(out.net_debt),
        shares=_num(out.shares),
        growth=_num(out.growth),
        growth_source=out.growth_source,
        wacc=out.wacc,
        terminal=out.terminal,
        value=_num(out.value),
        upside=_num(out.upside),
        waccs=list(out.waccs),
        terminals=list(out.terminals),
        grid=[[_num(v) for v in row] for row in out.grid],
    )


def analysts(symbol: str) -> Analysts:
    """The consensus, its price targets, the EPS revisions and the recent
    rating moves."""
    ticker = symbol.strip().upper()
    # Side by side: the rating changes are their own Yahoo call, and queued
    # behind the estimates they would add a second wait to a cold card.
    with ThreadPoolExecutor(max_workers=2) as pool:
        moved = pool.submit(carried(_rating_changes_or_none), ticker)
        live = pool.submit(carried(live_prices), [ticker])
        raw = loaders.estimates(ticker)
        changes = moved.result()
        now = live.result().get(ticker)
    cons = consensus(raw)
    # The targets payload carries the price of whenever it was pulled; the
    # track and both upsides are read against the header's (`at_live`).
    moved_to = at_live({"price": cons.price}, now)["price"]
    if moved_to != cons.price:
        cons = replace(cons, price=moved_to)
    months = rating_trend(raw, date.today())
    latest = months[-1] if months else None
    count = latest.total if latest else 0

    targets = None
    if cons.target_mean is not None:
        price = cons.price

        def _upside(target: float | None) -> float | None:
            return _num(target / price - 1) if target is not None and price else None

        targets = AnalystTargets(
            low=_num(cons.target_low),
            median=_num(cons.target_median),
            mean=_num(cons.target_mean),
            high=_num(cons.target_high),
            upside_mean=_upside(cons.target_mean),
            upside_median=_upside(cons.target_median),
            dispersion=_num(target_dispersion(cons)),
        )

    return Analysts(
        ticker=ticker,
        currency=_quote_currency(ticker),
        price=_num(cons.price),
        analysts=count,
        covered=count >= MIN_COVERAGE,
        min_coverage=MIN_COVERAGE,
        rating=cons.rating,
        rating_mean=_num(cons.rating_mean),
        months=[
            AnalystMonth(
                month=m.month,
                strong_buy=m.counts.get("strongBuy", 0),
                buy=m.counts.get("buy", 0),
                hold=m.counts.get("hold", 0),
                sell=m.counts.get("sell", 0),
                strong_sell=m.counts.get("strongSell", 0),
                total=m.total,
                mean=_num(m.mean),
            )
            for m in months
        ],
        targets=targets,
        revisions=[
            EpsRevisionRow(
                period=r.period,
                current=_num(r.current),
                change_7d=_num(r.change(7)),
                change_30d=_num(r.change(30)),
                change_90d=_num(r.change(90)),
                up_7d=r.up_7d,
                up_30d=r.up_30d,
                down_7d=r.down_7d,
                down_30d=r.down_30d,
            )
            for r in eps_revisions(raw)
        ],
        changes=[RatingChange(**c) for c in changes],
    )


def _rating_changes_or_none(ticker: str) -> list[dict]:
    """The recent rating moves, or [] when Yahoo refuses: the card keeps the
    consensus it has and just has no moves to list."""
    try:
        return loaders.rating_changes(ticker)
    except Exception as exc:  # noqa: BLE001 — one missing block, not a 500
        obs.warn(
            "api.rating_changes_failed", ticker=ticker, error_type=type(exc).__name__
        )
        return []


def options(symbol: str) -> OptionsView:
    """Implied volatility and the put/call balance; `listed` false for a
    name without options. A throttled Yahoo raises."""
    ticker = symbol.strip().upper()
    if is_crypto(ticker):
        return OptionsView(ticker=ticker, listed=False)
    try:
        view = loaders.options_view(ticker)
    except YFRateLimitError:
        raise
    except Exception as exc:  # noqa: BLE001
        obs.warn("api.options_failed", ticker=ticker, error_type=type(exc).__name__)
        return OptionsView(ticker=ticker, listed=False)
    if view is None:
        return OptionsView(ticker=ticker, listed=False)
    return OptionsView(ticker=ticker, listed=True, **view)


def _quote_currency(ticker: str) -> str | None:
    """The currency the share quotes in, which its price targets are set in.

    Off the fundamentals pull the KPI grid already made, so it costs a cache
    read; None when that pull failed — a target then prints without a mark
    rather than with a wrong one.
    """
    try:
        info = loaders.fundamentals(ticker).info or {}
    except Exception:  # noqa: BLE001 — a missing mark is not a failed section
        return None
    currency = info.get("currency")
    return str(currency) if currency else None
