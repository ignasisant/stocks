"""Query the production logs from the terminal (`stocks logs ...`).

Cloud Run ships the container's stdout/stderr to Cloud Logging, where it is
kept for 30 days in the _Default bucket. This module is the read side: it
builds a Logging filter, shells out to `gcloud logging read`, and renders the
entries as one compact line each — plus `stats` (counts and latency
percentiles per event), `usage` (accounts, visitors and page views per day,
out of the app's events and the access log together), `funnel` (landing
view to signup, by day and by campaign source), `connector` (Profile's
Claude tab to the connector's first tool call, in accounts) and `export` (a JSONL
snapshot on disk, for keeping a bad day past the retention window or
grinding through it offline).

`gcloud` does the auth, so there is no key to manage: whoever is logged in with
`gcloud auth login` and can read the project's logs can run these.

Every command accepts `--file` to read an exported JSONL snapshot instead of
calling Cloud Logging, so the same rendering works with no network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from stocks.config import DATA_DIR
from stocks.web.attribution import is_bot

PROJECT = os.getenv("STOCKS_GCP_PROJECT", "topstocks-507209")
SERVICE = os.getenv("STOCKS_GCP_SERVICE", "topstocks")
# The Cloud Run job that writes the Today page's market read each morning
# (infra/cron.tf). It runs the service's image and logs the same way, under a
# resource of its own; its lines belong in every app view here.
JOB = os.getenv("STOCKS_GCP_JOB", "topstocks-cron")
LOGS_DIR = DATA_DIR / "logs"

# The per-request access log. It is one entry per HTTP call — health checks
# included — so it drowns everything else unless asked for explicitly
# (`--http`).
_REQUEST_LOG = "run.googleapis.com%2Frequests"


class LogsError(RuntimeError):
    """gcloud is missing, unauthenticated, or refused the query."""


# --------------------------------------------------------------------- filters


def build_filter(
    *,
    service: str = SERVICE,
    job: str = JOB,
    project: str = PROJECT,
    level: str | None = None,
    event: str | None = None,
    user: str | None = None,
    grep: str | None = None,
    http: bool = False,
    revision: str | None = None,
    extra: str | None = None,
) -> str:
    """Assemble a Cloud Logging filter string from the CLI's options."""
    app = (
        'resource.type="cloud_run_revision"'
        f' AND resource.labels.service_name="{service}"'
    )
    cron = f'resource.type="cloud_run_job" AND resource.labels.job_name="{job}"'
    parts = [f"(({app}) OR ({cron}))"]
    if http:
        parts.append(f'logName="projects/{project}/logs/{_REQUEST_LOG}"')
    else:
        parts.append(f'logName!="projects/{project}/logs/{_REQUEST_LOG}"')
        # Admin API calls (deploys, IAM edits) are logged against the same
        # resource and land as ERROR whenever a console call 403s. They are not
        # the app talking, so they never belong in an app-error view.
        parts.append('NOT logName:"cloudaudit"')
    if level:
        parts.append(f"severity>={level.upper()}")
    if event:
        parts.append(f'jsonPayload.event="{event}"')
    if user:
        parts.append(f'jsonPayload.user="{user}"')
    if revision:
        parts.append(f'resource.labels.revision_name="{revision}"')
    if grep:
        # Free-text lines land in textPayload, ours in jsonPayload.message; a
        # user searching for a phrase means either.
        esc = grep.replace('"', '\\"')
        parts.append(f'(textPayload:"{esc}" OR jsonPayload.message:"{esc}")')
    if extra:
        parts.append(f"({extra})")
    return " AND ".join(parts)


# ----------------------------------------------------------------------- fetch


