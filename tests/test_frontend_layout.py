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
