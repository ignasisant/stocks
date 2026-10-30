"""Multi-user notification fan-out (stocks.notify.fanout)."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from stocks.notify import fanout, narrative
from stocks.notify import state as state_mod


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Silence the optional LLM lines by default.

    Not politeness: a developer with [free_llm] secrets configured otherwise
    runs the whole fan-out against real backends, which costs minutes per run
    and spends the shared daily pot. Tests that want a line opt back in.
    """
    monkeypatch.setattr(narrative, "alerts_line", lambda *a, **kw: None)
    monkeypatch.setattr(narrative, "highlight", lambda *a, **kw: None)
    monkeypatch.setattr(narrative, "weekly_line", lambda *a, **kw: None)


def _device(root, n: int = 1) -> None:
    """`n` subscribed devices in push.json, in the shape `webpush` keeps."""
    rows = {
        f"row{i}": {"endpoint": f"https://push.example/{i}", "p256dh": "k",
                    "auth": "a", "lang": "es", "created": float(i)}
        for i in range(n)
    }
    (root / "push.json").write_text(json.dumps({"subscriptions": rows}))


def _user(tmp_path, slug, prefs, watchlist=None, devices=0):
    root = tmp_path / "users" / slug
    root.mkdir(parents=True)
    (root / "prefs.json").write_text(json.dumps(prefs))
    if watchlist:
        (root / "watchlist.yaml").write_text(watchlist)
    if devices:
        _device(root, devices)
    return root


@pytest.fixture
def pushed(monkeypatch):
    """Record every push instead of sending it; each reaches one device."""
    sent: list[tuple[str, dict, str]] = []

    def send_all(path, message, *, topic=""):
        sent.append((path.parent.name, message, topic))
        return 1

    monkeypatch.setattr(fanout.webpush, "send_all", send_all)
    return sent


def _undelivered(monkeypatch):
    """Every device gone or refusing: the push reached nobody."""
    monkeypatch.setattr(fanout.webpush, "send_all", lambda *a, **kw: 0)


