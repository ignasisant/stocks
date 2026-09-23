"""Making the shared guest book exist, at boot and nowhere else.

An anonymous visitor reads one directory — `accounts.GUEST_DIR` — holding a
starter watchlist and the demo ledger. The Streamlit app wrote both on the
first anonymous page view, from inside `auth.resolve_user()`. Doing it here
instead, once, from the application's lifespan, is the strongest form of the
read-only rule this directory lives by:

**no request writes the guest directory, because the code that writes it has no
caller-facing entry point at all.**

That is a stronger claim than any check on who is asking, and it is the one
worth having — the bug this design is answering (`web.auth.push_recent_search`)
was a write nobody had thought to put a check in front of.
"""

from __future__ import annotations

from stocks import accounts, obs
from stocks.portfolio import demo


def provision() -> None:
    """Create the guest dir, its starter watchlist and its demo book.

    Both writes are idempotent. `restore_account` pulls the bucket first, so an
    ephemeral redeploy starts from the persisted copies rather than a blank
    dir, and only writes the starter watchlist when there is none. `demo.seed`
    is a no-op on a ledger that already holds anything, so a restart cannot
    stack a second copy of an invented cost basis.

    Never raises. A bucket outage costs a visitor the demo book — the empty
    state the pages already draw — and must not cost the deployment its boot.
    """
    paths = accounts.guest_paths()
    try:
        accounts.restore_account(paths, seed=True)
        seeded = demo.seed(paths.db)
    except Exception as exc:  # noqa: BLE001 — a guest book is not worth a boot
        obs.warn(
            "api.guest_unprovisioned",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return
    if seeded:
        obs.event("guest.provisioned", rows=len(seeded))
