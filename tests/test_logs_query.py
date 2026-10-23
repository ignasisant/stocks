"""The `stocks logs` read side (stocks.logs_query): filters, rendering, stats."""

from __future__ import annotations

import json

import pytest

from stocks import logs_query as lq


def entry(**payload) -> dict:
    sev = payload.pop("severity", "INFO")
    return {
        "timestamp": payload.pop("timestamp", "2026-08-31T13:29:11.000Z"),
        "severity": sev,
        "jsonPayload": payload,
    }


# ------------------------------------------------------------------- filters


def test_filter_excludes_the_access_log_by_default():
    f = lq.build_filter(project="p", service="svc")
    assert 'resource.labels.service_name="svc"' in f
    assert 'logName!="projects/p/logs/run.googleapis.com%2Frequests"' in f


def test_filter_reads_the_cron_job_beside_the_service():
    # The morning market read runs as a Cloud Run job (infra/cron.tf) and logs
    # under its own resource type; a view of the app's lines includes it.
    f = lq.build_filter(service="svc", job="svc-cron")
    app = 'resource.type="cloud_run_revision" AND resource.labels.service_name="svc"'
    cron = 'resource.type="cloud_run_job" AND resource.labels.job_name="svc-cron"'
    assert f"(({app}) OR ({cron}))" in f


def test_admin_audit_entries_are_excluded_from_the_app_view():
    # A 403 on a console API call is logged against the same resource at ERROR;
    # it is not the app failing.
    assert 'NOT logName:"cloudaudit"' in lq.build_filter()
    assert "cloudaudit" not in lq.build_filter(http=True)


def test_http_flag_selects_the_access_log_instead():
    f = lq.build_filter(project="p", http=True)
    assert 'logName="projects/p/logs/run.googleapis.com%2Frequests"' in f
    assert "logName!=" not in f


def test_structured_options_become_field_equalities():
    f = lq.build_filter(level="error", event="page.render", user="u_1",
                        revision="topstocks-00005-r7w")
    assert "severity>=ERROR" in f
    assert 'jsonPayload.event="page.render"' in f
    assert 'jsonPayload.user="u_1"' in f
    assert 'resource.labels.revision_name="topstocks-00005-r7w"' in f


def test_grep_searches_both_payload_shapes():
    f = lq.build_filter(grep="rate limit")
    assert 'textPayload:"rate limit"' in f
    assert 'jsonPayload.message:"rate limit"' in f


def test_grep_quotes_are_escaped():
    assert '\\"boom\\"' in lq.build_filter(grep='say "boom"')


# ------------------------------------------------------------------ payloads


def test_payload_reads_free_text_lines():
    assert lq.payload({"textPayload": "HTTP Error 404"})["message"] == "HTTP Error 404"


def test_payload_summarizes_access_log_entries():
    body = lq.payload({"httpRequest": {"requestMethod": "GET", "status": 500,
                                       "requestUrl": "/portfolio",
                                       "latency": "1.2s", "remoteIp": "1.2.3.4"}})
    assert body["message"] == "GET /portfolio"
    assert body["status"] == 500


# ----------------------------------------------------------------- rendering


def test_render_is_oldest_first_with_the_fields_appended():
    out = lq.render([
        entry(event="b", message="second", backend="groq"),
        entry(event="a", message="first"),
    ])
    lines = out.splitlines()
    assert lines[0].split()[3] == "a"       # the older entry leads
    assert "backend=groq" in lines[1]


def test_render_hides_stack_traces_unless_asked():
    e = entry(event="page.render", message="boom", severity="ERROR",
              stack_trace="Traceback...\n  ValueError")
    assert "Traceback" not in lq.render([e])
    assert "Traceback" in lq.render([e], show_trace=True)


def test_multiline_messages_collapse_to_one_row():
    out = lq.render([entry(event="x", message="head\nTraceback (most recent...)")])
    assert out.count("\n") == 0
    assert "Traceback" not in out


# --------------------------------------------------------------------- stats


def test_stats_counts_errors_and_percentiles_per_event():
    rows = lq.stats([
        entry(event="page.render", duration_ms=100),
        entry(event="page.render", duration_ms=300),
        entry(event="page.render", severity="ERROR", duration_ms=900),
        entry(event="chat.answered", duration_ms=50),
    ])
    page = next(r for r in rows if r["key"] == "page.render")
    assert page["count"] == 3
    assert page["errors"] == 1
    assert page["max_ms"] == 900
    assert page["p50_ms"] == 300
    assert rows[0]["key"] == "page.render"  # busiest first


