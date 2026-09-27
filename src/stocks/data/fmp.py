"""Financial Modeling Prep client — fallback fundamentals for non-US filers.

EDGAR only covers SEC filers, so emerging-market / foreign names (the user's
S&P + Nasdaq + EM universe) fall back here. Requires an API key in
FMP_API_KEY; without it every call returns empty and callers degrade to
"EDGAR only". `stable/` is the current API — the old `api/v3/` paths this
client used until 2026-09 were retired 2025-08-31 and now 403 unconditionally,
key or no key. A free key still 402s on a genuinely foreign symbol (a KRX
listing, an OTC ADR) — international coverage past the free tier's own
country list is a paid-plan feature — so treat this as best-effort even with
a key: some non-US names it will reach, some it will not.
"""

from __future__ import annotations

import json
import os
import urllib.error

import pandas as pd

from stocks.data.http import get_json

# 5 is the free plan's own ceiling on this endpoint — it 402s past that
# regardless of ticker (`limit=40`, the old value, 402'd on every symbol, not
# just a foreign one). Raise it if the key on FMP_API_KEY is ever a paid one.
LIMIT = 5
INCOME_URL = (
    "https://financialmodelingprep.com/stable/income-statement"
    f"?symbol={{ticker}}&period=quarter&limit={LIMIT}&apikey={{key}}"
)


def api_key() -> str | None:
    return os.getenv("FMP_API_KEY") or None


def has_key() -> bool:
    return api_key() is not None


def diluted_eps_facts(ticker: str) -> pd.DataFrame:
    """Per-quarter diluted EPS (as reported) from FMP, oldest-first.

    Same columns as edgar.diluted_eps_facts (end/filed/eps/kind) so the P/E
    pipeline is source-agnostic. FMP reports discrete quarters, so kind is
    always 'Q' — no Q4 reconstruction needed. Empty frame when no key is set
    or the request fails.
    """
    cols = ["end", "filed", "eps", "kind"]
    key = api_key()
    if key is None:
        return pd.DataFrame(columns=cols)
    url = INCOME_URL.format(ticker=ticker.upper(), key=key)
    try:
        data = get_json(url)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return pd.DataFrame(columns=cols)
    if not isinstance(data, list):
        return pd.DataFrame(columns=cols)

    rows = []
    for d in data:
        eps = d.get("epsdiluted")
        if eps is None:
            eps = d.get("epsDiluted")
        if eps is None:
            eps = d.get("eps")
        end = d.get("date")
        filed = d.get("fillingDate") or d.get("filingDate") or end
        if eps is None or end is None:
            continue
        rows.append((pd.to_datetime(end).date(), filed, float(eps), "Q"))
    return pd.DataFrame(sorted(rows), columns=cols)
