"""The assistant over HTTP: its threads, its settings, and one streaming turn.

The assistant itself lives in `stocks.chat.engine`: the provider chain, the free
quota, skill routing, the web grounding, and a turn that ends with a completed
user+assistant pair on disk. This router is the second binding of that engine
(headless callers are the first), so every surface
gives the same answer to the same question, and a change to how a turn works is
made once.

Sending is a stream, not a request/response. A chat turn takes ten to forty
seconds against a busy provider, and a client with nothing to show for thirty
of them looks broken — so `POST /chat/runs` answers `text/event-stream` and
the words arrive as the model writes them. The stream is AG-UI
(docs.ag-ui.com): the body is its `RunAgentInput`, the events are its own, an
app action waits on the reader as an interrupt, and a page link is a frontend
tool call. It is a POST rather than an
`EventSource` GET on purpose: the message is a body, bodies are what this API's
CSRF defence is built on (a cross-site form cannot send `application/json`), and
a question typed by a user does not belong in a URL that lands in logs.
"""

from __future__ import annotations

from fastapi import APIRouter

from stocks.api.routes.chat import actions, preferences, threads, turns
from stocks.api.routes.chat.preferences import session_keys
from stocks.api.routes.chat.turns import Run, holds

__all__ = ["holds", "Run", "session_keys"]

# Each leaf carries the "/chat" prefix itself: an included router is not
# flattened, and the guest gate reads the innermost route's path, which must
# still say "/chat/...".
router = APIRouter()
for _leaf in (threads, preferences, turns, actions):
    router.include_router(_leaf.router)
