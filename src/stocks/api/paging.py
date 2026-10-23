"""The one way a list endpoint pages: `limit` and `offset`.

`/transactions` was the first list to page and chose limit/offset; every other
list is a bounded "top N" with `limit` alone. So the convention is the one
already shipped: `limit` (1..max, per-route default) and `offset` (>= 0), and
a paged body carries `total` so a client knows when to stop.
"""

from typing import Annotated, TypeVar

from fastapi import Depends, Query

# No `from __future__ import annotations`: the closure's annotations must be
# real objects for FastAPI to read their bounds.
T = TypeVar("T")


class Page:
    def __init__(self, limit: int, offset: int) -> None:
        self.limit = limit
        self.offset = offset

    def apply(self, rows: list[T]) -> list[T]:
        return rows[self.offset : self.offset + self.limit]


def page(default: int = 50, maximum: int = 500):
    """A dependency for `limit`/`offset` with this route's bounds."""

    def read(
        limit: Annotated[int, Query(ge=1, le=maximum)] = default,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Page:
        return Page(limit, offset)

    return Depends(read)
