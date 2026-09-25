"""The routing in front of the app.

`/` is shared: the landing for a visitor who has neither a query parameter nor
the app cookie, the app for everyone else. That rule is the whole design (see
`stocks.web.server`), and it is the one thing here that could go wrong in a way
nobody notices — a leak in either direction either hides the app from returning
users or hides the pitch from Google.

The app shell is a stand-in document on disk, and the retired Streamlit app at
`/legacy` is stubbed with a catch-all. Booting the real one would need a
runtime, a websocket and a secrets file; what these tests are about is which
requests reach each at all, and what the response carries when they do.
"""

import asyncio

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from stocks import session
from stocks.web import landing_static, server

STUB = "APP-SHELL"
LEGACY = "STREAMLIT-APP"


@pytest.fixture(autouse=True)
def shell(tmp_path, monkeypatch):
    """A built shell on disk: markers to fill, and a line to recognise it by."""
    build = tmp_path / "app"
    build.mkdir()
    (build / "index.html").write_text(
        f"<html><head><!--AG-TOKENS--><!--AG-FONTS--></head><body>{STUB}</body></html>"
    )
    (build / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(server, "_APP_BUILD", build)
    server._app_document.cache_clear()
    yield build
    server._app_document.cache_clear()


def _legacy_stub() -> Starlette:
    async def stub(request):
        return PlainTextResponse(LEGACY, media_type="text/html")

    return Starlette(routes=[Route("/{path:path}", stub, methods=["GET", "POST"])])


def served(*middleware: type) -> Starlette:
    """server.py's routes behind `middleware`, the old app stubbed out."""
    routes = [
        Mount(server.LEGACY_PATH, app=_legacy_stub())
        if isinstance(r, Mount) and r.path == server.LEGACY_PATH
        else r
        for r in server.routes
    ]
    return Starlette(routes=routes, middleware=[Middleware(m) for m in middleware])


@pytest.fixture
def client(monkeypatch):
    """server.py's routes and gate."""
    landing_static.document.cache_clear()
    server._gzipped.cache_clear()
    # No secrets file in the test environment; make the override explicit so a
    # developer's own [app] public_url cannot change the expected URLs.
    monkeypatch.setattr(server, "secret", lambda *a, **k: "")
    app = served(server.SecurityHeaders, server.LandingGate)
    return TestClient(app, base_url="https://topstocks.example")


# ------------------------------------------------------------------ the gate


def test_a_first_visit_gets_the_landing(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'property="og:title"' in r.text
    assert STUB not in r.text


def test_a_crawler_gets_the_landing(client):
    """Crawlers send no cookies, so they always see the page a visitor sees."""
    r = client.get("/", headers={"User-Agent": "Googlebot/2.1"})
    assert 'rel="canonical"' in r.text


def test_a_cta_click_goes_to_the_app(client):
    r = client.get("/?guest=1")
    assert STUB in r.text


def test_a_ticker_deep_link_goes_to_the_app(client):
    r = client.get("/?ticker=AAPL")
    assert STUB in r.text


def test_the_app_response_marks_the_browser_and_the_next_visit_skips_the_pitch(client):
    assert STUB in client.get("/?guest=1").text
    assert client.cookies.get(server.APP_COOKIE) == "1"
    # cookie now on the client — a bare "/" is a returning visitor
    assert STUB in client.get("/").text


def test_the_landing_can_still_be_asked_for(client):
    client.cookies.set(server.APP_COOKIE, "1")
    assert 'property="og:title"' in client.get("/?landing=1").text


def test_a_post_to_the_root_is_never_the_landing(client):
    assert 'property="og:title"' not in client.post("/").text


def test_app_pages_are_untouched_by_the_gate(client):
    assert STUB in client.get("/portfolio").text


# --------------------------------------------------------------- index policy


def test_the_app_is_marked_noindex(client):
    """A JavaScript shell over somebody's positions has no business ranking."""
    for path in ("/portfolio", "/?guest=1", "/legacy/_stcore/health"):
        assert client.get(path).headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.parametrize(
    "path", ["/", "/es/", "/en-es/", "/es-us/", "/robots.txt", "/sitemap.xml"]
)
def test_the_marketing_pages_are_indexable(client, path):
    assert "x-robots-tag" not in client.get(path).headers


def test_only_the_root_is_revalidated_the_other_variants_are_cacheable(client):
    """`/` alone answers two documents on a cookie; the rest have own URLs."""
    en = client.get("/")
    assert en.headers["cache-control"] == "no-cache"
    assert "Cookie" in en.headers["vary"]
    for path in ("/es/", "/en-es/", "/es-us/"):
        r = client.get(path)
        assert r.headers["cache-control"] == "public, max-age=300"
        assert "Cookie" not in r.headers["vary"]


# ------------------------------------------------------------------- spanish


def test_the_spanish_page_is_served_in_spanish(client):
    r = client.get("/es/")
    assert r.status_code == 200
    assert 'lang="es"' in r.text
    assert "Tu rentabilidad real" in r.text


@pytest.mark.parametrize("path", ["/es", "/en-es", "/es-us"])
def test_an_unslashed_landing_url_redirects_once_and_permanently(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == f"{path}/"


# ------------------------------------------------- language x tax jurisdiction
# Four pages: the pitch is one country's case, and language and tax residence
# are independent (an English reader who files in Spain, a Spanish reader who
# files in the US).


def test_the_english_root_argues_the_us_rules(client):
    r = client.get("/")
    assert 'lang="en"' in r.text
    assert "IRS" in r.text and "Modelo 720" not in r.text


def test_the_english_spain_page_argues_the_spanish_rules(client):
    r = client.get("/en-es/")
    assert r.status_code == 200
    assert 'lang="en"' in r.text
    assert "Modelo 720" in r.text and "IRC 1091" not in r.text
    assert 'rel="canonical" href="https://topstocks.example/en-es/"' in r.text


def test_the_spanish_us_page_argues_the_us_rules(client):
    r = client.get("/es-us/")
    assert r.status_code == 200
    assert 'lang="es"' in r.text
    assert "IRC 1091" in r.text and "Modelo 720" not in r.text
    assert 'rel="canonical" href="https://topstocks.example/es-us/"' in r.text


def test_the_cross_variants_pair_with_their_own_language_alternate(client):
    """hreflang pairs translations, never two different countries' arguments."""
    r = client.get("/en-es/")
    assert 'hreflang="es" href="https://topstocks.example/es/"' in r.text
    assert 'hreflang="en" href="https://topstocks.example/en-es/"' in r.text


# --------------------------------------------------------- robots and sitemap


def test_robots_is_generated_for_the_host_that_answered(client):
    r = client.get("/robots.txt", headers={"X-Forwarded-Host": "topstocks.dev"})
    assert r.headers["content-type"].startswith("text/plain")
    assert "Sitemap: https://topstocks.dev/sitemap.xml" in r.text


def test_the_forwarded_scheme_wins_over_the_socket(client):
    """Cloud Run terminates TLS; the container itself sees plain HTTP."""
    r = client.get(
        "/robots.txt",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "topstocks.dev"},
    )
    assert "https://topstocks.dev" in r.text


def test_a_spoofed_host_cannot_get_into_the_canonical_url(client):
    r = client.get("/", headers={"X-Forwarded-Host": "evil.example/../x"})
    assert "evil.example" not in r.text


def test_the_sitemap_is_xml_with_both_pages(client):
    r = client.get("/sitemap.xml")
    assert r.headers["content-type"].startswith("application/xml")
    assert "<loc>https://topstocks.example/</loc>" in r.text
    assert "<loc>https://topstocks.example/es/</loc>" in r.text
    assert "<lastmod>" in r.text


# -------------------------------------------------------------------- assets


def test_the_brand_mark_is_served(client):
    r = client.get("/lp/topstocks-icon.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")
    assert "max-age" in r.headers["cache-control"]


def test_the_share_card_is_served(client):
    r = client.get("/lp/og.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


@pytest.mark.parametrize("name", ["..%2fapp.py", "%2e%2e/app.py", "nope.svg"])
def test_the_asset_mount_serves_nothing_outside_itself(client, name):
    assert client.get(f"/lp/{name}").status_code == 404


@pytest.mark.parametrize("name", ["../app.py", "../../../etc/passwd", "sub/../../x"])
def test_the_asset_handler_refuses_to_escape_its_directory(name):
    """Checked against the handler directly: an HTTP client normalises `..`
    out of the path before it is ever sent, so the client cannot express this."""

    class _Req:
        path_params = {"path": name}

    assert asyncio.run(server.asset(_Req())).status_code == 404


# ---------------------------------------------------------------- compression


def test_the_document_is_compressed_when_the_client_takes_it(client):
    plain = client.get("/", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers

    # TestClient transparently decodes, so the check is on the header and on
    # the fact that the decoded body is the same page.
    gzipped = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert gzipped.headers["content-encoding"] == "gzip"
    assert gzipped.text == plain.text
    assert "Accept-Encoding" in gzipped.headers["vary"]


# --------------------------------------------------------- one canonical host


@pytest.fixture
def pinned_client(monkeypatch):
    """The same app, with `[app] public_url` pinned to one origin."""
    landing_static.document.cache_clear()
    server._gzipped.cache_clear()
    monkeypatch.setattr(server, "secret", lambda *a, **k: "https://topstocks.example")
    return TestClient(served(server.LandingGate), base_url="https://alias.run.app")


def test_a_stray_hostname_is_redirected_to_the_canonical_one(pinned_client):
    r = pinned_client.get("/es/", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "https://topstocks.example/es/"


def test_the_redirect_keeps_the_query_string(pinned_client):
    r = pinned_client.get("/ticker?ticker=AAPL", follow_redirects=False)
    assert r.headers["location"] == "https://topstocks.example/ticker?ticker=AAPL"


def test_a_live_session_is_not_redirected_out_from_under_itself(pinned_client):
    # Moving a websocket or an XHR mid-session breaks the page the visitor is
    # already looking at; the document redirect is what moves them.
    assert pinned_client.get("/legacy/_stcore/health").status_code == 200


def test_the_health_probes_answer_on_any_host(pinned_client):
    # A canary is reachable only at its tagged hostname, so a redirect to the
    # canonical host would smoke the revision already serving and report its
    # revision name — which is exactly how a healthy candidate gets rejected.
    for path in ("/livez", "/healthz", "/status"):
        r = pinned_client.get(path, follow_redirects=False)
        assert r.status_code == 200, path
        assert r.json()["status"] == "ok"


def test_the_canonical_host_itself_is_served_not_redirected(monkeypatch):
    monkeypatch.setattr(server, "secret", lambda *a, **k: "https://topstocks.example")
    client = TestClient(served(server.LandingGate), base_url="https://topstocks.example")
    assert client.get("/es/", follow_redirects=False).status_code == 200


def test_without_a_public_url_every_host_is_served_as_is(client):
    assert client.get("/es/", follow_redirects=False).status_code == 200


# ------------------------------------------------------------- real not-founds


def test_an_unknown_path_is_a_404_not_the_app_shell(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404
    assert STUB not in r.text
    assert r.headers["X-Robots-Tag"] == "noindex"


@pytest.mark.parametrize(
    "path",
    ["/portfolio", "/ticker", "/sector", "/earnings", "/profile",
     "/import_transactions", "/import", "/home", "/bank",
     "/legacy/", "/legacy/portfolio", "/legacy/_stcore/health",
     "/legacy/media/abc", "/legacy/component/x/y"],
)
def test_everything_that_is_really_served_survives_the_gate(client, path):
    assert client.get(path).status_code == 200


def test_a_trailing_slash_on_a_real_page_is_not_a_404(client):
    assert client.get("/portfolio/").status_code == 200


def test_the_page_list_comes_from_the_navigation_table():
    # A page added to the shell must not need a second edit here to be
    # reachable — that drift is exactly what would 404 a live page.
    from stocks.web import seo

    assert "/portfolio" in seo.app_page_paths()
    assert all(server._is_known_path(p) for p in seo.app_page_paths())


@pytest.mark.parametrize(
    "path", [session.LOGIN_PATH, session.LOGOUT_PATH, session.CALLBACK_PATH]
)
def test_our_auth_routes_answer(client, path):
    """A 302 from our own handler, not a 404 from the gate and not the shell:
    the redirect URI registered with Google points here."""
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 302


def test_the_signin_parameter_bounces_into_the_apps_own_sign_in(client):
    """The landing's CTA. It used to reach `st.login()` inside a Streamlit run;
    it is answered here now, because this is the layer that can return a 302."""
    r = client.get("/?signin=1", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith(session.LOGIN_PATH)


def test_the_signin_parameter_is_ignored_once_signed_in(client, monkeypatch):
    """The parameter survives the round trip; acting on it twice would loop."""
    monkeypatch.setattr(server.session, "signed_in_email", lambda cookies: "a@b.com")
    assert STUB in client.get("/?signin=1").text


def test_the_signin_parameter_keeps_the_language_it_was_pressed_in(client):
    r = client.get("/?signin=1&lang=es", follow_redirects=False)
    assert "lang%3Des" in r.headers["location"]


def test_the_oidc_callback_is_never_bounced_to_another_host(pinned_client):
    # Google sends the browser to the exact URI registered with it; finishing
    # that round trip on a different origin is how a login silently breaks.
    r = pinned_client.get("/oauth2callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code != 301
    assert r.headers.get("location", "/").startswith("/")


# ------------------------------------------------------------------ liveness


@pytest.mark.parametrize("path", ["/livez", "/healthz"])
def test_liveness_answers_without_touching_the_app(client, path):
    # Two paths, one handler. /livez is the one monitoring probes: Google's
    # frontend answers /healthz itself on Cloud Run, so the route never runs
    # there — it stays for local runs and the Docker HEALTHCHECK.
    r = client.get(path)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["cache-control"] == "no-store"
    # An uptime probe has not "been to the app": no returning-visitor cookie,
    # or the checks themselves would flip what `/` serves to real monitors.
    assert "set-cookie" not in r.headers


def test_status_reports_revision_uptime_and_storage(client, monkeypatch):
    monkeypatch.setenv("K_REVISION", "topstocks-00042-abc")
    monkeypatch.setenv("STOCKS_COMMIT", "3ea8bbf0")
    r = client.get("/status")
    body = r.json()
    assert body["status"] == "ok"
    assert body["revision"] == "topstocks-00042-abc"
    # The deploy stamps the commit, so the answer to "what is prod running"
    # is served by the app itself rather than guessed from build times.
    assert body["commit"] == "3ea8bbf0"
    assert body["uptime_s"] >= 0
    assert body["storage"] is False  # no [storage] in the test env
    assert "set-cookie" not in r.headers


# --------------------------------------------------------------- legal pages


def test_the_legal_pages_are_served_in_both_languages(client):
    for doc in ("privacy", "terms"):
        en = client.get(f"/legal/{doc}")
        assert en.status_code == 200
        assert 'lang="en"' in en.text
        es = client.get(f"/legal/{doc}?lang=es")
        assert 'lang="es"' in es.text
        assert "set-cookie" not in en.headers


def test_the_terms_lead_with_the_investment_disclaimer(client):
    assert "not investment advice" in client.get("/legal/terms").text.lower()


def test_an_unknown_legal_doc_is_a_404(client):
    assert client.get("/legal/nonsense").status_code == 404


def test_the_landing_links_the_legal_pages(client):
    html = client.get("/").text
    assert 'href="/legal/privacy"' in html
    assert 'href="/legal/terms"' in html
    assert 'href="/legal/privacy?lang=es"' in client.get("/es/").text


# ---------------------------------------------------------- security headers


def test_every_response_carries_the_baseline_headers(client):
    for path in ("/", "/portfolio", "/legal/privacy", "/no-such-page"):
        h = client.get(path).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "SAMEORIGIN"
        assert h["content-security-policy"] == "frame-ancestors 'self'"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in h["permissions-policy"]


def test_hsts_is_set_on_tls_and_not_on_local_http(client, monkeypatch):
    assert "strict-transport-security" in client.get("/").headers

    monkeypatch.setattr(server, "secret", lambda *a, **k: "")

    async def stub(request):
        return PlainTextResponse(STUB, media_type="text/html")

    plain = TestClient(
        Starlette(
            routes=[Route("/{path:path}", stub, methods=["GET"])],
            middleware=[Middleware(server.SecurityHeaders)],
        ),
        base_url="http://localhost:8501",
    )
    # Teaching a dev browser to refuse http://localhost would outlive the run.
    assert "strict-transport-security" not in plain.get("/").headers


# ------------------------------------------------------------------- the API mount

# The API is mounted inside this server (stocks.api at /api), which puts it
# behind the same gate as everything else. Three things about that gate could
# quietly break it, and none of them would show up in the API's own tests: the
# 404 for unknown paths, the canonical-host redirect, and the app cookie.


def test_the_api_is_reachable_through_the_gate(client):
    """`_is_known_path` 404s anything it does not recognise, and without the
    API prefix in it every call would be answered with a 404 page."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert STUB not in response.text, "Streamlit must not answer for the API"


def test_an_unknown_api_path_is_the_apis_own_404(client):
    """Not the marketing 404 page: an API client parses JSON, not HTML."""
    response = client.get("/api/v1/nothing-here")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_the_api_never_sets_the_app_cookie(client):
    """A cron job is not a browser that has been to the app, and a Set-Cookie
    on its responses is a credential it never asked for."""
    response = client.get("/api/v1/health")
    assert server.APP_COOKIE not in response.cookies


def test_the_api_is_kept_out_of_the_index(client):
    response = client.get("/api/v1/health")
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_the_api_is_not_bounced_to_the_canonical_host(client, monkeypatch):
    """A cross-host 301 drops the Authorization header in several clients, and
    a canary answers about the container that took the request — which is the
    whole point of asking it."""
    monkeypatch.setattr(server, "public_origin", lambda: "https://topstocks.example")
    response = client.get("/api/v1/health", follow_redirects=False)
    assert response.status_code == 200


# --------------------------------------------------------------- the throttle
# One container answers everyone (--max-instances 1), so a burst from one
# client takes the app away from real users. What is tested here is that the
# limit counts the right things: a document and an API call are not the same
# unit of work, and metering them together makes an ordinary reader look like
# a flood.


@pytest.fixture
def metered(monkeypatch):
    """The gate with the throttle in front of it, and small budgets."""
    from stocks.web import ratelimit

    ratelimit._events.clear()
    monkeypatch.setattr(server, "CLIENT_MAX_DOCS", 3)
    monkeypatch.setattr(server, "API_MAX_REQUESTS", 8)
    app = served(server.ClientThrottle, server.SecurityHeaders, server.LandingGate)
    yield TestClient(app, base_url="https://topstocks.example")
    ratelimit._events.clear()


def codes(client, path: str, n: int) -> list[int]:
    return [client.get(path).status_code for _ in range(n)]


def test_a_document_flood_is_stopped(metered):
    assert codes(metered, "/?app=1", 5)[-1] == 429


def test_one_screen_of_api_calls_is_not_a_flood(metered):
    """The React ticker page asks for bars, quote, calendar, position, KPIs,
    financials, valuation, moat, insiders, fund and peers separately: one page
    view is around twenty requests. On the document budget, three tickers in a
    minute would 429 a reader doing nothing unusual."""
    assert 429 not in codes(metered, "/api/v1/health", 5)


def test_the_api_has_a_ceiling_of_its_own(metered):
    """Its own budget, not no budget."""
    assert codes(metered, "/api/v1/health", 10)[-1] == 429


def test_the_two_budgets_cannot_lock_each_other_out(metered):
    """Separate keys, not just a bigger number: a burst of API calls must not
    take the app shell away, and a reload loop on the shell must not take the
    data with it."""
    assert codes(metered, "/api/v1/health", 10)[-1] == 429
    assert metered.get("/?app=1").status_code == 200


def test_a_throttled_api_call_answers_in_json_like_every_other_refusal(metered):
    """A caller that parses the API's 503 for an upstream rate limit should not
    have to special-case this one into a text body — `reason` is the field it
    already switches on."""
    codes(metered, "/api/v1/health", 10)
    response = metered.get("/api/v1/health")
    assert response.status_code == 429
    assert response.json()["reason"] == "throttled"
    assert int(response.headers["Retry-After"]) >= 1


def test_a_throttled_document_still_answers_in_plain_text(metered):
    codes(metered, "/?app=1", 5)
    response = metered.get("/?app=1")
    assert response.status_code == 429
    assert "text/plain" in response.headers["content-type"]


def test_the_probes_an_uptime_monitor_hits_are_never_metered(metered):
    assert 429 not in codes(metered, "/livez", 20)


# ------------------------------------------------------------------- the shell
# One document for every page, so the client router owns the rest. Three things
# about that could quietly break it: the deep link, the old `/next` address,
# and the gate's 404 for paths it does not recognise.


def test_a_deep_link_gets_the_shell_rather_than_a_404(client):
    """/portfolio?tab=fees has to survive a reload, and the page it names is
    drawn in the browser — one document for every page is what does that."""
    client.cookies.set(server.APP_COOKIE, "1")
    for path in ("/", "/portfolio", "/portfolio?tab=fees", "/ticker?ticker=AAPL"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert STUB in response.text, path


def test_the_old_next_address_is_redirected_home(client):
    """Linked from the what's-new card and Profile while it was being built,
    and the bank's registered return address: every one must still land."""
    for old, new in (("/next", "/"), ("/next/", "/"),
                     ("/next/portfolio?tab=fees", "/portfolio?tab=fees"),
                     ("/next/bank?code=x&state=y", "/bank?code=x&state=y")):
        response = client.get(old, follow_redirects=False)
        assert response.status_code == 301, old
        assert response.headers["location"] == new, old


def test_the_old_app_answers_under_its_own_prefix(client):
    assert LEGACY in client.get("/legacy/portfolio").text
    assert STUB not in client.get("/legacy/portfolio").text
    response = client.get("/legacy", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/legacy/"


def test_the_old_app_is_kept_out_of_the_index(client):
    assert client.get("/legacy/").headers["X-Robots-Tag"] == "noindex, nofollow"


def test_the_mirrored_logos_are_served_at_the_root(client, tmp_path, monkeypatch):
    """The API hands them out as `/app/static/logos/…`, absolute — the old
    app's static serving answers only under `/legacy` now."""
    static = tmp_path / "static"
    (static / "logos").mkdir(parents=True)
    (static / "logos" / "AAPL.png").write_bytes(b"png")
    monkeypatch.setattr(server, "_STATIC", static)
    response = client.get("/app/static/logos/AAPL.png")
    assert response.status_code == 200
    assert response.content == b"png"
    assert client.get("/app/static/../../etc/passwd").status_code == 404


def test_the_shell_carries_the_design_tokens_inlined(client):
    """Inlined so the page paints in the right colours on its first frame, and
    so the charts read their palette from the same custom properties the
    old app uses rather than fetching a second copy."""
    body = client.get("/portfolio").text
    assert "<!--AG-TOKENS-->" not in body
    assert "--ag-" in body


def test_the_shell_document_is_never_cached(client):
    """It is a shell over somebody's book with their tokens inlined into it."""
    assert client.get("/portfolio").headers["cache-control"] == "no-store"


def test_the_bundle_is_served_and_cached_briefly(client):
    response = client.get("/next-assets/app.js")
    assert response.status_code == 200
    assert "max-age" in response.headers["cache-control"]


def test_the_bundle_route_will_not_walk_out_of_its_directory(client):
    assert client.get("/next-assets/../../../etc/passwd").status_code == 404


def test_the_shell_is_kept_out_of_the_index(client):
    """Somebody's book behind a login has no business in a search index."""
    assert client.get("/portfolio").headers["X-Robots-Tag"] == "noindex, nofollow"


def test_the_bundle_is_not_metered(client):
    """Static files ride free, like the mirrored logos and the landing assets:
    a page view is one document and a dozen files, and counting the files
    makes an ordinary reader look like a flood."""
    assert server.APP_ASSETS in server._UNMETERED
    assert server.STATIC_PATH in server._UNMETERED


def test_the_document_carries_the_typefaces_and_the_icon(client):
    """Without them the CSS still names Instrument Sans and the browser paints
    system-ui — which looks like nothing being wrong. Same stylesheet the
    landing links, rather than a second list of faces."""
    body = client.get("/portfolio").text
    assert "<!--AG-FONTS-->" not in body, "the marker was replaced"
    assert "fonts.googleapis.com" in body and "Instrument+Sans" in body
    assert 'rel="icon"' in body


def test_an_unbuilt_checkout_says_so(client, shell):
    (shell / "index.html").unlink()
    response = client.get("/portfolio")
    assert response.status_code == 503
    assert "npm run build" in response.text


def test_the_entry_point_is_a_plain_asgi_app():
    """Not an `st.App`: `streamlit run` would find one and serve it, and the
    Streamlit app is a tenant of this server now, not its owner."""
    assert isinstance(server.app, Starlette)


def test_booting_the_server_provisions_the_guest_book():
    """Starlette does not run a mounted app's lifespan, so the API's boot work
    — the shared guest book — has to be run by the app in front of it. Without
    it every anonymous request read a ledger that did not exist, and 500'd."""
    from stocks import accounts

    assert not (accounts.GUEST_DIR / "portfolio.db").exists()
    with TestClient(server.app):
        assert (accounts.GUEST_DIR / "portfolio.db").is_file()
        assert (accounts.GUEST_DIR / "watchlist.yaml").is_file()
