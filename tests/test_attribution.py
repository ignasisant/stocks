"""Where a visitor came from, end to end.

The chain has four links and each one is a place the token can be dropped: the
landing logs it, the landing's script copies it onto the CTA, the gate folds it
into the sign-in round trip, and the callback writes it onto the new account.
Break any one and the funnel still reports numbers — wrong ones, silently — so
every link is asserted here rather than at its own layer only.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount
from starlette.testclient import TestClient

from stocks import accounts, logs_query, obs
from stocks.accounts import load_prefs, paths_for
from stocks.web import attribution, landing, landing_static, oidc, server

CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)


# ------------------------------------------------------------- the vocabulary


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"utm_source": "Rankia"}, "rankia"),
        ({"src": "spainfire"}, "spainfire"),
        ({"ref": "hn"}, "hn"),
        # utm_source is what a campaign builder writes; it wins over the app's
        # own shorthand when a link somehow carries both.
        ({"utm_source": "rankia", "src": "other"}, "rankia"),
        ({}, ""),
        ({"utm_source": "   "}, ""),
    ],
)
def test_source_reads_the_keys_in_order(params, expected):
    assert attribution.source(params) == expected


def test_a_source_is_normalised_into_a_log_field():
    assert attribution.source({"src": "Spain FIRE/weekly"}) == "spain-fire-weekly"
    assert attribution.source({"src": "--hn--"}) == "hn"
    long = attribution.source({"src": "x" * 80})
    assert len(long) == attribution.MAX_LEN


def test_a_hostile_source_cannot_reach_the_log_as_written():
    dirty = attribution.source({"utm_source": '<script>alert("x")</script>'})
    assert "<" not in dirty and '"' not in dirty and "(" not in dirty


@pytest.mark.parametrize(
    ("referer", "expected"),
    [
        ("https://www.reddit.com/r/SpainFIRE/comments/abc/", "reddit.com"),
        ("https://news.ycombinator.com/item?id=1", "news.ycombinator.com"),
        ("", ""),
        (None, ""),
        ("not a url", ""),
    ],
)
def test_only_the_referring_host_is_kept(referer, expected):
    """A referrer path is somebody else's reader's state; the host is enough."""
    assert attribution.ref_host(referer) == expected


@pytest.mark.parametrize(
    "agent",
    ["Googlebot/2.1", "curl/8.4.0", "python-requests/2.32", "GoogleHC/1.0", "", None],
)
def test_crawlers_and_scripts_are_not_readers(agent):
    assert attribution.is_bot(agent) is True


def test_a_browser_is_a_reader():
    assert attribution.is_bot(CHROME) is False


def test_fields_leaves_out_what_it_does_not_know():
    fields = attribution.fields(
        {"utm_source": "rankia", "utm_medium": "post"},
        referer="https://www.rankia.com/foros/x",
        user_agent=CHROME,
    )
    assert fields == {"src": "rankia", "medium": "post", "ref": "rankia.com"}
    assert attribution.fields({}, user_agent=CHROME) == {}
    assert attribution.fields({}, user_agent="Googlebot/2.1") == {"bot": True}


def test_carry_is_a_query_fragment_or_nothing():
    assert attribution.carry({"utm_source": "rankia"}) == "src=rankia"
    assert attribution.carry({}) == ""


def test_the_landing_script_forwards_exactly_what_the_server_reads():
    """The CTA script and `attribution` are one vocabulary in two languages."""
    js = landing.source_script()
    for key in attribution.SOURCE_KEYS:
        assert f'q.get("{key}")' in js
    assert f'"&{attribution.PARAM_SRC}="' in js
    assert f"slice(0, {attribution.MAX_LEN})" in js
    # Same sanitiser rule as the rest of the landing's inline scripts.
    assert "<" not in js.replace("<script>", "").replace("</script>", "")


# ------------------------------------------------------------------ the chain


@pytest.fixture
def events(monkeypatch) -> list[tuple[str, dict]]:
    """Every `obs.event` the request under test emits, in order."""
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(obs, "event", lambda name, **fields: seen.append((name, fields)))
    return seen


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    """The real gate in front of a stand-in shell (as in tests/test_server.py).

    Only the gate: the events under test are emitted before anything renders,
    and booting the real shell would need a build on disk to say nothing extra.
    """
    build = tmp_path / "app"
    build.mkdir()
    (build / "index.html").write_text("<html><body>APP-SHELL</body></html>")
    monkeypatch.setattr(server, "_APP_BUILD", build)
    server._app_document.cache_clear()
    landing_static.document.cache_clear()
    server._gzipped.cache_clear()
    monkeypatch.setattr(server, "secret", lambda *a, **k: "")
    routes = [r for r in server.routes if not isinstance(r, Mount)]
    app = Starlette(routes=routes, middleware=[Middleware(server.LandingGate)])
    yield TestClient(app, base_url="https://topstocks.example")
    server._app_document.cache_clear()
    landing_static.document.cache_clear()
    server._gzipped.cache_clear()


def test_the_landing_logs_where_the_reader_came_from(client, events):
    client.get(
        "/?utm_source=Rankia&utm_campaign=fifo",
        headers={"User-Agent": CHROME, "Referer": "https://www.rankia.com/foros/x"},
    )
    name, fields = next(e for e in events if e[0] == "landing.view")
    assert fields["src"] == "rankia"
    assert fields["campaign"] == "fifo"
    assert fields["ref"] == "rankia.com"
    assert "bot" not in fields
    assert fields["lang"] == "en"


def test_a_campaign_link_still_gets_the_pitch(client, events):
    """`?utm_source=` is how every promoted link is written; it is not a click."""
    r = client.get("/?utm_source=rankia", headers={"User-Agent": CHROME})
    assert 'rel="canonical"' in r.text and "APP-SHELL" not in r.text
    assert [name for name, _ in events] == ["landing.view"]


def test_a_real_request_alongside_a_campaign_tag_still_opens_the_app(client, events):
    r = client.get("/?ticker=AAPL&utm_source=rankia", headers={"User-Agent": CHROME})
    assert "APP-SHELL" in r.text


def test_the_token_does_not_follow_the_reader_home_from_google():
    assert attribution.clean_target("/?src=rankia&lang=es") == "/?lang=es"
    assert attribution.clean_target("/?utm_source=rankia&gclid=x") == "/"
    assert attribution.clean_target("/portfolio?tab=fees") == "/portfolio?tab=fees"


def test_a_crawler_is_counted_as_one(client, events):
    client.get("/", headers={"User-Agent": "Googlebot/2.1"})
    _, fields = next(e for e in events if e[0] == "landing.view")
    assert fields["bot"] is True


def test_the_spanish_landing_logs_its_own_variant(client, events):
    client.get("/es/?src=hn", headers={"User-Agent": CHROME})
    _, fields = next(e for e in events if e[0] == "landing.view")
    assert (fields["lang"], fields["path"], fields["src"]) == ("es", "/es/", "hn")


def test_the_guest_cta_is_the_step_between_pitch_and_app(client, events):
    client.get("/?guest=1&src=rankia", headers={"User-Agent": CHROME})
    name, fields = next(e for e in events if e[0] == "landing.cta")
    assert fields["kind"] == "guest"
    assert fields["src"] == "rankia"


def test_a_bookmark_is_not_a_campaign(client, events):
    client.get("/portfolio", headers={"User-Agent": CHROME})
    _, fields = next(e for e in events if e[0] == "landing.cta")
    assert fields["kind"] == "direct"
    assert "src" not in fields


def test_the_crossing_is_counted_once_per_browser(client, events):
    client.get("/?guest=1", headers={"User-Agent": CHROME})
    client.get("/portfolio", headers={"User-Agent": CHROME})
    assert [e for e in events if e[0] == "landing.cta"] != []
    assert len([e for e in events if e[0] == "landing.cta"]) == 1


def test_the_source_rides_the_sign_in_round_trip(client, events):
    """Google is the referrer on the way back, so `next` is the only carrier."""
    r = client.get("/?signin=1&utm_source=rankia&lang=es",
                   headers={"User-Agent": CHROME}, follow_redirects=False)
    assert r.status_code == 302
    nxt = unquote(parse_qs(urlsplit(r.headers["location"]).query)["next"][0])
    assert parse_qs(urlsplit(nxt).query) == {"lang": ["es"], "src": ["rankia"]}
    _, fields = next(e for e in events if e[0] == "landing.cta")
    assert (fields["kind"], fields["src"]) == ("signin", "rankia")


def test_a_sign_in_without_a_campaign_is_unchanged(client, events):
    r = client.get("/?signin=1", headers={"User-Agent": CHROME},
                   follow_redirects=False)
    assert unquote(parse_qs(urlsplit(r.headers["location"]).query)["next"][0]) == "/"


def test_the_callback_reads_the_token_back_out_of_next():
    assert oidc._source("/?src=rankia&lang=es") == "rankia"
    assert oidc._source("/") == ""


# ------------------------------------------------------------- the account


def _account(tmp_path):
    """A brand-new account's paths, with the directory a stamp needs."""
    p = paths_for("jane@example.com", users_dir=tmp_path)
    p.prefs.parent.mkdir(parents=True, exist_ok=True)
    return p


