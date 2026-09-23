"""A tiny TTL memo — what `st.cache_data` does, without Streamlit.

The page loaders in `stocks.web.portfolio_data` are all wrapped in
`@st.cache_data`, and for good reason: a ledger replay plus a price burst for
a whole book is seconds of work and a pile of Yahoo requests. That decorator
needs a script run to key against, so it cannot cross into an ASGI worker.

This is the replacement, kept deliberately small: one dict, one lock, a TTL
and a cap. It is process-local, so a redeploy or a second container starts
cold, which is exactly the guarantee `st.cache_data` gives too.

Keying follows the same convention as the pages — `(db path, ledger mtime,
base currency)` — so an import invalidates a book's entries the moment the
file changes rather than when a timer runs out.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])


def ttl_cache(ttl_s: float, max_entries: int = 32) -> Callable[[F], F]:
    """Memoize a function on its arguments for `ttl_s` seconds.

    Arguments must be hashable — pass paths as strings and ticker lists as
    tuples, which is what the callers here do anyway.

    Eviction is oldest-inserted-first once `max_entries` is reached. A book's
    worth of cached frames is a few MB and this runs beside Streamlit in one
    container, so the cap matters more than the hit rate.
    """

    def decorate(fn: F) -> F:
        store: dict[tuple, tuple[float, Any]] = {}
        lock = threading.Lock()

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                hit = store.get(key)
                if hit is not None and now - hit[0] < ttl_s:
                    return hit[1]
            # Computed outside the lock: these calls go to the network, and
            # holding the lock across one would serialize every reader of
            # every account behind the slowest download.
            value = fn(*args, **kwargs)
            with lock:
                store[key] = (now, value)
                while len(store) > max_entries:
                    store.pop(next(iter(store)))
            return value

        # `cache_clear` hangs off the wrapper the way functools' caches do it,
        # so a test (or a forced refresh) can drop the entries without reaching
        # into this module. Assigned through an untyped alias because a
        # signature-preserving decorator has nowhere to declare the extra
        # attribute, and `cast` is what hands the caller back its own type.
        clearable: Any = wrapper
        clearable.cache_clear = store.clear
        return cast(F, wrapper)

    return decorate
