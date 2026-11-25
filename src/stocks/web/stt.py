"""Speech-to-text for the assistant's voice notes.

One backend, and it is one the deploy already pays for: the ``[free_llm]``
groq key that funds the keyless "MyBrainStock AI" chat chain also serves Whisper
at ``/audio/transcriptions`` in the OpenAI wire format, so a voice note costs
no new secret, no new dependency and no new account to watch. Shaped like
``chat_web``: ``available()`` decides whether the surface appears at all, and
an unconfigured deploy simply has no microphone.

The audio never lands on disk. ``transcribe`` takes the bytes the browser
recorded, returns the text, and the caller drops the clip — the thread stores
the transcript, so a voice note leaves the same trace as a typed message (see
api/routes/chat_voice.py).
"""

from __future__ import annotations

import io
import time
import wave

from stocks import llm, obs
from stocks.i18n import LANGUAGES

# Groq's turbo Whisper: the cheapest of the three it serves and the only one
# that is multilingual *and* fast enough to keep a voice note inside the pause
# a reader will accept. Overridable per deploy with "groq_stt_model" in
# [free_llm] — a retired slug stays a config fix, the same bargain the chat
# chain makes for its own models.
_BACKEND = "groq"
_BASE_URL = "https://api.groq.com/openai/v1"
_DEFAULT_MODEL = "whisper-large-v3-turbo"

# Guards on what reaches the endpoint. Groq caps a free-tier upload at 25 MB,
# well above anything a spoken question needs; the limits here are about the
# account's *quota*, not the wire — a pocket-dialled recording left running
# would spend a day's worth of audio minutes on silence.
MAX_BYTES = 8 * 1024 * 1024
MAX_SECONDS = 120.0
MIN_SECONDS = 0.4  # a tap on the button, not a question

# What the browser should record at. Whisper works internally at 16 kHz and
# resamples anything else on arrival, so recording at it is free accuracy and
# the smallest upload.
SAMPLE_RATE = 16_000

_TIMEOUT = 30.0

# What Whisper's verbose answer names a language by: OpenAI writes the English
# name ("spanish"), other backends a code or a capitalised name. Only the
# app's own languages need a name here — anything else is "not ours".
_NAMES = {"english": "en", "spanish": "es", "italian": "it", "castilian": "es"}


class TranscriptionFailed(Exception):
    """The clip never became text. Carries a translation key for the surface."""

    def __init__(self, key: str, **fields) -> None:
        super().__init__(key)
        self.key = key
        self.fields = fields


def _model() -> str:
    cfg = llm.free_secret(f"{_BACKEND}_stt_model")
    return cfg or _DEFAULT_MODEL


def available() -> bool:
    """True when a voice note could actually be transcribed.

    Same two conditions the free chat chain checks for a backend: the SDK is
    installed and the operator's key is set. Nothing here reaches the network
    — this runs on every rail render.
    """
    if not llm.installed("openai"):
        return False
    return bool(llm.free_secret(_BACKEND))


def clip_seconds(audio: bytes) -> float | None:
    """Length of a WAV clip, or None when the bytes aren't a WAV we can read.

    The duration check is a courtesy to the quota rather than a gate: an
    unreadable header falls through to the byte cap instead of refusing a clip
    that may be perfectly fine.
    """
    try:
        with wave.open(io.BytesIO(audio), "rb") as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except Exception:
        return None


def transcribe(audio: bytes, *, language: str | None = None,
               filename: str = "voice.wav",
               content_type: str = "audio/wav") -> str:
    """The spoken text of `audio`, or raise TranscriptionFailed.

    `language` is the app's active locale, and only a fallback. Whisper is
    first left to hear the language itself: given `language=` it does not
    detect, it writes that language — so a reader who keeps the app in English
    and speaks Spanish got an English translation of their question, and the
    answer in English with it. What it hears is kept when it is one of the
    app's languages; anything else (a two-second clip of Spanish is routinely
    taken for Portuguese) is asked again in the locale. Only a misheard clip
    pays for the second call.

    `content_type` and `filename` travel together and default to WAV. A
    browser recording through `MediaRecorder` produces whatever its engine
    supports instead — WebM/Opus on Chrome and Firefox, MP4/AAC on Safari —
    and both the name and the type have to say so, because the backend picks
    its decoder off them and rejects a WebM introduced as a WAV.
    """
    if not audio:
        raise TranscriptionFailed("chat.voice_empty")
    if len(audio) > MAX_BYTES:
        raise TranscriptionFailed("chat.voice_too_long",
                                  seconds=int(MAX_SECONDS))
    seconds = clip_seconds(audio)
    if seconds is not None:
        if seconds < MIN_SECONDS:
            raise TranscriptionFailed("chat.voice_empty")
        if seconds > MAX_SECONDS:
            raise TranscriptionFailed("chat.voice_too_long",
                                      seconds=int(MAX_SECONDS))
    key = llm.free_secret(_BACKEND)
    if not key:
        raise TranscriptionFailed("chat.voice_unavailable")

    from openai import OpenAI, omit

    model = _model()
    hint = (language or "").split("-")[0].strip().lower() or None
    t0 = time.perf_counter()
    heard: str | None = None
    retried = False
    try:
        client = OpenAI(api_key=key, base_url=_BASE_URL, timeout=_TIMEOUT)

        def ask(forced: str | None):
            return client.audio.transcriptions.create(
                model=model,
                file=(filename, audio, content_type),
                # `omit`, not None: the field is optional, and the SDK sends
                # None as a JSON null rather than leaving the key out — which
                # is a different request, and one Whisper backends are free
                # to reject. Unforced, the verbose answer names what it heard.
                language=forced or omit,
                response_format=omit if forced else "verbose_json",
            )

        resp = ask(None)
        heard = _code(getattr(resp, "language", None))
        if hint and heard and heard not in LANGUAGES:
            resp = ask(hint)
            retried = True
    except Exception as exc:
        obs.warn("stt.failed", backend=_BACKEND, model=model,
                 bytes=len(audio), seconds=round(seconds or 0.0, 1),
                 error_type=type(exc).__name__, error=str(exc)[:200])
        raise TranscriptionFailed("chat.voice_failed") from exc
    # response_format defaults to json, but a backend that answers with a bare
    # string is within its rights and the SDK passes it straight through.
    text = (resp if isinstance(resp, str) else getattr(resp, "text", "")) or ""
    text = " ".join(text.split())
    obs.event("stt.ok", backend=_BACKEND, model=model,
              seconds=round(seconds or 0.0, 1), chars=len(text),
              heard=heard or "?", hint=hint or "-", retried=retried,
              took_ms=int((time.perf_counter() - t0) * 1000))
    if not text:
        raise TranscriptionFailed("chat.voice_silent")
    return text


def _code(name) -> str | None:
    """A language as Whisper named it, as a two-letter code (None if unnamed)."""
    word = str(name or "").strip().lower()
    if not word:
        return None
    return _NAMES.get(word, word)
