"""Price charts in the chat: drawn by the app under the answer, never typed in it.

Asked to chart something, a model with no way to draw draws anyway — an ASCII
plot in a code fence, from monthly averages it found on some web page. The app
already has the closes (the Ticker page's own download, `loaders.price_bars`)
and the drawer already draws A2UI surfaces, so the chart is built here: the
message is read for what to chart and over which window, the closes are
fetched, and the result reaches the reader twice, the way a what-if sale does
(`chat/whatif.py`). Its figures ride on the question, so the prose quotes the
real first, last, high and low; and the line itself is a surface under the
answer, whose window chips fetch again without asking a model
(`POST /chat/actions`).

What to chart is resolved cheap-first, as `market.mentioned` resolves quotes:
a currency pair written as one ("EUR/USD") or as two currencies ("euro
dólar"), a handful of benchmarks by their everyday names ("oro", "S&P 500"),
then tickers and watchlist names, then a single name lookup. Up to three
symbols; two or more are drawn rebased, as change since the window opened,
because a 180-dollar share and a 1.1 exchange rate share no axis.

The reader's own book can be one of them ("¿cómo voy contra el S&P?", "gráfico
de mi cartera"): `BOOK`, drawn as its time-weighted return off the same daily
series the Rendimiento tab compounds, so a deposit is not a gain. Against it,
every other line is converted into the book's currency — a Spanish reader beat
the S&P or not in euros — and opens on the book's first day.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import pandas as pd

from stocks import obs
from stocks.chat import a2ui, market

SURFACE_ID = "chart"
ACTION = "rechart"
# The reader's own book as a line (`book_index`). No ticker has an "@", so it
# cannot collide with anything `market.mentioned` resolves.
BOOK = "@BOOK"
# What "the market" is when the book is compared with nothing named.
MARKET = "^GSPC"
MAX_SERIES = market.MAX_TICKERS
# Points per line sent to the drawer. Five years of daily closes are 1,260 and
# the drawer is 380px wide: past a few hundred, more points are more bytes in
# the stored thread and no more line.
MAX_POINTS = 260
# Closes quoted to the model along the way, besides first/last/high/low.
PROMPT_POINTS = 12
FETCH_TIMEOUT = 10.0

# Every window a message may ask for, and the ones the chips offer, in order.
WINDOWS = ("1d", "1w", "1m", "3m", "6m", "ytd", "1y", "2y", "5y", "max")
CHIPS = ("1m", "6m", "ytd", "1y", "5y", "max")
DEFAULT = "1y"

# Matched against the message with its accents folded away (`_fold`), so one
# spelling covers "gráfico" and "grafico", "evolución" and "evolucion". Loose
# on purpose, like the what-if gate: a false hit costs one cached download
# and no model call.
_WANTS_RE = re.compile(
    r"\bgrafic[oa]s?\b|\bcharts?\b|\bplot(?:s|ted)?\b|\bgraphs?\b|"
    r"\bevolucion\b|\bevolution\b|\bevolved\b|\bprice history\b|"
    r"\bhistoric[oa]\b|\btrayectoria\b|\bdibuj|\bpintame\b",
    re.IGNORECASE,
)

# First match wins, so the narrower spellings come before the words they
# contain ("6 meses" before "mes", "5 años" before "año").
_WINDOW_RES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (window, re.compile(pattern, re.IGNORECASE)) for window, pattern in (
        ("1d", r"\bintradia\b|\bintraday\b|\bde hoy\b|\btoday'?s\b|"
               r"(?<!hasta )\bhoy\b|(?<!until )(?<!to )\btoday\b"),
        ("1w", r"\bsemana\b|\bweek\b|\b5 (?:dias|days)\b"),
        ("3m", r"\b(?:3|tres) meses\b|\b(?:3|three) months\b|\btrimestre\b|"
               r"\bquarter\b"),
        ("6m", r"\b(?:6|seis) meses\b|\b(?:6|six) months\b|\bsemestre\b|"
               r"\bhalf[ -]year\b"),
        ("1m", r"\bmes\b|\bmonth\b|\b30 (?:dias|days)\b"),
        ("max", r"\b(?:10|diez|20|veinte) anos\b|\b(?:10|ten|20|twenty) years\b|"
                r"\bmaximo\b|\bmax\b|\bsiempre\b|\ball[ -]time\b|\bdesde (?:su )?"
                r"(?:salida|inicio|ipo|que cotiza)\b|\bsince (?:its )?(?:ipo|listing)\b"),
        ("5y", r"\b(?:5|cinco) anos\b|\b(?:5|five) years\b"),
        ("2y", r"\b(?:2|dos) anos\b|\b(?:2|two) years\b"),
        ("ytd", r"\bytd\b|\beste ano\b|\bthis year\b|\blo que va de ano\b|"
                r"\bso far this year\b"),
        ("1y", r"\bano\b|\byear\b|\b12 (?:meses|months)\b|\b52 (?:semanas|weeks)\b"),
    )
)

# Benchmarks a reader names in words, not symbols. `{base}` is the account's
# reporting currency: a Spanish reader's "bitcoin" is the euro pair.
_NAMED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), symbol) for pattern, symbol in (
        (r"\bs ?& ?p(?: ?500)?\b|\bsp ?500\b", "^GSPC"),
        (r"\bmsci (?:world|mundo)\b", "URTH"),
        (r"\bmsci acwi\b|\bacwi\b", "ACWI"),
        (r"\bnasdaq[ -]?100\b", "^NDX"),
        (r"\bnasdaq\b", "^IXIC"),
        (r"\bdow(?: jones)?\b", "^DJI"),
        (r"\beuro ?stoxx(?: ?50)?\b", "^STOXX50E"),
        (r"\bibex(?: ?35)?\b", "^IBEX"),
        (r"\bdax\b", "^GDAXI"),
        (r"\bnikkei\b", "^N225"),
        (r"\bvix\b", "^VIX"),
        (r"\boro\b|\bgold\b", "GC=F"),
        (r"\bplata\b|\bsilver\b", "SI=F"),
        (r"\bbrent\b|\bpetroleo\b|\bcrudo\b|\boil\b", "BZ=F"),
        (r"\bbitcoin\b", "BTC-{base}"),
        (r"\bethereum\b|\bether\b", "ETH-{base}"),
    )
)

# Currencies by name, longest first so "dólar canadiense" is not a dollar.
_CURRENCY_WORDS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), code) for pattern, code in (
        (r"\bdolar(?:es)? canadiense?s?\b|\bcanadian dollars?\b", "CAD"),
        (r"\bfranco(?:s)? suizos?\b|\bswiss francs?\b", "CHF"),
        (r"\bpeso(?:s)? mexicanos?\b|\bmexican pesos?\b", "MXN"),
        (r"\beuros?\b", "EUR"),
        (r"\bdolar(?:es)?\b|\bdollars?\b", "USD"),
        (r"\blibras?(?: esterlinas?)?\b|\bpounds?(?: sterling)?\b|\bsterling\b", "GBP"),
        (r"\byen(?:es)?\b", "JPY"),
        (r"\byuan(?:es)?\b|\brenminbi\b", "CNY"),
    )
)
_ISO = frozenset({
    "EUR", "USD", "GBP", "JPY", "CHF", "CNY", "CAD", "AUD", "NZD", "MXN",
    "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "BRL", "INR", "KRW", "HKD",
    "SGD", "ZAR", "TRY",
})
# "EUR/USD", "eur-usd", "EURUSD=X", "eurusd", or "EUR USD" in caps: two codes
# written as one pair. Space-separated lower case is left alone ("try usd").
_PAIR_RE = re.compile(r"\b([A-Za-z]{3}) ?([/-])? ?([A-Za-z]{3})(=X)?\b")
# A code on its own, not half of a crypto pair ("BTC-EUR") or a listing.
_CODE_RE = re.compile(r"(?<![\w.-])[A-Z]{3}(?![\w.=-])")
# Words of the request itself, stripped before the rest is read for a name:
# a capitalised "Hazme" or "Ultimo" is not a company to look up.
_ASKING_RE = re.compile(
    r"\b(?:haz(?:me)?|hacer|muestra(?:me)?|ensena(?:me)?|dibuja(?:me)?|pinta(?:me)?|"
    r"grafica(?:me)?|quiero|ver|show|make|draw|give|me|please|por favor|"
    r"ultim[oa]s?|last|past|los|las|el|la|un|una|a|the)\b",
    re.IGNORECASE,
)
# A lower-case name after "de"/"of" — "gráfico de nvidia" — for the one lookup
# when nothing cheaper resolved. Words that follow "de" without being a name
# are skipped rather than searched.
_OF_RE = re.compile(
    r"\b(?:de|del|of|for)\s+(?:la |las |los |el |the )?([a-z][\w&.-]{2,})",
    re.IGNORECASE)
_NOT_NAMES = frozenset({
    "evolucion", "cotizacion", "precio", "precios", "price", "prices", "grafico",
    "grafica", "chart", "historico", "cartera", "portfolio", "accion", "acciones",
    "shares", "stock", "stocks", "mercado", "market", "ultimo", "ultimos",
    "ultima", "ultimas", "last", "past", "este", "esta", "this", "hoy", "today",
    "ano", "anos", "year", "years", "mes", "meses", "month", "months", "semana",
    "week", "mis", "my", "mi", "tu", "your", "todo", "toda", "siempre", "cambio",
    "valor", "value", "rentabilidad", "performance", "comparacion", "comparison",
})
_COMPARE_RE = re.compile(r"\bcompar|\bvs\.?\b|\bversus\b|\bfrente a\b|\bcontra\b|"
                         r"\bagainst\b", re.IGNORECASE)
# The reader's own book, and the questions that measure it against something.
_BOOK_RE = re.compile(
    r"\b(?:mi|mis|my) (?:cartera|portfolio|portafolio|book|inversiones|"
    r"investments|holdings|rentabilidad|rendimiento|returns?|performance)\b|"
    r"\bcomo voy\b|\bhow am i doing\b|\bhow have i done\b|\bam i beating\b|"
    r"\bestoy batiendo\b",
    re.IGNORECASE,
)
_BEAT_RE = re.compile(r"\bbat(?:ir|iendo|o)\b|\bbeat(?:s|ing)?\b|\boutperform|"
                      r"\bunderperform|\bgan(?:o|ando) al\b", re.IGNORECASE)
_MARKET_RE = re.compile(r"\b(?:el|al|del|the) (?:mercado|market|indice|index|"
                        r"benchmark)\b|\bbenchmark\b", re.IGNORECASE)

# The window as the prompt names it.
_WINDOW_EN = {
    "1d": "today's session", "1w": "the last week", "1m": "the last month",
    "3m": "the last 3 months", "6m": "the last 6 months", "ytd": "year to date",
    "1y": "the last year", "2y": "the last 2 years", "5y": "the last 5 years",
    "max": "the whole listed history",
}


def _fold(text: str) -> str:
    """`text` with its accents dropped and its case kept: "Dólar" -> "Dolar"."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text or "")
                   if not unicodedata.combining(ch))


