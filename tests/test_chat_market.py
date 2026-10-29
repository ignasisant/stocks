"""chat/market: ticker resolution, quote batching, prompt block."""

import pytest

from stocks.chat import market
from stocks.chat.market import Quote, augment, mentioned, named, quotes

# ------------------------------------------------------------- mentions


def _no_lookup(name):  # a network lookup would be a test bug
    raise AssertionError(f"unexpected Yahoo lookup for {name!r}")


def test_caps_tokens_are_tickers():
    assert mentioned("what do you think of NVDA?", lookup=_no_lookup) == ["NVDA"]


def test_stop_list_screens_caps_that_are_not_tickers():
    assert mentioned("is this ETF ok for my IRPF?", lookup=lambda n: "") == []


def test_an_ampersand_initialism_is_not_a_ticker():
    # "S&P" once quoted Sirius XM ("S") under a question about the index.
    assert mentioned("¿Bato al S&P 500 este año?", lookup=_no_lookup) == ["^GSPC"]
    assert mentioned("¿bato al S & P?", lookup=_no_lookup) == ["^GSPC"]
    assert mentioned("compara NVDA con el SP500", lookup=_no_lookup) == [
        "^GSPC", "NVDA"
    ]
    assert mentioned("el R&D y el M&A de MSFT", lookup=_no_lookup) == ["MSFT"]


def test_ampersand_names_that_trade_resolve_to_their_symbol():
    assert mentioned("¿y AT&T?", lookup=_no_lookup) == ["T"]
    assert mentioned("P&G o J&J", lookup=_no_lookup) == ["PG", "JNJ"]
    assert named("¿qué tal el S&P 500?") == ["S&P"]


def test_watchlist_names_resolve_without_a_lookup():
    known = {"SAN.MC": "SAN.MC", "BANCO SANTANDER": "SAN.MC"}
    assert mentioned("cómo va Banco Santander?", known, lookup=_no_lookup) == [
        "SAN.MC"
    ]


def test_focus_ticker_answers_a_message_with_no_ticker_in_it():
    assert mentioned("y hoy cómo va?", focus="ASML", lookup=_no_lookup) == ["ASML"]


def test_the_page_in_focus_is_quoted_only_when_the_message_points_at_it(monkeypatch):
    # "¿qué es el ROIC?" asked on the BKNG page quoted BKNG, and every answer
    # on that page leaned towards it.
    asked = []
    monkeypatch.setattr(market, "quotes", lambda tickers: asked.append(tickers) or [])
    monkeypatch.setattr(market, "_lookup", lambda _name: "")
    for message in ("¿qué es el ROIC?",
                    "¿Cuánta exposición tengo por país? Dame % y euros.",
                    "¿Cuánto rinde el S&P 500 este año?",
                    "¿A qué PER cotiza META?"):
        market.lookup_for(message, focus="BKNG")
    for message in ("y hoy cómo va?", "is it cheap?", "¿la compro?",
                    "compara esta con AMD"):
        market.lookup_for(message, focus="BKNG")
    assert asked == [[], [], ["^GSPC"], ["META"],
                     ["BKNG"], ["BKNG"], ["BKNG"], ["BKNG", "AMD"]]


def test_unknown_company_name_falls_back_to_one_lookup():
    seen = []

    def lookup(name):
        seen.append(name)
        return "NVDA" if name == "Nvidia" else ""

    assert mentioned("qué tal Nvidia últimamente?", lookup=lookup) == ["NVDA"]
    assert seen == ["Nvidia"]


def test_an_imperative_that_opens_the_message_is_not_a_company():
    """"Mira premarket" quoted MIRA: the verb went to Yahoo as a name."""
    for verb in ("Mira", "Revisa", "Dime", "Busca", "Check", "Look", "Show"):
        assert mentioned(f"{verb} premarket", lookup=_no_lookup) == [], verb


