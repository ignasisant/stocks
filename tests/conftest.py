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

    The same goes for its two neighbours: the names Yahoo last disowned, and
    CoinGecko's memo and cooldown — each one process-wide on purpose.
    """
    from stocks.data.fetch import clear_coingecko, clear_throttle, clear_unlisted

    for clear in (clear_throttle, clear_unlisted, clear_coingecko):
        clear()
    yield
    for clear in (clear_throttle, clear_unlisted, clear_coingecko):
        clear()


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


@pytest.fixture(autouse=True)
def _own_import_diagnostics():
    """Keep the anonymised import diagnostics out of the checkout.

    `portfolio.diagnostics.DIAGNOSTICS_DIR` is the real `data/imports`, and
    since `/v1/import/preview` and `/commit` file a fingerprint for every
    attempt the way the Streamlit page does, every API test that previews a
    deliberately broken statement would otherwise leave a JSON file under
    version control. Its own temporary directory for the reason
    `_own_guest_dir` gives, restored by hand likewise.
    """
    import shutil
    import tempfile

    from stocks.portfolio import diagnostics

    before = diagnostics.DIAGNOSTICS_DIR
    made = tempfile.mkdtemp(prefix="imports-")
    diagnostics.DIAGNOSTICS_DIR = pathlib.Path(made)
    yield
    diagnostics.DIAGNOSTICS_DIR = before
    shutil.rmtree(made, ignore_errors=True)


@pytest.fixture(autouse=True)
def _own_feedback_dir():
    """Keep test submissions out of the real feedback inbox.

    `web.feedback.FEEDBACK_DIR` is the checkout's `data/feedback`, and
    `POST /feedback` is a route guests may call — so every suite that walks
    `guest.OPEN` files an `"a note"` report there, and `stocks feedback` read
    194 of them beside the 8 real ones on 2026-09-29. Its own temporary
    directory for the reason `_own_guest_dir` gives, restored by hand likewise.
    """
    import shutil
    import tempfile

    from stocks.web import feedback

    before = feedback.FEEDBACK_DIR
    made = tempfile.mkdtemp(prefix="feedback-")
    feedback.FEEDBACK_DIR = pathlib.Path(made)
    yield
    feedback.FEEDBACK_DIR = before
    shutil.rmtree(made, ignore_errors=True)


@pytest.fixture(autouse=True)
def _bucket_off():
    """Start every test with the bucket mirror unconfigured.

    `storage` reads `[storage]` from the checkout's `.streamlit/secrets.toml`,
    and on a machine that deploys, that is the production bucket: a write path
    under the repo root that a test exercised was mirrored there — which is how
    the guest-route suites' test notes reached the operator's inbox. A test
    about the mirror says what it is by replacing `storage._cached` itself.
    Restored by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks import storage

    before = storage._cached
    storage._cached = {"config": None}
    yield
    storage._cached = before


@pytest.fixture(autouse=True)
def _web_off():
    """Start every test with the chat's web search unavailable.

    The assistant reads the web wherever `ddgs` is installed — there is no
    per-account toggle any more (`engine.web_enabled`) — and it is installed
    here, so without this every suite that takes a chat turn would plan
    searches and open pages on the real internet. A test about the web says so
    by patching `chat_web.available` itself.
    Restored by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks.web import chat_web

    before = chat_web.available
    chat_web.available = lambda: False
    yield
    chat_web.available = before


@pytest.fixture(autouse=True)
def _listing_at_the_ledgers_word():
    """Answer "which currency is this price series in" with "unknown".

    `analysis.listing` asks the checkout's real profile memo (`data/profiles.
    json`) and, for an aliased name it has never seen, Yahoo — on every path
    that turns a close into money. Unknown falls back to the ledger row's
    currency, which is what every suite here was written against; a test about
    listing currencies says what the listing is by patching `_lookup` itself.
    Restored by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks.analysis import listing

    before = listing._lookup
    listing._lookup = lambda ticker: None
    yield
    listing._lookup = before


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


@pytest.fixture(autouse=True)
def _own_memo_dir(tmp_path):
    """The API cache's persisted memos (stocks.api.cache) land under a
    per-test directory, never in the checkout's data/memo — a test that
    priced a book would otherwise leave its frames for the next run to serve.
    Saved and restored by hand, like the fixtures above, for the same reason."""
    from stocks.api import cache

    before = cache.MEMO_DIR
    cache.MEMO_DIR = tmp_path / "memo"
    yield
    cache.MEMO_DIR = before


@pytest.fixture(autouse=True)
def _own_symbol_kinds():
    """Keep learned quoteTypes and asset kinds out of the checkout's data/.

    `funds.remember` runs on every Yahoo search row and `asset_kind.remember`
    on every fund the ticker routes classify, so without this each suite that
    serves a fake "MIPSX" or "XEON" writes it into `data/quote_types.json` /
    `data/asset_kinds.json` — and the next run, and the dev server, read it
    back as fact. Each test starts from the catalog seed alone, in its own
    directory, restored by hand for the reason `_own_free_llm_counter` gives.
    """
    import shutil
    import tempfile

    from stocks.data import asset_kind, funds

    before = (funds.TYPE_CACHE, funds._types, asset_kind.KIND_CACHE, asset_kind._kinds)
    made = pathlib.Path(tempfile.mkdtemp(prefix="kinds-"))
    funds.TYPE_CACHE = made / "quote_types.json"
    funds._types = None
    asset_kind.KIND_CACHE = made / "asset_kinds.json"
    asset_kind._kinds = None
    yield
    funds.TYPE_CACHE, funds._types, asset_kind.KIND_CACHE, asset_kind._kinds = before
    shutil.rmtree(made, ignore_errors=True)