def wants(message: str) -> bool:
    """Whether the message asks for a chart, for how something evolved, or
    how the reader's own book did against something."""
    text = _fold(message)
    if _WANTS_RE.search(text):
        return True
    return bool(_BOOK_RE.search(text) and (
        _COMPARE_RE.search(text) or _BEAT_RE.search(text) or _MARKET_RE.search(text)))


def window_asked(message: str, today: date | None = None) -> str:
    """The window the message names, or the default year."""
    folded = _fold(message)
    for window, pattern in _WINDOW_RES:
        if pattern.search(folded):
            return window
    if str((today or date.today()).year) in folded:
        return "ytd"
    return DEFAULT


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    """`text` with `pattern`'s matches blanked out, every offset kept."""
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def _currencies(text: str) -> tuple[list[str], str]:
    """Currencies named in words or typed as codes, in the order the text
    names them, and the text with them blanked out."""
    hits: list[tuple[int, str]] = []
    for pattern, code in _CURRENCY_WORDS:
        hits += [(found.start(), code) for found in pattern.finditer(text)]
        text = _blank(text, pattern)
    for found in _CODE_RE.finditer(text):
        if found.group(0) in _ISO:
            hits.append((found.start(), found.group(0)))
            text = text[:found.start()] + "   " + text[found.end():]
    return list(dict.fromkeys(code for _, code in sorted(hits))), text


