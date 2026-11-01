"""`POST /v1/schedule/tick`: the scheduled runs, on this request's CPU.

Cloud Scheduler calls it every quarter of an hour with the API token
(infra/cron.tf); `notify.schedule.tick` runs whatever came due since. Here
and not in a cron job because a run writes the account's chat.json, which
this instance owns (`storage`: single container).
"""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, Depends

from stocks.api import cache, security

router = APIRouter(include_in_schema=False)
_running = threading.Lock()


@router.post("/schedule/tick", name="schedule_tick")
def tick_now(
    who: Annotated[security.Caller, Depends(security.caller)],
) -> dict[str, object]:
    """The API token only, and one tick at a time: a second call while one
    runs answers `busy` at once rather than sending the same runs twice."""
    from stocks.notify import schedule

    if who.kind != "token":
        security.refuse()
    if not _running.acquire(blocking=False):
        return {"busy": True}
    token = cache.SYNC.set(True)
    try:
        return schedule.tick()
    finally:
        cache.SYNC.reset(token)
        _running.release()