@pytest.fixture
def local(monkeypatch, tmp_path):
    """Local-filesystem discovery (storage disabled), rooted at tmp_path."""
    from stocks import storage

    monkeypatch.setattr(storage, "_cached", {"config": None})
    monkeypatch.setattr(fanout, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(fanout, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fanout, "WATCHLIST_FILE", tmp_path / "watchlist.yaml")
    return tmp_path


SUBSCRIBED = {"language": "es"}


def test_iter_filters_on_devices_and_toggle(local):
    _user(local, "jane_ab12cd34", SUBSCRIBED, devices=1)
    _user(local, "bob_ef56ab78", {"notify_digest": False}, devices=2)
    _user(local, "carol_11223344", {"currency": "EUR"})  # no device
    _user(local, "_guest", SUBSCRIBED, devices=1)  # guests never notified

    digest_users = fanout.iter_notify_users("digest")
    assert [u.label for u in digest_users] == ["jane_ab12cd34"]
    assert digest_users[0].push_path == local / "users" / "jane_ab12cd34" / "push.json"
    assert digest_users[0].lang == "es"

    alert_users = fanout.iter_notify_users("alerts")  # bob only disabled digest
    assert [u.label for u in alert_users] == ["bob_ef56ab78", "jane_ab12cd34"]


def test_iter_all_users_includes_accounts_without_a_device(local):
    _user(local, "jane_ab12cd34", SUBSCRIBED, devices=1)
    _user(local, "carol_11223344", {"currency": "EUR"})  # no device

    users = fanout.iter_all_users()
    assert [u.label for u in users] == ["carol_11223344", "jane_ab12cd34"]
    # chat.json path sits next to prefs.json for slug accounts
    assert users[0].chat_path == local / "users" / "carol_11223344" / "chat.json"


def test_iter_accounts_reports_registration_dates(local):
    _user(local, "jane_ab12cd34", {**SUBSCRIBED,
                                   "first_seen": "2026-01-05T10:00:00+00:00",
                                   "last_seen": "2026-02-01"}, devices=2)
    _user(local, "carol_11223344", {"first_seen": "2026-03-09T08:00:00+00:00",
                                    "last_seen": "2026-03-09",
                                    "first_seen_estimated": True})
    _user(local, "_guest", {"first_seen": "2020-01-01T00:00:00+00:00"})
    (local / "prefs.json").write_text(json.dumps({"first_seen": "2025-12-01T00:00:00Z"}))

    rows = {r["label"]: r for r in fanout.iter_accounts()}
    assert set(rows) == {"jane_ab12cd34", "carol_11223344", "owner"}  # no _guest
    assert rows["jane_ab12cd34"]["last_seen"] == "2026-02-01"
    assert rows["jane_ab12cd34"]["push"] == 2
    assert rows["carol_11223344"]["push"] == 0
    assert rows["carol_11223344"]["estimated"] is True
    assert rows["jane_ab12cd34"]["estimated"] is False


def test_iter_accounts_tolerates_prefs_without_dates(local):
    _user(local, "jane_ab12cd34", {"currency": "EUR"})
    (row,) = fanout.iter_accounts()
    assert row == {"label": "jane_ab12cd34", "first_seen": "", "last_seen": "",
                   "estimated": False, "push": 0}


def test_owner_chat_path_is_data_chat_json(local):
    (local / "prefs.json").write_text(json.dumps({}))
    (owner,) = fanout.iter_all_users()
    assert owner.chat_path == local / "chat.json"


def test_owner_root_prefs_is_an_entry(local):
    (local / "prefs.json").write_text(json.dumps({}))
    _device(local)
    users = fanout.iter_notify_users("digest")
    assert [u.label for u in users] == ["owner"]
    assert users[0].push_path == local / "push.json"
    assert users[0].watchlist == fanout.WATCHLIST_FILE
    assert users[0].db == local / "portfolio.db"
    assert users[0].state_path == local / "alerts_state.json"


def test_bucket_discovery_restores_files(monkeypatch, tmp_path):
    """Slugs come from bucket keys; user files are pulled before reading."""
    from stocks import storage

    from .test_storage import FakeClient

    client = FakeClient()
    jane = "data/users/jane_ab12cd34"
    client.objects[f"{jane}/prefs.json"] = json.dumps(SUBSCRIBED).encode()
    client.objects["data/users/jane_ab12cd34/watchlist.yaml"] = b"watchlist: []\n"
    client.objects["data/users/jane_ab12cd34/push.json"] = json.dumps(
        {"subscriptions": {"r": {"endpoint": "https://push.example/1"}}}
    ).encode()
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        storage,
        "_cached",
        {
            "config": {
                "bucket": "b", "access_key_id": "k", "secret_access_key": "s",
                "endpoint_url": "", "region": "auto",
            },
            "client": client,
        },
    )
    monkeypatch.setattr(fanout, "USERS_DIR", tmp_path / "data" / "users")
    monkeypatch.setattr(fanout, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(fanout, "WATCHLIST_FILE", tmp_path / "watchlist.yaml")

    users = fanout.iter_notify_users("digest")
    assert [u.label for u in users] == ["jane_ab12cd34"]
    assert (tmp_path / "data" / "users" / "jane_ab12cd34" / "prefs.json").exists()
    assert users[0].watchlist.read_text() == "watchlist: []\n"


WATCHLIST_WITH_ALERT = """\
watchlist:
  - ticker: NVDA
    alerts:
      - type: above
        price: 100
"""


def _frame(closes):
    return pd.DataFrame({"Close": closes})


def _firing(monkeypatch, closes=(90, 150)):
    monkeypatch.setattr(
        fanout, "_fetch_frames",
        lambda tickers, max_workers=4: {"NVDA": _frame(list(closes))},
    )


def test_run_alerts_fanout_sends_once_then_dedupes(local, monkeypatch, pushed):
    _user(local, "jane_ab12cd34", SUBSCRIBED, watchlist=WATCHLIST_WITH_ALERT, devices=1)
    _firing(monkeypatch)

    status = fanout.run_alerts_fanout()
    assert status == {"jane_ab12cd34": "sent 1"}
    (slug, message, topic), = pushed
    assert (slug, topic) == ("jane_ab12cd34", "alerts")
    assert "NVDA" in message["body"] and "above 100" in message["body"]
    assert message["title"] == "⚠️ Alertas de precio · NVDA"  # user's language (es)

    # Second run an hour later: condition still true -> suppressed by state.
    status2 = fanout.run_alerts_fanout()
    assert status2 == {"jane_ab12cd34": "no hits"}
    assert len(pushed) == 1


def test_an_undelivered_alert_is_tried_again_next_run(local, monkeypatch, pushed):
    """No device took it, so nothing was said: the edge stays unfired and the
    next hour sends it rather than treating it as already delivered."""
    root = _user(local, "jane_ab12cd34", SUBSCRIBED,
                 watchlist=WATCHLIST_WITH_ALERT, devices=1)
    _firing(monkeypatch)
    sent = fanout.webpush.send_all
    _undelivered(monkeypatch)
    assert fanout.run_alerts_fanout() == {"jane_ab12cd34": "not delivered"}
    assert not (root / "alerts_state.json").exists()

    monkeypatch.setattr(fanout.webpush, "send_all", sent)
    assert fanout.run_alerts_fanout() == {"jane_ab12cd34": "sent 1"}
    assert len(pushed) == 1


def test_run_alerts_fanout_isolates_user_errors(local, monkeypatch):
    _user(local, "jane_ab12cd34", SUBSCRIBED, watchlist=WATCHLIST_WITH_ALERT, devices=1)
    _user(local, "bob_ef56ab78", {}, watchlist=WATCHLIST_WITH_ALERT, devices=1)
    _firing(monkeypatch)
    calls = []

    def flaky(path, message, *, topic=""):
        if path.parent.name == "bob_ef56ab78":
            raise RuntimeError("boom")
        calls.append(path.parent.name)
        return 1

    monkeypatch.setattr(fanout.webpush, "send_all", flaky)
    status = fanout.run_alerts_fanout()
    assert status["jane_ab12cd34"] == "sent 1"
    assert status["bob_ef56ab78"].startswith("error:")
    assert calls == ["jane_ab12cd34"]


def test_alert_note_is_added_when_the_llm_answers(local, monkeypatch, pushed):
    _user(local, "jane_ab12cd34", SUBSCRIBED, watchlist=WATCHLIST_WITH_ALERT, devices=1)
    _firing(monkeypatch)
    seen = []
    monkeypatch.setattr(
        narrative, "alerts_line",
        lambda hits, prefs, lang, **_: seen.append((len(hits), lang)) or "Semis running.",
    )

    assert fanout.run_alerts_fanout() == {"jane_ab12cd34": "sent 1"}
    assert seen == [(1, "es")]  # one call, the account's language
    body = pushed[0][1]["body"].splitlines()
    assert "NVDA" in body[0] and body[1] == "Semis running."


def test_alert_note_absent_never_blocks_the_alert(local, monkeypatch, pushed):
    _user(local, "jane_ab12cd34", SUBSCRIBED, watchlist=WATCHLIST_WITH_ALERT, devices=1)
    _firing(monkeypatch)
    monkeypatch.setattr(narrative, "alerts_line", lambda *a, **kw: None)

    assert fanout.run_alerts_fanout() == {"jane_ab12cd34": "sent 1"}
    assert pushed[0][1]["body"].count("\n") == 0


def test_no_hits_never_calls_the_llm(local, monkeypatch, pushed):
    _user(local, "jane_ab12cd34", SUBSCRIBED, watchlist=WATCHLIST_WITH_ALERT, devices=1)
    _firing(monkeypatch, closes=(90, 50))  # below 100
    calls = []
    monkeypatch.setattr(
        narrative, "alerts_line", lambda *a, **kw: calls.append(1) or "x"
    )
    assert fanout.run_alerts_fanout() == {"jane_ab12cd34": "no hits"}
    assert calls == [] and pushed == []


# ------------------------------------------------- digest highlight memory


def _digest_env(local, monkeypatch, highlight):
    """One linked account, a fixed digest, and `highlight` as the LLM."""
    from datetime import date

    from stocks.notify import digest

    _user(local, "jane_ab12cd34", SUBSCRIBED, devices=1)
    monkeypatch.setattr(
        digest, "compute_digest_data",
        lambda watchlist, db, base, import_record=None: digest.DigestData(
            date=date(2026, 9, 3), total=1000.0, day=(10.0, 0.01)
        ),
    )
    monkeypatch.setattr(narrative, "highlight", highlight)
    return digest


def test_digest_highlight_is_remembered_for_the_next_run(local, monkeypatch, pushed):
    seen = []

    def highlight(data, prefs, lang, recent=None, **_):
        seen.append(list(recent or []))
        return f"Line {len(seen)}."

    digest = _digest_env(local, monkeypatch, highlight)

    assert digest.run_digest_fanout() == {"jane_ab12cd34": "sent 1"}
    assert digest.run_digest_fanout() == {"jane_ab12cd34": "sent 1"}
    assert digest.run_digest_fanout() == {"jane_ab12cd34": "sent 1"}
    assert [topic for _, _, topic in pushed] == ["digest"] * 3
    # Each run sees everything delivered before it, oldest first.
    assert seen == [[], ["Line 1."], ["Line 1.", "Line 2."]]


def test_undelivered_highlight_is_not_remembered(local, monkeypatch):
    """A line the user never saw must not be treated as already said."""
    seen = []

    def highlight(data, prefs, lang, recent=None, **_):
        seen.append(list(recent or []))
        return "Only line."

    digest = _digest_env(local, monkeypatch, highlight)
    _undelivered(monkeypatch)
    assert digest.run_digest_fanout() == {"jane_ab12cd34": "not delivered"}
    assert state_mod.recent_highlights(
        state_mod.load_state(local / "users" / "jane_ab12cd34" / "alerts_state.json")
    ) == []


def test_digest_without_a_highlight_writes_no_state(local, monkeypatch, pushed):
    digest = _digest_env(local, monkeypatch, lambda *a, **kw: None)
    assert digest.run_digest_fanout() == {"jane_ab12cd34": "sent 1"}
    assert not (local / "users" / "jane_ab12cd34" / "alerts_state.json").exists()


# ------------------------------------------------- alert lines with context

WATCHLIST_HELD = """\
watchlist:
  - ticker: NVDA
    shares: 42
    cost: 100
    alerts:
      - type: above
        price: 120
"""


def _hit(ticker="NVDA", message="above 120 (last 150.00)"):
    from stocks.notify.alerts import AlertHit

    return AlertHit(ticker, "above", message)


def load_watchlist_from(text: str, tmp_path):
    from stocks.config import load_watchlist

    path = tmp_path / "watchlist.yaml"
    path.write_text(text)
    return load_watchlist(path)


def test_alert_line_carries_size_and_pl_for_a_held_name(tmp_path):
    """The same rule firing on a name you hold 42 shares of is a different
    message from one firing on a name you are only watching."""
    holdings = load_watchlist_from(WATCHLIST_HELD, tmp_path)
    frames = {"NVDA": _frame([100.0, 138.2])}
    line = fanout._alert_line(_hit(), holdings, frames, "en")
    assert line.startswith("NVDA: above 120 (last 150.00)")
    assert "42 shares" in line and "+38.2%" in line


def test_alert_line_stays_bare_for_a_watched_name(tmp_path):
    holdings = load_watchlist_from(WATCHLIST_WITH_ALERT, tmp_path)  # no shares
    line = fanout._alert_line(_hit(), holdings, {}, "en")
    assert line == "NVDA: above 120 (last 150.00)"


def test_alert_line_drops_the_pl_when_there_is_no_cost_or_price(tmp_path):
    holdings = load_watchlist_from(
        WATCHLIST_HELD.replace("    cost: 100\n", ""), tmp_path
    )
    line = fanout._alert_line(_hit(), holdings, {"NVDA": _frame([138.2])}, "en")
    assert "42 shares" in line and "%" not in line.split("·")[-1]


def test_alert_line_is_plain_text(tmp_path):
    """A notification draws its body as it is: no markup to escape."""
    holdings = load_watchlist_from(WATCHLIST_HELD, tmp_path)
    line = fanout._alert_line(_hit(message="crossed <above> & held"), holdings, {}, "en")
    assert line.startswith("NVDA: crossed <above> & held")


def test_alert_line_is_translated(tmp_path):
    holdings = load_watchlist_from(WATCHLIST_HELD, tmp_path)
    line = fanout._alert_line(_hit(), holdings, {}, "es")
    assert "42 acciones" in line


def test_one_name_opens_its_page_several_open_the_book():
    one = fanout.alerts_message(["NVDA: above 120"], ["NVDA", "NVDA"], None, "es")
    assert one["url"] == fanout.links.ticker_path("NVDA")
    assert one["title"] == "⚠️ Alertas de precio · NVDA"
    assert one["tag"] == "alerts"

    two = fanout.alerts_message(["NVDA: above", "KO: below"], ["NVDA", "KO"],
                                "Both moved on rates.", "en")
    assert two["url"] == "/portfolio"
    assert two["title"] == "⚠️ Price alerts"
    # The narrated line goes second, before the rules it sums up.
    assert two["body"].splitlines() == [
        "NVDA: above", "Both moved on rates.", "KO: below",
    ]


def test_the_held_context_reaches_the_push(local, monkeypatch, pushed):
    _user(local, "jane_ab12cd34", SUBSCRIBED, watchlist=WATCHLIST_HELD, devices=1)
    monkeypatch.setattr(
        fanout, "_fetch_frames",
        lambda tickers, max_workers=4: {"NVDA": _frame([100.0, 150.0])},
    )
    assert fanout.run_alerts_fanout() == {"jane_ab12cd34": "sent 1"}
    message = pushed[0][1]
    assert "42 acciones" in message["body"] and "+50.0%" in message["body"]
    assert message["url"] == "/ticker?ticker=NVDA"


# ----------------------------------------------------------- weekly review


def _weekly_data(monkeypatch, **over):
    """Point the fan-out at a fixed review, whatever the account's files say."""
    from datetime import date

    from stocks.notify import weekly

    base = dict(date=date(2026, 9, 13), total=1000.0, week=(10.0, 0.01),
                top_weight=0.68)
    base.update(over)
    monkeypatch.setattr(
        weekly, "compute_weekly_data",
        lambda watchlist, db, base_ccy="EUR", **kw: weekly.WeeklyData(**base),
    )
    return weekly


def _weekly_env(local, monkeypatch, **over):
    _user(local, "jane_ab12cd34", SUBSCRIBED, devices=1)
    return _weekly_data(monkeypatch, **over)


def test_weekly_subscribers_honour_their_own_toggle(local):
    _user(local, "jane_ab12cd34", SUBSCRIBED, devices=1)
    _user(local, "bob_ef56ab78", {"notify_weekly": False}, devices=1)
    assert [u.label for u in fanout.iter_notify_users("weekly")] == ["jane_ab12cd34"]


def test_weekly_drift_is_measured_against_the_last_delivered_review(
    local, monkeypatch, pushed
):
    """The baseline moves only when a review actually went out, so a failed
    send does not make next Sunday's drift measure from a week nobody saw."""
    weekly = _weekly_env(local, monkeypatch)
    assert weekly.run_weekly_fanout() == {"jane_ab12cd34": "sent 1"}
    assert [topic for _, _, topic in pushed] == ["weekly"]

    state = json.loads(
        (local / "users" / "jane_ab12cd34" / "alerts_state.json").read_text()
    )
    assert state["weekly"]["top_weight"] == pytest.approx(0.68)

    # Next week, more concentrated: the review says by how much.
    rendered = []
    real = weekly.weekly_message
    monkeypatch.setattr(
        weekly, "weekly_message",
        lambda data, lang: rendered.append(data.drift) or real(data, lang),
    )
    _weekly_data(monkeypatch, top_weight=0.71)
    assert weekly.run_weekly_fanout() == {"jane_ab12cd34": "sent 1"}
    assert rendered == [pytest.approx(0.03)]


def test_weekly_skips_an_account_with_no_book(local, monkeypatch):
    weekly = _weekly_env(local, monkeypatch, total=None, top_weight=None)
    monkeypatch.setattr(
        fanout.webpush, "send_all",
        lambda *a, **kw: pytest.fail("nothing to review, nothing to send"),
    )
    assert weekly.run_weekly_fanout() == {"jane_ab12cd34": "skipped: no book"}


def test_an_undelivered_weekly_keeps_no_baseline(local, monkeypatch):
    weekly = _weekly_env(local, monkeypatch)
    _undelivered(monkeypatch)
    assert weekly.run_weekly_fanout() == {"jane_ab12cd34": "not delivered"}
    # No concentration baseline from a review nobody received.
    assert not (local / "users" / "jane_ab12cd34" / "alerts_state.json").exists()


def test_every_delivery_the_cron_sends_has_a_default_to_read():
    """A toggle the senders default to on must be on in DEFAULT_PREFS too.

    `iter_notify_users` reads `notify_<kind>` with a default of True, and so
    does the Profile toggle — but `load_prefs()` only carries the keys
    DEFAULT_PREFS names. `notify_weekly` was missing from it for a while, which
    made one switch answer two ways: the review was delivered, while anything
    asking the loaded prefs dict plainly got None back. Any new delivery added
    to the cron and not here lands in the same state.
    """
    from stocks.accounts import DEFAULT_PREFS

    kinds = {"digest", "weekly", "alerts"}
    missing = {k for k in kinds if f"notify_{k}" not in DEFAULT_PREFS}
    assert not missing, f"delivered but not defaulted: {sorted(missing)}"
