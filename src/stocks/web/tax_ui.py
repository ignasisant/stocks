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

from dataclasses import replace

import streamlit as st

from stocks.config import currency_symbol
from stocks.portfolio import tax
from stocks.web import auth, i18n

# prefs.json keys. tax_residence None = auto (from the browser locale's region).
PREF_RESIDENCE = "tax_residence"
PREF_FILING_STATUS = "tax_filing_status"
PREF_OTHER_INCOME = "tax_other_income"
PREF_NIIT = "tax_niit"
PREF_CHURCH_TAX = "tax_church_rate"
PREF_SUBNATIONAL = "tax_subnational_rate"

AUTO = "auto"

# How the active jurisdiction was arrived at, because the honest UI depends on
# it: only one of these four means "this app does not model where you are".
CHOSEN = "chosen"  # the filer picked it on the Profile page
REGION = "region"  # the browser's region is one we model
UNMODELLED = "unmodelled"  # the browser named a region we do NOT model
UNKNOWN = "unknown"  # the browser named no region at all


def region_of(locale: str | None) -> str | None:
    """Region subtag of a browser locale: 'en-US' -> 'US', 'es' -> None."""
    if not locale:
        return None
    parts = str(locale).replace("_", "-").split("-")
    return parts[1].upper() if len(parts) > 1 and len(parts[1]) == 2 else None


def resolve(prefs: dict | None = None) -> tuple[str, str]:
    """(active jurisdiction, how we got there): preference > region > default.

    Mirrors how the language resolves, with one difference: an unknown region
    lands on Spain rather than on nothing, because the ledger has to be taxed
    under *some* set of rules and this app's home jurisdiction is Spain.

    The second element exists because that fallback is not harmless. A filer
    in a country this app does not model would otherwise read Spanish
    brackets, a Modelo 720 flag and a header saying IRPF over their own book,
    with nothing on the page admitting the rules are somebody else's. Callers
    use `UNMODELLED` to say so. `UNKNOWN` is kept apart from it on purpose: a
    browser reporting plain "es" names no region, and warning that account
    about a fallback would be noise — Spain is very likely right for it.
    """
    p = prefs if prefs is not None else auth.load_prefs()
    stored = p.get(PREF_RESIDENCE)
    if stored and stored != AUTO:
        return tax.normalize(stored), CHOSEN
    region = region_of(getattr(st.context, "locale", None))
    if region and region in tax.JURISDICTIONS:
        return region, REGION
    return tax.DEFAULT_CODE, UNMODELLED if region else UNKNOWN


def resolve_code(prefs: dict | None = None) -> str:
    """The active jurisdiction alone, for the callers that only need it."""
    return resolve(prefs)[0]


def settings(prefs: dict | None = None) -> tax.TaxSettings:
    """The filer's bracket inputs, straight from prefs.json."""
    p = prefs if prefs is not None else auth.load_prefs()
    try:
        income = float(p.get(PREF_OTHER_INCOME) or 0.0)
    except (TypeError, ValueError):
        income = 0.0
    try:
        church = float(p.get(PREF_CHURCH_TAX) or 0.0)
    except (TypeError, ValueError):
        church = 0.0
    try:
        subnational = float(p.get(PREF_SUBNATIONAL) or 0.0)
    except (TypeError, ValueError):
        subnational = 0.0
    return tax.TaxSettings(
        filing_status=str(p.get(PREF_FILING_STATUS) or "single"),
        other_income=income,
        include_niit=bool(p.get(PREF_NIIT)),
        church_tax_rate=church,
        subnational_rate=subnational,
    )


def with_funds(settings: tax.TaxSettings, tickers) -> tax.TaxSettings:
    """`settings` with the fund tickers among `tickers` classified.

    Germany exempts 30% of an equity fund's result, so the engine has to know
    which holdings are funds — and it must not guess: an unclassified book is
    computed without the exemption and says so. The classification comes from
    the learned quoteType cache (data.funds), never a live fetch, so a cold
    cache degrades to "not classified" instead of blocking the page.
    """
    from stocks.data.funds import is_fund

    return replace(
        settings,
        fund_tickers=frozenset(
            t.upper() for t in tickers if is_fund(t, fetch=False)
        ),
    )


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
