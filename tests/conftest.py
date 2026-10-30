"""Shared test fixtures."""

import itertools
import pathlib

import pytest


def pytest_xdist_auto_num_workers(config):
    """Run in one process when the command names a few test files.

    `-n auto` (pyproject's addopts) starts a worker per core, and each one
    imports the app before its first test — about two seconds that a
    `pytest tests/test_onboarding.py` spends twice over on startup alone. Three
    files or fewer, given by path or node id rather than as a directory, run
    in-process; anything wider keeps every core. `None` hands back to xdist.
    """
    args = [a for a in config.args if not a.startswith("-")]
    files = {a.split("::")[0] for a in args}
    if args and len(files) <= 3 and all(f.endswith(".py") for f in files):
        return 0
    return None


@pytest.fixture(scope="session")
def _scratch_root():
    """One temporary directory per test process, removed when it ends.

    The parent of every test's `_scratch`. Created once and deleted once:
    `tmp_path` and a `mkdtemp`/`rmtree` pair per fixture per test cost about
    two milliseconds a test between them, which across the suite was seconds
    spent on directories nearly every test leaves empty. Per process, so each
    pytest-xdist worker has its own.
    """
    import shutil
    import tempfile

    root = pathlib.Path(tempfile.mkdtemp(prefix="stocks-tests-"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _yahoo_offline():
    """Answer every request yfinance sends as an offline machine would.

    yfinance talks through `curl_cffi`, and a test that priced a book without
    stubbing the fetch went to Yahoo for real — 116 requests a run on
    2026-10-04, each a crumb round-trip worth up to a second, and a result that
    depended on what Yahoo answered that minute (two chat suites passed only
    because AAPL had a live price). The code under test already copes with no
    network, so that is what it gets; a test that needs a price stubs it.

    `ConnectionError` is what curl raises with the network down, so nothing
    here takes a path production never would.
    """
    from curl_cffi import requests

    def offline(self, method, url, *args, **kwargs):
        raise requests.exceptions.ConnectionError(f"network is off in tests: {url}")

    before = requests.Session.request
    requests.Session.request = offline
    yield
    requests.Session.request = before


@pytest.fixture(autouse=True)
def _symbol_search_offline():
    """The chat's made-up-symbol check (`market.unlisted`) searches Yahoo
    through urllib, which the curl stub above does not reach: offline, it
    could not ask, and so calls nothing made up. A test of it passes its own
    `search`. Set by hand, not through `monkeypatch`: requesting that here
    would move its undo after every module fixture's teardown."""
    from stocks.chat import market

    before = market._search_rows
    market._search_rows = lambda _q: ([], False)
    yield
    market._search_rows = before


# Units of each currency per euro: made up, fixed, never fetched.
_FX_PER_EUR = {"EUR": 1.0, "USD": 1.10, "GBP": 0.85, "CHF": 0.95, "JPY": 160.0}


@pytest.fixture(autouse=True)
def _chat_keeps_forgotten():
    """The chat keeps its searches, read pages (`chat_web._SEARCHED`, `_READ`)
    and answers (`engine._kept_answers`) for minutes in process: one test's
    fake hits or answer must not answer the next test. Only modules a test
    already imported are touched."""
    import sys

    if (chat_web := sys.modules.get("stocks.web.chat_web")) is not None:
        chat_web._SEARCHED.clear()
        chat_web._READ.clear()
    if (engine := sys.modules.get("stocks.chat.engine")) is not None:
        engine._kept_answers.clear()
    yield


@pytest.fixture(scope="session", autouse=True)
def _fx_offline():
    """Answer the three frankfurter shapes `stocks.data.fx` asks for — latest,
    one day, a range — from a fixed table, without a socket.

    fx went to frankfurter for real through urllib, which `_yahoo_offline`
    does not cover: on 2026-10-13 it timed out from the CI runners and failed
    every test that priced a book in another currency. A test that cares about
    a rate stubs `fx.get_json` (or `fx._fetch`) itself, which wins over this.
    """
    from datetime import date
    from urllib.parse import parse_qs, urlparse

    import pandas as pd

    from stocks.data import fx

    def get_json(url: str, timeout: float = 15) -> dict:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        base, quote = query["base"][0], query["symbols"][0]
        rate = _FX_PER_EUR.get(quote, 1.0) / _FX_PER_EUR.get(base, 1.0)
        when = parsed.path.rsplit("/", 1)[1]
        if ".." in when:
            start, end = when.split("..")
            days = pd.bdate_range(start, end or date.today())
            return {"rates": {d.date().isoformat(): {quote: rate} for d in days}}
        day = date.today().isoformat() if when == "latest" else when
        return {"rates": {quote: rate}, "date": day}

    before = fx.get_json
    fx.get_json = get_json  # type: ignore[assignment]
    yield
    fx.get_json = before


@pytest.fixture(scope="session", autouse=True)
def _crypto_llama_deribit_offline():
    """Refuse the nightly scan's Deribit and DefiLlama reads as a down network.

    `stocks.data.crypto_market.get_json` is one shared door; a scan test that
    stubs the source functions never gets here, and one that does not (the
    older CoinGecko-only tests) must not reach the real hosts. The scan keeps
    last night's figures on a failure, which is what those tests assert past.
    """
    from urllib.error import URLError

    from stocks.data import crypto_market

    real = crypto_market.get_json

    def guarded(url, **kwargs):
        if url.startswith((crypto_market.DERIBIT, crypto_market.LLAMA,
                           crypto_market.LLAMA_STABLES)):
            raise URLError("offline in tests")
        return real(url, **kwargs)

    crypto_market.get_json = guarded
    yield
    crypto_market.get_json = real


@pytest.fixture(scope="session", autouse=True)
def _cftc_offline():
    """CFTC's Socrata endpoint answers as an offline machine would.

    `stocks.data.cot` fetches through urllib, which `_yahoo_offline` does not
    cover, and `/pulse/tables` reads it for every request. A test that cares
    about a payload stubs `cot.get_bytes` itself, which wins over this.
    """
    from stocks.data import cot

    def offline(url, **kwargs):
        raise OSError(f"network is off in tests: {url}")

    before = cot.get_bytes
    cot.get_bytes = offline  # type: ignore[assignment]
    yield
    cot.get_bytes = before


@pytest.fixture(scope="session", autouse=True)
def _no_telegram_pause():
    """Send the fan-outs' messages back to back.

    Every loop over accounts waits `telegram.SEND_PAUSE` between two sends to
    stay under Telegram's rate — real seconds in a suite that fans out to fake
    accounts hundreds of times, with nothing on the other end to rate-limit.
    """
    from stocks.notify import telegram

    before = telegram.SEND_PAUSE
    telegram.SEND_PAUSE = 0
    yield
    telegram.SEND_PAUSE = before


_scratch_seq = itertools.count()


@pytest.fixture(autouse=True)
def _scratch(_scratch_root) -> pathlib.Path:
    """This test's own empty directory, for the fixtures below to carve up.

    Never `tmp_path`: a handful of tests assert that `tmp_path` is *empty*, and
    one that asked for it should find only what it put there. Not removed after
    the test — the session root goes in one sweep at the end.
    """
    path = _scratch_root / str(next(_scratch_seq))
    path.mkdir()
    return path


def _own(scratch: pathlib.Path, name: str) -> pathlib.Path:
    """A fresh, existing directory `name` under this test's scratch."""
    path = scratch / name
    path.mkdir()
    return path


@pytest.fixture(autouse=True)
def _no_yahoo_cooldown(_scratch):
    """Start every test with `data.fetch`'s circuit breaker closed.

    The breaker is deliberately process-wide — one host, one verdict about
    Yahoo — which in a test run means one module's exhausted retry ladder would
    otherwise silence every fetch in the files that come after it, as a batch
    of unrelated failures. That is real behaviour, not a bug, so the reset
    belongs here rather than in each suite that happens to trip it.

    The same goes for its two neighbours: the names Yahoo last disowned, and
    CoinGecko's memo and cooldown — each one process-wide on purpose.
    """
    from stocks import obs
    from stocks.data import fetch
    from stocks.data.fetch import clear_coingecko, clear_throttle, clear_unlisted

    # The verdicts live on disk too: each test its own file, never the
    # checkout's data/unlisted.json (which `clear_unlisted` deletes).
    before_cache = fetch.UNLISTED_CACHE
    fetch.UNLISTED_CACHE = _scratch / "unlisted.json"

    # `obs.warn_once` remembers per process, so a test asserting a warning
    # would otherwise depend on which test said it first.
    for clear in (clear_throttle, clear_unlisted, clear_coingecko, obs._once.clear):
        clear()
    yield
    for clear in (clear_throttle, clear_unlisted, clear_coingecko, obs._once.clear):
        clear()
    fetch.UNLISTED_CACHE = before_cache


@pytest.fixture(autouse=True)
def _finnhub_off():
    """Start every test with the Finnhub quote fallback keyless and reset.

    The key is env-first and then the checkout's secrets file, so a machine
    that has one would send every quote test that leaves Yahoo unanswered to
    Finnhub for real. A test about the fallback patches `finnhub.api_key`.
    Restored by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks.data import finnhub

    before = finnhub.api_key
    finnhub.api_key = lambda: None
    finnhub.clear()
    yield
    finnhub.api_key = before
    finnhub.clear()


@pytest.fixture(autouse=True)
def _twelvedata_off():
    """Start every test with the Twelve Data daily fallback keyless and reset,
    for the reason `_finnhub_off` gives. A test about it patches `api_key`."""
    from stocks.data import twelvedata

    before = twelvedata.api_key
    twelvedata.api_key = lambda: None
    twelvedata.clear()
    yield
    twelvedata.api_key = before
    twelvedata.clear()


@pytest.fixture(autouse=True)
def _openfigi_off(_scratch):
    """Start every test with OpenFIGI offline, keyless and cached nowhere real.

    The importer asks it for each ISIN of a statement; left alone a test would
    go to the network (and write the checkout's data/openfigi_isins.json). It
    answers as an unreachable host does, which callers treat as "no answer" and
    carry on with Yahoo. A test about it patches `openfigi._post` with a stub.
    """
    from stocks.data import openfigi

    def offline(jobs, key):
        raise ConnectionError("network is off in tests: OpenFIGI")

    before = (openfigi._post, openfigi.api_key, openfigi.CACHE)
    openfigi._post = offline
    openfigi.api_key = lambda: None
    openfigi.CACHE = _scratch / "openfigi_isins.json"
    openfigi.clear()
    yield
    openfigi._post, openfigi.api_key, openfigi.CACHE = before
    openfigi.clear()


@pytest.fixture(autouse=True)
def _esef_off(_scratch):
    """Keep ESEF (filings.xbrl.org) and GLEIF off the network and off `data/`.

    `loaders.fundamentals` overlays EU/UK issuers' filed statements, which
    means a lookup and a background download the first time any ".MC" or ".AS"
    ticker is seen. Tests get no thread, a scratch store and a host that
    refuses; `tests/test_esef.py` stubs `esef._get` itself. Restored by hand
    for the reason `_own_free_llm_counter` gives (a `monkeypatch` here would
    outlive the fixtures that clear loader caches on teardown).
    """
    from stocks.data import esef

    def refused(*args, **kwargs):
        raise ConnectionError("ESEF is off in tests")

    before = (esef.ESEF_DIR, esef.BACKGROUND, esef._get)
    esef.ESEF_DIR, esef.BACKGROUND, esef._get = _scratch / "esef", False, refused
    yield
    esef.ESEF_DIR, esef.BACKGROUND, esef._get = before


@pytest.fixture(autouse=True)
def _shorts_off(_scratch):
    """Keep the short-selling registers off the network and off `data/`.

    The ticker route asks `shorts.ensure_fresh()`, which would start a thread
    downloading the AFM, Federal Gazette, FCA and FINRA files; and the stores
    are files under `data/` shared by the deployment. A test of the registers
    stubs the downloads and reads the scratch files. Restored by hand for the
    reason `_own_free_llm_counter` gives.
    """
    from stocks.data import shorts

    before = (shorts.ensure_fresh, shorts.REGISTER_FILE, shorts.VOLUME_FILE)
    shorts.ensure_fresh = lambda: None
    shorts.REGISTER_FILE = _scratch / "shorts.json"
    shorts.VOLUME_FILE = _scratch / "short_volume.json"
    shorts.clear_cache()
    yield
    shorts.ensure_fresh, shorts.REGISTER_FILE, shorts.VOLUME_FILE = before
    shorts.clear_cache()


@pytest.fixture(autouse=True)
def _chat_guard_off():
    """Start every test with the chat's scope check off (`chat/guard.py`).

    Its default is `log`, which on the keyless chain is one more model call
    beside every longer message — a call each fake provider would answer and
    count, on a thread of its own. `tests/test_chat_guard.py` switches it on.
    Restored by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks.chat import guard

    before = guard.mode
    guard.mode = lambda: "off"
    yield
    guard.mode = before


@pytest.fixture(autouse=True)
def _own_free_llm_counter(_scratch):
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
    engine.GLOBAL_FREE_FILE = _scratch / "free_llm_global.json"
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
def _own_guest_dir(_scratch):
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

    Under `_scratch` rather than `tmp_path`, because a handful of tests assert
    that `tmp_path` is *empty* — a fixture that put something there would fail
    them for a reason with nothing to do with what they are testing.

    Saved and restored by hand rather than through `monkeypatch`, for the reason
    `_own_free_llm_counter` gives above.
    """
    from stocks import accounts

    before = accounts.GUEST_DIR
    accounts.GUEST_DIR = _own(_scratch, "guest")
    yield
    accounts.GUEST_DIR = before


@pytest.fixture(autouse=True)
def _own_import_diagnostics(_scratch):
    """Keep the anonymised import diagnostics out of the checkout.

    `portfolio.diagnostics.DIAGNOSTICS_DIR` is the real `data/imports`, and
    since `/v1/import/preview` and `/commit` file a fingerprint for every
    attempt, every API test that previews a deliberately broken statement
    would otherwise leave a JSON file under version control. Its own temporary
    directory for the reason `_own_guest_dir` gives, restored by hand likewise.
    """
    from stocks.portfolio import diagnostics

    before = diagnostics.DIAGNOSTICS_DIR
    diagnostics.DIAGNOSTICS_DIR = _own(_scratch, "imports")
    yield
    diagnostics.DIAGNOSTICS_DIR = before


@pytest.fixture(autouse=True)
def _own_feedback_dir(_scratch):
    """Keep test submissions out of the real feedback inbox.

    `web.feedback.FEEDBACK_DIR` is the checkout's `data/feedback`, and
    `POST /feedback` is a route guests may call — so every suite that walks
    `guest.OPEN` files an `"a note"` report there, and `stocks feedback` read
    194 of them beside the 8 real ones on 2026-09-29. Its own temporary
    directory for the reason `_own_guest_dir` gives, restored by hand likewise.
    """
    from stocks.web import feedback

    before = feedback.FEEDBACK_DIR
    feedback.FEEDBACK_DIR = _own(_scratch, "feedback")
    yield
    feedback.FEEDBACK_DIR = before


@pytest.fixture(autouse=True)
def _bucket_off():
    """Start every test with the bucket mirror unconfigured.

    `storage` reads `[storage]` from the checkout's `secrets.toml`,
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
def _no_provider_logos():
    """Start every test with the chat providers' marks unresolved.

    `/chat/state` names a logo per provider, and resolving one mirrors the
    brand's favicon off the real internet on first touch. A test about the
    marks patches `loaders.provider_logo` itself.
    Restored by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks.api import loaders

    before = loaders.provider_logo
    loaders.provider_logo = lambda provider, domain: None
    yield
    loaders.provider_logo = before


@pytest.fixture(autouse=True)
def _own_logo_cache(_scratch):
    """Keep resolved logo URLs out of the checkout's `data/logos.json`.

    The file is under version control and shipped in the image, and a suite
    that serves a fake probe for AAPL or MSFT wrote its verdict there — a dirty
    tree after every full run in a fresh worktree. Each test starts from an
    empty cache, no per-process memo and the bucket fold not yet done.
    Restored by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks.data import logo

    before = (logo.LOGO_CACHE, logo._inconclusive, logo._bucket)
    logo.LOGO_CACHE = _own(_scratch, "logos") / "logos.json"
    logo._inconclusive = {}
    logo._bucket = {"fold": False, "push": False}
    yield
    logo.LOGO_CACHE, logo._inconclusive, logo._bucket = before


@pytest.fixture(autouse=True)
def _forget_listing_names():
    """Names one test's fake spark taught `listing_names` stay in that test."""
    from stocks.api import loaders

    loaders._LISTING_NAMES.clear()
    yield
    loaders._LISTING_NAMES.clear()


@pytest.fixture(autouse=True)
def _own_world_search_memo(_scratch):
    """Point the shared worldwide-search memo at this test's scratch.

    It is every account's memory of what Yahoo listed for a query, kept in
    `data/symbol_search.json`: a suite that serves a fake MIPS.ST would
    otherwise teach the dev server, and the next test, a listing that isn't.
    """
    from stocks.api import loaders

    memo = loaders.WORLD_MEMO
    before = memo.path
    memo.clear()
    memo.path = _own(_scratch, "world_search") / "symbol_search.json"
    yield
    memo.clear()
    memo.path = before


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


@pytest.fixture(autouse=True)
def _codes_as_printed():
    """Keep every import's bare codes as the statement printed them.

    Both import surfaces now ask which listing a bare non-dollar code traded
    on (`venue.pick`): does Yahoo quote the code, which venues the search
    offers, what each closed on the trade day — three live calls per code, on
    every preview and commit a test makes with a euro row in it. A test about
    the relabel puts the real `pick` back itself (imported at module level,
    before this runs).
    Restored by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks.portfolio import venue

    before = venue.pick
    venue.pick = lambda *a, **k: None
    yield
    venue.pick = before


# --------------------------------------------------------------- the session

#: Long enough that itsdangerous is not the thing under test.
AUTH_COOKIE_SECRET = "a-cookie-signing-secret-long-enough"


@pytest.fixture
def cookie_secret(monkeypatch) -> str:
    """Sign this test's session cookies with a known secret.

    Through the environment, because `secrets_env.secret` is env-first — so no
    secrets.toml to write and nothing that has to be torn down in the right
    order.
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
def _own_memo_dir(_scratch):
    """The API cache's persisted memos (stocks.api.cache) land under a
    per-test directory, never in the checkout's data/memo — a test that
    priced a book would otherwise leave its frames for the next run to serve.
    Saved and restored by hand, like the fixtures above, for the same reason.
    The book frames a refresh extends (`loaders._bases`) go with them, and so
    do the refreshes a test left refused (`cache._refused`)."""
    from stocks.api import cache, loaders

    before = cache.MEMO_DIR
    cache.MEMO_DIR = _scratch / "memo"
    loaders._bases.clear()
    cache._refused.clear()
    yield
    cache.MEMO_DIR = before
    loaders._bases.clear()
    cache._refused.clear()


@pytest.fixture(autouse=True)
def _own_symbol_kinds(_scratch):
    """Keep learned quoteTypes and asset kinds out of the checkout's data/.

    `funds.remember` runs on every Yahoo search row and `asset_kind.remember`
    on every fund the ticker routes classify, so without this each suite that
    serves a fake "MIPSX" or "XEON" writes it into `data/quote_types.json` /
    `data/asset_kinds.json` — and the next run, and the dev server, read it
    back as fact. Each test starts from the catalog seed alone, in its own
    directory, restored by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks.data import asset_kind, funds

    memo = funds.TYPE_MEMO
    before = (memo.path, funds._types, asset_kind.KIND_CACHE, asset_kind._kinds)
    made = _own(_scratch, "kinds")
    memo.clear()
    memo.path = made / "quote_types.json"
    funds._types = None
    asset_kind.KIND_CACHE = made / "asset_kinds.json"
    asset_kind._kinds = None
    yield
    memo.clear()
    memo.path, funds._types, asset_kind.KIND_CACHE, asset_kind._kinds = before


@pytest.fixture(autouse=True)
def _own_code_symbols(_scratch):
    """Keep the broker codes Yahoo's search resolved out of the checkout.

    `symbols.CODE_CACHE` is the real `data/code_symbols.json`, and
    `fetch.resolve` reads it on every price path — so a machine that previewed
    a Revolut statement would map a test's "SIE" to "SIE.DE" behind its back,
    and a test that resolves a fake code would leave it there for the dev
    server. Each test starts with an empty map in its own directory, restored
    by hand for the reason `_own_free_llm_counter` gives.
    """
    from stocks.data import symbols

    before = (
        symbols.CODE_CACHE,
        symbols._code_memo,
        symbols._code_misses,
        symbols._code_settled,
        symbols._listings_memo,
    )
    made = _own(_scratch, "codes")
    symbols.CODE_CACHE = made / "code_symbols.json"
    symbols._code_memo = None
    symbols._code_misses = set()
    symbols._code_settled = set()
    symbols._listings_memo = {}
    yield
    (
        symbols.CODE_CACHE,
        symbols._code_memo,
        symbols._code_misses,
        symbols._code_settled,
        symbols._listings_memo,
    ) = before


@pytest.fixture(autouse=True)
def _no_statement_model():
    """Read statements with the parsers alone unless a test brings a model.

    Both import surfaces now ask the model first (`autodetect.read`), and the
    provider they ask is whatever the account's prefs and the server's free
    chain resolve to — on a dev machine with keys in `secrets.toml`, a real
    network call on every upload a test makes. A test that means the model to
    read patches `import_statement._provider` itself. The remembered reads are
    dropped too, and the labels the model named (`instruments._memo`), so one
    test's stub never answers for the next.

    Its own `MonkeyPatch`, not the fixture: an autouse fixture that asks for
    `monkeypatch` sets it up first and so tears it down last, after the
    per-module fixtures that expect a test's patches already undone (the
    loaders' `cache_clear` in `test_api.py`).
    """
    from stocks.api.routes import import_statement
    from stocks.portfolio import autodetect, instruments

    autodetect.forget()
    instruments._memo.clear()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(import_statement, "_provider", lambda paths, held=None: (None, ""))
        yield
    autodetect.forget()
    instruments._memo.clear()


@pytest.fixture(autouse=True)
def _own_connector_state(_scratch):
    """The MCP connector's grants and clients in a per-test directory.

    `connector.store.DIR` is the checkout's real `data/mcp`, and the ledger
    over it is a process singleton — without this a test that registered a
    client or issued a token would leave it for every test after it (and on
    disk). Under `_scratch`, not `tmp_path`, for the reason
    `_own_guest_dir` gives. The in-memory halves go too: pending codes,
    fetched client metadata documents, and the per-IP and per-account budgets
    the connector spends from.
    """
    from stocks.connector import clients, oauth, store
    from stocks.web import ratelimit

    def reset() -> None:
        store._ledger = None
        clients.forget_documents()
        oauth.forget_codes()
        for key in [k for k in ratelimit._events if k.startswith(("mcp", "oauth::"))]:
            ratelimit._events.pop(key, None)

    before = store.DIR
    store.DIR = _own(_scratch, "mcp")
    reset()
    yield
    store.DIR = before
    reset()


@pytest.fixture(autouse=True)
def _own_revocations(_scratch):
    """Revoked sessions in a per-test directory, like the connector's state:
    `revocation.DIR` is the checkout's real `data/sessions`, and the index
    over it is process-wide."""
    from stocks import revocation

    before = revocation.DIR
    revocation.DIR = _own(_scratch, "sessions")
    revocation.reset_for_tests()
    yield
    revocation.DIR = before
    revocation.reset_for_tests()


@pytest.fixture(autouse=True)
def _own_score_history(_scratch):
    """The review map's recorded scores in a per-test directory: every review
    a test asks for records its names, and `score_history.DIR` is the
    checkout's real `data/scores`."""
    from stocks.data import score_history

    before = score_history.DIR
    score_history.DIR = _own(_scratch, "scores")
    score_history.clear()
    yield
    score_history.DIR = before
    score_history.clear()


@pytest.fixture(autouse=True)
def _forget_inconsistencies():
    """`data.inconsistency` is said once per window per process, so a test
    asserting the line would otherwise depend on which test said it first."""
    from stocks.portfolio import consistency

    consistency.clear()
    yield
    consistency.clear()


@pytest.fixture(autouse=True)
def _own_today_market(_scratch):
    """Give every test its own Today market file, and a lazy rebuild that
    downloads nothing: `GET /today` (open to guests, so walked by the guest
    suite) would otherwise start a background build that reaches for Yahoo,
    FRED and the free chain. The build is recorded in `briefing.market_builds`
    for a test that asserts on it; a test about the build itself patches
    `briefing._market_start` back. Restored by hand for the reason
    `_own_free_llm_counter` gives.
    """
    from stocks.api import briefing, loaders
    from stocks.chat import today_market

    before = (today_market.FILE, briefing._market_start)
    builds: list[tuple[str, str]] = []

    def inert(kind: str, lang: str) -> None:
        builds.append((kind, lang))
        briefing._market_lock.release()

    today_market.FILE = _scratch / "today_market.json"
    briefing._market_start = inert
    briefing.market_builds = builds
    briefing._market_tried.clear()
    loaders.today_market.cache_clear()
    yield
    today_market.FILE, briefing._market_start = before
    briefing._market_tried.clear()
    loaders.today_market.cache_clear()


@pytest.fixture(autouse=True)
def _sec_bulk_offline(_scratch):
    """Keep the SEC frames and 13F index off the network and out of data/.

    `data.frames` and `data.thirteenf` each have one function that touches a
    socket (frames' `_get`; the 13F index page, zip download and OpenFIGI
    post) and one file under `data/`. Every sector scan calls `frames` and
    every Yahoo-less holders lookup reads the index, so without this a suite
    would download frames for real and read whatever index the checkout holds.
    A test about either module stubs the function itself. Restored by hand
    for the reason `_own_free_llm_counter` gives.
    """
    from stocks.data import frames, thirteenf

    def offline(*args, **kwargs):
        raise ConnectionError("network is off in tests")

    before = (frames._get, frames.FRAMES_FILE, frames._loaded, thirteenf.DB,
              thirteenf._page, thirteenf._fetch_zip, thirteenf._post,
              thirteenf._restored)
    frames._get = offline
    frames.FRAMES_FILE = _scratch / "edgar_frames.json"
    frames._loaded = None
    thirteenf.DB = _scratch / "thirteenf.sqlite"
    thirteenf._page = offline
    thirteenf._fetch_zip = offline
    thirteenf._post = offline
    yield
    (frames._get, frames.FRAMES_FILE, frames._loaded, thirteenf.DB,
     thirteenf._page, thirteenf._fetch_zip, thirteenf._post,
     thirteenf._restored) = before
