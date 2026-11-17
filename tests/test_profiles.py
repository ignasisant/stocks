"""The profile memo against Yahoo's quote-only answers.

A throttled Yahoo hands back the quote without the company's profile: a
quoteType, a price and a P/E, no sector and no industry. The review engine
picks its lens and its discount by the industry, so the ticker page valued
Adobe as a business nothing threatens while the sector map, read from a whole
answer, priced what AI can copy.
"""

import json

import pytest

from stocks.analysis import review
from stocks.data import fetch, profiles

WHOLE = {
    "quoteType": "EQUITY",
    "longName": "Adobe Inc.",
    "currency": "USD",
    "sector": "Technology",
    "industry": "Software - Application",
    "country": "United States",
    "forwardPE": 9.0,
}
QUOTE_ONLY = {
    "quoteType": "EQUITY",
    "longName": "Adobe Inc.",
    "currency": "USD",
    "forwardPE": 9.0,
}


@pytest.fixture
def memo(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILE_CACHE", tmp_path / "profiles.json")
    profiles.clear()
    yield tmp_path / "profiles.json"
    profiles.clear()


def test_a_quote_only_answer_does_not_forget_the_industry(memo):
    profiles.remember("ADBE", WHOLE)
    profiles.remember("ADBE", QUOTE_ONLY)
    assert profiles.known("ADBE")["industry"] == "Software - Application"
    assert json.loads(memo.read_text())["ADBE"]["sector"] == "Technology"


def test_a_new_industry_replaces_the_old_one(memo):
    profiles.remember("ADBE", WHOLE)
    profiles.remember("ADBE", {**WHOLE, "industry": "Software - Infrastructure"})
    assert profiles.known("ADBE")["industry"] == "Software - Infrastructure"


def test_fill_gives_a_quote_only_answer_its_known_industry(memo):
    profiles.remember("ADBE", WHOLE)
    filled = profiles.fill("ADBE", QUOTE_ONLY)
    assert filled["industry"] == "Software - Application"
    assert filled["sector"] == "Technology"
    assert filled["country"] == "United States"
    assert "industry" not in QUOTE_ONLY  # the caller's blob is not edited


def test_fill_leaves_a_whole_answer_and_an_unknown_name_alone(memo):
    profiles.remember("ADBE", WHOLE)
    moved = {**WHOLE, "industry": "Software - Infrastructure"}
    assert profiles.fill("ADBE", moved) is moved
    assert profiles.fill("NEVERSEEN", QUOTE_ONLY) is QUOTE_ONLY
    assert profiles.fill("ADBE", {}) == {}


def test_info_keeps_the_industry_through_a_throttled_answer(memo, monkeypatch):
    answers = iter([WHOLE, QUOTE_ONLY])

    class Ticker:
        def __init__(self, symbol):
            self.info = dict(next(answers))

    monkeypatch.setattr(fetch.yf, "Ticker", Ticker)
    monkeypatch.setattr(fetch, "_info_memo", {})
    assert fetch.info("ADBE")["industry"] == "Software - Application"
    monkeypatch.setattr(fetch, "_info_memo", {})
    throttled = fetch.info("ADBE")
    assert throttled["industry"] == "Software - Application"
    # What the engine does with it: the business is still one AI can copy.
    assert review.threat({"industry": throttled["industry"]}) == review.R_AI_RISK
    assert profiles.known("ADBE")["industry"] == "Software - Application"


# ------------------------------------------------- a quote without its figures
# Prod-shaped answers (2026-11-16, local memo): seven of the 58 names in a book
# were valued off one of these two halves, and the memo held each for hours.

#: The quote endpoint alone: no summary, no profile, no figures.
BARE_QUOTE = {
    "quoteType": "EQUITY",
    "symbol": "ADBE",
    "financialCurrency": "USD",
    "marketCap": 1.5e11,
    "forwardPE": 9.0,
}
#: The summary answered too (`maxAge`, `previousClose`), the figures did not.
HALF_SUMMARY = {
    "quoteType": "EQUITY",
    "symbol": "FISV",
    "maxAge": 86400,
    "previousClose": 61.2,
    "marketCap": 3.4e10,
    "forwardPE": 7.1,
}
FIGURES = {"enterpriseValue": 1.6e11, "totalDebt": 6.6e9, "operatingMargins": 0.36}


@pytest.mark.parametrize("half", [BARE_QUOTE, HALF_SUMMARY])
def test_a_described_company_without_its_figures_is_a_quote_only_answer(half):
    from stocks.data.fundamentals import quote_only

    assert quote_only({**half, "industry": "Software - Application"})
    assert quote_only({**half, "sector": "Technology"})


@pytest.mark.parametrize(
    "blob",
    [
        {},
        {**WHOLE, **FIGURES},
        # A bank reports no enterprise value and no debt line; its margin is there.
        {**WHOLE, "industry": "Banks - Diversified", "operatingMargins": 0.41},
        # A fund and a coin have none of the three on their best day.
        {"quoteType": "ETF", "category": "Large Blend", "totalAssets": 5e11},
        {"quoteType": "CRYPTOCURRENCY", "marketCap": 1.2e12},
        # Never described: a preferred share or a fresh listing, not a throttle.
        BARE_QUOTE,
        HALF_SUMMARY,
    ],
)
def test_a_whole_answer_a_fund_and_an_undescribed_name_are_not(blob):
    from stocks.data.fundamentals import quote_only

    assert not quote_only(blob)


@pytest.fixture
def yahoo(memo, monkeypatch):
    """A Yahoo that hands out the queued `.info` answers, one per request."""
    import pandas as pd

    answers: list[dict] = []

    class Ticker:
        financials = quarterly_financials = balance_sheet = cashflow = pd.DataFrame()

        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            return dict(answers.pop(0))

    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    monkeypatch.setattr(fetch.yf, "Ticker", Ticker)
    fetch.clear_info_cache()
    fetch.clear_throttle()
    yield answers
    fetch.clear_info_cache()
    fetch.clear_throttle()


def test_a_throttled_answer_is_a_failed_fetch_not_a_valuation(yahoo):
    """Adobe's page, 2026-11-16: a quote-only answer was scored as a company
    with no industry — Add, 97 on quality, 90 on price, nothing about AI — and
    the memo kept that verdict while the sector map said otherwise."""
    from yfinance.exceptions import YFRateLimitError

    from stocks.analysis.fundamentals import compute_metrics
    from stocks.data.fundamentals import fetch_fundamentals

    yahoo += [{**WHOLE, **FIGURES}, BARE_QUOTE]
    whole = fetch_fundamentals("ADBE")
    assert review.threat(compute_metrics(whole)) == review.R_AI_RISK

    fetch.clear_info_cache()
    with pytest.raises(YFRateLimitError):
        fetch_fundamentals("ADBE")
    # The quote did answer: nothing here says Yahoo is refusing everyone.
    assert fetch.throttle_remaining() == 0


def test_a_name_yahoo_never_described_still_answers(yahoo):
    from stocks.data.fundamentals import fetch_fundamentals

    yahoo.append(BARE_QUOTE)
    assert fetch_fundamentals("NEWCO").info["forwardPE"] == 9.0


@pytest.fixture
def loaded(yahoo, monkeypatch):
    """The review's two memos over that Yahoo, on a clock the test moves."""
    from stocks import cache, loaders

    clock = [1_800_000_000.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cache.time, "time", lambda: clock[0])
    memos = (loaders.fundamentals, loaders.review_metrics)
    # Memory alone: a forced refresh would stamp the moved clock on the memo.
    for one in memos:
        one.cache_clear(expire=False)
    yield clock
    for one in memos:
        one.cache_clear(expire=False)


def test_the_review_keeps_the_last_whole_answer_through_a_throttled_one(yahoo, loaded):
    """A day on, both memos lapsed, Yahoo answers Adobe by halves: the row the
    review scores is still the whole one, and the request says it is old."""
    from stocks import cache, loaders

    yahoo += [{**WHOLE, **FIGURES}, BARE_QUOTE]
    whole = loaders.review_metrics("ADBE")
    assert review.threat(whole) == review.R_AI_RISK

    loaded[0] += 25 * 3600  # past ttl and grace of both: fetched in the request
    fetch.clear_info_cache()
    holder: dict[str, float] = {}
    token = cache.STALE.set(holder)
    try:
        row = loaders.review_metrics("ADBE")
    finally:
        cache.STALE.reset(token)
    assert not yahoo  # the half answer was asked for, and refused
    # The profile memo alone would name the industry on the half answer too:
    # what the fallback keeps is the figures it was scored on.
    assert row == whole and row["ev"] == FIGURES["enterpriseValue"]
    assert "since" in holder


def test_a_first_throttled_answer_is_no_row_at_all(yahoo, loaded, memo):
    """Nothing whole was ever kept for the name: the review gets a failed
    fetch (its row reads unrated), not figures built on half an answer."""
    from yfinance.exceptions import YFRateLimitError

    from stocks import loaders

    profiles.remember("ADBE", WHOLE)
    yahoo.append(BARE_QUOTE)
    with pytest.raises(YFRateLimitError):
        loaders.review_metrics("ADBE")
