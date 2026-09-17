"""The feedback store (stocks.web.feedback) — submission files and read-back.

The sidebar widget itself is Streamlit chrome; what must not break silently is
the storage contract: a submission survives as a JSON file (mirrored to the
bucket) that `stocks feedback` can read back, including bucket-only copies a
fresh checkout has never seen.
"""

from __future__ import annotations

import base64
import io
import json
from contextlib import contextmanager

import pytest

from stocks import storage
from stocks.web import feedback, screenshot


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path / "feedback")
    monkeypatch.setattr(storage, "_cached", {"config": None})  # bucket off
    monkeypatch.setattr(feedback, "active_language", lambda: "en")
    # The submit cap counts per process and every test here sends as "guest",
    # so without this the sixth test in the file would be the rate-limited
    # one, whichever it happened to be. The cap has its own test below.
    monkeypatch.setattr(feedback.ratelimit, "allow", lambda *a, **kw: True)
    return tmp_path / "feedback"


def test_submit_writes_one_json_file_per_submission(sandbox):
    p = feedback.submit("The chart is upside down", "bug", page="Cartera")
    data = json.loads(p.read_text())
    assert data["kind"] == "bug"
    assert data["text"] == "The chart is upside down"
    assert data["page"] == "Cartera"
    assert data["user"] == "guest"  # no session -> anonymous
    assert p.parent == sandbox


def test_submit_clamps_kind_and_length(sandbox):
    p = feedback.submit("x" * (feedback.MAX_CHARS + 500), "exploit")
    data = json.loads(p.read_text())
    assert data["kind"] == "other"
    assert len(data["text"]) == feedback.MAX_CHARS


def test_stored_merges_local_and_bucket_and_sorts(sandbox, monkeypatch):
    feedback.submit("local one", "idea")
    bucket = {
        "data/feedback/2020-01-01T00-00-00Z-aaaaaa.json": json.dumps(
            {"ts": "2020-01-01T00-00-00Z", "kind": "bug", "text": "old, bucket-only"}
        ).encode(),
        "data/feedback/not-json.txt": b"ignored",
    }
    monkeypatch.setattr(
        storage, "list_keys",
        lambda prefix="": sorted(k for k in bucket if k.startswith(prefix)),
    )
    monkeypatch.setattr(storage, "read_key", bucket.get)
    items = feedback.stored()
    assert len(items) == 2
    assert items[0]["text"] == "old, bucket-only"  # oldest first
    assert items[1]["text"] == "local one"


def test_stored_is_empty_when_nothing_anywhere(sandbox):
    assert feedback.stored() == []


# --------------------------------------------------------------- the modal UI


APP = """
import streamlit as st
from stocks.web import feedback

st.write("page body")
feedback.render_sidebar("Cartera")
"""


