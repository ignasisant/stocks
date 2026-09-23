"""Read a broker export written in its own language.

Every parser in this package eventually has to answer the same two questions
about a cell nobody standardised: *what day is this* and *what happened*. Each
one used to answer them alone, in English, and that is why a Spanish export
imports as zero rows while reading perfectly well to a human:

* ``3 abr 2025 19:55:12`` is a date in exactly the shape ``%d %b %Y`` already
  accepted — except that ``abr`` is April only in Spanish, and pandas, which
  every fallback went through, knows ``apr``. Half the months of the year in
  es/ca/pt/fr/de have no English spelling, so half the file is unreadable and
  the other half imports fine, which reads as a corrupt export.
* ``Compra`` is a buy, but the type column was matched with ``startswith("BUY")``,
  so the whole statement came back as "unrecognised type — not imported".

So both vocabularies live here once, shared by the dedicated parsers and by
the column-mapping fallback (llm_map). The point is that neither question
needs a model: a month name is a lookup and a verb is a word list, and
anything a model has to be reached for is something that breaks when the
model is rate-limited.

Only the *language* is decoded here. What a buy means, which rows are worth
importing and whether the numbers add up stay with each parser.
"""

from __future__ import annotations

import re
from datetime import date

# Month names, lowercased and without accents, mapped to their number. Covers
# the languages a European broker exports in; ambiguity across them is not a
# problem because no two languages disagree about what a given spelling means
# (the near-misses — "mar", "may", "jun" — happen to agree).
#
# Abbreviations are matched by prefix, not by exact string, so "sept", "sep"
# and "septiembre" all resolve, as do the trailing-dot forms ("sept.").
_MONTH_WORDS: dict[int, tuple[str, ...]] = {
    1: ("jan", "ene", "gen", "janv", "januar", "jaan", "genn"),
    2: ("feb", "fev", "febr", "fevr", "februar"),
    3: ("mar", "mars", "marz", "mrz", "maart"),
    4: ("apr", "abr", "avr", "april", "abril"),
    5: ("may", "mai", "mag", "maig", "mei"),
    6: ("jun", "juin", "giu", "juni"),
    7: ("jul", "juil", "lug", "juli"),
    8: ("aug", "ago", "aou", "augu", "aout"),
    9: ("sep", "set", "sept", "settembre"),
    10: ("oct", "okt", "out", "ott", "outubro"),
    11: ("nov", "novembre", "november"),
    12: ("dec", "dic", "dez", "des", "dicembre", "dezember"),
}

# Accents are stripped before lookup so "març" and "marzo" both reach "mar".
_ACCENTS = str.maketrans("áàâäãéèêëíìîïóòôöõúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")


def plain(text: str | None) -> str:
    """`text` lowercased and stripped of accents, for matching words in it.

    Every vocabulary in this module is written unaccented, so "Comisión",
    "MARÇ" and "recompensa" all compare against it directly.
    """
    return (text or "").strip().lower().translate(_ACCENTS)


# A date cell is often a timestamp; the time half never carries the day.
_TIME_TAIL = re.compile(
    r"[\s,tT]+\d{1,2}:\d{2}(:\d{2})?(\.\d+)?\s*([ap]\.?m\.?)?\s*(z|[+-]\d{2}:?\d{2})?$",
    re.I,
)
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_NUMERIC = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{2,4})$")
# "3 feb 2025", "3-feb-2025", "feb 3, 2025", "3 de febrero de 2025"
_WORDY = re.compile(
    r"^(?:(\d{1,2})[\s.\-/]+(?:de\s+)?([a-z]{3,12})\.?|"
    r"([a-z]{3,12})\.?[\s.\-/]+(\d{1,2}))"
    r"[\s,.\-/]+(?:de\s+)?(\d{2,4})$"
)


class DateUnreadable(ValueError):
    """The cell is not a date this module can name a day for."""


def _month(word: str) -> int | None:
    word = word.strip().rstrip(".")
    for number, spellings in _MONTH_WORDS.items():
        for spelling in spellings:
            if word.startswith(spelling):
                return number
    return None


def _year(value: int) -> int:
    """A four-digit year from a two-digit one, on the usual 70 pivot."""
    if value >= 100:
        return value
    return 2000 + value if value < 70 else 1900 + value


def _build(year: int, month: int, day: int) -> str:
    return date(_year(year), month, day).isoformat()


