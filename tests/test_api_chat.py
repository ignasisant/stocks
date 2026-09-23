"""The assistant over HTTP.

What a chat turn *is* — provider chain, free quota, skill routing, what lands
in chat.json — belongs to `stocks.chat.engine` and is tested with it. What is
tested here is the HTTP shape put on top:

* a turn streams, and the pieces arrive in an order a client can render;
* the stream always ends in exactly one `done` frame, including when the turn
  failed, because a reader with a half-answer and no ending has no way to tell
  a slow model from a dead one;
* a thread is named by id and an unknown id 404s, so a client that deleted the
  wrong thing and one that deleted nothing do not look identical;
* every one of these is a write, and a bearer token never gets one — a chat
  turn spends the operator's shared keys, which is what a leaked token would
  be worth stealing for.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.chat import engine

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

WATCHLIST = """\
watchlist:
  - ticker: AAPL
    name: Apple
"""

# Skills off and web off: this file is about the HTTP surface, and a turn that
# routes skills or searches the internet is testing neither of those over a
# network nobody wants in a unit test.
PREFS = {"currency": "EUR", "chat_skills_mode": "off", "chat_web": False}


class FakeProvider:
    """A backend that answers from a list, or raises on cue.

    Shaped like `web.llm.Provider` only as far as the engine actually uses it:
    the engine asks for `stream`, `complete`, `id` and `default_model`, so a
    real Provider here would add a dataclass to keep in sync for nothing.
    """

    needs_key = False
    domain = None

    def __init__(self, chunks=("Hola", " mundo"), fail_after: int | None = None,
                 pid: str = "fake"):
        self.id = pid
        self.label = "Fake"
        self.models = ("fake-1",)
        self.default_model = "fake-1"
        self._chunks = list(chunks)
        self._fail_after = fail_after

    def stream(self, api_key, model, system, messages):
        for index, chunk in enumerate(self._chunks):
            if self._fail_after is not None and index == self._fail_after:
                raise RuntimeError("provider died")
            yield chunk
        if self._fail_after == len(self._chunks):
            raise RuntimeError("provider died")

    def complete(self, api_key, model, system, messages):
        return "".join(self._chunks)

    def available(self):
        return True


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text(WATCHLIST)
    paths.prefs.write_text(json.dumps(PREFS))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    """A browser session for EMAIL — what a write needs, since a token cannot."""
    return sign_in(client, EMAIL)


@pytest.fixture
def served(monkeypatch):
    """Put one fake backend at the head of the chain and cut the internet."""

    def install(provider=None):
        provider = provider or FakeProvider()
        monkeypatch.setattr(
            engine, "attempts", lambda prefs: [(provider, "k", "fake-1")]
        )
        monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])
        return provider

    return install


def frames(body: str) -> list[tuple[str, dict]]:
    """The SSE body as (event, payload) pairs, comments dropped."""
    out = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


# --------------------------------------------------------------------- state


def test_state_lists_the_skills_the_app_actually_ships(client, account, signed_in):
    body = signed_in.get("/v1/chat/state").json()
    assert body["skills"], "the skill library is a shipped directory, not a guess"
    assert all(s["id"] and s["name"] for s in body["skills"])
    assert body["skills_mode"] == "off"


def test_an_account_the_free_chain_does_not_serve_has_no_allowance_to_show(
    client, account, signed_in, monkeypatch
):
    """Null, not 0. Zero left is a wall that lifts tomorrow; null is a reader
    who was never given an allowance, and "0 of 30" tells them they spent
    messages they never sent."""
    monkeypatch.setattr(engine, "free_eligible", lambda prefs: False)
    body = signed_in.get("/v1/chat/state").json()
    assert body["free_left"] is None
    assert body["free_cap"] is None
    assert body["cap_reason"] == "chat.free_ineligible"


def test_an_eligible_account_gets_a_number_and_no_wall(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(engine, "free_eligible", lambda prefs: True)
    monkeypatch.setattr(engine, "free_left", lambda prefs: 12)
    body = signed_in.get("/v1/chat/state").json()
    assert body["free_left"] == 12
    assert body["cap_reason"] is None


# ------------------------------------------------------------------- threads


def test_a_fresh_account_has_no_threads_yet(client, account, signed_in):
    """Not one blank thread: the store invents a new id for that draft on every
    read, so a client handed one could not rename or delete what it just saw."""
    assert signed_in.get("/v1/chat/conversations").json()["conversations"] == []


def test_the_first_turn_is_what_makes_a_thread_exist(
    client, account, signed_in, served
):
    served()
    signed_in.post("/v1/chat/messages", json={"message": "hola"})
    threads = signed_in.get("/v1/chat/conversations").json()["conversations"]
    assert len(threads) == 1 and threads[0]["messages"] == 2


def test_starting_a_thread_twice_over_does_not_stack_blank_ones(
    client, account, signed_in
):
    first = signed_in.post("/v1/chat/conversations", json={}).json()["id"]
    second = signed_in.post("/v1/chat/conversations", json={}).json()["id"]
    assert first == second
    assert len(signed_in.get("/v1/chat/conversations").json()["conversations"]) == 1


def test_renaming_pins_the_title(client, account, signed_in):
    cid = signed_in.post("/v1/chat/conversations", json={}).json()["id"]
    body = signed_in.patch(f"/v1/chat/conversations/{cid}", json={"title": "Fiscal"})
    assert body.status_code == 200
    assert body.json()["title"] == "Fiscal"
    # Pinned: auto-titling from the opening exchange must never overwrite a
    # name the user chose.
    assert body.json()["title_auto"] is False


def test_an_unknown_thread_is_a_404_everywhere_it_is_named(
    client, account, signed_in
):
    assert signed_in.get("/v1/chat/conversations/c_nope").status_code == 404
    assert signed_in.patch(
        "/v1/chat/conversations/c_nope", json={"title": "x"}
    ).status_code == 404
    assert signed_in.delete("/v1/chat/conversations/c_nope").status_code == 404


def test_deleting_the_last_thread_leaves_one_to_type_into(
    client, account, signed_in
):
    cid = signed_in.post("/v1/chat/conversations", json={}).json()["id"]
    assert signed_in.delete(f"/v1/chat/conversations/{cid}").status_code == 204
    after = signed_in.get("/v1/chat/conversations").json()["conversations"]
    assert len(after) == 1 and after[0]["id"] != cid


# ------------------------------------------------------------------ settings


def test_a_skill_that_does_not_exist_is_refused(client, account, signed_in):
    response = signed_in.patch("/v1/chat/settings", json={"skills": ["astrology"]})
    assert response.status_code == 422


def test_a_mode_that_does_not_exist_is_refused(client, account, signed_in):
    assert signed_in.patch(
        "/v1/chat/settings", json={"skills_mode": "vibes"}
    ).status_code == 422


def test_settings_answer_with_the_state_they_produced(client, account, signed_in):
    body = signed_in.patch(
        "/v1/chat/settings", json={"skills_mode": "manual", "skills": ["spain-tax"]}
    )
    assert body.status_code == 200
    assert body.json()["skills_mode"] == "manual"
    assert json.loads(account.prefs.read_text())["chat_skills_mode"] == "manual"


def test_the_provider_and_its_model_are_set_together_and_read_back(
    client, account, signed_in
):
    """The settings screen's whole job. A model belongs to one backend, so it
    is stored under that backend's key and validated against it."""
    offered = signed_in.get("/v1/chat/state").json()["providers"]
    picked = next(p for p in offered if len(p["models"]) > 1)
    second = picked["models"][1]

    body = signed_in.patch(
        "/v1/chat/settings", json={"provider": picked["id"], "model": second}
    ).json()
    assert body["preferred"] == picked["id"]
    assert next(p for p in body["providers"] if p["id"] == picked["id"])[
        "model"
    ] == second
    stored = json.loads(account.prefs.read_text())
    assert stored["llm_provider"] == picked["id"]
    assert stored[f"{picked['id']}_model"] == second