@pytest.fixture
def app(sandbox):
    """The sidebar entry point running in a real script run."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(APP, default_timeout=30)
    at.run()
    return at


def _write(at, text: str):
    """Type into the composer and press send, the way a reader does."""
    return at.chat_input(key="fb_input").set_value(text).run()


def test_the_button_opens_a_dialog_with_a_composer(app):
    """The whole point of the modal: the comment field is reachable. The old
    sidebar popover died the moment the pointer left the drawer to reach it."""
    assert [b.key for b in app.sidebar.button] == ["fb_open"]
    assert not app.chat_input  # nothing rendered until the button is pressed
    app.sidebar.button(key="fb_open").click().run()
    assert [c.key for c in app.chat_input] == ["fb_input"]
    assert [s.key for s in app.segmented_control] == ["fb_kind"]
    assert not app.exception


def test_send_stores_the_comment_closes_the_modal_and_toasts(app, sandbox):
    app.sidebar.button(key="fb_open").click().run()
    app.segmented_control(key="fb_kind").set_value("bug").run()
    _write(app, "  the chart is upside down  ")

    stored = json.loads(next(sandbox.glob("*.json")).read_text())
    assert (stored["text"], stored["kind"], stored["page"]) == (
        "the chart is upside down", "bug", "Cartera")
    assert not app.chat_input  # modal closed
    assert [t.value for t in app.toast] == ["Thanks — received!"]
    assert not app.exception


def test_a_blank_send_warns_and_keeps_the_modal_open(app, sandbox):
    """A rejected submission must not close the modal — the composer is still
    there to write in."""
    app.sidebar.button(key="fb_open").click().run()
    _write(app, "   ")
    assert [w.value for w in app.warning] == ["Write something first."]
    assert [c.key for c in app.chat_input] == ["fb_input"]
    assert not sandbox.exists()  # nothing stored


# -------------------------------------------- the composer's own microphone


class _FakeSt:
    """Just enough Streamlit for `_transcribe` and `_close`: state, spinner,
    notices."""

    def __init__(self):
        self.session_state: dict = {}
        self.warnings: list[str] = []

    def warning(self, msg):
        self.warnings.append(msg)

    @contextmanager
    def spinner(self, *a, **kw):
        yield


class _Clip:
    """The recording st.chat_input hands back on `value.audio`."""

    def __init__(self, data: bytes = b"RIFFfake"):
        self._data = data
        self.name = "voice.wav"

    def getvalue(self) -> bytes:
        return self._data


class _Value:
    """A ChatInputValue: what was typed, plus what was recorded."""

    def __init__(self, text: str = "", audio=None):
        self.text = text
        self.audio = audio


@pytest.fixture
def dictated(monkeypatch):
    """A configured backend that hears one fixed sentence; counts the calls."""
    calls: list[bytes] = []

    def _transcribe(audio, **kw):
        calls.append(audio)
        return "the chart is upside down"

    monkeypatch.setattr(feedback.stt, "available", lambda: True)
    monkeypatch.setattr(feedback.stt, "transcribe", _transcribe)
    monkeypatch.setattr(feedback, "active_language", lambda: "en")
    return calls


def test_a_bare_string_means_the_microphone_was_never_drawn():
    """st.chat_input degrades to a plain string on a deploy with no
    transcription backend — the value has no `audio` to ask for."""
    assert feedback._submitted("typed only") == ("typed only", None)
    assert feedback._submitted(None) == ("", None)


def test_the_recording_arrives_beside_what_was_typed():
    clip = _Clip()
    assert feedback._submitted(_Value("half typed", clip)) == ("half typed", clip)


def test_transcribe_returns_the_words(dictated, monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(feedback, "st", fake)
    assert feedback._transcribe(_Clip()) == "the chart is upside down"
    assert len(dictated) == 1


def test_a_failed_transcription_says_so_and_sends_nothing(dictated, monkeypatch):
    def _boom(audio, **kw):
        raise feedback.stt.TranscriptionFailed("chat.voice_silent")

    monkeypatch.setattr(feedback.stt, "transcribe", _boom)
    fake = _FakeSt()
    monkeypatch.setattr(feedback, "st", fake)
    assert feedback._transcribe(_Clip()) is None
    assert fake.warnings  # the reason was drawn


def test_dictation_is_rate_limited(dictated, monkeypatch):
    """Every clip spends the operator's shared Whisper quota, and a mic inside
    the composer is one button to lean on."""
    monkeypatch.setattr(feedback.ratelimit, "allow", lambda *a, **kw: False)
    fake = _FakeSt()
    monkeypatch.setattr(feedback, "st", fake)
    assert feedback._transcribe(_Clip()) is None
    assert not dictated
    assert fake.warnings


def test_a_spoken_report_is_stored_as_it_was_heard(app, sandbox, dictated,
                                                   monkeypatch):
    """The chat's deal, kept here: the recording rides in with the send rather
    than landing in a box to fix first."""
    app.sidebar.button(key="fb_open").click().run()
    monkeypatch.setattr(
        feedback.st, "chat_input",
        lambda *a, **kw: _Value("on the holdings page:", _Clip()),
    )
    app.run()

    stored = json.loads(next(sandbox.glob("*.json")).read_text())
    assert stored["text"] == "on the holdings page: the chart is upside down"
    assert not app.exception


# ------------------------------------------ the screenshot attachment (shot)


def _jpeg(width: int = 8, height: int = 8) -> bytes:
    """A real, tiny JPEG — Streamlit's image element decodes what it draws."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def _data_url(raw: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def test_decode_reads_back_the_browsers_data_url():
    raw = _jpeg()
    assert screenshot.decode(_data_url(raw)) == raw


