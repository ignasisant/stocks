"""Reading the signed-in account out of the browser's own session cookie.

A shared bearer token is fine for a cron job and useless in a browser: it names
nobody, so the caller has to say which account it wants, which means every token
holder can read every account. A page rendered for a person needs the opposite —
the server decides whose book this is, and the client cannot ask for another.

The cookie itself is `stocks.session`, which the app mints in its own OIDC flow
and which knows nothing about any web framework. This module is the seam that
used to hold the Streamlit-format decoder; it now only re-exports, so that the
API's callers keep one import and the Streamlit-free contract lives in one
place. It goes away once nothing imports it.
"""

from __future__ import annotations

from stocks.session import claims, signed_in_email

__all__ = ["claims", "signed_in_email"]
