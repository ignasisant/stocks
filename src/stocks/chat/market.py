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

from stocks import obs
from stocks.formatting import bound
from stocks.portfolio import consistency

MAX_TICKERS = 3  # quotes fetched per message
LOOKUP_TIMEOUT = 8.0  # seconds for the whole quote batch
_MAX_LOOKUPS = 1  # company-name searches against Yahoo per message

# Ticker-shaped tokens as the app knows them: plain symbols (NVDA), venue
# suffixes (MIPS.ST), class shares (BRK.B), crypto pairs (BTC-EUR).
# A token touching "&" is a letter of an initialism ("S&P", "M&A", "R&D"), not
# a symbol: "¿bato al S&P 500?" once quoted Sirius XM ("S").
_TICKER_RE = re.compile(r"(?<![&\w])[A-Z]{1,5}(?:[.\-][A-Z]{1,4})?(?![&\w])")
# The "&" names that do stand for something to quote, as typed in caps.
_AMPERSAND = (
    (re.compile(r"\bS ?& ?P(?: ?500)?(?![&\w])|\bSP ?500\b", re.IGNORECASE), "^GSPC"),
    (re.compile(r"\bAT ?& ?T\b", re.IGNORECASE), "T"),
    (re.compile(r"\bP ?& ?G\b", re.IGNORECASE), "PG"),
    (re.compile(r"\bJ ?& ?J\b", re.IGNORECASE), "JNJ"),
)

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

# Words that point at the page on screen instead of naming a symbol: "¿y esta
# cómo va?", "is it cheap?", "¿la compro?". A question with none of them is not
# about the ticker open behind the drawer ("¿qué es el ROIC?", "¿cuánta
# exposición tengo por país?"), and quoting that ticker anyway pulled every
# answer towards it. "este año" and "esta semana" are dates, not the page.
_POINTS_RE = re.compile(
    r"\b(?:this|it|its|it's|that one|here|the (?:stock|company|share)s?"
    r"|(?:est|es)[aeo]s?(?!\s+(?:año|mes|semana|trimestre|semestre|ejercicio"
    r"|lunes|martes|miércoles|jueves|viernes|vez|momento|tipo|tema)\b)"
    r"|aquí|aquest[ae]?s?|això"
    r"|la (?:acción|empresa|compañía|ficha)|el (?:valor|ticker|título))\b",
    re.IGNORECASE,
)
# Words that ask about a price without saying whose: on the ticker's own page
# they mean that ticker, but only when the message names no other symbol
# ("¿a qué PER cotiza Meta?" is Meta's, wherever it is asked).
_PRICED_RE = re.compile(
    r"\b(?:c[oó]mo (?:va|est[aá]|lo ves|la ves)|qu[eé] tal|cotiza|compr[oa]r?"
    r"|vend[oe]r?|mantengo|mantener|refuerzo|reforzar|barat[ao]s?|car[ao]s?"
    r"|precio|price|cheap|expensive|buy|sell|hold)\b",
    re.IGNORECASE,
)

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
    # Imperatives and openers a message starts with: "Mira premarket" quoted
    # Mira Pharmaceuticals, and "Resultados ServiceNow" is no company's name.
    "Mira", "Mire", "Mirar", "Busca", "Buscar", "Revisa", "Dime", "Echa",
    "Fíjate", "Fijate", "Muestra", "Muéstrame", "Enséñame", "Quiero",
    "Resultados", "Noticias", "Look", "Check", "Show", "Find", "Results",
    "News",
}
_NOT_NAME_WORDS = frozenset(w.casefold() for w in _NOT_NAMES)


def _opened(run: str) -> tuple[str, bool]:
    """A capitalized run without the openers it starts with ("Resultados
    ServiceNow" is "ServiceNow"), and whether what is left follows one
    mid-sentence ("Vale. Entonces" starts a sentence again)."""
    words, after = run.split(" "), False
    while words and words[0].rstrip(".,") in _NOT_NAMES:
        after = not words.pop(0).endswith(".")
    return " ".join(words), after


