"""Sparklines and trend rows — the markup half of the Pulse page.

These render inside `st.html`, which sanitises with DOMPurify under
`USE_PROFILES: {html: true}` — a profile with no SVG in it. So the tests here
pin two things: the geometry (a sparkline that misreads its own scale draws a
plausible-looking wrong shape, which no exception would catch) and the fact
that nothing leaves these modules as markup the sanitiser would delete. The
second half is not hypothetical: an inline `svg` is removed silently and the
cell simply renders empty, which is what these tables did until the picture
moved into a data URI.
"""

import base64
import re

import pytest

from stocks.web import trend_ui
from stocks.web.spark import HEIGHT, PAD, WIDTH, flat_rule, sparkline, sparkline_svg
from stocks.web.trend_ui import TrendRow

# Everything DOMPurify keeps under Streamlit's profile and these modules are
# allowed to emit. Note what is NOT in it: `svg` and its children reach the
# page inside a data URI, never as markup.
ALLOWED_TAGS = {"div", "span"}


def _tags(markup: str) -> set[str]:
    return set(re.findall(r"<([a-zA-Z]+)", markup))


def _decoded(markup: str) -> str:
    """The SVG carried by the first data URI in `markup`."""
    payload = re.search(r"base64,([^&]+)&quot;", markup)
    assert payload, markup
    return base64.b64decode(payload.group(1)).decode()


def _points(markup: str) -> list[tuple[float, float]]:
    raw = re.search(r'points="([^"]+)"', markup).group(1)
    return [tuple(float(n) for n in pair.split(",")) for pair in raw.split()]


# ------------------------------------------------------------------ sparkline
def test_sparkline_spans_its_box_and_orders_oldest_first():
    points = _points(sparkline_svg([1.0, 2.0, 3.0]))
    xs = [x for x, _ in points]
    assert xs == sorted(xs)
    assert xs[0] == pytest.approx(PAD)
    assert xs[-1] == pytest.approx(WIDTH - PAD)


def test_sparkline_puts_high_values_at_the_top():
    """SVG's y axis grows downward, so this is an easy sign error to ship."""
    (_, y_low), _, (_, y_high) = _points(sparkline_svg([1.0, 2.0, 3.0]))
    assert y_high < y_low
    assert y_high == pytest.approx(PAD)
    assert y_low == pytest.approx(HEIGHT - PAD)


def test_sparkline_scales_to_its_own_range():
    """Each line fills its own box: these are shapes, not comparable heights."""
    small = _points(sparkline_svg([100.0, 101.0]))
    large = _points(sparkline_svg([100.0, 200.0]))
    assert [y for _, y in small] == [y for _, y in large]


def test_a_flat_series_draws_down_the_middle():
    """min == max would divide by zero."""
    points = _points(sparkline_svg([5.0, 5.0, 5.0]))
    assert all(y == pytest.approx(HEIGHT / 2) for _, y in points)


def test_sparkline_colours_by_the_whole_window_not_the_last_tick():
    """The line's own direction is the reading; a final uptick is noise."""
    from stocks.web.ds import CANDLE_DOWN, CANDLE_UP

    assert CANDLE_DOWN in sparkline_svg([10.0, 5.0, 4.0, 4.5])
    assert CANDLE_UP in sparkline_svg([4.0, 9.0, 10.0, 9.5])


def test_sparkline_of_one_point_draws_nothing():
    """A dot would imply a trend the caller does not have."""
    assert sparkline_svg([1.0]) == ""
    assert sparkline_svg([]) == ""


def test_sparkline_drops_nan_before_measuring():
    assert _points(sparkline_svg([1.0, float("nan"), 3.0])) == _points(
        sparkline_svg([1.0, 3.0])
    )


def test_baseline_is_drawn_only_when_it_falls_inside_the_range():
    assert "<line" in sparkline_svg([-1.0, 0.5, 1.0], baseline=0.0)
    assert "<line" not in sparkline_svg([1.0, 2.0, 3.0], baseline=0.0)


def test_nothing_reaches_the_page_as_markup_the_sanitiser_deletes():
    """The picture travels as a data URI; the page only sees a span."""
    for markup in (sparkline([1.0, 2.0, 3.0], baseline=1.5), flat_rule()):
        assert _tags(markup) <= ALLOWED_TAGS
        assert "<svg" not in markup
        assert "data:image/svg+xml;base64," in markup


def test_the_data_uri_carries_the_picture_that_was_drawn():
    assert _points(_decoded(sparkline([1.0, 2.0, 3.0]))) == _points(
        sparkline_svg([1.0, 2.0, 3.0])
    )


def test_an_empty_series_embeds_nothing_at_all():
    """No series, no span: the cell falls back to the placeholder rule."""
    assert sparkline([1.0]) == ""


def test_flat_rule_holds_the_column_width():
    """One unreadable row must not shift every sparkline beside it."""
    assert f"width:{WIDTH}px" in flat_rule()
    assert f'width="{WIDTH}"' in _decoded(flat_rule())


# ------------------------------------------------------------------ trend rows
def _row(**kw) -> str:
    defaults = dict(
        chip_labels=["1w", "1m"],
        label_label="Name",
        value_label="Level",
        spark_label="90d",
        state_label="Trend",
        state_names={"up": "Uptrend", "down": "Downtrend"},
    )
    return trend_ui.rows_html(**{**defaults, **kw})