def test_a_name_after_an_opening_word_is_looked_up_on_its_own():
    seen = []

    def lookup(name):
        seen.append(name)
        return "NOW" if name == "ServiceNow" else ""

    assert mentioned("Resultados ServiceNow de hoy.", lookup=lookup) == ["NOW"]
    assert seen == ["ServiceNow"]


def test_a_held_name_matches_as_it_is_said_not_only_as_filed():
    """The watchlist files "ServiceNow, Inc."; nobody types the suffix."""
    known = {"NOW": "NOW", "SERVICENOW, INC.": "NOW",
             "BANCO SANTANDER, S.A.": "SAN.MC", "VALE S.A.": "VALE"}
    assert mentioned("Resultados ServiceNow de hoy.", known,
                     lookup=_no_lookup) == ["NOW"]
    assert mentioned("cómo va banco santander", known,
                     lookup=_no_lookup) == ["SAN.MC"]
    # A short form that is also a word of the language stays a word.
    assert mentioned("vale, gracias", known, lookup=lambda n: "") == []
    # A word inside another is not the name or the symbol.
    assert mentioned("servicenowhere", known, lookup=lambda n: "") == []
    assert mentioned("ya lo sé, i know", known, lookup=lambda n: "") == []


def test_a_hit_that_only_starts_like_the_word_is_not_quoted(monkeypatch):
    # "Hay edge en booking?" was quoted as HAYW: Yahoo completes any prefix.
    hits = {
        "Hay": ("HAYW", "Hayward Holdings, Inc."),
        "Tengo": ("TNON", "Tenon Medical, Inc."),
        "Cuantas": ("CUEN", "Cuentas Inc."),
        "Booking": ("BKNG", "Booking Holdings Inc."),
    }
    monkeypatch.setattr(
        "stocks.data.symbols.search_symbols",
        lambda q, limit=6: [(*hits[q], "NASDAQ")] if q in hits else [],
    )
    assert market._lookup("Tengo") == ""
    assert market._lookup("Cuantas") == ""
    assert mentioned("Hay edge en Booking?") == ["BKNG"]


def test_a_name_typed_whole_or_an_alias_yahoo_knows_resolves():
    assert market.spells("Booking", "Booking Holdings Inc.")
    assert market.spells("telefonica", "Telefónica, S.A.")
    assert market.spells("Coca Cola", "The Coca-Cola Company")
    assert market.spells("Google", "Alphabet Inc.")
    assert not market.spells("Hay", "Hayward Holdings, Inc.")
    assert not market.spells("Quiero", "QuidelOrtho Corporation")
    assert not market.spells("Analiza Tat", "Taiwan Semiconductor Manufacturing")


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
    assert "day +0.81%" in line and "today" not in line
    assert "52w range 164.07–236.54" in line
    assert "market cap 5,500.0B" in line


def test_partial_quotes_still_render():
    assert Quote("XYZ", price=3.0).line() == "- XYZ: last 3.00"
    assert Quote("XYZ").line() == "- XYZ: no data"


def test_day_pct_needs_a_previous_close():
    assert Quote("XYZ", price=3.0).day_pct is None
    assert Quote("XYZ", price=3.0, prev_close=0).day_pct is None


def test_day_pct_drops_a_move_no_session_produces():
    """A close in pence against a price in pounds is the feed's slip, not a
    +9,900 % day the model should be told about; the price itself stays."""
    pence = Quote("VOD.L", price=12.5, prev_close=1250.0)
    assert pence.day_pct is None
    assert pence.line() == "- VOD.L: last 12.50"
    assert Quote("XYZ", price=6.0, prev_close=3.0).day_pct == pytest.approx(1.0)


