"""Risk of the current basket: volatility, beta, drawdown, concentration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from stocks import loaders
from stocks.analysis.portfolio import (
    allocation_parts,
    annualized_volatility,
    beta,
    correlation_matrix,
    effective_positions,
    flow_matched_curves,
    flow_series,
    historical_var,
    risk_shares,
    top_n_weight,
)
from stocks.api.deps import Account, Base, reporting_currency
from stocks.cache import carried
from stocks.jsonsafe import num as _num
from stocks.portfolio import custody
from stocks.schemas import (
    AllocationHolding,
    AllocationSlice,
    Risk,
    RiskCurves,
    RiskName,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# Windows the basket report will measure over. A period nobody defined is
# refused rather than guessed at: yfinance takes whatever string it is handed
# and an unknown one comes back as an empty frame, which would read as a book
# with no risk at all.
#
# "inception" is the default and the one the Portfolio page opens on: the fetch
# reaches back to the book's first trade and every return is clipped there, so
# a volatility or a beta is never scored over years nobody held anything (see
# `loaders.basket_report_since`). "max" stays accepted for a client that asked
# for it before inception existed; the pages no longer offer it, because an
# unclipped IPO-to-date backtest answers a question about the stock, not the
# book.
_RISK_PERIODS = ("inception", "6mo", "1y", "2y", "5y", "max")


@router.get("/risk", response_model=Risk, summary="Risk of the current basket")
def risk(
    account: Account,
    base: Base = None,
    period: Annotated[
        str,
        Query(
            description=(
                "Return window: inception (the default — clipped to the "
                "book's first trade), 6mo, 1y, 2y, 5y, max."
            )
        ),
    ] = "inception",
) -> Risk:
    """Today's holdings backtested at fixed weights over `period`.

    A profile of what is held *now*, which is not what the book did — that is
    `/portfolio/performance`, and the two disagree by exactly as much as the
    book has changed shape. Weights are put on the reporting currency's footing
    before anything is measured, because a mostly-USD book with some EUR in it
    is weighted wrong by native prices.
    """
    if period not in _RISK_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"period must be one of {', '.join(_RISK_PERIODS)}",
        )
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    # The priced table and the book's value path read the book's download; the
    # backtest has its own. Side by side, the page waits for the slower one
    # instead of the sum.
    pool = ThreadPoolExecutor(max_workers=2)
    priced = pool.submit(carried(loaders.positions_table), db, mtime, ccy)
    path = pool.submit(carried(loaders.history), db, mtime, ccy)
    pool.shutdown(wait=False)
    report = (
        loaders.basket_report_since(db, mtime, ccy)
        if period == "inception"
        else loaders.basket_report(db, mtime, ccy, period)
    )
    if report is None or not report.weights:
        return Risk(base=ccy, period=period)

    # What each slice is worth and what it cost, off the same priced rows the
    # positions table and the summary tiles read, so a slice's euros agree
    # with the tiles beside it. Only rows that priced count, on both sides.
    table = priced.result()
    values: dict[str, float] = {}
    costs: dict[str, float] = {}
    if not table.empty:
        for ticker, row in table[table["value"].notna()].iterrows():
            values[str(ticker)] = float(row["value"])
            costs[str(ticker)] = float(row["cost"])

    def slices(
        weights: dict[str, float],
        value_parts: dict[str, dict[str, float]],
        cost_parts: dict[str, dict[str, float]],
    ) -> list[AllocationSlice]:
        out = []
        for bucket, weight in sorted(weights.items(), key=lambda kv: -kv[1]):
            held = value_parts.get(bucket, {})
            paid = cost_parts.get(bucket, {})
            out.append(
                AllocationSlice(
                    label=str(bucket),
                    weight=float(weight),
                    value=_num(sum(held.values())) if held else None,
                    cost=_num(sum(paid.get(t, 0.0) for t in held)) if held else None,
                    holdings=[
                        AllocationHolding(
                            ticker=ticker, value=amount, cost=paid.get(ticker, 0.0)
                        )
                        for ticker, amount in sorted(
                            held.items(), key=lambda kv: -kv[1]
                        )
                    ],
                )
            )
        return out

    allocations = {
        key: slices(
            loaders.allocation_weights(
                db, mtime, ccy, report.meta, key, report.allocation(key).to_dict()
            ),
            allocation_parts(values, report.meta, key),
            allocation_parts(costs, report.meta, key),
        )
        for key in ("sector", "country", "currency")
    }
    # Custody joins only when the book actually spans brokers: a single-broker
    # 100% slice says nothing. It reuses the weights above, so it costs no fetch.
    held_by = loaders.custody(db, mtime)
    # Weighted off the priced values the three splits above and the slices'
    # own sums read, not the backtest's last-close weights: those drop names
    # with no series in the window, so the donut disagreed with its own euros.
    by_broker = (
        _shares(custody.broker_parts(held_by, values))
        if values
        else custody.broker_weights(held_by, report.weights)
    )
    if len(by_broker) > 1:
        allocations["broker"] = slices(
            by_broker,
            custody.broker_parts(held_by, values),
            custody.broker_parts(held_by, costs),
        )

    corr = correlation_matrix(report.returns)
    # The book's own line, which the report knows nothing about: `basket_report`
    # backtests today's holdings, and what the account actually earned is the
    # ledger's value path. Both belong on one axis or neither says much — the
    # gap between them is exactly how much the book has changed shape.
    hist, twr, missing = path.result()
    flows = flow_series(loaders.ledger_state(db, mtime, ccy).txs, base=ccy)
    return Risk(
        base=ccy,
        period=period,
        volatility=_num(report.volatility),
        max_drawdown=_num(report.max_drawdown),
        var_95=_num(historical_var(report.port_returns)),
        effective_names=_num(effective_positions(report.weights)),
        top5_weight=_num(top_n_weight(report.weights, 5)),
        betas={
            bench: value
            for bench in report.bench_returns
            if (value := _num(report.beta_vs(bench))) is not None
        },
        weights=report.weights,
        allocation={k: v for k, v in allocations.items() if v},
        correlation={
            str(row): {
                str(col): value
                for col, raw in corr.loc[row].items()
                if (value := _num(raw)) is not None
            }
            for row in corr.index
        },
        names=_names(report),
        curves=_curves(report, hist, flows),
        missing=missing,
        dropped_days=[
            str(pd.Timestamp(day).date()) for day in twr.attrs.get("dropped_days", ())
        ],
    )


def _shares(parts: dict[str, dict[str, float]]) -> dict[str, float]:
    """Each bucket's sum as a share of all of them, largest first."""
    sums = {label: sum(held.values()) for label, held in parts.items()}
    total = sum(sums.values())
    if not total:
        return {}
    return dict(sorted(((k, v / total) for k, v in sums.items()), key=lambda kv: -kv[1]))


