"""Remembered BYOK keys (chat/engine.py's byok helpers).

The window is sliding: reading a live key pushes its expiry out, reading any
prefs at all deletes the keys that already died. Both halves matter — the
second is what stops an abandoned account from holding a decryptable provider
key in prefs.json (and in the bucket mirror) forever.

Every helper mutates the prefs dict and says whether the caller should save,
so a "write" here is a True from the helper that changed it.
"""

from __future__ import annotations

import time

import pytest
from cryptography.fernet import Fernet

from stocks.chat import engine


@pytest.fixture(autouse=True)
def enc(monkeypatch):
    monkeypatch.setenv("CHAT_ENC_KEY", Fernet.generate_key().decode())


def read(prefs: dict, pid: str) -> tuple[str, bool]:
    """What a surface does on a read: decrypt, then slide and prune."""
    key = engine.decrypt_byok(prefs, pid)
    return key, engine.maintain_byok(prefs, pid if key else None)


def test_save_stamps_both_clocks():
    prefs: dict = {}
    assert engine.save_byok(prefs, "anthropic", "sk-user")
    assert prefs["anthropic_key_saved_at"] == prefs["anthropic_key_first_at"]
    assert read(prefs, "anthropic")[0] == "sk-user"


def test_reading_a_stale_key_slides_it():
    prefs: dict = {}
    engine.save_byok(prefs, "anthropic", "sk-user")
    old = int(time.time()) - 60 * 24 * 3600
    prefs["anthropic_key_saved_at"] = old
    first = prefs["anthropic_key_first_at"]

    assert read(prefs, "anthropic") == ("sk-user", True)
    assert prefs["anthropic_key_saved_at"] > old
    assert prefs["anthropic_key_first_at"] == first  # the cap never moves


def test_reading_twice_in_a_day_writes_once():
    prefs: dict = {}
    engine.save_byok(prefs, "anthropic", "sk-user")
    for _ in range(3):
        # The save was the write; the slide is throttled to one a day.
        assert read(prefs, "anthropic") == ("sk-user", False)


def test_expired_key_is_deleted_not_just_refused():
    prefs: dict = {}
    engine.save_byok(prefs, "anthropic", "sk-user")
    prefs["anthropic_key_saved_at"] = int(time.time()) - engine.BYOK_TTL - 60
    prefs["anthropic_key_first_at"] = prefs["anthropic_key_saved_at"]

    assert read(prefs, "anthropic") == ("", True)
    assert not any(k.startswith("anthropic_key") for k in prefs)


def test_capped_key_is_deleted_however_recently_used():
    prefs: dict = {}
    engine.save_byok(prefs, "anthropic", "sk-user")
    prefs["anthropic_key_first_at"] = int(time.time()) - engine.BYOK_MAX_AGE - 60

    assert read(prefs, "anthropic") == ("", True)
    assert not any(k.startswith("anthropic_key") for k in prefs)


def test_reading_one_provider_prunes_another():
    prefs: dict = {}
    engine.save_byok(prefs, "anthropic", "sk-a")
    engine.save_byok(prefs, "openai", "sk-o")
    prefs["openai_key_saved_at"] = int(time.time()) - engine.BYOK_TTL - 60
    prefs["openai_key_first_at"] = prefs["openai_key_saved_at"]

    assert read(prefs, "anthropic")[0] == "sk-a"
    assert not any(k.startswith("openai_key") for k in prefs)


def test_forget_wipes_every_field():
    prefs: dict = {}
    engine.save_byok(prefs, "anthropic", "sk-user")
    assert engine.forget_byok(prefs, "anthropic") is True
    assert not any(k.startswith("anthropic_key") for k in prefs)
    assert engine.forget_byok(prefs, "anthropic") is False


def test_no_secret_means_no_key_is_stored(monkeypatch):
    monkeypatch.delenv("CHAT_ENC_KEY")
    monkeypatch.setattr(engine, "secret", lambda *a, **k: "")
    prefs: dict = {}
    assert engine.save_byok(prefs, "anthropic", "sk-user") is False
    assert prefs == {}