def test_a_model_that_backend_does_not_serve_is_refused(client, account, signed_in):
    offered = signed_in.get("/v1/chat/state").json()["providers"][0]
    response = signed_in.patch(
        "/v1/chat/settings", json={"provider": offered["id"], "model": "gpt-9"}
    )
    assert response.status_code == 422
    assert "llm_provider" not in json.loads(account.prefs.read_text())


def test_a_provider_this_deployment_does_not_offer_is_refused(
    client, account, signed_in
):
    response = signed_in.patch("/v1/chat/settings", json={"provider": "skynet"})
    assert response.status_code == 422


def test_the_preferred_provider_is_not_always_the_one_answering(
    client, account, signed_in
):
    """A BYOK provider picked and not yet given a key is preferred and does not
    answer. A screen shown only `answering` would keep insisting the reader
    never made the choice they just made."""
    byok = next(
        p
        for p in signed_in.get("/v1/chat/state").json()["providers"]
        if p["needs_key"] and not p["has_key"]
    )
    body = signed_in.patch(
        "/v1/chat/settings", json={"provider": byok["id"]}
    ).json()
    assert body["preferred"] == byok["id"]
    assert body["answering"] != byok["id"]


# ---------------------------------------------------------------- one turn


def test_a_turn_streams_its_pieces_and_ends_in_one_done(
    client, account, signed_in, served
):
    served()
    body = signed_in.post("/v1/chat/messages", json={"message": "hola"}).text
    events = frames(body)
    kinds = [e for e, _ in events]
    # The phases come first — they are the wait before any provider answers —
    # and they are the panel's own `chat.work_*` keys, in the panel's order.
    phases = [p["phase"] for e, p in events if e == "phase"]
    assert phases == ["gathering", "searching", "writing"]
    assert kinds[len(phases)] == "meta"
    assert [p["chunk"] for e, p in events if e == "text"] == ["Hola", " mundo"]
    assert [e for e, _ in events].count("done") == 1
    assert events[-1][1]["text"] == "Hola mundo"
    assert events[-1][1]["error"] is None


