"""The Yahoo circuit breaker and the bulk-download budget (stocks.data.fetch).

Not to be confused with `test_throttle.py`, which is the per-client HTTP burst
limit in front of the app — this one is about the provider throttling us.

Both exist for the same failure: Yahoo refuses this host's egress IP, and the
app spends minutes rediscovering that, once per block, on every request.
"""

import functools
import logging
import threading
import time

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

import stocks.data.fetch as fetch


# ------------------------------------------------------------------ breaker
def test_a_spent_retry_ladder_opens_the_cooldown():
    calls = []

    def always_limited():
        calls.append(1)
        raise YFRateLimitError()

    with pytest.raises(YFRateLimitError):
        fetch.retry(always_limited, attempts=2, base_delay=0.0)
    assert len(calls) == 2  # the ladder was climbed...
    assert fetch.throttle_remaining() > 0  # ...and lost, so the breaker is open


def test_the_cooldown_refuses_without_touching_the_network():
    fetch.trip_throttle()
    called = []
    with pytest.raises(YFRateLimitError):
        fetch.retry(lambda: called.append(1))
    assert called == []  # the point: no request, no backoff, no yfinance retries


def test_a_success_never_opens_the_cooldown():
    assert fetch.retry(lambda: "ok") == "ok"
    assert fetch.throttle_remaining() == 0


def test_one_transient_limit_still_clears_on_the_next_attempt():
    tries = []

    def flaky():
        tries.append(1)
        if len(tries) == 1:
            raise YFRateLimitError()
        return "ok"

    assert fetch.retry(flaky, attempts=3, base_delay=0.0) == "ok"
    assert fetch.throttle_remaining() == 0  # flaky is not burnt


def test_the_breaker_is_shared_with_the_quote_path():
    """One host, one verdict: a throttled price fetch also silences quotes."""
    from stocks.data import quotes as q

    fetch.trip_throttle()
    assert q.quotes(["AAPL"]) == {}


def test_clear_throttle_reopens_the_line():
    fetch.trip_throttle()
    assert fetch.throttle_remaining() > 0
    fetch.clear_throttle()
    assert fetch.throttle_remaining() == 0
    assert fetch.retry(lambda: "ok") == "ok"


def test_trip_throttle_never_shortens_a_longer_cooldown():
    fetch.trip_throttle(cooldown=120)
    fetch.trip_throttle(cooldown=1)
    assert fetch.throttle_remaining() > 60


# ------------------------------------------------------------------- budget
def test_a_hung_download_gives_up_at_the_budget():
    slow = []

    def hang():
        slow.append(1)
        time.sleep(5)

    started = time.monotonic()
    with pytest.raises(YFRateLimitError):
        fetch._budgeted(hang, budget=0.1)
    # The caller is freed on the budget, not on the hang.
    assert time.monotonic() - started < 2
    assert slow == [1]


def test_the_budget_does_not_open_the_cooldown():
    """Slow is not the same claim as refused — the next request must try again."""
    with pytest.raises(YFRateLimitError):
        fetch._budgeted(lambda: time.sleep(5), budget=0.1)
    assert fetch.throttle_remaining() == 0


def test_a_download_inside_its_budget_is_untouched():
    assert fetch._budgeted(lambda: "frames", budget=5) == "frames"


def test_an_error_under_budget_propagates_unchanged():
    def boom():
        raise ValueError("bad frame")

    with pytest.raises(ValueError, match="bad frame"):
        fetch._budgeted(boom, budget=5)


def test_fetch_many_bounds_the_whole_retry_ladder(monkeypatch):
    """The budget wraps the retries, not each one: three attempts must not buy
    three budgets.

    The abandoned ladder is let go and waited for before the test ends. Left to
    hang it outlived the test by twenty seconds, logged into a closed stream
    and, on its last rung, tripped the process-wide breaker in the middle of
    whichever test that worker had moved on to."""
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    monkeypatch.setattr(fetch, "retry", functools.partial(fetch.retry, base_delay=0))
    released = threading.Event()

    def hang(*a, **k):
        released.wait(timeout=5)
        raise YFRateLimitError()

    monkeypatch.setattr(fetch.yf, "download", hang)
    before = set(threading.enumerate())
    started = time.monotonic()
    with pytest.raises(YFRateLimitError):
        fetch.fetch_many(["AAPL", "NVDA"], budget=0.2)
    assert time.monotonic() - started < 2
    released.set()
    for worker in set(threading.enumerate()) - before:
        worker.join(timeout=5)