def targets(message: str, known: dict[str, str] | None = None, focus: str = "",
            base: str = "EUR",
            lookup: Callable[[str], str] = market._lookup) -> list[str]:
    """The symbols a chart request is about, best first and at most three."""
    base = (base or "EUR").upper()
    out: list[str] = []

    def add(symbol: str) -> None:
        symbol = symbol.strip().upper()
        if symbol and symbol not in out and len(out) < MAX_SERIES:
            out.append(symbol)

    text = _fold(message)
    book = bool(_BOOK_RE.search(text))
    against = book and bool(_COMPARE_RE.search(text) or _BEAT_RE.search(text)
                            or _MARKET_RE.search(text))
    if book:
        add(BOOK)
        text = _blank(text, _BOOK_RE)
    if _MARKET_RE.search(text):
        add(MARKET)
        text = _blank(text, _MARKET_RE)
    for found in list(_PAIR_RE.finditer(text)):
        left, sep, right, suffix = found.groups()
        whole = found.group(0)
        pair = (left.upper(), right.upper())
        written = bool(sep or suffix) or " " not in whole or whole.isupper()
        if written and pair[0] != pair[1] and set(pair) <= _ISO:
            add(f"{pair[0]}{pair[1]}=X")
            text = text.replace(whole, " " * len(whole))
    for pattern, symbol in _NAMED:
        if pattern.search(text):
            add(symbol.format(base=base))
            text = _blank(text, pattern)
    named, text = _currencies(text)
    if len(named) >= 2:
        add(f"{named[0]}{named[1]}=X")
    for pattern in (_WANTS_RE, _ASKING_RE, *(p for _, p in _WINDOW_RES)):
        text = _blank(text, pattern)
    # The page in focus is not a mention: "gráfico de AAPL" asked on the NVDA
    # page is AAPL's, and the focus joins only a comparison (below).
    named_one = [s for s in out if s != BOOK]
    for symbol in market.mentioned(
            text, known, "",
            lookup=(lambda _name: "") if named_one or (book and not against) else lookup):
        add(symbol)
    if not out and len(named) == 1:
        # One currency on its own is that currency against the reader's own,
        # and the reader's own against the dollar.
        other = base if named[0] != base else ("USD" if base != "USD" else "EUR")
        add(f"{named[0]}{other}=X")
    if not out:
        for found in _OF_RE.finditer(text):
            name = found.group(1)
            if name.lower() in _NOT_NAMES:
                continue
            add(lookup(name))
            break
    if book:
        # The page in focus never joins the book: "¿cómo voy?" is about the
        # reader's money, whichever ticker is on screen.
        if against and out == [BOOK]:
            add(MARKET)
        return out
    if focus and focus not in out and (not out or _COMPARE_RE.search(text)):
        out.insert(0, focus)
        del out[MAX_SERIES:]
    return out