def iso_date(value: str | None, dayfirst: bool = True) -> str:
    """ISO ``YYYY-MM-DD`` from whatever a broker printed, or raise.

    Understands ISO dates and timestamps, numeric dates in any separator, and
    dates whose month is spelled out in any of the languages above. The time
    part, the timezone and the weekday are dropped.

    `dayfirst` only decides the genuinely ambiguous numeric case (``03/04/25``
    is two different days on either side of the Atlantic); every case the
    digits themselves settle ignores it.
    """
    raw = (value or "").replace("\u00a0", " ").strip()
    if not raw:
        raise DateUnreadable("missing date")

    text = _TIME_TAIL.sub("", raw).strip().strip(",")
    if iso := _ISO.match(text):
        year, month, day = (int(g) for g in iso.groups())
        try:
            return _build(year, month, day)
        except ValueError as exc:
            raise DateUnreadable(f"unrecognised date {raw!r}") from exc

    low = text.lower().translate(_ACCENTS)
    # A leading weekday ("lun, 3 feb 2025") is decoration, never the day.
    low = re.sub(r"^[a-z]{2,10}\.?,\s*", "", low)

    if numeric := _NUMERIC.match(low):
        a, b, c = (int(g) for g in numeric.groups())
        # A four-digit first group can only be the year: 2025/06/01.
        order = (a, b, c) if len(numeric.group(1)) == 4 else None
        if order is None:
            if a > 12 >= b:
                order = (c, b, a)
            elif b > 12 >= a:
                order = (c, a, b)
            else:
                order = (c, b, a) if dayfirst else (c, a, b)
        try:
            return _build(*order)
        except ValueError as exc:
            raise DateUnreadable(f"unrecognised date {raw!r}") from exc

    if wordy := _WORDY.match(low):
        day_text, month_text = (wordy.group(1), wordy.group(2))
        if day_text is None:
            month_text, day_text = wordy.group(3), wordy.group(4)
        month = _month(month_text or "")
        if month is not None:
            try:
                return _build(int(wordy.group(5)), month, int(day_text))
            except ValueError as exc:
                raise DateUnreadable(f"unrecognised date {raw!r}") from exc

    raise DateUnreadable(f"unrecognised date {raw!r}")


def readable_date(value: str | None, dayfirst: bool = True) -> str | None:
    """`iso_date`, returning None instead of raising."""
    try:
        return iso_date(value, dayfirst)
    except (DateUnreadable, ValueError):
        return None


# --------------------------------------------------------------- which money

# Symbol or code a money cell carries -> ISO currency, longest/most specific
# first ("US$" before "$"). Exports that have no currency column at all are
# the norm outside the US, and the € in "1.000,00 €" is the only thing that
# says the row is not dollars.
CURRENCY_MARKS: tuple[tuple[str, str], ...] = (
    ("us$", "USD"), ("usd", "USD"), ("$", "USD"),
    ("eur", "EUR"), ("\u20ac", "EUR"),
    ("gbp", "GBP"), ("\u00a3", "GBP"),
    ("chf", "CHF"),
    ("jpy", "JPY"), ("\u00a5", "JPY"),
)


def currency_of(text: str | None) -> str | None:
    """The ISO currency a money cell names, or None when it names none."""
    low = plain(text)
    if not low:
        return None
    for mark, code in CURRENCY_MARKS:
        if mark in low:
            return code
    return None


# --------------------------------------------------------------- what happened

# Ledger action -> the words a broker's type column uses for it. Matched as
# whole words inside the cell, so "BUY - MARKET", "Compra de valores" and
# Fidelity's "YOU BOUGHT …" all land on the same action.
#
# Deliberately narrow: a word goes in only when it means that action in every
# statement it appears in. "Interest", "reward" and "staking" are acquisitions
# or income that each parser reports as skipped with its own explanation, and
# guessing them into a buy here would book a cost basis nobody paid.
ACTION_WORDS: dict[str, tuple[str, ...]] = {
    "buy": (
        "buy", "bought", "buys", "purchase", "purchased", "acquisition",
        "compra", "comprada", "comprado", "comprar", "compraventa",
        "achat", "acquisto", "acquistato", "kauf", "kaufen", "koop",
        "aankoop", "compre",
    ),
    "sell": (
        "sell", "sold", "sells", "sale", "disposal", "redemption",
        "venta", "vendida", "vendido", "vender", "venda", "vente", "vendita",
        "verkauf", "verkoop", "cessione",
    ),
    "dividend": (
        "dividend", "dividends", "dividendo", "dividendos", "dividende",
        "dividenden", "dividendi", "dividend uitkering",
    ),
    "fee": (
        "fee", "fees", "commission", "comision", "comisiones", "comissao",
        "frais", "gebuhr", "gebuhren", "commissione", "kosten", "corretaje",
    ),
    "split": (
        "split", "desdoblamiento", "contrasplit", "frazionamento",
    ),
}

# Longest phrase first, so "compraventa" is never read as "compra", and the
# word is matched with its own boundaries so "sale" does not fire on
# "wholesale" nor "compra" on part of a name.
_ACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])"), action)
    for word, action in sorted(
        ((w, a) for a, words in ACTION_WORDS.items() for w in words),
        key=lambda pair: -len(pair[0]),
    )
)


def action_of(text: str | None) -> str | None:
    """The ledger action a broker's type cell names, or None.

    None means "this module has nothing to say about that cell" — it is the
    caller that decides whether an unnamed type is a row to skip (a transfer)
    or a row that is broken.
    """
    low = plain(text)
    if not low:
        return None
    for pattern, action in _ACTION_PATTERNS:
        if pattern.search(low):
            return action
    return None