def test_fetch_many_still_returns_frames(monkeypatch):
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    idx = pd.date_range("2026-01-05", periods=2, name="Date")
    frame = pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)
    monkeypatch.setattr(fetch.yf, "download", lambda *a, **k: frame)
    out = fetch.fetch_many(["AAPL"])
    assert list(out) == ["AAPL"] and len(out["AAPL"]) == 2


def test_fetch_many_never_asks_yahoo_for_a_blank_label(monkeypatch):
    """ERR-07 (triage 2026-11-05): a book's batch went out with "" in it and
    yfinance logged "Empty ticker name" for it."""
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    idx = pd.date_range("2026-01-05", periods=2, name="Date")
    frame = pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)
    asked: list[list[str]] = []

    def download(symbols, *a, **k):
        asked.append(list(symbols))
        return frame

    monkeypatch.setattr(fetch.yf, "download", download)
    out = fetch.fetch_many(["AAPL", "", " "])
    assert asked == [["AAPL"]] and list(out) == ["AAPL"]
    assert fetch.fetch_many(["", " "]) == {}
    assert asked == [["AAPL"]]


# ---------------------------------------------- what the bulk download said
# yfinance swallows every per-symbol failure and only names it in a summary it
# logs once the batch is done. "Yahoo has no such symbol" and "Yahoo refused"
# arrive the same way — an absent frame — and only that summary tells them
# apart.

DISOWNED = "No data found, symbol may be delisted"
REFUSED = "YFRateLimitError('Too Many Requests. Rate limited. Try after a while.')"


@pytest.fixture
def yf_log():
    """yfinance's logger, hearing everything for the length of the test."""
    logger = logging.getLogger("yfinance")
    level, disabled = logger.level, logger.disabled
    logger.setLevel(logging.DEBUG)
    logger.disabled = False
    yield logger
    logger.setLevel(level)
    logger.disabled = disabled


def _bulk(yf_log, priced: list[str], failures: dict[str, list[str]]):
    """A `yf.download` stand-in: frames for `priced`, then yfinance's summary,
    on the thread that called it, in the shape yfinance 1.7 prints it."""
    idx = pd.date_range("2026-01-05", periods=2, name="Date")

    def download(symbols, **kwargs):
        frame = pd.concat(
            {s: pd.DataFrame({"Close": [1.0, 2.0]}, index=idx) for s in priced},
            axis=1,
        )
        yf_log.error("\n%.f Failed downloads:", sum(map(len, failures.values())))
        for reason, syms in failures.items():
            yf_log.error(f"{syms}: " + reason)
        return frame

    return download


def test_a_disowned_symbol_is_told_apart_from_a_refused_one(monkeypatch, yf_log):
    # yfinance upper-cases the symbol it reports; the verdict is on the symbol
    # asked, and the caller reads it back under the code it holds.
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {"BSD2": "bsd2.de"})
    monkeypatch.setattr(
        fetch.yf,
        "download",
        _bulk(yf_log, ["AAPL"], {DISOWNED: ["SIE", "BSD2.DE"], REFUSED: ["NVDA"]}),
    )
    out = fetch.fetch_many(["AAPL", "SIE", "BSD2", "NVDA"])
    assert list(out) == ["AAPL"]
    assert fetch.unlisted(["AAPL", "SIE", "BSD2", "NVDA"]) == {"SIE", "BSD2"}
    assert fetch.throttle_remaining() == 0  # a refused name is not the breaker's


