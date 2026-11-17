"""Web Push: "your answer is ready" on a device nobody is looking at.

The protocol is two RFCs written by hand on `cryptography` (`notify/webpush.py`),
so what is pinned first is that a real implementation reads what we send:
`http_ece` (the library pywebpush is built on) decrypts the body with the
browser's keys, and the VAPID JWT verifies against the key the browser was
given. Then the bookkeeping — one row per device, dead ones dropped, nothing
kept that would point this server somewhere other than a push service — and
the one rule that makes it bearable: no push while the app is on screen.
"""

# The API fixtures are borrowed from test_api_chat, and a test naming one as
# a parameter reads to ruff as redefining the import.
# ruff: noqa: F811

from __future__ import annotations

import base64
import json
import time

import http_ece
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from stocks import accounts
from stocks.api import runs
from stocks.notify import webpush

from .test_api_chat import (  # noqa: F401 — fixtures
    EMAIL,
    FakeProvider,
    account,
    client,
    run,
    served,
    signed_in,
    token,
)

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Browser:
    """The keys a browser makes at subscribe time."""

    def __init__(self, endpoint: str = ENDPOINT):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"
        self.endpoint = endpoint

    @property
    def p256dh(self) -> str:
        return b64(self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))

    def subscription(self, lang: str = "en") -> dict:
        return {"endpoint": self.endpoint,
                "keys": {"p256dh": self.p256dh, "auth": b64(self.auth)}, "lang": lang}

    def read(self, body: bytes) -> dict:
        plain = http_ece.decrypt(body, private_key=self.key, auth_secret=self.auth,
                                 version="aes128gcm")
        return json.loads(plain)


@pytest.fixture
def vapid(monkeypatch):
    key = webpush.generate_key()
    monkeypatch.setenv("WEBPUSH_PRIVATE_KEY", key)
    return key


class Outbox(list):
    """Every push sent, as (endpoint, body, headers). The push service answers
    201, or what `status` says for an endpoint."""

    def __init__(self):
        super().__init__()
        self.status: dict[str, int] = {}

    def post(self, endpoint, body, headers) -> int:
        self.append((endpoint, body, headers))
        return self.status.get(endpoint, 201)


@pytest.fixture
def outbox(monkeypatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(webpush, "_post", box.post)
    return box


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    webpush._seen.clear()
    runs._reset()
    yield
    webpush._seen.clear()
    runs._reset()


# ------------------------------------------------------------------ protocol


def test_a_real_implementation_decrypts_what_we_send():
    browser = Browser()
    body = webpush.encrypt(b'{"title":"hi"}', browser.p256dh, b64(browser.auth))
    assert browser.read(body) == {"title": "hi"}


def test_each_message_is_encrypted_afresh():
    browser = Browser()
    one = webpush.encrypt(b"same", browser.p256dh, b64(browser.auth))
    two = webpush.encrypt(b"same", browser.p256dh, b64(browser.auth))
    assert one != two
    assert http_ece.decrypt(two, private_key=browser.key, auth_secret=browser.auth,
                            version="aes128gcm") == b"same"


def test_the_vapid_token_verifies_against_the_key_the_browser_was_given(vapid):
    key = webpush._private_key()
    header = webpush.vapid_header(ENDPOINT, "https://topstocks.example", key,
                                  now=1_000_000)
    token, k = header.removeprefix("vapid t=").split(", k=")
    assert k == webpush.public_key()

    head, claims, sig = token.split(".")
    assert json.loads(unb64(head)) == {"typ": "JWT", "alg": "ES256"}
    assert json.loads(unb64(claims)) == {
        "aud": "https://fcm.googleapis.com",
        "exp": 1_000_000 + 12 * 3600,
        "sub": "https://topstocks.example",
    }
    raw = unb64(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"),
                               int.from_bytes(raw[32:], "big"))
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(k))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_a_pem_key_works_as_well_as_a_raw_one(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    # Secret Manager hands it back with its newlines flattened.
    monkeypatch.setenv("WEBPUSH_PRIVATE_KEY", pem.replace("\n", "\\n"))
    assert webpush.configured()
    assert unb64(webpush.public_key()) == key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def test_without_a_key_nothing_is_offered(monkeypatch):
    monkeypatch.delenv("WEBPUSH_PRIVATE_KEY", raising=False)
    monkeypatch.setattr(webpush, "secret", lambda *a, **k: "")
    assert not webpush.configured()
    assert webpush.public_key() is None


# ------------------------------------------------------------- the store


def keep(path, browser: Browser, **kw) -> bool:
    return webpush.subscribe(path, endpoint=browser.endpoint, p256dh=browser.p256dh,
                             auth=b64(browser.auth), origin="https://topstocks.example",
                             lang=kw.get("lang", "en"))


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/x",           # not https
    "https://localhost/x",
    "https://127.0.0.1/x",
    "https://[::1]/x",
    "https://metadata.google.internal/x",
    "https://printer.local/x",
])
def test_only_a_public_push_service_is_kept(tmp_path, endpoint):
    """The endpoint is where this server will POST: a client must not be able
    to aim it at itself or its neighbours."""
    assert not keep(tmp_path / "push.json", Browser(endpoint))
    assert not (tmp_path / "push.json").exists()


