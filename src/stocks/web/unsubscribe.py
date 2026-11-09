"""`/email/unsubscribe` — the weekly email's one-click stop.

The token in the link is the whole credential (`weekly_email.unsubscribe_token`,
sealed for one purpose and one account): the reader is often not signed in on
the device that opened the mail, and asking them to would make stopping an
email harder than receiving it.

GET asks and never acts. Mail scanners and link previewers fetch every URL in
a message, and a GET that unsubscribed would unsubscribe people who never
clicked. POST acts: the page's own button, and the mail client's
`List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058), which arrives
from the provider's servers with the token in the query and no cookie — so
there is no same-site check here, unlike sign-out.
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from stocks import accounts, obs
from stocks.web import csp

PATH = "/email/unsubscribe"


def _paths(label: str):
    """The account `label` names, or None for one that is not a plain slug."""
    if label == "owner":
        return accounts.owner_paths()
    if not label or "/" in label or "\\" in label or label.startswith("."):
        return None
    directory = accounts.USERS_DIR / label
    return accounts.paths_in(directory) if directory.is_dir() else None


def _stop(label: str) -> bool:
    from stocks.notify.weekly_email import PREF

    paths = _paths(label)
    if paths is None:
        return False
    accounts.update_prefs(paths.prefs, {PREF: False})
    return True


def _page(lang: str, title: str, body: str, form: str = "",
          status: int = 200) -> Response:
    from stocks.web.markup import esc

    html = (
        "<!doctype html>"
        f'<html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" '
        'content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<meta name="theme-color" content="#18161C">'
        '<meta name="robots" content="noindex">'
        f"<title>{esc(title)} — TopStocks</title><style>{_CSS}</style>"
        f"</head><body><main><h1>{esc(title)}</h1><p>{esc(body)}</p>{form}"
        "</main></body></html>"
    )
    return Response(html, status_code=status, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store",
                             "Content-Security-Policy": csp.policy(
                                 styles=[csp.source(_CSS)], fonts=False)})


def _lang(request: Request) -> str:
    from stocks.i18n import negotiated

    return negotiated(request.query_params.get("lang"),
                      request.headers.get("accept-language"))


def _say(key: str, lang: str) -> str:
    from stocks.i18n import translate

    return translate(f"email.{key}", lang)


async def confirm(request: Request) -> Response:
    """`GET`: the question and a button, nothing changed."""
    from stocks.notify.weekly_email import unsubscribe_label
    from stocks.web.markup import esc

    lang = _lang(request)
    token = request.query_params.get("t", "")
    if unsubscribe_label(token) is None:
        return _page(lang, "TopStocks", _say("unsub_invalid", lang), status=400)
    form = (
        f'<form method="post" action="{PATH}">'
        f'<input type="hidden" name="t" value="{esc(token)}">'
        f'<input type="hidden" name="lang" value="{esc(lang)}">'
        f'<button type="submit">{esc(_say("unsub_button", lang))}</button></form>'
    )
    return _page(lang, _say("unsub_title", lang), _say("unsub_body", lang), form)


async def stop(request: Request) -> Response:
    """`POST`: switch the email off for the token's account."""
    from stocks.notify.weekly_email import unsubscribe_label

    form = await request.form()
    token = str(form.get("t") or request.query_params.get("t") or "")
    lang = _lang(request)
    if form.get("lang"):
        from stocks.i18n import negotiated

        lang = negotiated(str(form.get("lang")), None)
    label = unsubscribe_label(token)
    done = label is not None and await run_in_threadpool(_stop, label)
    one_click = form.get("List-Unsubscribe") == "One-Click"
    obs.event("email.unsubscribe", ok=done, one_click=one_click)
    if not done:
        return _page(lang, "TopStocks", _say("unsub_invalid", lang), status=400)
    return _page(lang, _say("unsub_done_title", lang), _say("unsub_done_body", lang))


def routes() -> list[Route]:
    return [
        Route(PATH, confirm, methods=["GET", "HEAD"]),
        Route(PATH, stop, methods=["POST"]),
    ]


_CSS = """
:root { color-scheme: dark; }
body { margin: 0; background: #18161C; color: #F9F9FA;
       font: 16px/1.65 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 28rem; margin: 0 auto; padding: 4rem 1.25rem; }
h1 { font-size: 1.5rem; line-height: 1.25; margin: 0 0 0.4rem; }
p { margin: 0.6rem 0 1.5rem; color: #B3AFBD; }
button { font: inherit; font-weight: 600; color: #FEFEFF; background: #7F3FE8;
         border: 0; border-radius: 10px; padding: 0.6rem 1.1rem; min-height: 44px;
         cursor: pointer; }
button:focus-visible { outline: 2px solid #A98EF7; outline-offset: 2px; }
"""
