"""What kind of thing a symbol is — the one answer the ticker page lays out by.

The search box finds shares, ETFs, coins and indices alike, and until this
module the page had two booleans to tell them apart (`crypto.is_crypto`,
`funds.is_fund`). Every one of them got the same row of RSI, SMA20 and
candles, which reads fine for a share and is actively misleading for a
money-market fund: XEON rises a sliver every single day, so its 14-day RSI
sits in the nineties and the page called a cash account "overbought".

Seven kinds, each one a different thing to own:

* **stock** — a company's share.
* **equity_fund** — an ETF or fund whose price follows a basket of shares.
  Also where commodity and leveraged wrappers land for now (GLD, TQQQ): they
  are baskets that trade like a share, and the page lays them out the same.
* **bond_fund** — a basket of bonds; what moves it is interest rates.
* **money_market** — cash that earns close to the central bank's rate. Its
  price is a gentle straight line and the number that matters is its yield.
* **closed_end** — a US listed closed-end fund (`stocks.data.cef`), which
  trades at a premium or discount to what it holds.
* **crypto** — a coin pair (`stocks.data.crypto`).
* **index** — a market gauge (^GSPC): followed, never bought.

**Why the name comes first.** Yahoo gives no category for UCITS lines —
XEON, IWDA, VWCE, IB01 and AGGH all answer ``category: None`` — so for most
of what a European investor holds the fund's own name is the best evidence
("Overnight Rate Swap", "Treasury Bond 0-1yr", "Aggregate Bond"). Then
Yahoo's category and asset mix, where it has them. When none of that settles
it, the price itself does: a money-market line moves well under 1% a year and
never falls, which no equity or bond fund does. That rule needs a year of
bars, so it runs only for the funds the text could not place.

**What is stored.** Only verdicts that came from the fund's description
(name, category, asset mix) go to ``data/asset_kinds.json``: those are facts
about the product. A verdict read off the price is recomputed whenever the
loader's own day-long memo expires, so one odd year cannot pin a label on a
fund forever — the same caution `stocks.data.cef` keeps for a failed lookup.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections.abc import Iterable, Sequence

from stocks import atomic
from stocks.config import DATA_DIR

STOCK = "stock"
EQUITY_FUND = "equity_fund"
BOND_FUND = "bond_fund"
MONEY_MARKET = "money_market"
CLOSED_END = "closed_end"
CRYPTO = "crypto"
INDEX = "index"

KINDS = (STOCK, EQUITY_FUND, BOND_FUND, MONEY_MARKET, CLOSED_END, CRYPTO, INDEX)
FUND_KINDS = frozenset({EQUITY_FUND, BOND_FUND, MONEY_MARKET, CLOSED_END})

# The search box's answer for a fund it has only a quoteType for: it knows it
# is a fund, not yet which kind, and a wrong "equity" pill is worse than a
# vague "fund" one.
FUND = "fund"

# symbol -> kind, learned from a fund's description (see module docstring).
KIND_CACHE = DATA_DIR / "asset_kinds.json"

# Below this annualised daily volatility a fund's price is behaving like cash.
# XEON runs at ~0.1%, IB01 at ~0.3%; the calmest short-bond funds sit at 1-2%
# and an equity index at 15%.
CASH_VOL = 0.01
# ...and it has never given back more than this from a high, which is what
# separates a money-market line from a quiet short-bond one.
CASH_DRAWDOWN = 0.005
# A year of trading days is what the verdict reads; fewer than this is too
# short to call (a fund listed last month).
MIN_BARS = 120
_YEAR = 252

_MONEY_MARKET_RE = re.compile(
    r"overnight|money[- ]market|€STR|\bESTR\b|\bSOFR\b|\bSONIA\b"
    r"|\b0-1 ?y(ea)?rs?\b|\b0-[136] ?m(onths?)?\b|\b1-3 ?m(onths?)?\b"
    r"|t-bill|treasury bills?|geldmarkt|mon[eé]taire|monetari|liquidity",
    re.IGNORECASE,
)
# No bare "government" or "municipal": a US money-market fund is often called
# "Government Cash Reserves", and its asset mix and price say what it is.
_BOND_RE = re.compile(
    r"\bbonds?\b|treasur|fixed income|aggregate|high yield|renta fija"
    r"|\bgilts?\b|\bgovt\b|\bobligations?\b|anleihen",
    re.IGNORECASE,
)

_lock = threading.Lock()
_kinds: dict[str, str] | None = None


# ------------------------------------------------------------------- verdict


def from_name(name: str = "", category: str = "") -> str | None:
    """The kind a fund's own words say it is, or None when they say nothing.

    Money market before bonds: "iShares $ Treasury Bond 0-1yr" is both, and
    what it behaves like is the former.
    """
    text = f"{name or ''} {category or ''}"
    if _MONEY_MARKET_RE.search(text):
        return MONEY_MARKET
    if _BOND_RE.search(text):
        return BOND_FUND
    return None


def price_signals(close: Sequence[float] | Iterable[float]) -> tuple[float, float] | None:
    """(annualised volatility, deepest drawdown) over the last year of closes.

    Both as positive fractions. None when there are fewer than MIN_BARS usable
    closes — a verdict off a month of prices is a guess.
    """
    values = [float(v) for v in close if v is not None and math.isfinite(float(v))]
    values = [v for v in values if v > 0][-(_YEAR + 1):]
    if len(values) < MIN_BARS:
        return None
    returns = [math.log(b / a) for a, b in zip(values, values[1:], strict=False)]
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(len(returns) - 1, 1)
    peak, deepest = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        deepest = max(deepest, 1 - v / peak)
    return math.sqrt(var) * math.sqrt(_YEAR), deepest


def _mix(asset_classes: Iterable[tuple[str, float]] | dict) -> dict[str, float]:
    pairs = asset_classes.items() if isinstance(asset_classes, dict) else asset_classes
    out: dict[str, float] = {}
    for label, weight in pairs or ():
        try:
            out[str(label)] = out.get(str(label), 0.0) + float(weight)
        except (TypeError, ValueError):
            continue
    return out


def needs_prices(
    *, name: str = "", category: str = "", asset_classes: Iterable = ()
) -> bool:
    """Whether a fund's verdict turns on how its price moves.

    True for the funds whose description cannot place them: an ultrashort
    category, a mostly-cash basket, or no usable asset mix at all. The loader
    fetches a year of bars only for these, and never stores what they say.
    """
    cat = (category or "").lower()
    if from_name(name, category) == MONEY_MARKET:
        return False
    if "ultrashort" in cat:
        return True
    if from_name(name, category) == BOND_FUND:
        return False
    mix = _mix(asset_classes)
    if mix.get("Bonds", 0.0) > 0.5:
        return False
    if mix.get("Cash", 0.0) >= 0.5 and not cat.startswith("trading--"):
        return True
    return not mix or mix.get("Other", 0.0) >= 0.5


def _fund(
    name: str,
    category: str,
    asset_classes: Iterable,
    vol_1y: float | None,
    max_dd: float | None,
) -> str:
    cat = (category or "").lower()
    calm = vol_1y is not None and vol_1y < CASH_VOL
    said = from_name(name, category)
    if said == MONEY_MARKET:
        return MONEY_MARKET
    if "ultrashort" in cat:
        # SGOV and BIL file here, and so does JPST: the price tells a T-bill
        # fund from a short-credit one.
        return MONEY_MARKET if calm else BOND_FUND
    mix = _mix(asset_classes)
    if said == BOND_FUND or mix.get("Bonds", 0.0) > 0.5:
        return BOND_FUND
    # A leveraged or inverse ETF holds its collateral as cash too; Yahoo files
    # those under "Trading--…", and their price is anything but calm.
    if mix.get("Cash", 0.0) >= 0.5 and not cat.startswith("trading--") and calm:
        return MONEY_MARKET
    swap_like = not mix or mix.get("Other", 0.0) >= 0.5
    if swap_like and calm and max_dd is not None and max_dd < CASH_DRAWDOWN:
        # A synthetic money-market ETF holds a swap, which Yahoo reports as an
        # empty or "Other" basket.
        return MONEY_MARKET
    return EQUITY_FUND


def classify(
    *,
    symbol: str,
    quote_type: str | None,
    name: str = "",
    category: str = "",
    asset_classes: Iterable = (),
    closed_end: bool = False,
    vol_1y: float | None = None,
    max_dd: float | None = None,
) -> str | None:
    """The kind of `symbol`, from what is known about it. Pure.

    None for what the page has no layout for (a future, a currency pair):
    those keep the default page and carry no label. An unknown quoteType is a
    stock, the behaviour the app had before any of this — a company must
    never lose its fundamentals because a lookup failed.
    """
    from stocks.data.crypto import is_crypto

    key = (symbol or "").upper().strip()
    qt = (quote_type or "").upper()
    if is_crypto(key) or qt == "CRYPTOCURRENCY":
        return CRYPTO
    if key.startswith("^") or qt == "INDEX":
        return INDEX
    if qt in ("ETF", "MUTUALFUND"):
        return _fund(name, category, asset_classes, vol_1y, max_dd)
    if qt in ("FUTURE", "CURRENCY") or key.endswith(("=F", "=X")):
        return None
    if closed_end:
        return CLOSED_END
    return STOCK


# ------------------------------------------------------------------- storage


def _read() -> dict[str, str]:
    try:
        data = json.loads(KIND_CACHE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v in KINDS}


def _known() -> dict[str, str]:
    global _kinds
    with _lock:
        if _kinds is None:
            _kinds = _read()
        return _kinds


def known(ticker: str) -> str | None:
    """The stored kind for `ticker`, None when none was ever settled."""
    return _known().get((ticker or "").upper().strip())


def remember(ticker: str, kind: str | None) -> None:
    """Keep a description-backed verdict; best-effort on a read-only disk."""
    key = (ticker or "").upper().strip()
    if not key or kind not in KINDS:
        return
    cache = _known()
    with _lock:
        if cache.get(key) == kind:
            return
        cache[key] = kind
        stored = _read() | {key: kind}
    try:
        atomic.write_json(KIND_CACHE, stored, indent=0, sort_keys=True)
    except OSError:
        pass


def cached(ticker: str, name: str = "") -> str | None:
    """The kind from what this host already knows — never a network call.

    For the paths that list many symbols at once (the search box, a table of
    profiles). A fund no page has opened yet answers `FUND` unless its name
    already says which kind it is; a symbol with no known quoteType answers
    None, which draws no label rather than a guessed one.
    """
    from stocks.data import cef, funds

    key = (ticker or "").upper().strip()
    if not key:
        return None
    if hit := known(key):
        return hit
    qt = funds.quote_type(key, fetch=False)
    if qt in funds.FUND_TYPES:
        said = from_name(name or funds.fund_name(key) or "")
        return said or FUND
    if qt is None and not key.startswith("^"):
        from stocks.data.crypto import is_crypto

        return CRYPTO if is_crypto(key) else None
    return classify(
        symbol=key,
        quote_type=qt,
        closed_end=qt == "EQUITY" and cef.is_closed_end(key, fetch=False),
    )


def clear() -> None:
    """Drop the in-process copy (tests)."""
    global _kinds
    with _lock:
        _kinds = None