def test_keys_of_the_wrong_size_are_refused(tmp_path):
    assert not webpush.subscribe(
        tmp_path / "p.json", endpoint=ENDPOINT, p256dh=b64(b"x" * 10),
        auth=b64(b"y" * 16), origin="", lang="en",
    )


def test_one_row_per_device_and_resubscribing_keeps_one(tmp_path):
    path = tmp_path / "push.json"
    browser = Browser()
    assert keep(path, browser) and keep(path, browser)
    assert keep(path, Browser("https://web.push.apple.com/abc"))
    assert len(webpush._read(path)) == 2
    assert webpush.subscribed(path, ENDPOINT)
    assert webpush.unsubscribe(path, ENDPOINT)
    assert not webpush.subscribed(path, ENDPOINT)


def test_the_file_is_one_of_the_accounts_files():
    paths = accounts.paths_for(EMAIL, None)
    assert paths.push.name in accounts.USER_FILES


# ------------------------------------------------ one device, one account

MESSAGE = {"title": "Tu día", "body": "NVDA +3 %", "url": "/?thread=c_1",
           "tag": "briefing"}


def two_accounts(tmp_path):
    return (tmp_path / "ann_example_com" / "push.json",
            tmp_path / "bob_example_com" / "push.json")


def test_a_device_two_accounts_subscribed_notifies_only_the_last(tmp_path, vapid, outbox):
    """A browser has one subscription whoever is signed in. Ann switched push
    on, then Bob signed in on the same phone and switched it on too: Ann's
    briefing kept arriving there, and tapping it opened Bob's book, where
    that thread does not exist."""
    ann, bob = two_accounts(tmp_path)
    browser = Browser()
    assert keep(ann, browser) and keep(bob, browser)

    assert webpush.send_all(ann, MESSAGE, topic="briefing") == 0
    assert webpush.answer_ready(ann, "ann", thread="c_1", question="q") == 0
    assert outbox == [] and webpush.history(ann) == []
    assert webpush.send_all(bob, MESSAGE, topic="briefing") == 1
    assert [endpoint for endpoint, _, _ in outbox] == [ENDPOINT]

    assert (webpush.devices(ann), webpush.devices(bob)) == (0, 1)
    assert not webpush.subscribed(ann, ENDPOINT) and webpush.subscribed(bob, ENDPOINT)
    assert webpush.row(ann, ENDPOINT) is None and webpush.lang_of(ann) is None


def test_another_device_of_the_same_account_is_untouched(tmp_path, vapid, outbox):
    ann, bob = two_accounts(tmp_path)
    phone, laptop = Browser(), Browser("https://web.push.apple.com/abc")
    keep(ann, phone)
    keep(ann, laptop)
    keep(bob, phone)
    assert webpush.send_all(ann, MESSAGE) == 1
    assert [endpoint for endpoint, _, _ in outbox] == [laptop.endpoint]