def test_a_signup_keeps_the_source_the_logs_will_forget(tmp_path):
    """Cloud Logging keeps 30 days; the account keeps its origin for good."""
    p = _account(tmp_path)
    assert accounts.stamp_login(p, seeded=True, source="rankia") == "signup"
    assert load_prefs(p.prefs)["first_source"] == "rankia"


def test_a_later_visit_through_another_link_does_not_rewrite_the_origin(tmp_path):
    p = _account(tmp_path)
    accounts.stamp_login(p, seeded=True, source="rankia")
    accounts.stamp_login(p, seeded=False, source="hn")
    assert load_prefs(p.prefs)["first_source"] == "rankia"


def test_an_account_that_arrived_without_a_campaign_stores_none(tmp_path):
    p = _account(tmp_path)
    accounts.stamp_login(p, seeded=True)
    assert load_prefs(p.prefs).get("first_source") in (None, "")


# -------------------------------------------------------------- the readout


def _entry(day: str, event: str, **fields) -> dict:
    return {
        "timestamp": f"{day}T10:00:00Z",
        "jsonPayload": {"event": event, **fields},
    }


def test_the_funnel_counts_the_four_steps_per_day():
    summary = logs_query.funnel([
        _entry("2026-09-20", "landing.view", src="rankia"),
        _entry("2026-09-20", "landing.view"),
        _entry("2026-09-20", "landing.cta", kind="signin", src="rankia"),
        _entry("2026-09-20", "auth.signup", src="rankia"),
        _entry("2026-09-21", "import.committed"),
        _entry("2026-09-21", "chat.request"),  # not a funnel step
    ])
    assert summary["days"] == [
        {"day": "2026-09-20", "views": 2, "ctas": 1, "signups": 1, "imports": 0},
        {"day": "2026-09-21", "views": 0, "ctas": 0, "signups": 0, "imports": 1},
    ]
    assert summary["totals"] == {"views": 2, "ctas": 1, "signups": 1, "imports": 1}


