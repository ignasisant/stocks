"""Availability rules for the bank connection feature.

Kept out of the page module so app.py can decide whether to show the nav entry
without importing the page (which would run it).

Two gates, both deliberate:

* credentials — no application id / private key, no feature. That alone keeps
  it dark on any deploy that has not been set up.
* allowlist — the application runs in Enable Banking's *restricted* production
  mode: the API returns only the accounts that were whitelisted in the control
  panel and strips every other one from the response. Another signed-in user
  reaching this feature could therefore never connect their own bank — they
  would authenticate at their bank and get an empty account list back. So the
  gate is an allowlist of accounts, [enable_banking] allowed_emails plus the
  owner, and it fails CLOSED: an empty list means nobody, never everybody.
  Unrestricted production (a signed contract, other people's banks, a monthly
  invoice per account accessed) is what would widen this — deliberately, by
  editing this function, not by leaving a secret unset.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import streamlit as st

from stocks.bank import enablebanking
from stocks.secrets_env import secret
from stocks.web import auth


def _allowed_emails() -> set[str]:
    raw = secret("EB_ALLOWED_EMAILS", "enable_banking", "allowed_emails")
    owner = str(st.secrets.get("app", {}).get("owner_email", "") or "")
    return {e.strip().lower() for e in (raw.split(",") + [owner]) if e.strip()}


def available() -> bool:
    """Whether this session may see the bank feature at all.

    Closed by default: an account has to be named in the allowlist (or be the
    owner). Anything else — misconfigured secrets, a stranger signing in with
    Google, a copied deploy — gets an app with no bank feature in it.
    """
    if not enablebanking.configured() or not auth.is_logged_in():
        return False
    email = auth.current_email().lower()
    return bool(email) and email in _allowed_emails()


def redirect_url() -> str:
    """Where the bank sends the user back — must match a redirect URL
    registered in the Enable Banking control panel, exactly.

    Configured explicitly when set; otherwise derived from the URL this run
    was served on, which is right for both localhost and the deploy.
    """
    configured = secret("EB_REDIRECT_URL", "enable_banking", "redirect_url")
    if configured:
        return configured
    # Origin + /bank, not "current URL + /bank": the page this runs on is
    # already /bank today, but deriving from the path would quietly produce
    # /portfolio/bank if it were ever called from anywhere else.
    #
    # https only, which is what makes a local dev server unable to start a
    # consent: Enable Banking refuses to register an http redirect URL
    # ("unsupported scheme"), so deriving one here would only trade a clear
    # "not available" for a failed API call halfway through the flow.
    parts = urlsplit(str(getattr(st.context, "url", "") or ""))
    if parts.scheme != "https" or not parts.netloc:
        return ""
    return f"https://{parts.netloc}/bank"