# ------------------------------------------------------------------ the data


@dataclass(frozen=True)
class Line:
    """One symbol's closes over the window, drawn and summarised."""

    symbol: str
    currency: str
    dates: tuple[str, ...]  # sampled for drawing, ISO
    values: tuple[float, ...]
    first: float  # everything below is read off the full series, not the sample
    first_on: str
    last: float
    last_on: str
    high: float
    high_on: str
    low: float
    low_on: str
    sessions: int
    along: tuple[tuple[str, float], ...]  # PROMPT_POINTS closes, for the prompt
    index: bool = False  # the book: a growth index from 100, not a price
    converted: str = ""  # the currency it trades in, when drawn in another

    @property
    def change(self) -> float:
        return self.last / self.first - 1 if self.first else 0.0

    def since(self, value: float) -> float:
        """`value` as change since the window opened."""
        return value / self.first - 1 if self.first else 0.0


@dataclass(frozen=True)
class Chart:
    window: str
    lines: tuple[Line, ...]

    @property
    def symbols(self) -> list[str]:
        return [line.symbol for line in self.lines]

    @property
    def book(self) -> Line | None:
        return next((ln for ln in self.lines if ln.index), None)

    @property
    def rebased(self) -> bool:
        return len(self.lines) > 1 or self.book is not None

    def line(self) -> str:
        """The prompt's paragraph: what is drawn, and the figures to quote."""
        rows = []
        for ln in self.lines:
            ccy = f" {ln.currency}" if ln.currency else ""
            if ln.index:
                rows.append(
                    f"- the reader's portfolio (its time-weighted return in "
                    f"{ln.currency}, so deposits and withdrawals do not move it): "
                    f"{ln.change:+.2%} from {ln.first_on} to {ln.last_on}; best "
                    f"{ln.since(ln.high):+.2%} on {ln.high_on}, worst "
                    f"{ln.since(ln.low):+.2%} on {ln.low_on}\n"
                    "  along the way: "
                    + ", ".join(f"{day} {ln.since(value):+.2%}"
                                for day, value in ln.along)
                )
                continue
            fx = (f" (converted from {ln.converted} at each day's rate)"
                  if ln.converted else "")
            rows.append(
                f"- {ln.symbol}{fx}: {_num(ln.first)}{ccy} on {ln.first_on} -> "
                f"{_num(ln.last)}{ccy} on {ln.last_on} ({ln.change:+.2%}); high "
                f"{_num(ln.high)} on {ln.high_on}, low {_num(ln.low)} on {ln.low_on}\n"
                "  closes along the way: "
                + ", ".join(f"{day} {_num(value)}" for day, value in ln.along)
            )
        how = (" as change since the window opened" if self.rebased else "")
        versus = ""
        if self.book is not None and len(self.lines) > 1:
            versus = (" The gap between the portfolio's change and another "
                      "line's is how far ahead or behind it the reader is.")
            if any(ln.symbol.startswith("^") for ln in self.lines):
                versus += " An index (^) is price only, without dividends."
        return (
            "\n\n---\nThe app draws a price chart of this under your answer "
            f"({_WINDOW_EN[self.window]}, closes from Yahoo Finance{how}). Do "
            "not draw a chart, plot or diagram yourself — no ASCII art, no "
            "code block of symbols; refer to the chart shown, and quote these "
            f"figures rather than any you found or remember:{versus}\n"
            + "\n".join(rows)
        )