def test_the_funnel_does_not_count_crawlers_in_the_denominator():
    summary = logs_query.funnel([
        _entry("2026-09-20", "landing.view", src="rankia"),
        _entry("2026-09-20", "landing.view", src="rankia", bot=True),
    ])
    assert summary["totals"]["views"] == 1


def test_the_funnel_ranks_the_sources_by_what_they_produced():
    summary = logs_query.funnel([
        _entry("2026-09-20", "landing.view", src="hn"),
        _entry("2026-09-20", "landing.view", src="hn"),
        _entry("2026-09-20", "landing.view", src="rankia"),
        _entry("2026-09-20", "landing.cta", src="rankia"),
        _entry("2026-09-20", "auth.signup", src="rankia"),
        _entry("2026-09-20", "landing.view"),  # no campaign on the link
    ])
    assert [r["src"] for r in summary["sources"]] == ["rankia", "hn", "-"]
    assert summary["sources"][0]["signups"] == 1


def test_the_readout_states_the_rates_it_can_and_hides_the_ones_it_cannot():
    text = logs_query.render_funnel(logs_query.funnel([
        _entry("2026-09-20", "landing.view", src="rankia"),
        _entry("2026-09-20", "landing.cta", src="rankia"),
    ]))
    assert "100.0%" in text  # one view, one entry
    assert "0 signups" in text
    assert logs_query.render_funnel(logs_query.funnel([])).startswith("(no funnel")


def test_the_events_the_funnel_reads_are_the_ones_the_app_emits(caplog):
    """The names are a contract between two modules that never import each other."""
    assert set(logs_query.FUNNEL_STEPS) >= {"landing.view", "landing.cta", "auth.signup"}
    with caplog.at_level(logging.INFO, logger="stocks"):
        obs.setup(force=True)
        obs.event("landing.view", src="rankia")
    assert any(r.message == "landing.view" for r in caplog.records)
    assert json.loads(obs.CloudLoggingFormatter().format(caplog.records[-1]))[
        "event"
    ] == "landing.view"