@dataclass(frozen=True)
class Quote:
    """One live snapshot. Every field past `ticker` may be missing — Yahoo
    returns partial rows for thin listings, and half a quote still beats a
    remembered price."""

    ticker: str
    name: str = ""
    price: float | None = None
    currency: str = ""
    # The close the move is measured from: the last close for a premarket
    # price, the one before it otherwise.
    prev_close: float | None = None
    year_high: float | None = None
    year_low: float | None = None
    market_cap: float | None = None
    # Figures past the quote, already worded: a coin's peak, rank and the
    # market's mood from the nightly scan (`crypto_context`).
    context: str = ""
    # Which print `price` is — "pre", "post" or "" for the regular session —
    # and the exchange date its move belongs to (`portfolio._snapshot`). A
    # report out after the bell trades in after-hours and the next premarket,
    # and a move with no date reads as today's whatever session it was.
    session: str = ""
    as_of: str = ""
    # The regular session's close, beside an extended-hours price.
    close: float | None = None

    @property
    def day_pct(self) -> float | None:
        """The move to `price`, or None without a close — or when the two
        cannot be one session apart (`consistency.day_move`), so the model is
        never told a name moved 9,900 % because the feed mixed its units."""
        return consistency.day_move(self.price, self.prev_close, ticker=self.ticker)

    def line(self, lang: str = "en") -> str:
        """The prompt line for this quote — figures only, no interpretation."""
        n, p = bound(lang)
        head = f"{self.ticker}" + (f" ({self.name})" if self.name else "")
        bits = []
        pct = self.day_pct
        day = f" {self.as_of}" if self.as_of else ""
        if self.price is not None and self.session == "pre":
            bits.append(f"premarket {n(self.price, 2)} {self.currency}".strip())
            if pct is not None and self.prev_close:
                bits.append(f"{day.strip()} {p(pct, 2, signed=True)} vs the "
                            f"last close {n(self.prev_close, 2)}".strip())
        elif self.price is not None and self.session == "post":
            bits.append(f"after-hours {n(self.price, 2)} {self.currency}".strip())
            if pct is not None:
                bits.append(f"session{day} incl. after-hours "
                            f"{p(pct, 2, signed=True)}")
            if self.close is not None:
                bits.append(f"regular close {n(self.close, 2)}")
        else:
            if self.price is not None:
                bits.append(f"last {n(self.price, 2)} {self.currency}".strip())
            if pct is not None:
                bits.append(f"session{day} {p(pct, 2, signed=True)}" if day
                            else f"day {p(pct, 2, signed=True)}")
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


def _ampersands(message: str, add: Callable[[str], None]) -> str:
    """`add` the symbol of each "&" name and return `message` without them,
    so a spaced "S & P" leaves no "S" behind for the token scan."""
    for pattern, symbol in _AMPERSAND:
        if pattern.search(message):
            add(symbol)
            message = pattern.sub(" ", message)
    return message


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

    if focus:
        # The page the user is on answers "and how does it look today?" with
        # no ticker in the message at all — the strongest signal there is.
        add(focus)
    # The regex only matches all-caps runs, so a token here is one the user
    # actually typed in caps; the stop-list keeps "ETF"/"USA"/"CEO" out.
    for tok in _TICKER_RE.findall(_ampersands(message, add)):
        if tok not in NOT_TICKERS:
            add(known.get(tok, tok))
    said = f" {' '.join(_words(message))} "
    for name, tk in known.items():
        # On word boundaries: a held NOW is not in "I know".
        if len(name) > 2 and f" {' '.join(_words(name))} " in said:
            add(tk)
            continue
        # As it is said: "ServiceNow" for the filed "ServiceNow, Inc.", and
        # never a short form that is a word of its own.
        short = _short(name)
        if (len(short) > 2 and short not in _COMMON
                and short not in _NOT_NAME_WORDS and f" {short} " in said):
            add(tk)
    if not out:
        for cand in _NAME_RE.findall(message)[:_MAX_LOOKUPS + 2]:
            cand, _ = _opened(cand)
            if not cand or cand in _NOT_NAMES or cand.upper() in NOT_TICKERS:
                continue
            sym = lookup(cand)
            if sym:
                add(sym)
                break
    return out[:MAX_TICKERS]


