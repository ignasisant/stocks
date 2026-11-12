"""A PDF attached to a question, turned into the text it holds.

The composer's "ask about it": a results release, a broker's note, a fund's
fact sheet. Its text is read off the pages (`chat/document.py`) and handed
back to the client, which sends it beside the question on the path every turn
takes (`forwardedProps.documents`). This is that one step — reading and
nothing else, as a pasted screenshot's is (`chat_screenshot.py`).

It is not the statement reader (`chat_attach.py`), which takes the same file
type through the same clip: that one looks for trades to import, with a model
and a preview card. Which of the two a PDF is for is the reader's to say, and
the composer asks.

**The file never lands on disk**, here or anywhere: it is decoded, read and
dropped. The thread stores the text that was sent with the question.

**The type is read off the bytes, not the name.** A file that does not open
as a PDF is refused whatever it is called.

**No model is called.** Extraction is a program's, so there is no daily
allowance to spend — only the burst budget, since laying out pages is this
worker's CPU.

**A refusal is a locale key, not a sentence** (`chat.doc_unreadable`,
`chat.doc_no_text`, `chat.doc_too_big`), as on the screenshot route.

**Every read leaves a line in the log**, with the account on it and never the
file's name or what it said: `doc.ok` (size, pages, how much text, how it
came in), `doc.refused` (why). `doc.used` is the turn's
(`routes/chat/turns.py`).
"""

from __future__ import annotations

import base64
import binascii
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.api.deps import ChatDocument
from stocks.chat import document

router = APIRouter(prefix="/chat", tags=["chat"])

# Base64 is four characters for three bytes; a little over, so a file at the
# cap is told it is too big (413) rather than refused as a malformed body.
_MAX_ENCODED = document.MAX_BYTES * 4 // 3 + 1024


def _refused(code: int, detail: str, reason: str, *, size: int = 0) -> HTTPException:
    """The refusal to raise, logged on its way out as one `doc.refused`."""
    obs.event("doc.refused", reason=reason, status=code, bytes=size)
    return HTTPException(status_code=code, detail=detail)


class PdfUpload(BaseModel):
    model_config = {"extra": "forbid"}

    filename: str = Field(
        default="", max_length=255,
        description="The file's name, shown on the question it goes with.",
    )
    content: str = Field(
        description=(
            "The PDF's bytes, base64-encoded: at most "
            f"{document.MAX_BYTES // (1024 * 1024)} MB."
        ),
    )
    via: Literal["paste", "pick", "drop"] = Field(
        default="pick",
        description=(
            "How the file reached the composer: pasted, picked with the "
            "clip, or dropped on the conversation. Logged, nothing else."
        ),
    )


class DocumentRead(BaseModel):
    name: str = Field(description="The file's name, as it may be shown.")
    text: str = Field(
        description=(
            "The document's text from its first page on, at most "
            f"{document.MAX_CHARS} characters. Send it back in a run's "
            "`forwardedProps.documents` to ask about it."
        ),
    )
    pages: int = Field(description="How many pages the file has.")
    read: int = Field(description="How many of them the text came from.")
    cut: bool = Field(description="Whether the file held more than `text`.")


@router.post("/documents", response_model=DocumentRead,
             summary="Read a PDF to ask about")
def read(body: PdfUpload, paths: ChatDocument) -> DocumentRead:
    """A PDF's text. Writes nothing — not the file, not a turn."""
    if len(body.content) > _MAX_ENCODED:
        raise _refused(status.HTTP_413_CONTENT_TOO_LARGE,
                       "chat.doc_too_big", "too_big")
    try:
        raw = base64.b64decode(body.content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _refused(status.HTTP_422_UNPROCESSABLE_CONTENT,
                       "content must be base64", "not_base64") from exc
    if len(raw) > document.MAX_BYTES:
        raise _refused(status.HTTP_413_CONTENT_TOO_LARGE,
                       "chat.doc_too_big", "too_big", size=len(raw))
    if not document.is_pdf(raw):
        raise _refused(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                       "chat.doc_unreadable", "not_pdf", size=len(raw))
    t0 = time.perf_counter()
    try:
        found = document.read_pdf(raw)
    except document.Unreadable as failed:
        raise _refused(status.HTTP_422_UNPROCESSABLE_CONTENT, failed.key,
                       failed.key.removeprefix("chat.doc_"),
                       size=len(raw)) from failed
    obs.event("doc.ok", bytes=len(raw), pages=found["pages"], read=found["read"],
              chars=len(found["text"]), cut=found["cut"], via=body.via,
              took_ms=int((time.perf_counter() - t0) * 1000))
    return DocumentRead(name=document.name_of(body.filename), **found)
