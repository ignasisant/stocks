"""The images a link preview shows: one per shared answer, one per ticker.

Every page used to unfurl with the landing's card (`assets/og.png`), so a
shared answer pasted into WhatsApp looked like an ad for the app rather than
the thing being sent. These draw the link's own content on the same brand
ground (`scripts/make_og_card.py` draws the static one; the tokens match).

A share's image (an answer's, or a list's symbols) is drawn from the stored
copy only (`web/shares.py`), which was cut when it was published: masked
amounts are already "•••" before a pixel is set, so the image can say no
more than the page. A ticker's is the symbol and the company name the
profiles memo already holds — no price. A preview is cached by the app that
unfurled it for as long as it likes, and a price frozen into it would be wrong
by the next session.

Both are kept in memory once drawn: a share is frozen, and a ticker's name
changes with a rename at most. The route checks the share still exists
before it serves the cached one, so a link taken down has no image either.

Pillow and the two faces (`web/fonts/`, OFL) load on the first image, not on
import: most containers never draw one.
"""

from __future__ import annotations

import io
import re
import threading
from collections import OrderedDict
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from stocks.web.i18n import DEFAULT_LANG, LANGUAGES, translate

if TYPE_CHECKING:
    from PIL import ImageDraw, ImageFont

W, H = 1200, 630
_FONTS = Path(__file__).with_name("fonts")

# stocks.web.ds tokens, as scripts/make_og_card.py spells them.
BG = (24, 22, 28)
TEXT = (249, 249, 250)
SOFT = (196, 194, 204)
PURPLE = (127, 63, 232)
PURPLE_LIGHT = (169, 142, 247)

_LEFT = 80
_TEXT_W = W - 2 * _LEFT
# Past these the text is not read in a preview anyway; cutting the input
# first keeps a long answer from costing a wrap of every word in it.
_QUESTION_LINES = 3
_ANSWER_LINES = 4
_ANSWER_CHARS = 600
_CACHED = 64

# Pictographs the faces have no glyph for: drawn, they are empty boxes.
_NO_GLYPH = re.compile(
    "[\U0001f000-\U0001faff☀-➿︎️‍\U000e0000-\U000e007f]"
)


@cache
def _face(kind: str) -> bytes:
    name = {"display": "Epilogue.ttf", "body": "InstrumentSans.ttf"}[kind]
    return (_FONTS / name).read_bytes()


@cache
def _font(kind: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    from PIL import ImageFont

    font = ImageFont.truetype(io.BytesIO(_face(kind)), size)
    # Epilogue has one axis (weight); Instrument Sans has width, then weight.
    font.set_variation_by_axes([weight] if kind == "display" else [100, weight])
    return font


def _plain(text: str) -> str:
    """Markdown as the words it shows, on one line, without what the faces
    cannot draw."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#>|]+", "", text)
    text = " ".join(_NO_GLYPH.sub("", text).split())
    # "18 %" and "••• €" are one word to a reader; a line must not part them.
    return re.sub(r" (?=[%€$£¥])", "\u00a0", text)


def _wrap(
    d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int,
    lines: int,
) -> list[str]:
    """`text` in at most `lines` lines of `width` pixels; the last one ends in
    "…" when there was more. A word wider than a line is cut where it fits."""
    out: list[str] = []
    line = ""
    for word in text.split(" "):
        candidate = f"{line} {word}" if line else word
        if d.textlength(candidate, font=font) <= width:
            line = candidate
            continue
        if line:
            out.append(line)
        line = word
        while d.textlength(line, font=font) > width:
            cut = len(line)
            while cut > 1 and d.textlength(line[:cut], font=font) > width:
                cut -= 1
            out.append(line[:cut])
            line = line[cut:]
            if len(out) >= lines:
                break
        if len(out) >= lines:
            return _ellipsis(d, out[:lines], font, width)
    if line:
        out.append(line)
    if len(out) > lines:
        return _ellipsis(d, out[:lines], font, width)
    return out


def _ellipsis(
    d: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont, width: int
) -> list[str]:
    last = lines[-1].rstrip()
    while last and d.textlength(f"{last}…", font=font) > width:
        last = last[:-1].rstrip()
    return [*lines[:-1], f"{last}…"]


def _ground():
    """The brand ground: page colour, a purple bloom top left, a hairline."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (W, H), (*BG, 255))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow = ImageDraw.Draw(overlay)
    for i in range(26, 0, -1):
        r = i * 26
        glow.ellipse((180 - r, 120 - r, 180 + r, 120 + r),
                     fill=(*PURPLE, int(3 + (26 - i) * 0.9)))
    img.alpha_composite(overlay)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 5), fill=PURPLE_LIGHT)
    return img, d