def _closes(symbol: str, window: str) -> pd.Series | None:
    """The window's closes, from the Ticker page's own cached download."""
    from stocks.api import loaders

    bars = loaders.price_bars(symbol, "1y" if window == "ytd" else window)
    if bars is None or bars.empty or "Close" not in bars:
        return None
    closes = bars["Close"].dropna()
    if getattr(closes.index, "tz", None) is not None:
        # The exchange's wall clock, which is what a reader's "at 15:30" means.
        closes.index = closes.index.tz_localize(None)
    if window == "ytd":
        closes = closes[closes.index >= pd.Timestamp(date.today().year, 1, 1)]
    return closes if len(closes) >= 2 else None


def _currency(symbol: str) -> str:
    quote = next(iter(market.quotes([symbol])), None)
    return quote.currency if quote else ""


def _stamp(at, intraday: bool) -> str:
    stamp = pd.Timestamp(at)
    return stamp.strftime("%Y-%m-%dT%H:%M" if intraday else "%Y-%m-%d")


def _picks(n: int, k: int, keep: tuple[int, ...] = ()) -> list[int]:
    """`k` indices spread evenly over `n`, the first and last always among
    them, plus `keep` — the high and the low, which a thinned line must not
    shave off the very figures printed above it."""
    if n <= k:
        return list(range(n))
    spread = {round(i * (n - 1) / (k - 1)) for i in range(k)}
    return sorted(spread | set(keep))


# The book's windows in calendar days, as `/portfolio/history` cuts them.
_BOOK_DAYS = {"1m": 30, "3m": 91, "6m": 182, "1y": 365, "2y": 730, "5y": 1825}


