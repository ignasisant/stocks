"""The consent screen: the one place a person says yes to an MCP client.

Asked every time, never remembered. A grant reads a whole portfolio, tax
report included, and the client asking may have chosen its own name, so the
cost of one more click is worth paying on every connection.

Writing is a second, separate yes: a box under the list of reads, unticked
every time, that adds `store.WRITE_SCOPE` to the grant. The client cannot ask
for it into existence — whatever scope it requested, only the box decides.

GET draws the page for the request `/authorize` sealed (`oauth.open_request`),
signing in first when there is no session. POST is the decision, and it must
prove three things before a code is minted:

* it came from this site's own page — `Origin` equals the public origin;
* the page was drawn for this session and this request — the hidden form
  token seals the email, the session id and a hash of the request;
* the request is still one we sealed, less than ten minutes old.

Server HTML rather than an app page on purpose: it has to work for somebody
who has never opened the app, and its Content-Security-Policy can then be the
strictest one on the site — no script at all, and the form may only post here
or, via the redirect after it, to the client's own redirect origin.
"""

from __future__ import annotations

import hashlib
import html
from urllib.parse import quote, urlsplit

from mcp.server.auth.provider import construct_redirect_uri
from mcp.server.transport_security import RequestBodyLimitMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route, request_response

from stocks import accounts, obs, session
from stocks.connector import clients, oauth, store

FORM_PURPOSE = "mcp.consent"
FORM_MAX_AGE = 600
_BODY_LIMIT = 16 * 1024

_READS = ("consent_read_positions", "consent_read_performance", "consent_read_tax",
          "consent_read_memory", "consent_read_market")


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _language(request: Request, email: str | None) -> str:
    """Profile language, then the browser's, then English — like the app."""
    from stocks.web import i18n

    if email:
        try:
            paths = accounts.paths_for(email, accounts.configured_owner())
            pref = i18n.supported(accounts.load_prefs(paths.prefs).get("language"))
        except Exception:  # noqa: BLE001 — a broken prefs file is not a 500
            pref = None
        if pref:
            return pref
    first = request.headers.get("accept-language", "").split(",")[0].split(";")[0]
    return i18n.supported(first.strip()) or i18n.DEFAULT_LANG


def _t(key: str, lang: str, **kw: str) -> str:
    """Translated and HTML-escaped, slots included."""
    from stocks.web import i18n

    escaped = {k: html.escape(v) for k, v in kw.items()}
    return i18n.translate(f"connector.{key}", lang, **escaped)


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _headers(form_target: str | None = None) -> dict[str, str]:
    from stocks.web.seo import FONTS_HREF

    fonts = _origin_of(FONTS_HREF)
    action = "'self'" + (f" {form_target}" if form_target else "")
    return {
        "Content-Security-Policy": (
            "default-src 'none'; "
            f"style-src 'unsafe-inline' {fonts}; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self'; "
            f"form-action {action}; "
            "frame-ancestors 'none'; base-uri 'none'"
        ),
        "Cache-Control": "no-store",
        # Not `no-referrer`: under it a browser sends `Origin: null` on the
        # form's POST, even to this same site, and `_decide` refuses that.
        "Referrer-Policy": "same-origin",
        "X-Frame-Options": "DENY",
    }