def test_the_answer_is_on_disk_when_the_stream_ends(
    client, account, signed_in, served
):
    served()
    signed_in.post("/v1/chat/messages", json={"message": "hola"})
    thread = signed_in.get("/v1/chat/conversations").json()["conversations"][0]
    turns = signed_in.get(f"/v1/chat/conversations/{thread['id']}").json()["messages"]
    assert [m["role"] for m in turns] == ["user", "assistant"]
    assert turns[1]["content"] == "Hola mundo"


def test_a_backend_that_dies_before_its_first_word_falls_through(
    client, account, signed_in, monkeypatch
):
    dead = FakeProvider(chunks=("x",), fail_after=0, pid="dead")
    alive = FakeProvider(chunks=("Hola",), pid="alive")
    monkeypatch.setattr(
        engine, "attempts",
        lambda prefs: [(dead, "k", "fake-1"), (alive, "k", "fake-1")],
    )
    monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])
    events = frames(signed_in.post("/v1/chat/messages", json={"message": "hola"}).text)
    assert events[-1][1]["text"] == "Hola"
    assert events[-1][1]["provider"] == "alive"


def test_a_backend_that_dies_mid_sentence_keeps_what_it_said(
    client, account, signed_in, monkeypatch
):
    """No failover once words are on screen: replacing them with another
    model's answer mid-paragraph reads as corruption, and the half-answer is
    still worth keeping."""
    half = FakeProvider(chunks=("Los dividendos", " se declaran"), fail_after=2)
    other = FakeProvider(chunks=("otra cosa",), pid="other")
    monkeypatch.setattr(
        engine, "attempts",
        lambda prefs: [(half, "k", "fake-1"), (other, "k", "fake-1")],
    )
    monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])
    events = frames(signed_in.post("/v1/chat/messages", json={"message": "hola"}).text)
    assert events[-1][1]["text"] == "Los dividendos se declaran"
    assert events[-1][1]["provider"] != "other"