def book_index(hist: pd.DataFrame | None, twr: pd.Series | None, window: str,
               today: date | None = None) -> pd.Series | None:
    """The book's time-weighted growth over `window`, as an index from 100.

    Off the daily returns `/portfolio/performance` compounds, so the line's
    change is the figure the Rendimiento tab prints and a deposit moves the
    book's value but not this. Counted back from the series' own last day, as
    `/portfolio/history` counts its windows, and opened at 100 on the last day
    before the window's first return, so that return is in the line rather
    than spent as its starting point. A day the TWR dropped is skipped, not
    drawn flat.
    """
    from stocks.analysis import naive_dates

    returns = twr.dropna() if twr is not None else pd.Series(dtype=float)
    if returns.empty:
        return None
    returns.index = naive_dates(returns.index)
    if window in _BOOK_DAYS:
        cut = returns.index.max() - pd.Timedelta(days=_BOOK_DAYS[window])
        returns = returns[returns.index >= cut]
    elif window == "ytd":
        year = (today or date.today()).year
        returns = returns[returns.index >= pd.Timestamp(year, 1, 1)]
    if returns.empty:
        return None
    days = (naive_dates(hist.index) if hist is not None and len(hist)
            else returns.index)
    earlier = days[days < returns.index[0]]
    opened = earlier[-1] if len(earlier) else returns.index[0] - pd.Timedelta(days=1)
    levels = 100 * (1 + returns).cumprod()
    return pd.concat([pd.Series([100.0], index=pd.DatetimeIndex([opened])), levels])


def book_for(db, base: str) -> Callable[[str], pd.Series | None]:
    """The reader's book as `build` takes it: a window in, its index out."""
    from pathlib import Path

    def fetch(window: str) -> pd.Series | None:
        from stocks.api import loaders

        path = str(db)
        if not Path(path).exists():
            return None
        hist, twr, _missing = loaders.history(path, loaders.db_mtime(path), base)
        return book_index(hist, twr, window)

    return fetch


def _to_base(closes: pd.Series, currency: str, base: str) -> pd.Series | None:
    """`closes` in `base` at each day's rate, or None without a rate."""
    from stocks.analysis.portfolio import fx_frame

    rates = fx_frame([currency], closes.index, base).get(currency.upper())
    if rates is None:
        return None
    out = (closes * rates.reindex(closes.index).ffill().bfill()).dropna()
    return out if len(out) >= 2 else None


def _since(closes: pd.Series, start: pd.Timestamp) -> pd.Series | None:
    """`closes` from the last one at or before `start`, the book's first day:
    a benchmark shut that day opens on its close before it."""
    before = closes.index[closes.index <= start]
    out = closes[closes.index >= (before[-1] if len(before) else start)]
    return out if len(out) >= 2 else None


def _line(symbol: str, closes: pd.Series, currency: str, window: str, *,
          index: bool = False, converted: str = "") -> Line:
    intraday = window in ("1d", "1w")
    values = [float(v) for v in closes.to_numpy()]
    days = [_stamp(at, intraday) for at in closes.index]
    hi = max(range(len(values)), key=values.__getitem__)
    lo = min(range(len(values)), key=values.__getitem__)
    drawn = _picks(len(values), MAX_POINTS, (hi, lo))
    quoted = _picks(len(values), PROMPT_POINTS)
    return Line(
        symbol=symbol, currency=currency,
        dates=tuple(days[i] for i in drawn),
        values=tuple(round(values[i], 6) for i in drawn),
        first=values[0], first_on=days[0], last=values[-1], last_on=days[-1],
        high=values[hi], high_on=days[hi], low=values[lo], low_on=days[lo],
        sessions=len(values),
        along=tuple((days[i], values[i]) for i in quoted[1:-1]),
        index=index, converted=converted,
    )


