# Interface design — Aguait (React app, frontend/app)

Decisions already made. Apply them; do not re-derive. Tokens come from the
Aguait design system (`web/ds.py` → `--ag-*` on `:root`, read in JS through
`shell/theme.ts` `token()` / `chart()`). Plain CSS per page (`portfolio.css`),
no Tailwind.

## Direction

- **Who:** one aggressive long-term investor checking their own book — often
  between other things, on desktop or phone. Programmer; wants the number and
  the assumption behind it, not marketing.
- **Feel:** a calm dark workbench. Dense but not cramped. Numbers lead; chrome
  recedes. Honest about uncertainty (ranges, not promises).
- **Signature:** figures always read against the money that cost them
  (return on money put in), and forecasts drawn as a shaded fan, never as
  confident lines.
- **Dark only, on purpose.** One theme: a dark workbench is the product's
  feel, and every token, chart colour and contrast check is tuned against it.
  No `prefers-color-scheme` switch and no light tokens in `ds.py`. The MCP
  connector views carry their own light values only because a host may embed
  them on a white page; they are not an app theme. Adding light mode means a
  second full token set plus a contrast pass, not a few overrides.

## Depth & surfaces

- Section cards = DS `RADIUS_LG` + `SHADOW_CARD`: `1px solid var(--ag-border)`,
  `border-radius: var(--ag-radius-lg)` (16px), `box-shadow: var(--ag-shadow-card)`
  (0 2px 4px rgba(0,0,0,.35)) — `.tk-card`, `.pf-card`, `.pf-proj-panel`,
  `.hm-card`, `.bk-card`, `.sn-card`, profile `.pf-card` (`styles.ts`) — the
  Perfil and Pulso canvases also draw 16px section cards. Overlays/dialogs
  use `--ag-shadow-overlay`.
- Page `--ag-surface-page` → card `--ag-surface-card` → inset/input
  `--ag-surface-sunken` (the KPI tile sits on `--ag-surface-page`) (inputs are darker than their card).
- Radius scale: inputs/segmented `--ag-radius-sm` (8px), KPI tiles and nested
  containers `--ag-radius-md` (12px), section cards/panels `--ag-radius-lg`
  (16px), chips `--ag-radius-pill`.

## Spacing & density

- Rem-based, ~4px grid: 0.25 / 0.35 / 0.5 / 0.75 / 1 / 1.25rem.
- Card padding `1rem 1.1rem`; gap between cards/columns `1rem`; between
  groups inside a panel `1rem` with a border-top divider.

## Type & hierarchy

- Three levers together: size, weight, colour. Labels `--ag-fs-xs` muted
  (500); values 600 primary; meta `--ag-fs-xs` muted at weight 400.
- Text contrast: primary, secondary and muted all clear 4.5:1 on page, card
  and hover. `--ag-text-faint` is never live text — rules, dashes and
  `:disabled` only (`test_faint_is_never_live_text`).
- Type tokens are rem (11px = 0.6875rem at the default root): text follows
  the reader's browser text size. No stylesheet sets a root font-size.
- Focus: a global `:where(:focus-visible)` ring, 2px `--ag-brand-accent`
  offset 2px. Never `--ag-border-focus` or `--ag-brand-cta` as a ring (1.6:1,
  2.7:1 on a card); a field that hides its outline shows an accent border
  plus a 1px accent box-shadow instead.
- Families are tokens, never literals: `--ag-font-body`, `--ag-font-display`
  (Epilogue, figures and display headings), `--ag-font-mono`. A
  `var(--ag-x, fallback)` fallback must equal the token's value
  (`test_stylesheet_fallbacks_match_the_design_system`); 11px floor covers
  `em` sizes and TSX/SVG `fontSize` too.
- **Every number** gets `font-variant-numeric: tabular-nums`.
- One focal figure per view when the view answers one question
  (`.pf-proj-figure` = the ticker hero `.tk-hero-level`: `--ag-fs-3xl` 28px /
  700 / line-height 1.1, same on mobile). Letter-spacing only from the
  tracking tokens: `--ag-track-xl` (-0.01em), `--ag-track-2xl` (-0.015em),
  `--ag-track-3xl` (-0.02em) on headings and figures at that size — big type
  tightens, body text keeps 0. Supporting
  facts drop to `--ag-fs-base` 600 with a muted label above.
- KPI tile: `Kpi` / `KpiGrid` in `src/ui/Kpi.tsx`, the only one — the DS
  tile `tables.kpi_grid_html` draws: `--ag-surface-page` inside the card,
  `--ag-radius-md`, sentence-case `--ag-fs-sm` 500 secondary label, Epilogue
  `--ag-fs-xl` 700 value, optional `Chip` beside it (`chipFor`, tones
  up/down/warn/flat; `off` = neutral; null draws nothing). The tile is a
  size container: the value steps down to `--ag-fs-lg` / `--ag-fs-md` when the
  tile narrows, and wraps only between words, never mid-figure. Guarded by
  `tests/test_frontend_kpi.py`.