def test_stats_groups_by_any_field():
    rows = lq.stats([entry(event="e", user="u_1"), entry(event="e", user="u_2")],
                    by="user")
    assert {r["key"] for r in rows} == {"u_1", "u_2"}


def test_stats_keeps_unstructured_lines_visible():
    rows = lq.stats([{"timestamp": "", "severity": "ERROR",
                      "textPayload": "HTTP Error 404"}])
    assert rows[0]["key"] == "-"
    assert rows[0]["errors"] == 1
    assert rows[0]["p50_ms"] is None


def test_render_stats_handles_an_empty_range():
    assert "no entries" in lq.render_stats([])


# ------------------------------------------------------------- export/import


def test_export_round_trips_through_jsonl(tmp_path):
    entries = [entry(event="a"), entry(event="b")]
    out = lq.export(entries, tmp_path / "snap.jsonl")
    assert lq.read_file(out) == entries


def test_read_surfaces_gcloud_failures_as_logs_error(monkeypatch):
    monkeypatch.setattr(lq.shutil, "which", lambda _: "/usr/bin/gcloud")

    class Proc:
        returncode = 1
        stdout = ""
        stderr = "ERROR: (gcloud.logging.read) You do not have permission"

    monkeypatch.setattr(lq.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(lq.LogsError, match="permission"):
        lq.read("filter")


def test_read_without_gcloud_or_credentials_explains_how_to_get_them(monkeypatch):
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError

    monkeypatch.setattr(lq.shutil, "which", lambda _: None)

    def no_creds(**_):
        raise DefaultCredentialsError("nothing here")

    monkeypatch.setattr(google.auth, "default", no_creds)
    with pytest.raises(lq.LogsError, match="gcloud auth login"):
        lq.read("filter")


def test_span_reads_gclouds_freshness_spelling():
    assert lq._span("30m") == lq.timedelta(minutes=30)
    assert lq._span("7d") == lq.timedelta(days=7)
    with pytest.raises(lq.LogsError, match="unreadable"):
        lq._span("last week")


class _Resp:
    def __init__(self, payload: dict, status: int = 200):
        self._payload, self.status_code = payload, status
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def test_read_without_gcloud_pages_through_the_logging_api(monkeypatch):
    monkeypatch.setattr(lq.shutil, "which", lambda _: None)
    monkeypatch.setattr(lq, "_access_token", lambda: "tok")
    calls: list[dict] = []
    pages = [
        {"entries": [{"n": 1}, {"n": 2}], "nextPageToken": "p2"},
        {"entries": [{"n": 3}]},
    ]

    class Client:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, *, json, headers):
            calls.append({"url": url, "json": dict(json), "headers": headers})
            return _Resp(pages[len(calls) - 1])

    monkeypatch.setattr(lq.httpx, "Client", Client)
    out = lq.read("severity>=ERROR", project="p", freshness="2d", limit=10)
    assert out == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert len(calls) == 2
    first = calls[0]["json"]
    assert first["resourceNames"] == ["projects/p"]
    assert first["filter"].startswith("(severity>=ERROR) AND timestamp>=")
    assert first["orderBy"] == "timestamp desc"
    assert first["pageSize"] == 10
    assert "pageToken" not in first
    assert calls[1]["json"]["pageToken"] == "p2"
    assert calls[0]["headers"] == {"Authorization": "Bearer tok"}


def test_the_logging_api_refusal_is_a_logs_error(monkeypatch):
    monkeypatch.setattr(lq.shutil, "which", lambda _: None)
    monkeypatch.setattr(lq, "_access_token", lambda: "tok")

    class Client:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return _Resp({"error": "PERMISSION_DENIED"}, status=403)

    monkeypatch.setattr(lq.httpx, "Client", Client)
    with pytest.raises(lq.LogsError, match="403"):
        lq.read("filter")


def test_usage_entries_reads_the_app_log_then_the_access_log(monkeypatch):
    filters: list[str] = []

    def fake_read(log_filter, *, project, freshness, limit):
        filters.append(log_filter)
        return [{"f": len(filters)}]

    monkeypatch.setattr(lq, "read", fake_read)
    out = lq.usage_entries(project="p", service="s", freshness="7d", limit=5)
    assert out == [{"f": 1}, {"f": 2}]
    access = '"projects/p/logs/run.googleapis.com%2Frequests"'
    assert f"logName!={access}" in filters[0]
    assert f"logName={access}" in filters[1]
    assert "/livez" in filters[1]