def build(symbols: list[str], window: str = DEFAULT, *,
          closes: Callable[[str, str], pd.Series | None] | None = None,
          currency: Callable[[str], str] | None = None,
          book: Callable[[str], pd.Series | None] | None = None,
          base: str = "",
          convert: Callable[[pd.Series, str, str], pd.Series | None] | None = None,
          timeout: float = FETCH_TIMEOUT) -> Chart | None:
    """The chart of `symbols` over `window`, or None when none could be priced.

    Fetched concurrently behind one wall-clock budget, like `market.quotes`: a
    throttled Yahoo costs the answer seconds, not the turn, and a symbol that
    fails drops out of the chart rather than taking the others with it.

    `BOOK` among the symbols is the reader's book, from `book` (`book_for`) in
    `base`; without one it drops out like any symbol without prices. Beside
    it the other lines are converted into `base` (an exchange rate is left
    as it is: its currencies are the point) and cut to the book's first day.
    """
    closes = closes or _closes
    currency = currency or _currency
    convert = convert or _to_base
    window = window if window in WINDOWS else DEFAULT
    names = list(dict.fromkeys(s.upper() for s in symbols if s))[:MAX_SERIES]
    if book is None and BOOK in names:
        names.remove(BOOK)
    if BOOK in names and window in ("1d", "1w"):
        # The book is valued once a day: a session of it is one point.
        window = "1m"
    if not names:
        return None
    base = (base or "").upper()

    def fetch(symbol: str) -> pd.Series | None:
        if book is not None and symbol == BOOK:
            return book(window)
        return closes(symbol, window)

    def code(symbol: str) -> str:
        return base if symbol == BOOK else currency(symbol)

    pool = ThreadPoolExecutor(max_workers=2 * len(names))
    try:
        bars = [pool.submit(fetch, s) for s in names]
        ccys = [pool.submit(code, s) for s in names]
        priced: list[tuple[str, pd.Series, str]] = []
        for symbol, got, ccy in zip(names, bars, ccys, strict=True):
            try:
                series = got.result(timeout=timeout)
            except Exception as exc:  # noqa: BLE001 — one symbol, not the chart
                obs.warn("chat.chart_failed", ticker=symbol,
                         error_type=type(exc).__name__, error=str(exc)[:200])
                continue
            if series is None:
                continue
            try:
                unit = ccy.result(timeout=timeout) or ""
            except Exception:  # noqa: BLE001 — a chart without a currency code
                unit = ""
            priced.append((symbol, series, unit))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    start = next((series.index[0] for symbol, series, _ in priced if symbol == BOOK),
                 None)
    lines = []
    for symbol, series, unit in priced:
        native = ""
        if start is not None and symbol != BOOK:
            if base and unit and unit.upper() != base and not symbol.endswith("=X"):
                try:
                    moved = convert(series, unit, base)
                except Exception as exc:  # noqa: BLE001 — drawn in its own currency
                    obs.warn("chat.chart_fx_failed", ticker=symbol,
                             error_type=type(exc).__name__, error=str(exc)[:200])
                    moved = None
                if moved is not None:
                    series, native, unit = moved, unit, base
            series = _since(series, start)
            if series is None:
                continue
        lines.append(_line(symbol, series, unit, window, index=symbol == BOOK,
                           converted=native))
    if not lines:
        return None
    obs.event("chat.chart", window=window, series=len(lines))
    return Chart(window, tuple(lines))


# ------------------------------------------------------------------- surface


def _num(value: float) -> str:
    """A close as a reader reads it: 1.1249, 182.50, 95,120."""
    size = abs(value)
    places = 4 if size < 10 else 2 if size < 10_000 else 0
    return f"{value:,.{places}f}"


def _tone(change: float) -> str:
    return "up" if change > 0 else "down" if change < 0 else "flat"


def _name(ln: Line, translate) -> str:
    return translate("chat.chart_book") if ln.index else ln.symbol


def _title(c: Chart, translate) -> str:
    window = translate(f"chat.chart_window_{c.window}")
    if c.book is not None:
        others = [ln.symbol for ln in c.lines if not ln.index]
        if others:
            return translate("chat.chart_title_book_vs", window=window,
                             others=", ".join(others))
        return translate("chat.chart_title_book", window=window)
    return translate(
        "chat.chart_title_change" if c.rebased else "chat.chart_title_price",
        window=window,
    )


