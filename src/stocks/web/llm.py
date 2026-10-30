"""LLM provider registry for the chat page — TopStocks AI (free), Claude, ChatGPT,
Gemini, OpenRouter.

The named providers are bring-your-own-key: the user supplies their own API key
(own billing). "TopStocks AI" is keyless for the user — it chains through
operator-funded free-tier backends configured in the ``[free_llm]`` secrets
section, hopping to the next backend when one is rate-limited, until all are
exhausted. A provider exposes a streaming generator plus an error classifier
that maps its SDK's exceptions onto the page's shared locale keys
(``chat.invalid_key`` / ``chat.no_credits`` / ``chat.api_error``); an unmapped
exception returns ``None`` so the caller can re-raise it.

SDKs are imported lazily inside each function, so a missing optional dependency
only disables that one provider (``Provider.available()``) instead of breaking
the whole page.
"""

from __future__ import annotations

import contextlib
import contextvars
import importlib.util
import re
import time
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from stocks import obs, secrets_env
from stocks.web import metering

# Output ceiling per turn. It has to leave room for reasoning tokens as well as
# the answer: on Opus 5.5 and Sonnet 5.5 adaptive thinking is on whenever
# `thinking` is omitted, and what the model thinks is drawn from this same
# budget. At 4096 a long answer after a long think came back cut off
# mid-sentence; the models
# only bill what they actually produce, so a roomier cap costs nothing on the
# short turns that are most of them.
MAX_TOKENS = 16000

# Rounds of "model asks for tools, we run them" before the loop is cut off. The
# gather step is a means to an answer, not the answer: three rounds is enough
# for search -> read -> check a quote, and a cap is what stops a model that
# keeps asking for one more page from owning the whole turn.
MAX_TOOL_ROUNDS = 3

# Calls of one round run at once, up to this many: a model that asks for three
# searches in one turn asked for them independently, and back to back they are
# three times the wait. Bounded so one greedy round does not open a socket per
# ticker in the book.
TOOL_WORKERS = 4

# What a call whose arguments were not JSON gets back instead of running. Run
# with `{}` it failed on a missing argument and the model read a refusal about
# the wrong thing; told this, it sends the call again (Groq, OpenRouter free
# models, prod 2026-10).
BAD_ARGS = "The arguments were not valid JSON. Send the call again with valid JSON."


def _execute_round(execute: Callable[[str, dict], str],
                   wanted: list[tuple[str, dict]]) -> list[str]:
    """`execute` over one round's calls, results in the order they were asked.

    One call runs inline: a pool for it is only overhead. The dispatcher must
    not raise (`toolbox.executor` turns a failure into a sentence), so a
    failure here is a bug and is allowed to end the loop like any other."""
    if len(wanted) <= 1:
        return [execute(name, args) for name, args in wanted]
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    # Each call in a copy of the round's context: the turn's log fields and
    # meter (`metering`) go with it to the pool thread.
    with ThreadPoolExecutor(max_workers=min(len(wanted), TOOL_WORKERS)) as pool:
        futures = [pool.submit(contextvars.copy_context().run, execute, *call)
                   for call in wanted]
        return [f.result() for f in futures]


@dataclass(frozen=True)
class ToolSpec:
    """One tool offered to the model: what it is called, what it does, and the
    JSON Schema of its arguments. Provider-neutral — each backend's own wire
    shape is built from this."""

    name: str
    description: str
    schema: dict


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict
    result: str


class Cut(str):
    """The empty chunk a stream ends with when the model ran out of room
    (`max_tokens`, `finish_reason: length`) rather than finishing. It joins to
    nothing, so `complete` is unaffected; the chat engine looks for it to close
    the half-written markdown and offer to continue."""

    def __new__(cls):
        return super().__new__(cls, "")


class Idle(str):
    """The empty chunk a free backend's stream yields for a frame with no text
    in it — reasoning, a keep-alive comment, usage. The chain reads it as "still
    thinking" to time the wait for the first word; it never reaches a reader."""

    def __new__(cls):
        return super().__new__(cls, "")


@dataclass(frozen=True)
class ToolRun:
    """What one tool-using exchange produced: the model's closing text and
    every tool call it made along the way, in order."""

    text: str
    calls: list[ToolCall]


# A model id as vendors spell them: "claude-opus-5", "gpt-5", "models/…"
# stripped, "openai/gpt-5.6-sol:free", "~anthropic/claude-sonnet-latest".
_MODEL_SLUG = re.compile(r"[A-Za-z0-9~][A-Za-z0-9._:/@+~-]{0,127}")

# One vendor listing per key fingerprint, for an hour (`Provider.list_models`).
MODELS_TTL_S = 60 * 60
_model_lists: dict[str, tuple[float, list[str]]] = {}


