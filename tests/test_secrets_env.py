"""The secrets file is looked at once per `RECHECK_S`, not once per secret.

Every look is syscalls that hand the GIL away, and behind a page's worth of
busy loaders each hand-back is a wait: the chat drawer's opening read took 8 s
on a phone while Home was loading. An edit to the file still lands, a few
seconds late.
"""

from __future__ import annotations

from stocks import secrets_env


def test_an_edit_lands_once_the_window_has_passed(monkeypatch, tmp_path):
    clock = [1000.0]
    monkeypatch.setattr(secrets_env.time, "monotonic", lambda: clock[0])
    file = tmp_path / "secrets.toml"
    file.write_text('[free_llm]\ngroq = "one"\n')
    monkeypatch.setattr(secrets_env, "SECRETS_FILE", file)
    assert secrets_env.section("free_llm") == {"groq": "one"}

    file.write_text('[free_llm]\ngroq = "two"\n')
    clock[0] += secrets_env.RECHECK_S / 2
    assert secrets_env.section("free_llm") == {"groq": "one"}

    clock[0] += secrets_env.RECHECK_S
    assert secrets_env.section("free_llm") == {"groq": "two"}


def test_reads_inside_the_window_touch_no_file(monkeypatch, tmp_path):
    file = tmp_path / "secrets.toml"
    file.write_text('[auth]\ncookie_secret = "s"\n')
    monkeypatch.setattr(secrets_env, "SECRETS_FILE", file)
    secrets_env.section("auth")

    def looked(*_args, **_kwargs):
        raise AssertionError("the file was looked at again")

    monkeypatch.setattr(secrets_env, "_read", looked)
    for _ in range(20):
        assert secrets_env.secret("NO_SUCH_ENV", "auth", "cookie_secret") == "s"


def test_another_file_is_read_at_once(monkeypatch, tmp_path):
    first = tmp_path / "a.toml"
    first.write_text('[auth]\ncookie_secret = "a"\n')
    second = tmp_path / "b.toml"
    second.write_text('[auth]\ncookie_secret = "b"\n')
    monkeypatch.setattr(secrets_env, "SECRETS_FILE", first)
    assert secrets_env.section("auth") == {"cookie_secret": "a"}
    monkeypatch.setattr(secrets_env, "SECRETS_FILE", second)
    assert secrets_env.section("auth") == {"cookie_secret": "b"}
