"""Structured replies from the models: shaped by BAML, judged by Python.

Every call that wants JSON back — the chat's three classifiers (skill routing
in web/chat_skills.py, web planning in web/chat_web.py, action detection in
chat/tools.py), the importer's column mapping, statement reading and symbol
resolution (portfolio/), the sector screen's peers, the Home briefing and
the chat's memory extraction (chat/learnings.py) — goes through here, in two
layers:

**Shape** is BAML's (`baml_src/`, generated into `stocks.baml_client`). Each
call is a BAML function whose return type is the reply's schema: `render`
turns the caller's instructions into a prompt that ends with that schema
spelled out, and `parse` reads the reply with BAML's schema-aligned parser,
which shrugs off what small free models actually send — prose around the
object, code fences, a trailing comma, unquoted keys, a lone string where a
list was asked for. Those used to cost a repair call or the whole answer. A
reply cut off before its JSON closes is still refused, as json.loads did.

**Rules** stay in Python: the pydantic contracts and parsers each caller
already had (known skill ids, symbol shapes, ledger actions, audited figures).
BAML hands them plain dicts and never decides what a value means.

BAML never sends anything. The prompt it renders goes out through
web.llm.Provider (or chat.engine.complete_attempts), which owns the free
chain, BYOK keys, quotas, prompt caching and logs — `baml_src/clients.baml`
points at an unroutable address to keep it that way.

Contracts are pydantic models, which buys the distinction the callers actually
need: "the model answered off-contract" (`OffContract`, so fall back) and "the
model answered, and the answer is empty" (a valid contract holding an empty
list, so obey it) stop being the same value. Every rejection is logged as
`llm.off_contract` with the function and the reason, under whatever provider,
model and attempt the caller bound with `obs.context`.

Errors are raised, not swallowed: the caller decides what a dead model costs.
A provider/network exception propagates untouched (nothing to repair);
`OffContract` means every attempt came back unusable.

Streamlit-free, like the callers it serves.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, ValidationError

from stocks import obs

if TYPE_CHECKING:
    from stocks.web.llm import Provider

# The repair turn. Deliberately not a restatement of the contract — the
# original system prompt (schema included) is sent again with it, so
# repeating the rules would only add tokens and room to contradict them.
_REPAIR = (
    "That reply was rejected: {error}\n"
    "Reply again with ONLY the JSON object the instructions describe — no "
    "prose, no explanation, no code fences."
)

# What the parser makes of an object it could not fit anywhere: a class with
# one list field takes the whole reply as that list's only element, rendered
# as `{key: value}` text — `{"peers": [...]}` becomes symbols=["{peers: …}"].
_STRINGIFIED = re.compile(r"^\s*\{.*\}\s*$", re.S)

# A bare value right before a trailing comma that closes its object or list:
# `"fee": null,}`, `"shares": 10,]`. The parser keeps the comma as part of the
# value and, wherever a string is allowed, hands back the text "null," or
# "10," — a headline reading "null,", a share count float() refuses. Quoted
# values are unaffected, and so is the same comma followed by a space.
_BARE_TRAILING = re.compile(r"([\w.+-])(\s*),(\s*[}\]])")


def _cut_off(raw: str) -> bool:
    """Whether the reply's JSON never closes: the model ran out of tokens
    mid-answer. The parser would close it and hand back what was there — a
    memory cut at "retire at 5", a share count missing its last digit — and
    a value cut short is a wrong value, not a sloppy one. json.loads refused
    these; so does this. Only double-quoted strings are tracked: they are
    what a cut-off reply is cut inside of."""
    starts = [i for i in (raw.find("{"), raw.find("[")) if i >= 0]
    if not starts:
        return False
    depth, quoted, escaped = 0, False, False
    for char in raw[min(starts):]:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth <= 0:
                return False
    return True


class Contract(BaseModel):
    """Base for the JSON shapes the models must answer in.

    ``extra="ignore"`` because a model volunteering a "reasoning" field is not
    a violation worth a second call: unknown *fields* are noise, unknown
    *values* are what the subclasses' validators reject.
    """

    model_config = ConfigDict(extra="ignore")


class OffContract(ValueError):
    """The model replied, but not in the requested shape (twice, if repaired).

    Carries the offending reply in `raw` — a caller with a looser last-resort
    reading of a reply (chat_skills scans prose for known skill ids) needs the
    text, not just the verdict.
    """

    def __init__(self, reason: str, raw: str = ""):
        super().__init__(reason)
        self.raw = raw


def _client():
    # Deferred: the generated client builds BAML's native runtime on import,
    # which the paths that never ask a model for JSON should not pay for.
    from stocks.baml_client import b

    return b


def render(fn: str, instructions: str, user: str) -> tuple[str, list[dict]]:
    """BAML function `fn`'s prompt as (system, messages) for Provider.complete.

    `instructions` is the caller's system prompt without any JSON shape in
    it — the schema BAML derives from `fn`'s return type is appended — and
    `user` the input. Content comes back as plain strings, the only form every
    provider in web/llm.py accepts.
    """
    request = getattr(_client().request, fn)(instructions, user)
    system: list[str] = []
    messages: list[dict] = []
    for message in request.body.json()["messages"]:
        content = message["content"]
        if not isinstance(content, str):
            content = "".join(part.get("text", "") for part in content)
        if message["role"] == "system":
            system.append(content.strip())
        else:
            messages.append({"role": message["role"], "content": content.strip()})
    return "\n\n".join(system), messages


def _plain(value: Any, raw: str) -> Any:
    """A parsed BAML value as the JSON-ish data the Python rules read.

    Fields the reply left out are dropped rather than kept as None, so a
    contract's defaults apply exactly as they did to a hand-parsed dict. Enum
    members become their lowercase wire spelling ("Above" -> "above"). An
    object stringified into a text field means the reply did not fit the
    schema at all, which is OffContract, not a value.
    """
    if isinstance(value, BaseModel):
        return {
            name: _plain(item, raw)
            for name, item in value
            if item is not None
        }
    if isinstance(value, Enum):
        return str(value.value).lower()
    if isinstance(value, dict):
        return {key: _plain(item, raw) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item, raw) for item in value]
    if isinstance(value, str) and _STRINGIFIED.match(value):
        raise OffContract("the reply's fields do not match the requested shape", raw)
    return value


def _rejected(fn: str, reason: str, raw: str) -> OffContract:
    obs.warn("llm.off_contract", fn=fn, reason=reason[:200], parser="baml")
    return OffContract(reason, raw)


def parse(raw: str, fn: str) -> dict:
    """The reply to BAML function `fn`, as plain data, or OffContract.

    A class-typed reply comes back as a dict holding only the fields the
    model filled in; a map-typed one as the map. A reply with no object in
    it at all is rejected even when every field is optional — prose is not
    the same answer as `{}`.
    """
    from baml_py.errors import BamlError

    if _cut_off(raw or ""):
        raise _rejected(fn, "the reply was cut off before its JSON closed", raw)
    try:
        parsed = getattr(_client().parse, fn)(_BARE_TRAILING.sub(r"\1\2\3", raw or ""))
    except BamlError as exc:
        # Not BAML's own message: it quotes the reply, which can be the
        # user's statement read back, and neither the log nor the repair
        # turn should carry that.
        reason = (
            "the reply is not the requested JSON"
            if "{" in (raw or "")
            else "no JSON object in the reply"
        )
        raise _rejected(fn, reason, raw) from exc
    try:
        data = _plain(parsed, raw)
    except OffContract as exc:
        raise _rejected(fn, str(exc), raw) from exc
    if isinstance(parsed, BaseModel) and not data and "{" not in (raw or ""):
        raise _rejected(fn, "no JSON object in the reply", raw)
    return data


def decode[C: Contract](raw: str, fn: str, schema: type[C]) -> C:
    """The reply to `fn` as `schema`, or OffContract carrying why it was rejected.

    The message is what gets fed back to the model on the repair turn, so it
    says what is wrong in the model's own terms (missing field, bad value) —
    pydantic's error text already does that better than a hand-written one.
    """
    data = parse(raw, fn)
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise _rejected(fn, _why(exc), raw) from exc


def _why(exc: ValidationError) -> str:
    """A pydantic error as one short line the model can act on."""
    parts = []
    for err in exc.errors()[:3]:
        where = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{where}: {err['msg']}")
    return "; ".join(parts)


def ask[C: Contract](
    provider: Provider,
    api_key: str,
    fn: str,
    system: str,
    user: str,
    schema: type[C],
    *,
    model: str = "",
    repair: bool = True,
) -> C:
    """One call to BAML function `fn` answered as `schema`, repaired once.

    Runs on the provider's cheapest model (`classifier_model`) unless `model`
    says otherwise. The repair turn costs a second cheap call, but only on the
    replies that were going to be thrown away anyway — a first-try success,
    which is the common case, spends nothing extra.

    Raises OffContract when both tries are unusable, and lets the provider's
    own exceptions through: a rate limit is not a contract problem, and the
    caller (heuristics, previous turn's skills, no action) already knows what
    to do about it.
    """
    picked = model or provider.classifier_model
    where = {"provider": getattr(provider, "id", ""), "model": picked}
    system, messages = render(fn, system, user)
    with obs.context(**where, attempt=1):
        raw = provider.complete(api_key, picked, system, messages)
        try:
            return decode(raw, fn, schema)
        except OffContract as exc:
            if not repair:
                raise
            why = str(exc)
    with obs.context(**where, attempt=2):
        second = provider.complete(
            api_key,
            picked,
            system,
            messages
            + [
                {"role": "assistant", "content": (raw or "").strip()[:500] or "(empty)"},
                {"role": "user", "content": _REPAIR.format(error=why)},
            ],
        )
        return decode(second, fn, schema)
