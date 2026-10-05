"""The design system in Python: the tokens and the CSS they emit.

Single source of truth for every color, radius, elevation and type step our
own HTML — the landing documents, the React shell's `/api/v1/design` tokens —
paints with. Values are Amphora Web DS tokens.

Nothing outside this module may write a raw hex: Python code imports these
names, CSS reads the `--ag-*` custom properties `ds_vars_css` emits from them,
so a token change lands everywhere at once. This is the bottom of the web
layer — it imports no other `stocks.web` module at all, so everything else is
free to import it.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────── TopStocks design tokens

# Semantic — market direction. Reserved for price change only; the light
# success/critical fills are the variants that read on a dark surface.
UP_COLOR = "#DBFFD2"    # alza — market gain (DS success fill)
DOWN_COLOR = "#FFD2CB"  # baja — market loss (DS critical fill)
SUCCESS_FILL = "#2A8200"    # DS success highlight — gain pill/badge background
DOWN_FILL = "#8C1F00"       # DS market-loss pill background (pairs with DOWN_COLOR)
CRITICAL_FILL = "#CC402F"   # DS critical stroke — error states, loss chart marks
WARN_COLOR = "#F4C600"      # aviso — caution (DS caution highlight)
WARN_ORANGE = "#EF752E"     # warning (DS orange) — secondary chart accent
INFO_COLOR = "#7290F0"      # info — chart lines, informational (DS blue 500)
INFO_DEEP = "#4667D0"       # DS chart blue 600 — second info step

# Brand purple ramp. BRAND_CTA/BRAND_ACCENT keep their historic names; the
# numbered steps match the DS scale.
PURPLE_900 = "#301263"  # active nav row / active chip fill
PURPLE_800 = "#4E2092"  # brand badge fill, active chip border
PURPLE_700 = "#6A2EBF"  # hover state on purple fills
BRAND_CTA = "#7F3FE8"   # purple 600 — CTAs, primary buttons, focus rings
BRAND_ACCENT = "#A98EF7"  # purple 500 — accents, active iconography, links
PURPLE_400 = "#C6B7FB"  # accent text on purple fills
PURPLE_300 = "#DED7FD"  # primary text on purple fills, mono/code

# Neutral ramp — surfaces, borders, text.
SURFACE_PAGE = "#18161C"    # neutral-950 — page and sidebar background
SURFACE_CARD = "#28262D"    # neutral-900 — elevated surface (cards, inputs)
SURFACE_HOVER = "#333139"   # DS hover step — nav rows, table rows, list buttons
BORDER = "#3B3942"          # neutral-800 — borders, dividers, table rules
RULE_PANEL = "#232128"      # hairline one step under BORDER — the assistant
                            # drawer's internal dividers (header rows, the
                            # onboarding list's rules, the composer's edge),
                            # where a full BORDER reads as a box seam
BORDER_FOCUS = "#48454F"    # DS focus/hover border — outlined controls on hover
TEXT_PRIMARY = "#F9F9FA"    # neutral-50 — primary text (also the logo plate)
TEXT_SECONDARY = "#B3AFBD"  # neutral-400 — widget labels, secondary body
TEXT_MUTED = "#827F8C"      # neutral-500 — captions, chart axes, company names
TEXT_FAINT = "#696673"      # neutral-600 — section headers, separators, rules

# Landing page. The public marketing surface needs two steps the app chrome
# never asked for: a card fill between SURFACE_PAGE and SURFACE_CARD, and a
# mid-tone green/red pair for figures. The DS success/critical pairs are a dark
# fill plus a light tint, which reads as a badge rather than as a number, so
# these follow the candle hues instead. Used only by landing.py.
SURFACE_RAISED = "#1F1D24"      # landing card fill — between page and card
SURFACE_BAND = "#1B1920"        # alternating full-width section band
SURFACE_BRAND_BAND = "#221B31"  # provenance band — purple-tinted page
BORDER_BRAND_BAND = "#3B3157"   # provenance band edge
LANDING_UP = "#2AC77E"          # positive figures, "fact" provenance tag
LANDING_DOWN = "#F0526A"        # negative figures, rejected import rows
LANDING_INFO = "#4C8DFF"        # benchmark series, "consensus" provenance tag
LANDING_WARN = "#F5B940"        # import warnings, deferred loss, disclaimers
ON_BRAND = "#FEFEFF"            # text on a BRAND_CTA fill

# Back-compat aliases — every green/red profit-loss cue routes through these.
PROFIT_COLOR, LOSS_COLOR = UP_COLOR, DOWN_COLOR

# Price-chart series hues, straight from the Aguait DS chart spec (section 07):
# mid-tone candle green/red that carry on a dark surface without stealing
# UP/DOWN (reserved for text and badges), plus the SMA overlay amber/blue the
# spec fixes at 1.5px line weight.
CANDLE_UP = "#7ED28C"    # bullish candles — DS success, mid step
CANDLE_DOWN = "#F0897E"  # bearish candles — DS critical, mid step
SMA_FAST = "#F2A33C"     # SMA20 overlay — DS chart amber (softer than WARN_ORANGE)
SMA_SLOW = "#6E8FF0"     # SMA50 overlay + results markers — DS chart blue
# The DS chart spec fixes two overlay hues, and the third average needs one the
# eye reads as slower rather than as a third signal: neutral-400, the same step
# the secondary text uses, sits under the amber/blue pair without competing
# with them — and cannot be mistaken for a candle, the purple price line, or
# the darker gridlines.
SMA_LONG = "#B3AFBD"     # SMA200 overlay — neutral-400, the quiet trend line
EVENT_LINE = TEXT_FAINT  # dashed corporate-event verticals + crosshair — neutral-600

# Caution fills, from the Pulse canvas. WARN_COLOR is a text hue and burns on a
# dark surface as a fill, so a caution badge needs its own opaque steps: a deep
# amber ground, its one-step-lighter edge, and a near-black wash for the badge
# that must read as caution without competing with the solid green/red pills
# beside it.
WARN_FILL = "#3D3000"       # caution badge ground (turning-down pill)
WARN_EDGE = "#6B5C00"       # its border, one step up
WARN_FILL_SOFT = "#241F04"  # softer ground — turning-up pill, warning panels

# Alpha variants. Written as rgba() because Plotly's SVG attributes predate
# 8-digit hex; the base hue is always the token named in the comment.
PROFIT_COLOR_MUTED = "rgba(219,255,210,0.45)"  # UP_COLOR @ 45%
LOSS_COLOR_MUTED = "rgba(255,210,203,0.45)"    # DOWN_COLOR @ 45%
PROFIT_BAND = "rgba(42,130,0,0.35)"      # SUCCESS_FILL @ 35% — area fills
LOSS_BAND = "rgba(204,64,47,0.25)"       # CRITICAL_FILL @ 25% — area fills
ACCENT_BAND = "rgba(169,142,247,0.15)"   # BRAND_ACCENT @ 15% — forecast bands
ACCENT_AREA = "rgba(169,142,247,0.22)"   # BRAND_ACCENT @ 22% — price-line area top
WARN_BAND = "rgba(244,198,0,0.18)"       # WARN_COLOR @ 18% — caution chip fill
SURFACE_SUNKEN = "rgba(59,57,66,0.25)"   # BORDER @ 25% — out-of-range cells
RULE_SOFT = "rgba(59,57,66,0.5)"         # BORDER @ 50% — dense row dividers
SURFACE_PAGE_HAZE = "rgba(24,22,28,0.92)"  # SURFACE_PAGE @ 92% — sticky topbar
SURFACE_PAGE_VEIL = "rgba(24,22,28,0.85)"  # SURFACE_PAGE @ 85% — touch chart readout
CTA_GLOW = "rgba(127,63,232,0.25)"       # BRAND_CTA @ 25% — launcher shadow
CTA_HALO = "rgba(127,63,232,0.4)"        # BRAND_CTA @ 40% — avatar shadow
CTA_TINT = "rgba(127,63,232,0.16)"       # BRAND_CTA @ 16% — user bubble fill
CTA_TINT_EDGE = "rgba(127,63,232,0.35)"  # BRAND_CTA @ 35% — user bubble border
SKELETON_BASE = "rgba(105,102,115,0.25)"  # TEXT_FAINT @ 25% — shimmer trough
SKELETON_HI = "rgba(105,102,115,0.45)"    # TEXT_FAINT @ 45% — shimmer crest
TRANSPARENT = "rgba(0,0,0,0)"            # Plotly canvas — inherit the surface

# Elevation. The DS has no shadow token, so the app defines three steps and
# uses nothing else; all three are neutral black over the purple-tinted
# surfaces, matching the design's soft-dark cards. The two bare colors exist
# for the side-anchored panels (the sidebar rail, the chat drawer), whose
# shadow must throw sideways — they compose their own offsets and take only
# the tint from here, so every elevation in the app still shares one palette.
SHADOW_COLOR = "rgba(0,0,0,0.35)"                # card-level tint
SHADOW_COLOR_STRONG = "rgba(0,0,0,0.5)"          # overlay-level tint
SHADOW_CARD = f"0px 2px 4px {SHADOW_COLOR}"      # section cards
SHADOW_HOVER = "0px 8px 15px rgba(0,0,0,0.45)"   # Plotly hover box — DS dialog step
SHADOW_OVERLAY = "0px 8px 15px rgba(0,0,0,0.45)"  # dropdowns, popovers — DS dialog step

# Radius scale — 8px is the middle step.
RADIUS_XS = "4px"       # logo chips, calendar chips, small badges
RADIUS_NAV = "6px"      # sidebar nav rows, segmented-selector chips (DS "6 · nav")
RADIUS_SM = "8px"       # inputs, buttons, table cells
RADIUS_MD = "12px"      # inset tiles, chat bubbles, Plotly hover box
RADIUS_LG = "16px"      # section cards
RADIUS_PILL = "9999px"  # delta pills
# Plotly wants a number, not a CSS length: bar-cap radius in px, the "6 · nav"
# step. Plotly clamps it to half the bar width (thin monthly bars stay
# square-ish) and rounds only the ends of a stack, never the joins inside it.
BAR_RADIUS = 6

# Type faces. `seo.FONTS_HREF` loads them into every document the app serves,
# but each page still has to name the family itself — so it is a token, not a
# literal repeated per page. Each keeps its own fallback stack: the webfont
# arrives over the network and the first paint must not be a different metric.
FONT_BODY = "'Instrument Sans', system-ui, -apple-system, sans-serif"
FONT_MONO = "'Martian Mono', ui-monospace, monospace"

# Type scale — the DS heading sizes (28/22/18/16/14/12) extended down with
# the three chrome steps the app needs. px, like the DS scale, so a root
# font-size change never silently rescales our own HTML.
FS_2XS = "11px"   # nav-section caps, dense calendar chips — DS floor; a phone reads nothing smaller
FS_XS = "11px"    # captions, tile labels, small pills
FS_SM = "12px"    # metric labels, muted secondary lines
FS_MD = "13px"    # nav rows, selector chips, table cells
FS_BASE = "14px"  # body
FS_LG = "16px"    # tile values
FS_XL = "18px"    # h3 / KPI figures
FS_2XL = "22px"   # h2
FS_3XL = "28px"   # h1
FS_DISPLAY = "32px"  # hero price figure (Epilogue), one step above h1

# Icon sizing is its own dimension, not a type step: a Material glyph takes
# its size from font-size, and the wrapper spans' width/height must match it
# exactly or the row height shifts. One token keeps all three in step.
ICON_NAV = "1.6rem"  # sidebar nav glyphs, identical in every rail state

# Diverging ramp for correlation heatmaps. The DS has a sequential purple
# ramp (SEQUENTIAL_SCALE) but no diverging one, so this is built
# from the DS semantic pair: brand blue for inverse, neutral-800 for
# uncorrelated, critical for tightly correlated. Plotly colorscale form.
DIVERGING_SCALE = [
    [0.0, INFO_DEEP],      # strongly inverse
    [0.25, INFO_COLOR],
    [0.5, BORDER],         # uncorrelated
    [0.75, CRITICAL_FILL],
    [1.0, DOWN_COLOR],     # moves together
]

# Sequential ramp for magnitude fills (choropleths). The DS brand purple ramp,
# dark→light. Starts at PURPLE_800, not
# 900: the bottom step must still separate from the SURFACE_PAGE land fill a
# globe paints under countries with no holdings. Plotly colorscale form.
SEQUENTIAL_SCALE = [
    [0.0, PURPLE_800],
    [0.25, PURPLE_700],
    [0.5, BRAND_CTA],
    [0.75, BRAND_ACCENT],
    [1.0, PURPLE_300],
]

# DS chart magenta — categorical slot 3, with no other DS role. Named here so
# the palette below stays hex-free like everything else outside this block.
CHART_MAGENTA = "#C54EA4"

# Categorical series palette. Fixed order, never cycled: a chart with more
# series than this folds the tail into one muted "Others" bucket instead of
# inventing a 9th hue.
CATEGORICAL_COLORS = [
    BRAND_ACCENT,   # purple 500
    INFO_COLOR,     # blue 500
    CHART_MAGENTA,
    WARN_COLOR,     # yellow
    WARN_ORANGE,
    INFO_DEEP,      # blue 600
    PURPLE_300,
    TEXT_MUTED,
]

# Brand exception, deliberately NOT a DS neutral: Google's sign-in guidelines
# require the "G" mark on pure white, so auth.py's button tile opts out of the
# ramp. It is declared here so an audit finds it named instead of as a stray
# literal, and so it stays the only such exception.
BRAND_GOOGLE_TILE = "#FFFFFF"


def tokens() -> dict[str, str]:
    """Every design token, by its `--ag-*` name without the prefix.

    The dict rather than the stylesheet, because not every consumer is CSS: a
    chart built in JavaScript picks its colours from here, and the React shell
    reads it over HTTP (`api/routes/design.py`). One source of truth, three
    renderings.
    """
    return {
        # color — semantic
        "up": UP_COLOR, "down": DOWN_COLOR,
        "success-fill": SUCCESS_FILL, "down-fill": DOWN_FILL,
        "critical-fill": CRITICAL_FILL,
        "warn": WARN_COLOR, "warn-orange": WARN_ORANGE,
        "warn-fill": WARN_FILL, "warn-edge": WARN_EDGE,
        "warn-fill-soft": WARN_FILL_SOFT,
        "info": INFO_COLOR, "info-deep": INFO_DEEP,
        # color — chart series. Published because a second front end draws
        # these same series and must not keep its own copy of the hexes.
        "candle-up": CANDLE_UP, "candle-down": CANDLE_DOWN,
        "sma-fast": SMA_FAST, "sma-slow": SMA_SLOW, "sma-long": SMA_LONG,
        # color — brand
        "purple-900": PURPLE_900, "purple-800": PURPLE_800,
        "purple-700": PURPLE_700, "brand-cta": BRAND_CTA,
        "brand-accent": BRAND_ACCENT, "purple-400": PURPLE_400,
        "purple-300": PURPLE_300,
        # color — neutral
        "surface-page": SURFACE_PAGE, "surface-card": SURFACE_CARD,
        "surface-hover": SURFACE_HOVER,
        "border": BORDER, "border-focus": BORDER_FOCUS,
        "rule-panel": RULE_PANEL,
        "text-primary": TEXT_PRIMARY,
        "text-secondary": TEXT_SECONDARY, "text-muted": TEXT_MUTED,
        "text-faint": TEXT_FAINT,
        # color — landing surface
        "surface-raised": SURFACE_RAISED, "surface-band": SURFACE_BAND,
        "surface-brand-band": SURFACE_BRAND_BAND,
        "border-brand-band": BORDER_BRAND_BAND,
        "landing-up": LANDING_UP, "landing-down": LANDING_DOWN,
        "landing-info": LANDING_INFO, "landing-warn": LANDING_WARN,
        "on-brand": ON_BRAND,
        # color — alpha variants
        "profit-band": PROFIT_BAND, "loss-band": LOSS_BAND,
        "warn-band": WARN_BAND,
        "accent-band": ACCENT_BAND, "accent-area": ACCENT_AREA,
        "surface-sunken": SURFACE_SUNKEN, "rule-soft": RULE_SOFT,
        "surface-page-haze": SURFACE_PAGE_HAZE,
        "surface-page-veil": SURFACE_PAGE_VEIL,
        "cta-glow": CTA_GLOW, "cta-halo": CTA_HALO,
        "cta-tint": CTA_TINT, "cta-tint-edge": CTA_TINT_EDGE,
        "skeleton-base": SKELETON_BASE, "skeleton-hi": SKELETON_HI,
        "brand-google-tile": BRAND_GOOGLE_TILE,
        # elevation
        "shadow-card": SHADOW_CARD, "shadow-hover": SHADOW_HOVER,
        "shadow-overlay": SHADOW_OVERLAY,
        "shadow-color": SHADOW_COLOR,
        "shadow-color-strong": SHADOW_COLOR_STRONG,
        # radius
        "radius-xs": RADIUS_XS, "radius-nav": RADIUS_NAV,
        "radius-sm": RADIUS_SM,
        "radius-md": RADIUS_MD, "radius-lg": RADIUS_LG,
        "radius-pill": RADIUS_PILL,
        # type
        "font-body": FONT_BODY, "font-mono": FONT_MONO,
        "fs-2xs": FS_2XS, "fs-xs": FS_XS, "fs-sm": FS_SM,
        "fs-md": FS_MD, "fs-base": FS_BASE, "fs-lg": FS_LG, "fs-xl": FS_XL,
        "fs-2xl": FS_2XL, "fs-3xl": FS_3XL, "fs-display": FS_DISPLAY,
        # icon
        "icon-nav": ICON_NAV,
    }


def ds_vars_css() -> str:
    """`:root` custom properties for every token, as a `<style>` block.

    Our CSS lives in string literals scattered across pages, most of them plain
    (non-f) triple-quoted blocks full of CSS braces — threading Python values
    through them would mean escaping every `{`. Emitting the tokens once as
    `--ag-*` custom properties instead lets that CSS read `var(--ag-border)`
    and stay literal, while Python keeps a single source of truth.
    `landing_static` inlines it into the plain HTML documents, and the server
    into the pages it renders itself.
    """
    body = "".join(f"--ag-{k}:{v};" for k, v in tokens().items())
    return f"<style>:root{{{body}}}</style>"
