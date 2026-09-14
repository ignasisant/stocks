"""Formatting primitives shared by the notification messages.

Pure text, no network, no clock: the daily digest and the weekly review print
the same money, the same dates and the same linked tickers, and a reader who
gets both should not be able to tell they were written by two modules.

Everything here targets Telegram's `parse_mode='HTML'`, which means every
dynamic string is escaped on the way out — tickers come from a watchlist file
the account controls, and a `<` in one would otherwise eat the rest of the
message.
"""

from __future__ import annotations

import html
from datetime import date

from stocks.config import currency_symbol
from stocks.notify import links


def esc(text: str) -> str:
    """Escape a string for a Telegram message body.

    Only `&`, `<` and `>` — the three characters Telegram's HTML mode
    documents. Python's default also turns quotes into numeric entities
    (`&#x27;`), and Telegram is not documented to decode those, so an LLM
    sentence containing an apostrophe would arrive showing the entity. Quotes
    are harmless in body text; `href` values still escape them (see
    `ticker_link`), because there they close the attribute.
    """
    return html.escape(text, quote=False)


WEEKDAYS = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "es": ("lun", "mar", "mié", "jue", "vie", "sáb", "dom"),
}
MONTHS = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "es": ("ene", "feb", "mar", "abr", "may", "jun",
           "jul", "ago", "sep", "oct", "nov", "dic"),
}


def money(amount: float, currency: str = "EUR") -> str:
    """€48,230 — always thousands-separated, no decimals for totals."""
    return f"{currency_symbol(currency)}{amount:,.0f}"


def signed(amount: float, currency: str = "EUR") -> str:
    """+415 € — a change, with its sign and its unit after the number."""
    return f"{amount:+,.0f} {currency_symbol(currency)}"


def delta(change: float, pct: float, currency: str = "EUR") -> str:
    return f"{signed(change, currency)} ({pct * 100:+.2f}%)"


def date_line(d: date, lang: str) -> str:
    wd = WEEKDAYS.get(lang, WEEKDAYS["en"])[d.weekday()]
    mo = MONTHS.get(lang, MONTHS["en"])[d.month - 1]
    return f"{wd} {d.day} {mo}"


def ticker_link(ticker: str, base: str | None) -> str:
    """A ticker, linked to its page when this deploy has a public origin.

    Escaped either way: the symbol reaches here from a watchlist file the
    account controls, and it is going into a parse_mode='HTML' message.
    """
    safe = esc(ticker)
    url = links.ticker_url(ticker, base) if base else None
    return f'<a href="{html.escape(url, quote=True)}">{safe}</a>' if url else safe


def heading(text: str) -> str:
    return f"<b>{esc(text)}</b>"
