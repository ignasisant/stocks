"""The Bank page: the consent round trip, end to end through the real script.

AppTest runs the page exactly as Streamlit does, so this covers what unit
tests over the client and the store cannot — that the redirect landing
consumes the code, that a foreign `state` is refused, and that the page's
widgets exist and are wired.

The Enable Banking client is stubbed everywhere; no request is made.
"""

from __future__ import annotations

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stocks.bank import enablebanking, store
from stocks.web import auth, bank_ui

PAGE = "src/stocks/web/app_pages/bank.py"
EMAIL = "me@example.com"

SESSION = {
    "session_id": "sid-1",
    "aspsp": {"name": "Bank A", "country": "ES"},
    "access": {"valid_until": "2026-12-01T00:00:00Z"},
    "accounts": [
        {
            "uid": "acc-1",
            "name": "Cuenta corriente",
            "account_id": {"iban": "ES9121000418450200051332"},
            "currency": "EUR",
        }
    ],
}


@pytest.fixture
def paths(tmp_path):
    return auth.UserPaths(
        root=tmp_path,
        watchlist=tmp_path / "watchlist.yaml",
        db=tmp_path / "portfolio.db",
        last_import=tmp_path / "last_import.json",
        prefs=tmp_path / "prefs.json",
        chat=tmp_path / "chat.json",
        bank=tmp_path / "bank.json",
        action=tmp_path / "daily_action.json",
    )


@pytest.fixture
def page(monkeypatch, paths):
    """The page with a signed-in, allowed account and a stubbed API."""
    monkeypatch.setattr(auth, "require_login", lambda: paths)
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(auth, "current_email", lambda: EMAIL)
    monkeypatch.setattr(bank_ui, "available", lambda: True)
    monkeypatch.setattr(bank_ui, "redirect_url", lambda: "https://app.example/bank")
    monkeypatch.setattr(
        enablebanking,
        "aspsps",
        lambda country="ES", psu_type="personal": [
            {"name": "Bank A", "country": country},
            {"name": "Bank B", "country": country},
        ],
    )
    monkeypatch.setattr(
        enablebanking, "start_auth", lambda **kw: ("https://bank.example/auth", "st-1")
    )
    monkeypatch.setattr(enablebanking, "create_session", lambda code: SESSION)
    st.cache_data.clear()  # the ASPSP list is cached across runs
    return AppTest.from_file(PAGE, default_timeout=30)


def test_the_page_renders_with_nothing_connected(page):
    page.run()
    assert not page.exception
    assert page.title[0].value == "Bank connection"
    assert page.info[0].value == "No bank connected yet."


def test_connecting_stores_a_pending_state_and_offers_the_bank_link(page, paths):
    page.run()
    page.button[0].click().run()
    assert not page.exception
    link = page.get("link_button")[0]
    assert link.url == "https://bank.example/auth"
    pending = store.load(paths.bank)["pending"]["st-1"]
    assert pending["email"] == EMAIL
    assert pending["aspsp"]["name"] == "Bank A"


def test_the_redirect_completes_the_connection(page, paths):
    store.add_pending(
        paths.bank, state="st-1", email=EMAIL, aspsp={"name": "Bank A", "country": "ES"}
    )
    page.query_params["code"] = "the-code"
    page.query_params["state"] = "st-1"
    page.run()
    assert not page.exception
    conn = store.connections(paths.bank)[0]
    assert conn["session_id"] == "sid-1"
    assert conn["accounts"][0]["masked_id"] == "ES91 ···· 1332"
    # The code is single-use: it must not survive in the URL to be replayed.
    assert dict(page.query_params) == {}
    assert store.load(paths.bank)["pending"] == {}


def test_a_state_from_another_account_is_refused(page, paths):
    store.add_pending(
        paths.bank,
        state="st-1",
        email="someone@else.com",
        aspsp={"name": "Bank A", "country": "ES"},
    )
    page.query_params["code"] = "the-code"
    page.query_params["state"] = "st-1"
    page.run()
    assert not page.exception
    assert store.connections(paths.bank) == []
    assert "could not be matched" in page.error[0].value


def test_a_declined_authorisation_says_so_without_connecting(page, paths):
    page.query_params["error"] = "access_denied"
    page.run()
    assert not page.exception
    assert store.connections(paths.bank) == []
    assert "cancelled" in page.warning[0].value


def test_the_feature_stays_dark_when_it_is_not_available(page, monkeypatch):
    monkeypatch.setattr(bank_ui, "available", lambda: False)
    page.run()
    assert not page.exception
    assert page.info[0].value.startswith("Bank connections are not available")
    assert not page.button


def test_a_connected_bank_can_be_disconnected(page, paths, monkeypatch):
    store.add_connection(paths.bank, SESSION)
    closed = []
    monkeypatch.setattr(enablebanking, "delete_session", closed.append)
    page.run()
    [b for b in page.button if b.key == "disconnect_sid-1"][0].click().run()
    assert not page.exception
    assert closed == ["sid-1"]
    assert store.connections(paths.bank) == []


def test_refresh_stores_the_balances_it_reads(page, paths, monkeypatch):
    store.add_connection(paths.bank, SESSION)
    balances = [{"balance_type": "CLBD", "balance_amount": {"amount": "1234.50",
                                                           "currency": "EUR"}}]
    monkeypatch.setattr(enablebanking, "balances", lambda uid: balances)
    page.run()
    [b for b in page.button if b.key == "refresh_sid-1"][0].click().run()
    assert not page.exception
    snapshot = store.connections(paths.bank)[0]["accounts"][0]["snapshot"]
    assert snapshot["balances"] == balances
    assert "**1,234.50 EUR**" in [m.value for m in page.markdown]


def test_a_spent_fetch_budget_is_explained_not_reported_as_a_failure(
    page, paths, monkeypatch
):
    store.add_connection(paths.bank, SESSION)

    def throttled(_uid):
        raise enablebanking.RateLimited(429, "ASPSP_RATE_LIMIT_EXCEEDED", "slow down")

    monkeypatch.setattr(enablebanking, "balances", throttled)
    page.run()
    [b for b in page.button if b.key == "refresh_sid-1"][0].click().run()
    assert not page.exception
    assert not page.error
    assert "only a few balance reads per day" in page.warning[0].value
    # The consent is untouched: nothing to reconnect.
    assert not store.expired(store.connections(paths.bank)[0])


def test_a_dead_consent_is_marked_instead_of_erroring(page, paths, monkeypatch):
    store.add_connection(paths.bank, SESSION)

    def revoked(_uid):
        raise enablebanking.ConsentError(401, "SESSION_EXPIRED", "gone")

    monkeypatch.setattr(enablebanking, "balances", revoked)
    page.run()
    [b for b in page.button if b.key == "refresh_sid-1"][0].click().run()
    assert not page.exception
    assert store.expired(store.connections(paths.bank)[0])
    assert "ended this consent" in page.warning[0].value
