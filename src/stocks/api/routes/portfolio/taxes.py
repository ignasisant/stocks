"""The realized result and its tax, on screen and as the year's CSV."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from stocks import loaders, obs
from stocks.api.deps import Account, reporting_currency
from stocks.cache import ttl_cache
from stocks.jsonsafe import num as _num
from stocks.portfolio import dividends, tax
from stocks.portfolio.tax import month_range
from stocks.portfolio.tax import prefs as tax_prefs
from stocks.schemas import TaxAllYears, TaxFlag, TaxKpi, TaxNote, TaxReport, TaxSale
from stocks.schemas import TaxPeriod as TaxPeriodOut

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/tax", response_model=TaxReport, summary="Realized result and tax")
def tax_(account: Account) -> TaxReport:
    """The book's realized result under the account's own jurisdiction.

    There is no `?base=` here, and that is deliberate: the ledger is replayed
    *at* the jurisdiction's currency and under its own share-matching rule
    rather than converted afterwards. A US filer's basis is USD at each trade
    date — two rates, not one — and a UK replay pools shares, so its parcels
    are not the FIFO ones the rest of the API reports.

    `resolved` says how the jurisdiction was arrived at. A caller that gets
    `unmodelled` is being shown somebody else's rules and has to say so.
    """
    prefs = tax_prefs.load(account.prefs)
    code, how = tax_prefs.resolve(prefs)
    jurisdiction = tax.get(code)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    txs, _, realized = loaders.ledger_state(
        db, mtime, jurisdiction.currency, jurisdiction.matching
    )
    # Under the replay's labels, not the ledger's: the exemption is applied by
    # testing a sale's ticker against this set (see tax.labels).
    settings = tax_prefs.with_funds(tax_prefs.settings(prefs), tax.labels(txs))
    report = TaxReport(
        jurisdiction=code,
        resolved=how,
        currency=jurisdiction.currency,
        matching=jurisdiction.matching,
        funds_classified=bool(settings.fund_tickers),
    )
    # Where dividends share the base with the gains (Spain's base del ahorro),
    # a year that only collected them is a taxable year too.
    paid = (
        dividends.payments(txs, base=jurisdiction.currency)
        if jurisdiction.dividends_in_base
        else []
    )
    if not realized and not paid:
        return report

    # Normalized inside, as the replay is: a RealizedSale carries the replay's
    # label and acquisition dates, and the raw ledger has neither, so a
    # repurchase under the other spelling — or one that arrived as an opening
    # balance — is invisible to every repurchase rule. See tax.buy_dates.
    buy_dates = tax.buy_dates(txs)

    def period(value, year: int | None = None) -> TaxPeriodOut:
        return TaxPeriodOut(
            period=value.period,
            realized_gain=_num(value.realized_gain) or 0.0,
            realized_loss=_num(value.realized_loss) or 0.0,
            disallowed_loss=_num(value.disallowed_loss) or 0.0,
            recovered_loss=_num(value.recovered_loss) or 0.0,
            deductible_loss=_num(value.deductible_loss) or 0.0,
            dividends=_num(value.dividends) or 0.0,
            net_taxable=_num(value.net_taxable) or 0.0,
            estimated_tax=_num(value.estimated_tax) or 0.0,
            carryforward_loss=_num(value.carryforward_loss) or 0.0,
            sales=len(value.sales),
            kpis=[
                TaxKpi(name=k.key, value=_num(k.value) or 0.0, help=k.help_key)
                for k in value.kpis()
            ],
            # Years only. A month is a breakdown of when the result was booked,
            # and every note a jurisdiction writes is about the year it nets —
            # repeating "your allowance used" under each of twelve months
            # would read as twelve allowances.
            year_label=jurisdiction.year_label(year) if year is not None else "",
            notes=[
                TaxNote(key=n.key, kwargs={k: str(v) for k, v in n.kwargs.items()})
                for n in value.notes()
            ]
            if year is not None
            else [],
        )

    # Tax years, not calendar years — the UK's open on 6 April.
    dates = [s.sell_date for s in realized] + [p.date for p in paid]
    years = sorted({jurisdiction.tax_year_of(day) for day in dates})
    months = sorted({day[:7] for day in dates})
    periods = [
        jurisdiction.fiscal_year(realized, year, buy_dates, settings, paid)
        for year in years
    ]
    report.years = [
        period(value, year) for value, year in zip(periods, years, strict=True)
    ]
    # The years added up, which is a history and not a period: `tax.total_of`
    # sums each year's own figures rather than replaying the ledger as one long
    # one, because allowances reset and brackets restart — a decade run up a
    # single progressive scale would invent a tax nobody owes. One year is
    # already all of them, so it gets no aggregate.
    if len(periods) > 1:
        total = tax.total_of(periods)
        report.all_years = TaxAllYears(
            years=list(total.years),
            realized_gain=_num(total.realized_gain) or 0.0,
            realized_loss=_num(total.realized_loss) or 0.0,
            disallowed_loss=_num(total.disallowed_loss) or 0.0,
            recovered_loss=_num(total.recovered_loss) or 0.0,
            deductible_loss=_num(total.deductible_loss) or 0.0,
            dividends=_num(total.dividends) or 0.0,
            sales=len(total.sales),
            kpis=[
                TaxKpi(name=k.key, value=_num(k.value) or 0.0, help=k.help_key)
                for k in total.kpis()
            ],
        )
    # Quiet months included (month_range), so a client charting this does not
    # have to invent the gaps between two sales.
    report.months = [
        period(jurisdiction.fiscal_period(realized, month, buy_dates, settings, paid))
        for month in month_range(months[0], months[-1])
    ]
    report.sales = [
        TaxSale(
            ticker=sale.ticker,
            buy_date=sale.buy_date,
            sell_date=sale.sell_date,
            quantity=sale.quantity,
            cost=sale.cost,
            proceeds=sale.proceeds,
            gain=sale.gain,
            matched=sale.matched,
            # Only where the rate turns on it: a column that says "long" on
            # every row of a Spanish report is a distinction the law does not
            # make.
            term=(
                (
                    "long"
                    if jurisdiction.is_long_term(sale.buy_date, sale.sell_date)
                    else "short"
                )
                if jurisdiction.splits_holding_period
                else None
            ),
        )
        for sale in sorted(realized, key=lambda s: s.sell_date)
    ]
    report.flags = _reporting_flags(account, jurisdiction, settings)
    return report


@ttl_cache(3600.0, max_entries=8)
def _tax_csv(db: str, mtime: float, code: str, year: int | None) -> bytes:
    """The tax file, memoized on (db, ledger mtime, jurisdiction, year).

    The jurisdiction is in the key because it picks the replay — currency and
    share-matching both — and a residence changed on the Profile page has to
    hand back a different file at once.
    """
    from stocks.web.exports import tax_csv

    jurisdiction = tax.get(code)
    txs, _, realized = loaders.ledger_state(
        db, mtime, jurisdiction.currency, jurisdiction.matching
    )
    return tax_csv(
        realized,
        txs,
        currency=jurisdiction.currency,
        tax_year_of=jurisdiction.tax_year_of,
        year=year,
    )


@router.get(
    "/tax.csv",
    response_class=Response,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "The taxable rows: one per lot sold, one per dividend.",
        }
    },
    summary="The realized result as a file",
)
def tax_file(
    account: Account,
    year: Annotated[
        int | None,
        Query(
            description=(
                "One tax year, by the jurisdiction's own calendar; every year "
                "when omitted."
            )
        ),
    ] = None,
) -> Response:
    """The Realized & tax tab as a file for the return.

    One row per matched lot sold — acquisition and sale dates, quantity, cost,
    proceeds, gain — and one per dividend, gross and withheld, all in the
    jurisdiction's currency at each date's own rate. The rows follow `/tax`:
    the same replay, the same currency, the same share-matching, so the file
    reconciles against the tab line by line. Dividends are listed whether or
    not the jurisdiction nets them with the gains; a return asks for them
    either way.

    A year with nothing taxable is a 404 rather than a zero-byte attachment,
    like the ledger export.
    """
    prefs = tax_prefs.load(account.prefs)
    code, _ = tax_prefs.resolve(prefs)
    db = str(account.db)
    body = _tax_csv(db, loaders.db_mtime(db), code, year)
    if not body:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this book has nothing taxable to export"
            + (f" in {year}" if year is not None else ""),
        )
    which = str(year) if year is not None else "all"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="aguait-tax-{code.lower()}-{which}-'
                f'{date.today():%Y-%m-%d}.csv"'
            )
        },
    )


def _reporting_flags(account, jurisdiction, settings) -> list[TaxFlag]:
    """Foreign-asset thresholds (Modelo 720, FBAR, Form 8938…) against the book.

    The open book marked to market off the shared positions table — a name
    with no price counts at its cost rather than vanishing from a total whose
    whole point is "how much is held abroad" — then converted to the
    jurisdiction's currency at today's spot. That is a threshold check and not
    a basis, so one live rate is the right tool (FBAR's year-end Treasury rate
    is not worth a second replay for a line that only says "may apply").

    Best effort both ways: a price pass or a rate that failed leaves no line
    at all, never a threshold measured against a total that is missing half
    the book. Every flag the jurisdiction returns is served, crossed or not —
    "under the line" is information too, and it is what the page prints.
    """
    from stocks.data.crypto import is_crypto

    ccy = reporting_currency(account, None)
    db = str(account.db)
    with obs.swallow("api.tax_flags", jurisdiction=jurisdiction.code):
        table = loaders.positions_table(db, loaders.db_mtime(db), ccy)
        if not table.empty:
            # Modelo 720 covers securities and accounts abroad; crypto is the
            # separate Modelo 721, so coins never count toward the 720 total.
            table = table[[not is_crypto(str(t)) for t in table.index]]
        held = (
            float(table["value"].fillna(table["cost"]).sum()) if not table.empty else 0.0
        )
        rate = (
            1.0
            if ccy.upper() == jurisdiction.currency.upper()
            else loaders.spot_rates((ccy,), jurisdiction.currency).get(ccy)
        )
        if not rate:
            return []
        return [
            TaxFlag(
                name=flag.name,
                reportable=bool(flag.reportable),
                total_value=float(flag.total_value),
                threshold=float(flag.threshold),
            )
            for flag in jurisdiction.reporting_flags(held * rate, settings)
        ]
    return []
