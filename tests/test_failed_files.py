"""Failed statements kept encrypted for fifteen days (portfolio.failed_files)."""

from __future__ import annotations

import time

import pytest
from cryptography.fernet import Fernet

from stocks import backup, storage
from stocks.portfolio import diagnostics, failed_files
from stocks.portfolio.statement import ParseResult
from tests.test_backup import FakeClient

SLUG = "jane_example_com_1a2b3c4d"
STATEMENT = b"date,ticker\n2025-01-02,ACME\n"


@pytest.fixture
def key(monkeypatch) -> bytes:
    found = Fernet.generate_key()
    monkeypatch.setenv("CHAT_ENC_KEY", found.decode())
    return found


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "DIAGNOSTICS_DIR", tmp_path / "imports")
    monkeypatch.setattr(storage, "_cached", {"config": None})
    return tmp_path / "imports" / "raw"


@pytest.fixture
def bucket(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "DIAGNOSTICS_DIR", tmp_path / "imports")
    client = FakeClient()
    monkeypatch.setattr(storage, "_cached", {
        "config": {"bucket": "b", "access_key_id": "k", "secret_access_key": "s",
                   "endpoint_url": "", "region": "auto"},
        "client": client,
    })
    return client


def test_kept_encrypted_and_read_back(local, key):
    file_id = failed_files.keep(SLUG, "Statement Jane Doe.CSV", STATEMENT)
    assert file_id and file_id.startswith(f"{SLUG}/") and file_id.endswith(".csv.enc")
    assert "Jane" not in file_id  # the original name is not kept
    blob = (local / file_id).read_bytes()
    assert b"ACME" not in blob
    assert failed_files.read(file_id) == STATEMENT
    # The same file twice is one file.
    assert failed_files.keep(SLUG, "again.csv", STATEMENT) == file_id
    assert failed_files.kept() == [file_id]


@pytest.mark.parametrize("user", ["-", "anon", "guest", "?", "e2e_1_2_x_1a2b3c4d",
                                  "../etc_1a2b3c4d"])
def test_nobody_but_an_account_is_kept(local, key, user):
    assert failed_files.keep(user, "a.csv", STATEMENT) is None
    assert not local.exists()


def test_nothing_kept_without_a_key_or_past_the_cap(local, monkeypatch):
    monkeypatch.setenv("CHAT_ENC_KEY", "")
    monkeypatch.setattr(failed_files, "secret", lambda *a, **k: "")
    assert failed_files.keep(SLUG, "a.csv", STATEMENT) is None
    monkeypatch.setattr(failed_files, "_key", lambda: Fernet.generate_key())
    big = b"x" * (failed_files.MAX_BYTES + 1)
    assert failed_files.keep(SLUG, "a.pdf", big) is None
    assert not local.exists()


def test_with_a_bucket_nothing_touches_the_disk(bucket, key):
    file_id = failed_files.keep(SLUG, "a.pdf", b"%PDF-1.7 statement")
    assert list(bucket.objects) == [failed_files.PREFIX + file_id]
    assert not (diagnostics.DIAGNOSTICS_DIR / "raw").exists()
    assert failed_files.read(file_id) == b"%PDF-1.7 statement"


def _stamp(days_ago: float) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(time.time() - days_ago * 86400))


def test_expire_needs_no_key_and_spares_the_fresh(bucket, monkeypatch):
    old = f"{failed_files.PREFIX}{SLUG}/{_stamp(16)}-{'a' * 16}.csv.enc"
    fresh = f"{failed_files.PREFIX}{SLUG}/{_stamp(14)}-{'b' * 16}.csv.enc"
    stray = f"{failed_files.PREFIX}{SLUG}/notes.txt"
    other = f"{failed_files.PREFIX}bob_x_9f9f9f9f/{_stamp(30)}-{'c' * 16}.pdf.enc"
    bucket.objects.update({old: b"1", fresh: b"2", stray: b"3", other: b"4"})
    monkeypatch.setattr(failed_files, "secret", lambda *a, **k: "")
    assert failed_files.expire() == (3, 0)
    assert set(bucket.objects) == {fresh}


