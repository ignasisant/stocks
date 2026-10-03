"""The app's HTTP API over the domain packages.

Everything the pages compute — positions, performance, the watchlist, live
quotes — comes out of `stocks.portfolio`, `stocks.analysis` and `stocks.data`.
This package puts an HTTP surface on that same code, for the React shell
(`frontend/app`) and for anything else that reads a book: a cron job, the
Telegram bot, a phone.

Mounted at `/api` inside the existing server (`stocks.web.server`), so it
deploys with the app and answers on the same hostname.
"""

from __future__ import annotations

from stocks.api.app import MOUNT_PATH, app

__all__ = ["MOUNT_PATH", "app"]
