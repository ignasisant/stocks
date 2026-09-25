"""ASGI entry point: the marketing site, the React app, the API — and the old app.

Run: uv run stocks dashboard   (or: uv run uvicorn stocks.web.server:app)

One process on one port, one Starlette app in front of everything:

    /              the landing (English), or the app for a visitor who has one
    /es/           the landing (Spanish)
    /lp/*          the landing's own assets — brand mark, share card
    /robots.txt    crawl rules, generated for whatever host we answer on
    /sitemap.xml   both landing URLs, cross-linked by hreflang
    /livez         liveness probe for uptime checks (scripts/setup_monitoring.sh)
    /healthz       the same probe, for local runs and the Docker HEALTHCHECK
    /status        which revision answers, from which commit (scripts/deploy.sh)
    /legal/*       privacy policy and terms of use (static, bilingual)
    /auth/login, /oauth2callback, /auth/logout   sign-in (web/oidc.py)
    /api/v1/*      the HTTP API (stocks.api) every screen reads through
    /portfolio, /ticker, …   the app: the React shell (frontend/app), one
                   document for every page its router answers
    /next-assets/* that shell's bundle
    /app/static/*  the mirrored logos (same-origin, see stocks.identity)
    /next/*        the shell's address while it was being built, redirected
    /legacy/*      the Streamlit app it replaced, read-only in spirit

`/` is shared: a request for it gets the landing only when it carries no query
parameter and no `ts_app` cookie, which is exactly the state of a first-time
visitor and of every crawler. Any CTA click arrives with a parameter, and the
cookie keeps returning visitors going straight to the app. Crawlers never send
cookies, so the pages Google sees at `/` and `/es/` are the pages a first-time
human sees. The app routes are marked `noindex` on the way out, because they are
a JavaScript shell over somebody's positions.

**Why the Streamlit app is still here.** The React shell replaced it screen for
screen, but "the old one showed something different" is a question worth being
able to answer by looking, for a while. So it is mounted whole at `/legacy`
(`st.App` supports being a sub-application) rather than deleted: same account,
same cookie, same data. It is started on the first request under that prefix,
not at boot, so a deployment nobody opens it on pays nothing for it. The last
commit where it was the app is tagged `streamlit-final`.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from starlette.routing import Mount, Route

from stocks import api, navigation, obs, session
from stocks.secrets_env import secret
from stocks.web import (
    attribution,
    landing,
    landing_static,
    legal,
    oidc,
    ratelimit,
    seo,
)
from stocks.web.landing import (
    ASSET_BASE,
    LANDING_PATHS,
    PATH_EN,
    PATH_ES,
    variant_for,
)

_HERE = Path(__file__).parent
_ASSETS = _HERE / "assets"

# Marks a browser that has already been handed the app. Set on every app
# response, read on `/` alone: without it that request is a first visit and
# gets the pitch, with it the visitor goes where they left off. Not a session
# and not a login — the app decides who is signed in, this only decides which
# document `/` returns.
APP_COOKIE = "ts_app"
_APP_COOKIE_MAX_AGE = 400 * 24 * 3600  # the ceiling Chrome will honour

# Forces the landing even for a returning visitor: `/?landing=1`. Anything else
# in the query string means "take me to the app".
PARAM_LANDING = "landing"

# The app: the React shell (frontend/app), served as one document for every
# page its client router answers (`navigation.SHELL_PATHS`), with its bundle
# under `/next-assets/`. Not under `/app/`: the logo mirror answers
# `/app/static/`, and the API hands those URLs out absolute.
APP_ASSETS = "/next-assets/"
_APP_BUILD = _HERE / "static" / "app"

# Where the shell lived while it was being built beside the Streamlit app.
# Redirected rather than dropped: it was linked from the "what's new" card and
# from Profile, and it is the bank's registered return address
# (`bank.access.APP_PATH`), which is changed in the Enable Banking panel, not
# here.
NEXT_PATH = "/next"

# The retired Streamlit app, mounted whole (see the module docstring).
LEGACY_PATH = "/legacy"

# The mirrored logos. Streamlit's static serving (`enableStaticServing`) used to
# answer this at the root; it now answers it only under `/legacy`, and the API
# hands out `/app/static/logos/…` absolute (`api.loaders.logo`), so the root
# serves the same directory itself.
STATIC_PATH = "/app/static/"
_STATIC = _HERE / "static"


# Where the read-only HTTP API is mounted (stocks.api). Not the marketing site
# and not the app shell either: its clients are cron jobs and scripts, so it is
# exempt from the app cookie below, and the gate has to be told it exists or
# every request under it is answered as a 404.
API_PREFIX = f"{api.MOUNT_PATH}/"

# The marketing site's own paths — deliberately excluding `/`, which is only
# the landing when the gate says so. Anything not listed here is the app, and
# gets stamped noindex on the way out. The probes and the legal pages ride
# along: they are public documents that must not set the app cookie (an uptime
# probe or a privacy-page reader has not "been to the app").
_MARKETING_PREFIXES = (
    *(p for p in LANDING_PATHS if p != PATH_EN),
    ASSET_BASE, "/robots.txt", "/sitemap.xml", "/livez", "/healthz",
    "/status", "/legal/",
)

# A Host header ends up inside canonical and Open Graph URLs, so it is checked
# before it is echoed: hostname characters and an optional port, nothing else.
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:\d+)?$")

_HTML = "text/html; charset=utf-8"

# Paths the canonical-host redirect must leave alone: the old app's transport
# (an in-flight session moves with it and breaks), the OIDC return (the
# hostname is registered with Google and is not ours to change mid-flight),
# and the health probes. Those three answer *about the container handling the
# request*, so sending them to the canonical host defeats their whole purpose:
# a canary lives at a tagged hostname (candidate---<service>…), and redirecting
# its /status hands back the revision already serving 100% of traffic. That is
# how scripts/deploy.sh came to smoke-test the old revision and refuse to
# promote a healthy candidate.
_NEVER_REDIRECT = (f"{LEGACY_PATH}/_stcore/", "/oauth2callback", "/livez",
                   "/healthz", "/status", API_PREFIX)


def _is_marketing_path(path: str) -> bool:
    """True for a path that only ever serves the marketing site.

    `/` is not one of them: the gate answers it with the landing directly, so
    anything that reaches this check for `/` came back from the app and is
    treated as such — which is what marks the browser as a returning visitor.
    """
    return any(path.startswith(p) for p in _MARKETING_PREFIXES)


def public_origin() -> str | None:
    """The one origin this site is meant to be reached at, if it is configured.

    `[app] public_url` (or `APP_PUBLIC_URL`). Unset, every hostname the service
    answers on is its own self-canonicalizing copy of the site — Cloud Run hands
    out more than one by default, so this is not hypothetical. Set, it is both
    the base for every absolute URL and the target every other hostname is
    redirected to.
    """
    override = secret("APP_PUBLIC_URL", "app", "public_url")
    return override.rstrip("/") if override else None


def base_url(request: Request) -> str:
    """Absolute origin for this request, e.g. `https://topstocks.example`.

    Canonical, hreflang, Open Graph and the sitemap all need absolute URLs, and
    this service is deployed at whatever hostname it is given (a `*.run.app`
    URL today), so the origin is derived per request rather than configured.
    Cloud Run terminates TLS and forwards the original scheme and host, which
    is why the forwarded headers win over the socket's own view.

    `[app] public_url` (or `APP_PUBLIC_URL`) overrides the lot — set it once a
    real domain is in front, so a request that reaches the container by its
    internal hostname still emits the public one.
    """
    if origin := public_origin():
        return origin

    forwarded = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded.split(",")[0].strip() or request.url.scheme
    host = (
        request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        or request.headers.get("host", "").strip()
    )
    if not _HOST_RE.match(host or ""):
        host = request.url.netloc
    return f"{scheme}://{host}"


@lru_cache(maxsize=16)
def _gzipped(lang: str, origin: str, jurisdiction: str) -> bytes:
    """The landing document, pre-compressed once per variant and host.

    Streamlit's own gzip middleware sits *inside* this module's, and the gate
    answers before reaching it, so compressing here is what keeps a ~90KB
    document from going out uncompressed. mtime is zeroed to keep the bytes
    reproducible.
    """
    body = landing_static.document(lang, origin, jurisdiction).encode("utf-8")
    return gzip.compress(body, compresslevel=9, mtime=0)


def landing_response(
    request: Request, lang: str, jurisdiction: str | None = None
) -> Response:
    """The landing document for one variant, gzipped when the client takes it."""
    origin = base_url(request)
    obs.event(
        "landing.view",
        lang=lang,
        path=request.url.path,
        **_attribution(request),
    )
    accepts_gzip = "gzip" in request.headers.get("accept-encoding", "").lower()
    jur = jurisdiction or landing.jurisdiction_for(lang)
    root = request.url.path == PATH_EN

    headers = {"Vary": "Accept-Encoding" + (", Cookie" if root else "")}
    if root:
        # `/` answers with two different documents depending on the cookie, so
        # it must be revalidated rather than reused from the browser cache —
        # otherwise the click that sets the cookie would still land on the
        # landing. Every other variant has a path of its own, no cookie split,
        # and can simply be cached.
        headers["Cache-Control"] = "no-cache"
    else:
        headers["Cache-Control"] = "public, max-age=300"

    if accepts_gzip:
        headers["Content-Encoding"] = "gzip"
        return Response(
            _gzipped(lang, origin, jur), media_type=_HTML, headers=headers
        )
    return Response(
        landing_static.document(lang, origin, jur),
        media_type=_HTML,
        headers=headers,
    )


def _wants_landing(request: Request) -> bool:
    """True when this request for `/` should get the pitch instead of the app.

    Nothing asked for in the query and no app cookie — a first-time visitor, or
    a crawler, which sends neither. `?landing=1` asks for it explicitly.

    Campaign parameters do not count as asking for anything: `?utm_source=` is
    how every promoted link is written, and a reader who follows one has to
    arrive at the pitch, not at an app shell over somebody else's demo book.
    `web.attribution.is_passive` is the whole of that exception.
    """
    if request.method not in ("GET", "HEAD"):
        return False
    if PARAM_LANDING in request.query_params:
        return True
    if any(not attribution.is_passive(k) for k in request.query_params):
        return False  # a CTA click, a ?ticker= deep link, an OIDC return
    return request.cookies.get(APP_COOKIE) != "1"


def _request_origin(request: Request) -> str:
    """The origin this request actually arrived on, ignoring the override."""
    scheme = (
        request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        or request.url.scheme
    )
    host = (
        request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        or request.headers.get("host", "").strip()
    )
    if not _HOST_RE.match(host or ""):
        host = request.url.netloc
    return f"{scheme}://{host}"


def canonical_redirect(request: Request) -> str | None:
    """Where this request should have gone, when it arrived on a stray host.

    One site, one hostname: without this, every alias Cloud Run answers on
    serves a full copy of the landing that canonicalizes to itself, which is
    duplicate content in the most literal sense. GET/HEAD only, and never for
    `/_stcore/` — redirecting a live websocket or an XHR would break the
    session a visitor is already in rather than move it. The OIDC callback is
    exempt for the same reason from the other end: Google sends the browser to
    the exact URI registered with it, and bouncing that response to another
    hostname lands the login on an origin the round trip did not start on.
    """
    if request.method not in ("GET", "HEAD"):
        return None
    origin = public_origin()
    if origin is None or origin == _request_origin(request):
        return None
    if request.url.path.startswith(_NEVER_REDIRECT):
        return None
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{origin}{request.url.path}{query}"


def _is_known_path(path: str) -> bool:
    """True for a path something actually serves.

    The shell's router answers any slug with a page — Home, for one it does not
    know — which would make every typo and every stale link a soft 404:
    indexed as nothing, reported in Search Console as a problem, and crawled
    forever. The set below is the whole surface: this module's own pages, the
    shell's pages (`navigation.SHELL_PATHS`), and the machinery prefixes.
    """
    path = path.rstrip("/") or "/"
    if path == PATH_EN or _is_marketing_path(path + "/") or _is_marketing_path(path):
        return True
    if path.startswith(API_PREFIX) or path + "/" == API_PREFIX:
        return True
    if path.startswith(APP_ASSETS) or path.startswith(STATIC_PATH):
        return True
    if path in (NEXT_PATH, LEGACY_PATH) or path.startswith(
        (NEXT_PATH + "/", LEGACY_PATH + "/")
    ):
        return True
    if path in seo.app_page_paths() or path in seo.APP_PATHS:
        return True
    return any(path.startswith(pre) or path + "/" == pre for pre in seo.APP_PREFIXES)


def not_found(request: Request) -> Response:
    """A real 404, with just enough page to be worth landing on."""
    home = PATH_ES if request.url.path.startswith(PATH_ES) else PATH_EN
    body = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="robots" content="noindex">'
        "<title>404 — TopStocks</title>"
        f'<style>body{{background:{seo.THEME_COLOR};color:#fff;font:16px/1.6 '
        "system-ui,sans-serif;display:grid;place-content:center;height:100vh;"
        "margin:0;text-align:center}a{color:#fff}</style></head><body>"
        f'<h1>404</h1><p>Nothing at this address. <a href="{home}">TopStocks</a></p>'
        "</body></html>"
    )
    return Response(body, status_code=404, media_type=_HTML,
                    headers={"X-Robots-Tag": "noindex"})


# Requests one client may make per window before it is turned away. Counted
# per document, not per asset: one page load pulls a dozen bundle chunks, and
# the old app's every websocket frame is a chat message, so metering those
# would either lock out a normal first visit or have to be set so high it
# meters nothing.
# Documents are the expensive part anyway — a landing render, an app shell.
CLIENT_MAX_DOCS = 60
CLIENT_WINDOW_S = 60

# Not metered: the transport the old app needs to keep a session alive (it has
# its own per-account limit on what arrives over it, see web/ratelimit.py's use
# in chat_core) and its bundle, the mirrored logos, the shell's bundle and the
# landing's assets, and the probes an uptime monitor hits on a schedule.
_UNMETERED = (
    *(f"{LEGACY_PATH}{p}" for p in ("/_stcore/", "/static/", "/app/static/",
                                     "/media/", "/component/")),
    ASSET_BASE, "/livez", "/healthz", STATIC_PATH, APP_ASSETS,
)

# The API gets its own budget, on its own key. A document and an API call are
# not the same unit of work: the shell's ticker page asks for its price bars,
# quote, calendar, position, KPIs, financials, valuation, moat, insiders, fund
# and peers separately, so one page view is around twenty requests here where
# it is one on the document path. Metered against CLIENT_MAX_DOCS, three
# tickers in a minute would 429 a reader doing nothing unusual.
#
# Separate keys, not just a bigger number: a burst of API calls must not be
# able to lock somebody out of the app shell, and a reload loop on the shell
# must not take the data with it.
API_MAX_REQUESTS = 300

# Both moved to `web/ratelimit.py`, beside the limiter they key, because the
# API needs the same answer for `POST /v1/feedback` from a guest and cannot
# import this module — it is the one that mounts the API. Re-exported under the
# names they have always had here: this is where a reader looks for them, and
# `tests/test_throttle.py` asks for them by this path.
TRUSTED_PROXY_HOPS = ratelimit.TRUSTED_PROXY_HOPS
client_ip = ratelimit.client_ip


class ClientThrottle(BaseHTTPMiddleware):
    """Per-client burst limit on document requests, outermost in the stack.

    The service runs at --max-instances 1, so one container answers everyone:
    a script hammering `/` does not just cost egress, it takes the app away
    from real users. The app's own limiter (web/ratelimit.py) only starts
    after a Google sign-in, which leaves everything before the login unmetered
    — this is that half.

    Fails open. A limiter that starts refusing traffic because of a bug in
    itself is worse than the flood it was added to stop.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _UNMETERED):
            return await call_next(request)
        is_api = path.startswith(API_PREFIX)
        try:
            key = f"{'api' if is_api else 'http'}::{client_ip(request)}"
            allowed = ratelimit.allow(
                key,
                max_events=API_MAX_REQUESTS if is_api else CLIENT_MAX_DOCS,
                window_s=CLIENT_WINDOW_S,
            )
        except Exception:
            return await call_next(request)
        if not allowed:
            wait = ratelimit.retry_after(key, window_s=CLIENT_WINDOW_S)
            obs.warn("http.throttled", path=path, retry_after=wait)
            headers = {"Retry-After": str(max(1, wait))}
            if is_api:
                # The API answers in JSON everywhere else, including its own
                # 503 for an upstream that is rate limiting us. A caller that
                # parses every other refusal should not have to special-case
                # this one into a text body, and `reason` is the field it
                # already switches on.
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "too many requests from this client",
                        "reason": "throttled",
                    },
                    headers=headers,
                )
            return Response("Too many requests\n", status_code=429,
                            media_type="text/plain; charset=utf-8",
                            headers=headers)
        return await call_next(request)