def test_an_exhausted_chain_still_ends_the_stream(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(engine, "attempts", lambda prefs: [])
    events = frames(signed_in.post("/v1/chat/messages", json={"message": "hola"}).text)
    assert events == [("done", {"text": "", "skills": [], "sources": [],
                               "provider": None, "error": "chat.free_exhausted",
                               "steps": []})]


def test_a_turn_can_be_aimed_at_a_named_thread(
    client, account, signed_in, served
):
    served()
    signed_in.post("/v1/chat/messages", json={"message": "primera"})
    second = signed_in.post("/v1/chat/conversations", json={"title": "Otra"}).json()
    signed_in.post(
        "/v1/chat/messages", json={"message": "segunda", "conversation": second["id"]}
    )
    turns = signed_in.get(
        f"/v1/chat/conversations/{second['id']}"
    ).json()["messages"]
    assert [m["content"] for m in turns if m["role"] == "user"] == ["segunda"]


def test_a_turn_aimed_at_a_thread_that_is_gone_is_a_404(
    client, account, signed_in, served
):
    served()
    response = signed_in.post(
        "/v1/chat/messages", json={"message": "hola", "conversation": "c_nope"}
    )
    assert response.status_code == 404


def test_a_token_cannot_spend_the_account_on_the_operators_keys(
    client, account, served
):
    served()
    response = client.post(
        "/v1/chat/messages",
        params={"account": EMAIL},
        headers=AUTH,
        json={"message": "hola"},
    )
    assert response.status_code == 403
    # Nothing was written on the way to the refusal.
    assert not account.chat.exists()


# ------------------------------------------------------------ provider keys


@pytest.fixture
def encrypted(monkeypatch):
    """A deployment that can actually store a key."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CHAT_ENC_KEY", key)
    return key


def test_storing_a_key_is_what_lifts_the_cap(
    client, account, signed_in, encrypted
):
    body = signed_in.put("/v1/chat/keys/anthropic", json={"key": "sk-ant-xxxxxxxx"})
    assert body.status_code == 200
    anthropic = next(
        p for p in body.json()["providers"] if p["id"] == "anthropic"
    )
    assert anthropic["has_key"] is True
    assert anthropic["key_days_left"] == 90


def test_the_key_never_comes_back_out(client, account, signed_in, encrypted):
    """The state payload says a key is stored and how long it has left. It does
    not say what the key is, and nothing here ever should."""
    signed_in.put("/v1/chat/keys/anthropic", json={"key": "sk-ant-secretvalue"})
    body = signed_in.get("/v1/chat/state").text
    assert "sk-ant-secretvalue" not in body
    # Nor in the file, which is the point of encrypting it.
    assert "sk-ant-secretvalue" not in account.prefs.read_text()


def test_a_deployment_that_cannot_encrypt_refuses_rather_than_storing(
    client, account, signed_in, monkeypatch
):
    """Plaintext beside somebody's portfolio is not a degraded mode."""
    monkeypatch.delenv("CHAT_ENC_KEY", raising=False)
    # Only the engine's own lookup: blanking `secrets_env.secret` wholesale
    # takes the free-tier counter's configuration down with it, and the test
    # would then be about a different failure.
    monkeypatch.setattr(engine, "secret", lambda *a, **k: "")
    response = signed_in.put("/v1/chat/keys/anthropic", json={"key": "sk-ant-xxxxxxxx"})
    assert response.status_code == 503
    assert "anthropic_key_enc" not in account.prefs.read_text()


def test_the_keyless_provider_takes_no_key(client, account, signed_in, encrypted):
    assert (
        signed_in.put("/v1/chat/keys/free", json={"key": "whatever12"}).status_code
        == 409
    )


def test_a_provider_that_does_not_exist_is_a_404(
    client, account, signed_in, encrypted
):
    assert (
        signed_in.put("/v1/chat/keys/astrology", json={"key": "xxxxxxxx"}).status_code
        == 404
    )


def test_forgetting_removes_the_ciphertext(client, account, signed_in, encrypted):
    signed_in.put("/v1/chat/keys/anthropic", json={"key": "sk-ant-xxxxxxxx"})
    body = signed_in.delete("/v1/chat/keys/anthropic")
    assert body.status_code == 200
    assert "anthropic_key_enc" not in account.prefs.read_text()
    anthropic = next(
        p for p in body.json()["providers"] if p["id"] == "anthropic"
    )
    assert anthropic["has_key"] is False
    assert anthropic["key_days_left"] is None


def test_forgetting_a_key_that_was_never_there_is_a_404(
    client, account, signed_in, encrypted
):
    assert signed_in.delete("/v1/chat/keys/anthropic").status_code == 404


def test_a_token_cannot_plant_a_key_on_an_account(client, account, encrypted):
    response = client.put(
        "/v1/chat/keys/anthropic",
        params={"account": EMAIL},
        headers=AUTH,
        json={"key": "sk-ant-xxxxxxxx"},
    )
    assert response.status_code == 403
    assert "anthropic_key_enc" not in account.prefs.read_text()


# ---------------------------------------------------------------- voice notes


def _wav(seconds: float = 1.0) -> bytes:
    """A silent WAV of a given length — enough for `stt.clip_seconds`."""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16_000)
        out.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return buf.getvalue()