def test_only_yahoos_own_words_disown_a_symbol(monkeypatch, yf_log):
    """yfinance's own guesses — "possibly delisted; no timezone found" shows up
    under throttling too — do not count."""
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    monkeypatch.setattr(
        fetch.yf,
        "download",
        _bulk(yf_log, ["AAPL"], {"possibly delisted; no timezone found": ["SIE"]}),
    )
    fetch.fetch_many(["AAPL", "SIE"])
    assert fetch.unlisted(["SIE"]) == set()


def test_a_name_that_prices_again_stops_being_unlisted(monkeypatch, yf_log):
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    disowned = _bulk(yf_log, ["AAPL"], {DISOWNED: ["SIE"]})
    monkeypatch.setattr(fetch.yf, "download", disowned)
    fetch.fetch_many(["AAPL", "SIE"])
    assert fetch.unlisted(["SIE"]) == {"SIE"}
    monkeypatch.setattr(fetch.yf, "download", _bulk(yf_log, ["AAPL", "SIE"], {}))
    fetch.fetch_many(["AAPL", "SIE"])
    assert fetch.unlisted(["SIE"]) == set()


def test_a_verdict_on_a_code_does_not_follow_it_to_its_alias(monkeypatch, yf_log):
    """LendingClub left NYSE LC for Nasdaq HAPN: Yahoo disowned LC, and the
    week-long verdict was stored under the code. Once an alias maps LC to
    HAPN the verdict is about a symbol nobody asks for any more; keyed by
    the code it kept HAPN from being downloaded and LC read at cost (prod
    2026-11-18, after the alias deployed)."""
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    monkeypatch.setattr(fetch.yf, "download", _bulk(yf_log, ["AAPL"], {DISOWNED: ["LC"]}))
    fetch.fetch_many(["AAPL", "LC"])
    assert fetch.unlisted(["LC"]) == {"LC"}
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {"LC": "HAPN"})
    assert fetch.unlisted(["LC"]) == set()
    fetch._forget_unlisted_in_memory()  # and after a restart, read off the disk
    assert fetch.unlisted(["LC"]) == set()


def test_a_verdict_on_the_alias_target_holds_for_the_code(monkeypatch, yf_log):
    """The other way round: what Yahoo disowned is the symbol asked, so a
    code whose alias Yahoo has no line for stays disowned."""
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {"LC": "HAPN"})
    monkeypatch.setattr(
        fetch.yf, "download", _bulk(yf_log, ["AAPL"], {DISOWNED: ["HAPN"]}))
    fetch.fetch_many(["AAPL", "LC"])
    assert fetch.unlisted(["LC"]) == {"LC"}
    assert fetch.unlisted(["HAPN"]) == {"HAPN"}


def test_the_summary_is_heard_only_by_the_download_that_logged_it(yf_log):
    """Two bulk downloads run at once on a page; each must read its own."""
    mine: dict[str, str] = {}
    fetch._download_log.sink = mine
    try:
        other = threading.Thread(target=lambda: yf_log.error(f"['NVDA']: {DISOWNED}"))
        other.start()
        other.join()
        assert mine == {}
        yf_log.error(f"['sie', 'OZTA']: {DISOWNED}")
    finally:
        fetch._download_log.sink = None
    assert mine == {"SIE": DISOWNED, "OZTA": DISOWNED}


# ------------------------------------------------------- the fundamentals path
# A screen is the widest fan-out in the app, and `data.fundamentals` used to
# call yfinance raw: no memo, no breaker, five requests per company. These pin
# the three properties a sector scan depends on.


class _FakeTicker:
    """Models the two yfinance behaviours these tests turn on: each statement
    frame is memoized on the instance, and any of them can refuse once."""

    def __init__(self, symbol, log, limit_on=None):
        self.symbol = symbol
        self._log = log
        self._limit_on = limit_on
        self._refused = set()
        self._cache = {}

    def _frame(self, name):
        if name in self._cache:
            return self._cache[name]
        self._log.append(name)
        if name == self._limit_on and name not in self._refused:
            self._refused.add(name)
            raise YFRateLimitError()
        self._cache[name] = pd.DataFrame({name: [1.0]})
        return self._cache[name]

    @property
    def info(self):
        self._log.append("info")
        return {"sector": "Technology"}

    financials = property(lambda self: self._frame("financials"))
    quarterly_financials = property(lambda self: self._frame("quarterly"))
    balance_sheet = property(lambda self: self._frame("balance"))
    cashflow = property(lambda self: self._frame("cashflow"))


