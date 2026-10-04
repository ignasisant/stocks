"""chat/market: ticker resolution, quote batching, prompt block."""

from stocks.chat import market
from stocks.chat.market import Quote, augment, mentioned, named, quotes

# ------------------------------------------------------------- mentions


def _no_lookup(name):  # a network lookup would be a test bug
    raise AssertionError(f"unexpected Yahoo lookup for {name!r}")


def test_caps_tokens_are_tickers():
    assert mentioned("what do you think of NVDA?", lookup=_no_lookup) == ["NVDA"]


def test_stop_list_screens_caps_that_are_not_tickers():
    assert mentioned("is this ETF ok for my IRPF?", lookup=lambda n: "") == []


def test_watchlist_names_resolve_without_a_lookup():
    known = {"SAN.MC": "SAN.MC", "BANCO SANTANDER": "SAN.MC"}
    assert mentioned("cómo va Banco Santander?", known, lookup=_no_lookup) == [
        "SAN.MC"
    ]


def test_focus_ticker_answers_a_message_with_no_ticker_in_it():
    assert mentioned("y hoy cómo va?", focus="ASML", lookup=_no_lookup) == ["ASML"]


def test_unknown_company_name_falls_back_to_one_lookup():
    seen = []

    def lookup(name):
        seen.append(name)
        return "NVDA" if name == "Nvidia" else ""

    assert mentioned("qué tal Nvidia últimamente?", lookup=lookup) == ["NVDA"]
    assert seen == ["Nvidia"]


def test_lookup_is_skipped_when_something_cheaper_matched():
    assert mentioned("NVDA vs Nvidia", lookup=_no_lookup) == ["NVDA"]


def test_mentions_are_deduped_and_capped():
    msg = "compare AAPL, MSFT, GOOG, AMZN and META"
    assert len(mentioned(msg, lookup=_no_lookup)) == market.MAX_TICKERS


# ------------------------------------------------------------------ names


def test_named_is_the_tickers_and_the_names_as_typed():
    assert named("¿qué opinabas de Golar LNG?") == ["LNG", "Golar LNG"]


def test_a_word_capitalized_only_because_it_starts_a_sentence_names_nothing():
    assert named("Quiero vender") == []
    assert named("Vale. Entonces compro") == []


def test_a_crypto_pair_also_names_its_coin():
    assert named("¿vendo mi SOL-EUR?") == ["SOL-EUR", "SOL"]


def test_stop_words_and_single_letters_are_not_names():
    # One letter is a word in a memory, whatever it is on an exchange.
    assert named("¿compro el ETF de V en USD?") == []


def test_a_name_with_punctuation_in_it_is_kept_whole():
    assert named("¿cómo va el S&P hoy?") == ["S&P"]


def test_a_month_is_not_a_company():
    assert named("what happened in October with Nvidia") == ["Nvidia"]


def test_named_never_looks_anything_up():
    # Unlike `mentioned`, which may ask Yahoo; a memory search must not.
    assert named("how is nvidia doing") == []


# --------------------------------------------------------------- quotes


def test_quotes_skip_failures_and_keep_order():
    def fetch(ticker):
        if ticker == "BAD":
            raise RuntimeError("Yahoo throttled us")
        return Quote(ticker, price=1.0)

    got = quotes(["NVDA", "BAD", "ASML"], fetch=fetch)
    assert [q.ticker for q in got] == ["NVDA", "ASML"]


def test_quotes_skip_unquotable_symbols():
    got = quotes(["NOPE"], fetch=lambda t: None)
    assert got == []


def test_quotes_dedupe_and_cap():
    seen = []

    def fetch(ticker):
        seen.append(ticker)
        return Quote(ticker, price=1.0)

    quotes(["nvda", "NVDA", "a", "b", "c", "d"], fetch=fetch)
    assert seen == ["NVDA", "A", "B"][: market.MAX_TICKERS]


def test_quotes_without_tickers_skip_the_pool():
    assert quotes([], fetch=_no_lookup) == []


# --------------------------------------------------------------- prompt


def _quote():
    return Quote("NVDA", name="NVIDIA", price=227.98, currency="USD",
                 prev_close=226.15, year_high=236.54, year_low=164.07,
                 market_cap=5.5e12)


def test_line_carries_the_figures():
    line = _quote().line()
    assert "NVDA (NVIDIA)" in line
    assert "last 227.98 USD" in line
    assert "today +0.81%" in line
    assert "52w range 164.07–236.54" in line
    assert "market cap 5,500.0B" in line


def test_partial_quotes_still_render():
    assert Quote("XYZ", price=3.0).line() == "- XYZ: last 3.00"
    assert Quote("XYZ").line() == "- XYZ: no data"


def test_day_pct_needs_a_previous_close():
    assert Quote("XYZ", price=3.0).day_pct is None
    assert Quote("XYZ", price=3.0, prev_close=0).day_pct is None


def test_augment_appends_the_block():
    out = augment("cómo va nvidia?", [_quote()])
    assert out.startswith("cómo va nvidia?")
    assert "Live market data" in out
    assert "- NVDA (NVIDIA): last 227.98 USD" in out


def test_augment_without_quotes_is_identity():
    assert augment("hola", []) == "hola"


def test_lookup_for_swallows_failures(monkeypatch):
    monkeypatch.setattr(market, "quotes", lambda *a, **k: 1 / 0)
    assert market.lookup_for("NVDA?", None) == []


_SCAN = {
    "saved": "2026-10-04",
    "global": {"btc_dominance": 57.25},
    "fear_greed": [["2026-10-03", 40], ["2026-10-04", 72]],
    "coins": {
        "SOL": {
            "rank": 6,
            "ath": {"eur": 250.0},
            "ath_date": {"eur": "2025-01-19"},
            "fdv": {"eur": 120e9},
            "market_cap": {"eur": 80e9},
        }
    },
}


def test_a_coin_quote_carries_its_peak_and_the_market_mood():
    from stocks.chat.market import crypto_context

    line = crypto_context(Quote("SOL-EUR", price=100.0), _SCAN)
    assert "all-time high 250 EUR on 2025-01-19 (-60% from it)" in line
    assert "rank #6" in line
    assert "smart contract" in line
    assert "fully diluted value 1.5x" in line
    assert "Fear & Greed 72/100 (greed)" in line
    assert "bitcoin dominance 57.2%" in line


def test_a_share_gets_no_crypto_context():
    from stocks.chat.market import crypto_context

    assert crypto_context(Quote("NVDA", price=100.0), _SCAN) == ""


def test_the_market_line_rides_on_one_coin_only():
    from stocks.chat.market import _with_crypto

    got = _with_crypto(
        [Quote("NVDA", price=1.0), Quote("SOL-EUR", price=100.0),
         Quote("BTC-EUR", price=1.0)],
        lambda: _SCAN,
    )
    assert got[0].context == ""
    assert "Fear & Greed" in got[1].context
    assert "Fear & Greed" not in got[2].context


def test_a_failed_scan_read_leaves_the_quotes_alone():
    from stocks.chat.market import _with_crypto

    def boom():
        raise OSError("bucket down")

    quotes_ = [Quote("SOL-EUR", price=100.0)]
    assert _with_crypto(quotes_, boom) == quotes_


def test_no_coin_means_no_scan_read():
    from stocks.chat.market import _with_crypto

    def never():
        raise AssertionError("scan read for a share")

    assert _with_crypto([Quote("NVDA", price=1.0)], never)[0].context == ""
