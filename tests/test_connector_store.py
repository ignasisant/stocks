"""The connector's grant ledger: hashes on disk, one grant per "Allow".

The HTTP side of the same rules is in `test_connector_oauth.py`; here is what
the ledger guarantees on its own — what it writes, what survives a restart,
what deletion and pruning take with them, and who may revoke what.
"""

from __future__ import annotations

import json

import pytest

from stocks import accounts
from stocks.connector import store

EMAIL = "Holder@Example.com"


@pytest.fixture
def ledger() -> store.Ledger:
    return store.ledger()


def grant(ledger: store.Ledger, email: str = EMAIL) -> store.Issued:
    return ledger.issue(
        email=email, client_id="c1", client_name="Claude", client_kind="cimd",
        redirect_host="claude.ai",
    )


def test_tokens_are_kept_only_as_hashes(ledger):
    issued = grant(ledger)
    on_disk = ledger.grants_file.read_text()
    assert issued.access not in on_disk
    assert issued.refresh not in on_disk
    assert store.digest(issued.access) in on_disk


def test_a_restart_reads_the_same_grants(ledger):
    issued = grant(ledger)
    again = store.Ledger(store.DIR)
    held = again.holder(issued.access)
    assert held is not None
    assert held.email == EMAIL.lower()


def test_an_unreadable_file_starts_fresh(ledger):
    store.DIR.mkdir(parents=True, exist_ok=True)
    ledger.grants_file.write_text("{not json")
    assert store.Ledger(store.DIR).grants_for(EMAIL) == []


def test_only_our_prefixes_are_looked_up(ledger):
    issued = grant(ledger)
    assert ledger.holder(issued.refresh) is None
    assert ledger.refresh_holder(issued.access) is None
    assert ledger.holder("s3cret-api-token") is None


def test_an_expired_access_token_holds_nothing(ledger, monkeypatch):
    issued = grant(ledger)
    later = store._now() + store.ACCESS_TTL + 1
    monkeypatch.setattr(store, "_now", lambda: later)
    assert ledger.holder(issued.access) is None


def test_rotation_never_outlives_the_grant(ledger, monkeypatch):
    """Sliding by a month at a time, still over at half a year."""
    start = store._now()
    clock = [start]
    monkeypatch.setattr(store, "_now", lambda: clock[0])
    refresh = grant(ledger).refresh
    while True:
        clock[0] += store.REFRESH_TTL - 86400
        rotated = ledger.rotate(refresh)
        if rotated is None:
            break
        assert ledger._grants[rotated.grant]["refresh"]["expires"] <= (
            start + store.GRANT_MAX_AGE)
        refresh = rotated.refresh
    assert clock[0] > start + store.GRANT_MAX_AGE - store.REFRESH_TTL


def test_a_spent_refresh_token_ends_the_grant(ledger):
    issued = grant(ledger)
    rotated = ledger.rotate(issued.refresh)
    assert rotated is not None
    assert ledger.refresh_holder(issued.refresh) is None
    assert ledger.holder(rotated.access) is None
    assert ledger.grants_for(EMAIL) == []


def test_only_the_owner_may_revoke_a_grant(ledger):
    gid = grant(ledger).grant
    assert ledger.revoke(gid, email="someone-else@example.com") is False
    assert [g["id"] for g in ledger.grants_for(EMAIL)] == [gid]
    assert ledger.revoke(gid, email=EMAIL) is True
    assert ledger.grants_for(EMAIL) == []


def test_the_profile_list_carries_no_secrets(ledger):
    grant(ledger)
    (row,) = ledger.grants_for(EMAIL)
    assert set(row) == {"id", "client_name", "client_kind", "redirect_host",
                        "created", "used", "expires", "write"}
    assert row["write"] is False


def test_deleting_an_account_ends_its_connections_only(ledger, tmp_path, monkeypatch):
    users = tmp_path / "users"
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    real = accounts.paths_for
    monkeypatch.setattr(
        accounts, "paths_for",
        lambda email, owner=None, users_dir=users: real(email, owner, users_dir=users),
    )
    grant(ledger)
    grant(ledger)
    grant(ledger, "other@example.com")
    assert store.revoke_account(accounts.paths_for(EMAIL)) == 2
    assert ledger.grants_for(EMAIL) == []
    assert len(ledger.grants_for("other@example.com")) == 1


def test_pruning_forgets_dead_grants_and_idle_registrations(ledger, monkeypatch):
    issued = grant(ledger)
    ledger.register("idle", {"name": "never used"})
    ledger.register("c1", {"name": "Claude"})
    later = store._now() + store.REFRESH_TTL + store.CLIENT_IDLE + 1
    monkeypatch.setattr(store, "_now", lambda: later)
    ledger.prune()
    assert ledger.refresh_holder(issued.refresh) is None
    assert ledger.client("idle") is None
    clients = json.loads(ledger.clients_file.read_text())
    assert "idle" not in clients


def test_registration_stops_at_the_cap(ledger, monkeypatch):
    monkeypatch.setattr(store, "CLIENT_CAP", 2)
    grant(ledger)  # holds "c1", so pruning cannot free it
    assert ledger.register("c1", {"name": "Claude"})
    assert ledger.register("c2", {"name": "two"})
    assert ledger.register("c3", {"name": "three"}) is False