@pytest.fixture
def yahoo(monkeypatch):
    """One fake Yahoo behind every `yf.Ticker`.

    `fetch.info` and `fetch_fundamentals` build one each, and `fetch.yf` is the
    same module object as `fundamentals.yf` — so this is one patch, not two.
    The profile memo is stubbed out because it is a real file on disk.
    """
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    monkeypatch.setattr(fetch.profiles, "remember", lambda *a, **k: None)
    # The ladder's rungs, without its real back-off between them.
    monkeypatch.setattr(fetch, "retry", functools.partial(fetch.retry, base_delay=0))
    fetch.clear_info_cache()
    seen = {"log": [], "built": [], "limit_on": None}

    def factory(symbol):
        seen["built"].append(symbol)
        return _FakeTicker(symbol, seen["log"], seen["limit_on"])

    monkeypatch.setattr(fetch.yf, "Ticker", factory)
    yield seen
    fetch.clear_info_cache()


def test_a_cooling_off_host_is_not_asked_for_fundamentals(yahoo):
    from stocks.data.fundamentals import fetch_fundamentals

    fetch.trip_throttle()
    with pytest.raises(YFRateLimitError):
        fetch_fundamentals("AAPL")
    assert yahoo["built"] == []  # refused before the first round trip


def test_fundamentals_share_the_info_memo(yahoo):
    """Two passes over one name in a render must not buy `.info` twice."""
    from stocks.data.fundamentals import fetch_fundamentals

    first = fetch_fundamentals("AAPL")
    second = fetch_fundamentals("AAPL")
    assert yahoo["log"].count("info") == 1
    assert first.info == second.info == {"sector": "Technology"}
    assert first.ticker == "AAPL"  # what the caller asked for, not the alias


def test_a_refused_statement_retries_only_that_frame(yahoo):
    """One ladder for the four frames, and the Ticker is built outside it — so
    a 429 on the last frame must not re-buy the three that already landed."""
    from stocks.data.fundamentals import fetch_fundamentals

    yahoo["limit_on"] = "cashflow"
    raw = fetch_fundamentals("NVDA")
    assert yahoo["log"] == [
        "info",
        "financials", "quarterly", "balance", "cashflow",  # the refused pass
        "cashflow",                                        # ...and just the retry
    ]
    # Two Tickers per call — one inside fetch.info, one for the statements —
    # and the retry adds no third.
    assert yahoo["built"] == ["NVDA", "NVDA"]
    assert not raw.cashflow.empty
    assert fetch.throttle_remaining() == 0  # one transient limit is not a burn


# --------------------------------------------- side errands keep their cool
def test_a_refused_crypto_fallback_does_not_open_the_cooldown(monkeypatch):
    """A meme coin missing from the main download goes to its USD pair. That
    errand being refused must not blank the whole book for five minutes."""
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    idx = pd.date_range("2026-01-05", periods=2, name="Date")
    asked: list[list[str]] = []

    def download(symbols, **kwargs):
        asked.append(list(symbols))
        if symbols == ["METIS-USD"]:
            raise YFRateLimitError()
        return pd.concat(
            {"AAPL": pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)}, axis=1
        )

    monkeypatch.setattr(fetch.yf, "download", download)
    out = fetch.fetch_many(["AAPL", "METIS-EUR"])
    assert list(out) == ["AAPL"]
    assert asked.count(["METIS-USD"]) == 1  # one attempt, no backoff ladder
    assert fetch.throttle_remaining() == 0


def test_retry_without_trip_raises_but_leaves_the_breaker_shut():
    def refused():
        raise YFRateLimitError()

    with pytest.raises(YFRateLimitError):
        fetch.retry(refused, attempts=1, trip=False)
    assert fetch.throttle_remaining() == 0
    with pytest.raises(YFRateLimitError):
        fetch.retry(refused, attempts=1)
    assert fetch.throttle_remaining() > 0


