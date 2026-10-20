"""Live quotes for whatever the message is about — the chat's market feed.

The system prompt already carries the user's own book valued live
(engine.book_snapshot), so "how is my Nvidia doing?" is grounded. Anything
*outside* the book was not: asked about a ticker they do not hold, the model
answered from training-data prices, and web snippets quote whatever day the
page was indexed. This module closes that gap — the tickers named in the
message are resolved and quoted at send time, and the figures ride on the
outgoing copy of the user turn exactly like web hits do (chat/../web/chat_web
.augment), so provider prompt caches stay warm and the stored history keeps
the user's own text.

Resolution is deliberately cheap-first: ticker-shaped tokens and the account's
own watchlist names cost nothing, and only when neither hits does one company
name go to Yahoo's search endpoint (data/symbols.py). Everything degrades to
"no quotes": an unresolvable name, a throttled Yahoo (routine on shared cloud
egress IPs) or a slow call all yield [], and the answer proceeds on the web
hits and the model's own knowledge.

The fetcher is injectable so the parsing and formatting are testable without a
network.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from stocks.formatting import bound
from stocks.portfolio import consistency

MAX_TICKERS = 3  # quotes fetched per message
LOOKUP_TIMEOUT = 8.0  # seconds for the whole quote batch
_MAX_LOOKUPS = 1  # company-name searches against Yahoo per message

# Ticker-shaped tokens as the app knows them: plain symbols (NVDA), venue
# suffixes (MIPS.ST), class shares (BRK.B), crypto pairs (BTC-EUR).
_TICKER_RE = re.compile(r"\b[A-Z]{1,5}(?:[.\-][A-Z]{1,4})?\b")

# Uppercase words that are not tickers. Without this every "ETF", "USA" or
# "OK" in a message would cost a quote lookup (and Yahoo does quote some of
# them, which is worse — wrong data, confidently formatted). Public because
# web/chat_web.py screens the same false positives when it decides, without a
# model, whether a message names a company worth searching for.
NOT_TICKERS = {
    "A", "AI", "ALL", "AND", "ANY", "API", "AT", "BE", "BUY", "BY", "CAGR",
    "CEO", "CFO", "CPI", "DCF", "DE", "DO", "EBIT", "EBITDA", "EL", "EPS",
    "ES", "ETF", "ETFS", "EU", "EUR", "EV", "FCF", "FED", "FOR", "FX", "GDP",
    "GO", "HOY", "I", "IA", "IF",
    "IN", "IPO", "IRPF", "IS", "IT", "LA", "LO", "MI", "MY", "NO", "NOT",
    "OF", "OK", "ON", "OR", "P", "PE", "PEG", "PER", "PIB", "PM", "PS", "QQQ",
    "ROE", "ROIC", "SEC", "SELL", "SI", "SP", "TAM", "TO", "TWR", "UK", "US",
    "USA", "USD", "VS", "WACC", "Y", "YES", "YOY",
}

# Capitalized runs that could be a company name ("Nvidia", "Banco Santander").
# Only consulted when nothing cheaper resolved — see `mentioned`.
_WORD = r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&.]+"
_NAME_RE = re.compile(rf"\b{_WORD}(?: {_WORD})?")
_NOT_NAMES = {
    "Que", "Qué", "Como", "Cómo", "Cuando", "Cuándo", "Donde", "Dónde", "Por",
    "Para", "Hoy", "Ayer", "Mañana", "The", "What", "When", "Where", "Why",
    "How", "Should", "Would", "Could", "Is", "Are", "Do", "Does", "My", "Mi",
    "Me", "Puedo", "Tengo", "Dame", "Give", "Tell", "Explain", "Analiza",
    "Analyze", "Compare", "Compara", "Hola", "Hi", "Hello", "Buenos",
    # Words Yahoo quotes as an alias it knows (see `spells`): "Estoy" is a
    # EURO STOXX ETF to it, "Vale" the miner.
    "Hay", "Estoy", "Vale",
}


@dataclass(frozen=True)
class Quote:
    """One live snapshot. Every field past `ticker` may be missing — Yahoo
    returns partial rows for thin listings, and half a quote still beats a
    remembered price."""

    ticker: str
    name: str = ""
    price: float | None = None
    currency: str = ""
    prev_close: float | None = None
    year_high: float | None = None
    year_low: float | None = None
    market_cap: float | None = None
    # Figures past the quote, already worded: a coin's peak, rank and the
    # market's mood from the nightly scan (`crypto_context`).
    context: str = ""

    @property
    def day_pct(self) -> float | None:
        """Today's move, or None without a close — or when the two cannot be
        one session apart (`consistency.day_move`), so the model is never
        told a name moved 9,900 % because the feed mixed its units."""
        return consistency.day_move(self.price, self.prev_close, ticker=self.ticker)

    def line(self, lang: str = "en") -> str:
        """The prompt line for this quote — figures only, no interpretation."""
        n, p = bound(lang)
        head = f"{self.ticker}" + (f" ({self.name})" if self.name else "")
        bits = []
        if self.price is not None:
            bits.append(f"last {n(self.price, 2)} {self.currency}".strip())
        if self.day_pct is not None:
            bits.append(f"today {p(self.day_pct, 2, signed=True)}")
        if self.year_low is not None and self.year_high is not None:
            bits.append(f"52w range {n(self.year_low, 2)}–{n(self.year_high, 2)}")
        if self.market_cap:
            bits.append(f"market cap {n(self.market_cap / 1e9, 1)}B")
        if self.context:
            bits.append(self.context)
        return f"- {head}: " + " | ".join(bits) if bits else f"- {head}: no data"


# ---------------------------------------------------------- ticker mentions


def watchlist_names(path: Path) -> dict[str, str]:
    """{upper name or symbol: ticker} for the account's own watchlist.

    The free half of resolution: "how is Santander doing" needs no network
    when Santander is already on the list."""
    try:
        from stocks.config import load_watchlist

        out: dict[str, str] = {}
        for h in load_watchlist(path):
            out[h.ticker.upper()] = h.ticker
            if h.name:
                out[h.name.upper()] = h.ticker
        return out
    except Exception:
        return {}


def _words(text: str) -> list[str]:
    """Lowercase, accent-free words: "Telefónica, S.A." is telefonica s a."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in folded if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", plain)


