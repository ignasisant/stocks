"""Grab a picture of the screen the user is looking at.

A bug report that carries the screen it happened on answers the questions the
text never does — which tab, which numbers, which layout, on what width. The
browser is the only thing that can see that screen, so the capture happens
there: a CCv2 component whose JS rasterises the app's own document and hands
the frame back as a JPEG data URL, which Python decodes into bytes the caller
stores next to the submission (see stocks.web.feedback).

Three things worth knowing before editing this:

1. **Nothing loads until the user asks for a shot.** html2canvas-pro is
   imported from jsdelivr inside the capture itself (pinned version, ~210 KB),
   so a session that never attaches one pays nothing. The *pro* fork, not
   html2canvas: this app's CSS is full of ``color-mix()``, which the original
   1.4.1 throws on.
2. **The modal is not part of the screen being reported.** The feedback dialog
   is open at capture time and is skipped (with the toasts) from the clone the
   library builds, so the picture shows the page underneath — what the user
   means by "this screen".
3. **The frame is a data URL over the websocket**, so size is a wire cost, not
   just a disk one: the JS scales to `MAX_WIDTH`, crops to the viewport and
   walks JPEG quality down until it fits `MAX_URL_CHARS`, and Python refuses
   anything bigger than `MAX_BYTES` after decoding. A shot that will not fit
   is dropped, never sent half-way.

The bytes are user input the same way the comment text is: `decode` accepts
one exact prefix, checks the JPEG magic and caps the length before anything is
written to disk.
"""

from __future__ import annotations

import base64
import binascii
import uuid

import streamlit as st
import streamlit.components.v2  # noqa: F401 — lazy submodule

from stocks import obs

# Pinned: the URL is fetched by the browser at capture time, and an unpinned
# tag would let a library upgrade land on users without a deploy.
LIB_URL = "https://cdn.jsdelivr.net/npm/html2canvas-pro@1.5.11/+esm"

# Wide enough to read a table cell on a 4K screen after the downscale, small
# enough that the JPEG stays in the hundreds of KB.
MAX_WIDTH = 1600
# Characters of base64 (roughly 4/3 of the bytes) the JS will send.
MAX_URL_CHARS = 3_000_000
# What Python will keep after decoding — the same limit, expressed in bytes.
MAX_BYTES = 2_000_000
# html2canvas can walk a big DOM for a long time; past this the user is better
# served by a report without a picture than by a modal that never answers.
TIMEOUT_MS = 20_000

_JPEG_PREFIX = "data:image/jpeg;base64,"
_JPEG_MAGIC = b"\xff\xd8\xff"

_GRABBER = None

_JS = """
export default function (component) {
  const { data, parentElement, setStateValue } = component
  // One capture per arming token: the component re-renders on every rerun of
  // the dialog it lives in (a keystroke in the comment box is one), and
  // re-shooting on each of those would fight the preview the user is looking
  // at — and spend a full rasterisation per character typed.
  const go = String((data && data.go) || "")
  if (!go || parentElement.dataset.shotFor === go) return
  parentElement.dataset.shotFor = go

  const doc = parentElement.ownerDocument
  const win = doc.defaultView
  const done = (shot, error) => {
    setStateValue("shot", shot || "")
    setStateValue("error", error || "")
  }
  // The dialog the user is typing in, and any toast on top of it, are this
  // widget's own chrome — not the screen being reported. ignoreElements drops
  // them from the clone, so the picture shows the page underneath.
  const skip = (el) => {
    const id = (el.getAttribute && el.getAttribute("data-testid")) || ""
    return /^stDialog|^stToast/.test(id) || el.getAttribute?.("role") === "dialog"
  }

  const shoot = async () => {
    const mod = await import(data.lib)
    const html2canvas = mod.default || mod
    const scale = Math.min(1, (data.maxWidth || 1600) / Math.max(1, win.innerWidth))
    const canvas = await html2canvas(doc.body, {
      backgroundColor: win.getComputedStyle(doc.body).backgroundColor || "#ffffff",
      scale,
      useCORS: true,
      logging: false,
      imageTimeout: 5000,
      ignoreElements: skip,
      // The viewport, not the whole document: a page scrolled to a chart
      // halfway down should come back as that chart, and a tall page would
      // rasterise into tens of megabytes.
      x: win.scrollX,
      y: win.scrollY,
      width: win.innerWidth,
      height: win.innerHeight,
    })
    // Belt and braces: if the crop options ever stop being honoured, take the
    // viewport out of whatever came back rather than sending the whole page.
    const vw = Math.round(win.innerWidth * scale)
    const vh = Math.round(win.innerHeight * scale)
    let frame = canvas
    if (canvas.width > vw + 2 || canvas.height > vh + 2) {
      frame = doc.createElement("canvas")
      frame.width = Math.min(vw, canvas.width)
      frame.height = Math.min(vh, canvas.height)
      frame.getContext("2d").drawImage(
        canvas,
        Math.round(win.scrollX * scale), Math.round(win.scrollY * scale),
        frame.width, frame.height, 0, 0, frame.width, frame.height,
      )
    }
    // Quality ladder rather than one guess: a dense page of tables is several
    // times the bytes of a mostly-empty one at the same size.
    const cap = data.maxUrl || 3000000
    let url = ""
    for (const quality of [0.72, 0.5, 0.35]) {
      url = frame.toDataURL("image/jpeg", quality)
      if (url.length <= cap) break
    }
    if (url.length > cap) return done("", "too_big")
    done(url, "")
  }

  const timeout = new Promise((_, reject) =>
    setTimeout(() => reject(new Error("timeout")), data.timeoutMs || 20000)
  )
  Promise.race([shoot(), timeout]).catch((err) =>
    done("", String((err && err.message) || err).slice(0, 160) || "failed")
  )
}
"""


