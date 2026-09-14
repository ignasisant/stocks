"""Markup for the Pulse page's trend rows — level, direction, shape, one line each.

The page this serves started as levels in KPI tiles and percentile captions,
and the levels turned out to be the least useful half of it: a 10-year yield
at 4.79% is a fact, and "+33bp over three months while the curve went nowhere"
is the reading. So every row here carries four things in one line —

    label            what it is
    value            the level, in its own units
    chips            the change over each horizon, coloured by whether that
                     direction is the welcome one for THIS series
    sparkline        the shape the numbers can't show (smooth drift versus a
                     spike and a round trip land on the same 3-month delta)
    state            where it sits in its own trend (up / turning / down)

— and the same row renders a yield, an index, a volatility gauge, a commodity
and a country's inflation, so the reader learns one layout instead of five.

`st.dataframe` cannot do this: it renders no HTML, so a sparkline column would
have to become a base64 data URI in an ImageColumn, and the sign colouring
would be lost. These are read-only rows on a page nobody sorts, so plain HTML
is both simpler and better here — sorting is what the Screener is for.

One CSS block for the whole page, injected via `stocks.web.css` (never
`st.html` directly — DOMPurify drops a style block containing a "<", so no
comment in the sheet below may contain one either).
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass, field

from stocks.web.ds import (
    BORDER,
    BORDER_FOCUS,
    CANDLE_DOWN,
    CANDLE_UP,
    DOWN_COLOR,
    DOWN_FILL,
    FS_2XS,
    FS_MD,
    FS_SM,
    FS_XS,
    RADIUS_PILL,
    RADIUS_SM,
    RADIUS_XS,
    SUCCESS_FILL,
    SURFACE_HOVER,
    SURFACE_SUNKEN,
    TEXT_FAINT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    UP_COLOR,
    WARN_COLOR,
    WARN_EDGE,
    WARN_FILL,
    WARN_FILL_SOFT,
)
from stocks.web.spark import flat_rule, sparkline

# Trend-state pill styling, (background, text, border). The two settled states
# are solid market pills; the two turning ones share the caution amber rather
# than getting a green and a red of their own — a turn is a turn, and painting
# "broke down but recovering" green would read as a buy signal from a page that
# does not give them. They separate on border instead: solid when a rally is
# losing its footing, dashed when a downtrend is recovering. That pair is half
# the value of the column, so it must not collapse into the outer two.
STATE_STYLE = {
    "up": (SUCCESS_FILL, UP_COLOR, "none"),
    "turning_down": (WARN_FILL, WARN_COLOR, f"1px solid {WARN_EDGE}"),
    "turning_up": (WARN_FILL_SOFT, WARN_COLOR, f"1px dashed {WARN_EDGE}"),
    "down": (DOWN_FILL, DOWN_COLOR, "none"),
    "unknown": ("transparent", TEXT_MUTED, "none"),
    # Not a `trend_state` value: the label a row carries when its own series
    # stopped being published, in place of a trend it can no longer claim.
    "stale": ("transparent", TEXT_SECONDARY, f"1px dashed {BORDER_FOCUS}"),
}

# The sparkline takes the state's own direction rather than the sign of its
# first-to-last change: the two must agree, and the state is the reading the
# row is making.
STATE_SPARK = {
    "up": CANDLE_UP,
    "turning_up": CANDLE_UP,
    "turning_down": CANDLE_DOWN,
    "down": CANDLE_DOWN,
}


@dataclass(frozen=True)
class TrendRow:
    """One line of the trend table.

    `chips` are (text, direction) pairs already formatted by the caller — the
    units differ per block (basis points on a yield, percent on an index,
    percentage points on an inflation rate) and only the caller knows which.
    `direction` is +1 for a welcome move, -1 for an unwelcome one and 0 for
    neutral, NOT the sign of the number: a falling credit spread and a rising
    index are both good news and must both be green.
    """

    label: str
    value: str
    # Hover text for the label — what this series actually is. The rows
    # replaced KPI tiles that carried a help tooltip each, and a 10-year TIPS
    # yield is not self-explanatory from its name, so the explanation rides
    # here rather than being dropped.
    hint: str | None = None
    # A second line under the label, always visible. What the row means to
    # THIS reader ("38% de tu cartera cotiza aquí") or what the series is when
    # its name does not say ("Diferencial HY, se abre antes que la bolsa").
    # A tooltip cannot carry either on a phone, where there is no hover.
    sub: str | None = None
    chips: Sequence[tuple[str, int]] = ()
    spark: Sequence[float] = ()
    state: str | None = None
    note: str | None = None
    # Draws the sparkline's zero line — for a series of changes rather than
    # levels, where "which side of zero" is the whole point.
    spark_baseline: float | None = None
    # Dims the whole row without removing it: a series the host has stopped
    # publishing is still a row the reader should see, greyed and labelled,
    # rather than a hole where a gauge used to be.
    dim: bool = False
    extras: Sequence[str] = field(default_factory=tuple)


def css(*, chip_labels: Sequence[str]) -> str:
    """The stylesheet for these rows, sized for `chip_labels` change columns.

    The column count is baked into the grid template because a CSS grid cannot
    read it from the markup, and every block on the page passes the same number
    so the columns line up down the whole page.
    """
    chips = " ".join(["4.2rem"] * len(chip_labels))
    cols = max(len(chip_labels), 2)
    return f"""
    .ag-trend {{ display: flex; flex-direction: column; }}
    .ag-trend-head, .ag-trend-row {{
      display: grid;
      grid-template-columns: minmax(8rem, 1.6fr) 5.4rem {chips} 6rem 7.4rem;
      align-items: center; gap: 0.4rem;
    }}
    .ag-trend-head {{
      font-size: {FS_2XS}; color: {TEXT_MUTED}; text-transform: uppercase;
      letter-spacing: 0.08em; font-weight: 600; padding: 0 0 0.3rem 0;
      border-bottom: 1px solid {BORDER};
    }}
    .ag-trend-row {{ padding: 0.34rem 0.35rem; border-radius: {RADIUS_XS};
                     border-bottom: 1px solid {SURFACE_SUNKEN}; }}
    .ag-trend-row:last-child {{ border-bottom: 0; }}
    .ag-trend-row:hover {{ background: {SURFACE_HOVER}; }}
    .ag-trend-row.ag-dim {{ opacity: 0.55; }}
    .ag-trend-l {{ font-size: {FS_SM}; color: {TEXT_SECONDARY};
                   overflow: hidden; text-overflow: ellipsis;
                   white-space: nowrap; }}
    .ag-trend-lc {{ display: flex; flex-direction: column; gap: 0.05rem;
                    min-width: 0; }}
    .ag-trend-lc .ag-trend-l {{ color: {TEXT_PRIMARY}; font-weight: 500; }}
    .ag-trend-sub {{ font-size: {FS_2XS}; line-height: 1.35; color: {TEXT_MUTED};
                     overflow: hidden; text-overflow: ellipsis;
                     white-space: nowrap; }}
    .ag-trend-v {{ font-size: {FS_SM}; color: {TEXT_PRIMARY}; text-align: right;
                   font-variant-numeric: tabular-nums; }}
    .ag-trend-c {{ font-size: {FS_XS}; text-align: right;
                   font-variant-numeric: tabular-nums; }}
    .ag-trend-s {{ display: flex; justify-content: flex-end; }}
    .ag-spark {{ display: block; }}
    .ag-trend-st {{ font-size: {FS_2XS}; font-weight: 600; text-align: center;
                    justify-self: end; max-width: 100%;
                    padding: 0.15rem 0.45rem; border-radius: {RADIUS_PILL};
                    white-space: nowrap; overflow: hidden;
                    text-overflow: ellipsis; box-sizing: border-box; }}
    .ag-trend-note {{ grid-column: 1 / -1; font-size: {FS_2XS};
                      color: {TEXT_MUTED}; padding: 0 0 0.1rem 0; }}
    .ag-quad {{ border: 1px solid {BORDER}; border-radius: {RADIUS_SM};
                padding: 0.55rem 0.7rem; display: flex; flex-direction: column;
                gap: 0.25rem; }}
    .ag-quad-l {{ font-size: {FS_XS}; color: {TEXT_MUTED}; font-weight: 600;
                  letter-spacing: 0.04em; }}
    .ag-quad-v {{ font-size: {FS_SM}; font-weight: 700; color: {TEXT_PRIMARY}; }}
    .ag-quad-n {{ font-size: {FS_2XS}; color: {TEXT_MUTED}; }}
    .ag-quads {{ display: grid; gap: 0.5rem;
                 grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }}
    @media (max-width: 640px) {{
      /* Eight columns will not fit a 390px screen, so the row becomes two
         lines: what it is, where it stands and its trend on the first, then
         the four horizons with the shape beside them on the second. The
         header row goes: the chips label themselves once the columns are
         gone. */
      .ag-trend-head {{ display: none; }}
      .ag-trend-row {{
        grid-template-columns: repeat({cols}, 1fr) auto;
        gap: 0.3rem 0.4rem; padding: 0.55rem 0;
      }}
      /* The first line is pinned to row 1 so the chips, which place
         themselves, start a second line under it instead of filling the
         gaps in the first. */
      .ag-trend-lc {{ grid-column: 1 / {cols}; grid-row: 1; }}
      .ag-trend-l {{ font-size: {FS_MD}; white-space: normal; }}
      .ag-trend-v {{ grid-column: {cols} / {cols + 1}; grid-row: 1;
                     text-align: right; }}
      .ag-trend-st {{ grid-column: {cols + 1} / {cols + 2}; grid-row: 1;
                      justify-self: end; }}
      .ag-trend-sub {{ white-space: normal; }}
      /* The header is gone, so each change cell labels its own horizon. */
      .ag-trend-c {{ text-align: left; }}
      .ag-trend-c::before {{ content: attr(data-h); display: block;
                             font-size: {FS_2XS}; font-weight: 500;
                             color: {TEXT_FAINT}; }}
    }}
    """


def _chip(text: str, direction: int, label: str = "") -> str:
    """One change cell, carrying the horizon it measures.

    The label rides along as a data attribute rather than as text: on a phone
    the header row is gone, and four bare percentages with no horizons over
    them are four numbers nobody can read. The stylesheet prints it there and
    nowhere else.
    """
    color = (
        CANDLE_UP if direction > 0 else CANDLE_DOWN if direction < 0 else TEXT_MUTED
    )
    return (
        f'<span class="ag-trend-c" data-h="{html.escape(label, quote=True)}" '
        f'style="color:{color}">{html.escape(text)}</span>'
    )


def rows_html(
    rows: Sequence[TrendRow],
    *,
    chip_labels: Sequence[str],
    value_label: str,
    label_label: str,
    spark_label: str,
    state_label: str,
    state_names: dict[str, str],
) -> str:
    """The rows as one self-contained HTML block, header included.

    `state_names` maps a `trend_state` key to its translated pill text; a row
    with `state=None` gets an empty cell, which is what the blocks that have no
    meaningful trend label (an inflation print) pass.
    """
    head = (
        f'<div class="ag-trend-head">'
        f'<span class="ag-trend-l">{html.escape(label_label)}</span>'
        f'<span class="ag-trend-v">{html.escape(value_label)}</span>'
        + "".join(
            f'<span class="ag-trend-c">{html.escape(c)}</span>' for c in chip_labels
        )
        + f'<span class="ag-trend-c">{html.escape(spark_label)}</span>'
        f'<span class="ag-trend-st">{html.escape(state_label)}</span>'
        "</div>"
    )
    body = []
    for row in rows:
        tip = row.hint or row.label
        label = (
            f'<span class="ag-trend-l" title="{html.escape(tip, quote=True)}">'
            f"{html.escape(row.label)}</span>"
        )
        if row.sub:
            label += f'<span class="ag-trend-sub">{html.escape(row.sub)}</span>'
        cells = [
            f'<div class="ag-trend-lc">{label}</div>',
            f'<span class="ag-trend-v">{html.escape(row.value)}</span>',
        ]
        cells += [
            _chip(text, direction, label)
            for (text, direction), label in zip(
                row.chips, chip_labels, strict=False
            )
        ]
        # Pad short chip lists so the sparkline and state columns stay aligned
        # when one series is too young for the longest horizon.
        cells += ['<span class="ag-trend-c"></span>'] * (
            len(chip_labels) - len(row.chips)
        )
        line = sparkline(
            row.spark,
            baseline=row.spark_baseline,
            color=STATE_SPARK.get(row.state or "", TEXT_MUTED),
        )
        cells.append(f'<span class="ag-trend-s">{line or flat_rule()}</span>')
        if row.state:
            back, fore, edge = STATE_STYLE.get(row.state, STATE_STYLE["unknown"])
            text = state_names.get(row.state, "")
            cells.append(
                f'<span class="ag-trend-st" style="background:{back};'
                f'color:{fore};border:{edge}">{html.escape(text)}</span>'
            )
        else:
            cells.append('<span class="ag-trend-st"></span>')
        cells += list(row.extras)
        if row.note:
            cells.append(
                f'<span class="ag-trend-note">{html.escape(row.note)}</span>'
            )
        klass = "ag-trend-row ag-dim" if row.dim else "ag-trend-row"
        body.append(f'<div class="{klass}">{"".join(cells)}</div>')
    return f'<div class="ag-trend">{head}{"".join(body)}</div>'


def quad_html(cards: Sequence[tuple[str, str, str]]) -> str:
    """A row of small (label, value, note) cards — the derived trend readings.

    Trend breadth, the stock/bond correlation and the rates quadrant are each
    one sentence's worth of number, and none of them fits the row layout above:
    they have no level, no horizons and no shape of their own.
    """
    tiles = [
        '<div class="ag-quad">'
        f'<span class="ag-quad-l">{html.escape(label)}</span>'
        f'<span class="ag-quad-v">{html.escape(value)}</span>'
        f'<span class="ag-quad-n">{html.escape(note)}</span>'
        "</div>"
        for label, value, note in cards
    ]
    return f'<div class="ag-quads">{"".join(tiles)}</div>'