def _brand(d: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    """The purple tile with its upward tick, and the wordmark beside it."""
    d.rounded_rectangle((x, y, x + size, y + size), radius=size // 4, fill=PURPLE)
    pad = size * 0.24
    d.line(
        [(x + pad, y + size - pad), (x + size * 0.42, y + size * 0.52),
         (x + size * 0.6, y + size * 0.66), (x + size - pad, y + pad)],
        fill=(255, 255, 255), width=max(3, size // 14), joint="curve",
    )
    font = _font("display", int(size * 0.72), 800)
    d.text((x + size + 18, y + size // 2), "TopStocks", font=font, fill=TEXT,
           anchor="lm")


def _png(img) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


def share_png(share: dict) -> bytes:
    """A shared answer's card: who asked, the question, the answer's start."""
    img, d = _ground()
    lang = str(share.get("lang") or "")
    lang = lang if lang in LANGUAGES else DEFAULT_LANG
    by = str(share.get("by") or "")
    lead = (translate("landing.share_card_by", lang, name=by) if by
            else translate("landing.share_card", lang))

    _brand(d, _LEFT, 56, 52)
    y = 150
    d.text((_LEFT, y), lead, font=_font("body", 30, 600), fill=PURPLE_LIGHT)
    y += 56

    q_font = _font("display", 52, 700)
    question = _plain(str(share.get("question") or ""))
    for line in _wrap(d, question, q_font, _TEXT_W, _QUESTION_LINES):
        d.text((_LEFT, y), line, font=q_font, fill=TEXT)
        y += 64
    y += 18

    a_font = _font("body", 32, 400)
    room = max(0, min(_ANSWER_LINES, (H - 60 - y) // 44))
    answer = _plain(str(share.get("content") or "")[:_ANSWER_CHARS])
    if room:
        for line in _wrap(d, answer, a_font, _TEXT_W, room):
            d.text((_LEFT, y), line, font=a_font, fill=SOFT)
            y += 44
    return _png(img)


def list_png(share: dict) -> bytes:
    """A shared list's card: who sent it, its name, then the symbols large —
    as many lines of them as fit, the rest counted."""
    img, d = _ground()
    lang = str(share.get("lang") or "")
    lang = lang if lang in LANGUAGES else DEFAULT_LANG
    by = str(share.get("by") or "")
    lead = (translate("landing.share_list_by", lang, name=by) if by
            else translate("landing.share_list", lang))
    symbols = [str(t) for t in share.get("tickers") or []]

    _brand(d, _LEFT, 56, 52)
    y = 150
    d.text((_LEFT, y), lead, font=_font("body", 30, 600), fill=PURPLE_LIGHT)
    y += 56
    title = _plain(str(share.get("title") or ""))
    if title:
        t_font = _font("display", 52, 700)
        d.text((_LEFT, y), _wrap(d, title, t_font, _TEXT_W, 1)[0], font=t_font,
               fill=TEXT)
        y += 84
    s_font = _font("display", 60, 800)
    gap = d.textlength("   ", font=s_font)
    x, row, shown = _LEFT, 0, 0
    rows = max(1, (H - 60 - y) // 76)
    for symbol in symbols:
        width = d.textlength(symbol, font=s_font)
        if x > _LEFT and x + width > _LEFT + _TEXT_W:
            row, x = row + 1, _LEFT
        # The last row keeps room for "+N" when more are left after it.
        if row >= rows or (row == rows - 1 and shown < len(symbols) - 1
                           and x + width + gap + d.textlength("+99", font=s_font)
                           > _LEFT + _TEXT_W):
            break
        d.text((x, y + row * 76), symbol, font=s_font, fill=TEXT)
        x += width + gap
        shown += 1
    if shown < len(symbols):
        d.text((x, y + row * 76 if row < rows else y + (rows - 1) * 76),
               f"+{len(symbols) - shown}", font=s_font, fill=SOFT)
    return _png(img)


def ticker_png(symbol: str, name: str = "") -> bytes:
    """A ticker's card: the brand, then the symbol large and the company
    under it. No figures and no words in a language: the card is the same
    for every reader and kept by the apps that show it."""
    img, d = _ground()
    _brand(d, _LEFT, 56, 52)
    size = 144
    while size > 64 and d.textlength(symbol, font=_font("display", size, 800)) > _TEXT_W:
        size -= 16
    d.text((_LEFT, 470), symbol, font=_font("display", size, 800), fill=TEXT,
           anchor="ls")
    name = _plain(name)
    if name:
        n_font = _font("body", 44, 500)
        line = _wrap(d, name, n_font, _TEXT_W, 1)[0]
        d.text((_LEFT, 550), line, font=n_font, fill=SOFT, anchor="ls")
    return _png(img)


class _Kept:
    """The last `cap` images drawn, by key. A lock, because the routes draw
    in the threadpool."""

    def __init__(self, cap: int) -> None:
        self._cap = cap
        self._items: OrderedDict[tuple, bytes] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple, draw) -> bytes:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        png = draw()
        with self._lock:
            self._items[key] = png
            while len(self._items) > self._cap:
                self._items.popitem(last=False)
        return png


_kept = _Kept(_CACHED)


def share_image(share: dict) -> bytes:
    draw = list_png if share.get("kind") == "watchlist" else share_png
    return _kept.get(("share", str(share.get("id") or "")), lambda: draw(share))


def ticker_image(symbol: str, name: str = "") -> bytes:
    return _kept.get(("ticker", symbol, name), lambda: ticker_png(symbol, name))
