# escenas.yaml — storyboard format

One file drives TTS, recording and assembly. Scenes play in order; ids are unique and short.

```yaml
release:
  version: 2026-11-comparar-indice    # → release_<version>.mp4
  title: Compara tu cartera con el S&P 500
  product: MyBrainStock                    # shown on cards
  max_duration: 60                     # optional override
  badge: 'Cartera de ejemplo · operaciones inventadas'   # burned top-right on every ui/video frame at build
  scenes:
  - id: gancho
    kind: card                         # title | card | diagram | outro | ui | video
    narration: MyBrainStock estrena el comparador con el índice…
    card: {kicker: Novedad, title: 'Compara con *el índice*', shot: {scene: exportar, at: 0.8}}
  - id: exportar
    kind: ui
    narration: En Hoy, tu cartera frente al S&P 500 con tu mismo dinero, desde tu primer día.
    mask: ['.account-email']   # blurred all scene long
    setup:                             # NOT recorded: get the page ready
      - {do: goto, url: /today}
      - {do: wait_for, target: {css: '.today-compare'}}
    steps:                             # recorded, in step with the narration
      - {do: highlight, target: {css: '.today-compare'}, on: cartera}
      - {do: zoom, target: {role: button, name: 'Desde el inicio'}, scale: 1.25, on: índice}
      - {do: click, target: {role: button, name: 'Desde el inicio'}, on: dinero}
      - {do: wait_for, target: {text: 'Desde el inicio'}}
      - {do: zoom_out}
```

## Kinds
- `ui` — recorded in the product. Needs `steps`; `setup` is optional and runs before the camera rolls.
- `video` — an external clip cut in at build time, never recorded: `src:` (path, required), `start:`
  (seconds into the source), `speed:` (1.25 = faster). Fitted to 16:9 on the brand background, trimmed
  to lead + narration + tail, badge burned on. Use it for footage Playwright cannot record (Claude
  Desktop with the MCP connector). Review every frame of `src` before using it: no real account data.
- `title` / `outro` — branded card with kicker, title, subtitle and an accent bar.
- `card` — heading + up to 6 `items` (`{title, text, on}`), the **"además"** scene or a plain explanation.
- `diagram` — heading + `items` drawn as a left-to-right flow; arrows light up as each node appears.
  Use it as **plan B**: backend-only changes, or a UI scene that cannot be recorded.

Card fields: `kicker` (eyebrow pill), `title` (`*words*` get the landing gradient), `subtitle`, `items`
(≤2 read best), `columns`, `cta` (outro button, e.g. `mybrainstock.com`), `tag` (top right), `logo: false`,
and the **required** `shot`: real product beside the copy — a ui scene id, `{scene: id, at: 0.0–1.0}`
(which frame of that take), or a PNG in the release dir. `shot_focus: [x%, y%]` aims it,
`shot_zoom: [from, to]` sets its slow push-in. See `references/formato.md`.
An item with `on: <word>` appears when the narration says that word; others appear in sequence.
A scene with no narration needs `hold: <seconds>`.

## Timing
- `on: <word>` — run the step when the narration reaches that word (prefix match, accents and case ignored,
  searched forward from the previous `on`, so repeated words work in order). `early: 0.35` is the default
  lead so the cursor arrives as the word is said.
- `at: <seconds>` — run at a fixed time after the narration starts.
- Neither — run right after the previous step.
- `goto`, `wait_for` and `wait` are **holds**: their time is cut from the clip, so slow loads never show
  and never desync the voice. `pause` is a visible pause.
- `held: true` on any step runs it inside a hold too: a scroll right after a `wait_for` lands in the
  same cut instead of showing as a jump.
- After the last step the recorder waits until the narration ends plus `scene_tail`.
- **Auto-zoom**: a `ui` scene with no `zoom`/`zoom_out` step zooms itself (Screen Studio style) on
  each `click`, `hover` and `fill` at `video.auto_zoom_scale` (1.8×, hover ×0.8 so tooltips fit), and
  pulls back 1.6 s after the last one. One manual zoom turns it off for that scene; `auto_zoom: false`
  on the scene turns it off without adding any.
- While a `fill` types, subtitles move to the top so they never cover the field.
- Steps in `setup` leave no marks: their clicks neither zoom nor sound.

## Steps
| do | args | effect |
|---|---|---|
| goto | url (relative to the env base_url), until | navigate (hold), re-inject overlay |
| wait_for | target, state, timeout | wait for an element (hold) |
| wait | s | invisible wait (hold) |
| pause | s | visible pause |
| click | target, fx, fy, ring (default true), ms | glide cursor, ring, click with ripple |
| hover / move | target, fx, fy, ring | glide cursor (ring off by default) |
| fill | target, text, delay | click the field and type |
| press | key | keyboard key |
| scroll | target \| dy | scroll an element into view, or wheel by dy px |
| highlight | target, style (ring \| spotlight), pad | persistent ring or dimmed spotlight |
| clear | — | remove ring/spotlight |
| zoom | target \| box, scale (1.1–2.4), dur | smooth zoom in post-production: crops **centred on the box centre at `scale`** (the box size is ignored); `box` is a dict `{x, y, width, height}` in CSS px of the 1440×810 viewport; clamped to the frame edges |
| zoom_out | dur | back to full frame |
| badge / hide_badge | n, text | step pill at the top-right |
| eval | js | run JS in the page |
| python | code | escape hatch: async code with `page`, `rec` |

## Targets (robust first)
`{role: button, name: Mapa}` · `{text: 'Ver ruta completa', exact: true}` · `{label: Buscar}` ·
`{placeholder: …}` · `{testid: …}` · `{css: …}` (last resort; never XPath). Modifiers: `nth`, `has_text`,
`within: <target>`. Design-system components (`ds-*`) often expose `role`/`aria-label` through their shadow
root — try `role` first, then the host tag (`{css: 'ds-button[icon=play]'}`).

## Checking selectors before the real take
`release.py record --work W --env E --scenes <id> --setup-only` runs only `setup`. To inspect the page
interactively, connect to the login browser (`chromium.connect_over_cdp('http://127.0.0.1:9333')`) and
screenshot; the overlay's own text is CSS-generated, so `get_by_text` never matches it.