- Choice / filter chip: `ToggleChip` in `src/ui/Toggle.tsx` — outline pill,
  on = `--ag-brand-accent` edge + `--ag-cta-tint` + a check glyph, so "on"
  never rests on colour alone. Never looks like `Chip`.

## Colour

- Structure is grey; colour means something. One accent per view:
  `--ag-brand-accent`.
- Charts use `chart()` from `shell/theme.ts`, never ad-hoc hex. Forecast
  spread = `accentBand` (brand at 15%); stacked bands deepen where they overlap.
  Real/recorded line = `textPrimary`; money-in / baselines = `textMuted`
  dashed; projected median = `brandAccent`.
- Up/down chips: `--ag-up` / `--ag-down` via `Chip`.
- A price line takes its move's sign, first close to last in the window on
  screen (range, or zoomed slice): `candleUp` when flat or rising,
  `candleDown` when falling, as Home's sparklines do; its area fades from that
  colour at 14% to nothing.
  Anything drawn over it (the reader's fills) stays `textPrimary` and is told
  apart by shape, never by green/red.

## Chart data rules

The dataviz skill's rules, fitted to Aguait. They apply to every chart on
every page; a chart that breaks one is wrong, not a style choice.

1. **Series palette.** Identity (which ticker, which bucket, which line)
   comes from `series()` in `shell/theme.ts` = `CATEGORICAL_COLORS` in
   `ds.py`: blue, orange, purple, amber, magenta, in that order. Fixed order,
   never cycled (`ramp[i] ?? seriesOther()`, never `i % length`). The tail
   past the fifth folds into one `seriesOther()` "Others", never a sixth hue.
   Colour follows the entity: a filter that drops a series does not repaint
   the survivors.
2. **Up/down are not identity.** `candleUp`/`candleDown`/`up`/`down` say sign
   or state only. Never "series 2", never a net-income bar's colour because
   it is "good".
3. **One y-axis.** Two magnitudes (revenue in € and EPS in €/share) are two
   charts sharing the X axis, or one indexed to a common base. No right axis.
4. **Bars:** ≤24px wide, 4px rounded data end, square on the baseline, 2px
   surface gap between neighbours and stacked segments.
5. **Dashed = not reported.** Forecast, hypothesis (backtest), reference
   (baseline, money in, event rule). Recorded data is solid, whatever its
   rank on the chart.
6. **Selective labels.** Name the last point, the extreme or the one the
   card is about; never a number on every bar or point. Text wears text
   tokens, never the series colour; the swatch beside it carries identity.
7. **Table twin.** A chart with ≤40 points offers "Ver datos" (the same
   numbers as a table); identity is never colour alone (legend for ≥2
   series, `EndLabels` for ≤4).
8. **Validated, not eyeballed.** `tests/test_chart_palette.py` re-runs the
   skill's checks on `CATEGORICAL_COLORS`: OKLCH L 0.48–0.67, chroma ≥ 0.10,
   adjacent ΔE ≥ 8 under protan/deutan and ≥ 15 for full-colour vision,
   ≥ 3:1 on card and page. A new hue goes in only when that test passes.

Deliberate deviations: dark only, so no light-mode band; the Epilogue hero
figure stays (tabular-nums); the price line keeps 2.25px and its 14% area
fade (`Price chart hierarchy` below). The text-weight hues (`info`,
`brandAccent`, `warn`, `smaFast`…) stay for overlays and event marks with one
fixed meaning — they are not a series palette.

## Component patterns

- **Segmented** (`ui/Segmented.tsx`, the only one): one `--ag-surface-page`
  track, `aria-pressed` buttons in a labelled `role="group"`, one
  `.ag-seg-thumb` (`--ag-surface-hover` + card shadow) that slides to the
  pressed option. `className` places the track, never restyles it. Inside a
  side panel, label stacks over control and options wrap. Any one-of-a-few
  choice is this, popovers included (chat's research/lens mode); pills or
  chips only where several can be on at once.
- **Progress checklist** (chat's deep-research plan, `.ag-chat-plan`): an
  `<ol>` whose `aria-label` counts "n of m done"; each row a 14px ring that
  fills `--ag-brand-cta` with a check when done, the text turning secondary,
  never struck through, plus "done" in `.ag-sr`. Above the live lookups, gone
  once the answer lands.
- **Help:** the "?" pill (`Help` in `src/ui/Kpi.tsx`, text in `aria-label`),
  never a dotted underline. Hover opens after 400ms, then the next "?" opens at
  once for 300ms (warm group); the bubble is `aria-hidden` (the label already
  read it) and fades out. Coarse hit area 44px via `::before`.
- **Dense rows** tint `--ag-surface-hover` on hover, `(hover: hover)` only.
- **Box tools** (`.ag-box-tool`): coarse `::before` grows the hit area to 44px
  tall; width stays so neighbours never overlap.
- **Split action** (`pages/ticker/AiAsk.tsx`): the primary press does the
  common thing; a quiet chevron beside it (`aria-haspopup="menu"`,
  `aria-expanded`, 44px coarse) opens a `role="menu"` popover of the
  variants, each a label over a one-line secondary hint. Arrows/Home/End
  walk it, Escape returns focus to the chevron, Tab or a press outside
  closes it. The common path first, the rest one level deeper — never a
  row of sibling buttons.
- **Mobile (≤640px):** 12px gap between cards, 44px touch targets.
- **Hex:** none outside `shell/theme.ts` (`tests/test_frontend_tokens.py`);
  use tokens, or `black`/`transparent` for masks.
- **Amount field** (`AmountField` in `Projection.tsx`): label over a
  `--ag-surface-sunken` box with a muted unit suffix (€), accent border +
  1px accent ring on `:focus-within`, commit on blur/Enter, text input with
  `inputMode="decimal"` (never `type=number` — it drops "1.500,5"), parsed by
  `parseAmount`. Empty = null ("no value"), not zero.
- **Assumptions panel** (`.pf-proj-panel`): 300px sticky column beside the
  main card (`grid-template-columns: minmax(0,1fr) 300px`), stacks below under
  900px. `fieldset` groups with `legend` titles ("Tu plan", "Supuestos").
- **Charts** (`ReturnLines` in `charts.tsx`): zero on the axis, legend inline
  above, crosshair + shared tooltip; series can carry `tipNote` (a % in
  parentheses), `tipOnly` (in tooltip, not stroked), `dashed`; optional
  `bands` and a `marker` (labelled "today" rule between record and forecast).
  A comparison chart opens with a `Lede` (`.pf-lede`, sm secondary, 70ch):
  its answer in one sentence, the key figure in `**bold**`, before the lines
  that show how (HIG charts › "Summarize the main message"). When the legend
  prints money the axis does too (`plot="gain"`, `compactMoneyIn` signed
  ticks): a percentage on a small early base dwarfs later years. A
  hypothetical line (backtest of today's holdings) is off by default behind a
  `.pf-chart-toggle` key (`aria-pressed`); readers took it for their own.
  Series wear the name people know (`portfolio.bench_<ticker>`: "S&P 500"),
  never a bare ETF ticker.
- **Every chart, all pages** (ticker `plot.tsx` `Chart`, portfolio, Home
  spark, chat): `aria-label` is a summary (title, window, headline change),
  never just the title. Walkable by keyboard through `useKeyWalk`
  (`shell/useKeyWalk.tsx`: arrows ±1, shift ±10, Home/End, Escape; keyboard
  focus opens the readout on the last point) and spoken through `Spoken`, a
  polite live region that talks only on key moves. Tooltips carry no
  `role="status"`. Crosshair `--ag-text-muted` (faint fails 3:1);
  `--ag-text-secondary` where it crosses a filled area (ticker price). A drag
  (mouse/pen button 0) takes `setPointerCapture`; touch stays free to scroll.
  Lines are named at their ends (`EndLabels` + `spreadLabels`, ≤4, not narrow)
  instead of colour-only legends; dashes only for what was not
  reported (rule 5 above). Up candles hollow
  once the body is ≥4px. Axis digits come from the tick step (`tickDigits`).
  The loading slot reserves the plot's height (`PriceChartWait`, Home spark
  56px, chat `min-height: 160px`).
- **Price chart hierarchy** (ticker `PriceChart.tsx`): lines are not equals.
  Price 2.25px, drawn last, with a 3.5px dot on the last close; overlays
  (SMAs) 1.25px at 0.7 opacity underneath (0.7 keeps SMA50 blue ≥3:1).
  Hovering or focusing a legend key lifts that overlay to 1 / 1.75px and fades
  the rest to 0.2 (`--ag-dur-press`, none under reduced motion). Event marks
  keep one colour per meaning: dividend `warn`, results `brandAccent`
  diamond, legend swatch to match. The readout is a fixed strip above the
  plot on every pointer (`.tk-plot-strip`, not a floating tooltip over the
  line): idle shows the last bar (desktop), hover the bar, measure the span.
  Zoom state sits in the legend row: the slice's change + dates and a
  "Restablecer" pill. The gesture hint shows until the first measure
  (`tk-span-learned` in localStorage).
- **Refetch on control change:** keep the last result on screen with
  `aria-busy` → opacity 0.6 (`--ag-dur-press` `--ag-ease-out`, none under reduced motion) instead
  of swapping in a skeleton. Skeleton only on first load.
- **Calendar chip** (`.earn-chip`, Earnings grid + Home four-week grid): a
  `<button>`, never a link — the click explains, the dialog carries the way
  on. `--ag-radius-xs`, kind = class (`past`, `soon`, `div`, `tax`, `rebuy`,
  `cb`); hover = inset 1px ring in `currentColor` at 45%, so every kind keeps
  its own colour. One fold for both grids: `DayChips` in `MonthGrid.tsx`
  (`limit` 5 on the page, 3 on Home, then "+N"). A grid holds one
  `EventPick | null` and one `EventDetail` — never a dialog per chip.
- **Event dialog** (`EventDetail.tsx`, `.earn-modal` shell, `.earn-ev` card
  30rem): head = logo + linked ticker + kind line (`PlainHead` when no
  ticker); then hero (sunken, `--ag-radius-sm`: muted label, `--ag-fs-2xl`
  600 tabular figure, secondary sub line with the assumption, pill tags
  `soon`/`warn`/`held`); then 2×2 `KpiGrid` (four abreast squeezes money
  into an ellipsis); then notes (`--ag-fs-sm` secondary); one `ag-btn` CTA
  to where the reader acts. Esc, backdrop and Close all close; focus goes to
  Close and back to the chip.
- **Table head help** (`Head` in `pages/review/Explain.tsx`): label + `Help`
  "?" inside the `th`, for any column whose number needs a definition. Row
  pills/tags carry their rule as `title` on hover; KPI defs come from the
  catalog (`kpi.<k>.desc`, `*` stripped), never re-written per page.
- **Figure columns**: a numeric `th` aligns right over its right-aligned,
  tabular figures (`.hm-table th.hm-num`), never left of them.
- **Runs inside one table** (Home 52-week extremes): two kinds of row (highs,
  lows) share one `thead` so the columns line up; each run is its own
  `tbody` headed by a `th scope="rowgroup"` row in the caption's voice
  (`--ag-fs-xs` muted, room above, no rule). The heading names the kind, so
  rows drop the repeated word and keep only the figure; an empty run drops
  out heading and all. On a phone: caption + `DenseRows` per run, the same
  split the movers card uses for gains and losses.
- **Row details dialog** (`DetailsButton` / `Details`, `Explain.tsx`): terse
  row (pill, two reasons, figure) + a way into the full story — a right
  chevron in the table's last column (`aria-haspopup="dialog"`, 44px
  coarse), "Details ›" under a card or dense row. It opens a dialog, never an
  inline fold (a fold took the width of a ~17rem card and pushed the list a
  screen down): `.ag-rev-modal`, the calendar's modal shell (veil, z 65,
  card 38rem, 90dvh scroll inside), portalled to `body` because `.ag-main` is
  a size container. Head = `TickerCell` + Close; then the rule, every reason
  spelled out (name beside rule, rule drops under at <16rem — flex, never a
  page query), the numbers as `dl` tiles (`--ag-surface-page` in the card,
  `auto-fill minmax(min(100%,7.25rem),1fr)` → 2 abreast on a phone). Esc,
  backdrop, Close close; focus to Close and back. A missing number reads
  n/a, never drops out.
- **Ticker picker in a page** (`Search` with `onPick` + `placeholder`): reuse
  the top-bar search dropdown (results + recents) instead of a bare input;
  picked tickers become removable chips (`TickerCell name={false}` + ×).
- **Table search** (`pages/review/Tables.tsx`): a long table (≥6 rows) gets
  its own `ag-search-field` box over it (sunken, ≤22rem, 44px coarse),
  matching symbol, cached name, sector and verdict words, case and accents
  folded; narrows only that table, with a "3 of 44" / "nothing matches"
  caption while typed in.
- **Chart search** (`pages/review/MapFind.tsx`): a plot with ≥6 points gets a
  combobox in the card's top-right corner (full width under the title when
  `ag-main` < 40rem), the top bar's `.ag-search-panel` at chart scale: logo,
  symbol, name, verdict chip; arrows + Enter pick, Escape shuts then clears.
  Non-matches fade to 0.15, matches keep their labels; a pick lights one
  point and opens its tooltip. A match with no point is listed, not
  pickable, with why ("Not on the map · no revenue").
