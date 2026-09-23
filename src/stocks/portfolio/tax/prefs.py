"""Where the filer's tax knobs live, and how a stored preference becomes rules.

Split out of `web.tax_ui` so both runtimes can read the same settings: the
Streamlit pages get them through that module as before, and the HTTP API — an
ASGI worker with no `st.context` and no session — gets them here. Nothing in
this file imports Streamlit, which is the whole point.

`resolve` takes the browser region as an argument rather than reading it,
because that is the one input the two runtimes come by differently: a page has
`st.context.locale`, a request has an `Accept-Language` header or nothing at
all.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from stocks.portfolio import tax

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


def load(path: Path) -> dict:
    """One account's prefs.json as a dict; anything unreadable reads as empty.

    A corrupt or missing file must not stop a book being taxed — it means "no
    preference expressed", which is exactly what `resolve` already handles.
    """
    try:
        stored = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return stored if isinstance(stored, dict) else {}


def resolve(prefs: dict, region: str | None = None) -> tuple[str, str]:
    """(active jurisdiction, how we got there): preference > region > default.

    Mirrors how the language resolves, with one difference: an unknown region
    lands on Spain rather than on nothing, because the ledger has to be taxed
    under *some* set of rules and this app's home jurisdiction is Spain.

    The second element exists because that fallback is not harmless. A filer in
    a country this app does not model would otherwise read Spanish brackets, a
    Modelo 720 flag and a header saying IRPF over their own book, with nothing
    admitting the rules are somebody else's. Callers use `UNMODELLED` to say
    so. `UNKNOWN` is kept apart from it on purpose: a caller that named no
    region at all — a script, a browser reporting plain "es" — is very likely
    right to get Spain, and warning it about a fallback would be noise.
    """
    stored = (prefs or {}).get(PREF_RESIDENCE)
    if stored and stored != AUTO:
        return tax.normalize(stored), CHOSEN
    if region and region in tax.JURISDICTIONS:
        return region, REGION
    return tax.DEFAULT_CODE, UNMODELLED if region else UNKNOWN


def settings(prefs: dict) -> tax.TaxSettings:
    """The filer's bracket inputs, straight from prefs.json."""
    p = prefs or {}

    def number(key: str) -> float:
        try:
            return float(p.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return tax.TaxSettings(
        filing_status=str(p.get(PREF_FILING_STATUS) or "single"),
        other_income=number(PREF_OTHER_INCOME),
        include_niit=bool(p.get(PREF_NIIT)),
        church_tax_rate=number(PREF_CHURCH_TAX),
        subnational_rate=number(PREF_SUBNATIONAL),
    )


def with_funds(settings: tax.TaxSettings, tickers) -> tax.TaxSettings:
    """`settings` with the fund tickers among `tickers` classified.

    Germany exempts 30% of an equity fund's result, so the engine has to know
    which holdings are funds — and it must not guess: an unclassified book is
    computed without the exemption and says so. The classification comes from
    the learned quoteType cache (data.funds), never a live fetch, so a cold
    cache degrades to "not classified" instead of blocking the caller.
    """
    from stocks.data.funds import is_fund

    return replace(
        settings,
        fund_tickers=frozenset(t.upper() for t in tickers if is_fund(t, fetch=False)),
    )