# ------------------------------------------------------------- retired lines
# A broker keeps the line a restructuring cancelled under its code plus ".OLD"
# (WOLF.OLD). Yahoo answers ANY symbol ending in ".OLD" with a 429 — not a
# 404 — so asking for one opened the cooldown and blanked a whole book for five
# minutes (prod 2026-10-16, twice). They are never asked.


class _NoYahoo:
    """A `yf.Ticker` that answers every symbol the way Yahoo answers WOLF.OLD."""

    asked: list[str] = []

    def __init__(self, symbol):
        _NoYahoo.asked.append(symbol)

    def __getattr__(self, name):
        raise YFRateLimitError()


@pytest.fixture
def no_yahoo(monkeypatch):
    _NoYahoo.asked = []
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {"WOLFX": "WOLF.OLD"})
    monkeypatch.setattr(fetch.yf, "Ticker", _NoYahoo)
    return _NoYahoo.asked


@pytest.mark.parametrize("ticker", ["WOLF.OLD", "wolf.old", "WOLFX"])
def test_a_retired_line_is_not_asked_for_its_dividends(no_yahoo, ticker):
    from stocks.data import dividends

    dividends.clear_history_cache()
    assert dividends.fetch_history(ticker).payments == ()
    assert dividends.fetch_ex_dividend(ticker) == (None, None, None)
    assert no_yahoo == []
    assert fetch.throttle_remaining() == 0


def test_a_retired_line_is_not_asked_one_symbol_at_a_time(no_yahoo):
    assert fetch.info("WOLF.OLD") == {}
    assert fetch.splits("WOLF.OLD") == []
    assert fetch.close_on("WOLF.OLD", "2026-10-01") is None
    assert fetch.fetch_history("WOLF.OLD").empty
    with pytest.raises(ValueError):
        fetch.latest_price("WOLF.OLD")
    assert no_yahoo == []
    assert fetch.throttle_remaining() == 0


def test_a_retired_line_stays_out_of_the_bulk_download(monkeypatch):
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    asked = []
    idx = pd.date_range("2026-01-05", periods=2, name="Date")

    def download(symbols, **kwargs):
        asked.extend(symbols)
        return pd.concat({s: pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)
                          for s in symbols}, axis=1)

    monkeypatch.setattr(fetch.yf, "download", download)
    assert list(fetch.fetch_many(["AAPL", "WOLF.OLD"])) == ["AAPL"]
    assert asked == ["AAPL"]
    assert fetch.fetch_many(["WOLF.OLD"]) == {}
    # Unlisted, so a gutted-download check does not count it as refused.
    assert fetch.unlisted(["AAPL", "WOLF.OLD"]) == {"WOLF.OLD"}


def test_only_the_exact_suffix_is_retired():
    assert fetch.retired("WOLF.OLD") and fetch.retired("zzzz.old")
    assert not any(map(fetch.retired, ["WOLF.NEW", "FOO-OLD", "XX.OLD2", "OLD"]))


# ---------------------------------------------- a blank answer is not an answer
class _BlankYahoo:
    """yfinance on a refusal it does not raise for (a 401 crumb, an empty
    body): it logs, and hands back no bars at all."""

    asked: list[str] = []

    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, **kwargs):
        _BlankYahoo.asked.append(self.symbol)
        return pd.DataFrame()


@pytest.fixture
def blank_yahoo(monkeypatch):
    _BlankYahoo.asked = []
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    monkeypatch.setattr(fetch.yf, "Ticker", _BlankYahoo)
    # The probe after a blank (`_disowned`) is a bulk download; this one says
    # nothing, as a Yahoo that is not answering says nothing.
    monkeypatch.setattr(fetch.yf, "download", lambda symbols, **kw: pd.DataFrame())
    monkeypatch.setattr(fetch, "_splits_memo", {})
    monkeypatch.setattr(fetch, "_close_memo", {})
    return _BlankYahoo.asked


