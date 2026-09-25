"""Where a visitor came from — read off the URL, logged, never stored in a cookie.

Promotion without measurement is guessing: a post on one forum and a post on
another both produce "some traffic", and nothing says which one produced an
account. This module is the smallest thing that answers it.

What it is, and what it deliberately is not:

* **First-party only.** No third-party script, no pixel, no analytics vendor —
  the facts land in this app's own structured log (`stocks.obs`), next to every
  other event, and `stocks logs funnel` reads them back. The privacy copy in
  `web.legal` promises no tracking cookies and no third-party analytics, and
  this keeps that promise literally.
* **No identifier of any kind.** Nothing here sets a cookie, reads one, or
  fingerprints a browser. What is recorded is a campaign token the *link* was
  built with (`?utm_source=rankia`) plus the referrer's **host** — never its
  path, never the query string it carried.
* **Normalised to a short opaque token.** `_token` keeps `[a-z0-9._+-]`, lower
  cases and truncates: a source is a label to group by in a report, and a log
  field is the last place a stray `?utm_source=<script>` should be able to
  reach. The landing's CTA script only ever forwards what came back out of
  here, so the round trip cannot smuggle anything either.

The chain a click travels, in order:

1. `?utm_source=X` lands on the landing (`server.landing_response` logs
   `landing.view`).
2. The landing's own script copies the token onto its CTA links, so the click
   into the app carries `?src=X` (`landing.source_script`).
3. Crossing into the app logs `landing.cta`; a sign-in click carries the token
   through the OIDC round trip inside `next` (`server.LandingGate`, `oidc`).
4. The account's first `auth.signup` carries `src=X`, and `first_source` is
   written once into its prefs — the logs are kept 30 days, an account is kept
   for as long as it exists.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: Query parameters a source can arrive under, in order of precedence. `utm_*`
#: is what an ad or a newsletter builder writes; `src` is what this app's own
#: links use (shorter, and already past normalisation); `ref` is what a human
#: hand-writes when sharing a link in a forum post.
SOURCE_KEYS = ("utm_source", "src", "ref")
MEDIUM_KEYS = ("utm_medium", "medium")
CAMPAIGN_KEYS = ("utm_campaign", "campaign")

#: The parameter the app's own links carry — the one `carry()` writes and the
#: one the sign-in round trip keeps.
PARAM_SRC = "src"

#: Long enough for "spainfire-weekly", short enough that a log field cannot be
#: used as a smuggling channel.
MAX_LEN = 32

_UNSAFE = re.compile(r"[^a-z0-9._+-]+")

#: Substrings that mean "not a reader". Deliberately crude: the point is a
#: denominator that is not three quarters crawler, not a bot taxonomy.
_BOTS = (
    "bot", "crawl", "spider", "slurp", "curl", "wget", "python-requests",
    "httpx", "http-client", "headlesschrome", "phantomjs", "lighthouse",
    "pagespeed", "googlehc", "uptime", "pingdom", "monitor", "probe",
    "facebookexternalhit", "preview", "scan", "fetcher", "feed",
)


def _token(raw: str | None) -> str:
    """One query value as a log field: lower case, safe characters, truncated."""
    cleaned = _UNSAFE.sub("-", (raw or "").strip().lower()).strip("-")
    return cleaned[:MAX_LEN]


def _pick(params: Mapping[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        if token := _token(params.get(key)):
            return token
    return ""


def source(params: Mapping[str, str]) -> str:
    """The campaign token this URL carries, or "" — `utm_source`, `src`, `ref`."""
    return _pick(params, SOURCE_KEYS)


def medium(params: Mapping[str, str]) -> str:
    return _pick(params, MEDIUM_KEYS)


def campaign(params: Mapping[str, str]) -> str:
    return _pick(params, CAMPAIGN_KEYS)


def ref_host(referer: str | None) -> str:
    """The referring site's host, without the path or query it came with.

    A referrer path is somebody else's page address and can carry their
    reader's state in it; the host is the whole of what a funnel needs.
    """
    if not referer:
        return ""
    host = urlsplit(referer.strip()).hostname or ""
    return _token(host.removeprefix("www."))


def is_bot(user_agent: str | None) -> bool:
    """Whether this User-Agent is a crawler, a probe or a script.

    An empty User-Agent counts as one: browsers always send it, and a funnel
    that counts scripted requests as readers reports a conversion rate that is
    wrong in the flattering direction.
    """
    agent = (user_agent or "").strip().lower()
    if not agent:
        return True
    return any(mark in agent for mark in _BOTS)


def fields(
    params: Mapping[str, str],
    *,
    referer: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """The attribution fields for one request, ready to splat into `obs.event`.

    Empty values are left out rather than logged as "": a log query filters on
    presence, and a field that is always there says nothing.
    """
    out: dict[str, str | bool] = {}
    if src := source(params):
        out["src"] = src
    if med := medium(params):
        out["medium"] = med
    if camp := campaign(params):
        out["campaign"] = camp
    if host := ref_host(referer):
        out["ref"] = host
    if is_bot(user_agent):
        out["bot"] = True
    return out


#: Parameters that say where a visitor came from and nothing else — this app's
#: own vocabulary plus what ad networks and share buttons staple onto a URL.
#: They must not change which document a request gets: a campaign link is still
#: a first visit, and a reader who arrives on `?utm_source=rankia` has to see
#: the pitch rather than be dropped into the app (`server._wants_landing`).
PASSIVE_KEYS = frozenset(
    SOURCE_KEYS + MEDIUM_KEYS + CAMPAIGN_KEYS
    + ("gclid", "fbclid", "mc_cid", "mc_eid", "igshid")
)
PASSIVE_PREFIX = "utm_"


def is_passive(key: str) -> bool:
    """Whether this query parameter is attribution rather than a request."""
    return key.startswith(PASSIVE_PREFIX) or key in PASSIVE_KEYS


def clean_target(target: str) -> str:
    """`target` without its campaign parameters, still site-relative.

    Once the token is on the event and on the account, leaving it in the
    address bar only invites it to be copied into a share of a share and
    re-attributed to the wrong post.
    """
    parts = urlsplit(target)
    kept = [(k, v) for k, v in parse_qsl(parts.query) if not is_passive(k)]
    return urlunsplit(("", "", parts.path or "/", urlencode(kept), parts.fragment))


def carry(params: Mapping[str, str]) -> str:
    """`src=<token>` for an internal redirect that must not lose the source.

    Returns "" when there is nothing to carry, so callers can concatenate it
    without a conditional of their own.
    """
    src = source(params)
    return f"{PARAM_SRC}={src}" if src else ""
