"""Crypto assets, identified by Yahoo Finance pair symbols (BTC-USD, ETH-EUR).

A crypto holding is stored everywhere — watchlist, ledger, picker — as the
full pair symbol, never the bare coin code: bare codes collide with real stock
tickers (SOL is Emeren Group on NYSE, LINK is Interlink Electronics), so
nothing here ever guesses that a bare symbol means a coin. The Revolut crypto
importer normalizes coins to pairs at parse time (coin + statement fiat
currency), which keeps the transaction currency and the quote currency of the
price series identical — FIFO, FX and tax then work unchanged.

The curated name map below powers the picker search ("bitcoin" -> BTC-USD),
display names and logos; pairs outside the map still count as crypto (any
BASE-USD/EUR/GBP form) — they just render without a friendly name.
"""

from __future__ import annotations

import re

from stocks.fuzzy import FUZZY_CUTOFF, MIN_QUERY, fuzzy_ratio

# Fiat quote currencies with reliable Yahoo pairs (also ECB currencies, so the
# FX layer can convert positions on statement currency alone).
QUOTE_CURRENCIES = ("USD", "EUR", "GBP")

_PAIR_RE = re.compile(rf"^([A-Z0-9]{{2,10}})-({'|'.join(QUOTE_CURRENCIES)})$")

# Coin code -> display name, major coins only. Extend freely; used for names,
# search and logos — never to reinterpret a bare symbol as crypto.
CRYPTO_NAMES: dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "USDT": "Tether",
    "BNB": "BNB",
    "SOL": "Solana",
    "XRP": "XRP",
    "USDC": "USD Coin",
    "ADA": "Cardano",
    "DOGE": "Dogecoin",
    "TON": "Toncoin",
    "TRX": "TRON",
    "AVAX": "Avalanche",
    "SHIB": "Shiba Inu",
    "DOT": "Polkadot",
    "LINK": "Chainlink",
    "BCH": "Bitcoin Cash",
    "LTC": "Litecoin",
    "MATIC": "Polygon",
    "POL": "Polygon Ecosystem Token",
    "UNI": "Uniswap",
    "NEAR": "NEAR Protocol",
    "ICP": "Internet Computer",
    "APT": "Aptos",
    "XLM": "Stellar",
    "ETC": "Ethereum Classic",
    "FIL": "Filecoin",
    "ARB": "Arbitrum",
    "OP": "Optimism",
    "ATOM": "Cosmos",
    "SUI": "Sui",
    "HBAR": "Hedera",
    "VET": "VeChain",
    "IMX": "Immutable",
    "INJ": "Injective",
    "RNDR": "Render",
    "GRT": "The Graph",
    "ALGO": "Algorand",
    "SEI": "Sei",
    "PEPE": "Pepe",
    "FTM": "Fantom",
    "RUNE": "THORChain",
    "AAVE": "Aave",
    "MKR": "Maker",
    "EOS": "EOS",
    "XTZ": "Tezos",
    "SAND": "The Sandbox",
    "MANA": "Decentraland",
    "CRO": "Cronos",
    "KAS": "Kaspa",
    "DYDX": "dYdX",
}

# Coin code -> CoinGecko coin id, priced from CoinGecko and never from Yahoo
# (`stocks.data.fetch.fetch_many`): either Yahoo has no pair at all (MOODENG),
# or its pair is a *different* coin under the same symbol (Yahoo's CAT-EUR
# quotes ~10,000x Simon's Cat, the CAT Revolut sells). Hand-curated and never
# resolved by CoinGecko's own symbol search: a ticker like MOODENG turns up
# more than one coin there, including scam duplicates of the real one. Add an
# entry only after checking its chart against the book's own fills.
COINGECKO_IDS: dict[str, str] = {
    "MOODENG": "moo-deng",
    "CAT": "simon-s-cat",
}

# Coin code -> CoinGecko coin id, for the coin's METADATA only: all-time high,
# supply, fully diluted value (`stocks.analysis.crypto_scan`). Kept apart from
# `COINGECKO_IDS` on purpose — an entry there reroutes the coin's *price* away
# from Yahoo, and Bitcoin's chart must not move because its tokenomics card
# gained a source. Same rule as above: checked by hand (symbol and rank against
# CoinGecko's own listing), never resolved by symbol search.
GECKO_MARKET_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "USDC": "usd-coin",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TON": "the-open-network",
    "TRX": "tron",
    "AVAX": "avalanche-2",
    "SHIB": "shiba-inu",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "BCH": "bitcoin-cash",
    "LTC": "litecoin",
    "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token",
    "UNI": "uniswap",
    "NEAR": "near",
    "ICP": "internet-computer",
    "APT": "aptos",
    "XLM": "stellar",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
    "ARB": "arbitrum",
    "OP": "optimism",
    "ATOM": "cosmos",
    "SUI": "sui",
    "HBAR": "hedera-hashgraph",
    "VET": "vechain",
    "IMX": "immutable-x",
    "INJ": "injective-protocol",
    "RNDR": "render-token",
    "GRT": "the-graph",
    "ALGO": "algorand",
    "SEI": "sei-network",
    "PEPE": "pepe",
    "FTM": "fantom",
    "RUNE": "thorchain",
    "AAVE": "aave",
    "MKR": "maker",
    "EOS": "eos",
    "XTZ": "tezos",
    "SAND": "the-sandbox",
    "MANA": "decentraland",
    "CRO": "crypto-com-chain",
    "KAS": "kaspa",
    "DYDX": "dydx-chain",
    **COINGECKO_IDS,
}