def test_a_blank_split_answer_is_asked_again_and_counted(blank_yahoo):
    """ERR-05 (triage 2026-10-24): a listed name always has bars, so none at
    all is Yahoo not answering. Memoized as "no splits", it hid BYND's 1:30
    from the warm's sweep, which then stamped the book for a week."""
    before = fetch.unanswered()
    assert fetch.splits("BYND") == []
    assert fetch.splits("BYND") == []
    assert blank_yahoo == ["BYND", "BYND"]
    assert fetch.unanswered() == before + 2


def test_a_disowned_name_is_not_asked_for_its_splits(blank_yahoo, monkeypatch):
    """ERR-04 (triage 2026-11-05): each blank counted, so the warm's sweep
    never stamped a book holding ORGN and asked for it on every tick."""
    monkeypatch.setattr(fetch, "_unlisted", {"ORGN": time.time()})
    monkeypatch.setattr(fetch, "_unlisted_loaded", True)
    before = fetch.unanswered()
    assert fetch.splits("ORGN") == []
    assert blank_yahoo == []
    assert fetch.unanswered() == before


def _disowning(yf_log, probed: list):
    """A `yf.download` that prices nothing and says, in Yahoo's own words,
    it has no such symbol."""

    def download(symbols, **kwargs):
        probed.append(symbols)
        yf_log.error("\n%.f Failed downloads:", len(symbols))
        yf_log.error(f"{[s.upper() for s in symbols]}: " + DISOWNED)
        return pd.DataFrame()

    return download


def test_a_blank_yahoo_disowns_is_an_answer(blank_yahoo, monkeypatch, yf_log):
    """Prod 2026-11-04 → 11-17: ORGN, TWTR and bare German codes sold out
    long ago are in no price download, so nothing ever marked them unlisted.
    Each blank was counted, the sweep never stamped those books, and every
    warm tick asked Yahoo for all their names again. Asked the way a bulk
    download asks, Yahoo says it has no such symbol: that is the answer."""
    probed: list = []
    monkeypatch.setattr(fetch.yf, "download", _disowning(yf_log, probed))
    before = fetch.unanswered()
    assert fetch.splits("ORGN") == []
    assert fetch.unlisted(["ORGN"]) == {"ORGN"}
    assert fetch.splits("ORGN") == []
    assert blank_yahoo == ["ORGN"]  # the second call never reaches Yahoo
    assert probed == [["ORGN"]]
    assert fetch.close_on("ORGN", "2026-08-04") is None
    assert blank_yahoo == ["ORGN"]
    assert fetch.unanswered() == before


def test_a_disowned_bare_code_leaves_its_line_alone(blank_yahoo, monkeypatch, yf_log):
    """The verdict is on the code as asked: a bare IUSA Yahoo disowns says
    nothing about IUSA.DE, the line a EUR book holds it on."""
    monkeypatch.setattr(fetch.yf, "download", _disowning(yf_log, []))
    assert fetch.splits("IUSA") == []
    assert fetch.unlisted(["IUSA", "IUSA.DE"]) == {"IUSA"}


def test_a_throttled_moment_does_not_use_the_probe_up(blank_yahoo, monkeypatch, yf_log):
    probed: list = []
    monkeypatch.setattr(fetch.yf, "download", _disowning(yf_log, probed))
    # Open when the blank lands (between the bars and the probe), then shut.
    waits = iter([0.0, 30.0])
    monkeypatch.setattr(fetch, "throttle_remaining", lambda: next(waits, 0.0))
    before = fetch.unanswered()
    assert fetch.splits("ORGN") == []
    assert probed == []
    assert fetch.unanswered() == before + 1
    assert fetch.splits("ORGN") == []
    assert probed == [["ORGN"]]
    assert fetch.unlisted(["ORGN"]) == {"ORGN"}


def test_a_probe_that_fails_is_not_a_verdict(blank_yahoo, monkeypatch):
    def broken(symbols, **kwargs):
        raise RuntimeError("socket closed")

    monkeypatch.setattr(fetch.yf, "download", broken)
    before = fetch.unanswered()
    assert fetch.splits("ORGN") == []
    assert fetch.unlisted(["ORGN"]) == set()
    assert fetch.unanswered() == before + 1