@pytest.mark.parametrize("url", [
    "",
    "not a url",
    "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n").decode(),
    "data:image/jpeg;base64," + base64.b64encode(b"\x89PNG not a jpeg").decode(),
    "data:image/jpeg;base64,!!!! not base64 !!!!",
    "data:image/jpeg;base64," + "A" * (screenshot.MAX_URL_CHARS + 1),
])
def test_decode_refuses_anything_that_is_not_our_jpeg(url):
    """The frame arrives from the browser like any other user input: one
    accepted prefix, the magic bytes checked, the length capped before the
    decode allocates."""
    assert screenshot.decode(url) is None


def test_submit_keeps_the_picture_beside_the_comment(sandbox):
    raw = _jpeg()
    path = feedback.submit("the chart is upside down", "bug", "Cartera", shot=raw)
    data = json.loads(path.read_text())
    image = sandbox / data["shot"]
    assert image.read_bytes() == raw
    assert image.stem == path.stem  # same submission, same name
    assert image.suffix == ".jpg"


def test_submit_without_a_picture_names_none(sandbox):
    path = feedback.submit("no screenshot here", "idea")
    assert "shot" not in json.loads(path.read_text())
    assert not list(sandbox.glob("*.jpg"))


def test_a_picture_that_cannot_be_stored_never_costs_the_comment(
    sandbox, monkeypatch
):
    """The text is the report; the image is an extra. A bucket that refuses
    the upload must not take the submission down with it — and must not leave
    a local orphan the JSON does not name."""
    def _boom(path):
        if path.suffix == ".jpg":
            raise OSError("bucket said no")

    monkeypatch.setattr(feedback.storage, "persist", _boom)
    path = feedback.submit("the chart is upside down", "bug", shot=_jpeg())
    assert json.loads(path.read_text())["text"] == "the chart is upside down"
    assert "shot" not in json.loads(path.read_text())
    assert not list(sandbox.glob("*.jpg"))


def test_shot_path_finds_the_local_file_and_refuses_a_traversal(sandbox):
    path = feedback.submit("with a picture", "bug", shot=_jpeg())
    name = json.loads(path.read_text())["shot"]
    assert feedback.shot_path(name) == sandbox / name
    assert feedback.shot_path("../../etc/passwd.jpg") is None
    assert feedback.shot_path("data/feedback/x.jpg") is None
    assert feedback.shot_path("") is None
    assert feedback.shot_path("nothing-stored-here.jpg") is None