def test_read_parses_the_gcloud_json_output(monkeypatch):
    monkeypatch.setattr(lq.shutil, "which", lambda _: "/usr/bin/gcloud")
    captured = {}

    class Proc:
        returncode = 0
        stdout = json.dumps([entry(event="a")])
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Proc()

    monkeypatch.setattr(lq.subprocess, "run", fake_run)
    got = lq.read("my-filter", project="p", freshness="6h", limit=5)
    assert got[0]["jsonPayload"]["event"] == "a"
    assert "my-filter" in captured["cmd"]
    assert "--freshness" in captured["cmd"] and "6h" in captured["cmd"]


# --------------------------------------------------------------------- usage

BROWSER = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605"


def hit(url: str, *, ip: str = "1.2.3.4", at: str = "2026-08-31T13:29:11.000Z",
        ua: str = BROWSER, status: int = 200) -> dict:
    """One line of the Cloud Run access log, as `gcloud logging read` ships it."""
    return {
        "timestamp": at,
        "severity": "INFO",
        "httpRequest": {
            "requestMethod": "GET", "requestUrl": f"https://topstocks.example{url}",
            "status": status, "remoteIp": ip, "userAgent": ua, "latency": "0.1s",
        },
    }


def test_page_of_maps_api_calls_and_shell_routes_to_a_page():
    assert lq.page_of("https://h/api/v1/home/market") == "home"
    assert lq.page_of("/api/v1/movers?span=1d") == "home"
    assert lq.page_of("/api/v1/watchlist") == "home"
    assert lq.page_of("/api/v1/watchlist/AAPL/alerts") == "ticker"
    assert lq.page_of("/api/v1/ticker/AAPL/bars") == "ticker"
    assert lq.page_of("/api/v1/portfolio/summary") == "portfolio"
    assert lq.page_of("/api/v1/review/returns") == "review"
    assert lq.page_of("/api/v1/pulse/book") == "sentiment"
    assert lq.page_of("/api/v1/sectors/Technology") == "sector"
    assert lq.page_of("/api/v1/earnings/NFLX/result") == "earnings"
    assert lq.page_of("/api/v1/chat/conversations") == "chat"
    assert lq.page_of("/portfolio") == "portfolio"
    assert lq.page_of("/ticker?ticker=AAPL") == "ticker"
    # Every page makes these; they say nothing about which one was open.
    for url in ("/api/v1/progress", "/api/v1/me", "/api/v1/prefs", "/api/v1/i18n/es",
                "/api/v1/market/status", "/api/v1/hold", "/livez", "/", "/status",
                "/next-assets/app.js", "/lp/og.png"):
        assert lq.page_of(url) is None, url


def test_usage_http_filter_drops_the_probe_and_the_assets_server_side():
    f = lq.build_filter(project="p", http=True, extra=lq.USAGE_HTTP_EXTRA)
    assert 'logName="projects/p/logs/run.googleapis.com%2Frequests"' in f
    for noise in ("/livez", "/next-assets/", "/app/static/", "/lp/"):
        assert f'NOT httpRequest.requestUrl:"{noise}"' in f


