"""Shared test fixtures."""

import pathlib

import pytest


@pytest.fixture(autouse=True)
def _no_yahoo_cooldown():
    """Start every test with `data.fetch`'s circuit breaker closed.

    The breaker is deliberately process-wide — one host, one verdict about
    Yahoo — which in a test run means one module's exhausted retry ladder would
    otherwise silence every fetch in the files that come after it, as a batch
    of unrelated failures. That is real behaviour, not a bug, so the reset
    belongs here rather than in each suite that happens to trip it.
    """
    from stocks.data.fetch import clear_throttle

    clear_throttle()
    yield
    clear_throttle()


@pytest.fixture(autouse=True)
def _own_free_llm_counter(tmp_path):
    """Give every test its own global free-LLM counter, on its own path.

    The real one is a file under `data/`, read once per process and shared by
    the whole deployment — which is right in production and wrong here: the
    counter is capped per calendar day, so a day the deployment actually spends
    its allowance is a day every test that takes a free turn fails, on a
    machine where nothing is broken. That is what happened on 2026-09-18, with
    the file sitting at 400 of 400.

    Isolated here rather than in each suite because nothing in a test should
    ever read or write that file, whether it thinks about the counter or not.

    Saved and restored by hand rather than through `monkeypatch`: an autouse
    fixture in conftest that asks for `monkeypatch` makes every test's
    monkeypatch the *first* fixture set up and so the last torn down, which
    puts other fixtures' teardown before the restores they depend on.
    """
    from stocks.chat import engine

    before = (
        engine.GLOBAL_FREE_FILE,
        dict(engine._global_free),
        engine._global_free_loaded,
    )
    engine.GLOBAL_FREE_FILE = tmp_path / "free_llm_global.json"
    engine._global_free = {"day": "", "used": 0}
    engine._global_free_loaded = False
    try:
        yield
    finally:
        (
            engine.GLOBAL_FREE_FILE,
            engine._global_free,
            engine._global_free_loaded,
        ) = before



@pytest.fixture(autouse=True)
def _own_guest_dir():
    """Give every test its own anonymous-visitor directory.

    `accounts.GUEST_DIR` is a module constant pointing at the checkout's real
    `data/users/_guest`, and since the API started serving guests it is what an
    unauthenticated request reads — so without this, half the suite asserts
    against whatever demo book this machine happens to be carrying, and any
    test that exercises a write path aims it at a directory under version
    control.

    Empty rather than seeded: in production `api.guestbook.provision()` fills it
    at boot, and a test that wants a book in it should put one there where the
    reader can see it.

    Its own temporary directory rather than a child of `tmp_path`, because a
    handful of tests assert that `tmp_path` is *empty* — a fixture that put
    something there would fail them for a reason with nothing to do with what
    they are testing.

    Saved and restored by hand rather than through `monkeypatch`, for the reason
    `_own_free_llm_counter` gives above.
    """
    import shutil
    import tempfile

    from stocks import accounts

    before = accounts.GUEST_DIR
    made = tempfile.mkdtemp(prefix="guest-")
    accounts.GUEST_DIR = pathlib.Path(made)
    yield
    accounts.GUEST_DIR = before
    shutil.rmtree(made, ignore_errors=True)

# --------------------------------------------------------------- the session

#: Long enough that itsdangerous is not the thing under test.
AUTH_COOKIE_SECRET = "a-cookie-signing-secret-long-enough"


@pytest.fixture
def cookie_secret(monkeypatch) -> str:
    """Sign this test's session cookies with a known secret.

    Through the environment, because `secrets_env.secret` is env-first — so no
    secrets.toml to write, no Streamlit config singleton to reset, and nothing
    that has to be torn down in the right order.
    """
    monkeypatch.setenv("AUTH_COOKIE_SECRET", AUTH_COOKIE_SECRET)
    return AUTH_COOKIE_SECRET


@pytest.fixture
def sign_in(cookie_secret):
    """Put a signed session cookie for `email` on a client, and hand it back.

    A factory rather than an autouse fixture: a good half of what the API's
    tests assert is what an *anonymous* caller gets, and a suite-wide session
    would quietly make those pass for the wrong reason.
    """
    from stocks import session

    def _sign_in(client, email: str, **claims):
        client.cookies.set(
            session.COOKIE,
            session.mint({"email": email, "email_verified": True, "name": "T", **claims}),
        )
        return client

    return _sign_in