def view(c: Chart, translate) -> dict:
    """The figures the surface prints, formatted: its `/view` data."""
    out: dict = {"title": _title(c, translate)}
    for i, ln in enumerate(c.lines):
        ccy = f" {ln.currency}" if ln.currency else ""
        out[f"m{i}"] = {
            "last": (translate("chat.chart_book_hint", currency=ln.currency)
                     if ln.index else _num(ln.last) + ccy),
            "last_hint": ln.last_on[:10],
            "change": f"{ln.change:+.2%}",
            "tone": _tone(ln.change),
            "change_hint": translate("chat.chart_since", value=_num(ln.first)),
            "range": f"{_num(ln.low)} – {_num(ln.high)}",
            "range_hint": translate("chat.chart_range_hint", low=ln.low_on[:10],
                                    high=ln.high_on[:10]),
        }
    return out


def series(c: Chart, translate=None) -> list[dict]:
    """What the Chart component draws: its `/chart` data. The book's line is
    named and marked as an index, which the drawer reads as change only."""
    out = []
    for ln in c.lines:
        row = {"symbol": ln.symbol, "currency": ln.currency,
               "dates": list(ln.dates), "values": list(ln.values)}
        if ln.index:
            row["index"] = True
            if translate is not None:
                row["label"] = _name(ln, translate)
        out.append(row)
    return out


def surface(c: Chart, translate) -> list[dict]:
    """The line, the figures over it, and the chips that change its window.

    Built for the symbols it was asked about: a press on a chip sends them
    back with the window, and the answer is the same surface's data again
    (`moved`), so the parts here never change after the first draw.
    """
    tickers = [a2ui.component(f"t{i}", "Ticker", symbol=ln.symbol)
               for i, ln in enumerate(c.lines) if not ln.index]
    if c.rebased:
        figures = [
            a2ui.component(f"f{i}", "Metric", label=_name(ln, translate),
                           value=a2ui.path(f"/view/m{i}/change"),
                           tone=a2ui.path(f"/view/m{i}/tone"),
                           hint=a2ui.path(f"/view/m{i}/last"))
            for i, ln in enumerate(c.lines)
        ]
    else:
        figures = [
            a2ui.component("f_last", "Metric", label=translate("chat.chart_last"),
                           value=a2ui.path("/view/m0/last"),
                           hint=a2ui.path("/view/m0/last_hint")),
            a2ui.component("f_change", "Metric", label=translate("chat.chart_change"),
                           value=a2ui.path("/view/m0/change"),
                           tone=a2ui.path("/view/m0/tone"),
                           hint=a2ui.path("/view/m0/change_hint")),
            a2ui.component("f_range", "Metric", label=translate("chat.chart_range"),
                           value=a2ui.path("/view/m0/range"),
                           hint=a2ui.path("/view/m0/range_hint")),
        ]
    parts = [
        a2ui.component("root", "Column",
                       children=["head", "figures", "plot", "windows", "note"]),
        a2ui.component("head", "Row", children=[*(t["id"] for t in tickers), "title"],
                       align="center"),
        *tickers,
        a2ui.component("title", "Text", text=a2ui.path("/view/title"), variant="h3"),
        a2ui.component("figures", "Row", children=[f["id"] for f in figures]),
        *figures,
        a2ui.component("plot", "Chart", series=a2ui.path("/chart"),
                       mode="change" if c.rebased else "price",
                       label=a2ui.path("/view/title")),
        a2ui.component(
            "windows", "ChoicePicker",
            options=[{"label": translate(f"chat.chart_chip_{w}"), "value": w}
                     for w in CHIPS],
            value=a2ui.path("/window"), variant="chips",
            action=a2ui.event(ACTION, symbols=c.symbols, window=a2ui.path("/window")),
        ),
        a2ui.component("note", "Text",
                       text=(translate("chat.chart_note_book", currency=c.book.currency)
                             if c.book is not None else translate("chat.chart_note")),
                       variant="caption"),
    ]
    data = {"window": c.window, "chart": series(c, translate),
            "view": view(c, translate)}
    return a2ui.surface(SURFACE_ID, parts, data)


def moved(c: Chart, translate) -> list[dict]:
    """The same surface over another window: its data, nothing else."""
    return [a2ui.data_update(SURFACE_ID, "/chart", series(c, translate)),
            a2ui.data_update(SURFACE_ID, "/view", view(c, translate)),
            a2ui.data_update(SURFACE_ID, "/window", c.window)]
