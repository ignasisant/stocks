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

# Each hand-drawn chart's scrub surface and the hover box it opens. A chart
# with a frame of its own docks the touch reading in a strip that frame
# reserves (frame, tip); the Home spark, a few lines tall, lifts it above.
_TOUCH_CHARTS = [
    (
        "pages/portfolio/portfolio.css",
        ".pf-plot > svg",
        ".pf-scrub > .pf-tip.pf-tip-x",
        ".pf-scrub",
    ),
    ("pages/ticker/ticker.css", ".tk-svg", ".tk-plot .tk-tip", ".tk-plot"),
    ("pages/home/home.css", ".hm-spark-wrap", ".hm-spark-tip", None),
]


def _touch_rule(css: str, selector: str) -> str | None:
    block = re.search(r"@media \(hover: none\) \{(.*?)\n\}", css, re.S)
    if not block:
        return None
    rule = re.search(rf"(?m)^\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", block.group(1))
    return rule.group(1) if rule else None


def test_charts_scrub_under_a_finger():
    """On a phone a chart is read by dragging a finger across it: the surface
    must keep vertical scrolling but own the sideways drag, a held finger must
    not select its labels or open iOS's callout, and the reading must open
    clear of the fingertip wherever the device cannot hover — in a strip at
    the top of the chart's own frame, its height reserved so nothing jumps and
    nothing above the chart is covered, or above a frameless spark."""
    for path, surface, tip, frame in _TOUCH_CHARTS:
        css = (APP / path).read_text()
        rules = _block(css, surface)
        assert re.search(r"touch-action\s*:\s*pan-y", rules), (path, surface)
        assert re.search(r"-webkit-touch-callout\s*:\s*none", rules), (path, surface)
        assert re.search(r"(?m)^\s*user-select\s*:\s*none", rules), (path, surface)
        touch = _touch_rule(css, tip)
        assert touch is not None, (path, tip)
        if frame is None:
            assert re.search(r"bottom\s*:\s*calc\(100%", touch), (path, tip)
            continue
        assert re.search(r"(?m)^\s*top\s*:\s*0\s*;", touch), (path, tip)
        assert re.search(r"(?m)^\s*height\s*:", touch), (path, tip)
        assert re.search(r"overflow\s*:\s*hidden", touch), (path, tip)
        reserve = _touch_rule(css, frame)
        assert reserve and re.search(r"padding-top\s*:", reserve), (path, frame)


# Every control measured under 44px at 390px, and where its touch sizing lives.
_TOUCH_TARGETS = [
    ("pages/portfolio/portfolio.css", ".pf-seg button", r"min-height\s*:\s*44px"),
    ("pages/portfolio/portfolio.css", ".pf-legend-btn", r"min-height\s*:\s*44px"),
    ("pages/ticker/ticker.css", ".tk-legend-btn", r"min-height\s*:\s*44px"),
    ("ui/ui.css", ".ag-toggle", r"min-height\s*:\s*44px"),
    ("pages/earnings/earnings.css", ".earn-seg button", r"min-height\s*:\s*44px"),
    ("pages/earnings/earnings.css", ".earn-chip::before", r"inset\s*:\s*-4px"),
    ("pages/home/home.css", ".hm-seg", r"min-height\s*:\s*44px"),
    ("pages/home/home.css", ".hm-link::before", r"inset\s*:\s*-14px"),
    ("pages/home/home.css", ".hm-customize::before", r"inset\s*:\s*-8px"),
    ("pages/sentiment/sentiment.css", ".sn-tab", r"min-height\s*:\s*44px"),
    ("pages/sector/sector.css", ".ag-sec-controls > summary", r"min-height\s*:\s*44px"),
    ("pages/profile/styles.ts", ".pr-signout", r"min-height\s*:\s*44px"),
    ("pages/profile/styles.ts", ".pr-more > summary", r"min-height\s*:\s*44px"),
    ("chat/chat.css", ".ag-chat-thumb", r"min-height\s*:\s*44px"),
    ("chat/chat.css", ".ag-chat-why-chips .ag-chat-chip", r"min-height\s*:\s*44px"),
]


def test_controls_reach_a_finger():
    """A fingertip is ~44px: the small controls (period buttons, chips, legend
    rows, links, folds) grow, or gain an invisible inset, wherever the pointer
    is coarse, and stay as compact as they were under a mouse."""
    for path, selector, rule in _TOUCH_TARGETS:
        css = (APP / path).read_text()
        coarse = re.findall(r"@media \(pointer: coarse\) \{(.*?)\n\}", css, flags=re.S)
        assert any(selector in block and re.search(rule, block) for block in coarse), (
            path,
            selector,
        )


