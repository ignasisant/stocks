"""Answer text cleaned before it is stored: citation marks, tool calls
written as text, markdown left open.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from stocks import obs
from stocks.chat import (
    toolbox,
)

if TYPE_CHECKING:

    from stocks.web.llm import Provider


# gpt-oss cites as "【2†L13-L17】", pointers into a browser it does not have
# here; the reader sees noise. The panel drops them while it streams
# (chat/markdown.tsx), this keeps them out of what is stored and sent.
_CITE_MARK = re.compile(r" ?【[^】\n]*】")


def strip_cite_marks(text: str) -> str:
    return _CITE_MARK.sub("", text)


# A free model handed its research sometimes answers by asking for more, in
# its own syntax: "{{search_web(query: …)}}", "<function=…>", "[TOOL_CALLS]".
# The writing step has no tools, so that text reached the reader as the whole
# answer. A call is scrubbed out of what is stored; an answer that was nothing
# else is no answer, and the next provider is asked.
_TOOL_NAMES = "|".join(sorted(map(re.escape, toolbox.TOOLS), key=len, reverse=True))
_WRITTEN_CALL = re.compile(
    rf"\{{\{{\s*(?:{_TOOL_NAMES})\s*\(.*?\)\s*\}}\}}"
    r"|<(?:function|tool_call)\b[^>]*>.*?(?:</(?:function|tool_call)>|$)"
    r"|\[TOOL_CALLS\].*?$"
    rf"|^[ \t]*`?(?:{_TOOL_NAMES})\((?:[^()\n]|\([^()\n]*\))*\)`?[ \t]*$",
    re.S | re.M,
)
_CALL_OPENERS = ("{{", "<function", "<tool_call", "[TOOL_CALLS]",
                 *(f"{name}(" for name in toolbox.TOOLS))
# How much of an answer's start is held back while it may still be a call.
CALL_HOLD_CHARS = 600


def scrub_written_calls(text: str) -> str:
    """The answer without the tool calls the model wrote out as text."""
    if not _WRITTEN_CALL.search(text):
        return text
    return re.sub(r"\n{3,}", "\n\n", _WRITTEN_CALL.sub("", text)).strip()


def _may_open_call(text: str) -> bool:
    """Whether an answer's first words could still be a written tool call."""
    head = text.lstrip()
    return any(o.startswith(head) or head.startswith(o) for o in _CALL_OPENERS)


def _only_calls(text: str, provider: Provider, model: str) -> bool:
    """A reply that was nothing but written tool calls, logged as such."""
    if not text or scrub_written_calls(text):
        return False
    obs.warn("chat.written_tool_call", provider=provider.id, model=model)
    return True


def close_markdown(text: str) -> str:
    """A half-written answer made whole enough to render.

    The tail a model stopped in the middle of is the only thing that can be
    open: a code fence, a link, an emphasis mark, a table row. The fence is
    closed, a dangling `[label](partial` or last unfinished table row is
    dropped, and an odd `**` is paired, so the reader never sees raw markdown.
    """
    out = text.rstrip()
    if out.count("```") % 2:
        return out + "\n```"
    out = re.sub(r"\[[^\]\n]*\]\([^)\n]*$", "", out).rstrip()
    out = re.sub(r"\[[^\]\n]*$", "", out).rstrip()
    lines = out.split("\n")
    last = lines[-1].strip()
    if last.startswith("|") and not last.endswith("|"):
        lines.pop()
        out = "\n".join(lines).rstrip()
    if out.count("**") % 2:
        out += "**"
    elif out.count("`") % 2:
        out += "`"
    return out
