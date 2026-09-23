"""Turning pandas' idea of "no value" into JSON's.

pandas says "no price" with NaN and "no span" with inf; JSON can express
neither, and both would otherwise serialize as literals no parser accepts.
Everything unrepresentable becomes null — which is also what the schemas
promise: a number the app could not compute is absent, not zero.
"""

from __future__ import annotations

import math


def num(value) -> float | None:
    """A JSON-safe float, or None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def scalar(value) -> float | str | None:
    """`num`, but a label passes through.

    A few KPIs are strings (a sector, a currency) rather than figures, and
    coercing those to a float would drop them.
    """
    return value if isinstance(value, str) else num(value)