def test_short_chip_lists_are_padded_so_the_columns_stay_aligned():
    """A series too young for the longest horizon must not shift the row.

    The grid has one column per chip label; a row supplying fewer would slide
    its sparkline and state pill left into the change columns.
    """
    labels = ["1w", "1m", "3m", "12m"]
    markup = _row(
        chip_labels=labels,
        rows=[TrendRow(label="X", value="1", chips=[("+1%", 1)])],
    )
    row = markup.split('class="ag-trend-row"')[1]
    assert row.count('class="ag-trend-c"') == len(labels)


def test_chip_direction_colours_by_welcome_not_by_sign():
    """A tightening credit spread and a rising index are both good news."""
    from stocks.web.ds import CANDLE_DOWN, CANDLE_UP

    good = _row(rows=[TrendRow(label="X", value="1", chips=[("-13bp", 1)])])
    bad = _row(rows=[TrendRow(label="X", value="1", chips=[("-13bp", -1)])])
    assert CANDLE_UP in good and CANDLE_DOWN not in good
    assert CANDLE_DOWN in bad and CANDLE_UP not in bad


def test_a_neutral_chip_is_muted():
    from stocks.web.ds import TEXT_MUTED

    assert TEXT_MUTED in _row(
        rows=[TrendRow(label="X", value="1", chips=[("2.4%", 0)])]
    )


def test_the_hint_becomes_the_label_tooltip():
    """The rows replaced KPI tiles that each carried a help tooltip."""
    markup = _row(
        rows=[TrendRow(label="US 10y real", value="2.44%", hint="TIPS yield")]
    )
    assert 'title="TIPS yield"' in markup


def test_the_label_is_its_own_tooltip_without_a_hint():
    assert 'title="US 10y"' in _row(rows=[TrendRow(label="US 10y", value="4.79%")])


def test_the_hint_also_opens_a_dot_beside_the_name():
    """A native title needs a hover and a second of patience. The dot is the
    affordance: visible, focusable, and readable on a phone with a tap."""
    markup = _row(rows=[TrendRow(label="VIX", value="17.7", hint="Fear, priced")])
    assert 'class="ag-trend-i" tabindex="0" data-tip="Fear, priced"' in markup
    # Outside the label span, which clips its own overflow for the ellipsis.
    assert '</span><span class="ag-trend-i"' in markup


def test_a_row_with_nothing_to_explain_gets_no_dot():
    """A dot on every row teaches the reader to stop looking at dots."""
    assert "ag-trend-i" not in _row(rows=[TrendRow(label="Spain", value="4.5%")])


def test_the_dot_text_is_escaped():
    markup = _row(rows=[TrendRow(label="X", value="1", hint='S&P "puts"')])
    assert "S&amp;P &quot;puts&quot;" in markup


def test_a_row_without_a_state_still_fills_the_state_cell():
    markup = _row(rows=[TrendRow(label="Spain", value="4.5%")])
    assert markup.count('class="ag-trend-st"') == 2  # header plus the empty cell


def test_a_row_with_no_sparkline_gets_the_placeholder_rule():
    markup = _row(rows=[TrendRow(label="X", value="1", spark=[1.0])])
    drawn = _decoded(markup)
    assert 'stroke-dasharray="2 3"' in drawn
    assert "<polyline" not in drawn


def test_labels_and_values_are_escaped():
    markup = _row(rows=[TrendRow(label="S&P 500", value="1")])
    assert "S&amp;P 500" in markup
    assert "S&P 500" not in markup


def test_rows_html_stays_inside_the_sanitiser_allowlist():
    markup = _row(
        rows=[
            TrendRow(
                label="X", value="1", chips=[("+1%", 1)], spark=[1.0, 2.0, 3.0],
                state="up", note="stale",
            )
        ]
    )
    assert _tags(markup) <= ALLOWED_TAGS


def test_css_declares_one_column_per_chip_label():
    """The grid template cannot count the markup, so the count is passed in.

    Label, level, one column per chip, the sparkline and the state pill — the
    widths themselves are the design's business and may change; the count is
    what keeps the tables lined up down the page.
    """
    sheet = trend_ui.css(chip_labels=["a", "b", "c"])
    template = re.search(r"grid-template-columns:([^;]+);", sheet).group(1)
    # A minmax() track holds a space of its own, so collapse it to one token
    # before counting.
    assert len(re.sub(r"minmax\([^)]*\)", "track", template).split()) == 3 + 4


def test_the_stylesheet_carries_no_angle_bracket():
    """DOMPurify drops an entire style block containing one, silently."""
    assert "<" not in trend_ui.css(chip_labels=["a", "b", "c", "d"])


def test_quad_html_escapes_and_renders_one_card_per_entry():
    markup = trend_ui.quad_html(
        [("Breadth", "12/13", "above their 200-session average"), ("A&B", "1", "n")]
    )
    assert markup.count('class="ag-quad"') == 2
    assert "A&amp;B" in markup
    assert _tags(markup) <= ALLOWED_TAGS