_STYLE = """
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
  padding:24px 16px;background:var(--ag-surface-page);color:var(--ag-text-primary);
  font:var(--ag-fs-base)/1.5 var(--ag-font-body)}
main{width:100%;max-width:440px;background:var(--ag-surface-card);
  border:1px solid var(--ag-border);border-radius:var(--ag-radius-lg);padding:28px 24px;
  box-shadow:var(--ag-shadow-card)}
.mark{display:flex;align-items:center;gap:8px;color:var(--ag-text-secondary);
  font-size:var(--ag-fs-md);margin-bottom:20px}
.mark img{width:24px;height:24px}
h1{font-size:var(--ag-fs-2xl);line-height:1.25;margin:0 0 12px;font-weight:600}
p{margin:0 0 12px;color:var(--ag-text-secondary)}
.who{font-size:var(--ag-fs-md)}
.who a{color:var(--ag-brand-accent)}
.badge{display:inline-block;font-size:var(--ag-fs-xs);font-weight:600;padding:2px 8px;
  border-radius:var(--ag-radius-pill);background:var(--ag-warn-band);color:var(--ag-warn);
  margin-bottom:8px}
.note{font-size:var(--ag-fs-sm);color:var(--ag-text-muted)}
.host{font-family:var(--ag-font-mono);font-size:var(--ag-fs-sm);color:var(--ag-text-primary);
  word-break:break-all}
ul{margin:4px 0 16px;padding:0 0 0 18px;color:var(--ag-text-primary)}
li{margin:4px 0}
.opt{display:flex;gap:10px;align-items:flex-start;margin:4px 0 16px;padding:12px;
  border:1px solid var(--ag-border);border-radius:var(--ag-radius-sm);cursor:pointer}
.opt input{margin:3px 0 0;width:16px;height:16px;flex:none;
  accent-color:var(--ag-brand-cta)}
.opt strong{display:block;font-weight:600;color:var(--ag-text-primary)}
.opt .note{display:block;margin-top:2px}
.actions{display:flex;gap:12px;margin-top:20px}
button{flex:1;font:inherit;font-weight:600;border-radius:var(--ag-radius-sm);
  padding:10px 16px;cursor:pointer;border:1px solid var(--ag-border)}
.allow{background:var(--ag-brand-cta);color:var(--ag-on-brand);
  border-color:var(--ag-brand-cta)}
.deny{background:transparent;color:var(--ag-text-primary)}
"""


def _document(lang: str, title: str, body: str) -> str:
    from stocks.web.ds import ds_vars_css
    from stocks.web.landing import ASSET_BASE
    from stocks.web.seo import FONTS_HREF

    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{title}</title>{ds_vars_css()}"
        f'<link rel="stylesheet" href="{html.escape(FONTS_HREF)}">'
        f"<style>{_STYLE}</style></head><body><main>"
        f'<div class="mark"><img src="{ASSET_BASE}topstocks-icon.svg" alt="">'
        "TopStocks</div>"
        f"{body}</main></body></html>"
    )


def _problem(lang: str, key: str, status: int) -> Response:
    title = _t("consent_error_title", lang)
    body = f"<h1>{title}</h1><p>{_t(key, lang)}</p>"
    return HTMLResponse(_document(lang, title, body), status_code=status,
                        headers=_headers())


def _page(lang: str, *, name: str, unverified: bool, host: str, email: str,
          req: str, form: str, switch: str) -> str:
    title = _t("consent_title", lang, client=name)
    badge = (
        f'<span class="badge">{_t("consent_unverified", lang)}</span>'
        f'<p class="note">{_t("consent_unverified_help", lang)}</p>'
        if unverified else ""
    )
    reads = "".join(f"<li>{_t(k, lang)}</li>" for k in _READS)
    return _document(lang, _t("consent_page_title", lang), (
        f"{badge}<h1>{title}</h1>"
        f'<p class="who">{_t("consent_signed_in", lang, email=email)} '
        f'<a href="{html.escape(switch)}">{_t("consent_switch", lang)}</a></p>'
        f"<p>{_t('consent_reads', lang, client=name)}</p><ul>{reads}</ul>"
        f'<form method="post" action="{oauth.CONSENT_PATH}">'
        '<label class="opt"><input type="checkbox" name="write" value="1">'
        f"<span><strong>{_t('consent_write', lang, client=name)}</strong>"
        f'<span class="note">{_t("consent_write_help", lang)}</span></span></label>'
        f"<p>{_t('consent_cannot', lang)}</p>"
        f'<p class="note">{_t("consent_return", lang)}<br>'
        f'<span class="host">{html.escape(host)}</span></p>'
        f'<p class="note">{_t("consent_revoke_hint", lang)}</p>'
        f'<input type="hidden" name="req" value="{html.escape(req)}">'
        f'<input type="hidden" name="csrf" value="{html.escape(form)}">'
        '<div class="actions">'
        f'<button class="deny" name="decision" value="deny">'
        f"{_t('consent_deny', lang)}</button>"
        f'<button class="allow" name="decision" value="allow">'
        f"{_t('consent_allow', lang)}</button>"
        "</div></form>"
    ))