- **Out-of-scope rows**: rows a screen cannot judge (coins on Review: no
  filings) leave the read before it is drawn — no table of n/a — and get one
  caption line under the table with their share and a wrap of `TickerCell`s
  + weight.
- **Filter bar** (`pages/review/Filters.tsx`): folded by default behind one
  "Filters" button (`ag-toggle` + filter_list icon + accent count badge of
  picks, `aria-expanded`/`aria-controls`, on while open). While folded each
  pick shows as a removable pill (`ag-toggle-on` + ×, "Remove filter: X")
  and the "16 of 51 · Clear" count stays on the same line — a filtered read
  never looks unfiltered. Open = the chip rows in a bordered `--ag-radius-md`
  card under the bar. First row "Include" picks what
  is compared at all (book / favourites / whole watchlist / each watchlist
  group, union, `?in=`; tickers typed into the page always in; drawn only
  when there are ≥2 sources; with no `?in=` it opens on the book alone —
  `?in=all` is everything — unless nothing is held). Then `ToggleChip` rows in one grid,
  muted `--ag-fs-xs` label column (`max-content`) beside the chips; multi-pick
  chips carry a faint tabular count; "All" clears; a single-pick band clears
  on a second press. Filters ride the URL and cut every section at once
  (plan figures re-added client-side). A count line ("21 of 51", `aria-live`)
  + a text "Clear" button appear only while filtered; filtered to nothing =
  empty card with that one action. Under 640px (`@container ag-main`) labels
  stack and each chip row scrolls sideways on one line — never four rows of
  chips above the content.