def spells(typed: str, company: str) -> bool:
    """Whether a Yahoo hit for `typed` is the company the user named.

    Yahoo's matcher answers every query with something: it completes a prefix
    and forgives a typo, so the Spanish words a capitalized sentence starts
    with come back as tickers — "Hay edge en booking?" as HAYW (Hayward),
    "Tengo" as TNON, "Quiero" as QDEL — and the answer quoted a stranger's
    price as the one asked about. A hit stands when the typed words are whole
    words of its name ("Booking" → Booking Holdings), or when they share
    nothing with it at all, which is Yahoo knowing an alias ("Google" →
    Alphabet). A name that merely begins like the typed word, or one letter
    off it, is a guess, and a guess is dropped rather than quoted.
    """
    said, name = _words(typed), _words(company)
    if not said or not name:
        return False
    n = len(said)
    if any(name[i:i + n] == said for i in range(len(name) - n + 1)):
        return True
    return not any(a[:2] == b[:2] for a in said for b in name)


def _lookup(name: str) -> str:
    """Yahoo's best symbol for a company name, or '' (throttled, unknown, or
    a hit that is not the name typed — see `spells`)."""
    try:
        from stocks.data.symbols import search_symbols

        hits = search_symbols(name, limit=1)
    except Exception:
        return ""
    if not hits:
        return ""
    symbol, company, _venue = hits[0]
    return symbol if spells(name, company) else ""