@dataclass(frozen=True)
class Provider:
    id: str
    label: str  # brand name, shown in the selector (not translated)
    models: tuple[str, ...]  # selectable models; the first is the default
    key_placeholder: str
    console_url: str
    _module: str  # top-level import name used for the availability probe
    _stream: Callable[[str, str, str, list[dict]], Iterator[str]]
    _error_key: Callable[[Exception], str | None]
    needs_key: bool = True  # False = keyless (server-side keys); no BYOK gate
    _available: Callable[[], bool] | None = None  # overrides the SDK probe
    # Cheapest model, used by the skill auto-router (web/chat_skills.py). ""
    # falls back to default_model — right for the free chain, which ignores the
    # model argument and picks per backend.
    classifier_model: str = ""
    # Brand website, for the selector logo (mirrored same-origin like broker
    # logos). None = no external brand; the keyless TopStocks provider ships its
    # own bundled icon instead.
    domain: str | None = None
    # Native tool use, when this backend has it wired up. None means the caller
    # keeps the fixed pre-flight (chat/engine.py) — a provider without tools
    # loses the model-directed lookup, not the answer.
    _tools: Callable[..., ToolRun] | None = None
    # One-click sign-in in place of a pasted key: an OAuth PKCE authorize page
    # and the endpoint that trades its code for a key the user owns. Both run
    # in the reader's browser (frontend chat/connect.ts) and the key they mint
    # goes through the same store / this-session-only paths a typed one does,
    # so the server learns nothing new. "" = paste-a-key only.
    connect_url: str = ""
    connect_token_url: str = ""
    # Every model this provider serves the given key, live from its own
    # /models. None = only the curated `models` are offered (the free chain,
    # which picks its own per backend).
    _list_models: Callable[[str], list[str]] | None = None
    # The listing answers without a key (OpenRouter's catalogue is public), so
    # a reader can browse before pasting one.
    public_models: bool = False
    # `_stream` takes a `thinking` level (`thinking()`); the others ignore it.
    _thinking: bool = False

    @property
    def default_model(self) -> str:
        return self.models[0]

    def accepts_model(self, model: str) -> bool:
        """Whether `model` may be saved as this account's choice here.

        A BYOK provider takes any well-formed slug: the curated `models` are
        the ones offered first, not the only ones the reader's key can reach,
        and a list kept here would always trail the vendor's. Whether the slug
        exists is the provider's to say (`list_models`, checked when a key is
        at hand to ask with). The keyless chain serves only what it lists.
        """
        if not self.needs_key:
            return model in self.models
        return bool(_MODEL_SLUG.fullmatch(model or ""))

    def list_models(self, api_key: str) -> list[str]:
        """The chat models `api_key` can use here, sorted; raises the SDK's own
        exceptions. The curated list when this provider cannot be asked.

        Kept MODELS_TTL_S per key: the settings screen asks on open and again
        when a model is saved, and a vendor's catalogue does not move that fast.
        """
        if self._list_models is None:
            return list(self.models)
        fp = _fingerprint(self.id, api_key)
        hit = _model_lists.get(fp)
        if hit and time.monotonic() - hit[0] < MODELS_TTL_S:
            return list(hit[1])
        got = self._list_models(api_key)
        _model_lists[fp] = (time.monotonic(), got)
        return list(got)

    def available(self) -> bool:
        """True when this provider's SDK is installed (or its override says so)."""
        if self._available is not None:
            return self._available()
        return importlib.util.find_spec(self._module) is not None

    def stream(
        self, api_key: str, model: str, system: str, messages: list[dict]
    ) -> Iterator[str]:
        # Read here, when the call is made, not in the generator's body: that
        # runs on whichever thread pulls the first chunk, in its context.
        level = _THINKING.get()
        if level and self._thinking:
            return self._stream(api_key, model, system, messages, thinking=level)
        return self._stream(api_key, model, system, messages)

    def complete(
        self, api_key: str, model: str, system: str, messages: list[dict]
    ) -> str:
        """One short non-interactive completion (the skill router's call).

        Joins the streaming generator rather than adding a second code path per
        provider — for the tiny replies involved the cost is identical. On the
        cheapest model it thinks as little as it can unless told otherwise:
        a router's JSON or a title gains nothing from a minute of reasoning."""
        model = model or self.default_model
        if model == self.classifier_model and not _THINKING.get():
            with thinking("minimal"):
                return "".join(self.stream(api_key, model, system, messages))
        return "".join(self.stream(api_key, model, system, messages))

    def error_key(self, exc: Exception) -> str | None:
        """Locale key for a known SDK error, or None to let the caller re-raise."""
        return self._error_key(exc)

    def supports_tools(self) -> bool:
        """Whether this provider can run the model-directed lookup."""
        return self._tools is not None and self.available()

    def run_tools(
        self,
        api_key: str,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[ToolSpec],
        execute: Callable[[str, dict], str],
        max_rounds: int = MAX_TOOL_ROUNDS,
        stop: Callable[[], bool] | None = None,
    ) -> ToolRun:
        """Let the model call `tools` until it stops asking, then hand back what
        it said and what it ran.

        `stop()` is asked after each round: True ends the loop there, without
        the model call that would only have been told the budget is spent
        (chat/agent.py `_Budget`). The closing text is then "".

        `execute(name, args) -> str` is the caller's dispatcher; the loop itself
        (and every backend's message shape) stays in here. Raises the SDK's own
        exceptions — the caller decides whether a failed lookup is fatal (it is
        not: chat/agent.py falls back to the fixed pre-flight).
        """
        if self._tools is None:
            raise NotImplementedError(f"{self.id} has no tool support")
        return self._tools(api_key, model or self.default_model, system,
                           messages, tools, execute, max_rounds, stop=stop)


class Prompt(str):
    """A system prompt that remembers where its stable parts end.

    The string is the whole prompt — every provider, counter and log reads it
    as one — and `blocks` are its parts in order, most stable first: the fixed
    persona with the user's memories, the book snapshot, then what changes
    with the turn (the current view, the skills, the rules). A provider that
    caches by explicit breakpoint (Anthropic) marks each part, so a turn that
    changed only the view still reads the persona and the book from the cache
    instead of rewriting the whole prompt; providers that cache by prefix on
    their own get the same gain from the order alone."""

    blocks: tuple[str, ...]

    def __new__(cls, *blocks: str) -> Prompt:
        self = super().__new__(cls, "".join(blocks))
        self.blocks = tuple(b for b in blocks if b)
        return self


# ------------------------------------------------------------- Claude (Anthropic)


def _system_blocks(system: str) -> list[dict]:
    """The system prompt as Anthropic content blocks, one cache breakpoint on
    each part (`Prompt.blocks`; a plain string is one part). The lookup takes
    the longest cached prefix of parts, so a change in a later part costs
    only the parts after it. Four breakpoints are allowed per request: three
    parts here plus the one on the last message."""
    parts = getattr(system, "blocks", None) or (str(system),)
    return [{"type": "text", "text": part, "cache_control": {"type": "ephemeral"}}
            for part in parts[:3] if part]


def _with_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """A copy of the turns with one ephemeral cache breakpoint on the last one.

    Prompt caching is a prefix match: the whole prior-conversation prefix is a
    cache *read* on the next turn (~0.1x cost) instead of full-price reprocessing
    of the entire thread every message. We copy rather than mutate — the caller's
    history is shared with the other providers and persisted to disk as plain
    strings.
    """
    if not messages:
        return messages
    out = [dict(m) for m in messages]
    out[-1]["content"] = [
        {"type": "text", "text": out[-1]["content"],
         "cache_control": {"type": "ephemeral"}}
    ]
    return out


def _anthropic_stream(api_key, model, system, messages):
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    # Cache the system prompt part by part (persona + memories, book, the
    # turn's own context) and the conversation prefix. Within a session the
    # first parts repeat verbatim while the view and the skills move, so the
    # resend-everything-every-turn cost becomes cheap cache reads of the
    # parts that held. A miss (the book repriced, a prefix below the model's
    # minimum) just rewrites — no error, no behaviour change.
    with client.messages.stream(
        model=model, max_tokens=MAX_TOKENS, system=cast(Any, _system_blocks(system)),
        messages=cast(Any, _with_cache_breakpoint(messages)),
    ) as stream:
        yield from stream.text_stream
        final = stream.get_final_message()
        metering.note_anthropic(model, final.usage)
        if final.stop_reason == "max_tokens":
            yield Cut()


# Context editing for the tool loops. A deep research runs up to eight rounds,
# and every round resends what all the earlier ones read: by the sixth, the
# model pays for (and wades through) pages it has already taken in. Once the
# results still on the wire pass CLEAR_AFTER characters, those older than the
# last KEEP_ROUNDS rounds are cut to their opening and marked — in one go, so
# a provider's prompt cache breaks once, not every round. Only the loop's
# copy: the calls it returns keep every result whole, and the answer is
# written from those.
CLEAR_AFTER = 80_000
KEEP_ROUNDS = 2
CLEARED_CHARS = 300
CLEARED = ("\n[Already read earlier in this research — cleared here to save "
           "room; the answer still gets it in full.]")


def _clear_old_results(rounds: list[list[dict]]) -> int:
    """Clear the results of all but the last KEEP_ROUNDS rounds, in place,
    when what is left of them all passes CLEAR_AFTER. `rounds` holds each
    round's result dicts as sent ("content" is the text). Returns how many
    were cleared."""
    live = sum(len(str(r.get("content") or "")) for batch in rounds
               for r in batch if not str(r.get("content") or "").endswith(CLEARED))
    if live <= CLEAR_AFTER:
        return 0
    cleared = 0
    for batch in rounds[:-KEEP_ROUNDS]:
        for r in batch:
            text = str(r.get("content") or "")
            if text.endswith(CLEARED) or len(text) <= CLEARED_CHARS:
                continue
            r["content"] = text[:CLEARED_CHARS].rstrip() + CLEARED
            cleared += 1
    if cleared:
        obs.event("llm.tool_results_cleared", results=cleared, chars=live)
    return cleared


