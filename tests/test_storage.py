"""S3-compatible persistence layer (stocks.storage) and its write hooks."""

from __future__ import annotations

import io

import pytest

from stocks import storage
from stocks.portfolio import last_import, ledger


class NoSuchKey(Exception):
    pass


class FakeExceptions:
    NoSuchKey = NoSuchKey


class FakeClient:
    """Minimal in-memory stand-in for boto3's S3 client."""

    exceptions = FakeExceptions

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.calls: list[tuple[str, str]] = []

    def put_object(self, Bucket, Key, Body, Metadata=None):
        self.calls.append(("put", Key))
        self.objects[Key] = Body
        self.metadata[Key] = dict(Metadata or {})

    def get_object(self, Bucket, Key):
        self.calls.append(("get", Key))
        if Key not in self.objects:
            raise NoSuchKey(Key)
        return {
            "Body": io.BytesIO(self.objects[Key]),
            "Metadata": self.metadata.get(Key, {}),
        }

    def delete_object(self, Bucket, Key):
        self.calls.append(("delete", Key))
        self.objects.pop(Key, None)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        client = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                client.calls.append(("list", Prefix))
                keys = sorted(k for k in client.objects if k.startswith(Prefix))
                yield {"Contents": [{"Key": k} for k in keys]} if keys else {}

        return Paginator()


@pytest.fixture
def bucket(monkeypatch, tmp_path):
    """Enable storage against a fake client, rooted at tmp_path."""
    client = FakeClient()
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        storage,
        "_cached",
        {
            "config": {
                "bucket": "b",
                "access_key_id": "k",
                "secret_access_key": "s",
                "endpoint_url": "",
                "region": "auto",
            },
            "client": client,
        },
    )
    monkeypatch.setattr(storage, "_restored", set())
    monkeypatch.setattr(storage, "_listings", {})
    return client


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.setattr(storage, "_cached", {"config": None})


# ------------------------------------------------------------------ storage


