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
  (500); values 600 primary; meta `--ag-fs-xs` faint.
- **Every number** gets `font-variant-numeric: tabular-nums`.
- One focal figure per view when the view answers one question
  (`.pf-proj-figure` = the ticker hero `.tk-hero-level`: `--ag-fs-3xl` 28px /
  700 / line-height 1.1, same on mobile). Never touch letter-spacing. Supporting
  facts drop to `--ag-fs-base` 600 with a muted label above.
- KPI tile: `Kpi` / `KpiGrid` in `src/ui/Kpi.tsx`, the only one — the DS
  tile `tables.kpi_grid_html` draws: `--ag-surface-page` inside the card,
  `--ag-radius-md`, sentence-case `--ag-fs-sm` 500 secondary label, Epilogue
  `--ag-fs-xl` 700 value, optional `Chip` beside it (`chipFor`, tones
  up/down/warn/flat; `off` = neutral; null draws nothing). Guarded by
  `tests/test_frontend_kpi.py`.
- Choice / filter chip: `ToggleChip` in `src/ui/Toggle.tsx` — outline pill,
  on = `--ag-brand-accent` edge + `--ag-cta-tint`. Never looks like `Chip`.

## Colour

- Structure is grey; colour means something. One accent per view:
  `--ag-brand-accent`.
- Charts use `chart()` from `shell/theme.ts`, never ad-hoc hex. Forecast
  spread = `accentBand` (brand at 15%); stacked bands deepen where they overlap.
  Real/recorded line = `textPrimary`; money-in / baselines = `textMuted`
  dashed; projected median = `brandAccent`.
- Up/down chips: `--ag-up` / `--ag-down` via `Chip`.

## Component patterns

- **Segmented** (`ui.tsx`): `.pf-seg`, 0.78rem, `--ag-surface-hover` for the
  active option. Inside a side panel, label stacks over control and options wrap.
- **Help:** the "?" pill (`Help` in `src/ui/Kpi.tsx`, text in `title` +
  `aria-label`), never a dotted underline.
- **Mobile (≤640px):** 12px gap between cards, 44px touch targets.
- **Hex:** none outside `shell/theme.ts` (`tests/test_frontend_tokens.py`);
  use tokens, or `black`/`transparent` for masks.
- **Amount field** (`AmountField` in `Projection.tsx`): label over a
  `--ag-surface-sunken` box with a muted unit suffix (€), focus ring via
  `--ag-border-focus` on `:focus-within`, commit on blur/Enter, text input with
  `inputMode="decimal"` (never `type=number` — it drops "1.500,5"), parsed by
  `parseAmount`. Empty = null ("no value"), not zero.
- **Assumptions panel** (`.pf-proj-panel`): 300px sticky column beside the
  main card (`grid-template-columns: minmax(0,1fr) 300px`), stacks below under
  900px. `fieldset` groups with `legend` titles ("Tu plan", "Supuestos").
- **Charts** (`ReturnLines` in `charts.tsx`): zero on the axis, legend inline
  above, crosshair + shared tooltip; series can carry `tipNote` (a % in
  parentheses), `tipOnly` (in tooltip, not stroked), `dashed`; optional
  `bands` and a `marker` (labelled "today" rule between record and forecast).
- **Refetch on control change:** keep the last result on screen with
  `aria-busy` → opacity 0.6 (100ms ease-out — DS motion is 50/100ms, none under reduced motion) instead
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
  page the map is the first section after the filters.
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
