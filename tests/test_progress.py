"""The slow-load registry the corner banner polls (`stocks.progress`)."""

from __future__ import annotations

import pytest

from stocks import progress


@pytest.fixture(autouse=True)
def _clean():
    progress.reset()
    yield
    progress.reset()


def test_idle_book_has_no_job():
    assert progress.snapshot("db") is None


def test_a_job_counts_its_names_and_goes_away():
    with progress.job("db", "prices.tail", total=40):
        progress.tick(20)
        snap = progress.snapshot("db")
        assert snap is not None
        assert (snap["step"], snap["done"], snap["total"]) == ("prices.tail", 20, 40)
        progress.tick(30)
        assert progress.snapshot("db")["done"] == 40  # capped at total
    assert progress.snapshot("db") is None


def test_a_step_change_resets_the_count():
    with progress.job("db", "prices.tail", total=40):
        progress.tick(40)
        progress.step("prices.full", total=3)
        snap = progress.snapshot("db")
        assert (snap["step"], snap["done"], snap["total"]) == ("prices.full", 0, 3)


def test_the_next_run_knows_how_long_the_last_took():
    with progress.job("db", "prices.tail", total=1):
        pass
    progress._last[("db", "prices.tail")] = 25.0
    with progress.job("db", "prices.tail", total=1):
        assert progress.snapshot("db")["expected_s"] == 25.0


def test_a_failed_run_sets_no_estimate():
    with pytest.raises(RuntimeError), progress.job("db", "prices.full"):
        raise RuntimeError
    assert ("db", "prices.full") not in progress._last
    assert progress.snapshot("db") is None


def test_ticks_outside_a_job_are_ignored():
    progress.tick(5)
    progress.step("prices.full")
    assert progress.snapshot("db") is None


def test_a_nested_job_joins_the_outer_one():
    with progress.job("db", "prices.tail", total=10):
        with progress.job("db", "prices.full", total=99):
            progress.tick(2)
        snap = progress.snapshot("db")
        assert (snap["step"], snap["done"]) == ("prices.tail", 2)


def test_one_book_never_sees_anothers_job():
    with progress.job("mine", "prices.tail", total=5):
        assert progress.snapshot("theirs") is None


# --- over HTTP -------------------------------------------------------------

EMAIL = "holder@example.com"


@pytest.fixture
def signed_in(monkeypatch, tmp_path, sign_in):
    import json

    from fastapi.testclient import TestClient

    from stocks import accounts
    from stocks.api.app import app as fastapi_app

    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return sign_in(TestClient(fastapi_app), EMAIL), paths


def test_the_route_reports_the_callers_own_book(signed_in):
    client, paths = signed_in
    assert client.get("/v1/progress").json() == {"job": None}
    with progress.job(str(paths.db), "prices.tail", total=82):
        progress.tick(20)
        with progress.job("someone-elses.db", "prices.full", total=3):
            body = client.get("/v1/progress").json()
    job = body["job"]
    assert (job["step"], job["done"], job["total"]) == ("prices.tail", 20, 82)


def test_the_route_is_never_cached(signed_in):
    client, _ = signed_in
    assert client.get("/v1/progress").headers["cache-control"] == "no-store"
