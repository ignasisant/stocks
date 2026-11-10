"""One account's preferences and investor profile.

`load_prefs` is read on nearly every request, so the parse is memoized on the
file's stat signature; `save_prefs` writes back only the keys a caller changed
(`accounts.LoadedPrefs`). The investor profile lives inside prefs, under
`investor_profile`, as locale-independent enum keys.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from stocks import accounts, userstore
from stocks.config import stat_key

RECENT_SEARCHES_MAX = accounts.RECENT_SEARCHES_MAX
DEFAULT_PREFS = accounts.DEFAULT_PREFS


@lru_cache(maxsize=64)
def _prefs_stored(path: Path, _key: tuple[int, int] | None) -> dict:
    """The stored half of `load_prefs`, memoized on the file's stat signature.

    Keyed like `config._yaml`: `save_prefs` changes the file, which changes the
    key, so there is no invalidation call to forget. Never handed out directly
    — `load_prefs` merges a fresh dict over the defaults, because its callers
    mutate what they get back and then save it.
    """
    if _key is None:
        return {}
    return accounts.stored_prefs(path)


def load_prefs(path: Path) -> dict:
    """This account's preferences, defaults filled in.

    Read on nearly every request by a dozen callers (the language resolver,
    the setup card, the tour, the chat), so the file read and parse are
    memoized while the merge stays per-call: the result is mutable and callers
    edit it in place before `save_prefs` — which, the dict being an
    `accounts.LoadedPrefs`, writes back only what they edited.
    """
    return accounts.LoadedPrefs(
        {**DEFAULT_PREFS, **_prefs_stored(path, stat_key(path))}
    )


def save_prefs(prefs: dict, path: Path) -> None:
    accounts.save_prefs(path, prefs, persist=userstore.persist)



# ------------------------------------------------------- investor profile
# Who the assistant is advising, stated by the user (not hard-coded). Stored
# under prefs["investor_profile"] as stable enum keys (locale-independent, so
# the English system prompt stays stable whatever the UI language) plus a free
# notes field. The chat engine reads it to build the assistant persona; empty
# -> it falls back to its historical default line.

# Both tuples are the order the controls draw in, and both run low to high in
# the same direction: a row of chips only reads as a scale when its two halves
# agree on which end is "more".
PROFILE_RISK = ("conservative", "balanced", "aggressive", "very_aggressive")
PROFILE_HORIZON = ("under_1y", "1_3y", "3_5y", "5y_plus")
PROFILE_FOCUS = ("tech", "em", "crypto", "dividends_value")
PROFILE_CONSTRAINTS = ("spain_tax", "us_tax", "eur", "no_leverage", "esg")

# Example tickers per declared focus, offered on the Profile page to an
# account whose watchlist does not have them yet (see focus_suggestions).
#
# Keyed on `focus` — a stated interest — and deliberately NOT on `risk`. A
# list assembled from someone's risk tolerance is a recommendation however it
# is worded, and this app is not in that business; a list assembled from "you
# said you follow emerging markets" is a shortcut for typing eight symbols,
# which is all it is meant to be. The seed already covers each area thinly, so
# these widen rather than replace, and nothing is ever removed.
#
# Tags are the English labels the starter watchlist uses, so an appended row
# lands in the same dashboard group as the seeded ones rather than starting a
# near-duplicate group.
FOCUS_EXAMPLES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "tech": (
        ("GOOGL", "Alphabet", "Tech"),
        ("AMD", "AMD", "Tech"),
        ("NOW", "ServiceNow", "Tech"),
    ),
    "em": (
        ("BABA", "Alibaba", "Emerging markets"),
        ("INFY", "Infosys", "Emerging markets"),
        ("NU", "Nu Holdings", "Emerging markets"),
    ),
    "crypto": (
        ("ETH-EUR", "Ethereum", "Crypto"),
        ("SOL-EUR", "Solana", "Crypto"),
        ("COIN", "Coinbase", "Crypto"),
    ),
    "dividends_value": (
        ("KO", "Coca-Cola", "Dividends"),
        ("PG", "Procter & Gamble", "Dividends"),
        ("ENB", "Enbridge", "Dividends"),
    ),
}

# What an account that never opened the form pre-selects. The middle of the
# risk scale rather than one end: this is a guess about someone we know
# nothing about, and the form is the place to correct it.
_PROFILE_DEFAULTS = {
    "risk": "balanced",
    "horizon": "5y_plus",
    "focus": [],
    "constraints": [],
    "notes": "",
}


def load_profile(prefs: dict) -> dict:
    """The account's investor profile, defaults filled in for missing fields.

    `set` is True once the user has saved the form at least once; callers use
    it to tell a real (possibly minimal) profile from the mere defaults.
    """
    stored = prefs.get("investor_profile") or {}
    out = {**_PROFILE_DEFAULTS, **stored, "set": bool(stored.get("set"))}
    # The investor plan rides along for `chat.engine.persona`, which says it
    # after the profile: every prompt that knows who the reader is then also
    # knows the lines they drew (`stocks.portfolio.plan`).
    plan = prefs.get("investor_plan")
    if isinstance(plan, dict) and plan.get("set"):
        out["plan"] = plan
    # And the entry criteria beside it (`stocks.portfolio.entry`): what a
    # buy or an add is held to, said after the plan.
    entry = prefs.get("entry_criteria")
    if isinstance(entry, dict) and entry:
        out["entry"] = entry
    return out


def profile_is_set(prefs: dict) -> bool:
    return bool((prefs.get("investor_profile") or {}).get("set"))



def focus_suggestions(profile: dict, path: Path) -> list[dict]:
    """Example rows for the account's declared focus that it does not have yet.

    Returns watchlist rows ({ticker, name, tags}), in `FOCUS_EXAMPLES` order, with
    everything already on the watchlist filtered out — so the offer shrinks as
    it is taken up and disappears once there is nothing left to add. Empty
    whenever no focus is declared, which is what keeps this off the page for
    an account that skipped the profile.
    """
    from stocks.config import load_watchlist

    have = {h.ticker.upper() for h in load_watchlist(path)}
    out: list[dict] = []
    for area in profile.get("focus") or []:
        for ticker, name, tag in FOCUS_EXAMPLES.get(area, ()):
            if ticker.upper() in have:
                continue
            have.add(ticker.upper())  # a ticker in two areas is offered once
            out.append({"ticker": ticker, "name": name, "tags": [tag]})
    return out
