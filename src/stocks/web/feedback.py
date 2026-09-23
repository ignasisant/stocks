"""In-app feedback: a sidebar button opening a modal, stored durably.

Two sinks, deliberately redundant:

* A JSON file per submission under data/feedback/, mirrored to the bucket
  (key data/feedback/<stamp>-<id>.json) — the full text, kept until deleted.
  `stocks feedback` reads them back, local or straight from the bucket. When
  the writer attached a picture of their screen it sits beside it under the
  same stem (<stamp>-<id>.jpg) and the JSON names it in "shot".
* An obs event ("feedback") — so submissions show up in the production log
  timeline next to whatever the user was doing when they hit the button, and
  `stocks logs tail --event feedback` works with no extra tooling.

Who sent it: the account's data-dir name (the same pseudonymous slug the logs
use), "guest" for anonymous visitors. The text itself is user input — treat it
as untrusted when reading it back anywhere.
"""

from __future__ import annotations

import io
import json
import time
import uuid
from pathlib import Path

import streamlit as st

from stocks import obs, storage
from stocks.config import DATA_DIR, PROJECT_ROOT
from stocks.web import ratelimit, screenshot, skeletons, stt
from stocks.web.i18n import active_language
from stocks.web.i18n import t as tr

FEEDBACK_DIR = DATA_DIR / "feedback"
KINDS = ("bug", "idea", "other")
MAX_CHARS = 4000

# Feedback is cheap to store but a spam vector like any free-text endpoint.
_MAX_PER_HOUR = 5
# Dictation is the expensive half: every clip spends the operator's shared
# Whisper quota, and a recorder is one button to lean on. Looser than the
# submit cap — redoing a sentence you fumbled is normal — but still a wall.
_MAX_CLIPS_PER_HOUR = 15

# A submission pressed Send on while its screenshot was still being taken.
_QUEUED = "_fb_queued"
# Text a send was refused for (the cap, a storage failure). A chat input hands
# its value over and empties itself, so without this the writer's words would
# be gone from the screen with nothing stored anywhere.
_UNSENT = "_fb_unsent"


def _sender() -> str:
    """The pseudonymous account slug the logs already use, or "guest"."""
    try:
        paths = st.session_state.get("user_paths")
    except Exception:  # outside a script run (CLI, tests): anonymous
        paths = None
    if paths is None:
        return "guest"
    root = paths.root
    return "owner" if root == PROJECT_ROOT else root.name


def submit(
    text: str,
    kind: str,
    page: str = "",
    shot: bytes | None = None,
    *,
    sender: str | None = None,
    lang: str = "",
) -> Path:
    """Persist one submission (disk + bucket) and log the event.

    `shot` is the optional JPEG of the screen the writer was on, already
    decoded and size-checked by stocks.web.screenshot.

    `sender` and `lang` are the two facts only a caller knows. The Streamlit
    composer leaves them out and they are read off the session; the HTTP API
    has no session and names them, which is why they are arguments rather than
    two more things this module guesses.
    """
    kind = kind if kind in KINDS else "other"
    text = text.strip()[:MAX_CHARS]
    stamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    path = FEEDBACK_DIR / f"{stamp}-{uuid.uuid4().hex[:6]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # The picture goes first: the JSON must never name a file that isn't there,
    # and a submission whose image failed is still a submission.
    shot_name = _store_shot(path, shot) if shot else ""
    payload = {
        "ts": stamp,
        "kind": kind,
        "text": text,
        "page": page,
        "user": sender if sender is not None else _sender(),
        "lang": lang or active_language(),
    }
    if shot_name:
        payload["shot"] = shot_name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    storage.persist(path)
    obs.event("feedback", kind=kind, page=page, chars=len(text),
              shot=len(shot) if shot and shot_name else 0)
    return path


def _store_shot(path: Path, shot: bytes) -> str:
    """Write the screenshot beside its submission; "" if it could not be kept.

    The one swallowed failure in this module, and deliberate: the comment is
    the report and the picture is an extra, so a bucket that refuses the image
    must not cost us the text that came with it. The local copy goes too — an
    orphan nothing names would never be read, only found years later.
    """
    image = path.with_suffix(".jpg")
    try:
        image.write_bytes(shot)
        storage.persist(image)
    except Exception:
        obs.event("feedback.shot_store_failed")
        image.unlink(missing_ok=True)
        return ""
    return image.name


