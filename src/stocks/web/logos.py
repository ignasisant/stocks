"""Logos and display names — the visual identity of a ticker, brand or broker.

Every one of these is a network lookup behind a long cache: a logo that
resolves once should stay resolved for a day, and a name the user set on their
own watchlist must never render for another account (see `company_name`).
Mirroring to ./static is what keeps the hosted app from hot-linking on every
rerun; `stocks.data.logo` owns that side.
"""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from stocks import identity
from stocks.data.logo import brand_logo_url, mirror_brand
from stocks.portfolio import platforms
from stocks.portfolio.custody import UNKNOWN as BROKER_UNKNOWN
from stocks.web import auth
from stocks.web.ds import (
    BORDER,
    FS_XS,
    RADIUS_XS,
    TEXT_MUTED,
    TEXT_PRIMARY,
)
from stocks.web.i18n import t as tr

# Streamlit static serving root: ./static next to the entry point (app.py).
# Defined in `stocks.identity` so the API mirrors into the same directory.
_STATIC_LOGO_DIR = identity.STATIC_LOGO_DIR


def _static_logo_src(name: str) -> str:
    """Browser URL for a mirrored logo file — RELATIVE, no leading slash.

    Streamlit serves ./static at <base>/app/static, where <base> is wherever
    the document actually lives: "/" locally, but "/~/+/" behind Streamlit
    Cloud's shell iframe, and "/<prefix>/" under server.baseUrlPath. A
    relative URL resolves against the document URL and lands on the right
    mount in all three; an absolute "/app/static/..." escapes the Cloud
    iframe mount and 404s (this is also the form the Streamlit docs use).
    Page routes (".../portfolio") have no trailing slash, so the last
    segment drops out and "app/static/..." still resolves at the mount root.
    """
    return f"{identity.STATIC_PREFIX}{name}"


@st.cache_data(ttl=86400, show_spinner=False)
def logo(ticker: str) -> str | None:
    """Same-origin logo URL for a ticker (cached a day — logos rarely change).

    See `stocks.identity.logo_src`; this is the script-run cache around it.
    """
    return identity.logo_src(ticker, _STATIC_LOGO_DIR)


@st.cache_data(ttl=86400, show_spinner=False)
def brand_logo(key: str, domain: str | None) -> str | None:
    """Same-origin logo URL for a brand/platform (broker selector, …).

    Mirrored into static/logos/ like ticker logos — same privacy rationale;
    the external URL is the fallback when this host can't fetch the image.
    None when the platform declares no domain (e.g. the generic CSV)."""
    if not domain:
        return None
    if name := mirror_brand(key, domain, _STATIC_LOGO_DIR):
        return _static_logo_src(name)
    return brand_logo_url(domain)


def broker_name(key: str) -> str:
    """Display name for a ledger broker prefix ("clicktrade" -> "ClickTrade").

    Brand names come from the import registry; the two generic buckets — a
    hand-entered row and a holding no note attributes — are localized.
    """
    if key == "manual":
        return tr("portfolio.broker_manual")
    if key == BROKER_UNKNOWN:
        return tr("portfolio.broker_unknown")
    return platforms.broker_label(key)


def broker_chips_html(
    mix: list[tuple[str, float]], *, size: int = 22, shares: bool = True
) -> str:
    """Custody marks for one holding: a brand logo per broker holding it.

    `mix` is `custody.mix()`'s (broker, share of shares) list. A broker with
    no brand domain of its own (a hand-entered row, a one-off note) shows a
    muted name pill instead of a logo, so the row never renders as a gap. The
    share of the position rides each mark's tooltip — the marks sit next to a
    badge, where a second number would crowd it — and `shares=False` drops it
    for a single-custodian holding.
    """
    marks = []
    for key, share in mix:
        name = broker_name(key)
        title = f"{name} · {share:.0%}" if shares and len(mix) > 1 else name
        title = html.escape(title, quote=True)
        src = brand_logo(key, platforms.broker_domain(key))
        if src:
            marks.append(
                f'<img src="{html.escape(src, quote=True)}" alt="{title}"'
                f' title="{title}" style="width:{size}px;height:{size}px;'
                f"border-radius:{RADIUS_XS};background:{TEXT_PRIMARY};"
                f"border:1px solid {BORDER};box-sizing:border-box;"
                f'padding:2px;object-fit:contain">'
            )
        else:
            marks.append(
                f'<span title="{title}" style="font-size:{FS_XS};'
                f"font-weight:600;color:{TEXT_MUTED};border:1px solid {BORDER};"
                f"border-radius:{RADIUS_XS};padding:2px 6px;"
                f'white-space:nowrap">{html.escape(name)}</span>'
            )
    if not marks:
        return ""
    return (
        '<span style="display:inline-flex;align-items:center;gap:4px">'
        + "".join(marks)
        + "</span>"
    )


@st.cache_data(show_spinner=False)
def asset_logo(name: str) -> str | None:
    """Same-origin URL for a bundled image from web/assets/ (e.g. the TopStocks
    icon), copied into static/logos/ so it is served like the brand logos."""
    src = Path(__file__).parent / "assets" / name
    dest = _STATIC_LOGO_DIR / name
    try:
        if not dest.exists():
            _STATIC_LOGO_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
    except OSError:
        return None
    return _static_logo_src(name)


@st.cache_data(ttl=86400, show_spinner=False)
def _company_name(ticker: str, watchlist: str) -> str | None:
    """`identity.company_name`, memoized per (ticker, account watchlist).

    The watchlist path is in the key because a custom name one account set
    must never render for another.
    """
    return identity.company_name(ticker, watchlist)


@st.cache_data(ttl=86400, show_spinner=False)
def yahoo_symbol(ticker: str) -> str:
    """`identity.yahoo_symbol`, memoized for a script run.

    Worth a cache here rather than only in the domain: a page that prints
    twenty rows asks this twenty times, and the ISIN tier is a network lookup.
    """
    return identity.yahoo_symbol(ticker)


def display_symbol(ticker: str) -> str:
    """What to PRINT for a ledger label: the Yahoo symbol, never the ISIN.

    Importers keep whatever the broker wrote — Revolut's local codes, and an
    ISIN whenever the statement had no symbol we could place — because that
    string is the ledger's audit trail and the key positions are booked under.
    It is a terrible thing to read: "US81762P1021" tells nobody it is
    ServiceNow. Every screen therefore prints the resolved symbol
    (`yahoo_symbol`) while links, lookups and the stored rows keep the
    original label.
    """
    return yahoo_symbol(ticker)


def company_name(ticker: str) -> str | None:
    """Human name: the session account's watchlist name first, then the coin
    map for crypto pairs, then the SEC ticker map (offline once cached). None
    for symbols no source knows. Broker codes and ISINs are resolved through
    watchlist.yaml `aliases` before any source is asked, so a holding the
    ledger stores as "US4131971040" reads as its company name. The cache keys
    on the account's watchlist path — custom names one user sets must never
    render for another."""
    return _company_name(ticker, str(auth.watchlist_path()))
