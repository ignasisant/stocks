"""The funds that buy a whole sector, beside the companies the screen ranks.

The sector page answers "which of these companies is the best one". Its
obvious next question — "or do I just buy all of them?" — had no answer in
the app: a reader had to go and find a sector fund, guess whether it really
holds the sector, and work out what it costs. This module is that answer.

**The vehicles are curated, not searched.** Every symbol below was probed by
hand against Yahoo (2026-11-22): the EUR line that actually trades, an
unhedged class, and a sector split that matches the label. Distributing
lines are fine: returns are read on adjusted closes, dividends included. A
fund-name search returns hedged classes, dollar lines and floor listings with
no volume, and a hedged class standing in for an unhedged one is a wrong
number on screen, not a missing one. Mutual funds are listed only when their
ISIN resolves straight to Yahoo's own Morningstar line (`0P…`); a fund found by
name alone is left out.

**The profiles are stored, never fetched at render.** `refresh` runs in the
nightly sector job and writes `data/sector_funds.json` (mirrored to the bucket
like the sector scan), so the page costs no Yahoo request. A vehicle Yahoo
refuses tonight keeps the profile it had.

**Everything derived is a floor.** Yahoo discloses a fund's ten largest lines
only, so "how much of the fund is in the cohort" and "how much of the fund is
your podium's winner" can be undercounted, never overcounted; a name outside
the ten is "not among its ten largest", which the client must not print as 0 %.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR

FUNDS_FILE = DATA_DIR / "sector_funds.json"

Kind = Literal["etf", "fund"]
Scope = Literal["world", "us", "europe"]
Role = Literal["podium", "cohort", "other"]


@dataclass(frozen=True)
class Vehicle:
    """One curated way to buy a sector: the symbol, what it is, where it buys."""

    symbol: str
    kind: Kind
    scope: Scope
    # A part of the sector only ("banks"): Yahoo files a bank fund under
    # Financial Services at 100 %, so purity alone would sell it as the lot.
    only: str | None = None


def _etf(symbol: str, scope: Scope, only: str | None = None) -> Vehicle:
    return Vehicle(symbol, "etf", scope, only)


def _fund(symbol: str) -> Vehicle:
    return Vehicle(symbol, "fund", "world")


# Per sector: the MSCI World sector ETF (Xtrackers, Xetra, EUR, accumulating),
# the S&P 500 sector line (iShares UCITS, Xetra, EUR), the STOXX Europe 600
# one (iShares, Xetra) and a traspasable mutual fund where one was verified.
# Gaps are on purpose: no S&P UCITS line for Real Estate or Communication
# answers on Xetra, the STOXX Personal & Household Goods fund is half
# Consumer Defensive (it would mislabel Consumer Cyclical), and no mutual
# fund for the other sectors resolved by ISIN to an unhedged EUR line.
SECTOR_FUNDS: dict[str, tuple[Vehicle, ...]] = {
    "Technology": (
        _etf("XDWT.DE", "world"),
        _etf("QDVE.DE", "us"),
        _etf("EXV3.DE", "europe"),
        _fund("0P00015OFP.F"),  # Fidelity Global Technology A-Acc-EUR, LU1213836080
    ),
    "Financial Services": (
        _etf("XDWF.DE", "world"),
        _etf("QDVH.DE", "us"),
        _etf("EXV1.DE", "europe", only="banks"),
    ),
    "Healthcare": (
        _etf("XDWH.DE", "world"),
        _etf("QDVG.DE", "us"),
        _etf("EXV4.DE", "europe"),
        _fund("0P0000Y1OS.F"),  # JPM Global Healthcare A (acc) EUR, LU0880062913
    ),
    "Energy": (
        _etf("XDW0.DE", "world"),
        _etf("QDVF.DE", "us"),
        _etf("EXH1.DE", "europe"),
    ),
    "Consumer Cyclical": (
        _etf("XDWC.DE", "world"),
        _etf("QDVK.DE", "us"),
    ),
    "Consumer Defensive": (
        _etf("XDWS.DE", "world"),
        _etf("2B7D.DE", "us"),
        _etf("EXH3.DE", "europe"),
    ),
    "Industrials": (
        _etf("XDWI.DE", "world"),
        _etf("2B7C.DE", "us"),
        _etf("EXH4.DE", "europe"),
    ),
    "Utilities": (
        _etf("XDWU.DE", "world"),
        _etf("2B7A.DE", "us"),
        _etf("EXH9.DE", "europe"),
    ),
    "Basic Materials": (
        _etf("XDWM.DE", "world"),
        _etf("2B7B.DE", "us"),
        _etf("EXV6.DE", "europe"),
    ),
    "Real Estate": (
        _etf("IQQ6.DE", "world"),
        _etf("EXI5.DE", "europe"),
        # Janus Henderson Horizon Global Property A2 EUR, LU0264738294
        _fund("0P0000HS8U.F"),
    ),
    "Communication Services": (
        _etf("XWTS.DE", "world"),
        _etf("EXV2.DE", "europe"),
    ),
}

# Below this share of the fund in the page's sector, a vehicle is not "the
# sector" and is not shown under it: Fidelity Global Industrials was 44 %
# industrials with Exxon and Chevron on top. Checked at render against the
# stored profile, so a fund that drifts drops out instead of being mislabeled.
MIN_PURITY = 0.6


def vehicles(sector: str) -> tuple[Vehicle, ...]:
    return SECTOR_FUNDS.get(sector, ())


def symbols() -> tuple[str, ...]:
    """Every curated symbol once, in catalog order."""
    seen: dict[str, None] = {}
    for row in SECTOR_FUNDS.values():
        for v in row:
            seen.setdefault(v.symbol, None)
    return tuple(seen)


# ------------------------------------------------------------------ storage


def _profile_dict(profile) -> dict:
    """The stored half of a `FundProfile`: what the card reads, nothing else."""
    return {
        "name": profile.name,
        "quote_type": profile.quote_type,
        "currency": profile.currency,
        "family": profile.family,
        "expense_ratio": profile.expense_ratio,
        "holdings": [[h.symbol, h.name, h.weight] for h in profile.holdings],
        "sectors": [[label, w] for label, w in profile.sectors],
    }


def load(*, restore: bool = True) -> dict[str, dict]:
    """{symbol: stored profile}. Empty on a missing or corrupt file, like
    `sectors.load_scan`: the page renders no card rather than an error."""
    if restore and storage.enabled():
        with obs.swallow("sector.funds_restore"):
            storage.restore(FUNDS_FILE)
    try:
        raw = json.loads(FUNDS_FILE.read_text())
    except (OSError, ValueError):
        return {}
    funds = raw.get("funds") if isinstance(raw, dict) else None
    if not isinstance(funds, dict):
        return {}
    return {str(k): v for k, v in funds.items() if isinstance(v, dict)}


def save(funds: dict[str, dict]) -> None:
    payload = {"saved": date.today().isoformat(), "funds": funds}
    FUNDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(FUNDS_FILE, payload, indent=0, sort_keys=True)
    if storage.enabled():
        with obs.swallow("sector.funds_persist"):
            storage.persist(FUNDS_FILE)


# Between profiles: two Yahoo requests each, thirty-odd symbols.
PAUSE_S = 1.0


def refresh(*, dry_run: bool = False, pause_s: float = PAUSE_S) -> dict[str, str]:
    """Fetch every curated vehicle's profile and store it; {symbol: outcome}.

    Merged into what was stored: a symbol Yahoo refuses, or answers without a
    basket or a sector split, keeps last night's profile. A profile with
    neither is no use to the card (no purity, no overlap) and must not
    overwrite one that had them.
    """
    from stocks.data.funds import fetch_profile

    kept = load()
    status: dict[str, str] = {}
    for i, symbol in enumerate(symbols()):
        if i and pause_s:
            time.sleep(pause_s)
        try:
            profile = fetch_profile(symbol)
        except Exception as exc:  # noqa: BLE001 — one vehicle, not the run
            profile = None
            status[symbol] = f"failed ({type(exc).__name__}), kept"
        if profile is None or not (profile.holdings and profile.sectors):
            status.setdefault(
                symbol, "no profile, kept" if symbol in kept else "no profile"
            )
            continue
        entry = _profile_dict(profile) | {"fetched": date.today().isoformat()}
        kept[symbol] = entry
        status[symbol] = "ok"
    if not dry_run and any(s == "ok" for s in status.values()):
        save(kept)
    return status


# ------------------------------------------------------------- derived facts

# "Alphabet Inc Class A" / "Alphabet Inc Class C" are one company to a reader
# deciding whether a fund is concentrated: the fund lists GOOGL and GOOG as two
# lines, and their sum is the concentration.
_CLASS = re.compile(
    r"\b(class|cl|series|ser|cat)(?:\.\s*|\s+)[a-z0-9]\b|\b(non[- ]?voting|pref\w*)\b",
    re.I,
)
# "S.A.", "N.V.", "S.p.A.": letters with dots between them, one word.
_DOTTED = re.compile(r"\b(?:[a-z]\.){2,}")
_NOISE = re.compile(r"[^a-z0-9 ]+")
_SUFFIX = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|sa|ag|nv|se|"
    r"spa|sca|kgaa|aktiengesellschaft|oyj|asa|ab|act|"
    r"the|shs|registered|ordinary|shares|adr|group|holdings?)\b"
)


def _company(name: str) -> str:
    """A company name reduced to what two listings of it share: no accents
    ("Nestlé" is "Nestle" at another exchange), no legal form, no class."""
    text = unicodedata.normalize("NFKD", name.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"['’]", "", text)
    text = _DOTTED.sub(lambda m: m.group(0).replace(".", "") + " ", text)
    text = _CLASS.sub(" ", text)
    text = _SUFFIX.sub(" ", _NOISE.sub(" ", text))
    return " ".join(text.split())


def merged_holdings(
    rows: list, prefer: frozenset[str] | set[str] = frozenset()
) -> list[tuple[str, str, float]]:
    """Top holdings as (symbol, name, weight) with share classes summed.

    Two lines merge when their company name, stripped of the class marker and
    legal suffix, is the same. The merged line takes the symbol `prefer`
    holds (the cohort's spelling, so the overlap below matches it), else the
    heavier line's."""
    groups: dict[str, list[tuple[str, str, float]]] = {}
    order: list[str] = []
    for row in rows:
        try:
            symbol, name, weight = str(row[0]).upper(), str(row[1]), float(row[2])
        except (TypeError, ValueError, IndexError):
            continue
        # A line with no symbol (cash, a swap) cannot be linked or matched.
        if symbol in {"", "NONE", "NAN"}:
            continue
        key = _company(name) or symbol
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((symbol, name, weight))
    out = []
    for key in order:
        lines = sorted(groups[key], key=lambda r: -r[2])
        pick = next((r for r in lines if r[0] in prefer), lines[0])
        out.append((pick[0], pick[1], sum(r[2] for r in lines)))
    return sorted(out, key=lambda r: -r[2])


def _purity(profile: dict, sector: str) -> float | None:
    rows = profile.get("sectors") or []
    try:
        total = sum(float(w) for _, w in rows)
        mine = sum(float(w) for label, w in rows if label == sector)
    except (TypeError, ValueError):
        return None
    return mine / total if total > 0 else None


@dataclass(frozen=True)
class FundLine:
    """One disclosed holding, spelled as the cohort spells it, with what it
    is to this page: a podium name, another ranked company, or neither."""

    symbol: str
    name: str
    weight: float
    role: Role


@dataclass(frozen=True)
class FundFacts:
    """One vehicle as the sector card reads it. Weights are fractions."""

    symbol: str
    kind: Kind
    scope: Scope
    only: str | None
    name: str
    currency: str | None
    family: str | None
    expense_ratio: float | None
    purity: float
    lines: tuple[FundLine, ...]  # the disclosed lines, largest first, classes merged
    top3: float
    top10: float  # what the disclosed lines add up to
    cohort_weight: float  # disclosed lines that are cohort names (a floor)
    podium: tuple[tuple[str, float | None], ...]  # None = not among its ten largest
    fetched: str | None


def _listed_as(
    lines: list[tuple[str, str, float]], cohort: set[str], names: dict[str, str]
) -> list[tuple[str, str, float]]:
    """`lines` with each holding spelled as the cohort spells that company.

    A fund lists a company at its home listing and the cohort may carry
    another: MSCI World Materials holds BHP as BHP.AX while the cohort ranks
    BHP.L, and an exact symbol match would print the podium's BHP as "not
    among its ten largest" when it is the fund's second line. Matched on the
    company name stripped the same way the share classes are."""
    by_company = {_company(n): t.upper() for t, n in names.items() if n and _company(n)}
    out = []
    for symbol, name, weight in lines:
        if symbol not in cohort and (twin := by_company.get(_company(name))):
            symbol = twin
        out.append((symbol, name, weight))
    return out


def _role(symbol: str, podium: set[str], cohort: set[str]) -> Role:
    if symbol in podium:
        return "podium"
    return "cohort" if symbol in cohort else "other"


def sector_facts(
    sector: str,
    stored: dict[str, dict],
    cohort: tuple[str, ...] = (),
    podium: tuple[str, ...] = (),
    names: dict[str, str] | None = None,
) -> list[FundFacts]:
    """The curated vehicles for `sector` that the stored profiles back.

    `names` ({cohort ticker: company name}) lets a holding listed elsewhere
    count as the cohort's own line. A vehicle with no stored profile, or one
    whose split puts less than `MIN_PURITY` in `sector`, is left out (the
    second logged, since it means the catalog above needs a look)."""
    podium_in = {t.upper() for t in podium}
    names_in = {t.upper() for t in cohort} | podium_in
    out: list[FundFacts] = []
    for v in vehicles(sector):
        profile = stored.get(v.symbol)
        if not profile:
            continue
        purity = _purity(profile, sector)
        if purity is None or purity < MIN_PURITY:
            obs.warn(
                "sector.fund_impure",
                symbol=v.symbol,
                sector=sector,
                purity=None if purity is None else round(purity, 3),
            )
            continue
        lines = merged_holdings(profile.get("holdings") or [], names_in)
        lines = _listed_as(lines, names_in, names or {})
        weights: dict[str, float] = {}
        for s, _, w in lines:
            weights[s] = weights.get(s, 0.0) + w
        er = profile.get("expense_ratio")
        out.append(
            FundFacts(
                symbol=v.symbol,
                kind=v.kind,
                scope=v.scope,
                only=v.only,
                name=str(profile.get("name") or v.symbol),
                currency=profile.get("currency"),
                family=profile.get("family"),
                expense_ratio=float(er) if isinstance(er, (int, float)) else None,
                purity=purity,
                lines=tuple(
                    FundLine(s, n, w, _role(s, podium_in, names_in)) for s, n, w in lines
                ),
                top3=sum(w for _, _, w in lines[:3]),
                top10=sum(w for _, _, w in lines),
                cohort_weight=sum(w for s, _, w in lines if s in names_in),
                podium=tuple((t.upper(), weights.get(t.upper())) for t in podium),
                fetched=profile.get("fetched"),
            )
        )
    return out