def render_sidebar(page_title: str) -> None:
    """The entry point: one sidebar button on every page, opening the modal.

    A modal, not a sidebar popover: the collapsed desktop sidebar is a
    hover-expanded overlay rail, and app.py hides the drawer's own content
    (`stSidebarUserContent`) whenever the rail is not hovered — so a popover
    anchored to a button in there died the moment the pointer left the sidebar
    to reach it, i.e. before the user could type a word. It was also capped at
    the drawer's width. The dialog is centered in the page, independent of the
    sidebar's hover state, and roomy enough to write in.
    """
    # The success toast belongs to the run AFTER the modal closes — a toast
    # emitted inside the dialog dies with the rerun that shuts it.
    if st.session_state.pop("_fb_sent", False):
        st.toast(tr("feedback.sent"), icon=":material/favorite:")
    if st.sidebar.button(
        tr("feedback.button"),
        icon=":material/rate_review:",
        width="stretch",
        key="fb_open",
    ):
        st.session_state["_fb_open"] = True
    if not st.session_state.get("_fb_open"):
        return
    # Kept open by a session flag rather than by the button's own run: every
    # full rerun in this app (top-bar search, chat panel, page nav) would
    # otherwise drop the modal mid-sentence. Dismissing clears the flag —
    # without the callback the next full rerun would pop it straight back up.
    # Built at call time (not @st.dialog) so the title resolves in the run's
    # active language rather than freezing at import — same as the login and
    # investor-profile modals.
    st.dialog(
        tr("feedback.button"), width="small", on_dismiss=_close
    )(_dialog_body)(page_title)


def _close() -> None:
    st.session_state["_fb_open"] = False
    # A submission held back for its screenshot dies with the modal: it was
    # never stored, and firing it on the next open would send a comment about
    # a screen the writer has since left. The refused draft goes with it —
    # it was on screen to be copied, not to be kept.
    st.session_state.pop(_QUEUED, None)
    st.session_state.pop(_UNSENT, None)


def _composer():
    """The comment box: one line that grows, with send and mic inside it.

    Two calls rather than one with a computed flag: `accept_audio` is typed as
    a literal (the widget returns a bare string without it), and a deploy with
    no transcription backend must draw no microphone at all — a mic that
    answers "not available" on press is worse than none. Which one runs cannot
    change inside a session, so the widget is never reset under the writer.
    """
    if stt.available():
        return st.chat_input(
            tr("feedback.placeholder"), key="fb_input", max_chars=MAX_CHARS,
            height=140, accept_audio=True, audio_sample_rate=stt.SAMPLE_RATE,
        )
    return st.chat_input(
        tr("feedback.placeholder"), key="fb_input", max_chars=MAX_CHARS,
        height=140,
    )


def _submitted(value) -> tuple[str, object | None]:
    """(text, recording) out of st.chat_input, which hands back a bare string
    when the microphone is off — every deploy without a transcription key.

    `audio` raises AttributeError rather than answering None on a widget drawn
    with accept_audio=False, hence getattr; same shape as chat_core._submitted.
    """
    if value is None:
        return "", None
    if isinstance(value, str):
        return value, None
    return (value.text or ""), getattr(value, "audio", None)


def _transcribe(clip) -> str | None:
    """The words in a recording, or None once the reason is on screen.

    Rate-limited on its own account: every clip spends the operator's shared
    Whisper quota, and a microphone is one button to lean on. Looser than the
    submit cap — redoing a sentence you fumbled is normal — but still a wall.
    """
    if not ratelimit.allow(f"feedback_stt::{_sender()}",
                           max_events=_MAX_CLIPS_PER_HOUR, window_s=3600):
        st.warning(tr("feedback.rate_limited"))
        return None
    # A shimmer in the shape of the line the transcript will become, never a
    # spinner: the web layer holds places, it does not spin (test_skeletons).
    with skeletons.slot("text", lines=1, width="60%"):
        try:
            said = stt.transcribe(clip.getvalue(), language=active_language())
        except stt.TranscriptionFailed as exc:
            st.warning(tr(exc.key, **exc.fields))
            return None
    obs.event("feedback.dictated", chars=len(said))
    return said


def _attachment(ns: str = "fb") -> tuple[bytes | None, str]:
    """Optionally attach a picture of the screen behind this modal.

    Returns `(jpeg, status)` — the status is what the send path needs to tell
    "still being taken" (worth waiting a second for) from "cannot be taken"
    (send the comment without it). See stocks.web.screenshot for the capture.

    Outside the form for the same reason the recorder is: a form hands its
    widgets over only when it is submitted, so a box ticked inside one would
    ask the browser for the picture at the very instant of Send — the writer
    would never see what they were about to attach. Out here, ticking it is
    its own rerun and the shot appears under the box.
    """
    key = f"{ns}_shot"
    if not st.toggle(tr("feedback.shot"), key=f"{key}_on",
                     help=tr("feedback.shot_help")):
        # Unticking drops the frame, so re-ticking later captures the screen
        # as it is *then* rather than resurrecting a stale one.
        screenshot.reset(key)
        return None, ""
    shot, status = screenshot.capture(key)
    if status == "pending":
        st.caption(tr("feedback.shot_working"))
    elif status == "too_big":
        st.caption(tr("feedback.shot_big"))
    elif status:
        st.caption(tr("feedback.shot_failed"))
    elif shot:
        # Shown, not just counted: the writer is sending their own screen, and
        # gets to see exactly which one before it leaves the browser.
        st.image(io.BytesIO(shot), width=260,
                 caption=tr("feedback.shot_ready", kb=round(len(shot) / 1024)))
    return shot, status