def test_opening_the_app_claims_the_device_for_who_is_signed_in(tmp_path, vapid, outbox):
    """Subscriptions made before devices had an owner sit in both files with
    nobody named: the account the app opens on takes the device, and the
    other one's row sleeps — kept, so it wakes when that account is back."""
    ann, bob = two_accounts(tmp_path)
    browser = Browser()
    keep(ann, browser)
    keep(bob, browser)
    webpush.OWNERS.unlink()
    assert webpush.send_all(ann, MESSAGE) == 1 and webpush.send_all(bob, MESSAGE) == 1

    assert webpush.claim(ann, ENDPOINT)
    assert (webpush.devices(ann), webpush.devices(bob)) == (1, 0)
    assert webpush._row_id(ENDPOINT) in webpush._read(bob)

    assert webpush.claim(bob, ENDPOINT)
    assert (webpush.devices(ann), webpush.devices(bob)) == (0, 1)


def test_claiming_subscribes_nothing(tmp_path, vapid, outbox):
    """Bob never switched push on: signing in on Ann's phone stops Ann's
    notifications there, and sends him none."""
    ann, bob = two_accounts(tmp_path)
    keep(ann, Browser())
    assert not webpush.claim(bob, ENDPOINT)
    assert not bob.exists()
    assert webpush.send_all(ann, MESSAGE) == 0 and webpush.send_all(bob, MESSAGE) == 0
    assert not webpush.claim(bob, "https://localhost/x")


def test_signing_out_silences_the_device_until_somebody_signs_in(tmp_path, vapid, outbox):
    ann, bob = two_accounts(tmp_path)
    keep(ann, Browser())
    webpush.release(ann, ENDPOINT)
    assert webpush.send_all(ann, MESSAGE) == 0 and outbox == []
    assert webpush._row_id(ENDPOINT) in webpush._read(ann)

    assert webpush.claim(ann, ENDPOINT)
    assert webpush.send_all(ann, MESSAGE) == 1


def test_signing_out_does_not_release_somebody_elses_device(tmp_path, vapid, outbox):
    """A sign-out request that lands after the next account's sign-in."""
    ann, bob = two_accounts(tmp_path)
    browser = Browser()
    keep(ann, browser)
    keep(bob, browser)
    webpush.release(ann, ENDPOINT)
    assert webpush.send_all(bob, MESSAGE) == 1


def test_a_device_changing_hands_is_logged_without_naming_anybody(tmp_path, caplog):
    ann, bob = two_accounts(tmp_path)
    browser = Browser()
    with caplog.at_level("INFO"):
        keep(ann, browser)
        webpush.claim(ann, ENDPOINT)
        assert "push.claimed" not in caplog.text
        keep(bob, browser)
    record, = [r for r in caplog.records if r.getMessage() == "push.claimed"]
    assert "example" not in json.dumps(record.__dict__, default=str)


def test_the_owners_come_back_from_the_bucket_once(tmp_path, monkeypatch):
    """A cold instance and the crons start with no local file."""
    seen = []
    monkeypatch.setattr("stocks.storage.restore_once",
                        lambda group, files: seen.append((group, files)))
    webpush.devices(tmp_path / "ann_example_com" / "push.json")
    keep(tmp_path / "ann_example_com" / "push.json", Browser())
    webpush.devices(tmp_path / "ann_example_com" / "push.json")
    assert seen and set(seen) == {(webpush.OWNERS, (webpush.OWNERS,))}