def test_shell_respects_phone_chrome():
    """The document draws under the notch (`viewport-fit=cover`), so what is
    fixed to an edge pads itself by the safe area; the shell's height is the
    dynamic viewport's; and the page's foot clears the tab bar plus the
    assistant's launcher, which would otherwise sit on the last row."""
    html = (APP.parent / "index.html").read_text()
    assert "viewport-fit=cover" in html
    assert 'name="theme-color"' in html

    css = STYLES.read_text()
    assert re.search(r"min-height\s*:\s*100dvh", _block(css, ".ag-shell"))
    phone = css[css.index("@media (max-width: 640px)") :]
    main = _block(phone.replace("\n  .", "\n.").replace("\n    ", "\n"), ".ag-main")
    assert "--dock" in main and "safe-area-inset-top" in main
    assert "safe-area-inset-bottom" in phone

    chat = (APP / "chat/chat.css").read_text()
    assert "safe-area-inset-bottom" in _block(chat, ".ag-chat-fab")
    assert re.search(r"bottom\s*:\s*calc\(76px \+ env\(safe-area-inset-bottom\)", chat)


def _stylesheets():
    """Every stylesheet the app ships, comments stripped: the .css files and
    the profile page's CSS-in-TS."""
    files = sorted(APP.rglob("*.css")) + [APP / "pages/profile/styles.ts"]
    for path in files:
        yield (
            path.relative_to(APP),
            re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S),
        )


# Paths allowed below the floor, each with its reason. Empty on purpose: a
# phone reads nothing under 11px, and a decorative mark that wants less should
# say so here rather than slip in.
_TINY_TEXT_ALLOWED: set[str] = set()


def test_no_text_below_the_phone_floor():
    """At 390px 9-10px text is unreadable. `--ag-fs-2xs` (the design token, 11px
    in ds.py) is the floor; a literal size under 11px / 0.6875rem, or a token
    fallback under it, fails here."""
    bad = []
    for path, css in _stylesheets():
        if str(path) in _TINY_TEXT_ALLOWED:
            continue
        for decl in re.findall(r"font(?:-size)?\s*:\s*([^;}]*)", css):
            for num, unit in re.findall(r"(?<![\w.-])(\d*\.?\d+)(px|rem|em)\b", decl):
                px = float(num) * (1 if unit == "px" else 16)
                if px < 11 and not re.search(r"line-height|/\s*" + num, decl):
                    bad.append((str(path), decl.strip()))
    assert not bad, bad


# Rules allowed to stay ungated, with the reason. Empty: a tapped element on a
# phone keeps its :hover style until the next tap elsewhere.
_UNGATED_HOVER_ALLOWED: set[str] = set()


def test_hover_styles_wait_for_a_hovering_device():
    """`:hover` sticks after a tap on a touch screen, so every rule that uses it
    sits inside `@media (hover: hover)`."""
    bad = []
    for path, css in _stylesheets():
        stack: list[str] = []
        pos = 0
        for m in re.finditer(r"[{}]", css):
            if m.group() == "{":
                prelude = css[pos : m.start()].strip()
                if ":hover" in prelude and not any("hover: hover" in p for p in stack):
                    if prelude not in _UNGATED_HOVER_ALLOWED:
                        bad.append((str(path), " ".join(prelude.split())))
                stack.append(prelude)
            elif stack:
                stack.pop()
            pos = m.end()
    assert not bad, bad


# The SVG primitives themselves: they draw whatever frame a caller measured.
_CHART_PRIMITIVES = {"pages/ticker/plot.tsx"}


def test_charts_with_labels_draw_at_their_real_width():
    """A chart laid out in a fixed viewBox and scaled by CSS shrinks its text
    with it: an 11px axis label in a 760-unit frame prints at 5px on a phone.
    Any component that draws SVG text — or builds a ticker `frame()` — measures
    its container (`shell/useWidth`) so one unit is one pixel. Text-free
    sparklines may stretch."""
    for path in sorted(APP.rglob("*.tsx")):
        rel = path.relative_to(APP).as_posix()
        if rel.endswith(".test.tsx") or rel in _CHART_PRIMITIVES:
            continue
        source = path.read_text()
        draws_text = "<text" in source and "viewBox=" in source
        builds_frame = re.search(r"\bframe\(\{", source) is not None
        if draws_text or builds_frame:
            assert "useWidth(" in source, rel
