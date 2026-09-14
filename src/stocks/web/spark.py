"""Inline SVG sparklines — a trend line small enough to sit inside a KPI tile.

Every trend row on the Pulse page carries one of these next to its numbers,
which is thirteen of them in the indices table alone. That count is the whole
design constraint:

* **SVG, not Plotly.** A Plotly figure per tile means thirteen React charts,
  thirteen resize observers and thirteen `st.plotly_chart` element containers
  on one page. These are one `polyline` each, emitted inside the same HTML
  block as the tile they belong to — no extra Streamlit elements at all.
* **No axes, no labels, no hover.** A sparkline answers "which way, how
  smoothly" and nothing else; the exact figures are already printed beside it.
  Adding a tooltip would also mean adding it on touch, where a `title` never
  fires.

**The SVG travels as a data URI, and it has to.** Streamlit runs everything
`st.html` renders through DOMPurify configured `USE_PROFILES: {html: true}`,
and that profile has no SVG in it: an inline `svg` element is removed, silently
and completely, leaving an empty cell where the shape should be. A background
image is not markup, so a `background-image: url("data:image/svg+xml;base64,…")`
on a plain `span` survives the same sanitiser untouched. Hence the split below:
`sparkline_svg` builds the picture, `sparkline` wraps it in the one container
that reaches the page.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence

from stocks.web.ds import CANDLE_DOWN, CANDLE_UP, TEXT_FAINT, TEXT_MUTED

# A data-URI SVG is a standalone document, so it carries its own namespace.
SVG_NS = "http://www.w3.org/2000/svg"

# Tile-sized by default: wide enough to read a shape, short enough to sit on
# one line beside a number without changing the row height.
WIDTH, HEIGHT = 84, 22
# Keeps the stroke's own width from clipping at the extremes.
PAD = 1.5


def _points(values: Sequence[float], width: float, height: float) -> str:
    """`values` mapped to an SVG polyline point list, oldest point on the left.

    The vertical scale is the series' own min-to-max, so every sparkline fills
    its box and none of them share a scale — these are shapes, not comparable
    magnitudes. A flat series would divide by zero, so it draws down the middle
    instead.
    """
    lo, hi = min(values), max(values)
    span = hi - lo
    inner_h = height - 2 * PAD
    inner_w = width - 2 * PAD
    step = inner_w / (len(values) - 1) if len(values) > 1 else 0.0
    coords = []
    for i, value in enumerate(values):
        # SVG's y grows downward, so the ratio is inverted to put high values
        # at the top.
        ratio = 0.5 if span == 0 else (value - lo) / span
        x = PAD + i * step
        y = PAD + (1.0 - ratio) * inner_h
        coords.append(f"{x:.1f},{y:.1f}")
    return " ".join(coords)


def embed(svg: str, *, css: str) -> str:
    """`svg` as a `span` the sanitiser keeps, sized and stretched by `css`.

    Base64 rather than percent-encoding: the payload then contains no quote,
    angle bracket or `#` for the style attribute, the CSS parser or DOMPurify
    to disagree about, and one round of guessing about escaping is one round
    too many for something that fails invisibly.
    """
    if not svg:
        return ""
    uri = base64.b64encode(svg.encode()).decode()
    return (
        f'<span class="ag-spark" style="{css};'
        f'background-image:url(&quot;data:image/svg+xml;base64,{uri}&quot;);'
        'background-repeat:no-repeat;background-size:100% 100%"></span>'
    )


def sparkline(
    values: Sequence[float],
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
    color: str | None = None,
    baseline: float | None = None,
) -> str:
    """One sparkline, ready to drop into a block of HTML.

    Empty when there is nothing to draw, so a caller can leave the cell out
    rather than draw a dot and imply a trend.
    """
    return embed(
        sparkline_svg(
            values, width=width, height=height, color=color, baseline=baseline
        ),
        css=f"display:inline-block;width:{width}px;height:{height}px",
    )


def sparkline_svg(
    values: Sequence[float],
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
    color: str | None = None,
    baseline: float | None = None,
) -> str:
    """The sparkline's own markup, empty when there is nothing to draw.

    Args:
        values: the series, oldest first. Two points is the minimum; anything
            shorter returns "" so a caller can drop the cell rather than draw a
            dot and imply a trend.
        color: stroke colour. Defaults to green/red by the sign of the total
            change across the window, which is the reading the tile wants — the
            line's own direction, not the last tick's.
        baseline: draws a faint horizontal rule at this value when it falls
            inside the range. Pass 0 for a series of changes, so "above or
            below zero" is visible without reading the numbers.
    """
    series = [float(v) for v in values if v == v]
    if len(series) < 2:
        return ""
    stroke = color or (CANDLE_UP if series[-1] >= series[0] else CANDLE_DOWN)
    parts = [
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" preserveAspectRatio="none">'
    ]
    if baseline is not None:
        lo, hi = min(series), max(series)
        if lo < baseline < hi:
            inner_h = height - 2 * PAD
            y = PAD + (1.0 - (baseline - lo) / (hi - lo)) * inner_h
            parts.append(
                f'<line x1="0" y1="{y:.1f}" x2="{width}" y2="{y:.1f}" '
                f'stroke="{TEXT_FAINT}" stroke-width="1" '
                'stroke-dasharray="2 2"/>'
            )
    parts.append(
        f'<polyline points="{_points(series, width, height)}" fill="none" '
        f'stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round" '
        'stroke-linecap="round"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def flat_rule(*, width: int = WIDTH, height: int = HEIGHT) -> str:
    """A muted horizontal rule, for a cell whose series was too short to plot.

    Holds the column's width so a table with one unreadable row does not shift
    every sparkline beside it.
    """
    y = height / 2
    return embed(
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" preserveAspectRatio="none">'
        f'<line x1="0" y1="{y:.1f}" x2="{width}" '
        f'y2="{y:.1f}" stroke="{TEXT_MUTED}" stroke-width="1" '
        'stroke-dasharray="2 3"/></svg>',
        css=f"display:inline-block;width:{width}px;height:{height}px",
    )