def test_an_index_that_could_not_be_fetched_is_never_written_over(
    tmp_path, vapid, outbox, monkeypatch
):
    """A cold instance whose bucket read fails knows no owners. Saving the one
    it was just told would replace everybody's: the claim fails instead, and
    sending goes on as it did before there was an index."""
    ann, _ = two_accounts(tmp_path)
    keep(ann, Browser())
    webpush.OWNERS.unlink()

    def down(group, files):
        raise OSError("bucket unreachable")

    monkeypatch.setattr("stocks.storage.restore_once", down)
    with pytest.raises(OSError):
        webpush.claim(ann, ENDPOINT)
    assert not webpush.OWNERS.exists()
    assert webpush.send_all(ann, MESSAGE) == 1


def test_the_index_names_no_account(tmp_path):
    """One file for everybody, kept after an account is deleted: the directory
    name is the e-mail address, so it is never written there."""
    ann, bob = two_accounts(tmp_path)
    keep(ann, Browser())
    keep(bob, Browser())
    webpush.release(bob, ENDPOINT)
    kept = webpush.OWNERS.read_text()
    assert "ann_example_com" not in kept and "bob_example_com" not in kept
    assert "example" not in kept


# ----------------------------------------------------------------- sending


def test_a_push_reaches_the_device_readable_and_signed(tmp_path, vapid, outbox):
    path = tmp_path / "push.json"
    browser = Browser()
    keep(path, browser, lang="es")
    took = webpush.answer_ready(path, "owner", thread="t-1", question="¿Cómo va  NVDA?")
    assert took == 1
    (endpoint, body, headers), = outbox
    assert endpoint == ENDPOINT
    assert headers["Content-Encoding"] == "aes128gcm"
    assert headers["Authorization"].startswith("vapid t=")
    assert int(headers["TTL"]) == webpush.TTL_S
    assert headers["Topic"] == "t-1"
    assert browser.read(body) == {
        "title": "Tu respuesta está lista",
        "body": "¿Cómo va NVDA?",
        "url": "/?thread=t-1",
        "tag": "answer-t-1",
    }


def test_a_gone_subscription_is_dropped(tmp_path, vapid, outbox):
    path = tmp_path / "push.json"
    keep(path, Browser())
    outbox.status[ENDPOINT] = 410
    assert webpush.answer_ready(path, "owner", thread="t", question="q") == 0
    assert not webpush.subscribed(path, ENDPOINT)


def test_a_refusal_that_is_not_gone_keeps_the_row(tmp_path, vapid, outbox):
    path = tmp_path / "push.json"
    keep(path, Browser())
    outbox.status[ENDPOINT] = 429
    webpush.answer_ready(path, "owner", thread="t", question="q")
    assert webpush.subscribed(path, ENDPOINT)


def test_one_broken_device_does_not_stop_the_others(tmp_path, vapid, outbox, monkeypatch):
    path = tmp_path / "push.json"
    keep(path, Browser())
    keep(path, Browser("https://web.push.apple.com/abc"))
    real = webpush._post

    def flaky(endpoint, body, headers):
        if endpoint == ENDPOINT:
            raise OSError("connection reset")
        return real(endpoint, body, headers)

    monkeypatch.setattr(webpush, "_post", flaky)
    assert webpush.answer_ready(path, "owner", thread="t", question="q") == 1


def test_what_was_sent_is_logged_newest_first(tmp_path, vapid, outbox):
    path = tmp_path / "push.json"
    keep(path, Browser())
    keep(path, Browser("https://web.push.apple.com/abc"))
    outbox.status["https://web.push.apple.com/abc"] = 429
    message = {"title": "NVDA", "body": "Below 90", "url": "/ticker?ticker=NVDA"}
    assert webpush.send_all(path, message, topic="alerts") == 1
    webpush.answer_ready(path, "owner", thread="t", question="q")
    first, second = webpush.history(path)[:2]
    assert first["topic"] == "answer" and second["topic"] == "alerts"
    assert second["title"] == "NVDA" and second["took"] == 1 and second["devices"] == 2


