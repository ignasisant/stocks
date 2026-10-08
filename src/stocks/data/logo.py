"""Resolve company logo image URLs for the dashboard.

Preference order, best-looking first:
  1. FMP  — a real transparent-PNG logo keyed straight off the *ticker*
            (the same source TIKR-style dashboards use); no key needed for
            the image path, and no yfinance round-trip to find a domain.
  2. Google favicon — low-res, but always returns *something*, keyed off the
            company website domain (yfinance lookup).

(Clearbit used to sit between the two; HubSpot shut the API down, so it was
dropped — the v3 cache bump re-resolves entries that still point there.)

Each candidate is probed once *from this host*. Definitive answers — a
working image, or a hard 404 on every source — are cached to data/logos.json
for good. An inconclusive probe (403/429/timeout: FMP/Yahoo block datacenter
IPs, which is exactly what a cloud deploy runs on) still hands the browser (a
residential IP) the best-guess URL, and is kept apart in the same file for
BLOCKED_TTL only, so the host tries again within the week but not on every
boot. The cache is versioned: bump CACHE_VERSION to force every ticker to
re-resolve.

The file ships in the image (git-tracked) and the running host adds to it, so
with a storage bucket configured each process folds the bucket's copy in on
first use and pushes every save back: an ephemeral host's probes survive the
next deploy instead of being run again, a few seconds each, on its first page.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from stocks import atomic, obs
from stocks.config import DATA_DIR
from stocks.data.http import get_bytes_and_type, probe_image

LOGO_CACHE = DATA_DIR / "logos.json"
FMP_LOGO_URL = "https://financialmodelingprep.com/image-stock/{ticker}.png"
FAVICON_URL = "https://www.google.com/s2/favicons?domain={domain}&sz=128"
COINCAP_URL = "https://assets.coincap.io/assets/icons/{coin}@2x.png"

# Bumping this invalidates the whole on-disk cache on next load. v3 dropped
# Clearbit (API shut down) and stopped caching probes blocked by the host.
CACHE_VERSION = 3


def domain_from_website(website: str | None) -> str | None:
    """Bare domain (no scheme, no www.) from a website URL, or None."""
    if not website:
        return None
    # urlparse needs a scheme to populate netloc; add one if missing.
    if "//" not in website:
        website = "//" + website
    host = urlparse(website).netloc.lower().removeprefix("www.")
    return host or None


# The schema stamp shares the file with the URL entries but is an int, so it
# is kept out of the in-memory dict rather than widening every value's type.
_VERSION_KEY = "_v"
# Inconclusive walks, {key: [best-guess url, epoch seconds]}, beside the
# definitive string entries.
_BLOCKED_KEY = "_blocked"
BLOCKED_TTL = 7 * 86400


def _parse(text: str | bytes) -> dict:
    """A cache file's contents, {} when written by an older schema."""
    data = json.loads(text)
    if isinstance(data, dict) and data.get(_VERSION_KEY) == CACHE_VERSION:
        data.pop(_VERSION_KEY)
        return data
    return {}


def _load_file() -> dict:
    """On-disk cache, discarded wholesale if written by an older schema.

    Or if it does not parse. Every entry can be probed again, so a broken file
    costs a round of probes; raising cost every logo request a 500 until
    someone deleted it by hand — `/market/profiles` resolves rows on eight
    threads, and two interleaved writes once left it with "Extra data".
    """
    try:
        return _parse(LOGO_CACHE.read_text()) if LOGO_CACHE.exists() else {}
    except (json.JSONDecodeError, OSError) as exc:
        obs.warn("logo.cache_unreadable", error_type=type(exc).__name__)
        return {}


def _load_cache() -> dict[str, str]:
    """The definitive answers: URL, or "" for "nothing exists"."""
    return {k: v for k, v in _load_file().items() if isinstance(v, str)}


def _blocked(data: dict, now: float) -> dict[str, list]:
    """The inconclusive entries still inside BLOCKED_TTL."""
    raw = data.get(_BLOCKED_KEY)
    return {
        k: v
        for k, v in (raw if isinstance(raw, dict) else {}).items()
        if isinstance(v, list) and len(v) == 2 and now - v[1] < BLOCKED_TTL
    }


