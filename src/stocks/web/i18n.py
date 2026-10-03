"""Lightweight i18n — explicit language per call, no global locale.

Standard Python i18n (gettext / Babel) leans on a process-global locale
(`gettext.install`, `locale.setlocale`); this server answers many accounts in
one process, so a global locale would leak one visitor's language into
another's response. Instead every caller passes the language it resolved for
its own request, and `translate()` is a pure dict lookup — no `.mo` compile
step.

Catalogs live under locales/<lang>/*.json as flat {key: string} fragments,
one fragment per page (plus common.json for nav/shared widgets); the loader
merges every fragment for a language into one dict. Keys are dotted and
page-prefixed (`ticker.price`, `home.movers`, `common.save`) so fragments
never collide. English is the source language and the fallback for any key a
translation is missing.
"""

from __future__ import annotations

import json
from pathlib import Path

_LOCALES = Path(__file__).parent / "locales"

# code -> native language name (shown in the Profile selector). English is the
# source catalog; add a code here and drop a locales/<code>/ folder to extend.
LANGUAGES = {"en": "English", "es": "Español"}
# code -> flag drawn beside it in that selector: the country the catalog is
# written for, since a language has no flag of its own.
LANGUAGE_FLAGS = {"en": "\U0001F1EC\U0001F1E7", "es": "\U0001F1EA\U0001F1F8"}
DEFAULT_LANG = "en"


# lang -> (mtimes, merged catalog): the last catalog served for each language.
# One entry per language, replaced when the key changes — it can't grow.
# Catalogs are shipped files, not user data, so a process-wide memo leaks
# nothing between accounts.
_MEMO: dict[str, tuple[tuple[float, ...], dict[str, str]]] = {}


def _mtimes(lang: str) -> tuple[float, ...]:
    """Modification times of a language's fragments — the freshness key."""
    d = _LOCALES / lang
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    return tuple(f.stat().st_mtime for f in files)


def _catalog(lang: str) -> dict[str, str]:
    """Merge every locales/<lang>/*.json fragment into one flat dict.

    Keyed on the fragments' mtimes, so an edited fragment is picked up on the
    next call without a server restart.
    """
    key = _mtimes(lang)
    hit = _MEMO.get(lang)
    if hit is not None and hit[0] == key:
        return hit[1]
    out: dict[str, str] = {}
    d = _LOCALES / lang
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            try:
                out.update(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue  # a broken fragment falls back to English per-key
    _MEMO[lang] = (key, out)
    return out


def catalog(lang: str) -> dict[str, str]:
    """Every translated string for one language, flat and dotted.

    Public because the front end fetches this over HTTP (`api/routes/i18n.py`)
    and does its own lookups, so the server and the browser read the same
    strings from the same fragments instead of drifting.
    """
    return _catalog(lang)


def supported(lang: str | None) -> str | None:
    """Normalize a locale tag ('es-ES', 'en_US') to a supported code, or None.

    Takes the primary subtag ('es-ES' -> 'es') so browser locales and stored
    prefs both resolve; returns None when the language isn't shipped.
    """
    if not lang:
        return None
    code = str(lang).replace("_", "-").split("-")[0].lower()
    return code if code in LANGUAGES else None


def translate(key: str, lang: str | None, /, **kwargs) -> str:
    """Translate a key into `lang` (any tag `supported` accepts).

    Falls back to the English catalog, then to the raw key, so a missing
    translation degrades gracefully instead of raising. Pass format values as
    kwargs for placeholder strings, e.g. translate("ticker.loading", "es",
    ticker="AAPL") against a catalog value "Cargando {ticker}…". Only
    formatted when kwargs are given, so literal-brace strings without
    placeholders stay untouched.
    """
    code = supported(lang) or DEFAULT_LANG
    s = _catalog(code).get(key)
    if s is None:
        s = _catalog(DEFAULT_LANG).get(key, key)
    return s.format(**kwargs) if kwargs else s


def has(key: str) -> bool:
    """True when the source (English) catalog defines `key`.

    Lets a caller pick the most specific key it has copy for — the tax tab asks
    for `portfolio.us_estimated_tax_help` and falls back to the neutral
    `portfolio.estimated_tax_help` when a jurisdiction ships no override.
    """
    return key in _catalog(DEFAULT_LANG)
