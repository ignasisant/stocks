"""Who may use the bank connection, and where the bank sends them back.

Split out of `web/bank_ui.py` when the React app took over the flow: the rules
are the same on both front ends, and the API cannot import Streamlit to read
them. `bank_ui` now wraps this with the Streamlit session's own answers to
"who is signed in" and "which URL is this being served on".

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
  editing this module, not by leaving a secret unset.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from stocks import accounts
from stocks.bank import enablebanking
from stocks.secrets_env import secret

#: Where the React shell answers, which is where the bank now redirects to.
#: The Streamlit page keeps its own `/bank` (it passes its path explicitly):
#: only one of the two can be the registered redirect URL, and the flow the
#: app actually offers is the one in the shell.
APP_PATH = "/next/bank"


def allowed_emails() -> set[str]:
    raw = secret("EB_ALLOWED_EMAILS", "enable_banking", "allowed_emails")
    owner = accounts.configured_owner() or ""
    return {e.strip().lower() for e in (raw.split(",") + [owner]) if e.strip()}


def available(email: str) -> bool:
    """Whether this account may see the bank feature at all.

    Closed by default: an account has to be named in the allowlist (or be the
    owner). Anything else — misconfigured secrets, a stranger signing in with
    Google, a copied deploy — gets an app with no bank feature in it.
    """
    if not enablebanking.configured():
        return False
    address = email.strip().lower()
    return bool(address) and address in allowed_emails()


def redirect_url(served_url: str, path: str = APP_PATH) -> str:
    """Where the bank sends the user back — must match a redirect URL
    registered in the Enable Banking control panel, exactly.

    Configured explicitly when set; otherwise derived from the URL this run
    was served on, which is right for both localhost and the deploy.

    Origin + `path`, not "current URL + path": deriving from the path would
    quietly produce /portfolio/bank when called from anywhere else.

    https only, which is what makes a local dev server unable to start a
    consent: Enable Banking refuses to register an http redirect URL
    ("unsupported scheme"), so deriving one here would only trade a clear
    "not available" for a failed API call halfway through the flow.
    """
    configured = secret("EB_REDIRECT_URL", "enable_banking", "redirect_url")
    if configured:
        return configured
    parts = urlsplit(str(served_url or ""))
    if parts.scheme != "https" or not parts.netloc:
        return ""
    return f"https://{parts.netloc}{path}"
