# The app shell, and the contract a page keeps with it

This is the React rebuild of the Streamlit app, page by page, against the HTTP
API in `src/stocks/api`. The shell — routing, session, translations, design
tokens, the four loading states — is written and is not a page's to change.

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

Register it in `src/shell/pages.ts`. Where the slug differs from the Streamlit
`url_path` it replaces, list the old path in `aliases`: `pageFor` falls back to
Home for an unknown slug, so a bookmark of the old URL does not 404 — it quietly
serves the dashboard instead. `tests/test_frontend_nav_parity.py` checks every
path `stocks.navigation` ships is reachable here.

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

**Read the Streamlit page you are replacing.** It is the specification, and its
comments explain decisions that are not obvious from the screen. Match what it
shows and why; do not redesign it.

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

One endpoint does not answer JSON: `POST /chat/messages` sends
`text/event-stream`. It is a POST, so `EventSource` cannot read it — the drawer
uses `fetch` plus `response.body.getReader()` and parses the frames itself.
`src/chat/` owns that reader; a page has no reason to stream anything and
should use `get`/`send` like everything else.

## What is deliberately out of scope

The guided tour and the "what's new" modal. They stay in Streamlit; a page
should not try to render either.

The assistant drawer is **not** out of scope any more — it lives in
`src/chat/`, is mounted once by the shell, and renders over every page. A page
does not mount it and does not talk to it.
