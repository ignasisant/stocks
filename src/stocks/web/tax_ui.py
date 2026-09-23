"""Jurisdiction plumbing for the web layer: which country, which words.

The Portfolio page renders whatever the active jurisdiction's `TaxPeriod`
returns (`kpis()`, `notes()`, reporting flags) — it never branches on a country
code. That works because catalog keys follow one convention:

    portfolio.<code>_<name>   e.g. portfolio.us_estimated_tax_help
    portfolio.<name>          the neutral fallback

`key()` picks the most specific string that exists, so shipping a new
jurisdiction means adding a module under `stocks.portfolio.tax` plus whatever
`portfolio.<code>_*` copy reads better than the neutral default. Nothing here
decides tax; it decides wording, currency symbols and where the setting lives.
"""

from __future__ import annotations

import streamlit as st

from stocks.config import currency_symbol
from stocks.portfolio import tax
from stocks.portfolio.tax import prefs as tax_prefs
from stocks.portfolio.tax.prefs import (
    AUTO,
    CHOSEN,
    PREF_CHURCH_TAX,
    PREF_FILING_STATUS,
    PREF_NIIT,
    PREF_OTHER_INCOME,
    PREF_RESIDENCE,
    PREF_SUBNATIONAL,
    REGION,
    UNKNOWN,
    UNMODELLED,
    region_of,
    with_funds,
)
from stocks.web import auth, i18n

__all__ = [
    "AUTO",
    "CHOSEN",
    "PREF_CHURCH_TAX",
    "PREF_FILING_STATUS",
    "PREF_NIIT",
    "PREF_OTHER_INCOME",
    "PREF_RESIDENCE",
    "PREF_SUBNATIONAL",
    "REGION",
    "UNKNOWN",
    "UNMODELLED",
    "active",
    "flag_caption",
    "flag_emoji",
    "jurisdiction",
    "key",
    "label",
    "money",
    "region_of",
    "resolve",
    "resolve_code",
    "settings",
    "symbol",
    "t",
    "with_funds",
]


def resolve(prefs: dict | None = None) -> tuple[str, str]:
    """The active jurisdiction for this session, and how it was arrived at.

    The rules live in `stocks.portfolio.tax.prefs` so the API can read the same
    setting without Streamlit; this binding supplies the one thing only a page
    has — the browser's region — and the account's own prefs.json.
    """
    p = prefs if prefs is not None else auth.load_prefs()
    return tax_prefs.resolve(p, region_of(getattr(st.context, "locale", None)))


def resolve_code(prefs: dict | None = None) -> str:
    """The active jurisdiction alone, for the callers that only need it."""
    return resolve(prefs)[0]


def settings(prefs: dict | None = None) -> tax.TaxSettings:
    """The filer's bracket inputs, defaulting to this session's own prefs."""
    return tax_prefs.settings(prefs if prefs is not None else auth.load_prefs())


def jurisdiction(prefs: dict | None = None) -> tax.Jurisdiction:
    return tax.get(resolve_code(prefs))


def active(prefs: dict | None = None) -> tuple[tax.Jurisdiction, str]:
    """The active jurisdiction and how it was resolved (see `resolve`)."""
    code, how = resolve(prefs)
    return tax.get(code), how


# ------------------------------------------------------------------- wording


def key(code: str, name: str) -> str:
    """`portfolio.<code>_<name>` when that string exists, else the neutral one."""
    specific = f"portfolio.{code.lower()}_{name}"
    return specific if i18n.has(specific) else f"portfolio.{name}"


def t(code: str, name: str, /, **kwargs) -> str:
    """Translate a tax string for `code`, most specific wording first."""
    return i18n.t(key(code, name), **kwargs)


# ISO 3166-1 alpha-2 for the flag, where the jurisdiction code is not it.
# "UK" is how everyone writes the tax code; the country code is GB.
_FLAG_ALPHA2 = {"UK": "GB"}


def flag_emoji(code: str) -> str:
    """The jurisdiction's flag, built from its code rather than a table.

    Regional indicator symbols — "ES" is U+1F1EA U+1F1F8 — so a new
    jurisdiction gets its flag for free and only a code that is not ISO
    3166-1 alpha-2 needs an entry above. Empty for anything else, so a caller
    can concatenate unconditionally.
    """
    alpha2 = _FLAG_ALPHA2.get(code.upper(), code.upper())
    if len(alpha2) != 2 or not alpha2.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in alpha2)


def label(code: str) -> str:
    """The jurisdiction behind its flag, e.g. "🇪🇸 Spain — IRPF" — for selectors.

    The flag is prepended here rather than written into the catalogs: it is
    the same glyph in every language, and eleven countries is where a list of
    names starts needing something to scan by.
    """
    name = i18n.t(f"profile.tax_residence_{code.lower()}")
    return f"{flag_emoji(code)} {name}".strip()


def symbol(currency: str) -> str:
    return currency_symbol(currency)


def money(value: float, currency: str, *, signed: bool = False) -> str:
    """A whole-unit amount with its currency symbol: "€1,240", "$-3,000"."""
    fmt = "+,.0f" if signed else ",.0f"
    return f"{symbol(currency)}{value:{fmt}}"


def flag_caption(code: str, flag: tax.ReportingFlag, currency: str) -> str:
    """One localized line for a reporting threshold, crossed or not.

    Wording comes from `portfolio.<code>_flag_<name>` (plus a `_reportable` /
    `_ok` variant for the inner clause). A jurisdiction that ships a flag with
    no copy of its own still renders, through the neutral `flag_default` set —
    a threshold nobody worded is better shown generically than as a raw key.
    """
    name = f"flag_{flag.name}"
    if not (
        i18n.has(f"portfolio.{code.lower()}_{name}") or i18n.has(f"portfolio.{name}")
    ):
        name = "flag_default"
    inner = t(
        code,
        f"{name}_reportable" if flag.reportable else f"{name}_ok",
        val=money(flag.total_value, currency),
        threshold=money(flag.threshold, currency),
    )
    return t(code, name, message=inner)
