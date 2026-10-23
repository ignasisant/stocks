"""The owner's Monday read of the product: who came and what they looked at.

`stocks usage-digest` rolls the last week of production logs up
(`logs_query.usage` and `logs_query.funnel`) and sends the owner one Telegram
message. It runs as the Cloud Run job (infra/cron.tf, Monday 07:00 UTC):
GitHub Actions holds no Google credentials, and the job already runs the
service's image under its identity, which Cloud Logging answers once that
identity may view logs. On a laptop the same command reads through gcloud.

The recipient is the owner: the chat linked on the Profile page (the owner's
prefs, restored from the bucket), or `TELEGRAM_OWNER_CHAT_ID` /
`[telegram] owner_chat_id` when one is configured.
"""

from __future__ import annotations

import json

from stocks import logs_query as lq
from stocks import obs, storage
from stocks.config import DATA_DIR
from stocks.notify import telegram
from stocks.notify.render import esc
from stocks.secrets_env import secret
from stocks.web.i18n import translate

SINCE = "7d"
#: Pages named in the message; the rest of the list says little on a phone.
TOP_PAGES = 6
#: Skills named in the message: the dearest ones, which is what is worth a look.
TOP_SKILLS = 5
#: `<pre>` widths of the skills table: skill, answers, mean $, up, down.
_SKILL_COLS = (("skill", 13), ("n", 4), ("mean", 7), ("up", 3), ("down", 4))
#: `<pre>` column widths — a phone shows about 35 monospace characters.
#: (label key, usage row key, width).
_COLS = (
    ("day", "day", 5), ("accounts", "users", 5), ("visitors", "visitors", 5),
    ("views", "views", 6), ("chat", "chat", 5),
)


def _owner_prefs() -> dict:
    """The owner's prefs.json (accounts.paths_for maps the owner to DATA_DIR)."""
    path = DATA_DIR / "prefs.json"
    storage.restore(path)
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def owner_chat_id() -> str:
    """Where the digest goes: a configured chat, else the one the owner linked."""
    configured = secret("TELEGRAM_OWNER_CHAT_ID", "telegram", "owner_chat_id")
    return configured or str(_owner_prefs().get("telegram_chat_id") or "")


def owner_lang() -> str:
    return str(_owner_prefs().get("language") or "en")


def _ratings() -> list[dict]:
    """The stored thumbs, one per conversation; none when the store is out of
    reach — the digest still goes, just without the like column."""
    from stocks.web import feedback

    with obs.swallow("usage_digest.ratings"):
        return feedback.latest_ratings(feedback.stored())
    return []


def summarise(entries: list[dict], ratings: list[dict] | None = None) -> dict:
    return {
        "usage": lq.usage(entries),
        "funnel": lq.funnel(entries),
        "skills": lq.skills(entries, ratings or []),
    }


def _skills_block(summary: dict, tr) -> str | None:
    """The dearest skills with their mean cost and thumbs, as a narrow table."""
    rows = summary.get("skills", {}).get("rows", [])[:TOP_SKILLS]
    if not rows:
        return None
    head = " ".join(
        f"{tr(f'skill_col_{n}')[:w]:<{w}}"
        if n == "skill"
        else f"{tr(f'skill_col_{n}')[:w]:>{w}}"
        for n, w in _SKILL_COLS
    )
    body = [
        " ".join(
            (
                f"{r['skill'][:13]:<13}",
                f"{r['answers']:>4}",
                f"{r['mean_usd']:>7.4f}" if r["mean_usd"] is not None else f"{'-':>7}",
                f"{r['up']:>3}",
                f"{r['down']:>4}",
            )
        )
        for r in rows
    ]
    total = summary["skills"]
    return (
        f"<b>{esc(tr('skills_title'))}</b>\n"
        f"<pre>{esc(chr(10).join([head, *body]))}</pre>\n"
        + esc(tr("skills_total", answers=total["answers"], usd=f"{total['usd']:.2f}"))
    )


def _cell(name: str, value, width: int) -> str:
    text = str(value)[:width]
    return f"{text:<{width}}" if name == "day" else f"{text:>{width}}"


def render(summary: dict, lang: str) -> str:
    """One Telegram message (HTML): the week's table, totals, pages, funnel."""
    def tr(key: str, **kw) -> str:
        return translate(f"notify.usage_{key}", lang, **kw)

    u, f = summary["usage"], summary["funnel"]
    if not u["days"]:
        return f"<b>📈 {esc(tr('title'))}</b>\n{esc(tr('empty'))}"
    days = u["days"]
    span = f"{days[0]['day'][5:]} – {days[-1]['day'][5:]}"
    head = " ".join(_cell(name, tr(f"col_{name}"), width) for name, _, width in _COLS)
    rows = [
        " ".join(
            _cell(name, d[key][5:] if name == "day" else d[key], width)
            for name, key, width in _COLS
        )
        for d in days
    ]
    table = "\n".join([head, *rows])
    lines = [
        f"<b>📈 {esc(tr('title'))}</b> · {esc(span)}",
        f"<pre>{esc(table)}</pre>",
        esc(tr(
            "totals",
            accounts=u["total_users"], addresses=u["total_visitors"],
            logins=sum(d["logins"] for d in days),
            signups=sum(d["signups"] for d in days),
            imports=sum(d["imports"] for d in days),
            first=sum(d["first_imports"] for d in days),
            chat=sum(d["chat"] for d in days),
        )),
    ]
    if u["pages"]:
        pages = " · ".join(f"{page} {n}" for page, n in u["pages"][:TOP_PAGES])
        lines.append(f"{esc(tr('pages'))}: {esc(pages)}")
    t = f["totals"]
    lines.append(esc(tr(
        "funnel", views=t["views"], entries=t["ctas"], signups=t["signups"],
        imports=t["imports"],
    )))
    r = f["retention"]
    if r["eligible"]:
        lines.append(esc(tr(
            "retention", returned=r["returned"], eligible=r["eligible"],
            days=r["days"],
        )))
    if block := _skills_block(summary, tr):
        lines.append(block)
    return "\n".join(lines)


def run(
    *,
    since: str = SINCE,
    dry_run: bool = False,
    entries: list[dict] | None = None,
    lang: str | None = None,
    project: str | None = None,
    service: str | None = None,
) -> tuple[str, str]:
    """Build the message and send it to the owner: (status, text).

    `entries` skips the log read (exported snapshots, tests); a dry run
    renders and sends nothing; without a recipient the text is still the
    return value, so the job's log shows what it would have said.
    """
    if entries is None:
        entries = lq.usage_entries(
            project=project or lq.PROJECT, service=service or lq.SERVICE,
            freshness=since,
        )
    text = render(summarise(entries, _ratings()), lang or owner_lang())
    if dry_run:
        return "dry-run", text
    chat = owner_chat_id()
    if not chat:
        obs.warn("usage_digest.no_recipient", entries=len(entries))
        return "no recipient", text
    telegram.send_message(text, chat, parse_mode="HTML")
    obs.event("usage_digest.sent", entries=len(entries), chars=len(text))
    return "sent", text
