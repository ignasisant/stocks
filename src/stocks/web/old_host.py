"""The old address's answer to an installed app: the app has moved.

An installed app (PWA) belongs to the origin it was installed from, and no
browser moves one to another. Once `[app] public_url` names a new host, every
page on the old one is a 301 there (`server.canonical_redirect`) — which an
installed app follows into an out-of-scope view of the new site, signed out,
while its service worker on the old origin keeps receiving notifications. Add
the app again from the new host and that phone gets every push twice.

So the installed app's launch (`start_url` is `/?installed=1`) gets this page
instead of the 301. Its script is the only code that can still run on the old
origin: it drops that origin's push subscription — here, through the API,
which the redirect leaves alone and where the old session cookie still
works, and at the push service — and unregisters its worker. The page then
says how to add the app from the new address. A browser tab gets the plain
301 as before.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import Response

from stocks import obs
from stocks.web import csp

# The manifest's `start_url` (`assets/manifest.webmanifest`): only an
# installed app opens `/` with it.
LAUNCH_PARAM = "installed"

_UNSUBSCRIBE = "/api/v1/push/unsubscribe"

_SCRIPT = (
    "(async()=>{try{"
    "if(!('serviceWorker'in navigator))return;"
    "for(const reg of await navigator.serviceWorker.getRegistrations()){"
    "const sub=reg.pushManager&&await reg.pushManager.getSubscription();"
    "if(sub){"
    f"await fetch('{_UNSUBSCRIBE}',{{method:'POST',credentials:'same-origin',"
    "headers:{'Content-Type':'application/json'},"
    "body:JSON.stringify({endpoint:sub.endpoint})}).catch(()=>{});"
    "await sub.unsubscribe().catch(()=>{});}"
    "await reg.unregister();}"
    "}catch(e){}})();"
)

_CSS = """
:root { color-scheme: dark; }
body { margin: 0; background: #18161C; color: #E8E5EF;
       font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 28rem; margin: 0 auto;
       padding: max(3rem, env(safe-area-inset-top)) 1.25rem 3rem; }
h1 { font-size: 1.5rem; line-height: 1.25; margin: 0 0 0.75rem; }
p { margin: 0.6rem 0; color: #C9C4D4; }
.host { font-weight: 600; color: #E8E5EF; }
ul { margin: 1rem 0; padding-left: 1.25rem; color: #C9C4D4; }
li { margin: 0.4rem 0; }
a { display: inline-flex; align-items: center; min-height: 44px; margin-top: 1rem;
    font-weight: 600; color: #18161C; background: #E8E5EF; border-radius: 10px;
    padding: 0 1.1rem; text-decoration: none; }
a:focus-visible { outline: 2px solid #9AD1FF; outline-offset: 2px; }
.note { font-size: 0.875rem; }
"""


def is_app_launch(request: Request) -> bool:
    """Whether this request is an installed app opening: `GET /?installed=1`."""
    return (
        request.method == "GET"
        and request.url.path == "/"
        and LAUNCH_PARAM in request.query_params
    )


def page(request: Request, target: str) -> Response:
    """The "we moved" page, pointing at `target` on the new host."""
    from stocks.i18n import negotiated, translate
    from stocks.web.markup import esc

    lang = negotiated(
        request.query_params.get("lang"), request.headers.get("accept-language")
    )
    host = urlsplit(target).netloc
    home = f"{urlsplit(target).scheme}://{host}/"
    shown = f'<span class="host">{esc(host)}</span>'
    say = {
        key: esc(translate(f"auth.moved_{key}", lang, host=host))
        .replace(esc(host), shown)
        for key in ("title", "body", "iphone", "android", "push", "open")
    }
    obs.event("app.moved", lang=lang)
    html = (
        "<!doctype html>"
        f'<html lang="{lang}"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" '
        'content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<meta name="theme-color" content="#18161C">'
        '<meta name="robots" content="noindex">'
        f"<title>{say['title']}</title>"
        f"<style>{_CSS}</style>"
        "</head><body><main>"
        f"<h1>{say['title']}</h1>"
        f"<p>{say['body']}</p>"
        f"<ul><li>{say['iphone']}</li><li>{say['android']}</li></ul>"
        f'<p class="note">{say["push"]}</p>'
        f'<a href="{esc(home)}">{say["open"]}</a>'
        "</main>"
        f"<script>{_SCRIPT}</script>"
        "</body></html>"
    )
    return Response(
        html,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex",
            "Content-Security-Policy": csp.policy(
                styles=[csp.source(_CSS)], scripts=[csp.source(_SCRIPT)], fonts=False
            ),
        },
    )