- **Page → assistant:** a question built from the page goes into the
  composer unsent (`draftAssistant`), never auto-sent; the button says it
  drafts and sits in `SignedInOnly` (no drawer for a guest).
- **Ticker links inside a page:** each page styles its own `a.ag-tick`
  (primary text, no underline, symbol underlined on hover) — otherwise the
  browser default blue underline leaks in.
- **SVG scatter labels** (`pages/review/labels.ts` `placeLabels`): placed
  one by one in priority order (moves sell/trim/add/buy, then held, then
  weight), each in the first free spot right → left → above → below, clear of
  other labels, other dots, quadrant captions and y-tick labels, inside the
  plot. No free spot = no label (the dot still opens the tooltip) — never two
  labels on top of each other. Keep `PAD.right` ≥ 44px. Quadrant captions go
  in the corners dots crowd least. On a phone (<560px wide) the plot is
  near-square (height ≈ 0.95 × width, 260–420px) so the dots spread; legend
  is a wrapping `ul` of key + words, plus the "tap a dot" hint. On the Review
  page the map comes right after the plan.
- **Plan card** (`pages/review/Actions.tsx` `Plan`): the first section after
  the filters, the page's answer before its evidence. One focal figure
  (fs-3xl/700/1.1, tabular) labelled by its sign (new money the adds need /
  cash the sales free / even), the sale's tax as its supporting fact, and two
  flow bars on one shared scale (label | 10px pill track on surface-sunken |
  amount; down for sells, up for adds; the shorter side's missing length is a
  dashed text-faint segment, no gradient). Under it the moves as compact rows,
  not cards: two lists by direction ("Sell or trim", most negative first;
  "Add to", largest first), head = title + muted count + toned subtotal over
  a border rule, rows split by rule-soft. Row grid = who (logo + symbol +
  ellipsed name, trim chip only) | weight → target | bold toned money |
  details chevron, reasons (≤3) and a short tax / buy-after note under it.
  Lists sit side by side via `auto-fit minmax(min(100%, 22rem), 1fr)`; each
  list is its own `ag-rev-mvs` container and drops the weights under the
  name below 26rem.
