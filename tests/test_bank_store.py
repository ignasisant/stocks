"""Per-account bank state: the pending-authorisation guard and connections.

The pending entries are the security-relevant part — they are what ties a
bank redirect back to the account that started it, across a page load that
destroys the Streamlit session.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from stocks.bank import store


@pytest.fixture
def path(tmp_path):
    return tmp_path / "bank.json"


def aspsp(name="Bank A", country="ES"):
    return {"name": name, "country": country}


def session(session_id="sid-1", *, name="Bank A", valid_until="2026-12-01T00:00:00Z"):
    return {
        "session_id": session_id,
        "aspsp": aspsp(name),
        "access": {"valid_until": valid_until},
        "accounts": [
            {
                "uid": "acc-1",
                "name": "Cuenta corriente",
                "account_id": {"iban": "ES9121000418450200051332"},
                "currency": "EUR",
            }
        ],
    }


# ---------------------------------------------------------------- pending


def test_a_pending_state_round_trips_once(path):
    store.add_pending(path, state="st-1", email="Me@Example.com", aspsp=aspsp())
    entry = store.take_pending(path, "st-1", "me@example.com")
    assert entry["aspsp"]["name"] == "Bank A"
    # Single use: a replayed redirect finds nothing.
    assert store.take_pending(path, "st-1", "me@example.com") is None


def test_another_account_cannot_claim_a_pending_state(path):
    store.add_pending(path, state="st-1", email="me@example.com", aspsp=aspsp())
    assert store.take_pending(path, "st-1", "someone@else.com") is None
    # And the attempt burns it, so the race cannot be retried.
    assert store.take_pending(path, "st-1", "me@example.com") is None


def test_an_unknown_state_is_refused(path):
    assert store.take_pending(path, "never-issued", "me@example.com") is None


def test_an_expired_state_is_refused(path):
    store.add_pending(path, state="st-1", email="me@example.com", aspsp=aspsp(), ttl=-1)
    assert store.take_pending(path, "st-1", "me@example.com") is None


def test_pending_attempts_are_capped(path):
    for i in range(store.MAX_PENDING + 3):
        store.add_pending(path, state=f"st-{i}", email="me@example.com", aspsp=aspsp())
    assert len(store.load(path)["pending"]) <= store.MAX_PENDING


def test_a_corrupt_state_file_reads_as_empty(path):
    path.write_text("{not json")
    assert store.load(path) == store._blank()


# ------------------------------------------------------------ connections


def test_a_connection_keeps_what_the_user_needs_to_recognise_it(path):
    conn = store.add_connection(path, session())
    account = conn["accounts"][0]
    assert conn["session_id"] == "sid-1"
    assert conn["valid_until"] == "2026-12-01T00:00:00Z"
    assert account["uid"] == "acc-1"
    assert account["currency"] == "EUR"
    # The IBAN is masked: enough to identify the account, not to quote it.
    assert account["masked_id"] == "ES91 ···· 1332"
    assert "ES9121000418450200051332" not in path.read_text()


def test_reconnecting_the_same_bank_replaces_the_old_session(path):
    store.add_connection(path, session("sid-1"))
    store.add_connection(path, session("sid-2"))
    assert [c["session_id"] for c in store.connections(path)] == ["sid-2"]


def test_a_different_bank_is_a_second_connection(path):
    store.add_connection(path, session("sid-1", name="Bank A"))
    store.add_connection(path, session("sid-2", name="Bank B"))
    assert len(store.connections(path)) == 2


def test_bare_uid_accounts_are_accepted(path):
    payload = session()
    payload["accounts"] = ["acc-9"]
    assert store.add_connection(path, payload)["accounts"] == [
        {"uid": "acc-9", "name": "", "masked_id": "", "currency": ""}
    ]


def test_remove_connection_reports_whether_it_removed_anything(path):
    store.add_connection(path, session("sid-1"))
    assert store.remove_connection(path, "sid-1") is True
    assert store.remove_connection(path, "sid-1") is False
    assert store.connections(path) == []


@pytest.mark.parametrize(
    "valid_until,gone",
    [
        ((datetime.now(UTC) - timedelta(days=1)).isoformat(), True),
        ((datetime.now(UTC) + timedelta(days=1)).isoformat(), False),
        ("", False),          # unknown: the API is the authority
        ("not-a-date", False),
    ],
)
def test_expired_reads_the_consent_date(valid_until, gone):
    assert store.expired({"valid_until": valid_until}) is gone


def test_expired_accepts_the_api_z_suffix():
    past = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0)
    stamp = past.isoformat().replace("+00:00", "Z")
    assert store.expired({"valid_until": stamp}) is True


def test_record_fetch_stamps_the_account_snapshot(path):
    store.add_connection(path, session())
    balances = [{"balance_type": "CLBD", "balance_amount": {"amount": "12.5"}}]
    store.record_fetch(path, "sid-1", "acc-1", balances=balances)
    snapshot = store.connections(path)[0]["accounts"][0]["snapshot"]
    assert snapshot["balances"] == balances
    assert snapshot["fetched_at"].startswith(str(datetime.now(UTC).year))


def test_record_fetch_ignores_an_account_from_another_session(path):
    store.add_connection(path, session())
    before = json.loads(path.read_text())
    store.record_fetch(path, "other-sid", "acc-1", balances=[])
    assert json.loads(path.read_text()) == before
