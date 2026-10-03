"""Who gets to see the bank feature (stocks.bank.access).

The app has other signed-in Google accounts on it, and the Enable Banking
application runs in restricted mode — the API strips any account that was not
whitelisted in the control panel. So the gate must be an allowlist that fails
closed: a stranger, or a deploy with the secret missing, must get no feature
at all rather than one that authenticates and then returns nothing.
"""

from __future__ import annotations

import pytest

from stocks import accounts
from stocks.bank import access, enablebanking

OWNER = "owner@example.com"
GUEST = "someone@else.com"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """Credentials present, no owner and no allowlist configured."""
    monkeypatch.setattr(enablebanking, "configured", lambda: True)
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setenv("EB_ALLOWED_EMAILS", "")


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(accounts, "configured_owner", lambda: OWNER)


def test_nobody_gets_in_when_the_allowlist_is_empty():
    assert access.available(OWNER) is False


def test_the_owner_is_allowed(owner):
    assert access.available(OWNER) is True


def test_another_signed_in_account_is_not(owner):
    assert access.available(GUEST) is False


def test_the_allowlist_admits_named_accounts_case_insensitively(monkeypatch):
    monkeypatch.setenv("EB_ALLOWED_EMAILS", f" {GUEST.upper()} , third@example.com")
    assert access.available(GUEST) is True


def test_missing_credentials_close_the_feature_for_everyone(owner, monkeypatch):
    monkeypatch.setattr(enablebanking, "configured", lambda: False)
    assert access.available(OWNER) is False


def test_an_anonymous_visitor_is_closed_out(owner):
    """No session means no email, and no email is never on the list."""
    assert access.available("") is False


def test_an_empty_email_never_matches_an_empty_allowlist_entry(monkeypatch):
    monkeypatch.setenv("EB_ALLOWED_EMAILS", ",,  ,")
    assert access.available("") is False


# ------------------------------------------------------------- redirect URL


def test_the_configured_redirect_url_wins(monkeypatch):
    monkeypatch.setenv("EB_REDIRECT_URL", "https://topstocks.app/bank")
    assert access.redirect_url("https://elsewhere.example/") == "https://topstocks.app/bank"


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
    assert access.redirect_url(url, "/bank") == expected