def test_shot_path_pulls_a_bucket_only_picture_down(sandbox, monkeypatch):
    """`stocks feedback` on a fresh checkout has the JSON from the bucket but
    none of the images; asking for one fetches it."""
    raw = _jpeg()

    def _restore(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return True

    monkeypatch.setattr(feedback.storage, "restore", _restore)
    got = feedback.shot_path("2020-01-01T00-00-00Z-aaaaaa.jpg")
    assert got is not None and got.read_bytes() == raw


# --------------------------------------------- the attachment in the modal UI


@pytest.fixture
def grabbed(monkeypatch):
    """Stand in for the browser: `capture` answers whatever the test sets.

    The real capture is a CCv2 component rasterising the live DOM, which no
    headless script run has — what is under test here is the modal's side of
    the deal: the box, the wait, and what reaches `submit`.
    """
    state = {"shot": None, "status": "pending"}
    monkeypatch.setattr(
        feedback.screenshot, "capture",
        lambda key="fb_shot": (state["shot"], state["status"]),
    )
    return state


def test_the_modal_offers_the_screenshot_box_unticked(app):
    """Opt-in, always: the picture carries the writer's own figures."""
    app.sidebar.button(key="fb_open").click().run()
    assert [t.key for t in app.toggle] == ["fb_shot_on"]
    assert app.toggle(key="fb_shot_on").value is False


def test_a_ticked_box_sends_the_picture_with_the_comment(app, sandbox, grabbed):
    grabbed.update(shot=_jpeg(), status="")
    app.sidebar.button(key="fb_open").click().run()
    app.toggle(key="fb_shot_on").set_value(True).run()
    _write(app, "the chart is upside down")

    stored = json.loads(next(sandbox.glob("*.json")).read_text())
    assert (sandbox / stored["shot"]).read_bytes() == grabbed["shot"]
    assert not app.exception


def test_a_send_is_held_until_the_picture_lands(app, sandbox, grabbed):
    """The composer clears itself on submit, so refusing a send mid-capture
    would eat what was written. It waits instead, and goes with the frame."""
    app.sidebar.button(key="fb_open").click().run()
    app.toggle(key="fb_shot_on").set_value(True).run()
    _write(app, "the chart is upside down")
    assert not sandbox.exists()  # nothing stored yet
    assert [c.key for c in app.chat_input] == ["fb_input"]  # modal still open

    grabbed.update(shot=_jpeg(), status="")  # the browser answers
    app.run()
    stored = json.loads(next(sandbox.glob("*.json")).read_text())
    assert stored["text"] == "the chart is upside down"
    assert (sandbox / stored["shot"]).read_bytes() == grabbed["shot"]
    assert not app.exception


def test_closing_the_modal_drops_a_held_send(monkeypatch):
    """Dismissing is not sending: a comment held for a picture must not fire
    itself the next time the modal opens, on a screen the writer has left."""
    fake = _FakeSt()
    fake.session_state.update({
        "_fb_open": True, feedback._QUEUED: {"text": "held", "kind": "bug"},
    })
    monkeypatch.setattr(feedback, "st", fake)
    feedback._close()
    assert fake.session_state == {"_fb_open": False}


def test_a_send_over_the_cap_warns_and_stores_nothing(app, sandbox, monkeypatch):
    """Free-text endpoint, same wall as before the composer changed."""
    monkeypatch.setattr(feedback.ratelimit, "allow", lambda *a, **kw: False)
    app.sidebar.button(key="fb_open").click().run()
    _write(app, "the chart is upside down")
    assert [w.value for w in app.warning] == [
        "That's plenty for now — try again in a while."
    ]
    assert not sandbox.exists()


def test_a_refused_send_hands_the_words_back(app, sandbox, monkeypatch):
    """A chat input empties itself on submit, so a refusal that said only
    "could not save" would take the report with it."""
    def _boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(feedback, "submit", _boom)
    app.sidebar.button(key="fb_open").click().run()
    _write(app, "the chart is upside down")
    assert [e.value for e in app.error] == [
        "Could not save your feedback. Please try again later."
    ]
    assert [c.value for c in app.code] == ["the chart is upside down"]


def test_a_screen_that_cannot_be_captured_still_sends_the_comment(
    app, sandbox, grabbed
):
    grabbed.update(shot=None, status="failed")
    app.sidebar.button(key="fb_open").click().run()
    app.toggle(key="fb_shot_on").set_value(True).run()
    _write(app, "the chart is upside down")

    stored = json.loads(next(sandbox.glob("*.json")).read_text())
    assert stored["text"] == "the chart is upside down"
    assert "shot" not in stored
    assert not app.exception