def _save_file(data: dict) -> None:
    """Whole-file replace, so a reader never sees half of a write; then the
    bucket, once this process has folded the bucket's own copy in."""
    stamped = {_VERSION_KEY: CACHE_VERSION, **data}
    atomic.write_json(LOGO_CACHE, stamped, indent=2, sort_keys=True)
    if _bucket["push"]:
        _persist_quiet(LOGO_CACHE)


# `fold`: this process already merged the bucket's copy (or tried to).
# `push`: saves may go back to the bucket — only once the fold read it, so a
# failed read never has this host's file overwrite what other boots learned.
_bucket = {"fold": False, "push": False}


# Held across read-merge-write, not across the probe: without it two threads
# each load the file, add their own key and save, and the second save drops
# the first one's.
_cache_lock = threading.Lock()


def _fold_bucket_copy() -> None:
    """Once per process: merge the bucket's cache into the shipped one.

    Merged rather than restored: the image carries entries resolved on a
    developer's machine that the bucket may never have seen, and the bucket
    carries everything earlier boots of the deployed host learned. On a key
    both know, the host's answer wins — it is the one probed from where the
    app runs.
    """
    if _bucket["fold"]:
        return
    with _cache_lock:
        if _bucket["fold"]:
            return
        with obs.swallow("logo.cache_restore"):
            from stocks import storage

            if storage.enabled():
                raw = storage.read(LOGO_CACHE)
                theirs = _parse(raw) if raw else {}
                ours = _load_file()
                if theirs:
                    blocked = {
                        **_blocked(ours, time.time()),
                        **_blocked(theirs, time.time()),
                    }
                    # Merged locally only: the bucket learns it on the next save.
                    atomic.write_json(
                        LOGO_CACHE,
                        {
                            _VERSION_KEY: CACHE_VERSION,
                            **{k: v for k, v in ours.items() if isinstance(v, str)},
                            **{k: v for k, v in theirs.items() if isinstance(v, str)},
                            _BLOCKED_KEY: blocked,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                _bucket["push"] = True
        _bucket["fold"] = True


# Skips 404 placeholders and dead FMP paths; "blocked" = can't tell from here.
_probe = probe_image

# Inconclusive resolutions (every remaining source blocked from this host),
# memoized for the process on top of the file's BLOCKED_TTL copy.
_inconclusive: dict[str, str] = {}


def _first_alive(candidates) -> tuple[str, bool]:
    """(url, definitive) — first live candidate, walked in preference order.

    "ok" wins definitively; "dead" moves on; "blocked" keeps the first such
    candidate as the browser's best guess and, unless a later candidate
    probes "ok", marks the walk inconclusive.
    """
    guess = ""
    for url in candidates:
        verdict = _probe(url)
        if verdict == "ok":
            return url, True
        if verdict == "blocked" and not guess:
            guess = url
    return guess, not guess


def _company_domain(ticker: str) -> str | None:
    """Website domain via yfinance, or None — never raises: Yahoo throttles
    shared cloud IPs hard, and a logo lookup must not take the page down."""
    try:
        from stocks.data.fetch import info as quote_info

        website = quote_info(ticker).get("website")
    except Exception:
        return None
    return domain_from_website(website)


def _candidates(ticker: str):
    """Candidate URLs, best first, yielded lazily so the yfinance domain
    lookup only runs when the FMP probe didn't already settle it."""
    from stocks.data.crypto import split_pair

    # Crypto pairs: coin icon sources — a company-domain lookup can't work.
    if pair := split_pair(ticker):
        coin = pair[0]
        yield COINCAP_URL.format(coin=coin.lower())
        yield FMP_LOGO_URL.format(ticker=f"{coin}USD")  # FMP keys crypto as BTCUSD
        return
    yield FMP_LOGO_URL.format(ticker=ticker)
    if domain := _company_domain(ticker):
        yield FAVICON_URL.format(domain=domain)


def _resolve(key: str, candidates) -> str | None:
    """Cache-then-probe walk shared by logo_url / brand_logo_url."""
    if key in _inconclusive:
        return _inconclusive[key] or None
    _fold_bucket_copy()
    data = _load_file()
    if isinstance(data.get(key), str):
        return data[key] or None
    if key in (blocked := _blocked(data, time.time())):
        _inconclusive[key] = blocked[key][0]
        return _inconclusive[key] or None
    url, definitive = _first_alive(candidates)
    with _cache_lock:
        data = _load_file()
        blocked = _blocked(data, time.time())
        if definitive:
            data[key] = url
            blocked.pop(key, None)
        else:
            blocked[key] = [url, time.time()]
        _save_file({**data, _BLOCKED_KEY: blocked})
    if not definitive:
        _inconclusive[key] = url
    return url or None


def logo_url(ticker: str) -> str | None:
    """Working logo image URL for a ticker, or None.

    FMP ticker logo first (best quality, no domain lookup), then the Google
    favicon off the yfinance website domain. Definitive results are cached
    to disk ("" means "nothing exists"); blocked probes only in memory.
    """
    ticker = ticker.upper()
    return _resolve(ticker, _candidates(ticker))


def brand_logo_url(domain: str) -> str | None:
    """Working logo URL for a brand *domain* (broker/platform, no ticker).

    Google favicon — Clearbit, the old quality source, was shut down. Cached
    under a `brand:` prefix so brand keys can never collide with tickers.
    """
    return _resolve(f"brand:{domain.lower()}", [FAVICON_URL.format(domain=domain)])


_EXT_BY_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
}


def _restore_quiet(static_dir: Path, stem: str) -> str | None:
    """Pull one previously mirrored logo back from the storage bucket
    (ephemeral hosts boot with an empty static dir); its file name. Never
    fatal: a failed pull only means the logo re-resolves over the network."""
    with obs.swallow("logo.restore", stem=stem):
        from stocks import storage

        return storage.restore_stem(static_dir, stem)
    return None


def _persist_quiet(path: Path) -> None:
    """Push one mirrored logo to the bucket. Unlike user data, a lost logo
    re-mirrors itself, so a storage hiccup must never break a render."""
    with obs.swallow("logo.mirror", path=str(path)):
        from stocks import storage

        storage.persist(path)


def _mirror(stem: str, resolve_url, static_dir: Path) -> str | None:
    """Mirror one image into `static_dir` as `stem.<ext>`; returns the file
    name. An already-mirrored file (local, or pulled back from the storage
    bucket on an ephemeral host's first touch) short-circuits before any
    network call; `resolve_url` is only invoked on a cache miss."""
    if static_dir.is_dir():
        for existing in static_dir.glob(f"{stem}.*"):
            # Exact stem: the glob for BRK also matches BRK.B's logo.
            if existing.name.rpartition(".")[0] == stem:
                return existing.name
    if restored := _restore_quiet(static_dir, stem):
        return restored
    url = resolve_url()
    if not url:
        return None
    try:
        data, ctype = get_bytes_and_type(url)
    except Exception:
        return None  # hiccup / blocked host — caller falls back to external URL
    ctype = ctype.partition(";")[0].strip().lower()
    if not ctype.startswith("image"):
        return None  # a CDN challenge page with a 200 — don't store HTML as a .png
    ext = _EXT_BY_TYPE.get(ctype, "png")
    static_dir.mkdir(parents=True, exist_ok=True)
    out = static_dir / f"{stem}.{ext}"
    out.write_bytes(data)
    _persist_quiet(out)
    return out.name


def mirror_logo(ticker: str, static_dir: Path) -> str | None:
    """Mirror a ticker's logo into `static_dir`; returns the file name.

    The dashboard serves logos same-origin (`server.static_file`) so the
    logo hosts (FMP, Clearbit, Google) never learn which tickers a viewer
    looks at — only the server fetches each image, once per ticker. Returns
    e.g. "AAPL.png", or None when no source resolved or the download failed.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", ticker.upper())
    return _mirror(safe, lambda: logo_url(ticker), static_dir)


def mirror_brand(key: str, domain: str, static_dir: Path) -> str | None:
    """Mirror a brand-domain logo as `brand-<key>.<ext>`; same contract as
    mirror_logo. The `brand-` stem keeps platform keys clear of tickers."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", key.lower())
    return _mirror(f"brand-{safe}", lambda: brand_logo_url(domain), static_dir)
