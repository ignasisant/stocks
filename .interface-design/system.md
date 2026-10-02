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
