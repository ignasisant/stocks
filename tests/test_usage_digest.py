"""The owner's Monday Telegram: usage and funnel from one week of logs."""

from __future__ import annotations

import json

import pytest

from stocks import logs_query as lq
from stocks.notify import usage_digest as ud

BROWSER = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1"


def app(event: str, at: str, **fields) -> dict:
    return {"timestamp": at, "jsonPayload": {"event": event, **fields}}


def hit(url: str, *, ip: str, at: str) -> dict:
    return {
        "timestamp": at,
        "httpRequest": {
            "requestMethod": "GET", "requestUrl": f"https://x.app{url}",
            "status": 200, "remoteIp": ip, "userAgent": BROWSER,
        },
    }


WEEK = [
    hit("/api/v1/home/summary", ip="1.1.1.1", at="2026-10-19T08:00:00Z"),
    hit("/api/v1/portfolio/kpis", ip="1.1.1.1", at="2026-10-19T08:01:00Z"),
    hit("/api/v1/home/summary", ip="2.2.2.2", at="2026-10-20T09:00:00Z"),
    app("auth.login", "2026-10-19T08:00:30Z", user="ana"),
    app("chat.answered", "2026-10-19T08:05:00Z", user="ana"),
    app("landing.view", "2026-10-20T10:00:00Z", user="anon"),
    app("landing.cta", "2026-10-20T10:00:10Z", user="anon"),
    app("auth.signup", "2026-10-20T10:01:00Z", user="bea"),
    app("import.committed", "2026-10-20T10:05:00Z", user="bea", first=True),
]


def test_render_is_one_html_message_a_phone_can_read():
    text = ud.render(ud.summarise(WEEK), "en")
    assert text.startswith("<b>📈 TopStocks — the week in numbers</b> · 10-19 – 10-20")
    pre = text.split("<pre>", 1)[1].split("</pre>", 1)[0]
    rows = pre.splitlines()
    assert rows[0].split() == ["day", "acc", "vis", "views", "chat"]
    assert rows[1].split() == ["10-19", "1", "1", "2", "1"]
    assert rows[2].split() == ["10-20", "1", "1", "1", "0"]
    assert all(len(r) <= 35 for r in rows)
    assert "2 accounts · 2 addresses · 1 sign-ins · 1 signups" in text
    assert "1 imports (1 first) · 1 chat turns" in text
    assert "Pages: home 2 · portfolio 1" in text
    assert "Funnel: 1 landing views → 1 entries → 1 signups → 1 first imports" in text
    # No HTML slipped through unescaped outside the tags we wrote.
    assert text.count("<") == text.count(">") == 4  # b, /b, pre, /pre


def test_render_speaks_spanish_and_survives_an_empty_week():
    assert "la semana en cifras" in ud.render(ud.summarise(WEEK), "es")
    assert "Embudo:" in ud.render(ud.summarise(WEEK), "es")
    empty = ud.render(ud.summarise([]), "en")
    assert "No entries in the range." in empty


def test_the_recipient_is_the_configured_chat_else_the_owners_linked_one(
    monkeypatch, tmp_path
):
    prefs = tmp_path / "prefs.json"
    prefs.write_text(json.dumps({"telegram_chat_id": 4242, "language": "es"}))
    monkeypatch.setattr(ud, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ud.storage, "restore", lambda path: False)
    monkeypatch.setattr(ud, "secret", lambda *a, **k: "")
    assert ud.owner_chat_id() == "4242"
    assert ud.owner_lang() == "es"
    monkeypatch.setattr(ud, "secret", lambda *a, **k: "777")
    assert ud.owner_chat_id() == "777"
    prefs.unlink()
    monkeypatch.setattr(ud, "secret", lambda *a, **k: "")
    assert ud.owner_chat_id() == ""
    assert ud.owner_lang() == "en"


def test_run_sends_the_owner_one_message_and_a_dry_run_sends_nothing(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr(ud.telegram, "send_message",
                        lambda text, chat, **kw: sent.append((text, chat, kw)))
    monkeypatch.setattr(ud, "owner_chat_id", lambda: "4242")
    monkeypatch.setattr(ud, "owner_lang", lambda: "en")

    status, text = ud.run(entries=WEEK, dry_run=True)
    assert status == "dry-run" and "week in numbers" in text and not sent

    status, text = ud.run(entries=WEEK)
    assert status == "sent"
    assert sent == [(text, "4242", {"parse_mode": "HTML"})]


def test_run_without_a_recipient_keeps_the_text_and_sends_nothing(monkeypatch):
    monkeypatch.setattr(ud.telegram, "send_message",
                        lambda *a, **k: pytest.fail("must not send"))
    monkeypatch.setattr(ud, "owner_chat_id", lambda: "")
    monkeypatch.setattr(ud, "owner_lang", lambda: "en")
    status, text = ud.run(entries=WEEK)
    assert status == "no recipient" and "week in numbers" in text


def test_run_reads_both_streams_when_no_entries_are_given(monkeypatch):
    asked: dict = {}

    def fake_entries(*, project, service, freshness):
        asked.update(project=project, service=service, freshness=freshness)
        return WEEK

    monkeypatch.setattr(lq, "usage_entries", fake_entries)
    monkeypatch.setattr(ud, "owner_lang", lambda: "en")
    status, _ = ud.run(since="3d", dry_run=True)
    assert status == "dry-run"
    assert asked == {"project": lq.PROJECT, "service": lq.SERVICE, "freshness": "3d"}
