"""The book: positions, totals, the ledger itself, and how it has done."""

from __future__ import annotations

from fastapi import APIRouter

from stocks.api.routes.portfolio import (
    forecast,
    holdings,
    income,
    ledger,
    returns,
    risk_report,
    taxes,
)
from stocks.api.routes.portfolio.forecast import projection
from stocks.api.routes.portfolio.holdings import (
    _cash_in,
    _ledger_csv,
    positions,
    summary,
    transactions,
)
from stocks.api.routes.portfolio.income import dividends_, dividends_unbooked, fees_
from stocks.api.routes.portfolio.ledger import (
    EditOps,
    health,
    list_changes,
    plan_change,
)
from stocks.api.routes.portfolio.returns import attribution, history, monthly, performance
from stocks.api.routes.portfolio.risk_report import risk
from stocks.api.routes.portfolio.taxes import tax_

__all__ = [
    "_cash_in",
    "_ledger_csv",
    "attribution",
    "dividends_",
    "dividends_unbooked",
    "EditOps",
    "fees_",
    "health",
    "history",
    "list_changes",
    "monthly",
    "performance",
    "plan_change",
    "positions",
    "projection",
    "risk",
    "summary",
    "tax_",
    "transactions",
]

# Each leaf carries the "/portfolio" prefix itself: an included router is not
# flattened, and the guest gate reads the innermost route's path, which must
# still say "/portfolio/...".
router = APIRouter()
for _leaf in (holdings, returns, income, taxes, forecast, risk_report, ledger):
    router.include_router(_leaf.router)