# Shortest typed symbol `unlisted` will call made up: "F" and "GE" are real,
# and two letters say too little to search on.
_UNLISTED_MIN = 3


def _search_rows(query: str) -> tuple[list[tuple[str, str]], bool]:
    """Yahoo's (symbol, name) rows for `query`, and whether it was asked at
    all — an empty answer while it cools down after a refusal means nothing."""
    from stocks.data.symbols import reachable, search_rows

    rows = [(r[0], r[1]) for r in search_rows(query, limit=3)]
    return rows, reachable()


def _same_symbol(typed: str, symbol: str) -> bool:
    s = symbol.upper()
    return typed in (s, s.split(".")[0], s.split("-")[0], s.replace("-", "."))


def unlisted(
    message: str,
    known: dict[str, str] | None = None,
    held: str | Callable[[], str] = "",
    search: Callable[[str], tuple[list[tuple[str, str]], bool]] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """The symbols typed in `message` that Yahoo lists nothing under, each
    with its nearest matches as (symbol, name) — or {} unless every symbol
    typed is one.

    Wary by construction, since a "no such company" answer to a real one is
    worse than a slow answer: a symbol on the watchlist or in the book
    (`held`, its text — or what reads it, asked only once a symbol is left
    to search) is real, one too short to search on may be, and a Yahoo that
    could not be asked (`search`'s second half) settles nothing.
    """
    known = known or {}
    names = {v.upper() for v in known.values()} | {k.upper() for k in known}
    typed = [t for t in dict.fromkeys(_TICKER_RE.findall(
        _ampersands(message, lambda _s: None))) if t not in NOT_TICKERS]
    if not typed or any(len(t) < _UNLISTED_MIN or t in names for t in typed):
        return {}
    book = held if isinstance(held, str) else held()
    search = search or _search_rows
    out: dict[str, list[tuple[str, str]]] = {}
    for tok in typed:
        if re.search(rf"(?<![\w.-]){re.escape(tok)}(?![\w-])", book):
            return {}
        try:
            rows, asked = search(tok)
        except Exception:
            return {}
        if not asked or any(_same_symbol(tok, sym) for sym, _n in rows):
            return {}
        out[tok] = rows
    return out


def unlisted_block(missing: dict[str, list[tuple[str, str]]]) -> str:
    """What the answer is told about symbols nobody lists."""
    if not missing:
        return ""
    rows = []
    for tok, near in missing.items():
        close = "; ".join(f"{sym} ({name})" for sym, name in near)
        rows.append(f"- {tok}: no security listed under it"
                    + (f"; the nearest Yahoo offers: {close}" if close else ""))
    return (
        "\n\n---\nChecked just now on Yahoo Finance, which lists stocks, funds "
        "and coins on every major exchange:\n" + "\n".join(rows) + "\nIf the "
        "question is about that symbol, say in a line or two that you could not "
        "find it, invent nothing about it, name a near match only as a "
        "possibility, and ask the user to check the spelling or give the "
        "company's name. If it is not a symbol here (an acronym, a word), "
        "ignore this note."
    )


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
    for tok in _TICKER_RE.findall(_ampersands(message, lambda _symbol: None)):
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
        # The rest of a run that opens with "Resultados" or "Mira" does not
        # start the sentence.
        cand, opened = _opened(m.group(0).rstrip("."))
        if (not cand or (m.start() in starts and not opened)
                or cand in _NOT_NAMES or cand in _CALENDAR
                or cand.upper() in NOT_TICKERS):
            continue
        out.append(cand)
    return list(dict.fromkeys(out))


# What a legal name carries that nobody types: "NVIDIA Corporation" is said
# "Nvidia", "Banco Santander, S.A." is "Banco Santander".
_LEGAL = frozenset("""
    inc incorporated corp corporation company co plc ltd limited sa se ag nv
    holding holdings group class adr spa ab asa oyj
""".split())
# Too common to name one company on its own.
_COMMON = frozenset("""
    banco bank international global technologies technology systems american
    first general united the energy group
""".split())


def _short(name: str) -> str:
    """A company's name as it is said: legal suffixes and share classes off."""
    words = _words(name)
    while words and (words[-1] in _LEGAL or len(words[-1]) == 1):
        words.pop()
    return " ".join(words)


def aliases(names: Iterable[str], message: str,
            known: dict[str, str]) -> list[str]:
    """`names` (as `named` found them) with every other name the same
    holding goes by on the watchlist — "Nvidia" is also "NVDA" and "NVIDIA
    Corporation" — so a past conversation that called it the other way is
    still about it. A watchlist company said in lower case ("¿y nvidia?")
    counts as named too. A typed name that fits two holdings is left alone:
    widening it would be a guess."""
    by_ticker: dict[str, list[str]] = {}
    for name, tk in known.items():
        by_ticker.setdefault(tk.upper(), []).append(name)
    said = f" {' '.join(_words(message))} "
    out = list(names)
    hits: list[str] = []
    for typed in out:
        words = set(_words(typed))
        if not words or words <= _COMMON:
            continue
        fits = {tk.upper() for name, tk in known.items()
                if name == typed.upper() or words <= set(_words(name))}
        if len(fits) == 1:
            hits.extend(fits)
    for tk, forms in by_ticker.items():
        for form in forms:
            short = _short(form)
            if (len(short) >= 4 and short not in _COMMON
                    and f" {short} " in said):
                hits.append(tk)
    for tk in dict.fromkeys(hits):
        for form in (tk, *by_ticker.get(tk, ())):
            out.append(form)
            if (short := _short(form)) and short.upper() != form.upper():
                out.append(short)
    return list(dict.fromkeys(out))


# ----------------------------------------------------------------- quotes


def _fetch_quote(ticker: str) -> Quote | None:
    """One live snapshot: the app's session quote first, yfinance's fast
    path when that has nothing.

    The session quote (`data.quotes`, read by `portfolio._snapshot`) is the
    one the pages show: premarket and after-hours included, and dated. The
    fast path stays for what the batch quote misses."""
    with obs.swallow("chat.quote"):
        if (got := _session_quote(ticker)) is not None:
            return got
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


def _session_quote(ticker: str) -> Quote | None:
    from stocks.analysis.portfolio import _snapshot
    from stocks.data.quotes import quote as live_quote

    row = live_quote(ticker)
    snap = _snapshot(row) if row else None
    if not snap or snap.get("price") is None:
        return None
    basis = snap.get("basis")
    # The close the move runs from: premarket against the last close,
    # everything else against the one before (`_snapshot`).
    since = snap.get("regular") if basis == "pre" else row.get(
        "regularMarketPreviousClose")
    cap = row.get("marketCap")
    return Quote(
        ticker=ticker.upper(),
        name=str(row.get("shortName") or row.get("longName") or ""),
        price=float(snap["price"]),
        currency=str(snap.get("currency") or ""),
        prev_close=float(since) if since else None,
        year_high=snap.get("high_52w"),
        year_low=snap.get("low_52w"),
        market_cap=float(cap) if cap else None,
        session=basis if basis in ("pre", "post") else "",
        as_of=str(snap.get("as_of") or ""),
        close=snap.get("regular") if basis in ("pre", "post") else None,
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
        "prices quoted in web results; each move is dated with its session, "
        "and premarket or after-hours is where a report out of hours trades "
        "first):\n"
        + "\n".join(q.line(lang) for q in quotes_)
    )


def points_at_screen(message: str, known: dict[str, str] | None = None) -> bool:
    """Whether `message` is about the ticker on screen without naming it."""
    if _POINTS_RE.search(message):
        return True
    return bool(_PRICED_RE.search(message)) and not mentioned(
        message, known, lookup=lambda _name: "")


def lookup_for(
    message: str, watchlist: Path | None = None, focus: str = "", lang: str = "en"
) -> list[Quote]:
    """The whole path in one call: mentions → live quotes.

    The convenience entry point both chat surfaces use; every failure inside
    degrades to []. `focus` is quoted only when the message points at it
    (`points_at_screen`); a symbol it names is quoted whatever the page."""
    try:
        known = watchlist_names(watchlist) if watchlist else {}
        focus = focus if focus and points_at_screen(message, known) else ""
        return _with_crypto(quotes(mentioned(message, known, focus)), _scan, lang)
    except Exception:
        return []
