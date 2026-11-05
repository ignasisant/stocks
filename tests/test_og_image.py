"""The link-preview images (`web/og_image.py`): what they are drawn from and
what they survive. The route tests are in test_server."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from stocks.web import og_image

SHARE = {"id": "AbCdEfGh123", "lang": "es", "by": "Ana",
         "question": "¿Debería vender parte de NVDA? 🚀",
         "content": "**Sí**: recorta ~3 puntos; ganancia de ••• € y un 18 % sobre coste."}


def _size(png: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(png)).size


def test_a_share_is_a_png_of_the_preview_size():
    png = og_image.share_png(SHARE)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert _size(png) == (og_image.W, og_image.H)


@pytest.mark.parametrize("share", [
    {},
    {"id": "x" * 8, "question": "A" * 5000, "content": "B" * 50000},
    {"question": "<script>alert(1)</script>", "content": "\x00‮" + "é" * 900},
    {"question": "🚀🔥💰", "content": "👍" * 300, "lang": "xx", "by": "👤"},
])
def test_any_stored_share_draws(share):
    assert _size(og_image.share_png(share)) == (og_image.W, og_image.H)


@pytest.mark.parametrize("tickers", [[], ["NVDA"], [f"SYM{i}.DE" for i in range(50)],
                                     ["A" * 32] * 3])
def test_a_shared_list_draws_whatever_it_holds(tickers):
    share = {"id": f"list{len(tickers)}", "kind": "watchlist", "title": "Semis " * 20,
             "tickers": tickers, "by": "Ana", "lang": "es"}
    assert _size(og_image.list_png(share)) == (og_image.W, og_image.H)
    assert og_image.share_image(share) == og_image.list_png(share)


def test_a_ticker_draws_with_or_without_a_long_name():
    for symbol, name in (("NVDA", "NVIDIA Corporation"), ("A" * 32, "N" * 300),
                         ("^GSPC", "")):
        assert _size(og_image.ticker_png(symbol, name)) == (og_image.W, og_image.H)


def test_markdown_and_pictographs_are_not_drawn():
    """A face with no glyph draws an empty box; markdown marks draw as
    themselves."""
    assert og_image._plain("**Sí** 🚀 [10-K](https://x.y) `code`") == "Sí 10-K code"


def test_an_amount_and_its_sign_stay_on_one_line():
    assert og_image._plain("un 18 % y ••• €") == "un 18 % y ••• €"


def test_a_long_text_is_cut_to_its_lines_and_says_so():
    from PIL import ImageDraw

    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = og_image._font("body", 32, 400)
    lines = og_image._wrap(d, "palabra " * 200, font, 600, 3)
    assert len(lines) == 3 and lines[-1].endswith("…")
    assert all(d.textlength(line, font=font) <= 600 for line in lines)
    # One word wider than a line is cut where it fits rather than overflowing.
    long = og_image._wrap(d, "W" * 400, font, 600, 2)
    assert len(long) == 2 and all(d.textlength(x, font=font) <= 600 for x in long)
    assert og_image._wrap(d, "corto", font, 600, 3) == ["corto"]


def test_a_drawn_image_is_kept_by_its_key(monkeypatch):
    drawn = []
    monkeypatch.setattr(og_image, "_kept", og_image._Kept(2))
    monkeypatch.setattr(og_image, "share_png",
                        lambda share: drawn.append(share["id"]) or share["id"].encode())
    for sid in ("a", "a", "b", "c", "a"):
        og_image.share_image({"id": sid})
    # "a" fell out when "c" came in (cap 2), so it was drawn twice.
    assert drawn == ["a", "b", "c", "a"]