class SecurityHeaders(BaseHTTPMiddleware):
    """Baseline hardening headers on every response, marketing and app alike.

    Deliberately not a full Content-Security-Policy: Streamlit's shell relies
    on inline scripts/styles and a websocket, so a source allowlist would
    either break the app or be wide enough to mean nothing. What is set here
    is the uncontroversial floor:

    * `nosniff` — responses execute as their declared type only.
    * `frame-ancestors 'self'` (+ the legacy X-Frame-Options) — nobody frames
      the app on another origin to clickjack a logged-in session. Streamlit's
      own component iframes are same-origin and unaffected.
    * a tight Referrer-Policy — app URLs can carry tickers and view state;
      other origins get the origin, not the path.
    * HSTS, only when the request already arrived on TLS (Cloud Run
      terminates it and forwards the scheme): a plain-HTTP local dev run
      must not teach the browser to refuse http://localhost.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy",
                     "camera=(), microphone=(), geolocation=()")
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        if (proto or request.url.scheme) == "https":
            h.setdefault("Strict-Transport-Security",
                         "max-age=31536000; includeSubDomains")
        return response


def _attribution(request: Request) -> dict:
    """Where this request came from, as log fields (see `web.attribution`)."""
    return attribution.fields(
        request.query_params,
        referer=request.headers.get("referer"),
        user_agent=request.headers.get("user-agent"),
    )


def _entry_kind(request: Request) -> str:
    """Which door this browser came through on its first app document.

    "guest" and "signin" are the landing's two calls to action; "link" is a URL
    somebody shared with a source token on it (including the return leg of a
    sign-in, which carries the token home); "direct" is everything else — a
    bookmark, a typed address, a deep link from a chat window.
    """
    params = request.query_params
    if landing.PARAM_GUEST in params:
        return "guest"
    if landing.PARAM_SIGNIN in params:
        return "signin"
    return "link" if attribution.source(params) else "direct"


class LandingGate(BaseHTTPMiddleware):
    """Serves the landing at `/`, and keeps the app out of search indexes.

    Middleware rather than a route because `/` has two owners: the landing for
    a first visit, the app shell for everyone else, and the shell's route is
    the one that answers once the gate lets a request through.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (target := canonical_redirect(request)) is not None:
            return RedirectResponse(target, status_code=301)
        # `?signin=1` on the landing is a request to sign in, and this is the
        # first place that can answer it with a real redirect. Guarded on the
        # session so a stale parameter cannot bounce somebody who is already
        # signed in back out to Google.
        if (
            path == PATH_EN
            and landing.PARAM_SIGNIN in request.query_params
            and not session.signed_in_email(request.cookies)
        ):
            obs.event("landing.cta", kind="signin", **_attribution(request))
            # `next` is where the callback sends the browser once Google is
            # done, so it is also the only place a source token can wait out
            # the round trip — there is no cookie of ours to park it in, and
            # the referrer is Google by then.
            lang = request.query_params.get("lang")
            carried = "&".join(
                part
                for part in (
                    f"lang={lang}" if lang else "",
                    attribution.carry(request.query_params),
                )
                if part
            )
            target = f"?{carried}" if carried else ""
            return RedirectResponse(
                f"{session.LOGIN_PATH}?next={quote(f'/{target}')}", status_code=302
            )

        if path == PATH_EN and _wants_landing(request):
            return landing_response(request, "en")
        if not _is_known_path(path):
            return not_found(request)

        response = await call_next(request)

        if not _is_marketing_path(path):
            # Everything that is not the marketing site is the app: a shell
            # over private positions, or transport. Out of the index, and the
            # browser is now known to have been there.
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
            # …but only a browser gets marked as having been to the app. An API
            # client is not one, and a Set-Cookie on its responses would be
            # noise at best and a stored credential it never asked for at worst.
            if not path.startswith(API_PREFIX) and request.cookies.get(APP_COOKIE) != "1":
                # First app document this browser has been handed: the step
                # between "read the pitch" and "has an account", and the only
                # one no other event covers.
                obs.event(
                    "landing.cta",
                    kind=_entry_kind(request),
                    path=path,
                    **_attribution(request),
                )
                response.set_cookie(
                    APP_COOKIE,
                    "1",
                    max_age=_APP_COOKIE_MAX_AGE,
                    path="/",
                    httponly=True,
                    samesite="lax",
                )
        return response