def voice(audio: bytes | None = None, **extra) -> dict:
    import base64

    return {
        "audio": base64.b64encode(audio if audio is not None else _wav()).decode(),
        "content_type": "audio/wav",
        **extra,
    }


def test_a_recording_comes_back_as_the_words_in_it(
    client, account, signed_in, monkeypatch
):
    seen: dict = {}

    def fake(audio, *, language=None, filename="voice.wav", content_type="audio/wav"):
        seen.update(bytes=len(audio), language=language, filename=filename,
                    content_type=content_type)
        return "cuánto llevo en Apple"

    monkeypatch.setattr("stocks.web.stt.available", lambda: True)
    monkeypatch.setattr("stocks.web.stt.transcribe", fake)
    body = signed_in.post("/v1/chat/voice", json=voice(lang="es"))
    assert body.status_code == 200
    assert body.json()["text"] == "cuánto llevo en Apple"
    # The locale reaches Whisper as a hint: two seconds of Spanish is routinely
    # detected as Portuguese without one.
    assert seen["language"] == "es"


def test_the_recorder_s_own_format_reaches_the_backend(
    client, account, signed_in, monkeypatch
):
    """A WebM introduced as a WAV is rejected by the backend, so the type the
    browser reported travels with the bytes — and names the file too."""
    seen: dict = {}
    monkeypatch.setattr("stocks.web.stt.available", lambda: True)
    monkeypatch.setattr(
        "stocks.web.stt.transcribe",
        lambda audio, **kw: seen.update(kw) or "hola",
    )
    signed_in.post(
        "/v1/chat/voice", json=voice(b"not really webm", content_type="audio/webm")
    )
    assert seen["content_type"] == "audio/webm"
    assert seen["filename"] == "voice.webm"


def test_a_format_no_backend_reads_is_refused(client, account, signed_in, monkeypatch):
    monkeypatch.setattr("stocks.web.stt.available", lambda: True)
    response = signed_in.post("/v1/chat/voice", json=voice(content_type="audio/aiff"))
    assert response.status_code == 415


def test_what_the_clip_is_guilty_of_comes_back_as_the_key_that_says_so(
    client, account, signed_in, monkeypatch
):
    """Both front ends say the same thing about the same clip, in the reader's
    own language — so the API answers with the key, not with a sentence."""
    from stocks.web import stt

    monkeypatch.setattr("stocks.web.stt.available", lambda: True)

    def silent(audio, **kw):
        raise stt.TranscriptionFailed("chat.voice_silent")

    monkeypatch.setattr("stocks.web.stt.transcribe", silent)
    response = signed_in.post("/v1/chat/voice", json=voice())
    assert response.status_code == 422
    assert response.json()["detail"] == "chat.voice_silent"


