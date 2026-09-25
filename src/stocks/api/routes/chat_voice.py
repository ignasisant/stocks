"""A voice note, turned into the question it was.

The Streamlit composer has had a microphone since `st.chat_input` grew one: the
clip is transcribed by `web.stt` (Whisper on the free chain's own key) and the
words are sent down the same path typed text takes. This is that one step for
any other front end — transcription and nothing else, because a spoken question
*is* a question, and a client that had to send it through a second, different
route would have a second, different turn.

**The audio never lands on disk**, here or anywhere: it is decoded, sent to the
backend, and dropped. There is nothing to keep — the transcript is what the
thread stores, and a recording of somebody talking about their portfolio is the
last thing this app should be accumulating.

**A refusal is a locale key, not a sentence.** `TranscriptionFailed` carries the
key the drawer already renders (`chat.voice_too_long`, `chat.voice_silent`, …)
with its parameters, so both front ends say the same thing about the same clip
in the reader's own language, and the API stays out of the copywriting.

**`available()` decides whether the button exists.** A deployment with no
transcription key answers 503 here and says so in `/chat/state`, because a
microphone that apologises on press is worse than no microphone.
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stocks import accounts
from stocks.api.deps import VoiceNote as VoiceBudget
from stocks.web import stt

router = APIRouter(prefix="/chat", tags=["chat"])

# What a browser's MediaRecorder actually produces, and what Whisper backends
# take: WebM/Opus on Chrome and Firefox, MP4/AAC on Safari, WAV from anything
# that encodes by hand. The name is derived from the type rather than trusted
# from the client, because the decoder is picked off both.
_TYPES = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


class VoiceNote(BaseModel):
    model_config = {"extra": "forbid"}

    audio: str = Field(description="The recording's bytes, base64-encoded.")
    content_type: str = Field(
        default="audio/webm",
        description=(
            "The recording's media type, as the recorder reported it. "
            f"One of: {', '.join(sorted(_TYPES))}."
        ),
    )
    lang: str | None = Field(
        default=None,
        description=(
            "ISO-639-1 hint. Whisper detects the language by itself, but two "
            "seconds of Spanish is routinely detected as Portuguese, and the "
            "hint costs nothing."
        ),
    )


class Transcript(BaseModel):
    text: str


@router.post("/voice", response_model=Transcript, summary="Transcribe a voice note")
def transcribe(body: VoiceNote, paths: VoiceBudget) -> Transcript:
    """The words in a recording. Writes nothing — not the audio, not a turn.

    A `Writer` even so: it spends the operator's transcription key, which is
    exactly what a bearer token must never be able to do on somebody else's
    account.
    """
    if not stt.available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="chat.voice_unavailable",
        )
    kind = body.content_type.split(";")[0].strip().lower()
    if kind not in _TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"cannot read {body.content_type!r}",
        )
    try:
        audio = base64.b64decode(body.audio, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="audio must be base64",
        ) from exc
    if len(audio) > stt.MAX_BYTES:
        # The same refusal `stt` would raise, made before the bytes are handed
        # on: a clip over the cap is over it whatever the backend thinks.
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="chat.voice_too_long",
        )

    prefs = accounts.load_prefs(paths.prefs)
    lang = (body.lang or prefs.get("language") or "").strip().lower() or None
    try:
        text = stt.transcribe(
            audio,
            language=lang,
            filename=f"voice.{_TYPES[kind]}",
            content_type=kind,
        )
    except stt.TranscriptionFailed as failed:
        # 422 for everything the clip itself is guilty of (too long, too short,
        # silent) and 503 for a backend that was not there. The body is the
        # locale key either way — the drawer already knows how to say it.
        unavailable = failed.key == "chat.voice_unavailable"
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if unavailable
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=failed.key,
        ) from failed
    return Transcript(text=text)