def _grabber():
    """The registered component (once per process, on first mount).

    Registered lazily for the same reason `search._live_search_component` is:
    server.py imports the web package at ASGI boot, before the Streamlit
    runtime exists, and a registration made then lands in a throwaway manager.
    """
    global _GRABBER
    if _GRABBER is None:
        _GRABBER = st.components.v2.component(
            "topstocks_screen_grab",
            # The component itself must not show up in its own picture; it has
            # nothing to draw anyway — Python renders the preview.
            html='<span hidden data-topstocks-grab="1"></span>',
            js=_JS,
        )
    return _GRABBER


def _field(state: object, name: str) -> str:
    """One key off the component's state, dict-shaped or attribute-shaped."""
    if isinstance(state, dict):
        value = state.get(name, "")
    else:
        value = getattr(state, name, "")
    return value if isinstance(value, str) else ""


def decode(url: str) -> bytes | None:
    """The JPEG behind a data URL the browser sent, or None if it isn't one.

    Untrusted input: exactly one accepted prefix, a length cap applied before
    the decode allocates, and the JPEG magic checked after it.
    """
    if not isinstance(url, str) or not url.startswith(_JPEG_PREFIX):
        return None
    payload = url[len(_JPEG_PREFIX):]
    if not payload or len(payload) > MAX_URL_CHARS:
        return None
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if raw.startswith(_JPEG_MAGIC) else None


def arm(key: str) -> None:
    """Ask for a fresh capture on the next mount of `key`."""
    st.session_state[f"_{key}_go"] = uuid.uuid4().hex[:8]


def reset(key: str) -> None:
    """Forget the shot and its arming token (the widget must not be on screen).

    Called when the user drops the attachment or sends the submission, so the
    next time the box is ticked the app captures the screen as it is *then*.
    """
    st.session_state.pop(key, None)
    st.session_state.pop(f"_{key}_go", None)


def capture(key: str = "fb_shot") -> tuple[bytes | None, str]:
    """Mount the grabber and report what it has: `(jpeg, status)`.

    `status` is "" once the bytes are in hand, "pending" while the browser is
    still working (the caller should say so and let the rerun bring it),
    "too_big" when the screen would not compress into the wire budget, and
    "failed" for everything else — a blocked CDN, a DOM the library choked on,
    the timeout. The caller decides what to say; nothing here warns, because
    a missing picture must never block the comment underneath it.
    """
    if not st.session_state.get(f"_{key}_go"):
        arm(key)
    result = _grabber()(
        key=key,
        data={
            "go": st.session_state[f"_{key}_go"],
            "lib": LIB_URL,
            "maxWidth": MAX_WIDTH,
            "maxUrl": MAX_URL_CHARS,
            "timeoutMs": TIMEOUT_MS,
        },
        height="content",
        # Logged where the value changes, not in the body below: the body runs
        # on every rerun of the dialog and would repeat one failure forever.
        on_error_change=lambda: _log_failure(key),
        on_shot_change=lambda: None,
    )
    error = _field(result, "error")
    if error:
        return None, "too_big" if error == "too_big" else "failed"
    url = _field(result, "shot")
    if not url:
        return None, "pending"
    raw = decode(url)
    if raw is None:
        obs.event("feedback.shot_failed", reason="undecodable")
        return None, "failed"
    if len(raw) > MAX_BYTES:
        return None, "too_big"
    return raw, ""


def _log_failure(key: str) -> None:
    reason = _field(st.session_state.get(key), "error")
    if reason:
        obs.event("feedback.shot_failed", reason=reason[:120])