- **Linked focus across sections** (`pages/review/focus.tsx`): one name
  pointed at (hover or keyboard focus, settled 70ms; touch never points) in
  the plan, the map or a wide table lights in every other section: its row
  washed surface-sunken with a 3px brand-accent inset bar on the left, the
  rest of that list faded to 0.35 (opacity 100ms, none under reduced
  motion); on the map its dot rings, gets a label even where `placeLabels`
  had none, every other dot fades and its `Tip` opens. The section the
  pointer is in never fades around it. Nothing moves or reflows — fading
  reads as a filter without shoving rows from under the pointer. Phone dense
  rows do not take part.
- **Point tooltip** (`pages/review/QualityMap.tsx` `Tip`): never the SVG's
  native `<title>` (~1s browser delay, OS chrome). The DS box (`.tk-tip` look:
  surface-page, 1px border, radius-sm, shadow-overlay, fs-xs, tabular) opens
  300ms after the mouse settles, at once on keyboard focus or a tap; Esc or a
  tap elsewhere closes it. Placed by measuring: centred above the dot, below
  when it does not fit, clamped 8px inside the plot. Head = symbol + verdict
  `Chip`, name muted, figures "label muted / value bold", reasons as a list
  under a rule. Dots are focusable (`tabIndex=0`, `role="img"`, full
  `aria-label`), with an invisible ≥22px hit ring; fade 100ms, none under
  reduced motion.
- **Layers:** page modal `z-index: 65` — above the chat launcher and guide
  strip (60), below the open chat drawer (70); tour scrim 90 above all. A
  modal under 60 lets the launcher float over its scrim on a phone.
- **Overlays hold the page still:** any scrim (`.ag-rev-modal`, `.earn-modal`,
  `.ag-tour-scrim`, `.ag-fb-scrim`, `.ag-jr-veil`, `.pr-modal`,
  `.ag-nav-scrim`) or a covering chat (`data-chat="overlay"`) locks the
  document scroll through one `:root:has(…)` rule in styles.css, gutter kept.
  A new scrim joins that rule. Scrolling cards inside get
  `overscroll-behavior: contain`; dialog heights use `dvh`, never `vh`.
  Scrims pad by `max(1rem, env(safe-area-inset-*))` on all four sides, and
  a card that can outgrow a sideways phone with the keyboard up scrolls on
  its own (`max-height: 100%; overflow-y: auto`).
