"""The categorical series palette has to survive the people who read it.

`ds.CATEGORICAL_COLORS` is what tells one line, slice or bar from another. The
DS's text-weight hues (L 0.67–0.84 in OKLCH) are too light for a mark on the
dark card, and two of them collapse into one colour for a red-green colour-
blind reader — which is why the palette is its own set of mid steps.

These are the dataviz skill's checks (`scripts/validate_palette.js`), ported
so they run in CI rather than when someone remembers:

- every hue sits in the dark mark band (OKLCH L 0.48–0.67) with chroma ≥ 0.10;
- each adjacent pair stays ≥ 8 apart (ΔE OKLab ×100) under protan and deutan
  simulation (Machado 2009, severity 1.0) and ≥ 15 for full-colour vision;
- each hue reads ≥ 3:1 against both the card and the page surface.

Adjacent, not all pairs: the palette is assigned in fixed order and never
cycled, so slot 1 meets slot 2 on every chart while slot 1 and slot 5 only
meet on a chart with five series, beside three others between them.

Dark only: the app has no light theme, so no light-band check.
"""

from __future__ import annotations

import pytest

from stocks.web.ds import (
    CANDLE_DOWN,
    CANDLE_UP,
    CATEGORICAL_COLORS,
    CRITICAL_FILL,
    DOWN_COLOR,
    SERIES_OTHER,
    SUCCESS_FILL,
    SURFACE_CARD,
    SURFACE_PAGE,
    UP_COLOR,
    tokens,
)

L_BAND = (0.48, 0.67)
CHROMA_FLOOR = 0.10
CVD_TARGET = 8.0
NORMAL_FLOOR = 15.0
CONTRAST_FLOOR = 3.0
SURFACES = {"card": SURFACE_CARD, "page": SURFACE_PAGE}

# Machado, Oliveira & Fernandes (2009), severity 1.0, on linear RGB.
_PROTAN = (
    (0.152286, 1.052583, -0.204868),
    (0.114503, 0.786281, 0.099216),
    (-0.003882, -0.048116, 1.051998),
)
_DEUTAN = (
    (0.367322, 0.860646, -0.227968),
    (0.280085, 0.672501, 0.047413),
    (-0.011820, 0.042940, 0.968881),
)

Rgb = tuple[float, float, float]


def _linear(hex_: str) -> Rgb:
    raw = hex_.lstrip("#")
    channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    )
    return r, g, b


def _simulate(rgb: Rgb, matrix: tuple[Rgb, Rgb, Rgb]) -> Rgb:
    r, g, b = (
        min(1.0, max(0.0, row[0] * rgb[0] + row[1] * rgb[1] + row[2] * rgb[2]))
        for row in matrix
    )
    return r, g, b


def _oklab(rgb: Rgb) -> Rgb:
    r, g, b = rgb
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def _delta_e(one: Rgb, two: Rgb) -> float:
    """ΔE in OKLab, ×100 so the skill's thresholds read as written."""
    a, b = _oklab(one), _oklab(two)
    return 100 * sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def _luminance(hex_: str) -> float:
    r, g, b = _linear(hex_)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(one: str, two: str) -> float:
    hi, lo = sorted((_luminance(one), _luminance(two)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


_PAIRS = list(zip(CATEGORICAL_COLORS, CATEGORICAL_COLORS[1:], strict=False))


@pytest.mark.parametrize("hue", CATEGORICAL_COLORS)
def test_hue_sits_in_the_dark_mark_band(hue: str) -> None:
    lightness, a, b = _oklab(_linear(hue))
    chroma = (a * a + b * b) ** 0.5
    assert L_BAND[0] <= lightness <= L_BAND[1], f"{hue} L={lightness:.3f}"
    assert chroma >= CHROMA_FLOOR, f"{hue} C={chroma:.3f}"


@pytest.mark.parametrize(("one", "two"), _PAIRS)
def test_adjacent_pair_survives_red_green_blindness(one: str, two: str) -> None:
    for name, matrix in (("protan", _PROTAN), ("deutan", _DEUTAN)):
        seen = _delta_e(_simulate(_linear(one), matrix), _simulate(_linear(two), matrix))
        assert seen >= CVD_TARGET, f"{one}/{two} {name} ΔE={seen:.1f}"


@pytest.mark.parametrize(("one", "two"), _PAIRS)
def test_adjacent_pair_is_apart_for_full_colour_vision(one: str, two: str) -> None:
    seen = _delta_e(_linear(one), _linear(two))
    assert seen >= NORMAL_FLOOR, f"{one}/{two} ΔE={seen:.1f}"


@pytest.mark.parametrize("hue", CATEGORICAL_COLORS)
@pytest.mark.parametrize("surface", SURFACES)
def test_hue_reads_on_the_surface(hue: str, surface: str) -> None:
    ratio = _contrast(hue, SURFACES[surface])
    assert ratio >= CONTRAST_FLOOR, f"{hue} on {surface} {ratio:.2f}:1"


def test_series_hues_are_not_up_or_down() -> None:
    """Green and red say up and down on a market chart, never "which one"."""
    status = {CANDLE_UP, CANDLE_DOWN, UP_COLOR, DOWN_COLOR, SUCCESS_FILL, CRITICAL_FILL}
    assert not status & {*CATEGORICAL_COLORS, SERIES_OTHER}


def test_series_tokens_publish_the_palette_in_order() -> None:
    """`theme.ts`'s `series()` reads `series-1…n`; the slots are the list's order."""
    published = tokens()
    assert [
        published[f"series-{slot}"] for slot in range(1, len(CATEGORICAL_COLORS) + 1)
    ] == CATEGORICAL_COLORS
    assert f"series-{len(CATEGORICAL_COLORS) + 1}" not in published
    assert published["series-other"] == SERIES_OTHER
