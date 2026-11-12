"""One picture, read by a model that can see.

Everything else in this package is text in, text out: the chat's history, its
metering, the free chain's token budgets and every provider's tool loop are
built on messages that are strings. A picture does not go through any of that.
It goes through here, once, and comes back as words (`chat/screenshot.py`),
so nothing downstream has to learn what an image is.

`readers(provider, key, model)` is the list of calls that could read a picture
with one of the chat's own candidates (`engine.attempts`), in the order to try
them.

A reader's own key reads on the provider's light model first, then on the
model they chose. Copying a table off a picture is the small, fast job the
light model exists for, and the composer is waiting on it: on a live key
(2026-11-12) gemini-flash-lite read 270 cells of a 12 px table exactly in 5 s,
while gemini-3.6-flash on the same key answered 503 "high demand", then 429,
and took 12 s when it did answer. The chosen model stays as the second call,
for the day the light one is the busy one.

The keyless chain is several calls too, because which free model reads a
picture today is a thing that changes under it:

- groq first. It is the backend the chain leads with and its quota is by the
  minute, so a reading costs the next answer nothing.
- openrouter second. Its free models share one pot a day with the chat's own
  fallback, and every reading taken from it is an answer it cannot give.

The slugs are config, the same bargain the chain makes for its chat models: a
retired one is "<backend>_vision_models" in [free_llm] (comma-separated), not
a release.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from stocks.llm import metering

# Room for the model's reasoning as well as its reading: a free reasoning
# model given 600 answered 200 with no text at all (2026-11-11), having spent
# the lot thinking.
MAX_TOKENS = 3000

# A reading is a pause in front of a composer, not a research: a backend that
# has not answered by now is passed over for the next.
TIMEOUT_S = 30.0

_BASES = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# Free models that take an image, per backend, in the order to try them.
# groq: the two its vision docs named on 2026-11-11 — unverified from here,
# its API refuses this machine's address. openrouter: the `:free` slugs its
# catalogue listed with image input the same day.
_FREE_VISION: dict[str, tuple[str, ...]] = {
    "groq": (
        "qwen/qwen3.6-27b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
    ),
    "openrouter": (
        "nvidia/nemotron-3.5-super-vl:free",
        "dots-studio/dots-3-note-preview:free",
        "google/gemma-4-31b-it:free",
    ),
}


class NothingRead(RuntimeError):
    """The model answered, and said nothing."""


@dataclass(frozen=True)
class Reader:
    """One way to read a picture: a backend, a model, and the call."""

    backend: str  # for the log line: "groq", "anthropic", …
    model: str
    free: bool
    _call: Callable[[bytes, str, str, str], str]

    def read(self, image: bytes, mime: str, system: str, ask: str) -> str:
        """What the model wrote about `image`; raises the SDK's own
        exceptions, and `NothingRead` for an answer with no text in it."""
        text = (self._call(image, mime, system, ask) or "").strip()
        if not text:
            raise NothingRead(f"{self.backend}/{self.model}")
        return text


def _openai_compat(base_url: str | None, api_key: str, model: str, *,
                   free: bool = False) -> Callable[[bytes, str, str, str], str]:
    def call(image: bytes, mime: str, system: str, ask: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url,
                        timeout=TIMEOUT_S, max_retries=0)
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        # OpenAI's own reasoning models refuse `max_tokens`; the hosts behind
        # a base_url all take it, and not all of them the newer name.
        cap: dict[str, Any] = ({"max_completion_tokens": MAX_TOKENS}
                               if base_url is None else {"max_tokens": MAX_TOKENS})
        resp = client.chat.completions.create(
            model=model,
            messages=cast(Any, [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": ask},
                    {"type": "image_url", "image_url": {"url": url}},
                ]},
            ]),
            **cap,
        )
        metering.note_openai(model, getattr(resp, "usage", None), free=free)
        if not resp.choices:
            return ""
        return resp.choices[0].message.content or ""

    return call


def _anthropic(api_key: str, model: str) -> Callable[[bytes, str, str, str], str]:
    def call(image: bytes, mime: str, system: str, ask: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_S,
                                     max_retries=0)
        resp = client.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=system,
            messages=cast(Any, [{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": mime,
                    "data": base64.b64encode(image).decode(),
                }},
                {"type": "text", "text": ask},
            ]}]),
        )
        metering.note_anthropic(model, resp.usage)
        return "".join(getattr(block, "text", "") or "" for block in resp.content
                       if getattr(block, "type", "") == "text")

    return call


def _gemini(api_key: str, model: str) -> Callable[[bytes, str, str, str], str]:
    def call(image: bytes, mime: str, system: str, ask: str) -> str:
        from google import genai
        from google.genai import errors, types

        from stocks.llm import _NO_THINKING_LEVEL, GEMINI_API_VERSION

        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            api_version=GEMINI_API_VERSION, timeout=int(TIMEOUT_S * 1000)))

        def ask_once(think: bool):
            return client.models.generate_content(
                model=model,
                contents=cast(Any, [
                    types.Part.from_bytes(data=image, mime_type=mime), ask]),
                config=types.GenerateContentConfig(
                    system_instruction=str(system),
                    max_output_tokens=MAX_TOKENS,
                    # A transcription gains nothing from reasoning, and the
                    # default level took 20 s over a three-line table.
                    thinking_config=(types.ThinkingConfig(
                        thinking_level=cast(Any, "MINIMAL")) if think else None),
                ),
            )

        try:
            resp = ask_once(model not in _NO_THINKING_LEVEL)
        except errors.ClientError as exc:
            # A model that takes a budget, not a level: asked again without
            # one, as the chat's own stream does.
            if (model in _NO_THINKING_LEVEL or getattr(exc, "code", None) != 400
                    or "think" not in str(exc).lower()):
                raise
            _NO_THINKING_LEVEL.add(model)
            resp = ask_once(False)
        metering.note_gemini(model, getattr(resp, "usage_metadata", None))
        return resp.text or ""

    return call


def _free_models(backend: str) -> tuple[str, ...]:
    from stocks.llm import free_secret

    cfg = free_secret(f"{backend}_vision_models")
    if cfg:
        return tuple(m.strip() for m in cfg.split(",") if m.strip())
    return _FREE_VISION[backend]


def _free_readers() -> list[Reader]:
    from stocks.llm import free_secret, installed

    if not installed("openai"):
        return []
    out = []
    for backend, base in _BASES.items():
        key = free_secret(backend)
        if not key:
            continue
        out.extend(
            Reader(backend, model, True,
                   _openai_compat(base, key, model, free=True))
            for model in _free_models(backend)
        )
    return out


def readers(provider, api_key: str, model: str = "") -> list[Reader]:
    """The calls that could read a picture with this chat candidate, in order.

    `model` is the account's saved choice for the provider, "" for its
    default. A reader's own key reads on the provider's light model, then on
    that one (see the module docstring). Nobody is asked whether a model can
    see: the curated ones all can, and a slug that cannot refuses the picture
    itself — which is the next call's turn, and costs one failed call rather
    than a catalogue kept in step with four vendors.
    """
    if provider.id == "free":
        return _free_readers()
    if not provider.available():
        return []
    if provider.id == "anthropic":
        make = _anthropic
    elif provider.id == "gemini":
        make = _gemini
    elif provider.id in ("openai", "openrouter"):
        base = _BASES.get(provider.id)

        def make(api_key: str, model: str):
            return _openai_compat(base, api_key, model)
    else:
        return []
    light = getattr(provider, "classifier_model", "")
    models = dict.fromkeys(
        m for m in (light, model or provider.default_model) if m)
    return [Reader(provider.id, m, False, make(api_key, m)) for m in models]