- **Sheets and side panels** (`shell/useSheet.ts`): enter as today (keyframe,
  `--ag-dur-move` `--ag-ease-out`), and leave the way they came:
  `usePresence` keeps them mounted 200ms under `data-leaving`, and the exit
  is a CSS transition so re-opening mid-way turns them back. Touch/pen can
  throw them toward their edge (`useSwipeDismiss`): 1:1 follow, rubber-band
  past rest, release projected at 0.998 deceleration and dismissed past half
  the panel; `[data-swiped]` exits off the edge (100%). The chat drags by its
  header only. Reduced motion: no animation, no transition, no exit wait.
- **Phone chrome:** `viewport-fit=cover`; anything fixed to an edge pads by
  `env(safe-area-inset-*)` — the rail (left) and page (right) for a phone in
  landscape, the chat panel on three sides. With a keyboard up, the chat panel
  is sized to `visualViewport` (`useKeyboardFit`). Launched from a home screen
  (`display-mode: standalone`) the shell shows its own Back once the visit
  has gone somewhere.
- **Chat on a phone:** the header is title + a "provider · quota" sub line,
  one ⋮ menu (new, settings, width) and close; a grab handle drags it down.
  Another tab-bar item or a route change closes it.
- **A failed chat turn** is a neutral bubble (`.ag-chat-bad`, focus border);
  yellow (`data-tone="wait"`, inset rim) only while a wait is counting down.
  One sentence, then a mono cause line (provider · error · when), then at
  most two buttons, the first filled: the way out (retry, try another model,
  add a key) before Drop.
- **Import card:** counts first (ready, flagged in warn tone, held,
  rejected), then rows. On a phone every row is a 44px touch row (checkbox,
  verb + ticker cell × units, mono date · price, amount, "!" that opens the
  fix inline). On a desktop a three-row sample and "Open wide": the review
  fills the chat panel (`.ag-chat-wide`, borrowing the full width without
  storing it), tabs by tier plus a summary side panel; Back or Esc returns to
  the drawer at its old width. A wide markdown table (more than three
  columns) offers "see wide" under the answer.

## Focus, forms & states

- **Dialogs take focus** through `useDialog` (`shell/useDialog.ts`): focus
  enters the card (or `initial`), Tab stays inside, focus returns to the
  opener on close; `open` gates it for a dialog that stays mounted. Escape
  closes. The card is `tabIndex=-1` with no outline. The primary button is
  the trailing one in the footer.
- **One `<main id="ag-main" tabIndex=-1>`** behind a skip link (app shell,
  landing, legal). A route change moves focus to it; back/forward restores
  the scroll the page was left at.
- **Active nav** marks shape too (3px bar) plus `aria-current="page"`, never
  fill alone.
- **Search** is a WAI-ARIA combobox (listbox, `aria-activedescendant`); `/`
  and ⌘K/Ctrl+K focus it from anywhere outside a field.
- **Phone keyboard:** while a text field has focus `<html data-kbd>` hides
  the tab bar. Text fields are 16px on coarse pointers so iOS does not zoom;
  the chat composer takes focus on open only on a fine pointer.
- **Ticker / ISIN / search fields:** `autoCapitalize="off"` (a field that
  takes only a ticker: `"characters"`), `autoCorrect="off"`,
  `autoComplete="off"`, `spellCheck={false}`, and an `enterKeyHint` that
  names what Enter does (`search`, `send`, `done`).
- **Number fields** clamp to their min/max on commit; an inline edit commits
  on Enter as well as on blur.
- **44px coarse targets** hold in page stylesheets too, not just shell
  controls; a dense row grows its hit area with padding or `::before`.
  Text fields, selects and `.ag-btn` get the floor from styles.css
  (`min-height: 44px !important` under `pointer: coarse`), so a page's own
  pointer-sized `min-height` cannot undercut it; a checkbox's 44px target is
  its `<label>` row.
- **Controls under a finger** (styles.css): `touch-action: manipulation` on
  buttons, links, summaries, labels, selects, tabs; `user-select: none` on
  buttons, summaries, tabs (never on links or content). The viewport carries
  `interactive-widget=resizes-content` (Android's keyboard shrinks the
  layout, as `useKeyboardFit` makes iOS do for the chat) and `:root` sets
  `text-size-adjust: 100%`.
- **Phone first screen:** a row of three KPI tiles that stacks one per line
  (`.ag-kpis`, ag-main ≤38rem) draws each tile as a list row, label left and
  figure right; a filter pill row that would wrap to a second line on a phone
  slides sideways instead (`.earn-kinds`).
- **No hover-only actions:** what hover reveals on desktop (copy an answer,
  row tools) is visible on touch.
