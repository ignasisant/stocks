# The app shell, and the contract a page keeps with it

This is the app, page by page, against the HTTP API in `src/stocks/api`;
`stocks.web.server` serves it at `/`. The shell — routing, session,
translations, design tokens, the four loading states — is written and is not a
page's to change.

## What a page owns

Exactly one directory: `src/pages/<slug>/`. Nothing outside it. If a page needs
something from the shell that the shell does not have, say so rather than
reaching around it — two pages solving the same problem two ways is the thing
this layout exists to prevent.

The entry point is `src/pages/<slug>/<Name>.tsx` — named after the page, not
`Page.tsx` — default-exporting a component that takes no props. Split the rest
of the page into as many files inside that directory as it deserves.

The filename is not cosmetic: Rollup names a chunk (and the stylesheet it pulls
in) after the module that produced it, so eight files called `Page` ship as
`Page.js`, `Page2.js`, `Page3.js` — unreadable in a network tab, and a set of
names that silently renumber when a page is added.

Register it in `src/shell/pages.ts`. Where the slug differs from the path
`stocks.navigation` ships, list that path in `aliases` so old bookmarks keep
working: `pageFor` falls back to Home for an unknown slug, so a bookmark of the
old URL does not 404 — it quietly serves the dashboard instead.
`tests/test_frontend_nav_parity.py` checks every path `stocks.navigation`
ships is reachable here.

## What the shell gives you

```ts
import { get, send, isTransient } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { useSession, useCurrency } from "../../shell/session";
import { Link, useRoute } from "../../shell/router";
import { chart, token } from "../../shell/theme";
```

- `useApi(() => get<T>("/path"), [deps])` returns a `Query<T>`: loading,
  signed-out, failed, loaded. Hand it to `<Loaded query={...}>` and render only
  the happy path; the shell draws the other three.
- `useT()` returns `t("some.key")`, with `{slot}` filling.
- `useRoute()` gives `{ page, params, go, setParams }`. `setParams` writes the
  query string **without** a history entry — that is what a tab switch is.
- `chart()` and `token()` read the `--ag-*` custom properties the server
  inlines.

## The shared primitives

`src/ui/` is the design system's components, the ones every page draws the
same way. A page composes them and does not restyle them.

```tsx
import { Chip, Kpi, KpiGrid, chipFor, bandTone } from "../../ui/Kpi";

<KpiGrid>
  <Kpi label={t("home.market_value")} value={money(v)} chip={chipFor(pct, text)} />
  <Kpi label={t("ticker.moat_score")} value="72" help={t("kpi.moat.desc")}
       chip={{ text: rating, tone: bandTone(rating_tone) }} />
</KpiGrid>
```

- `Kpi` slots: `label`, `value`, `help` (the "?"), `chip`, `note`, and
  `children` for a meter or a sparkline. An empty slot takes no room.
- `chipFor(value, text, off?)` returns `null` when there is nothing to say,
  and `Chip` draws nothing for `null` — hand it over without checking.
- Tones are `up` / `down` / `warn` / `flat`; `bandTone` maps the API's
  green / red / orange / gray bands onto them.
- `KpiGrid` wraps rows of 2, 3, 4 and 6 evenly (no 3+1 orphan).

`tests/test_frontend_kpi.py` fails if a page stylesheet defines its own tile
or delta pill again.

A table with figures ships a phone rendering too (`src/ui/Rows.tsx`):
`<Responsive wide={table} narrow={…} />`, where `narrow` is `DenseRows` for a
ticker list (logo, symbol + pill, dim line, figure on the right — the whole row
links to the ticker) or `StackCards` for anything else (one card per row, one
label/value line per column). A container query on `ag-main` at 40rem picks
one. The portfolio `Table` does this for you: pass `dense` for a ticker list,
or get cards by default.

## Rules that are not style preferences

**Never write a user-visible string.** Every label, heading and message is
`t("key")`. This app ships in English and Spanish.

**Verify every i18n key exists before you use it.** The catalogs are
`src/stocks/web/locales/{en,es}/*.json`. Several keys that look obvious are not
there, and several have a different name than you would guess. A key that does
not exist renders as the dotted key on screen. Grep first:

```bash
grep -rn '"tab_positions"' ../../src/stocks/web/locales/en/
```

If a string genuinely has no key, add it to **both** `en` and `es` catalogs —
`tests/test_i18n_parity.py` fails if they drift.

**No hex colours, ever.** Use `token()` / `chart()` or a `var(--ag-*)` in CSS.
A colour written by hand is a colour the design system does not know about, and
it will be wrong in one of the two themes.

**A number that could not be computed is not zero.** The API sends `null` for
exactly this reason: an unpriced position has no value, a book with no history
has no return, a spread nobody could measure is not a spread of zero. Render
`null` as "n/a" or a dash — never as `0`, never as `—` dressed up as a figure.

**Deep links keep working.** `?ticker=AAPL`, `?tab=fees` and the rest are
bookmarked URLs. Read them from `useRoute().params` and write them with
`setParams`.

## Checking your work

From `frontend/app/`:

```bash
npx tsc --noEmit
npx prettier --check src
```

Both must pass. Do not run `npm install`, do not touch `package.json`, do not
edit anything under `src/shell/`, and do not commit.

## Streaming

One endpoint does not answer JSON: `POST /chat/runs` sends
`text/event-stream` — an [AG-UI](https://docs.ag-ui.com) run, `RunAgentInput`
in and AG-UI events out. It is a POST, so `EventSource` cannot read it — the
drawer uses `fetch` plus `response.body.getReader()` and parses the events
itself (`run` in `src/chat/api.ts`). `@ag-ui/core` is a dev dependency and is
only ever imported with `import type`: its runtime is zod schemas, and the
drawer is in the chunk every reader downloads.
`src/chat/` owns that reader; a page has no reason to stream anything and
should use `get`/`send` like everything else.

## What is deliberately out of scope

The guided tour and the "what's new" modal. The shell draws both
(`src/shell/Tour.tsx`); a page should not try to render either.

The assistant drawer is **not** out of scope any more — it lives in
`src/chat/`, is mounted once by the shell, and renders over every page. A page
does not mount it and does not talk to it.
