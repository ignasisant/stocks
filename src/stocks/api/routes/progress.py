"""What this account's slow load is doing right now (`stocks.progress`).

Polled by the corner banner, about once a second, only while a request has
been out longer than its threshold. Cheap on purpose: a dict read, no
download, nothing that could itself be the slow request it reports on.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from stocks import progress as registry
from stocks.api.deps import Account
from stocks.api.schemas import Progress, ProgressJob

router = APIRouter(tags=["progress"])


@router.get("/progress", response_model=Progress, summary="Slow load in progress")
def progress(account: Account, response: Response) -> Progress:
    """The step this account's price download is on, or `job: null` when idle.

    `done`/`total` count names where the step can count them (the refresh,
    twenty names a request); a bulk download that cannot reports `total`
    only, and `expected_s` — how long the same step took last time on this
    book — stands in for the count.
    """
    response.headers["Cache-Control"] = "no-store"
    snap = registry.snapshot(str(account.db))
    return Progress(job=ProgressJob(**snap) if snap else None)