def test_a_quote_says_which_session_its_move_belongs_to():
    regular = Quote("NOW", price=150.13, currency="USD", prev_close=154.78,
                    as_of="2026-10-28")
    assert "last 150.13 USD | session 2026-10-28 -3.00%" in regular.line()
    pre = Quote("NOW", price=123.42, currency="USD", prev_close=150.13,
                session="pre", as_of="2026-10-29", close=150.13)
    line = pre.line()
    assert "premarket 123.42 USD" in line
    assert "2026-10-29 -17.79% vs the last close 150.13" in line
    post = Quote("NOW", price=126.0, currency="USD", prev_close=154.78,
                 session="post", as_of="2026-10-28", close=150.13)
    line = post.line()
    assert "after-hours 126.00 USD" in line
    assert "session 2026-10-28 incl. after-hours -18.59%" in line
    assert "regular close 150.13" in line


def test_a_quote_is_read_off_the_session_snapshot(monkeypatch):
    """The chat's quote is the app's: premarket and after-hours included,
    and dated, where yfinance's fast_info only had the regular session."""
    from stocks.data import quotes as live

    row = {"symbol": "NOW", "marketState": "PRE", "currency": "USD",
           "shortName": "ServiceNow, Inc.", "regularMarketPrice": 150.13,
           "regularMarketPreviousClose": 154.78, "preMarketPrice": 123.42,
           "fiftyTwoWeekHigh": 239.6, "fiftyTwoWeekLow": 120.1,
           "marketCap": 1.55e11}
    monkeypatch.setattr(live, "quote", lambda t, **kw: row)
    q = market._fetch_quote("NOW")
    assert (q.price, q.prev_close, q.session, q.close) == (123.42, 150.13, "pre", 150.13)
    assert q.name == "ServiceNow, Inc." and q.market_cap == 1.55e11
    assert q.day_pct == pytest.approx(123.42 / 150.13 - 1)
    assert (q.year_low, q.year_high) == (120.1, 239.6) and q.as_of


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


# ------------------------------------------------------------------ unlisted


def _yahoo(rows=(), asked=True):
    seen = []

    def search(q):
        seen.append(q)
        return list(rows), asked

    return search, seen


def test_a_symbol_yahoo_lists_nothing_under_is_named_with_its_near_matches():
    search, _ = _yahoo([("ZQ", "Zymeworks Quasi")])
    got = market.unlisted("¿qué opinas de ZXQW?", search=search)
    assert got == {"ZXQW": [("ZQ", "Zymeworks Quasi")]}
    block = market.unlisted_block(got)
    assert "ZXQW: no security listed under it" in block
    assert "ZQ (Zymeworks Quasi)" in block


@pytest.mark.parametrize(("typed", "listed"), [
    ("NVDA", "NVDA"),
    ("SAP.DE", "SAP.DE"),
    ("BRK.B", "BRK-B"),
    ("SOL", "SOL-USD"),
    ("IBE", "IBE.MC"),
])
def test_a_symbol_yahoo_lists_is_real(typed, listed):
    search, _ = _yahoo([(listed, "Some Co")])
    assert market.unlisted(f"¿qué tal {typed}?", search=search) == {}


def test_nothing_is_called_made_up_when_yahoo_could_not_be_asked():
    search, _ = _yahoo(asked=False)
    assert market.unlisted("¿qué opinas de ZXQW?", search=search) == {}


def test_one_real_symbol_beside_it_keeps_the_research():
    def search(q):
        return ([("NVDA", "NVIDIA")] if q == "NVDA" else []), True

    assert market.unlisted("compara ZXQW con NVDA", search=search) == {}


def test_a_watched_held_or_short_symbol_is_never_searched():
    search, seen = _yahoo()
    assert market.unlisted("¿y QQQX?", {"MI FONDO": "QQQX"}, search=search) == {}
    assert market.unlisted("¿y XYZW.OLD?", held="- XYZW.OLD: 10 shares",
                           search=search) == {}
    assert market.unlisted("¿y GE?", search=search) == {}
    assert market.unlisted("¿qué tal la bolsa hoy?", search=search) == {}
    assert seen == []