def _draw_unsent(text: str) -> None:
    """A refused submission, in the one element that has a copy button."""
    st.caption(tr("feedback.unsent"))
    st.code(text, language=None, wrap_lines=True)


def _handback(text: str) -> None:
    """Hand a refused submission back: on screen now, and again on the reruns
    that follow (the refusal itself does not rerun the modal, and the block at
    the top of the body only exists from the next run on)."""
    st.session_state[_UNSENT] = text
    _draw_unsent(text)


def _dialog_body(page_title: str) -> None:
    """The modal's body: what kind of note, an optional picture, the composer.

    The composer is `st.chat_input`, not a text area inside a form, and that
    is what puts the microphone where the assistant's is: `accept_audio` draws
    the recorder *inside* the input bar, next to the send arrow, instead of
    parking a separate recorder widget above the box. It also does what the
    form was there for — a chat input commits its own text, so the blur rerun
    can no longer eat the first click on Send.

    The trade is the chat's trade: a recording is sent as it was heard, not
    dropped into a box to fix first. Whisper mishears tickers, so the reader
    of a spoken report gets the odd wrong symbol — the same deal the assistant
    already makes with a voice note.
    """
    st.caption(tr("feedback.caption"))
    unsent = st.session_state.get(_UNSENT)
    if unsent:
        _draw_unsent(unsent)
    kind = st.segmented_control(
        tr("feedback.kind"),
        KINDS,
        default="idea",
        format_func=lambda k: tr(f"feedback.kind_{k}"),
        key="fb_kind",
    )
    shot, shot_status = _attachment()
    value = _composer()
    text, clip = _submitted(value)
    if clip is not None:
        said = _transcribe(clip)
        if said is None:
            return  # the reason is already drawn; there is nothing to send
        # A note recorded *with* something typed is one report, not two.
        text = f"{text} {said}".strip() if text else said

    queued = st.session_state.get(_QUEUED)
    if value is None:
        if not queued:
            return
        # The picture this submission was held for has arrived (or given up).
        text, kind = queued["text"], queued["kind"]
    if not text.strip():
        st.warning(tr("feedback.empty"))
        return
    if shot_status == "pending":
        # The composer clears itself on submit, so refusing the send here
        # would eat what was written. Hold the submission instead: the frame
        # lands a rerun later and carries it in.
        st.session_state[_QUEUED] = {"text": text, "kind": kind}
        st.caption(tr("feedback.shot_wait"))
        return
    st.session_state.pop(_QUEUED, None)
    if not ratelimit.allow(f"feedback::{_sender()}",
                           max_events=_MAX_PER_HOUR, window_s=3600):
        st.warning(tr("feedback.rate_limited"))
        _handback(text)
        return
    try:
        submit(text, kind or "other", page_title, shot=shot)
    except Exception:
        # The local file may have been written even if the mirror failed; the
        # writer shouldn't retry into a duplicate — hence the text handed back
        # to copy rather than a composer refilled to press Send again.
        st.error(tr("feedback.failed"))
        _handback(text)
        obs.event("feedback.store_failed")
        return
    # Stored: forget the attachment so the next open starts blank, then close
    # the modal with a full rerun (which also renders the toast above).
    st.session_state.pop("fb_shot_on", None)
    st.session_state.pop(_UNSENT, None)
    screenshot.reset("fb_shot")
    st.session_state["_fb_sent"] = True
    _close()
    st.rerun()


# ------------------------------------------------------------------ read side


def stored(prefix: str = "data/feedback/") -> list[dict]:
    """Every stored submission, oldest first — local files plus bucket-only
    ones (a headless checkout sees the bucket, a dev checkout sees both)."""
    items: dict[str, dict] = {}
    if FEEDBACK_DIR.is_dir():
        for f in sorted(FEEDBACK_DIR.glob("*.json")):
            try:
                items[f.name] = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
    for key in storage.list_keys(prefix):
        name = key.removeprefix(prefix)
        if name in items or not name.endswith(".json"):
            continue  # the .jpg siblings are fetched on demand by shot_path
        raw = storage.read_key(key)
        if raw:
            try:
                items[name] = json.loads(raw)
            except ValueError:
                continue
    return [items[k] for k in sorted(items)]


def shot_path(name: str) -> Path | None:
    """The local file for a submission's screenshot, or None if there isn't one.

    Pulls it out of the bucket when this checkout has never seen it, so
    `stocks feedback` on a fresh clone can still open the picture. `name`
    comes out of a stored JSON file — treated as untrusted: one directory, one
    extension, no traversal.
    """
    if not name or name != Path(name).name or not name.endswith(".jpg"):
        return None
    path = FEEDBACK_DIR / name
    if path.exists() or storage.restore(path):
        return path
    return None
