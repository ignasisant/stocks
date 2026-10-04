"""Layout rules for the React shell that a screenshot would catch too late."""

import re
from pathlib import Path

STYLES = Path(__file__).resolve().parents[1] / "frontend/app/src/styles.css"


def _block(css: str, selector: str) -> str:
    match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    assert match, f"{selector} not found in styles.css"
    return match.group(1)


def test_main_column_is_never_capped():
    """On a desktop the page runs to the right edge; only an open chat drawer
    takes room (it pads the shell), never a margin kept up front."""
    main = re.sub(r"/\*.*?\*/", "", _block(STYLES.read_text(), ".ag-main"), flags=re.S)
    assert not re.search(r"(?m)^\s*max-width\s*:", main)


APP = STYLES.parent

# Each hand-drawn chart's scrub surface, and the hover box it opens.
_TOUCH_CHARTS = [
    ("pages/portfolio/portfolio.css", ".pf-plot > svg", ".pf-tip.pf-tip-x"),
    ("pages/ticker/ticker.css", ".tk-svg", ".tk-tip"),
    ("pages/home/home.css", ".hm-spark-wrap", ".hm-spark-tip"),
]


def test_charts_scrub_under_a_finger():
    """On a phone a chart is read by dragging a finger across it: the surface
    must keep vertical scrolling but own the sideways drag, a held finger must
    not select its labels or open iOS's callout, and the box must open clear
    of the fingertip — above the plot — wherever the device cannot hover."""
    for path, surface, tip in _TOUCH_CHARTS:
        css = (APP / path).read_text()
        rules = _block(css, surface)
        assert re.search(r"touch-action\s*:\s*pan-y", rules), (path, surface)
        assert re.search(r"-webkit-touch-callout\s*:\s*none", rules), (path, surface)
        assert re.search(r"(?m)^\s*user-select\s*:\s*none", rules), (path, surface)
        touch = re.search(
            rf"@media \(hover: none\) \{{\s*{re.escape(tip)}\s*\{{([^}}]*)\}}", css
        )
        assert touch, (path, tip)
        assert re.search(r"bottom\s*:\s*calc\(100%", touch.group(1)), (path, tip)
