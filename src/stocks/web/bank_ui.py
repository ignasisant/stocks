"""Availability rules for the bank connection feature, for the Streamlit app.

Kept out of the page module so app.py can decide whether to show the nav entry
without importing the page (which would run it).

The rules themselves are `stocks.bank.access`, shared with the API: the React
shell asks the same questions of the same secrets, and an allowlist that said
two different things on two front ends would be an allowlist with a hole in it.
What stays here is the pair of answers only a Streamlit run can give — who is
signed in, and which URL this run was served on.
"""

from __future__ import annotations

import streamlit as st  # noqa: F401  (tests patch st.secrets / st.context through it)

from stocks.bank import access
from stocks.web import auth


def available() -> bool:
    """Whether this session may see the bank feature at all."""
    if not auth.is_logged_in():
        return False
    return access.available(auth.current_email())


def redirect_url() -> str:
    """Where the bank sends this page's round trip back to.

    `/bank`, this page's own path — the shell's flow asks for `/next/bank`.
    Only one of the two can be registered, so a deploy that sets
    [enable_banking] redirect_url explicitly settles it for both.
    """
    return access.redirect_url(str(getattr(st.context, "url", "") or ""), "/bank")
