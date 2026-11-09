"""Where the book could be in a few years, from its own past and the plan."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from urllib.error import URLError

import pandas as pd
from fastapi import APIRouter, Query
from yfinance.exceptions import YFRateLimitError

from stocks import accounts, loaders, obs
from stocks.accounts import UserPaths
from stocks.analysis.portfolio import flow_series, project_sleeves
from stocks.api.deps import Account, Base, reporting_currency
from stocks.data import fx
from stocks.frames import midnight
from stocks.jsonsafe import num as _num
from stocks.schemas import Projection, ProjectionPlan, ProjectionSleeve

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# Median compound annual growth per sleeve when the caller names none. Stocks:
# roughly what world equities have compounded at over the long run — never
# the book's own history by default, where a good two years projected forward
# five is a wish, not a plan (`stock_own` draws it when the reader asks).
# Crypto: zero, because there is no long run to read one off, and the recent
# one would project a bubble.
_DEFAULT_GROWTH = {"stocks": 0.08, "crypto": 0.0}
# Used only when a sleeve has no measurable volatility (too little history).
_DEFAULT_VOL = {"stocks": 0.20, "crypto": 0.60}
# Deflator for "today's money": the ECB's target, not a forecast of it.
_INFLATION = 0.02
# How far back the projection draws the book before its fan starts.
_PAST_MONTHS = 12
# Share of a sleeve's value the risk download must price for its measured
# volatility and growth to stand for the sleeve.
_MIN_COVERAGE = 0.5
# The investor profile's horizon as one of the page's spans: the far end of
# each band, and ten years for "five or more" — the page's longest.
_HORIZON_YEARS = {"under_1y": 1, "1_3y": 3, "3_5y": 5, "5y_plus": 10}


@router.get(
    "/projection", response_model=Projection, summary="Range for the value years out"
)
def projection(
    account: Account,
    base: Base = None,
    years: Annotated[
        int | None,
        Query(
            ge=1,
            le=30,
            description="Default 5, or the profile's horizon with `from_plan`.",
        ),
    ] = None,
    stock_growth: Annotated[
        float | None,
        Query(ge=-0.5, le=0.5, description="Median compound annual; default 8%."),
    ] = None,
    crypto_growth: Annotated[
        float | None,
        Query(ge=-0.9, le=2.0, description="Median compound annual; default 0%."),
    ] = None,
    stock_own: Annotated[
        bool,
        Query(
            description=(
                "Grow stocks at their own measured rate (today's holdings, up "
                "to 2 years) instead of `stock_growth`; falls back when unmeasured."
            )
        ),
    ] = False,
    crypto_own: Annotated[
        bool,
        Query(description="The same for crypto, instead of `crypto_growth`."),
    ] = False,
    crypto_share: Annotated[
        float | None,
        Query(
            ge=0,
            le=1,
            description="Share of each contribution to crypto; default its weight today.",
        ),
    ] = None,
    monthly: Annotated[
        float | None,
        Query(
            ge=0,
            description=(
                "Contribution per month; default the last 12 months' average "
                "net money put in."
            ),
        ),
    ] = None,
    real: Annotated[
        bool, Query(description="Deflate the future to today's money (2% a year).")
    ] = False,
    target: Annotated[
        float | None,
        Query(
            gt=0,
            description="Value to reach; the share of paths that end at or above it.",
        ),
    ] = None,
    from_plan: Annotated[
        bool,
        Query(
            description=(
                "Fill what is not given from the investor plan: `monthly` is its "
                "contribution per month (0 without one), `years` the profile's "
                "horizon. The plan itself is echoed under `plan` either way."
            )
        ),
    ] = False,
) -> Projection:
    """Where the book's value could be `years` out, as a percentile fan.

    Starts from today's value split into two sleeves — stocks and crypto, by
    today's market-value weights — each with its own median growth rate and
    its own measured volatility (`basket_report` over two years, every name
    clipped to its first buy), correlated at the weekly correlation the two
    actually showed (`sleeve_stats`, `project_sleeves`).

    `stock_own` / `crypto_own` swap a sleeve's chosen rate for the one its
    current holdings compounded at over the same window — the reader's ask,
    echoed as `own_growth` on every sleeve so the page can offer it by number.

    `from_plan` starts the page where the reader's plan stands rather than at
    nothing added; a figure the reader types still wins over it.
    """
    from stocks.analysis.portfolio import Sleeve, first_owned, sleeve_stats
    from stocks.data.crypto import is_crypto

    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    hist, _twr, _missing = loaders.history(db, mtime, ccy)
    start_value = loaders.book_value_today(db, mtime, ccy, hist) or 0.0

    txs = loaders.ledger_state(db, mtime, ccy).txs
    flows = flow_series(txs, base=ccy)
    year_ago = pd.Timestamp(date.today()) - pd.Timedelta(days=365)
    recent = flows[flows.index > year_ago] if not flows.empty else flows
    suggested = max(float(recent.sum()) / 12, 0.0) if not recent.empty else 0.0
    suggested = round(suggested / 10) * 10

    # The split comes off the positions table, unpriced rows at cost, not off
    # the risk report's weights: those are renormalised over whatever the
    # download priced, so a throttled fetch that only brought back one coin
    # read as a book 100% in that coin, at that coin's volatility.
    table = loaders.positions_table(db, mtime, ccy)
    worth = (
        table["value"].fillna(table["cost"])
        if not table.empty and {"value", "cost"} <= set(table.columns)
        else pd.Series(dtype=float)
    )
    sleeve_of = {t: "crypto" if is_crypto(t) else "stocks" for t in worth.index}
    held = {
        key: float(worth[[sleeve_of[t] == key for t in worth.index]].sum())
        for key in ("stocks", "crypto")
    }
    total = held["stocks"] + held["crypto"]

    vols: dict[str, float] = {}
    measured: dict[str, float] = {}
    corr = None
    weights: dict[str, float] = {}
    try:
        report = loaders.basket_report(db, mtime, ccy, "2y")
        if report is not None:
            weights = report.weights
            groups = {
                "stocks": [t for t in weights if not is_crypto(t)],
                "crypto": [t for t in weights if is_crypto(t)],
            }
            vols, corr, measured = sleeve_stats(
                report.returns, weights, groups, since=first_owned(txs)
            )
            # A sleeve the download covered less than half of is measured on
            # the names that happened to price, not on what is held: its
            # figures fall back to the presets, and the correlation with them.
            for key, names in groups.items():
                covered = float(worth.reindex(names).fillna(0).sum())
                if held[key] and covered < _MIN_COVERAGE * held[key]:
                    vols.pop(key, None)
                    measured.pop(key, None)
                    corr = None
    except (URLError, YFRateLimitError):
        obs.warn("projection.volatility_unavailable")

    crypto_weight = (
        held["crypto"] / total
        if total > 0
        else sum(w for t, w in weights.items() if is_crypto(t))
    )
    share = crypto_weight if crypto_share is None else crypto_share
    chosen = {"stocks": stock_growth, "crypto": crypto_growth}
    own = {
        key
        for key, asked in (("stocks", stock_own), ("crypto", crypto_own))
        if asked and key in measured
    }
    growth: dict[str, float] = {}
    for key in ("stocks", "crypto"):
        picked = chosen[key]
        growth[key] = (
            measured[key] if key in own
            else _DEFAULT_GROWTH[key] if picked is None else picked
        )
    split = {"stocks": 1 - crypto_weight, "crypto": crypto_weight}
    shares = {"stocks": 1 - share, "crypto": share}
    sleeves = [
        Sleeve(
            key=key,
            value=start_value * split[key],
            growth=growth[key],
            volatility=vols.get(key, _DEFAULT_VOL[key]),
            share=shares[key],
        )
        for key in ("stocks", "crypto")
        if split[key] > 0 or shares[key] > 0
    ]
    guest = account.root == accounts.GUEST_DIR
    stated = None if guest else _projection_plan(account, ccy)
    if monthly is not None:
        per_month = monthly
    elif from_plan:
        per_month = (stated.monthly if stated else None) or 0.0
    else:
        per_month = suggested
    if years is None:
        years = (stated.years if from_plan and stated else None) or 5
    echo = [
        ProjectionSleeve(
            key=sl.key,
            value=round(sl.value, 2),
            weight=split[sl.key],
            growth=sl.growth,
            growth_own=sl.key in own,
            own_growth=_num(measured.get(sl.key)),
            volatility=sl.volatility,
            volatility_measured=sl.key in vols,
            share=sl.share,
        )
        for sl in sleeves
    ]
    common: dict[str, Any] = dict(
        base=ccy,
        years=years,
        sleeves=echo,
        correlation=_num(corr),
        crypto_weight=crypto_weight,
        monthly=per_month,
        monthly_suggested=suggested,
        plan=stated,
        real=real,
        inflation=_INFLATION,
        target=target,
    )
    if start_value <= 0 and per_month <= 0:
        return Projection(**common)
    fan, finals = project_sleeves(
        sleeves,
        corr=corr or 0.0,
        monthly=per_month,
        years=years,
        inflation=_INFLATION if real else 0.0,
    )
    # The road so far, one point a month, so the fan reads as a continuation
    # of the book rather than a line out of nowhere. Only the last year: the
    # chart looks ahead, and a long past squeezes the fan into a corner. The
    # current month is left off: today's value is the fan's own first point.
    # Past figures stay the euros they were — only the future is deflated.
    past = pd.DataFrame()
    if not hist.empty and {"value", "injected"} <= set(hist.columns):
        monthly_end = hist[["value", "injected"]].resample("ME").last()
        month = midnight(date.today().replace(day=1))
        past = monthly_end[
            (monthly_end.index < month)
            & (monthly_end.index >= month - pd.DateOffset(months=_PAST_MONTHS))
        ]
        past = past[past["injected"].fillna(0) > 0]
    today = pd.Timestamp(date.today())
    dates = [today + pd.DateOffset(months=m) for m in range(len(fan))]
    return Projection(
        **common,
        start_value=start_value,
        target_probability=(
            float((finals >= target).mean()) if target is not None else None
        ),
        dates=[f"{d:%Y-%m-%d}" for d in dates],
        **{col: [round(float(v), 2) for v in fan[col]] for col in fan.columns},
        history_dates=[str(d.date()) for d in past.index],
        history_value=[_num(v) for v in past["value"]] if not past.empty else [],
        history_invested=[_num(v) for v in past["injected"]] if not past.empty else [],
    )


def _projection_plan(paths: UserPaths, ccy: str) -> ProjectionPlan:
    """The plan's say on the projection's inputs, its contribution in `ccy`.
    The plan states money in the reporting currency; read in another `base`
    with no rate to hand, the contribution is left out rather than guessed."""
    from stocks.portfolio import plan as plans
    from stocks.userprefs import load_profile

    prefs = accounts.load_prefs(paths.prefs)
    investor = plans.load(prefs)
    profile = load_profile(prefs)
    home = reporting_currency(paths)
    c = investor.contribution
    monthly = plans.per_month(investor)
    if monthly is not None and home != ccy:
        try:
            monthly *= fx.spot(home, ccy)[0]
        except Exception:  # noqa: BLE001 — the page stands without it
            obs.event("projection.fx_missing", source=home, target=ccy)
            monthly = None
    mix = investor.mix
    return ProjectionPlan(
        currency=home,
        monthly=None if monthly is None else round(monthly, 2),
        amount=c.amount if c else None,
        every=c.every if c else None,
        day=c.day if c else None,
        crypto_share=mix.targets.get(plans.CRYPTO, 0.0) / 100 if mix else None,
        years=_HORIZON_YEARS.get(profile["horizon"]) if profile["set"] else None,
    )
