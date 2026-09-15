"""Who gets to see the bank feature.

The app has other signed-in Google accounts on it, and the Enable Banking
application runs in restricted mode — the API strips any account that was not
whitelisted in the control panel. So the gate must be an allowlist that fails
closed: a stranger, or a deploy with the secret missing, must get no feature
at all rather than one that authenticates and then returns nothing.
"""

from __future__ import annotations

import pytest

from stocks.bank import enablebanking
from stocks.web import auth, bank_ui

OWNER = "owner@example.com"
GUEST = "someone@else.com"


@pytest.fixture
def signed_in(monkeypatch):
    """Credentials present, an authenticated session, no secrets configured."""
    monkeypatch.setattr(enablebanking, "configured", lambda: True)
    monkeypatch.setattr(auth, "is_logged_in", lambda: True)
    monkeypatch.setattr(bank_ui.st, "secrets", {})
    monkeypatch.setenv("EB_ALLOWED_EMAILS", "")

    def _as(email: str):
        monkeypatch.setattr(auth, "current_email", lambda: email)

    return _as


def test_nobody_gets_in_when_the_allowlist_is_empty(signed_in):
    signed_in(OWNER)
    assert bank_ui.available() is False


def test_the_owner_is_allowed(signed_in, monkeypatch):
    monkeypatch.setattr(bank_ui.st, "secrets", {"app": {"owner_email": OWNER}})
    signed_in(OWNER)
    assert bank_ui.available() is True


def test_another_signed_in_account_is_not(signed_in, monkeypatch):
    monkeypatch.setattr(bank_ui.st, "secrets", {"app": {"owner_email": OWNER}})
    signed_in(GUEST)
    assert bank_ui.available() is False


def test_the_allowlist_admits_named_accounts_case_insensitively(signed_in, monkeypatch):
    monkeypatch.setenv("EB_ALLOWED_EMAILS", f" {GUEST.upper()} , third@example.com")
    signed_in(GUEST)
    assert bank_ui.available() is True


def test_missing_credentials_close_the_feature_for_everyone(signed_in, monkeypatch):
    monkeypatch.setattr(bank_ui.st, "secrets", {"app": {"owner_email": OWNER}})
    monkeypatch.setattr(enablebanking, "configured", lambda: False)
    signed_in(OWNER)
    assert bank_ui.available() is False


def test_an_anonymous_visitor_is_closed_out(signed_in, monkeypatch):
    monkeypatch.setattr(bank_ui.st, "secrets", {"app": {"owner_email": OWNER}})
    monkeypatch.setattr(auth, "is_logged_in", lambda: False)
    signed_in(OWNER)
    assert bank_ui.available() is False


def test_an_empty_email_never_matches_an_empty_allowlist_entry(signed_in, monkeypatch):
    monkeypatch.setenv("EB_ALLOWED_EMAILS", ",,  ,")
    signed_in("")
    assert bank_ui.available() is False


# ------------------------------------------------------------- redirect URL


def test_the_configured_redirect_url_wins(monkeypatch):
    monkeypatch.setenv("EB_REDIRECT_URL", "https://topstocks.app/bank")
    assert bank_ui.redirect_url() == "https://topstocks.app/bank"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://topstocks.app/bank?code=x", "https://topstocks.app/bank"),
        # Derived from the origin, so any page it is called from gives /bank.
        ("https://topstocks.app/portfolio", "https://topstocks.app/bank"),
        # http is refused by the API at registration time, so there is no
        # redirect URL to offer from a plain local dev server.
        ("http://localhost:8501/", ""),
        ("", ""),
        ("not-a-url", ""),
    ],
)
def test_the_redirect_url_is_derived_from_the_served_url(monkeypatch, url, expected):
    monkeypatch.setenv("EB_REDIRECT_URL", "")

    class Context:
        pass

    ctx = Context()
    ctx.url = url
    monkeypatch.setattr(bank_ui.st, "context", ctx)
    assert bank_ui.redirect_url() == expected
