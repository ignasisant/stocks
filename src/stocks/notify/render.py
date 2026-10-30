"""Formatting primitives shared by the notification messages.

Pure text, no network, no clock: the daily digest, the weekly review and the
reminder print the same money and the same dates, and a reader who gets all
three should not be able to tell they were written by three modules.

Everything here is plain text for a Web Push notification (`webpush.send_all`):
a title and a body the device draws as they are, with no markup to escape and
no links — the tap opens one page, named by the message's `url`.
"""

from __future__ import annotations

from datetime import date

from stocks.config import currency_symbol

# What a notification body shows before the device folds it: two or three
# lines on Android, fewer on a watch. Past this the reader opens the page.
BODY_LINES = 3
LINE_CHARS = 120


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


def clip(text: str, limit: int = LINE_CHARS) -> str:
    """One line, whitespace folded, cut with an ellipsis past `limit`."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def body(lines: list[str | None]) -> str:
    """The notification body: the first BODY_LINES non-empty lines, clipped.

    Callers list lines most important first; whatever does not fit is what the
    page the tap opens is for.
    """
    kept = [clip(line) for line in lines if line and line.strip()]
    return "\n".join(kept[:BODY_LINES])


def message(title: str, lines: list[str | None], url: str, tag: str) -> dict:
    """The service worker's JSON (`assets/sw.js`): what it shows, where it goes.

    `tag` makes a newer notification of the same kind replace the one still
    on screen — yesterday's digest is not worth a second row.
    """
    return {"title": clip(title, 80), "body": body(lines), "url": url, "tag": tag}