def test_usage_counts_people_from_the_app_log_and_the_access_log_together():
    entries = [
        # Who: the app's events, stamped with the account slug by the middleware.
        entry(event="yahoo.quotes", user="jane_1a"),
        entry(event="auth.login", user="jane_1a", via="oidc"),
        entry(event="prices.live", user="bob_2b"),
        entry(event="chat.answered", chars=300),  # no slug on a chat turn
        entry(event="feedback", user="bob_2b", kind="bug"),
        entry(event="import.committed", user="bob_2b", first=True, n=40),
        entry(event="import.committed", user="jane_1a", first=False, n=12),
        # Stand-ins for "nobody" are never an account.
        entry(event="api.warm", user="token"),
        entry(event="prices.live", user="guest"),
        entry(event="cron.market", user="-"),
        entry(message="free text, no event"),
        # What: the Home page fans out into several calls — one view.
        hit("/api/v1/home/market", at="2026-08-31T13:29:11.000Z"),
        hit("/api/v1/movers", at="2026-08-31T13:29:12.000Z"),
        hit("/api/v1/daily", at="2026-08-31T13:29:40.000Z"),
        # ...and a second look well after the window is a second view.
        hit("/api/v1/home/market", at="2026-08-31T14:10:00.000Z"),
        # Another address, another page; the shell's own route counts too.
        hit("/portfolio", ip="9.9.9.9", at="2026-08-31T13:30:00.000Z"),
        hit("/api/v1/portfolio/summary", ip="9.9.9.9", at="2026-08-31T13:30:01.000Z"),
        # Not people: the probe, a scheduler, a link unfurler, a script.
        hit("/api/v1/home/market", ip="5.5.5.5", ua="Google-Cloud-Scheduler"),
        hit("/api/v1/movers", ip="6.6.6.6",
            ua="Slack-ImgProxy (+https://api.slack.com/robots)"),
        hit("/api/v1/earnings", ip="7.7.7.7", ua="python-httpx/0.28.1"),
        hit("/livez", ip="8.8.8.8", ua="GoogleStackdriverMonitoring-UptimeChecks"),
        # Calls every page makes say nothing about which page was open.
        hit("/api/v1/progress", ip="3.3.3.3"),
        # The next day, one account back on the ticker page.
        entry(event="yahoo.spark", user="jane_1a", timestamp="2026-09-01T09:00:00.000Z"),
        hit("/api/v1/ticker/AAPL/bars", at="2026-09-01T09:00:01.000Z"),
    ]
    s = lq.usage(entries)
    assert (s["total_users"], s["total_visitors"]) == (2, 2)
    d1, d2 = s["days"]
    assert d1["day"] == "2026-08-31"
    assert (d1["users"], d1["visitors"], d1["views"]) == (2, 2, 3)
    assert (d1["chat"], d1["logins"], d1["signups"]) == (1, 1, 0)
    assert (d1["imports"], d1["first_imports"], d1["feedback"]) == (2, 1, 1)
    assert (d2["day"], d2["users"], d2["visitors"], d2["views"]) == (
        "2026-09-01", 1, 1, 1,
    )
    assert s["pages"] == [("home", 2), ("portfolio", 1), ("ticker", 1)]


def test_usage_reads_the_entries_in_any_order():
    # gcloud ships newest first; the view window must not depend on that.
    forward = [
        hit("/api/v1/home/market", at="2026-08-31T13:29:11.000Z"),
        hit("/api/v1/movers", at="2026-08-31T13:29:12.000Z"),
        hit("/api/v1/home/market", at="2026-08-31T14:10:00.000Z"),
    ]
    assert lq.usage(forward)["pages"] == lq.usage(forward[::-1])["pages"] == [("home", 2)]


def test_usage_renders_and_survives_empty_input():
    assert lq.render_usage(lq.usage([])) == "(no entries in range)"
    text = lq.render_usage(lq.usage([
        entry(event="auth.login", user="jane_1a"),
        entry(event="import.committed", user="jane_1a", first=True),
        hit("/api/v1/home/market"),
    ]))
    assert "2026-08-31" in text
    assert ("in range: 1 accounts, 1 addresses; "
            "1 of 1 imports were an account's first") in text
    assert "views by page:" in text and "home" in text


def test_the_usage_command_reads_the_app_log_and_the_access_log(monkeypatch, capsys):
    import argparse

    from stocks import cli

    filters: list[str] = []

    def fake_read(log_filter, *, project, freshness, limit):
        filters.append(log_filter)
        if 'logName="projects/p/logs/run.googleapis.com%2Frequests"' in log_filter:
            return [hit("/api/v1/home/market")]
        return [entry(event="auth.login", user="jane_1a")]

    monkeypatch.setattr(lq, "read", fake_read)
    args = argparse.Namespace(
        logs_command="usage", file=None, level=None, service="svc", project="p",
        since="7d", limit=20000, event=None, user=None, grep=None, http=False,
        revision=None,
    )
    cli.cmd_logs(args)
    out = capsys.readouterr().out
    assert len(filters) == 2
    assert 'logName!="projects/p/logs/run.googleapis.com%2Frequests"' in filters[0]
    assert 'logName="projects/p/logs/run.googleapis.com%2Frequests"' in filters[1]
    assert 'NOT httpRequest.requestUrl:"/livez"' in filters[1]
    assert "2026-08-31" in out and "in range: 1 accounts, 1 addresses" in out


def test_several_snapshots_are_read_together(tmp_path, capsys):
    import argparse

    from stocks import cli

    app = tmp_path / "app.jsonl"
    app.write_text(json.dumps(entry(event="auth.login", user="jane_1a")) + "\n")
    http = tmp_path / "http.jsonl"
    http.write_text(json.dumps(hit("/api/v1/home/market")) + "\n")
    args = argparse.Namespace(
        logs_command="usage", file=[str(app), str(http)], level=None, service="svc",
        project="p", since="7d", limit=20000,
    )
    cli.cmd_logs(args)
    assert "in range: 1 accounts, 1 addresses" in capsys.readouterr().out