def test_a_disowned_close_is_an_answer(blank_yahoo, monkeypatch, yf_log):
    probed: list = []
    monkeypatch.setattr(fetch.yf, "download", _disowning(yf_log, probed))
    before = fetch.unanswered()
    assert fetch.close_on("MIMI", "2026-08-04") is None
    assert fetch.unlisted(["MIMI"]) == {"MIMI"}
    assert fetch.unanswered() == before


def test_a_silent_blank_is_probed_once_a_day(blank_yahoo, monkeypatch):
    """A Yahoo blanking every name is weather: the probe is not repeated on
    each lookup, and the blank still holds the sweep's stamp back."""
    probed: list = []

    def silent(symbols, **kwargs):
        probed.append(symbols)
        return pd.DataFrame()

    monkeypatch.setattr(fetch.yf, "download", silent)
    before = fetch.unanswered()
    for _ in range(3):
        assert fetch.splits("BYND") == []
    assert probed == [["BYND"]]
    assert fetch.unanswered() == before + 3


def test_a_blank_close_is_asked_again_and_counted(blank_yahoo):
    before = fetch.unanswered()
    assert fetch.close_on("BYND", "2026-08-04") is None
    assert fetch.close_on("BYND", "2026-08-04") is None
    assert blank_yahoo == ["BYND", "BYND"]
    assert fetch.unanswered() == before + 2


def test_splits_are_read_off_the_bars(monkeypatch):
    idx = pd.to_datetime(["2026-08-13", "2026-08-14", "2026-08-15"])
    bars = pd.DataFrame(
        {"Close": [0.41, 13.47, 14.0], "Stock Splits": [0.0, 1 / 30, 0.0]},
        index=idx,
    )

    class _Yahoo:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            return bars

    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    monkeypatch.setattr(fetch.yf, "Ticker", _Yahoo)
    monkeypatch.setattr(fetch, "_splits_memo", {})
    before = fetch.unanswered()
    assert fetch.splits("BYND") == [("2026-08-14", pytest.approx(1 / 30))]
    assert fetch.unanswered() == before


def test_an_unplaced_isin_is_not_sent_to_yahoo(blank_yahoo, monkeypatch):
    """Prod 10-30→11-03, ×12: yfinance runs its own ISIN search for an
    ISIN-shaped symbol and raises "Invalid ISIN number" when that finds
    nothing. A label `resolve` could not place is no symbol to ask about,
    and asking again changes nothing, so it does not hold the split sweep's
    stamp back either: that re-asked Yahoo for every other name each warm."""
    from stocks.data import dividends

    monkeypatch.setattr(fetch, "code_symbol", lambda key: None)
    monkeypatch.setattr(fetch, "cached_isin_symbol", lambda key: None)
    dividends.clear_history_cache()
    before = fetch.unanswered()
    assert fetch.splits("US9344231041") == []
    assert dividends.fetch_history("US9344231041").payments == ()
    assert blank_yahoo == []
    assert fetch.unanswered() == before


def test_range_on_is_the_bar_close_on_read_and_never_a_request(monkeypatch):
    """The split check judges a wild day's fill against the bar's low and
    high (portfolio.corporate): the same download as the close, kept beside
    it, and nothing when the close was never asked."""
    asked: list[str] = []

    class _Bars:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            asked.append(self.symbol)
            index = pd.DatetimeIndex(["2025-10-21", "2025-10-22"])
            return pd.DataFrame(
                {"Low": [40.0, 70.0], "High": [50.0, 220.0], "Close": [45.0, 100.0]},
                index=index,
            )

    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    monkeypatch.setattr(fetch.yf, "Ticker", _Bars)
    monkeypatch.setattr(fetch, "_close_memo", {})
    monkeypatch.setattr(fetch, "_range_memo", {})
    assert fetch.range_on("XYZ", "2025-10-22") is None
    assert fetch.close_on("XYZ", "2025-10-22") == 100.0
    assert fetch.range_on("XYZ", "2025-10-22") == (70.0, 220.0)
    assert asked == ["XYZ"]