def mentioned(
    message: str,
    known: dict[str, str] | None = None,
    focus: str = "",
    lookup: Callable[[str], str] = _lookup,
) -> list[str]:
    """Tickers to quote for this message, best-effort and capped.

    Order of trust: the ticker in focus (the page the user is looking at),
    then ticker-shaped tokens, then watchlist names, then — only when nothing
    else resolved — one Yahoo name lookup, which is what makes plain "Nvidia"
    or "Telefónica" work without the user typing a symbol."""
    known = known or {}
    out: list[str] = []

    def add(tk: str) -> None:
        tk = (tk or "").strip().upper()
        if tk and tk not in out and len(out) < MAX_TICKERS:
            out.append(tk)

    upper = message.upper()
    if focus:
        # The page the user is on answers "and how does it look today?" with
        # no ticker in the message at all — the strongest signal there is.
        add(focus)
    # The regex only matches all-caps runs, so a token here is one the user
    # actually typed in caps; the stop-list keeps "ETF"/"USA"/"CEO" out.
    for tok in _TICKER_RE.findall(message):
        if tok not in NOT_TICKERS:
            add(known.get(tok, tok))
    for name, tk in known.items():
        if len(name) > 2 and name in upper:
            add(tk)
    if not out:
        for cand in _NAME_RE.findall(message)[:_MAX_LOOKUPS + 2]:
            if cand in _NOT_NAMES or cand.upper() in NOT_TICKERS:
                continue
            sym = lookup(cand)
            if sym:
                add(sym)
                break
    return out[:MAX_TICKERS]


# Where a sentence starts: its first word is capitalized by grammar, not
# because it names anything ("Quiero…", "Explícame…").
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?¿¡:;\n][\s\"'«(]*)(?=\S)")
_CALENDAR = {
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
    "Sunday", "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
}


def named(message: str) -> list[str]:
    """What `message` names, as typed — no lookup, no network.

    Ticker-shaped tokens (a crypto pair also as its coin: "SOL-EUR" is
    "SOL" too), and capitalized runs that do not merely start a sentence:
    "¿qué opinabas de Golar LNG?" names "Golar LNG" and "LNG", "Quiero
    vender" names nothing. The earlier-conversations recall (chat/memory.py
    `about`) searches for these; it is `mentioned` without the guesses that
    are fine for a quote and wrong for a memory.
    """
    out: list[str] = []
    for tok in _TICKER_RE.findall(message):
        # One letter is a word in a memory ("the S of S&P"), whatever it is
        # on an exchange.
        if tok in NOT_TICKERS or len(tok) < 2:
            continue
        out.append(tok)
        base = tok.split("-")[0]
        if base != tok and len(base) >= 2 and base not in NOT_TICKERS:
            out.append(base)
    starts = {m.end() for m in _SENTENCE_START_RE.finditer(message)}
    for m in _NAME_RE.finditer(message):
        cand = m.group(0).rstrip(".")
        if (m.start() in starts or cand in _NOT_NAMES or cand in _CALENDAR
                or cand.upper() in NOT_TICKERS):
            continue
        out.append(cand)
    return list(dict.fromkeys(out))


# ----------------------------------------------------------------- quotes


def _fetch_quote(ticker: str) -> Quote | None:
    """One live snapshot via yfinance's fast path (no `.info` scrape).

    fast_info is a single quote request; `.info` is a much heavier call that
    Yahoo throttles first, and none of its extra fields are worth adding a
    second round-trip per message."""
    try:
        import yfinance as yf

        from stocks.data.fetch import resolve

        fi = dict(yf.Ticker(resolve(ticker)).fast_info)
    except Exception:
        return None
    if not fi:
        return None

    def num(key: str) -> float | None:
        raw = fi.get(key)
        if raw is None:
            return None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
        return val if val == val else None  # val==val screens NaN

    price = num("lastPrice")
    if price is None:
        return None
    return Quote(
        ticker=ticker.upper(),
        price=price,
        currency=str(fi.get("currency") or ""),
        prev_close=num("previousClose") or num("regularMarketPreviousClose"),
        year_high=num("yearHigh"),
        year_low=num("yearLow"),
        market_cap=num("marketCap"),
    )


def quotes(
    tickers: Iterable[str],
    fetch: Callable[[str], Quote | None] = _fetch_quote,
    timeout: float = LOOKUP_TIMEOUT,
    limit: int = MAX_TICKERS,
) -> list[Quote]:
    """Live snapshots for `tickers` (the first `limit`), in order, skipping
    whatever failed.

    Fetched concurrently and behind one wall-clock budget: a throttled Yahoo
    must cost the answer a few seconds, not the whole turn. No `with` on the
    pool — shutdown would block on the hung worker the timeout just escaped."""
    names = [t for t in dict.fromkeys(t.upper() for t in tickers) if t][:limit]
    if not names:
        return []
    pool = ThreadPoolExecutor(max_workers=len(names))
    try:
        futures = [pool.submit(fetch, t) for t in names]
        out = []
        for f in futures:
            try:
                q = f.result(timeout=timeout)
            except Exception:
                continue
            if q is not None:
                out.append(q)
        return out
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# ------------------------------------------------------------------ crypto