def _anthropic_tools(api_key, model, system, messages, tools, execute, rounds,
                     stop=None):
    """Anthropic's tool loop: create, run every tool_use block, feed the results
    back, repeat until the model stops asking.

    Parallel tool calls arrive as several tool_use blocks in one assistant
    message and their results must go back in ONE user message — splitting them
    teaches the model to stop asking for them in parallel. The assistant turn is
    appended as `resp.content` rather than re-serialized text so nothing (the
    tool_use blocks least of all) is lost on the way back.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    schema = [{"name": t.name, "description": t.description,
               "input_schema": t.schema} for t in tools]
    # The loop resends the system prompt and the thread every round; marked,
    # they are cache reads from the second round on (and from the answer's
    # own call after, which sends the same parts).
    convo = _with_cache_breakpoint(list(messages))
    calls: list[ToolCall] = []
    sent: list[list[dict]] = []  # each round's results, for `_clear_old_results`
    text = ""
    for _ in range(max(1, rounds)):
        _clear_old_results(sent)
        resp = client.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=cast(Any, _system_blocks(system)),
            messages=cast(Any, convo), tools=cast(Any, schema),
        )
        metering.note_anthropic(model, getattr(resp, "usage", None))
        text = "".join(b.text for b in resp.content if b.type == "text")
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            break
        convo.append({"role": "assistant", "content": resp.content})
        wanted = [(block.name, dict(block.input or {})) for block in uses]
        results = []
        for block, (name, args), out in zip(
                uses, wanted, _execute_round(execute, wanted), strict=True):
            calls.append(ToolCall(name, args, out))
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": out or "(no result)"})
        sent.append(results)
        convo.append({"role": "user", "content": results})
        if stop is not None and stop():
            return ToolRun("", calls)
    return ToolRun(text, calls)


def _anthropic_error(exc):
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return "chat.invalid_key"
    if isinstance(exc, anthropic.BadRequestError):
        return "chat.no_credits" if "credit balance" in str(exc) else "chat.api_error"
    if isinstance(exc, anthropic.OverloadedError | anthropic.ServiceUnavailableError):
        # 529 overloaded / 503: saturated, not broken (see _gemini_error).
        return "chat.provider_busy"
    if isinstance(exc, anthropic.APIError):
        return "chat.api_error"
    return None


# ------------------------------------------------------------- ChatGPT (OpenAI)


def _openai_compat_stream(base_url: str | None = None, *, free: bool = False,
                          **client_opts):
    """Streaming generator for OpenAI and any OpenAI-compatible endpoint
    (Groq, Cerebras, OpenRouter, ...) — only the base_url differs.

    `client_opts` reach the OpenAI client as given (the free chain passes
    `_FREE_CLIENT`); `free` marks its usage as costing nothing
    (`metering`) and has every frame without text yield an `Idle`, so the
    chain sees a model that is thinking rather than writing."""

    def _stream(api_key, model, system, messages):
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url, **client_opts)
        # Usage on the last chunk is OpenAI's opt-in; the hosts behind a
        # base_url send it unasked or not at all, and an option one of them
        # does not know is a 400 on every answer.
        extra: dict[str, Any] = ({"stream_options": {"include_usage": True}}
                                 if base_url is None else {})
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, *messages],
            stream=True, **extra,
        )
        cut = False
        try:
            for chunk in stream:
                if getattr(chunk, "usage", None) is not None:
                    metering.note_openai(model, chunk.usage, free=free)
                # OpenRouter interleaves comment frames with no choices; skip them.
                if chunk.choices and chunk.choices[0].finish_reason == "length":
                    cut = True
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
                elif free:
                    yield Idle()
        finally:
            stream.close()  # a caller that stops reading drops the connection
        if cut:
            yield Cut()

    return _stream


_openai_stream = _openai_compat_stream()


def _count(text: str) -> int:
    from stocks.chat import tokens

    return tokens.count(text)


def _squeeze_tool_results(convo: list[dict], budget: int) -> None:
    """Shrink tool results in place until the conversation fits `budget` tokens.

    The thread was fitted to a backend's per-minute cap before the loop began,
    but every round appends what the tools returned — a few searched pages are
    enough to push the next request past a cap the first one cleared (groq 413,
    8705 asked against 8000). The biggest result is halved first, so the one
    page that is most of the bulk goes before the short answers do.
    """
    from stocks.chat import tokens

    for _ in range(40):
        if tokens.count_messages(convo) <= budget:
            return
        tool = [m for m in convo if m.get("role") == "tool"
                and len(str(m.get("content") or "")) > 400]
        if not tool:
            return  # nothing left to give; the backend decides
        big = max(tool, key=lambda m: len(str(m["content"])))
        text = str(big["content"])
        big["content"] = text[: len(text) // 2].rstrip() + tokens.TRIM_MARK


def _openai_compat_tools(base_url: str | None = None, *, free: bool = False,
                         **client_opts):
    """The same loop over any OpenAI-compatible host: OpenAI itself, and every
    backend in the free chain (groq and openrouter both speak it).

    Tool results go back as one "tool" message per call, each keyed by the
    tool_call_id from the assistant turn — the wire equivalent of Anthropic's
    single user message of tool_result blocks.
    """

    def run(api_key, model, system, messages, tools, execute, rounds,
            cap: int = 0, stop=None):
        import json

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url, **client_opts)
        schema = [{"type": "function",
                   "function": {"name": t.name, "description": t.description,
                                "parameters": t.schema}} for t in tools]
        convo = [{"role": "system", "content": system}] + list(messages)
        schema_tokens = _count(json.dumps(schema)) if cap else 0
        calls: list[ToolCall] = []
        sent: list[list[dict]] = []  # each round's results (`_clear_old_results`)
        text = ""
        for _ in range(max(1, rounds)):
            _clear_old_results(sent)
            if cap:
                _squeeze_tool_results(convo, cap - schema_tokens)
            resp = client.chat.completions.create(
                model=model, max_tokens=MAX_TOKENS, messages=convo,
                tools=cast(Any, schema),
            )
            metering.note_openai(model, getattr(resp, "usage", None), free=free)
            if not resp.choices:
                # OpenRouter answers an upstream failure with HTTP 200 and an
                # "error" object where the choices should be.
                err = (getattr(resp, "model_extra", None) or {}).get("error")
                raise RuntimeError(f"no choices in the reply: {err or 'empty'}")
            msg = resp.choices[0].message
            text = msg.content or ""
            if not msg.tool_calls:
                break
            convo.append(msg.model_dump(exclude_none=True))
            # Only function tools are ever sent, so a custom-tool call (which
            # carries no `.function`) can't be one of ours.
            asked = [tc for tc in msg.tool_calls if tc.type == "function"]
            wanted: list[tuple[str, dict]] = []
            bad: set[int] = set()
            for n, tc in enumerate(asked):
                # Never string-match the serialized arguments: models escape
                # them differently. Bad JSON is the model's error to see, and
                # it is not run: `{}` would fail on the wrong thing.
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except ValueError:
                    args = None
                if not isinstance(args, dict):
                    bad.add(n)
                    obs.warn("llm.malformed_call", tool=tc.function.name,
                             model=model, action="told")
                    continue
                wanted.append((tc.function.name, args))
            ran = iter(zip(wanted, _execute_round(execute, wanted), strict=True))
            batch: list[dict] = []
            for n, tc in enumerate(asked):
                if n in bad:
                    out = BAD_ARGS
                else:
                    (name, args), out = next(ran)
                    calls.append(ToolCall(name, args, out))
                batch.append({"role": "tool", "tool_call_id": tc.id,
                              "content": out or "(no result)"})
            convo.extend(batch)
            sent.append(batch)
            if stop is not None and stop():
                return ToolRun("", calls)
        return ToolRun(text, calls)

    return run


_openai_tools = _openai_compat_tools()


def _openai_error(exc):
    import openai

    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return "chat.invalid_key"
    if isinstance(exc, openai.RateLimitError):
        # OpenAI returns 429 for both rate limits and an exhausted quota.
        code = str(getattr(exc, "code", "") or "")
        no_credit = code == "insufficient_quota" or "quota" in str(exc).lower()
        return "chat.no_credits" if no_credit else "chat.api_error"
    if getattr(exc, "status_code", None) == 503:
        return "chat.provider_busy"  # saturated, not broken (see _gemini_error)
    if isinstance(exc, openai.APIError):
        return "chat.api_error"
    return None


# ------------------------------------------------------------- Gemini (Google)


# A 503 "high demand" from Gemini is a spike, usually gone in a second or two
# (prod: five a week on gemini-flash-latest). One more ask after this pause,
# before anything was shown, beats handing a reader with their own key to the
# free chain, which answered 2-35 s later and with another model.
GEMINI_BUSY_RETRY_S = 1.5

# google-genai sends no timeout of its own (httpx's is set to None), so a hung
# request waits for ever: prod 2026-10-28 13:36, the busy retry held 2.4 min
# until the caller's own deadline cut it. In milliseconds, as the SDK wants;
# it also rides to Google as X-Server-Timeout, so it is the whole answer's
# budget: two minutes, past any wait a reader sits through.
_GEMINI_TIMEOUT_MS = 120_000


# How long a model thinks before it writes, for the calls made inside
# `thinking()`. Gemini's flash thinks at its own default when not told, and
# prod's answers on gemini-flash-latest took 94-164 s against 5-20 s on lite:
# the reasoning, not the reading. "" = the model's own default.
_THINKING: contextvars.ContextVar[str] = contextvars.ContextVar(
    "stocks_llm_thinking", default="")
# Models that answered a thinking level with a 400 (2.5 takes a budget, not a
# level): asked again without one, and not told again in this process.
_NO_THINKING_LEVEL: set[str] = set()


@contextlib.contextmanager
def thinking(level: str) -> Generator[None]:
    """Think at `level` ("minimal", "low", "medium", "high") in the calls
    started in the block, on the providers that can be told (Gemini)."""
    token = _THINKING.set(level)
    try:
        yield
    finally:
        _THINKING.reset(token)


def _gemini_stream(api_key, model, system, messages, thinking=""):
    from google.genai import errors

    if model in _NO_THINKING_LEVEL:
        thinking = ""
    first = True
    try:
        for chunk in _gemini_stream_once(api_key, model, system, messages,
                                         thinking):
            first = False
            yield chunk
        return
    except errors.ClientError as exc:
        if (not first or not thinking or getattr(exc, "code", None) != 400
                or "think" not in str(exc).lower()):
            raise
        _NO_THINKING_LEVEL.add(model)
        obs.warn("llm.gemini_thinking_refused", model=model, thinking=thinking)
        thinking = ""
    except errors.APIError as exc:
        if not first or getattr(exc, "code", None) != 503:
            raise
        obs.warn("llm.gemini_busy_retry", model=model)
        time.sleep(GEMINI_BUSY_RETRY_S)
    yield from _gemini_stream_once(api_key, model, system, messages, thinking)


# Usage fields as Gemini streams them: each chunk may carry its own partial
# count, so the turn's is the largest seen of each, not the last chunk's.
_GEMINI_USAGE = ("prompt_token_count", "cached_content_token_count",
                 "candidates_token_count", "thoughts_token_count")


def _gemini_stream_once(api_key, model, system, messages, thinking=""):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
        timeout=_GEMINI_TIMEOUT_MS))
    # Gemini roles are "user"/"model"; map the assistant turns accordingly.
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]
    stream = client.models.generate_content_stream(
        model=model,
        contents=cast(Any, contents),
        # str(): the SDK turns a str subclass (`Prompt`) into an empty Content,
        # and the model then answered with no persona, rules or book at all.
        config=types.GenerateContentConfig(
            system_instruction=str(system),
            thinking_config=(types.ThinkingConfig(
                thinking_level=cast(Any, thinking.upper()))
                if thinking else None),
        ),
    )
    usage: dict[str, int] = {}
    for chunk in stream:
        if (meta := getattr(chunk, "usage_metadata", None)) is not None:
            for name in _GEMINI_USAGE:
                usage[name] = max(usage.get(name, 0),
                                  int(getattr(meta, name, 0) or 0))
        if chunk.text:
            yield chunk.text
    metering.note_gemini(model, SimpleNamespace(**usage) if usage else None)


def _gemini_error(exc):
    from google.genai import errors

    if isinstance(exc, errors.ClientError):
        code = getattr(exc, "code", None)
        msg = str(exc).lower()
        if code in (401, 403) or "api key" in msg or "api_key" in msg:
            return "chat.invalid_key"
        if code == 429 or "quota" in msg or "billing" in msg:
            return "chat.no_credits"
        return "chat.api_error"
    if isinstance(exc, errors.APIError):
        # 503 UNAVAILABLE "experiencing high demand": the model is saturated,
        # not broken — tell the user it's the provider and that switching
        # helps, instead of the generic "assistant is unavailable".
        if getattr(exc, "code", None) == 503:
            return "chat.provider_busy"
        # 504 DEADLINE_EXCEEDED: the answer outran `_GEMINI_TIMEOUT_MS`, which
        # rides to Google as the server's deadline. Said as the wait it was,
        # not "unavailable": the same question on a lighter model answers.
        if getattr(exc, "code", None) == 504:
            return "chat.provider_slow"
        return "chat.api_error"
    import httpx

    if isinstance(exc, httpx.TimeoutException):  # the same deadline, client side
        return "chat.provider_slow"
    return None


# ------------------------------------------------------------- OpenRouter

# One key, every vendor's models, billed to the reader's own OpenRouter
# credits. It speaks the OpenAI wire format, so the stream and the tool loop
# are OpenAI's with another base_url.
OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def _openrouter_error(exc):
    # 402 is OpenRouter's "out of credits" (or a request priced above what is
    # left). The OpenAI SDK has no class for it and files it as a plain
    # APIStatusError, which _openai_error would call a generic outage.
    if getattr(exc, "status_code", None) == 402:
        return "chat.no_credits"
    return _openai_error(exc)


# ------------------------------------------------------- TopStocks AI (free chain)
# Keyless for the user: a fixed-order chain of free-tier backends billed to the
# operator's keys ([free_llm] in secrets.toml). Each entry is (backend id,
# default model, OpenAI-compatible base_url) — all backends speak the OpenAI
# wire format. The model can be overridden per backend with a "<id>_model"
# secret, so a retired free model is a config change, not a release.

_FREE_BACKEND_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    # groq retired llama-3.3-70b-versatile before 2026-09-01; prod logs through
    # 2026-09-22 show the chain substituting this slug from /models on every
    # boot, so it is the default now. The substitution path still covers the
    # next retirement.
    ("groq", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1"),
    # Checked live 2026-08-31 against each backend's /models and a real
    # completion. openrouter: the google/* free slugs 429 with limit_source
    # "upstream_provider_shared_pool" (Google AI Studio's pool, shared by all
    # OpenRouter users — nothing this account can raise), so the default moved
    # to a non-Google slug that streams today. A retired default is still a
    # config fix — "<id>_model" in [free_llm] overrides these.
    #
    # cerebras left the chain 2026-10-03: every model has answered 402
    # payment_required since 2026-08-31 (free quota is account-level and
    # spent), so it was a dead hop on every fallback, never an answer.
    ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free",
     "https://openrouter.ai/api/v1"),
)


# Further models a backend falls to when its first one is overloaded. An
# OpenRouter free slug is one upstream provider's capacity: nvidia/nemotron
# answers 503 "Service temporarily overloaded" most days, and with a single
# model that was the end of the backend. Ordered, after the "<id>_model" one;
# "<id>_fallback_models" in [free_llm] (comma-separated) replaces the list.
#
# Checked live 2026-10-14: openai/gpt-oss-120b:free and
# meta-llama/llama-3.3-70b-instruct:free went paid-only (404 "unavailable for
# free"); the google/* and poolside free slugs 429 on the shared upstream pool.
# Best answers first. 2026-10-29, a 10k-token prompt: nemotron-3-super-120b
# went paid-only (404) too; dots wrote its first word in 4.5 s; lightning
# reasoned 7 s and wrote nothing, so it stays last.
_FREE_FALLBACK_MODELS: dict[str, tuple[str, ...]] = {
    "openrouter": ("dots-studio/dots-3-note-preview:free",
                   "nvidia/nemotron-3.5-lightning:free"),
}

# Tokens per minute a backend's free tier admits, prompt included. One request
# over it is refused outright — groq answers 413 "Request too large … (TPM):
# Limit 8000" — however idle the minute was, while a chat turn may carry up to
# chat.tokens.MAX_CONTEXT_TOKENS. Overridable with a "<id>_tpm" secret when a
# tier changes; a backend missing here has no cap worth planning around.
_FREE_TPM: dict[str, int] = {"groq": 8000}

# Our count is tiktoken's o200k_base, not the backend's own tokenizer and chat
# template, so plan to this share of the limit.
_TPM_MARGIN = 0.9

# How far a backend's count ran over ours, learned from its 413 ("Limit 8000,
# Requested 8095" for a thread we had put under 7200, prod 2026-10-14). The
# margin above covers prose; a turn heavy with tables and numbers tokenizes
# worse on their side. Kept for the life of the process, only ever raised.
_tpm_skew: dict[str, float] = {}
_REQUESTED = re.compile(r"Limit (\d+), Requested (\d+)")


def _tpm_cap(b: _FreeBackend) -> int:
    """Tokens, by our count, a request to `b` may carry; 0 = uncapped."""
    if not b.tpm:
        return 0
    return int(b.tpm * _TPM_MARGIN / _tpm_skew.get(b.id, 1.0))


def _learn_skew(b: _FreeBackend, exc: Exception, sent: int) -> bool:
    """Record how far over its cap `b` counted a request we sized at `sent`
    tokens. True when the failure was that 413, so a shorter retry can fit."""
    if getattr(exc, "status_code", None) != 413 or not sent:
        return False
    m = _REQUESTED.search(str(exc))
    if not m:
        return False
    skew = int(m.group(2)) / sent
    if skew > _tpm_skew.get(b.id, 1.0):
        _tpm_skew[b.id] = skew
        obs.warn("llm.free.tpm_skew", backend=b.id, skew=round(skew, 3))
    return True

# The SDK's defaults (two retries honouring retry-after, a 600 s timeout) are
# for a caller with one backend. The chain has a next one: groq's 429s ask for
# 4-21 s each, so two retries held a request ~25 s before the fallback got its
# turn, and an OpenRouter free model once took 180 s to read one PDF page
# block. One retry still rides out a short groq window; past that it is the
# next backend's turn. `timeout` is httpx's, per read — a stream that keeps
# producing is never cut.
_FREE_CLIENT: dict[str, Any] = {"max_retries": 1, "timeout": 60.0}


class FreeTierExhausted(Exception):
    """Every configured free backend failed before producing any output."""


@dataclass(frozen=True)
class _FreeBackend:
    id: str
    api_key: str
    model: str
    stream: Callable[[str, str, str, list[dict]], Iterator[str]]
    base_url: str = ""  # for the /models lookup when `model` has been retired
    tpm: int = 0  # tokens per minute the free tier admits; 0 = no cap
    primary: bool = True  # False for a fallback model of the same backend


# Free tiers retire model slugs without notice, and the chain's only symptom is
# a 404 "model does not exist" on every request until an operator edits a
# secret. These let it recover on its own: on a retired-model failure the
# backend's own /models list (every OpenAI-compatible host serves one) picks a
# replacement, and the one that answers is remembered for the rest of the
# process, so the dead slug costs one call per boot rather than one per chat.
_free_live_model: dict[str, str] = {}

# Not chat models — Groq alone serves speech, guard and embedding slugs.
_NON_CHAT_MODEL_HINTS = ("whisper", "tts", "guard", "embed", "rerank", "moderat")

# Substring preferences, best first: hold the tier the retired defaults were
# (a large instruct model) before dropping to the small/fast ones.
_CHAT_MODEL_PREFS = (
    "versatile", "120b", "-70b", "kimi", "qwen3-32b", "maverick", "scout",
    "instant", "20b", "mini",
)


def _retired_model(exc: Exception) -> bool:
    """True when a failure says the *model* is gone rather than the tier being
    rate-limited, out of credit or the key being wrong. OpenRouter's way of
    saying it is a 404 "This model is unavailable for free" once a :free slug
    goes paid-only."""
    if getattr(exc, "status_code", None) not in (None, 404):
        return False
    text = str(exc).lower()
    return ("model_not_found" in text or "does not exist" in text
            or "unavailable for free" in text)


# Slugs that answered "retired", per backend, for the life of the process: a
# fallback model that went paid costs one call per boot, not one per chat.
_free_gone: set[tuple[str, str]] = set()


def _pick_chat_model(ids: list[str]) -> str | None:
    chat = [m for m in sorted(ids)
            if not any(h in m.lower() for h in _NON_CHAT_MODEL_HINTS)]
    for pref in _CHAT_MODEL_PREFS:
        for mid in chat:
            if pref in mid.lower():
                return mid
    return chat[0] if chat else None


def _live_model(b: _FreeBackend) -> str | None:
    """A model this backend actually serves right now, or None if it won't say.

    OpenRouter lists every paid model beside the free ones; a :free slug is
    only ever replaced by another :free slug not already known to be gone."""
    from openai import OpenAI

    try:
        client = OpenAI(api_key=b.api_key, base_url=b.base_url or None)
        ids = [m.id for m in client.models.list()]
        if b.model.endswith(":free"):
            ids = [i for i in ids
                   if i.endswith(":free") and (b.id, i) not in _free_gone]
        return _pick_chat_model(ids)
    except Exception as exc:  # a backend that hides /models keeps its retired slug
        obs.warn("llm.free.model_list_failed", backend=b.id,
                 error_type=type(exc).__name__, error=str(exc)[:200])
        return None


# A backend that answered 402 has no free quota left (cerebras, 2026-08-31) and
# will keep saying so until an operator tops it up: every hop to it is a wasted
# call. Remembered for the life of the process, like `_rejected` is for a key —
# a deploy is the retry.
_free_dead: set[str] = set()

# groq's 429 says how long to wait ("Please try again in 1.6125s"). Up to this
# is worth sitting out once on the same backend; past it, the next one's turn.
_MAX_RETRY_WAIT_S = 5.0
_RETRY_IN = re.compile(
    r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)\s*(ms|s)\b", re.I)

_sleep = time.sleep  # a name of its own so tests need not wait
_clock = time.perf_counter  # and one tests can move by hand

# Past the short wait, a 429 rests its backend for the wait it named (capped):
# every turn in that window would otherwise pay the SDK's own retry-after on it
# before the next backend got its turn. Per process, like `_free_dead`.
_free_resting: dict[str, float] = {}  # backend id -> monotonic time it lifts
_MAX_REST_S = 60.0


def _retry_after(exc: Exception) -> float | None:
    """Seconds a 429 asked us to wait ("1.6s", "307ms", "6m7.3s"), or None."""
    if getattr(exc, "status_code", None) != 429:
        return None
    m = _RETRY_IN.search(str(exc))
    if not m:
        return None
    secs = float(m.group(2)) / (1000 if m.group(3).lower() == "ms" else 1)
    return secs + 60 * int(m.group(1) or 0)


def _short_wait(exc: Exception) -> float | None:
    """Seconds a rate-limited backend asked us to wait, when that is short."""
    secs = _retry_after(exc)
    return secs + 0.25 if secs is not None and secs <= _MAX_RETRY_WAIT_S else None


def _note_dead(b: _FreeBackend, exc: Exception) -> None:
    if getattr(exc, "status_code", None) == 402 and b.id not in _free_dead:
        _free_dead.add(b.id)
        obs.error("llm.free.backend_dead", exc, backend=b.id)


def _note_rest(b: _FreeBackend, exc: Exception) -> None:
    """A 429 the chain moves on from: skip `b` until the wait it named."""
    secs = _retry_after(exc)
    if secs is not None and secs > _MAX_RETRY_WAIT_S:
        _free_resting[b.id] = time.monotonic() + min(secs, _MAX_REST_S)
        obs.warn("llm.free.backend_resting", backend=b.id,
                 seconds=round(secs, 1))


def _resting(b: _FreeBackend) -> bool:
    if _slow(b):
        return True
    until = _free_resting.get(b.id)
    if until is None:
        return False
    if time.monotonic() >= until:
        _free_resting.pop(b.id, None)
        return False
    return True


# How long a free model may think before its first word while another one is
# still behind it in the chain. The 200 arrives at once and reasoning frames
# keep the per-read timeout alive, so without this nemotron-3-ultra held answers
# 59-242 s in prod (2026-10-26/28) with dots-3 a 5 s answer away. groq writes in
# under 2 s and dots in ~5 s on a 10k-token prompt.
_FIRST_TEXT_S = 20.0

# A model cut for that sits out this long, per backend and model — the shared
# free pool that made it slow does not clear in a turn. Per process.
_free_slow: dict[tuple[str, str], float] = {}  # (backend, model) -> lifts at
_SLOW_REST_S = 600.0


class _Slow(TimeoutError):
    """A free model that wrote nothing within `_FIRST_TEXT_S`."""


def _slow(b: _FreeBackend) -> bool:
    until = _free_slow.get((b.id, b.model))
    if until is None:
        return False
    if time.monotonic() >= until:
        _free_slow.pop((b.id, b.model), None)
        return False
    return True


def _skip(plan: list, attempt: int) -> bool:
    """Whether the chain passes over `plan[attempt]`: dead, or resting while a
    later entry is awake — the last one awake is tried even resting, since a
    wait beats no answer."""
    b = plan[attempt][0]
    if b.id in _free_dead:
        return True
    return _resting(b) and any(
        n.id not in _free_dead and not _resting(n) for n, _ in plan[attempt + 1:])


def _free_secrets() -> dict:
    cfg = secrets_env.section("free_llm")
    # Env overlay so headless jobs (GitHub Actions digest) can run the chain
    # without a secrets.toml: FREE_LLM_GROQ, FREE_LLM_GROQ_MODEL, ...
    import os

    for bid, _model, _url in _FREE_BACKEND_DEFAULTS:
        for k in (bid, f"{bid}_model", f"{bid}_tpm", f"{bid}_fallback_models"):
            env = os.environ.get(f"FREE_LLM_{k.upper()}")
            if env:
                cfg[k] = env
    return cfg


def free_secret(name: str) -> str:
    """One [free_llm] value, stripped, with the same FREE_LLM_* env overlay.

    The chat chain is no longer the only thing these keys fund — the
    assistant's speech-to-text (web/stt.py) rides the groq key too — so the
    section gets one public reader instead of a second copy of the secrets
    lookup and its env fallback. Unlike _free_secrets this takes any name, so
    a key the chain itself never reads ("groq_stt_model") still honours its
    environment variable.
    """
    import os

    env = os.environ.get(f"FREE_LLM_{name.upper()}")
    if env:
        return env.strip()
    return str(_free_secrets().get(name) or "").strip()


def _free_backends() -> list[_FreeBackend]:
    """The configured slice of the chain, in fixed fallback order.

    A backend joins only when its [free_llm] key is set and its SDK is
    installed, so an unconfigured deploy simply has no free provider."""
    cfg = _free_secrets()
    if importlib.util.find_spec("openai") is None:
        return []
    out = []
    for bid, default_model, base_url in _FREE_BACKEND_DEFAULTS:
        key = (cfg.get(bid) or "").strip()
        if not key or bid in _free_dead:
            continue
        model = (_free_live_model.get(bid)
                 or cfg.get(f"{bid}_model", default_model))
        tried = {model}
        try:
            tpm = int(cfg.get(f"{bid}_tpm") or _FREE_TPM.get(bid, 0))
        except (TypeError, ValueError):
            tpm = _FREE_TPM.get(bid, 0)
        stream = _openai_compat_stream(base_url, free=True, **_FREE_CLIENT)
        # A gone primary stays in: its failure is what asks /models for a
        # replacement. Gone fallbacks are only dead hops.
        out.append(_FreeBackend(bid, key, model, stream, base_url, tpm))
        extra = cfg.get(f"{bid}_fallback_models")
        more = (tuple(m.strip() for m in str(extra).split(","))
                if extra is not None else _FREE_FALLBACK_MODELS.get(bid, ()))
        for alt in more:
            if alt and alt not in tried and (bid, alt) not in _free_gone:
                tried.add(alt)
                out.append(_FreeBackend(bid, key, alt, stream, base_url, tpm,
                                        primary=False))
    return out


def _free_plan(backends: list[_FreeBackend], system: str, messages: list[dict],
               extra: int = 0) -> list[tuple[_FreeBackend, list[dict]]]:
    """Each backend with the thread it can take, in the order to try them.

    A request over a backend's per-minute cap is refused outright, so sending it
    the whole thread wastes the hop. Backends it fits go first, in chain order,
    with the thread untouched; those it does not fit go last, with the thread cut
    to their cap by chat.tokens.fit — oldest turns first, then the tail of the
    newest, where pasted pages and quotes live. A fast backend that has
    forgotten half the conversation is the last resort, not the first. One whose
    cap the system prompt alone overruns cannot answer at all and is left out.

    `extra` is what rides the request besides system and messages — the tool
    schemas, for the tool loop.
    """
    from stocks.chat import tokens

    fits: list[tuple[_FreeBackend, list[dict]]] = []
    over: list[tuple[_FreeBackend, list[dict]]] = []
    need = None
    for b in backends:
        if not b.tpm:
            fits.append((b, messages))
            continue
        if need is None:
            need = tokens.count(system) + tokens.count_messages(messages) + extra
        cap = _tpm_cap(b)
        budget = cap - extra  # what system and thread may take between them
        if need <= cap:
            fits.append((b, messages))
        elif tokens.count(system) >= budget:
            obs.warn("llm.free.over_tpm", backend=b.id, tokens=need, tpm=b.tpm,
                     action="skipped")
        else:
            obs.warn("llm.free.over_tpm", backend=b.id, tokens=need, tpm=b.tpm,
                     action="trimmed")
            over.append((b, tokens.fit(messages, system=system, budget=budget)))
    return fits + over


class _NoText(RuntimeError):
    """A backend that answered 200 and streamed nothing."""


def _sent(system: str, thread: list[dict]) -> int:
    from stocks.chat import tokens

    return tokens.count(system) + tokens.count_messages(thread)


def _refit(b: _FreeBackend, system: str, messages: list[dict],
           extra: int = 0) -> list[dict] | None:
    """`messages` cut to `b`'s cap as now known, or None when the system prompt
    alone leaves no room."""
    from stocks.chat import tokens

    budget = _tpm_cap(b) - extra
    if tokens.count(system) >= budget:
        return None
    return tokens.fit(messages, system=system, budget=budget)


def _free_stream(api_key, model, system, messages):
    del api_key, model  # the chain supplies its own key and model per backend
    backends = _free_backends()
    if not backends:
        raise FreeTierExhausted("no free backend configured")
    started = False
    plan = _free_plan(backends, system, messages)
    refitted: set[str] = set()
    attempt = -1
    while (attempt := attempt + 1) < len(plan):
        b, thread = plan[attempt]
        if _skip(plan, attempt):
            continue
        # Grows by at most one entry: a retired slug appends the replacement
        # /models named, so the same backend gets a second shot before the
        # chain moves on. A short rate-limit wait, or an empty answer, re-queues
        # the same model once.
        candidates = [b.model]
        waited = False
        while candidates:
            model = candidates.pop(0)
            t0 = _clock()
            # The last one left may think as long as it likes: a slow answer
            # beats none.
            late = (t0 + _FIRST_TEXT_S
                    if candidates or attempt + 1 < len(plan) else None)
            first_ms = chunks = None
            try:
                got = False
                chunks = b.stream(b.api_key, model, system, thread)
                for chunk in chunks:
                    if isinstance(chunk, Idle):
                        if not got and late and _clock() > late:
                            _free_slow[(b.id, model)] = (time.monotonic()
                                                         + _SLOW_REST_S)
                            raise _Slow(f"no text after {_FIRST_TEXT_S:.0f} s")
                        continue
                    if first_ms is None:
                        first_ms = round((_clock() - t0) * 1000)
                    started = got = True
                    yield chunk
                if not got:
                    # OpenRouter's upstream failure can arrive as a 200 with no
                    # choices, which streams to nothing: not an answer.
                    raise _NoText("the backend streamed no text")
                if model != b.model and b.primary:
                    _free_live_model[b.id] = model  # proven: skip the dead slug
                obs.event("llm.free.answered", backend=b.id, model=model,
                          attempt=attempt, first_ms=first_ms,
                          duration_ms=round((_clock() - t0) * 1000))
                return
            except Exception as exc:
                if close := getattr(chunks, "close", None):
                    close()  # a dropped stream must not hold its connection
                if started:
                    obs.error("llm.free.mid_answer_failure", exc, backend=b.id,
                              model=model)
                    raise  # mid-answer failure: text already on screen, can't switch
                # rate limit / bad key / retired model — try the next one, but say
                # which one died and why: this is the operator's only signal that a
                # free tier went paid or a model was retired. Structured, because
                # "which backend has been failing all week" is a query, not a read:
                #   stocks logs stats --event llm.free.backend_failed --by backend
                obs.warn("llm.free.backend_failed", backend=b.id, model=model,
                         attempt=attempt, error_type=type(exc).__name__,
                         error=str(exc)[:300],
                         status=getattr(exc, "status_code", None))
                _note_dead(b, exc)
                _note_rest(b, exc)
                if (b.id not in refitted
                        and _learn_skew(b, exc, _sent(system, thread))):
                    # Their count ran over ours: the same backend, the thread
                    # cut to the corrected cap, after every other one has had
                    # its turn with the whole of it.
                    refitted.add(b.id)
                    if (cut := _refit(b, system, messages)) is not None:
                        plan.append((b, cut))
                    break
                if not waited and isinstance(exc, _NoText):
                    # Usually a one-off on the shared free pool (3 tries of
                    # nemotron-3-ultra on 2026-10-14: 1 answer, 2 empties).
                    waited = True
                    candidates.insert(0, model)
                    continue
                wait = None if waited else _short_wait(exc)
                if wait is not None:
                    waited = True
                    _sleep(wait)
                    candidates.insert(0, model)
                    continue
                if not _retired_model(exc):
                    break
                _free_gone.add((b.id, model))
                if not b.primary:
                    break  # the primary's /models lookup already covers it
                alt = _live_model(b)
                if not alt or alt == model:
                    break
                obs.warn("llm.free.model_substituted", backend=b.id,
                         retired=model, model=alt)
                candidates.append(alt)
    obs.error("llm.free.exhausted", backends=[b.id for b in backends])
    raise FreeTierExhausted("all free backends failed")


# What a backend says when the model wrote a tool call it could not parse:
# Groq answers 400 "tool_use_failed" ("Failed to call a function. Please
# adjust your prompt."). The same request usually parses on a second try.
_MALFORMED = ("tool_use_failed", "failed to call a function")


def _malformed(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) not in (None, 400):
        return False
    text = str(exc).lower()
    return any(m in text for m in _MALFORMED)


def _free_tools(api_key, model, system, messages, tools, execute, rounds,
                stop=None):
    """The chain again, for the tool loop: first backend that gets through wins.

    Simpler than _free_stream on purpose — nothing has been shown to the user
    yet, so any failure (rate limit, a backend whose model has no tool support,
    a retired slug) is just the next backend's turn. When they all refuse, the
    caller falls back to the fixed pre-flight, so this raising is not the end of
    the answer.
    """
    del api_key, model  # the chain supplies its own key and model per backend
    backends = _free_backends()
    if not backends:
        raise FreeTierExhausted("no free backend configured")
    import json

    from stocks.chat import tokens

    schema = tokens.count(json.dumps(
        [{"name": t.name, "description": t.description, "parameters": t.schema}
         for t in tools]))
    plan = _free_plan(backends, system, messages, extra=schema)
    refitted: set[str] = set()
    attempt = -1
    while (attempt := attempt + 1) < len(plan):
        b, thread = plan[attempt]
        if _skip(plan, attempt):
            continue
        cap = _tpm_cap(b)
        for retry in range(2):
            try:
                return _openai_compat_tools(b.base_url or None, free=True,
                                            **_FREE_CLIENT)(
                    b.api_key, b.model, system, thread, tools, execute, rounds,
                    cap, stop=stop)
            except Exception as exc:
                obs.warn("llm.free.tools_failed", backend=b.id, model=b.model,
                         attempt=attempt, error_type=type(exc).__name__,
                         error=str(exc)[:300],
                         status=getattr(exc, "status_code", None))
                _note_dead(b, exc)
                _note_rest(b, exc)
                # Each round is squeezed under `cap`, and the one that failed
                # may be a later, fuller one than the thread: `cap` is the
                # nearest thing to what was sent, and errs to a smaller skew.
                if b.id not in refitted and _learn_skew(b, exc, cap):
                    refitted.add(b.id)
                    if (cut := _refit(b, system, messages, schema)) is not None:
                        plan.append((b, cut))
                    break
                if _retired_model(exc):
                    _free_gone.add((b.id, b.model))
                    break
                if retry == 0 and _malformed(exc):
                    # Once, on the same backend: a call it could not parse is
                    # the model's slip, not the backend's limit. The rounds
                    # already run replay from the dispatcher's memory
                    # (agent._Budget), so the second try costs no fetches.
                    obs.warn("llm.malformed_call", backend=b.id, model=b.model,
                             action="retry")
                    continue
                wait = _short_wait(exc) if retry == 0 else None
                if wait is None:
                    break
                _sleep(wait)
    raise FreeTierExhausted("no free backend ran the tool loop")


def _free_error(exc):
    if isinstance(exc, FreeTierExhausted):
        return "chat.free_exhausted"
    # Backends are operator-configured; nothing here is actionable by the user.
    return "chat.api_error"


# ------------------------------------------------------------- model lists
# What the account's own key can reach, asked of the vendor rather than kept
# here: the curated tuples in the registry are a starting point, and each
# vendor ships models faster than a release could add them. Speech, image,
# embedding and moderation models share these listings and cannot answer a
# chat turn, so they are filtered out by name.

_NOT_CHAT = ("whisper", "tts", "audio", "realtime", "transcribe", "image",
             "dall-e", "embed", "moderat", "guard", "rerank", "search",
             "computer-use", "veo", "imagen", "aqa")


def _chat_only(ids) -> list[str]:
    return sorted({i for i in ids if i and not any(h in i.lower() for h in _NOT_CHAT)})


def _anthropic_models(api_key: str) -> list[str]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    return _chat_only(m.id for m in client.models.list(limit=1000))


def _openai_models(api_key: str) -> list[str]:
    from openai import OpenAI

    ids = (m.id for m in OpenAI(api_key=api_key).models.list())
    # The listing also carries babbage/davinci completions and fine-tune bases.
    return _chat_only(i for i in ids if re.match(r"(gpt-|chatgpt-|o\d)", i))


def _gemini_models(api_key: str) -> list[str]:
    from google import genai

    out = []
    for m in genai.Client(api_key=api_key).models.list():
        actions = getattr(m, "supported_actions", None) or []
        name = (getattr(m, "name", "") or "").removeprefix("models/")
        if "gemini" in name and "generateContent" in actions:
            out.append(name)
    return _chat_only(out)


def _openrouter_models(api_key: str) -> list[str]:
    # OpenRouter's catalogue is public; the key is sent anyway so an account
    # with provider restrictions sees its own list.
    from openai import OpenAI

    client = OpenAI(api_key=api_key or "-", base_url=OPENROUTER_BASE)
    return _chat_only(m.id for m in client.models.list())


# ------------------------------------------------------------- registry

PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider(
            "free", "TopStocks AI",
            ("auto",),  # the chain picks the backend; no user-facing model list
            "", "",  # keyless: no placeholder, no console link
            "openai", _free_stream, _free_error,
            needs_key=False,
            _available=lambda: bool(_free_backends()),
            _tools=_free_tools,
        ),
        Provider(
            "anthropic", "Claude",
            ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"),
            "sk-ant-...", "https://console.anthropic.com/settings/keys",
            "anthropic", _anthropic_stream, _anthropic_error,
            _tools=_anthropic_tools,
            classifier_model="claude-haiku-4-5",
            _list_models=_anthropic_models,
            domain="claude.ai",
        ),
        Provider(
            "openai", "ChatGPT",
            ("gpt-5", "gpt-4o", "gpt-4o-mini"),
            "sk-...", "https://platform.openai.com/api-keys",
            "openai", _openai_stream, _openai_error,
            _tools=_openai_tools,
            classifier_model="gpt-4o-mini",
            _list_models=_openai_models,
            domain="chatgpt.com",
        ),
        Provider(
            "gemini", "Gemini",
            # Rolling "-latest" aliases so the list can't rot when Google
            # retires a pinned version (2.5-flash/2.5-pro dropped for new keys).
            ("gemini-flash-latest", "gemini-3.6-flash", "gemini-flash-lite-latest"),
            "AQ... or AIza...", "https://aistudio.google.com/apikey",
            # No _tools: google-genai's function calling has its own message
            # shape, and Gemini keeps the fixed pre-flight until it is written
            # and tested against a live key. Everything else on this page works.
            "google.genai", _gemini_stream, _gemini_error,
            classifier_model="gemini-flash-lite-latest",
            _list_models=_gemini_models,
            domain="gemini.google.com",
            _thinking=True,
        ),
        Provider(
            "openrouter", "OpenRouter",
            # Slugs checked live against openrouter.ai/api/v1/models on
            # 2026-10-01, all with tool support. Pinned versions rot, so the
            # list ends on the auto router, which never does.
            ("anthropic/claude-sonnet-5.5", "openai/gpt-5.6-sol",
             "google/gemini-3.8-flash", "deepseek/deepseek-v4.1-flash",
             "openrouter/auto"),
            "sk-or-v1-...", "https://openrouter.ai/settings/keys",
            "openai", _openai_compat_stream(OPENROUTER_BASE), _openrouter_error,
            _tools=_openai_compat_tools(OPENROUTER_BASE),
            classifier_model="google/gemini-3.5-flash-lite",
            _list_models=_openrouter_models,
            public_models=True,
            domain="openrouter.ai",
            connect_url="https://openrouter.ai/auth",
            connect_token_url=f"{OPENROUTER_BASE}/auth/keys",
        ),
    )
}

DEFAULT_PROVIDER = "anthropic"  # BYOK default when the free chain is not deployed


def default_provider_id() -> str:
    """Free chain when the deploy configures it (zero-setup chat), else BYOK."""
    return "free" if PROVIDERS["free"].available() else DEFAULT_PROVIDER


def available_providers() -> list[Provider]:
    """Usable providers, registry order (TopStocks AI, Claude, ChatGPT, Gemini,
    OpenRouter)."""
    return [p for p in PROVIDERS.values() if p.available()]


# ------------------------------------------------------------- rejected keys

# A key the provider has refused (401/403) is remembered for a while, by
# fingerprint, so the turns after it stop spending their research on it. The
# answer always fell through to the next candidate on a dead key; the cheap
# calls before it — the tool-using lookup, the web planner, the skill router —
# all ran on the head of the chain and simply failed, so a reader whose stored
# ChatGPT key had gone bad got answers built with no search at all, every turn,
# with nothing on screen saying why. Process-local and timed: a key fixed in
# the provider's console works again without anyone telling this process.
REJECTED_TTL_S = 15 * 60
_rejected: dict[str, float] = {}


def _fingerprint(provider_id: str, key: str) -> str:
    import hashlib

    return hashlib.sha256(f"{provider_id}\0{key}".encode()).hexdigest()[:16]


def note_failure(provider: Provider, key: str, exc: Exception) -> None:
    """Remember `key` as refused when `exc` says the provider refused it."""
    if not key or not getattr(provider, "needs_key", True):
        return
    try:
        refused = provider.error_key(exc) == "chat.invalid_key"
    except Exception:  # an SDK missing on this host: not a verdict on the key
        return
    if refused:
        _rejected[_fingerprint(provider.id, key)] = time.monotonic()


def rejected(provider: Provider, key: str) -> bool:
    """Whether `key` was refused by `provider` within REJECTED_TTL_S."""
    if not key:
        return False
    fp = _fingerprint(provider.id, key)
    at = _rejected.get(fp)
    if at is None:
        return False
    if time.monotonic() - at > REJECTED_TTL_S:
        _rejected.pop(fp, None)
        return False
    return True