def test_a_new_failure_sweeps_its_own_expired_files(bucket, key):
    old = f"{failed_files.PREFIX}{SLUG}/{_stamp(20)}-{'a' * 16}.csv.enc"
    bucket.objects[old] = b"1"
    file_id = failed_files.keep(SLUG, "a.csv", STATEMENT)
    assert set(bucket.objects) == {failed_files.PREFIX + file_id}


def test_purge_account_takes_only_that_account(bucket, key):
    mine = failed_files.keep(SLUG, "a.csv", STATEMENT)
    theirs = failed_files.keep("bob_x_9f9f9f9f", "a.csv", STATEMENT)
    assert failed_files.purge_account(SLUG) == 1
    assert set(bucket.objects) == {failed_files.PREFIX + theirs}
    assert mine


def test_report_names_the_kept_file_only_on_failure(local, key, monkeypatch):
    monkeypatch.setattr(diagnostics.obs, "current", lambda: {"user": SLUG})
    fp = diagnostics.report("generic", "s.csv", STATEMENT, ParseResult())
    assert fp["raw"].startswith(f"{SLUG}/")
    assert diagnostics.find(fp["id"])["raw"] == fp["raw"]

    from stocks.portfolio.statement import Transaction

    ok = ParseResult(transactions=[Transaction(
        date="2025-01-02", ticker="ACME", action="buy", quantity=1, price=1,
        currency="EUR", fee=0, note="")])
    assert "raw" not in diagnostics.report("generic", "t.csv", b"other", ok)
    assert len(failed_files.kept()) == 1


def test_kept_files_are_not_snapshotted(bucket):
    assert backup.KEPT_IMPORTS_PREFIX == failed_files.PREFIX
    bucket.objects = {"data/users/a/portfolio.db": b"1",
                      f"{failed_files.PREFIX}{SLUG}/x.csv.enc": b"2"}
    assert backup.live_keys() == ["data/users/a/portfolio.db"]


def test_cli_fetch_writes_outside_the_repo_only(local, key, tmp_path):
    import argparse

    from stocks import cli
    from stocks.config import PROJECT_ROOT

    file_id = failed_files.keep(SLUG, "a.csv", STATEMENT)
    out = tmp_path / "statement.csv"
    cli.cmd_imports(argparse.Namespace(imports_command="fetch", id=file_id, out=str(out)))
    assert out.read_bytes() == STATEMENT
    with pytest.raises(SystemExit):
        cli.cmd_imports(argparse.Namespace(
            imports_command="fetch", id=file_id, out=str(PROJECT_ROOT / "x.csv")))
    assert not (PROJECT_ROOT / "x.csv").exists()


@pytest.mark.parametrize("email", [
    "jane@example.com", "Jane.Doe+stocks@Example.co.uk", "a-b_c@x.io",
    "x" * 64 + "@" + "sub." * 40 + "example.com",
])
def test_every_real_account_slug_is_one(email):
    from stocks import accounts

    assert failed_files._SLUG.fullmatch(accounts.slug(email))


def test_held_finds_a_kept_file_by_its_digest(local, key):
    """How a report names a statement a failed read already kept, instead of
    sending it again: only the same account's, only a well-formed digest."""
    import hashlib

    digest = hashlib.sha256(STATEMENT).hexdigest()[:16]
    assert failed_files.held(SLUG, digest) is None
    file_id = failed_files.keep(SLUG, "a.csv", STATEMENT)
    assert failed_files.held(SLUG, digest) == file_id
    assert failed_files.held("bob_example_com_1a2b3c4d", digest) is None
    assert failed_files.held(SLUG, "0" * 16) is None
    assert failed_files.held(SLUG, "../" + digest) is None
    assert failed_files.held("../x", digest) is None


def test_held_reads_the_bucket_too(bucket, key):
    import hashlib

    file_id = failed_files.keep(SLUG, "a.pdf", b"%PDF-1.7 statement")
    digest = hashlib.sha256(b"%PDF-1.7 statement").hexdigest()[:16]
    assert failed_files.held(SLUG, digest) == file_id