def read(
    log_filter: str,
    *,
    project: str = PROJECT,
    freshness: str = "1h",
    limit: int = 100,
) -> list[dict]:
    """The entries, newest first: through `gcloud` where it is installed,
    else straight from the Logging API (`read_api`)."""
    if shutil.which("gcloud") is None:
        return read_api(log_filter, project=project, freshness=freshness, limit=limit)
    cmd = [
        "gcloud", "logging", "read", log_filter,
        "--project", project,
        "--limit", str(limit),
        "--freshness", freshness,
        "--order", "desc",
        "--format", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise LogsError((proc.stderr or proc.stdout).strip()[:2000])
    return json.loads(proc.stdout or "[]")


# The Logging API, for where `gcloud` is not: the service's own image. The
# weekly usage digest runs as the Cloud Run job (infra/cron.tf) under the
# service's identity, which Application Default Credentials find on the
# metadata server; `gcloud auth application-default login` fills the same
# role on a laptop without the CLI. Entries come back in the shape `gcloud
# logging read --format json` prints, so nothing downstream can tell.
_ENTRIES_LIST = "https://logging.googleapis.com/v2/entries:list"
_LOGGING_SCOPE = "https://www.googleapis.com/auth/logging.read"
_PAGE_SIZE = 1000


def _span(freshness: str) -> timedelta:
    """gcloud's freshness spelling (30m, 6h, 7d) as a timedelta."""
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", freshness or "")
    if not m:
        raise LogsError(f"unreadable --since {freshness!r}: use 30m, 6h or 7d")
    unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
    return timedelta(**{unit: int(m.group(1))})


def _access_token() -> str:
    """A bearer token from Application Default Credentials."""
    import google.auth
    from google.auth.exceptions import GoogleAuthError
    from google.auth.transport.requests import Request

    try:
        creds, _ = google.auth.default(scopes=[_LOGGING_SCOPE])
        creds.refresh(Request())
    except GoogleAuthError as exc:
        raise LogsError(
            "no Google credentials — install the Google Cloud CLI and run "
            "`gcloud auth login` to read production logs, or run this inside "
            f"the service's own image ({exc})"
        ) from exc
    return str(creds.token)


def read_api(
    log_filter: str,
    *,
    project: str = PROJECT,
    freshness: str = "1h",
    limit: int = 100,
) -> list[dict]:
    """`entries:list` with Application Default Credentials, newest first."""
    since = (datetime.now(UTC) - _span(freshness)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body: dict = {
        "resourceNames": [f"projects/{project}"],
        "filter": f'({log_filter}) AND timestamp>="{since}"',
        "orderBy": "timestamp desc",
        "pageSize": max(1, min(_PAGE_SIZE, limit)),
    }
    headers = {"Authorization": f"Bearer {_access_token()}"}
    out: list[dict] = []
    with httpx.Client(timeout=60) as client:
        while len(out) < limit:
            resp = client.post(_ENTRIES_LIST, json=body, headers=headers)
            if resp.status_code != 200:
                raise LogsError(f"Logging API {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            out.extend(data.get("entries") or [])
            token = data.get("nextPageToken")
            if not token:
                break
            body["pageToken"] = token
    return out[:limit]


def read_file(path: Path) -> list[dict]:
    """Entries from a JSONL snapshot written by `stocks logs export`."""
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def export(entries: Sequence[dict], out: Path | None = None) -> Path:
    """Write entries as JSONL. Default name carries the export timestamp."""
    if out is None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = LOGS_DIR / f"topstocks-{stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return out


# ------------------------------------------------------------------- rendering

# Bookkeeping we render in the fixed columns or never want in the k=v tail.
_TAIL_SKIP = frozenset(
    {"message", "event", "severity", "logger", "stack_trace", "@type", "revision",
     "logging.googleapis.com/sourceLocation", "ok"}
)


def payload(entry: dict) -> dict:
    """The structured body of an entry, whatever shape it arrived in."""
    if "jsonPayload" in entry:
        return entry["jsonPayload"]
    if "textPayload" in entry:
        return {"message": entry["textPayload"]}
    if "httpRequest" in entry:
        r = entry["httpRequest"]
        return {
            "message": f"{r.get('requestMethod', '?')} {r.get('requestUrl', '?')}",
            "status": r.get("status"),
            "latency": r.get("latency"),
            "ip": r.get("remoteIp"),
        }
    return {"message": json.dumps(entry.get("protoPayload", ""))[:200]}


# Fixed-width severity so the columns line up; Cloud Logging's own names are
# too long to sit in a terminal line next to the message.
_SEV = {"DEFAULT": "log", "DEBUG": "DEBUG", "INFO": "INFO", "NOTICE": "NOTE",
        "WARNING": "WARN", "ERROR": "ERROR", "CRITICAL": "CRIT", "ALERT": "ALERT",
        "EMERGENCY": "EMERG"}


def _local_time(ts: str) -> str:
    try:
        return (
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%m-%d %H:%M:%S")
        )
    except (ValueError, TypeError):
        return (ts or "")[:19]


def format_entry(entry: dict, *, show_trace: bool = False) -> str:
    """One line per entry: time, severity, event/logger, message, then k=v."""
    body = payload(entry)
    raw_sev = entry.get("severity") or "DEFAULT"
    sev = _SEV.get(raw_sev, raw_sev[:5])
    name = body.get("event") or body.get("logger") or ""
    msg = str(body.get("message", "")).split("\n")[0][:160]
    tail = " ".join(
        f"{k}={v}"
        for k, v in body.items()
        if k not in _TAIL_SKIP and v not in (None, "")
    )
    line = f"{_local_time(entry.get('timestamp', ''))} {sev:<5} {name:<26} {msg}"
    if tail:
        line = f"{line}  {tail}"
    if show_trace and body.get("stack_trace"):
        line = f"{line}\n{body['stack_trace'].rstrip()}"
    return line


def render(entries: Iterable[dict], *, show_trace: bool = False) -> str:
    """Oldest first — reading a timeline top-to-bottom beats newest-first."""
    rows = list(entries)[::-1]
    return "\n".join(format_entry(e, show_trace=show_trace) for e in rows)


# --------------------------------------------------------------------- summary


def _pct(values: list[float], q: float) -> float:
    """Nearest-rank percentile; statistics.quantiles needs n>=2."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


def stats(entries: Iterable[dict], *, by: str = "event") -> list[dict]:
    """Per-group counts, error counts and latency percentiles.

    Groups on `jsonPayload.<by>` (default the event name); entries without
    that field are grouped under "-" so free-text noise stays visible rather
    than silently dropping out of the totals.
    """
    groups: dict[str, dict] = {}
    for entry in entries:
        body = payload(entry)
        key = str(body.get(by) or "-")
        g = groups.setdefault(key, {"key": key, "count": 0, "errors": 0, "ms": []})
        g["count"] += 1
        if (entry.get("severity") or "") in ("ERROR", "CRITICAL"):
            g["errors"] += 1
        ms = body.get("duration_ms")
        if isinstance(ms, (int, float)):
            g["ms"].append(float(ms))
    out = []
    for g in groups.values():
        ms = g.pop("ms")
        out.append({
            **g,
            "p50_ms": round(_pct(ms, 0.50)) if ms else None,
            "p95_ms": round(_pct(ms, 0.95)) if ms else None,
            "max_ms": round(max(ms)) if ms else None,
        })
    return sorted(out, key=lambda g: g["count"], reverse=True)


# ----------------------------------------------------------------------- usage

# What `usage` reads beside the app's own events: the per-request access log,
# minus the lines nobody typed — the uptime probe, the bundle's assets, the
# landing's icons. Cloud Logging's `:` is a substring match.
USAGE_HTTP_EXTRA = (
    'NOT httpRequest.requestUrl:"/livez"'
    ' AND NOT httpRequest.requestUrl:"/next-assets/"'
    ' AND NOT httpRequest.requestUrl:"/app/static/"'
    ' AND NOT httpRequest.requestUrl:"/lp/"'
)

# Two calls from one address to one page closer together than this are one
# view: the shell fans a page out into half a dozen API calls, a stale
# countdown retries, and a reload is not a second visit.
VIEW_WINDOW_S = 300

# `jsonPayload.user` when the request carried no account — the middleware's
# stand-ins (api/app.py `_log_user`) and the kinds `security.visitor` names.
_NOBODY = frozenset({"", "-", "?", "anon", "guest", "session", "token"})

# The shell's routes (frontend/app/src/shell/pages.ts): a top-level hit on one
# is the page loading cold.
_SHELL_PAGES = frozenset({
    "home", "today", "portfolio", "review", "import", "ticker", "sentiment",
    "sector", "earnings", "learn", "profile", "bank",
})

# What each page asks `/api/v1/` for, by prefix; the first match wins, so a
# longer prefix sits before the shorter one it extends. Calls that every page
# makes (`me`, `prefs`, `i18n/*`, `progress`, `market/*`...) match nothing
# and count for no page.
_PAGE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("home/", "home"), ("movers", "home"), ("extremes", "home"),
    ("daily", "home"), ("watchlist/", "ticker"), ("watchlist", "home"),
    ("today", "today"),
    ("portfolio/", "portfolio"),
    ("review", "review"),
    ("import/", "import"),
    ("ticker/", "ticker"),
    ("pulse", "sentiment"),
    ("sector", "sector"),
    ("earnings", "earnings"),
    ("learn", "learn"),
    ("profile", "profile"),
    ("bank", "bank"), ("connections", "bank"),
    ("journal", "profile"),  # the decision journal lives on the profile page
    ("chat/", "chat"),
)
_API = "/api/v1/"


def usage_entries(
    *,
    project: str = PROJECT,
    service: str = SERVICE,
    freshness: str = "7d",
    limit: int = 20000,
) -> list[dict]:
    """Both streams `usage` reads: the app's events, then the access log
    without the probe and the assets."""
    app = read(
        build_filter(service=service, project=project),
        project=project, freshness=freshness, limit=limit,
    )
    web = read(
        build_filter(service=service, project=project, http=True,
                     extra=USAGE_HTTP_EXTRA),
        project=project, freshness=freshness, limit=limit,
    )
    return app + web


def page_of(url: str) -> str | None:
    """The page a request belongs to, or None when it is not someone using one."""
    path = urlsplit(url).path if "://" in url else url.split("?", 1)[0]
    if path.startswith(_API):
        rest = path[len(_API):]
        for prefix, page in _PAGE_PREFIXES:
            if rest.startswith(prefix):
                return page
        return None
    slug = path.strip("/").split("/", 1)[0]
    return slug if slug in _SHELL_PAGES else None


def _is_person(user_agent: str | None) -> bool:
    """A browser, as against the probe, the scheduler, a script or a crawler."""
    agent = user_agent or ""
    return agent.startswith("Mozilla/") and not is_bot(agent)


def _epoch(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0.0


_USAGE_COUNTS = ("views", "chat", "logins", "signups", "imports", "first_imports",
                 "feedback")


def usage(entries: Iterable[dict]) -> dict:
    """Product-usage rollup out of the logs the app already writes — per day.

    Two streams, read together. The app's events say who: a "user" is an
    account slug on any line that day (the request middleware stamps every
    event with it), a chat turn is `chat.answered`, a login `auth.login`, a
    signup `auth.signup`, an import `import.committed` (`first` marks the one
    that replaced the demo book), feedback the widget. The access log says
    what was looked at: a "visitor" is an address that called a page's API
    from a browser (`page_of`, `_is_person`), and a "view" is one address on
    one page, counted again only after `VIEW_WINDOW_S` of silence.

    Guests and token callers (the warm-up, the MCP) carry no slug and count as
    visitors only. Entries without a timestamp are skipped.
    """
    days: dict[str, dict] = {}
    pages: dict[str, int] = {}
    all_users: set[str] = set()
    all_visitors: set[str] = set()
    last_view: dict[tuple[str, str], float] = {}

    def row(day: str) -> dict:
        return days.setdefault(
            day, {"day": day, "users": set(), "visitors": set(),
                  **dict.fromkeys(_USAGE_COUNTS, 0)},
        )

    for entry in sorted(entries, key=lambda e: str(e.get("timestamp") or "")):
        stamp = str(entry.get("timestamp") or "")
        day = stamp[:10]
        if not day:
            continue
        req = entry.get("httpRequest")
        if req and "jsonPayload" not in entry and "textPayload" not in entry:
            page = page_of(str(req.get("requestUrl") or ""))
            if page is None or not _is_person(req.get("userAgent")):
                continue
            ip = str(req.get("remoteIp") or "?")
            d = row(day)
            d["visitors"].add(ip)
            all_visitors.add(ip)
            at = _epoch(stamp)
            if at - last_view.get((ip, page), float("-inf")) >= VIEW_WINDOW_S:
                last_view[(ip, page)] = at
                d["views"] += 1
                pages[page] = pages.get(page, 0) + 1
            continue
        body = payload(entry)
        d = row(day)
        user = str(body.get("user") or "")
        if user not in _NOBODY:
            d["users"].add(user)
            all_users.add(user)
        event = str(body.get("event") or "")
        if event == "chat.answered":
            d["chat"] += 1
        elif event == "auth.login":
            d["logins"] += 1
        elif event == "auth.signup":
            d["signups"] += 1
        elif event == "import.committed":
            d["imports"] += 1
            if body.get("first"):
                d["first_imports"] += 1
        elif event == "feedback":
            d["feedback"] += 1
    rows = [
        {**d, "users": len(d["users"]), "visitors": len(d["visitors"])}
        for _, d in sorted(days.items())
    ]
    return {
        "days": rows,
        "pages": sorted(pages.items(), key=lambda kv: (-kv[1], kv[0])),
        "total_users": len(all_users),
        "total_visitors": len(all_visitors),
    }


def render_usage(summary: dict) -> str:
    if not summary["days"]:
        return "(no entries in range)"
    cols = (("day", 12), ("users", 6), ("visitors", 9), ("views", 6), ("chat", 5),
            ("logins", 7), ("signups", 8), ("imports", 8), ("feedback", 9))
    head = " ".join(
        f"{name:<{width}}" if name == "day" else f"{name:>{width}}"
        for name, width in cols
    )
    lines = [head, "-" * len(head)]
    for d in summary["days"]:
        lines.append(" ".join(
            f"{d[name]:<{width}}" if name == "day" else f"{d[name]:>{width}}"
            for name, width in cols
        ))
    first = sum(d["first_imports"] for d in summary["days"])
    imports = sum(d["imports"] for d in summary["days"])
    lines.append(
        f"\nin range: {summary['total_users']} accounts, "
        f"{summary['total_visitors']} addresses; "
        f"{first} of {imports} imports were an account's first"
    )
    if summary["pages"]:
        lines.append("\nviews by page:")
        for page, count in summary["pages"]:
            lines.append(f"  {page:<28} {count:>6}")
    return "\n".join(lines)


# The four steps a promoted link travels, in order. `web.attribution` emits the
# first two, the OIDC callback the third, the import API the fourth — this is
# only the arithmetic over them.
FUNNEL_STEPS = ("landing.view", "landing.cta", "auth.signup", "import.committed")

# A signup "came back" when the account shows up again this many days after
# it was created: one week is past the first look and the import that follows
# it, so a return is the habit forming rather than the onboarding finishing.
RETURN_DAYS = 7


def _retention(signups: dict[str, str], seen: dict[str, set[str]], last: str) -> dict:
    """Signups old enough to judge, and how many were seen RETURN_DAYS later.

    `last` is the newest day in the range: a signup whose week has not ended
    by then is not counted either way, so a fresh cohort never drags the rate
    down. Any event carrying the account slug counts as a visit — the log
    has no "page view" of its own, and a session cookie outlives a login.
    """
    eligible = returned = 0
    for user, day in signups.items():
        try:
            due = (datetime.strptime(day, "%Y-%m-%d")
                   + timedelta(days=RETURN_DAYS)).strftime("%Y-%m-%d")
        except ValueError:
            continue
        if due > last:
            continue
        eligible += 1
        if any(d >= due for d in seen.get(user, ())):
            returned += 1
    return {"days": RETURN_DAYS, "eligible": eligible, "returned": returned}


def funnel(entries: Iterable[dict]) -> dict:
    """Landing view -> app entry -> signup -> first import, per day and per source.

    Crawlers are excluded everywhere (`bot` on the event, set by
    `web.attribution.is_bot`): a conversion rate whose denominator is mostly
    Googlebot flatters every channel equally and ranks none of them.

    A source is the campaign token the link carried; requests that arrived with
    none are grouped under "-", which is the honest answer for a bookmark, a
    typed address, or a post that dropped the parameter.

    Signups are also counted by `wall` — the in-app prompt that was pressed
    (the locked assistant, a page's banner, the rail; `oidc._wall`) — which
    says which ask converts where `src` says which post brought the visitor.

    The import step is the *activation*: an account's first real import, the
    one that replaces the demo book, counted once per account. The import
    routes say which commit that was (`first` on the event); a second
    statement, or a wipe and re-import, is use, not conversion. Events from
    before the flag are deduplicated by account slug instead, so the oldest
    import an account shows in the range is the one that counts.

    `retention` closes the loop: of the signups old enough to tell, how many
    were seen again RETURN_DAYS later (`_retention`).
    """
    days: dict[str, dict] = {}
    walls: dict[str, int] = {}
    sources: dict[str, dict] = {}
    signups: dict[str, str] = {}  # account slug -> day it signed up
    seen: dict[str, set[str]] = {}  # account slug -> days with any event
    activated: set[str] = set()  # slugs whose first import is already counted
    last = ""
    totals = dict.fromkeys(("views", "ctas", "signups", "imports"), 0)
    step_of = {
        "landing.view": "views",
        "landing.cta": "ctas",
        "auth.signup": "signups",
        "import.committed": "imports",
    }
    for entry in entries:
        body = payload(entry)
        if body.get("bot"):
            continue
        day = str(entry.get("timestamp", ""))[:10] or "-"
        user = str(body.get("user") or "")
        if day != "-":
            last = max(last, day)
            if user and user != "-":
                seen.setdefault(user, set()).add(day)
        step = step_of.get(str(body.get("event") or ""))
        if step is None:
            continue
        if step == "signups" and user and user != "-":
            signups.setdefault(user, day)
        if step == "imports":
            if body.get("first") is False:
                continue
            if user and user != "-":
                if user in activated:
                    continue
                activated.add(user)
        src = str(body.get("src") or "-")
        for bucket, key in ((days, day), (sources, src)):
            row = bucket.setdefault(
                key, dict.fromkeys(("views", "ctas", "signups", "imports"), 0)
            )
            row[step] += 1
        totals[step] += 1
        if step == "signups":
            wall = str(body.get("wall") or "-")
            walls[wall] = walls.get(wall, 0) + 1
    return {
        "days": [{"day": d, **row} for d, row in sorted(days.items())],
        "sources": sorted(
            ({"src": s, **row} for s, row in sources.items()),
            key=lambda r: (r["signups"], r["ctas"], r["views"]),
            reverse=True,
        ),
        "totals": totals,
        "walls": sorted(
            ({"wall": w, "signups": n} for w, n in walls.items()),
            key=lambda r: (r["signups"], r["wall"]),
            reverse=True,
        ),
        "retention": _retention(signups, seen, last),
    }


def _rate(part: int, whole: int) -> str:
    """A percentage, or "-" when the denominator makes one meaningless."""
    return f"{100 * part / whole:.1f}%" if whole else "-"


def render_funnel(summary: dict) -> str:
    if not summary["days"]:
        return "(no funnel events in range)"
    lines = []
    head = f"{'day':<12} {'views':>7} {'entries':>8} {'signups':>8} {'imports':>8}"
    lines += [head, "-" * len(head)]
    for d in summary["days"]:
        lines.append(
            f"{d['day']:<12} {d['views']:>7} {d['ctas']:>8} "
            f"{d['signups']:>8} {d['imports']:>8}"
        )
    t = summary["totals"]
    lines.append(
        f"\ntotal: {t['views']} views -> {t['ctas']} entries "
        f"({_rate(t['ctas'], t['views'])}) -> {t['signups']} signups "
        f"({_rate(t['signups'], t['ctas'])}) -> {t['imports']} first imports "
        f"({_rate(t['imports'], t['signups'])})"
    )
    r = summary.get("retention") or {}
    if r.get("eligible"):
        lines.append(
            f"came back after {r['days']}d: {r['returned']} of {r['eligible']} "
            f"signups ({_rate(r['returned'], r['eligible'])})"
        )
    if summary["sources"]:
        head = f"{'source':<24} {'views':>7} {'entries':>8} {'signups':>8} {'entry%':>8}"
        lines += ["\nby source:", head, "-" * len(head)]
        for r in summary["sources"]:
            lines.append(
                f"{r['src'][:24]:<24} {r['views']:>7} {r['ctas']:>8} "
                f"{r['signups']:>8} {_rate(r['ctas'], r['views']):>8}"
            )
    if summary.get("walls"):
        head = f"{'signed in from':<24} {'signups':>8}"
        lines += ["\nby prompt:", head, "-" * len(head)]
        for r in summary["walls"]:
            lines.append(f"{r['wall'][:24]:<24} {r['signups']:>8}")
    return "\n".join(lines)


# ------------------------------------------------------------------- connector

#: The connector funnel's events, fetched together (`stocks logs connector`).
CONNECTOR_EXTRA = (
    'jsonPayload.event=("connector.card" OR "connector.copy" OR "mcp.consent"'
    ' OR "mcp.grant" OR "mcp.tool")'
)

_CONNECTOR_STEPS = ("card", "copy", "allow", "used")


def connector(entries: Iterable[dict]) -> dict:
    """Profile's Claude tab -> address copied -> approved -> first tool call.

    Counted in accounts, not events: a reader who opens the tab five times
    and copies twice is one reader who copied. `card` is split by `src`
    (what sent them there: the chat's nudge, the "what's new" card, the
    tour, or the tab picked by hand), which is the question the nudges were
    built to answer. `allow` is the consent screen's yes, which names the
    account; `mcp.grant` does not (it happens on the token exchange, in no
    one's session), so grants are a count beside the funnel, not a step.
    `used` is an account with any `mcp.tool` call in range — whether or not
    it saw the card in range, since a connection made last month still
    counts as a reader the connector kept.
    """
    reached: dict[str, set[str]] = {step: set() for step in _CONNECTOR_STEPS}
    by_src: dict[str, set[str]] = {}
    grants = denied = 0
    for entry in entries:
        body = payload(entry)
        name = str(body.get("event") or "")
        user = str(body.get("user") or "")
        if name == "mcp.grant":
            grants += 1
            continue
        if not user or user in ("-", "anon", "?"):
            continue
        if name == "connector.card":
            reached["card"].add(user)
            by_src.setdefault(str(body.get("src") or "-"), set()).add(user)
        elif name == "connector.copy":
            reached["copy"].add(user)
        elif name == "mcp.consent" and body.get("step") == "allow":
            reached["allow"].add(user)
        elif name == "mcp.consent" and body.get("step") == "deny":
            denied += 1
        elif name == "mcp.tool":
            reached["used"].add(user)
    return {
        "steps": {step: len(users) for step, users in reached.items()},
        "sources": sorted(
            ({"src": s, "accounts": len(u)} for s, u in by_src.items()),
            key=lambda r: (r["accounts"], r["src"]),
            reverse=True,
        ),
        "grants": grants,
        "denied": denied,
    }


def render_connector(summary: dict) -> str:
    steps = summary["steps"]
    if not any(steps.values()) and not summary["grants"]:
        return "(no connector events in range)"
    labels = {
        "card": "saw the Claude tab",
        "copy": "copied the address",
        "allow": "approved in TopStocks",
        "used": "called a tool",
    }
    lines = [f"{'accounts':<24} {'n':>6} {'of prev':>8}", "-" * 40]
    prev = None
    for step in _CONNECTOR_STEPS:
        n = steps[step]
        rate = _rate(n, prev) if prev is not None else ""
        lines.append(f"{labels[step]:<24} {n:>6} {rate:>8}")
        prev = n
    lines.append(f"\ngrants issued: {summary['grants']}   denied: {summary['denied']}")
    if summary["sources"]:
        lines += ["\nsent to the tab by:", f"{'source':<24} {'accounts':>8}", "-" * 33]
        for r in summary["sources"]:
            lines.append(f"{r['src'][:24]:<24} {r['accounts']:>8}")
    return "\n".join(lines)


# ---------------------------------------------------------------------- skills

#: Row labels for turns that loaded no skill, and for turns logged before
#: `chat.cost` named its skills (and never rated, so no thumbs says either).
NO_SKILL = "(none)"
UNKNOWN_SKILL = "(unknown)"


def skills(entries: Iterable[dict], ratings: Iterable[dict] = ()) -> dict:
    """Per chat skill: answers, what they cost and what the thumbs said.

    `entries` are the app log (one `chat.cost` per turn: `turn`, `skills`,
    `usd`); `ratings` the stored thumbs (`feedback.latest_ratings`), crossed
    with the turns by their turn id. A turn that loaded several skills counts
    in each of them in full, so the rows overlap and do not sum to the totals;
    `answers` and `usd` in the result are the distinct turns. A turn on an
    unpriced model has no cost (`priced` counts the ones that do), so the mean
    is over the priced turns only. Ratings of turns outside the log range are
    counted in `unmatched`, not in a row. Only skill names, ids and numbers
    are read: no message text, no account.
    """
    turns: dict[str, dict] = {}
    for entry in entries:
        body = payload(entry)
        if body.get("event") != "chat.cost":
            continue
        usd = body.get("usd")
        names = body.get("skills")
        turns[str(body.get("turn") or id(entry))] = {
            "skills": ([str(x) for x in names] or [NO_SKILL])
            if isinstance(names, list)
            else [UNKNOWN_SKILL],
            "usd": float(usd) if isinstance(usd, (int, float)) else None,
            "vote": None,
        }
    unmatched = 0
    for rating in ratings:
        vote = rating.get("vote")
        turn = turns.get(str(rating.get("turn") or ""))
        if rating.get("kind") != "rating" or vote not in ("up", "down"):
            continue
        if turn is None:
            unmatched += 1
            continue
        turn["vote"] = vote
        if turn["skills"] == [UNKNOWN_SKILL] and rating.get("skills"):
            turn["skills"] = [str(x) for x in rating["skills"]]
    rows: dict[str, dict] = {}
    for turn in turns.values():
        for name in turn["skills"]:
            r = rows.setdefault(
                name,
                {
                    "skill": name,
                    "answers": 0,
                    "priced": 0,
                    "usd": 0.0,
                    "up": 0,
                    "down": 0,
                },
            )
            r["answers"] += 1
            if turn["usd"] is not None:
                r["priced"] += 1
                r["usd"] += turn["usd"]
            if turn["vote"]:
                r[turn["vote"]] += 1
    out: list[dict] = []
    for r in rows.values():
        voted = r["up"] + r["down"]
        out.append(
            {
                **r,
                "usd": round(r["usd"], 6),
                "mean_usd": r["usd"] / r["priced"] if r["priced"] else None,
                "share_up": r["up"] / voted if voted else None,
            }
        )
    out.sort(key=lambda r: (-float(r["usd"]), -int(r["answers"]), r["skill"]))
    priced = [t["usd"] for t in turns.values() if t["usd"] is not None]
    return {
        "rows": out,
        "answers": len(turns),
        "usd": round(sum(priced), 6),
        "unmatched": unmatched,
    }


def render_skills(summary: dict) -> str:
    """The `skills` table, dearest skill first."""
    rows = summary["rows"]
    if not rows:
        return "(no chat.cost entries in range)"
    width = max(5, *(len(r["skill"]) for r in rows))
    head = (
        f"{'skill':<{width}}  {'answers':>7}  {'total $':>9}  {'mean $':>8}"
        f"  {'up':>4}  {'down':>4}  {'up %':>5}"
    )
    lines = [head, "-" * len(head)]
    for r in rows:
        mean = f"{r['mean_usd']:.4f}" if r["mean_usd"] is not None else "-"
        share = f"{r['share_up'] * 100:.0f}%" if r["share_up"] is not None else "-"
        lines.append(
            f"{r['skill']:<{width}}  {r['answers']:>7}  {r['usd']:>9.4f}"
            f"  {mean:>8}  {r['up']:>4}  {r['down']:>4}  {share:>5}"
        )
    lines.append(
        f"{summary['answers']} answers, ${summary['usd']:.4f} in all; a "
        "turn counts in every skill it loaded"
    )
    if summary["unmatched"]:
        lines.append(f"{summary['unmatched']} ratings of answers outside the range")
    return "\n".join(lines)


# One route, not one URL: the access log carries a symbol or an id in the
# path, and `/ticker/NVDA/compare` is the same code as `/ticker/AAPL/compare`.
_ROUTE_IDS = (
    (re.compile(r"/ticker/[^/]+"), "/ticker/{t}"),
    (re.compile(r"/conversations/[^/]+"), "/conversations/{id}"),
    (re.compile(r"/threads/[^/]+"), "/threads/{id}"),
    (re.compile(r"/runs/[^/]+"), "/runs/{id}"),
    (re.compile(r"/turns/[^/]+"), "/turns/{id}"),
    (re.compile(r"/memories/[^/]+"), "/memories/{id}"),
    (re.compile(r"/changes/[^/]+"), "/changes/{id}"),
    (re.compile(r"/sessions/[^/]+"), "/sessions/{id}"),
    (re.compile(r"/connections/[^/]+"), "/connections/{id}"),
    (re.compile(r"/watchlist/[^/]+"), "/watchlist/{t}"),
    (re.compile(r"/i18n/[^/]+"), "/i18n/{lang}"),
    (re.compile(r"/lessons/[^/]+"), "/lessons/{id}"),
)


def route_of(url: str) -> str:
    """The route a request URL belongs to: path only, ids collapsed."""
    path = urlsplit(url).path if "://" in url else url.split("?", 1)[0]
    for pattern, placeholder in _ROUTE_IDS:
        path = pattern.sub(placeholder, path)
    return path


def _latency_ms(entry: dict) -> float | None:
    """`httpRequest.latency` ("1.234s") in milliseconds, or None."""
    raw = (entry.get("httpRequest") or {}).get("latency")
    if not isinstance(raw, str) or not raw.endswith("s"):
        return None
    try:
        return float(raw[:-1]) * 1000.0
    except ValueError:
        return None


# A request slower than this is listed by itself under the table: the ones a
# reader actually sat through, with the time they happened.
SLOW_MS = 10_000.0


def http_stats(entries: Iterable[dict], *, slow_ms: float = SLOW_MS) -> dict:
    """Per-route counts and latency percentiles from the access log.

    Groups on method + route (`route_of`), so one row is one handler. Errors
    are 5xx answers. `slow` lists every request over `slow_ms`, oldest first,
    so the daily cold cluster shows up as a cluster.
    """
    groups: dict[str, dict] = {}
    slow: list[dict] = []
    for entry in entries:
        r = entry.get("httpRequest")
        if not r:
            continue
        key = f"{r.get('requestMethod') or '?'} {route_of(r.get('requestUrl') or '')}"
        g = groups.setdefault(key, {"key": key, "count": 0, "errors": 0, "ms": []})
        g["count"] += 1
        status = r.get("status")
        if isinstance(status, int) and status >= 500:
            g["errors"] += 1
        ms = _latency_ms(entry)
        if ms is None:
            continue
        g["ms"].append(ms)
        if ms > slow_ms:
            slow.append({"at": entry.get("timestamp", ""), "key": key, "ms": round(ms)})
    rows: list[dict] = []
    for g in groups.values():
        ms = g.pop("ms")
        rows.append({
            **g,
            "p50_ms": round(_pct(ms, 0.50)) if ms else None,
            "p90_ms": round(_pct(ms, 0.90)) if ms else None,
            "p95_ms": round(_pct(ms, 0.95)) if ms else None,
            "max_ms": round(max(ms)) if ms else None,
        })
    rows.sort(key=lambda g: g["count"], reverse=True)
    slow.sort(key=lambda s: s["at"])
    total = sum(g["count"] for g in rows)
    return {"rows": rows, "slow": slow, "total": total}


def render_http_stats(summary: dict, *, top: int = 60) -> str:
    rows, slow, total = summary["rows"], summary["slow"], summary["total"]
    if not rows:
        return "(no requests in range)"
    head = (
        f"{'route':<52} {'count':>6} {'5xx':>4} {'p50':>7} {'p90':>7} "
        f"{'p95':>7} {'max':>7}"
    )
    lines = [head, "-" * len(head)]

    def ms(v):
        return "-" if v is None else f"{v}ms"

    for r in rows[:top]:
        lines.append(
            f"{r['key'][:52]:<52} {r['count']:>6} {r['errors']:>4} "
            f"{ms(r['p50_ms']):>7} {ms(r['p90_ms']):>7} {ms(r['p95_ms']):>7} "
            f"{ms(r['max_ms']):>7}"
        )
    if len(rows) > top:
        lines.append(f"... {len(rows) - top} more routes")
    share = f"{100.0 * len(slow) / total:.1f}%" if total else "0%"
    lines.append("")
    lines.append(f"requests over {SLOW_MS / 1000:.0f}s: {len(slow)} of {total} ({share})")
    for s in slow[-40:]:
        lines.append(f"  {_local_time(s['at'])}  {s['key']:<52} {s['ms']:>7}ms")
    return "\n".join(lines)


def render_stats(rows: Sequence[dict], *, by: str = "event") -> str:
    if not rows:
        return "(no entries in range)"
    head = f"{by:<32} {'count':>7} {'errors':>7} {'p50':>8} {'p95':>8} {'max':>8}"
    lines = [head, "-" * len(head)]
    for r in rows:
        def ms(v):
            return "-" if v is None else f"{v}ms"
        lines.append(
            f"{r['key'][:32]:<32} {r['count']:>7} {r['errors']:>7} "
            f"{ms(r['p50_ms']):>8} {ms(r['p95_ms']):>8} {ms(r['max_ms']):>8}"
        )
    return "\n".join(lines)