def test_a_deployment_with_no_transcription_key_says_so_rather_than_failing(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr("stocks.web.stt.available", lambda: False)
    response = signed_in.post("/v1/chat/voice", json=voice())
    assert response.status_code == 503
    assert response.json()["detail"] == "chat.voice_unavailable"
    assert signed_in.get("/v1/chat/state").json()["voice"] is False


def test_transcription_spends_the_operator_s_key_so_a_token_may_not(client, account):
    response = client.post("/v1/chat/voice", params=WHO, headers=AUTH, json=voice())
    assert response.status_code == 403


# ---------------------------------------------------------------- regenerate


def test_regenerating_leaves_one_pair_on_the_thread_not_two(
    client, account, signed_in, served
):
    """The engine appends the question it is given, so the old pair goes first
    — otherwise the same question ends up filed twice with two answers."""
    served()
    signed_in.post("/v1/chat/messages", json={"message": "hola"})
    again = signed_in.post("/v1/chat/messages", json={"regenerate": True})
    assert again.status_code == 200
    assert [f[0] for f in frames(again.text)][-1] == "done"

    cid = signed_in.get("/v1/chat/conversations").json()["conversations"][0]["id"]
    turns = signed_in.get(f"/v1/chat/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in turns] == ["user", "assistant"]
    assert turns[0]["content"] == "hola"


def test_regenerate_with_a_message_is_refused_rather_than_guessed_at(
    client, account, signed_in
):
    response = signed_in.post(
        "/v1/chat/messages", json={"message": "hola", "regenerate": True}
    )
    assert response.status_code == 422


def test_a_thread_with_nothing_to_regenerate_says_so(client, account, signed_in):
    assert signed_in.post(
        "/v1/chat/messages", json={"regenerate": True}
    ).status_code == 409


def test_an_empty_message_is_still_refused(client, account, signed_in):
    assert signed_in.post("/v1/chat/messages", json={"message": "   "}).status_code == 422


# ---------------------------------------------------------------- bursts


def test_a_burst_of_turns_hits_the_same_wall_the_composer_does(
    client, account, signed_in, served
):
    """Keyed exactly as `chat_core` keys it, so a reader with two windows open
    (one Streamlit, one React) gets one budget and not two."""
    from stocks.web import ratelimit

    served()
    key = f"chat::{account.root}"
    for _ in range(ratelimit.CHAT_MAX_TURNS):
        ratelimit.allow(key)
    response = signed_in.post("/v1/chat/messages", json={"message": "hola"})
    assert response.status_code == 429
    assert response.json()["detail"] == "chat.rate_limited"
    assert int(response.headers["Retry-After"]) >= 1


def test_an_attachment_spends_the_same_budget_as_a_typed_turn(
    client, account, signed_in
):
    from stocks.web import ratelimit

    key = f"chat::{account.root}"
    for _ in range(ratelimit.CHAT_MAX_TURNS):
        ratelimit.allow(key)
    response = signed_in.post(
        "/v1/chat/attachments",
        json={"filename": "x.csv", "content": "eA=="},
    )
    assert response.status_code == 429


def test_a_voice_note_does_not_eat_the_turn_it_becomes(
    client, account, signed_in, monkeypatch
):
    """A spoken question is a note *and* a message. Counting both against one
    budget would halve the allowance of everyone who talks to it."""
    from stocks.web import ratelimit

    for _ in range(ratelimit.CHAT_MAX_TURNS):
        ratelimit.allow(f"chat::{account.root}")
    monkeypatch.setattr("stocks.web.stt.available", lambda: True)
    monkeypatch.setattr("stocks.web.stt.transcribe", lambda audio, **kw: "hola")
    assert signed_in.post("/v1/chat/voice", json=voice()).status_code == 200


def test_asking_to_import_with_a_preview_up_points_at_its_button(
    client, account, signed_in, served
):
    """With a card waiting, the step that does work is the button under it —
    not attaching the file a second time."""
    served()
    body = signed_in.post(
        "/v1/chat/messages",
        json={"message": "importa estas operaciones", "staged_import": "rev.csv"},
    ).text
    done = [data for event, data in frames(body) if event == "done"][0]
    assert "rev.csv" in done["text"]


def test_asking_to_import_with_nothing_staged_asks_for_the_file(
    client, account, signed_in, served
):
    served()
    body = signed_in.post(
        "/v1/chat/messages", json={"message": "importa estas operaciones"}
    ).text
    done = [data for event, data in frames(body) if event == "done"][0]
    assert done["text"] and "rev.csv" not in done["text"]



def test_the_tool_trace_rides_on_the_answer_and_on_the_stored_turn(
    client, account, signed_in, served, monkeypatch
):
    """The panel's "N steps" counter, for every binding: what ran, on what, and
    what came back. On the `done` frame for the reader watching, and on the
    stored turn for the one who reloads."""
    from stocks.chat import market

    class Quote:
        ticker = "AAPL"

    served()
    monkeypatch.setattr(market, "lookup_for", lambda *a, **k: [Quote()])
    monkeypatch.setattr(market, "augment", lambda text, live: text)
    body = signed_in.post("/v1/chat/messages", json={"message": "hola AAPL"}).text
    done = frames(body)[-1][1]
    assert done["steps"] == [
        {"tool": "get_quotes", "arg": "AAPL", "out": "1 live quotes"}
    ]
    cid = signed_in.get("/v1/chat/conversations").json()["conversations"][0]["id"]
    stored = signed_in.get(f"/v1/chat/conversations/{cid}").json()["messages"][-1]
    assert stored["steps"] == done["steps"]