async def variant_landing(request: Request) -> Response:
    """Any landing path but `/`: the language and jurisdiction it stands for.

    One handler for all of them — the path *is* the variant (landing.VARIANTS),
    so another pair needs a route and no new code.
    """
    lang, jur = variant_for(request.url.path) or ("es", "ES")
    return landing_response(request, lang, jur)


async def variant_redirect(request: Request) -> Response:
    """`/es` -> `/es/`: one canonical address per variant, permanently."""
    path = request.url.path
    target = next(
        (p for p in LANDING_PATHS if p.rstrip("/") == path.rstrip("/")), PATH_ES
    )
    return RedirectResponse(target, status_code=301)


def _landing_sources() -> list[Path]:
    """The files whose content *is* the landing page."""
    sources = [_HERE / "landing.py", _HERE / "landing_static.py", _HERE / "seo.py"]
    return sources + sorted(_HERE.glob("locales/*/landing.json"))


def _git_lastmod(sources: list[Path]) -> str | None:
    """The newest commit date among `sources`, when this is a git checkout.

    Preferred over mtime because mtime is a property of the filesystem, not of
    the content: a fresh clone (or any CI build) stamps every file with the
    checkout time and would have the sitemap claim the copy changed today.
    Deployed images carry no `.git`, so this returns None there and the mtime
    path below takes over — correct, because the source upload preserves the
    times the files really had.
    """
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", *[str(p) for p in sources]],
            cwd=_HERE, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    date = out.stdout.strip()
    if out.returncode != 0 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    return date


