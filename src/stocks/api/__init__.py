"""The app's read-only HTTP API over the domain packages.

Everything the pages compute — positions, performance, the watchlist, live
quotes — comes out of `stocks.portfolio`, `stocks.analysis` and `stocks.data`,
none of which import Streamlit. This package puts an HTTP surface on that
same code so something other than a browser session can read a book: a cron
job, the Telegram bot, a phone, or a front end that is not Streamlit.

It is deliberately read-only. Every write the app performs (an import, a
preference, a watchlist edit) still goes through the pages, so nothing here
can put the ledger in a state the UI did not produce.

Mounted at `/api` inside the existing server (`stocks.web.server`), so it
deploys with the app and answers on the same hostname. `stocks.web` does not
import this package and never will: the dependency points one way, and
deleting this directory leaves the app exactly as it was.
"""

from __future__ import annotations

from stocks.api.app import MOUNT_PATH, app

__all__ = ["MOUNT_PATH", "app"]