def test_disabled_is_noop(disabled, tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hi")
    assert not storage.enabled()
    storage.persist(f)  # must not raise or need a client
    assert storage.restore(f) is False


def test_persist_uploads_repo_relative_key(bucket, tmp_path):
    f = tmp_path / "data" / "users" / "jane" / "prefs.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"currency": "USD"}')
    storage.persist(f)
    assert bucket.objects["data/users/jane/prefs.json"] == f.read_bytes()


def test_persist_missing_file_deletes_remote(bucket, tmp_path):
    key = "data/last_import.json"
    bucket.objects[key] = b"{}"
    storage.persist(tmp_path / "data" / "last_import.json")
    assert key not in bucket.objects


def test_persist_outside_repo_root_skips(bucket, tmp_path_factory):
    other = tmp_path_factory.mktemp("elsewhere") / "f.txt"
    other.write_text("x")
    storage.persist(other)
    assert bucket.calls == []


def test_restore_overwrites_local(bucket, tmp_path):
    bucket.objects["watchlist.yaml"] = b"watchlist: []\n"
    f = tmp_path / "watchlist.yaml"
    f.write_text("stale local")
    assert storage.restore(f) is True
    assert f.read_bytes() == b"watchlist: []\n"


def test_restore_keeps_the_mtime_the_file_was_persisted_with(bucket, tmp_path):
    """Caches key on a ledger's mtime. A restore stamping "now" made every
    boot a fresh write, and the memos persisted under the old key never hit."""
    import os

    f = tmp_path / "portfolio.db"
    f.write_bytes(b"book")
    os.utime(f, (1_700_000_000.5, 1_700_000_000.5))
    storage.persist(f)
    f.unlink()  # the boot
    assert storage.restore(f)
    assert f.stat().st_mtime == 1_700_000_000.5


def test_restore_falls_back_to_last_modified(bucket, tmp_path, monkeypatch):
    """An object persisted before the metadata existed: LastModified, which
    is at least the same on every boot."""
    from datetime import UTC, datetime

    stamp = datetime(2026, 10, 1, tzinfo=UTC)
    bucket.objects["old.db"] = b"x"
    real = bucket.get_object
    monkeypatch.setattr(
        bucket, "get_object", lambda **kw: {**real(**kw), "LastModified": stamp}
    )
    f = tmp_path / "old.db"
    assert storage.restore(f)
    assert f.stat().st_mtime == stamp.timestamp()


def test_restore_missing_remote(bucket, tmp_path):
    f = tmp_path / "nope.json"
    assert storage.restore(f) is False
    assert not f.exists()


def test_restore_once_runs_once_per_group(bucket, tmp_path):
    bucket.objects["u/a.txt"] = b"a"
    group = tmp_path / "u"
    files = (group / "a.txt",)
    storage.restore_once(group, files)
    storage.restore_once(group, files)
    assert bucket.calls.count(("get", "u/a.txt")) == 1


def test_restore_once_retries_after_failure(bucket, tmp_path, monkeypatch):
    group = tmp_path / "u"
    bucket.objects["u/a.txt"] = b"a"
    real, state = storage.restore, {"fail": True}

    def flaky(path):
        if state["fail"]:
            raise OSError("net down")
        return real(path)

    monkeypatch.setattr(storage, "restore", flaky)
    with pytest.raises(OSError):
        storage.restore_once(group, (group / "a.txt",))
    state["fail"] = False  # group must not be cached as restored by the failed try
    storage.restore_once(group, (group / "a.txt",))
    assert (group / "a.txt").read_bytes() == b"a"


def test_restore_once_makes_a_concurrent_caller_wait(bucket, tmp_path, monkeypatch):
    """The second request of a fresh boot must not run against an empty dir.

    It used to return at once, while the first request was still downloading,
    and read prefs.json as absent — then write that back over the bucket copy.
    """
    import threading

    group = tmp_path / "u"
    bucket.objects["u/a.txt"] = b"a"
    real = storage.restore
    started, release = threading.Event(), threading.Event()

    def slow(path):
        started.set()
        release.wait(5)
        return real(path)

    monkeypatch.setattr(storage, "restore", slow)
    first = threading.Thread(target=storage.restore_once,
                             args=(group, (group / "a.txt",)))
    first.start()
    assert started.wait(5)
    seen: list[bool] = []
    second = threading.Thread(
        target=lambda: (storage.restore_once(group, (group / "a.txt",)),
                        seen.append((group / "a.txt").exists()))
    )
    second.start()
    second.join(0.2)
    assert second.is_alive()  # waiting on the first restore, not racing past it
    release.set()
    first.join(5)
    second.join(5)
    assert seen == [True]
    assert bucket.calls.count(("get", "u/a.txt")) == 1


def test_restore_stem_pulls_only_the_file_asked_for(bucket, tmp_path):
    d = tmp_path / "src/stocks/web/static/logos"
    bucket.objects["src/stocks/web/static/logos/AAPL.png"] = b"a"
    bucket.objects["src/stocks/web/static/logos/MSFT.svg"] = b"m"
    bucket.objects["src/stocks/web/static/logos/nested/AAPL.png"] = b"n"
    assert storage.restore_stem(d, "AAPL") == "AAPL.png"
    assert (d / "AAPL.png").read_bytes() == b"a"
    assert not (d / "MSFT.svg").exists()
    assert not (d / "nested").exists()
    # One listing for the process, then one GET per file asked for.
    assert storage.restore_stem(d, "MSFT") == "MSFT.svg"
    assert storage.restore_stem(d, "AAPL") == "AAPL.png"
    assert [c for c, _ in bucket.calls] == ["list", "get", "get"]


def test_restore_stem_matches_the_exact_stem(bucket, tmp_path):
    d = tmp_path / "logos"
    bucket.objects["logos/BRK.B.png"] = b"b"
    assert storage.restore_stem(d, "BRK") is None
    assert storage.restore_stem(d, "BRK.B") == "BRK.B.png"


def test_restore_stem_miss_costs_no_get(bucket, tmp_path):
    d = tmp_path / "logos"
    bucket.objects["logos/AAPL.png"] = b"a"
    assert storage.restore_stem(d, "ZZZZ") is None
    assert storage.restore_stem(d, "YYYY") is None
    assert bucket.calls == [("list", "logos/")]


def test_restore_stem_local_wins(bucket, tmp_path):
    d = tmp_path / "logos"
    d.mkdir()
    (d / "AAPL.png").write_bytes(b"fresh")
    bucket.objects["logos/AAPL.png"] = b"stale"
    assert storage.restore_stem(d, "AAPL") == "AAPL.png"
    assert (d / "AAPL.png").read_bytes() == b"fresh"


def test_restore_stem_retries_a_failed_listing(bucket, tmp_path, monkeypatch):
    d = tmp_path / "logos"
    bucket.objects["logos/AAPL.png"] = b"a"
    real = bucket.get_paginator
    monkeypatch.setattr(bucket, "get_paginator", lambda name: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        storage.restore_stem(d, "AAPL")
    monkeypatch.setattr(bucket, "get_paginator", real)
    assert storage.restore_stem(d, "AAPL") == "AAPL.png"


def test_restore_stem_disabled_is_noop(disabled, tmp_path):
    assert storage.restore_stem(tmp_path / "logos", "AAPL") is None
    assert not (tmp_path / "logos").exists()


def test_read_leaves_the_local_file_alone(bucket, tmp_path):
    f = tmp_path / "data/logos.json"
    f.parent.mkdir()
    f.write_text("local")
    bucket.objects["data/logos.json"] = b"remote"
    assert storage.read(f) == b"remote"
    assert f.read_text() == "local"
    assert storage.read(tmp_path / "data/none.json") is None


def test_mirror_logo_persists_and_restores(bucket, tmp_path, monkeypatch):
    """One successful mirror survives an 'ephemeral reboot' via the bucket."""
    import stocks.data.logo as logo_mod

    d = tmp_path / "src/stocks/web/static/logos"
    monkeypatch.setattr(logo_mod, "logo_url", lambda t: "https://x/AAPL.png")
    monkeypatch.setattr(
        logo_mod, "get_bytes_and_type", lambda url, **kw: (b"png", "image/png")
    )
    assert logo_mod.mirror_logo("AAPL", d) == "AAPL.png"
    assert bucket.objects["src/stocks/web/static/logos/AAPL.png"] == b"png"

    # "Reboot": static dir wiped, restore memo reset, source unresolvable —
    # the bucket copy alone brings the logo back.
    for f in d.iterdir():
        f.unlink()
    monkeypatch.setattr(storage, "_listings", {})
    monkeypatch.setattr(logo_mod, "logo_url", lambda t: None)
    assert logo_mod.mirror_logo("AAPL", d) == "AAPL.png"
    assert (d / "AAPL.png").read_bytes() == b"png"


def _logo_cache(monkeypatch, tmp_path):
    import stocks.data.logo as logo_mod

    monkeypatch.setattr(logo_mod, "LOGO_CACHE", tmp_path / "data/logos.json")
    monkeypatch.setattr(logo_mod, "_inconclusive", {})
    monkeypatch.setattr(logo_mod, "_bucket", {"fold": False, "push": False})
    logo_mod.LOGO_CACHE.parent.mkdir(parents=True, exist_ok=True)
    return logo_mod


def test_logo_cache_folds_bucket_copy_into_shipped_one(bucket, tmp_path, monkeypatch):
    """The image ships a cache, the host adds to it: both survive a deploy."""
    import json

    logo_mod = _logo_cache(monkeypatch, tmp_path)
    v = logo_mod.CACHE_VERSION
    logo_mod.LOGO_CACHE.write_text(json.dumps({"_v": v, "DEV": "https://d", "BOTH": "a"}))
    bucket.objects["data/logos.json"] = json.dumps(
        {"_v": v, "HOST": "", "BOTH": "b"}
    ).encode()
    monkeypatch.setattr(logo_mod, "_probe", lambda url: "ok")

    assert logo_mod.logo_url("HOST") is None  # the host's answer, no probe
    assert logo_mod.logo_url("BOTH") == "b"
    assert logo_mod.logo_url("NEW") == logo_mod.FMP_LOGO_URL.format(ticker="NEW")
    pushed = json.loads(bucket.objects["data/logos.json"])
    assert {"DEV", "HOST", "BOTH", "NEW"} <= set(pushed)
    assert bucket.calls.count(("get", "data/logos.json")) == 1


def test_logo_cache_never_pushes_after_a_failed_fold(bucket, tmp_path, monkeypatch):
    """A read that failed must not let this host's file replace the bucket's."""
    logo_mod = _logo_cache(monkeypatch, tmp_path)
    bucket.objects["data/logos.json"] = b"{}"
    monkeypatch.setattr(storage, "read", lambda path: 1 / 0)
    monkeypatch.setattr(logo_mod, "_probe", lambda url: "ok")
    assert logo_mod.logo_url("AAPL")
    assert bucket.objects["data/logos.json"] == b"{}"


# -------------------------------------------------------------- write hooks


def test_ledger_writes_persist(bucket, tmp_path):
    db = tmp_path / "data" / "users" / "jane" / "portfolio.db"
    db.parent.mkdir(parents=True)
    key = "data/users/jane/portfolio.db"

    tx_id = ledger.add(ledger.Transaction("2026-01-02", "AAPL", "buy", 1, 100), db)
    assert key in bucket.objects
    snapshot = bucket.objects[key]

    ledger.delete(tx_id, db)
    assert bucket.objects[key] != snapshot  # re-uploaded after the delete
    assert ledger.all_transactions(db) == []


def test_last_import_save_and_forget_persist(bucket, tmp_path):
    p = tmp_path / "data" / "users" / "jane" / "last_import.json"
    p.parent.mkdir(parents=True)
    key = "data/users/jane/last_import.json"

    last_import.save(last_import.ImportRecord("s.csv", "2026-01-02T00:00:00Z", [1]), p)
    assert key in bucket.objects
    last_import.forget(p)
    assert key not in bucket.objects


def test_restore_account_restores_before_seeding(bucket, tmp_path):
    from stocks import accounts

    paths = accounts.paths_for(
        "jane@example.com", users_dir=tmp_path / "data" / "users"
    )
    key = f"data/users/{accounts.slug('jane@example.com')}/watchlist.yaml"
    bucket.objects[key] = b"watchlist:\n- ticker: NVDA\n"

    accounts.restore_account(paths)
    assert "NVDA" in paths.watchlist.read_text()  # restored copy, not the starter


def test_restore_account_seeds_and_persists_new_account(bucket, tmp_path):
    from stocks import accounts

    paths = accounts.paths_for(
        "new@example.com", users_dir=tmp_path / "data" / "users"
    )
    accounts.restore_account(paths)
    assert "AAPL" in paths.watchlist.read_text()
    key = f"data/users/{accounts.slug('new@example.com')}/watchlist.yaml"
    assert key in bucket.objects


def test_restore_account_migrates_legacy_bucket_objects(bucket, tmp_path):
    # An account whose data predates the digest-suffixed slug and survives
    # only in the bucket (ephemeral host): objects are restored, the dir is
    # renamed, and every object is re-keyed to the new slug.
    from stocks import accounts

    users = tmp_path / "data" / "users"
    email = "jane@example.com"
    paths = accounts.paths_for(email, users_dir=users)
    legacy = users / accounts.legacy_slug(email)
    legacy_key = f"data/users/{accounts.legacy_slug(email)}/portfolio.db"
    bucket.objects[legacy_key] = b"ledgerbytes"

    accounts.restore_account(paths, legacy_root=legacy)
    assert paths.db.read_bytes() == b"ledgerbytes"
    assert not legacy.exists()
    assert legacy_key not in bucket.objects  # old key deleted
    new_key = f"data/users/{accounts.slug(email)}/portfolio.db"
    assert bucket.objects[new_key] == b"ledgerbytes"


def test_list_keys_filters_by_prefix(bucket):
    bucket.objects["data/users/jane_ab12cd34/prefs.json"] = b"{}"
    bucket.objects["data/users/bob_ef56ab78/prefs.json"] = b"{}"
    bucket.objects["data/prefs.json"] = b"{}"
    keys = storage.list_keys("data/users/")
    assert keys == [
        "data/users/bob_ef56ab78/prefs.json",
        "data/users/jane_ab12cd34/prefs.json",
    ]


def test_list_keys_disabled_returns_empty(disabled):
    assert storage.list_keys("data/") == []