def test_the_log_keeps_what_another_process_logged(tmp_path, vapid, outbox, monkeypatch):
    path = tmp_path / "push.json"
    keep(path, Browser())
    theirs = {"sent": [{"id": "cron1", "at": 1, "topic": "digest", "title": "d"}]}
    monkeypatch.setattr("stocks.storage.read",
                        lambda p: json.dumps(theirs).encode())
    webpush.send_all(path, {"title": "mine"}, topic="alerts")
    assert [r["id"] for r in webpush.history(path)][1:] == ["cron1"]
    for n in range(webpush.LOG_ROWS + 3):
        webpush.send_all(path, {"title": f"m{n}"}, topic="alerts")
    rows = webpush.history(path)
    assert len(rows) == webpush.LOG_ROWS
    assert rows[0]["title"] == f"m{webpush.LOG_ROWS + 2}"
    assert "cron1" not in {r["id"] for r in rows}  # the oldest went past the cap


def test_no_device_logs_nothing(tmp_path, vapid, outbox):
    path = tmp_path / "push.json"
    assert webpush.send_all(path, {"title": "x"}, topic="alerts") == 0
    assert webpush.history(path) == []


def test_the_log_is_one_of_the_accounts_files():
    paths = accounts.paths_for(EMAIL, None)
    assert paths.push_log.name in accounts.USER_FILES
    assert paths.push_log.name == webpush.LOG_FILE


# ---------------------------------------------------------------- presence


def test_no_push_while_the_app_is_on_screen(tmp_path, vapid, outbox):
    path = tmp_path / "push.json"
    keep(path, Browser())
    webpush.seen("owner", "tab-1", True)
    assert webpush.answer_ready(path, "owner", thread="t", question="q") == 0
    assert outbox == []


def test_a_hidden_app_or_a_stale_beat_is_nobody_looking():
    now = time.time()
    webpush.seen("owner", "tab-1", True, now=now - webpush.PRESENT_S - 1)
    assert not webpush.present("owner", now=now)
    webpush.seen("owner", "tab-1", True, now=now)
    assert webpush.present("owner", now=now)
    webpush.seen("owner", "tab-1", False, now=now)
    assert not webpush.present("owner", now=now)
    assert not webpush.present("someone-else", now=now)


# ------------------------------------------------------------------ routes


def test_the_routes_subscribe_report_and_unsubscribe(client, account, signed_in, vapid):
    browser = Browser()
    state = signed_in.get("/v1/push", params={"endpoint": ENDPOINT}).json()
    assert state == {
        "configured": True, "key": webpush.public_key(),
        "subscribed": False, "devices": 0, "recent": [],
    }

    kept = signed_in.post("/v1/push/subscription", json=browser.subscription("es"))
    assert kept.status_code == 200 and kept.json()["subscribed"]
    assert kept.json()["devices"] == 1
    assert webpush._read(account.push)[webpush._row_id(ENDPOINT)]["lang"] == "es"
    assert signed_in.get("/v1/push", params={"endpoint": ENDPOINT}).json()["subscribed"]

    assert signed_in.post("/v1/push/unsubscribe",
                          json={"endpoint": ENDPOINT}).status_code == 204
    assert not webpush.subscribed(account.push, ENDPOINT)


def test_the_routes_claim_and_release_this_device(client, account, signed_in, vapid,
                                                  tmp_path, outbox):
    """What the app sends when it opens and when it signs out."""
    other = tmp_path / "users" / "bob_example_com" / "push.json"
    browser = Browser()
    signed_in.post("/v1/push/subscription", json=browser.subscription())
    keep(other, browser)
    assert signed_in.get("/v1/push", params={"endpoint": ENDPOINT}).json() == {
        "configured": True, "key": webpush.public_key(),
        "subscribed": False, "devices": 0, "recent": [],
    }

    assert signed_in.post("/v1/push/claim",
                          json={"endpoint": ENDPOINT}).status_code == 204
    assert signed_in.get("/v1/push", params={"endpoint": ENDPOINT}).json()["subscribed"]
    assert webpush.send_all(other, MESSAGE) == 0

    assert signed_in.post("/v1/push/release",
                          json={"endpoint": ENDPOINT}).status_code == 204
    assert webpush.devices(account.push) == 0
    assert webpush.send_all(other, MESSAGE) == 0