- **Loading:** skeletons keep their final height from the first frame and
  fade in after `calc(var(--ag-dur-move) * 2)`, so a fast load never flashes.
- **Failed loads** use `LoadFailed` (`shell/Layout.tsx`): offline,
  rate-limited, transient or generic copy plus Retry; offline retries itself
  when the connection returns. Never print a raw error. `role="alert"` only
  for errors the reader must act on; progress and results are `role=status`.
- **Onboarding dialogs** (tour, what's new, welcome, profile nudge): the
  action that moves on is `.ag-tour-cta`, filled and trailing; a side door
  ("take me there", "don't ask again") is `.ag-tour-lead`, pushed to the
  leading edge. A multi-step dialog shows its way out ("Skip") in the header,
  not only behind Escape or the scrim. A step change re-keys the content in
  `.ag-redraw` and says "n of m: heading" through an `.ag-sr` live region.
  A paged dialog (`.ag-tour-paged`) keeps one height and Next one place: all
  pages stack in one grid cell (others `visibility: hidden`), so the card is
  as tall as its tallest page and the reader taps Next without re-aiming. In
  a paged dialog the side door lives in the page (`.ag-tour-go`), the footer
  is only Back + CTA, and "Skip" keeps its slot hidden on the last page.
- **Locked for guests:** an action a guest cannot take becomes a `SignIn`
  link, never a disabled button that answers a press with nothing.
- **"Don't show again"** either offers Undo for a few seconds in place of what
  it hid, or is an account pref (`setup_card_dismissed`,
  `profile_prompt_off`) rather than a browser flag. A progress count counts
  required steps only; optional rows say "(optional)".

## Motion & input feedback

- Tokens only: `--ag-dur-hover` (colour/background), `--ag-dur-press`
  (press, popovers, chevrons), `--ag-dur-move` (sheets, dialogs, panels);
  `--ag-ease-out` for anything entering or answering a press,
  `--ag-ease-settle` for a spring back. No raw ms or cubic-bezier in a
  stylesheet.
- **Press:** buttons, chips and segment options `scale: 0.97` on `:active`
  (one `:is(…)` list in styles.css, reduced motion excluded). A new pressable
  joins that list and adds `scale var(--ag-dur-press) var(--ag-ease-out)` to
  its transition.
- **Tabs** (`ui/Tabs.tsx`, the only one): WAI-ARIA tablist with manual
  activation (arrows move focus, Enter/Space pick), one `.ag-tabs-ink`
  underline that slides to the picked tab. Never a per-page tab strip.
- **Popovers** grow from their trigger: `ag-pop-in` (fade + scale 0.96) with
  `transform-origin` at the trigger's corner (search panel top left, KPI help
  at its "?", ticker menu top right).
- **Dialogs** (`.ag-rev-modal`, `.earn-modal`, `.ag-tour-scrim`): scrim
  fades, card `ag-dialog-in` from scale 0.97; on close `useExitGhost`
  (`shell/useSheet.ts`) leaves an inert clone under `[data-leaving]` for
  `--ag-dur-move`, so React can unmount at once. A new modal takes
  `ref={scrim}` + `useExitGhost(scrim)`, and `useDialog(card)` for focus.
- **Sticky headers** show their bottom edge only once content scrolls under
  them: `container-type: scroll-state` + `@container scroll-state(stuck: top)`
  drawing a 1px `::after` (`.im-confirm`, `.earn-week-h`). Browsers without
  it keep the plain border.
- **Chat resize:** the grip keeps the grab offset (no jump on press); past
  min/max the panel gives with `rubberBand` (up to 96px) and springs back on
  release (`settle()`, `[data-chat-settle]`).
- **Chart redraw:** marks sit in `<g className="ag-redraw" key={range}>`, so
  a range, zoom or series change cross-fades (opacity 0.25 → 1,
  `--ag-dur-move`) instead of snapping; none under reduced motion.
- **AI rim** (`.ag-ai`, chat FAB) is still at rest; it turns only on hover,
  focus-visible or `[data-busy]`, paused (not reset) so it resumes in place.

- **Toasts** (`ui/toast.ts`, mounted once by `ui/Toaster.tsx` in the shell;
  sonner underneath, never imported by a page): the only transient notice.
  `toast.ok / warn / bad` fade (4 / 6 / 8s; 8s with a button), `busy` and
  `promise` turn loading into the outcome in one slot, `stay` has no timer and
  a close button. One action at most, Undo being the usual (replaces a
  "hidden, undo" line). Bottom right, lifted over the phone's tab bar
  (`--dock`) and out of the open chat drawer (`--toast-right`); 44px
  buttons on coarse pointers, `:focus-visible` ring, hover pauses. Enter and
  leave are interruptible (a new toast restacks mid-move). Reduced motion: no
  slide, an opacity fade only. Never the only copy of a figure, and never for
  a persistent state (empty card, stale banner, failed load, a field's own
  validation): those stay on the page.

## Accessibility media