def _names(report) -> dict[str, RiskName]:
    """Each held name's volatility, betas and share of the basket's risk —
    what the correlation grid's hover reads beside a pair."""
    shares = risk_shares(report.returns, report.port_returns, report.weights)
    out: dict[str, RiskName] = {}
    for name in report.returns.columns:
        series = report.returns[name].dropna()
        if series.empty:
            continue
        out[str(name)] = RiskName(
            volatility=_num(annualized_volatility(series)),
            betas={
                bench: value
                for bench, returns in report.bench_returns.items()
                if (value := _num(beta(series, returns))) is not None
            },
            risk_share=_num(shares.get(name)),
        )
    return out


def _points(values: pd.Series) -> list[float | None]:
    return [_num(v) for v in values]


def _curves(report, hist: pd.DataFrame, flows: pd.Series) -> RiskCurves | None:
    """The lines on one axis: the book, today's basket, the benchmarks.

    The axis is the basket's trading days. Nothing is rebased to its first
    day: each alternative is fed the book's own flows on their own dates
    (`flow_matched_curves`), so an index is credited with the euros the book
    actually had at work, when it had them — not with all of it from day one.
    """
    axis = report.returns.index
    if axis.empty:
        return None
    # An axis whose first entry is not a date has no window to clip to, and
    # `NaT` is what pandas hands back for one — it is also the reason this is
    # an isinstance check and not a truth test.
    if not isinstance(pd.Timestamp(axis[0]), pd.Timestamp):
        return None
    value = hist["value"] if "value" in hist else pd.Series(dtype=float)
    invested, book, shadows = flow_matched_curves(
        value,
        flows,
        axis,
        {
            "basket": report.port_returns,
            **{f"bench:{name}": series for name, series in report.bench_returns.items()},
        },
    )
    return RiskCurves(
        dates=[str(day.date()) for day in book.index],
        invested=_points(invested.where(invested > 1e-9)),
        portfolio=_points(book),
        basket=_points(shadows["basket"]),
        benchmarks={
            name: _points(shadows[f"bench:{name}"]) for name in report.bench_returns
        },
    )