def crypto_context(
    quote: Quote, scan: dict, market: bool = True, lang: str = "en"
) -> str:
    """A coin quote's figures from the nightly scan, worded for the prompt.

    The model's own idea of a coin's all-time high is a training-data figure,
    and so is its sense of the market's mood; both are a night old at worst
    here. Figures only, as the quote line is — the bands are the index's own
    names, not a reading. `market` adds the market-wide half (Fear & Greed,
    bitcoin dominance), which one coin per message is enough to carry.
    """
    n, p = bound(lang)
    from stocks.analysis import crypto_market as cm
    from stocks.data.crypto import COIN_CATEGORY, split_pair

    pair = split_pair(quote.ticker)
    if pair is None or not scan:
        return ""
    coin, ccy = pair
    q = ccy.lower()
    entry = (scan.get("coins") or {}).get(coin) or {}
    bits: list[str] = []
    ath = (entry.get("ath") or {}).get(q)
    drop = cm.from_peak(quote.price, ath)
    if ath and drop is not None:
        day = (entry.get("ath_date") or {}).get(q) or "?"
        high = f"{ath:,.6g}"
        if lang == "es":
            high = high.translate({ord(","): ".", ord("."): ","})
        bits.append(
            f"all-time high {high} {ccy} on {day} ({p(drop, 0, signed=True)} from it)"
        )
    if entry.get("rank"):
        bits.append(f"market-cap rank #{entry['rank']}")
    if coin in COIN_CATEGORY:
        bits.append(f"category {COIN_CATEGORY[coin].replace('_', ' ')}")
    ratio = cm.fdv_ratio(
        (entry.get("fdv") or {}).get(q), (entry.get("market_cap") or {}).get(q))
    if ratio is not None and ratio > 1.1:
        bits.append(f"fully diluted value {n(ratio, 1)}x market cap")
    if market:
        fg = scan.get("fear_greed") or []
        if fg:
            value = int(fg[-1][1])
            band = cm.fear_greed_band(value)
            bits.append(f"crypto Fear & Greed {value}/100"
                        + (f" ({band.key.replace('_', ' ')})" if band else ""))
        dom = (scan.get("global") or {}).get("btc_dominance")
        if dom is not None:
            bits.append(f"bitcoin dominance {n(dom, 1)}%")
        if scan.get("saved"):
            bits.append(f"scan of {scan['saved']}")
    return " | ".join(bits)


def _with_crypto(
    quotes_: list[Quote], scan: Callable[[], dict], lang: str = "en"
) -> list[Quote]:
    """`quotes_` with each coin's scan figures attached; the scan is only
    read when a coin is among them, and a failed read changes nothing."""
    from stocks.data.crypto import is_crypto

    if not any(is_crypto(q.ticker) for q in quotes_):
        return quotes_
    try:
        data = scan()
    except Exception:
        return quotes_
    out, first = [], True
    for q in quotes_:
        if is_crypto(q.ticker):
            context = crypto_context(q, data, market=first, lang=lang)
            first = first and not context
            q = replace(q, context=context) if context else q
        out.append(q)
    return out


def _scan() -> dict:
    from stocks.api import loaders

    return loaders.crypto_scan()


# ----------------------------------------------------------------- prompt


def augment(message: str, quotes_: list[Quote], lang: str = "en") -> str:
    """The user message with the live quotes appended (unchanged when none)."""
    if not quotes_:
        return message
    return (
        message
        + "\n\n---\nLive market data fetched for this message (these are "
        "current prices — trust them over any figure you remember, and over "
        "prices quoted in web results):\n"
        + "\n".join(q.line(lang) for q in quotes_)
    )


def lookup_for(
    message: str, watchlist: Path | None = None, focus: str = "", lang: str = "en"
) -> list[Quote]:
    """The whole path in one call: mentions → live quotes.

    The convenience entry point both chat surfaces use; every failure inside
    degrades to []."""
    try:
        known = watchlist_names(watchlist) if watchlist else {}
        return _with_crypto(quotes(mentioned(message, known, focus)), _scan, lang)
    except Exception:
        return []