- `prefers-reduced-motion: reduce`: no animation, no transition, no exit wait.
- `prefers-reduced-transparency: reduce`: veils go opaque
  (`--ag-surface-page-veil` = page), ambient light, aurora and AI glow hidden.
- `prefers-contrast: more`: muted and faint text become secondary, borders
  and soft rules become `--ag-border-focus`.
- `forced-colors: active`: tab ink and on-segments paint `Highlight`, the AI
  button gets a `ButtonText` border, decorative pseudos hidden, focus ring
  `Highlight`.
- All overrides use `:root:root` so they beat the server-inlined tokens.

## Copy

- Every figure that depends on an assumption says the assumption in the
  caption beneath it, with the real measured inputs (volatility, weights,
  correlation). "Not a prediction" wording for any forecast.
- Money the reader receives leads with what lands (net), says what was taken
  off and where that rate came from (their own statements, by name, then by
  currency). No rate on record = say "gross" and give the reference rate —
  never print a 0% no broker charged. A second figure in the base currency
  only when the currency differs, at the rate that applies (event day once
  past, today while ahead), and the line says which.
- All strings in `src/stocks/web/locales/{en,es}/*.json`, same keys and
  placeholders in both (`tests/test_i18n_parity.py`).

## Matrices and heatmaps

- A grid of cells is an ARIA `grid`: one tab stop, arrows walk it, each cell labelled
  "row × column, value, band"; the focused cell opens the same reading as hover.
- Lead with the answer (a verdict line and the ranked top pairs); the full matrix is a
  disclosure, open by default only for small N.
- Diverging ramps rise in lightness from the neutral outwards; the diagonal and
  "no data" never use the ramp (surface grey / dashed outline).
- Rank "most linked" by what the book holds, not by raw value.

## Phone adaptations

What a desktop layout draws that a 390px column cannot, and the shape it takes
instead. "Narrow" is the measured width (`useWidth` < 480 for a plot, `useMobile`
≤ 640 on `ag-main` for a page), never the viewport: an open chat drawer narrows
a laptop page the same way.

- **Category labels never squeeze.** A bar chart whose x axis is named
  categories (not dates) and has more than four of them lies down when narrow:
  one row per bar — name, the bar on a shared scale, figure — instead of
  columns whose labels overprint (`Waterfall` → `.pf-fall-rows`). Date axes
  thin their ticks instead.
- **A matrix is read one row at a time.** Past six names a narrow heatmap is a
  name picker plus that name's row as a ranked list with a diverging bar from
  the centre, ten rows then "Show all N" (`Heatmap` → `.pf-heat-rows`). It
  opens on the row of the most-linked pair. The grid stays the desktop
  reading.
- **Dense scatter: the nearest dot answers.** Dots keep their drawn size; a
  finger that lands between them opens the nearest within 22px of its edge
  (`QualityMap` `REACH`). Never grow every dot's hit area to 44px — in a
  cluster it swallows the neighbours.
- **A row about one ticker is one target.** Under `pointer: coarse` a list row
  whose subject is one ticker takes `.ag-row-reach`: the ticker link's
  `::after` stretches over the row; any other control in it sits above. Not for
  rows naming two tickers (a correlation pair) or a ticker inside a sentence.
- **Long pages fold.** Below the first screen a page's secondary cards fold to
  their heading on a phone (`ui/Fold`, ticker `Card fold="id"`): a list of
  headings is an index the reader opens where they want. Closed by default;
  an opened card stays open on the next visit (localStorage, per card).
  Never fold the hero, the price chart, a holding, or anything the first
  screen answers with. A folded card renders nothing below its heading, and
  its heading row shows the title alone (captions, badges, sources wait).
  A link that lands inside a fold (`#anchor`, a jump bar) opens it; so does
  `opened` when the URL names part of it (`?tab=`). Adopted on Ticker,
  Earnings list (book, past dividends, past results) and Sentiment (snapshot,
  book, detail). Not on Home: its cards are the reader's own pick, and the
  editor is where a card is put away.
- **A field's hint fits the field.** Chromium draws no ellipsis on a
  textarea's placeholder, so a hint longer than the field is cut mid-word
  ("Pregunta sobre tu carter"): keep it to two or three words, and below a
  320px container a field flanked by controls takes a row of its own (the chat
  composer). A row of small controls under a card wraps (`flex-wrap`) instead
  of pushing its last one off the screen.
- **The answer first.** A page leads with what it concludes (Review: the plan,
  then the book-wide notes), in DOM order, not by CSS `order` — a screen
  reader and a phone read the same sequence.

## Cards that share labels say their scope on the page

Two cards with the same tile name (volatility, drawdown) need a visible
subtitle (`Card sub`) and distinct labels ("real" / "simulated"); a tooltip is
not enough. A selector that scopes cards shows the resolved dates and says
which cards it moves. A donut's hole shows the total at rest, a slice only on
hover or pin; every legend row carries its money.