@lru_cache(maxsize=1)
def _lastmod() -> str:
    """The landing's own modification date, for the sitemap.

    The markup, the copy and the metadata are the page, so their newest change
    is the honest answer — and it beats a build timestamp (which would claim a
    change on every redeploy) or a hard-coded date (which would go stale
    silently). Git first, mtime second; see `_git_lastmod`.
    """
    sources = _landing_sources()
    if (from_git := _git_lastmod(sources)) is not None:
        return from_git
    stamps = [p.stat().st_mtime for p in sources if p.exists()]
    newest = max(stamps) if stamps else 0
    return datetime.fromtimestamp(newest, UTC).strftime("%Y-%m-%d")


async def robots(request: Request) -> Response:
    return Response(
        seo.robots_txt(base_url(request)),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


async def sitemap(request: Request) -> Response:
    return Response(
        seo.sitemap_xml(base_url(request), lastmod=_lastmod()),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


async def healthz(request: Request) -> Response:
    """Liveness for uptime checks: the ASGI stack answers, nothing deeper.

    Served at both /livez and /healthz. /livez is the one to probe from
    outside: on Cloud Run a request for /healthz is answered by Google's
    frontend with its own 404 and never reaches the container (no
    x-cloud-trace-context on the response, no entry in the request log),
    so the route below is unreachable in production. /healthz is kept
    because it does work everywhere else — local runs, the Docker
    HEALTHCHECK, any other host.

    Deliberately no storage or market-data round trip — this runs once a
    minute from several regions, and a dependency blip should page through
    the error-rate alert (which sees the real user impact), not by taking
    the whole service "down" in the uptime check.
    """
    return Response(
        '{"status":"ok"}',
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


_BOOTED = datetime.now(UTC)


async def status(request: Request) -> Response:
    """`/status` — a shade more than liveness, still zero round trips.

    What it adds over `/healthz`: which revision is answering and the commit it
    was built from, how long this container has been up (a suspiciously young
    uptime during an incident means crash-looping), and whether persistence is
    configured. Deliberately
    no storage or market-data probe — this must stay cheap enough to curl in
    a loop mid-incident. See docs/RUNBOOK.md.
    """
    from stocks import storage

    body = {
        "status": "ok",
        "revision": os.getenv("K_REVISION", "dev"),
        # The commit the revision was built from — scripts/deploy.sh sets it.
        # Without it, "is prod running the last version?" is archaeology on
        # build timestamps; with it, it is one curl against one `git log`.
        "commit": os.getenv("STOCKS_COMMIT", "dev"),
        "uptime_s": int((datetime.now(UTC) - _BOOTED).total_seconds()),
        "storage": storage.enabled(),
    }
    return Response(
        json.dumps(body),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


async def legal_page(request: Request) -> Response:
    doc = request.path_params["doc"]
    if doc not in ("privacy", "terms"):
        return not_found(request)
    lang = request.query_params.get("lang", "en")
    return Response(
        legal.document(doc, lang),
        media_type=_HTML,
        headers={"Cache-Control": "public, max-age=3600", "Vary": "Accept-Encoding"},
    )


@lru_cache(maxsize=1)
def _app_document(mtime: float) -> bytes:  # noqa: ARG001 — mtime keys the cache
    """The shell's index.html with the design tokens inlined.

    `ds_vars_css()` replaces the `<!--AG-TOKENS-->` marker so the page paints in
    the right colours on its first frame and the charts read their palette back
    out of those custom properties instead of fetching them, and `_faces()`
    replaces `<!--AG-FONTS-->` with the stylesheet that makes it the app's
    typeface rather than the system's — and the tab its icon, which the
    landing's own mark is.
    """
    from stocks.web.widgets import ds_vars_css

    html = (_APP_BUILD / "index.html").read_text(encoding="utf-8")
    html = html.replace("<!--AG-TOKENS-->", ds_vars_css())
    icon = f'<link rel="icon" type="image/svg+xml" href="{ASSET_BASE}topstocks-icon.svg">'
    return html.replace("<!--AG-FONTS-->", _faces() + icon).encode("utf-8")


def _faces() -> str:
    """Link tags for the DS typefaces.

    `seo.FONTS_HREF` is the stylesheet the landing already links; Streamlit
    loads the same faces from config.toml. A React document that links neither
    declares Instrument Sans in its CSS and paints in system-ui — which reads
    as nothing being wrong.
    """
    from stocks.web.seo import FONTS_HREF

    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link rel="stylesheet" href="{FONTS_HREF}">'
    )


async def app_shell(request: Request) -> Response:
    """Every page of the app — the client router reads the path.

    Serving one document for every page is what makes a deep link work:
    /portfolio?tab=fees has to survive a reload, and the page it names is
    drawn in the browser.
    """
    index = _APP_BUILD / "index.html"
    if not index.is_file():
        # A checkout that never ran `npm run build`. CI refuses to merge one
        # (the bundle is committed and checked), so this is a local run.
        return Response("The app is not built: cd frontend/app && npm run build\n",
                        status_code=503, media_type="text/plain")
    return Response(
        _app_document(index.stat().st_mtime),
        media_type=_HTML,
        # A shell over somebody's book, with the tokens inlined into it: never
        # a cacheable file.
        headers={"Cache-Control": "no-store"},
    )


async def next_redirect(request: Request) -> Response:
    """`/next/<page>` → `/<page>`, query and all, permanently."""
    rest = request.path_params.get("path", "").strip("/")
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/{rest}{query}", status_code=301)


async def legacy_slash(request: Request) -> Response:
    """`/legacy` → `/legacy/`: the old app resolves its assets from the slash."""
    return RedirectResponse(f"{LEGACY_PATH}/", status_code=301)


async def static_file(request: Request) -> Response:
    """`/app/static/<file>` — the mirrored logos, from the directory they land in."""
    name = request.path_params.get("path", "")
    target = (_STATIC / name).resolve()
    if _STATIC.resolve() not in target.parents or not target.is_file():
        return Response("Not found", status_code=404, media_type="text/plain")
    return FileResponse(target, headers={"Cache-Control": "public, max-age=86400"})


async def app_asset(request: Request) -> Response:
    """`/next-assets/<file>` — the shell's own bundle, stylesheet and chunks.

    Short cache: a rebuild reuses the same filenames, and a long max-age would
    serve yesterday's bundle against today's API.
    """
    name = request.path_params.get("path", "")
    target = (_APP_BUILD / name).resolve()
    if _APP_BUILD.resolve() not in target.parents or not target.is_file():
        return Response("Not found", status_code=404, media_type="text/plain")
    return FileResponse(target, headers={"Cache-Control": "public, max-age=300"})


async def asset(request: Request) -> Response:
    """`/lp/<file>` — the landing's brand mark and share card.

    Its own mount rather than Streamlit's `app/static`: that one is served at a
    path relative to wherever the app document lives, which `/es/` is one
    segment away from, and these files have to resolve from both pages.
    """
    name = request.path_params.get("path", "")
    target = (_ASSETS / name).resolve()
    if _ASSETS.resolve() not in target.parents or not target.is_file():
        return Response("Not found", status_code=404, media_type="text/plain")
    return FileResponse(
        target, headers={"Cache-Control": "public, max-age=3600"}
    )


# The retired Streamlit app. The script path is absolute on purpose: `st.App`
# resolves a relative one against the working directory when an ASGI server
# (rather than `streamlit run`) loads it.
legacy = st.App(str(_HERE / "app.py"))

routes = [
    *(
        Route(p, variant_landing, methods=["GET", "HEAD"])
        for p in LANDING_PATHS
        if p != PATH_EN
    ),
    *(
        Route(p.rstrip("/"), variant_redirect, methods=["GET", "HEAD"])
        for p in LANDING_PATHS
        if p != PATH_EN
    ),
    Route("/robots.txt", robots, methods=["GET", "HEAD"]),
    Route("/sitemap.xml", sitemap, methods=["GET", "HEAD"]),
    Route("/livez", healthz, methods=["GET", "HEAD"]),
    Route("/healthz", healthz, methods=["GET", "HEAD"]),
    Route("/status", status, methods=["GET", "HEAD"]),
    Route("/legal/{doc:str}", legal_page, methods=["GET", "HEAD"]),
    Route(f"{ASSET_BASE}{{path:path}}", asset, methods=["GET", "HEAD"]),
    Route(f"{APP_ASSETS}{{path:path}}", app_asset, methods=["GET", "HEAD"]),
    Route(f"{STATIC_PATH}{{path:path}}", static_file, methods=["GET", "HEAD"]),
    *oidc.routes(),
    Mount(api.MOUNT_PATH, app=api.app),
    # `/` is the shell for whoever the gate lets through (see LandingGate).
    Route("/", app_shell, methods=["GET", "HEAD"]),
    *(Route(f"/{slug}", app_shell, methods=["GET", "HEAD"])
      for slug in navigation.SHELL_PATHS),
    Route(NEXT_PATH, next_redirect, methods=["GET", "HEAD"]),
    Route(f"{NEXT_PATH}/{{path:path}}", next_redirect, methods=["GET", "HEAD"]),
    Route(LEGACY_PATH, legacy_slash, methods=["GET", "HEAD"]),
    Mount(LEGACY_PATH, app=legacy),
]


@asynccontextmanager
async def lifespan(app: Starlette):
    """Run the API's boot work, which its own lifespan cannot do from here.

    Starlette does not run a mounted sub-application's lifespan, so without
    this `api.app`'s — the one that provisions the shared guest book — never
    runs in the deployed process, and every anonymous request reads a ledger
    that does not exist.
    """
    async with api.app.router.lifespan_context(api.app):
        yield


app = Starlette(
    routes=routes,
    lifespan=lifespan,
    # First is outermost: the security headers wrap everything, including the
    # gate's own short-circuit responses (landing, redirects, 404s). Compression
    # sits inside them and skips what is already compressed (the landing, the
    # old app's own gzip) and what must not be buffered (the chat's stream).
    middleware=[
        Middleware(ClientThrottle),
        Middleware(SecurityHeaders),
        Middleware(GZipMiddleware, minimum_size=1024),
        Middleware(LandingGate),
    ],
)