def test_a_token_cannot_claim_a_device(client, account, vapid):
    for route in ("claim", "release"):
        response = client.post(
            f"/v1/push/{route}", params={"account": EMAIL},
            headers={"Authorization": "Bearer s3cret-token"}, json={"endpoint": ENDPOINT},
        )
        assert response.status_code == 403


def test_a_route_refuses_a_subscription_it_cannot_use(client, account, signed_in, vapid):
    bad = Browser("https://169.254.169.254/latest")
    assert signed_in.post("/v1/push/subscription",
                          json=bad.subscription()).status_code == 422


def test_without_a_key_the_route_says_so(client, account, signed_in, monkeypatch):
    monkeypatch.setattr(webpush, "secret", lambda *a, **k: "")
    assert signed_in.get("/v1/push").json()["configured"] is False
    assert signed_in.post("/v1/push/subscription",
                          json=Browser().subscription()).status_code == 409


def test_a_token_cannot_subscribe_an_account(client, account, vapid):
    response = client.post(
        "/v1/push/subscription", params={"account": EMAIL},
        headers={"Authorization": "Bearer s3cret-token"}, json=Browser().subscription(),
    )
    assert response.status_code == 403


def test_presence_is_kept_per_account(client, account, signed_in):
    assert signed_in.post("/v1/push/presence",
                          json={"client": "tab-1", "visible": True}).status_code == 204
    assert webpush.present(str(account.chat))


# -------------------------------------------------------------- the run hook


def wait_for(predicate, seconds: float = 5) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("never happened")


def test_a_finished_answer_pushes_to_the_account(
    client, account, signed_in, served, vapid, outbox
):
    served()
    browser = Browser()
    signed_in.post("/v1/push/subscription", json=browser.subscription())
    cid = signed_in.post("/v1/chat/conversations", json={"title": "T"}).json()["id"]
    signed_in.post("/v1/chat/runs", json=run("hola", thread=cid))
    wait_for(lambda: outbox)
    message = browser.read(outbox[0][1])
    assert message["body"] == "hola"
    assert message["url"] == f"/?thread={cid}"


def test_a_stopped_or_refused_run_pushes_nothing(vapid, outbox, tmp_path):
    called: list = []

    def frames(_run):
        yield 'data: {"type":"RUN_ERROR","message":"no"}\n\n'

    run_ = runs.start(owner="o", rid="r", thread="t", question="q", events=frames,
                      stopped="", failed=lambda f: "RUN_ERROR" in f,
                      done=called.append)
    wait_for(lambda: not run_.live)
    time.sleep(0.05)
    assert called == []


def test_a_done_hook_that_fails_does_not_break_the_run():
    def frames(_run):
        yield 'data: {"type":"RUN_FINISHED"}\n\n'

    def boom(_run):
        raise RuntimeError("push service down")

    run_ = runs.start(owner="o", rid="r", thread="t", question="q", events=frames,
                      stopped="", failed=lambda f: False, done=boom)
    wait_for(lambda: not run_.live)
    assert not run_.failed


def test_the_push_state_lists_what_was_last_sent(monkeypatch, tmp_path):
    """`GET /push` carries the account's recent sends, newest first."""
    from types import SimpleNamespace

    from stocks.api.routes import push as push_routes

    rows = [
        {"id": "b", "at": 20.0, "topic": "alert", "title": "T", "body": "B",
         "url": "/today", "devices": 2, "took": 1},
        {"id": "a", "at": 10, "topic": "test"},
    ]
    monkeypatch.setattr(webpush, "history", lambda path: rows)
    monkeypatch.setattr(webpush, "devices", lambda path: 2)
    monkeypatch.setattr(webpush, "public_key", lambda: "k")
    out = push_routes.state(SimpleNamespace(push=tmp_path / "push.json"))
    assert [s.topic for s in out.recent] == ["alert", "test"]
    assert out.recent[0].took == 1
    assert out.recent[1].title == ""