# What claim a coin is: the investment case and the way it fails differ
# completely between a monetary asset, a platform that charges fees, an app
# token and a meme. Hand-curated, because CoinGecko's own tags run to a dozen
# per coin ("FTX Holdings", "Alleged SEC Securities") and none of them is the
# one-word answer. A coin missing here has no category line — never a guess.
COIN_CATEGORY: dict[str, str] = {
    **dict.fromkeys(("BTC", "BCH", "LTC", "KAS"), "store_of_value"),
    **dict.fromkeys(
        (
            "ETH", "SOL", "ADA", "TON", "TRX", "AVAX", "DOT", "NEAR", "ICP",
            "APT", "ATOM", "SUI", "HBAR", "ALGO", "SEI", "FTM", "EOS", "XTZ",
            "ETC",
        ),
        "smart_contract",
    ),
    **dict.fromkeys(("ARB", "OP", "MATIC", "POL", "IMX"), "layer2"),
    **dict.fromkeys(("USDT", "USDC"), "stablecoin"),
    **dict.fromkeys(("XRP", "XLM"), "payments"),
    **dict.fromkeys(("BNB", "CRO"), "exchange"),
    **dict.fromkeys(("UNI", "AAVE", "MKR", "RUNE", "DYDX", "INJ"), "defi"),
    **dict.fromkeys(("LINK", "GRT", "FIL", "RNDR", "VET"), "infrastructure"),
    **dict.fromkeys(("DOGE", "SHIB", "PEPE", "MOODENG", "CAT"), "meme"),
    **dict.fromkeys(("SAND", "MANA"), "gaming"),
}

# A stablecoin tracks its peg: no cycle, no momentum, no perpetual worth
# reading. Its page keeps the stats and drops the rest.
STABLECOINS = frozenset(c for c, k in COIN_CATEGORY.items() if k == "stablecoin")

# Bitcoin's block-subsidy halvings. The next one is an ESTIMATE — it lands on
# block 1,050,000, whose date depends on hash rate — and is only ever printed
# as "around".
HALVINGS: tuple[str, ...] = ("2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20")
NEXT_HALVING_EST = "2028-04-15"

# Dated events a coin's chart marks with a vertical, as the share chart marks
# results: a move next to a halving or an ETF approval is a different fact
# from a move next to nothing. Only events whose date is a matter of record.
CYCLE_EVENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "BTC": tuple((day, "halving") for day in HALVINGS)
    + (("2024-01-11", "etf"),),
    "ETH": (("2022-09-15", "merge"), ("2024-07-23", "etf")),
}


def split_pair(ticker: str) -> tuple[str, str] | None:
    """(coin, fiat) for a crypto pair symbol, None for anything else.

    Matches BASE-USD/EUR/GBP only — stock class shares (BRK-B, HEI-A) and
    exchange suffixes (RMS.PA) never match.
    """
    m = _PAIR_RE.match(ticker.upper().strip())
    return (m.group(1), m.group(2)) if m else None


def is_crypto(ticker: str) -> bool:
    """True when the symbol is a crypto pair (BTC-USD form)."""
    return split_pair(ticker) is not None


def to_pair(coin: str, currency: str = "USD") -> str:
    """Yahoo pair symbol for a coin code and fiat currency, e.g. BTC-EUR.

    Fiat currencies without a reliable Yahoo pair fall back to USD (the
    transaction keeps its native currency; only the price series differs).
    """
    ccy = currency.upper().strip()
    if ccy not in QUOTE_CURRENCIES:
        ccy = "USD"
    return f"{coin.upper().strip()}-{ccy}"


def crypto_name(ticker: str) -> str | None:
    """Display name for a pair symbol or bare coin code, None when unknown."""
    pair = split_pair(ticker)
    coin = pair[0] if pair else ticker.upper().strip()
    return CRYPTO_NAMES.get(coin)


def search_crypto(query: str, limit: int = 6) -> list[tuple[str, str]]:
    """(pair, name) matches for a query against coin codes and names.

    Returns USD pairs (the deepest Yahoo series); code matches rank before
    name matches so "btc" puts Bitcoin first.
    """
    q = query.upper().strip()
    if not q:
        return []
    by_code = [c for c in CRYPTO_NAMES if q in c]
    by_name = [
        c for c, n in CRYPTO_NAMES.items() if q in n.upper() and c not in by_code
    ]
    matches = by_code + by_name
    if not matches and len(q) >= MIN_QUERY:
        # Typo fallback ("bitcon"): fuzzy over code and name, best first.
        # Score ties keep CRYPTO_NAMES order (major coins first), so Bitcoin
        # beats Bitcoin Cash instead of losing the alphabetical tie-break.
        scored = [
            (-s, i, c)
            for i, (c, n) in enumerate(CRYPTO_NAMES.items())
            if (s := max(fuzzy_ratio(q, c), fuzzy_ratio(q, n.upper())))
            >= FUZZY_CUTOFF
        ]
        matches = [c for _, _, c in sorted(scored)]
    return [(to_pair(c), CRYPTO_NAMES[c]) for c in matches[:limit]]
