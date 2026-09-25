"""Re-export of `stocks.frames`, kept so web call sites do not move.

The helpers moved out of `web/` when the price-history windowing did
(`analysis.history`): reading a price frame's index is pandas typing, not a UI
concern, and the analysis package cannot import from the web layer.
"""

from __future__ import annotations

from stocks.frames import dates, sessions, weekdays

__all__ = ["dates", "sessions", "weekdays"]