def _login(raw: str) -> Response:
    back = f"{oauth.CONSENT_PATH}?req={quote(raw, safe='')}"
    response = RedirectResponse(
        f"/auth/login?next={quote(back, safe='')}", status_code=302
    )
    response.headers["Cache-Control"] = "no-store"
    return response


async def _show(request: Request) -> Response:
    raw = request.query_params.get("req", "")
    email = session.signed_in_email(request.cookies)
    lang = _language(request, email)
    req = oauth.open_request(raw)
    if req is None:
        return _problem(lang, "consent_expired", 400)
    if not email:
        return _login(raw)
    client = await clients.get(req["client_id"])
    if client is None:
        return _problem(lang, "consent_unknown_client", 400)
    claims = session.claims(request.cookies) or {}
    form = session.seal(FORM_PURPOSE, {
        "email": email, "sid": str(claims.get("sid") or ""), "req": _digest(raw),
    })
    if form is None:
        return _problem(lang, "consent_stale_form", 503)
    redirect = req["redirect_uri"]
    here = quote(f"{request.url.path}?{request.url.query}", safe="")
    body = _page(
        lang,
        name=clients.label(client),
        unverified=clients.describe(client)["client_kind"] != "cimd",
        host=clients.redirect_host(redirect),
        email=email,
        req=raw,
        form=form,
        switch=f"/auth/login?next={here}",
    )
    obs.event("mcp.consent", step="shown")
    return HTMLResponse(body, headers=_headers(_origin_of(redirect)))


async def _decide(request: Request, origin: str) -> Response:
    email = session.signed_in_email(request.cookies)
    lang = _language(request, email)
    if request.headers.get("origin") != origin:
        obs.warn("mcp.consent_refused", reason="origin")
        return _problem(lang, "consent_stale_form", 403)
    form = await request.form()
    raw, token = str(form.get("req") or ""), str(form.get("csrf") or "")
    req = oauth.open_request(raw)
    if req is None:
        return _problem(lang, "consent_expired", 400)
    claims = session.claims(request.cookies) or {}
    check = session.unseal(FORM_PURPOSE, token, FORM_MAX_AGE)
    if (
        not email
        or not check
        or check.get("email") != email
        or check.get("sid") != str(claims.get("sid") or "")
        or check.get("req") != _digest(raw)
    ):
        obs.warn("mcp.consent_refused", reason="form")
        return _problem(lang, "consent_stale_form", 403)
    client = await clients.get(req["client_id"])
    if client is None:
        return _problem(lang, "consent_unknown_client", 400)
    redirect = req["redirect_uri"]
    kind = clients.describe(client)["client_kind"]
    if form.get("decision") == "allow":
        write = form.get("write") == "1"
        scopes = store.SCOPES if write else (store.SCOPE,)
        code = oauth.mint_code(email, req, resource=origin + oauth.MCP_PATH,
                               scopes=scopes)
        target = construct_redirect_uri(redirect, code=code, state=req.get("state"),
                                        iss=origin)
        obs.event("mcp.consent", step="allow", client_kind=kind, write=write)
    else:
        target = construct_redirect_uri(redirect, error="access_denied",
                                        state=req.get("state"), iss=origin)
        obs.event("mcp.consent", step="deny", client_kind=kind)
    response = RedirectResponse(target, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def routes(origin: str) -> list[Route]:
    """`/oauth/consent`, GET to look and POST to decide."""

    async def consent(request: Request) -> Response:
        if request.method == "POST":
            return await _decide(request, origin)
        return await _show(request)

    return [Route(oauth.CONSENT_PATH, methods=["GET", "POST"], endpoint=(
        RequestBodyLimitMiddleware(request_response(consent), _BODY_LIMIT)))]
