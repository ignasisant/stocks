# frontend/

The React app, and the record of the experiment that decided to keep going.

```
frontend/app/                source — the shell and every page (see its README)
src/stocks/web/static/app/   the build output — committed, see below
src/stocks/web/static/mcp/   the Claude connector's view, one HTML file — same
```

There was a second directory here until 2026-09-19: `frontend/ticker`, one page
rebuilt on its own to measure what the rebuild would cost. It is gone, and what
it measured is written down at the bottom of this file. Its page now lives in
the shell as `pages/ticker/`, which is where every page lives.

## Running it

```bash
npm --prefix frontend/app install
uv run stocks dashboard --reload       # :8501, frontend live from source (HMR)
npm --prefix frontend/app run build    # format, types, tests, then the bundle
```

`dashboard --reload` is the way to work on it. It starts Vite on a free port
beside uvicorn and :8501 sends the app's document with its modules pointed at
that dev server, so the page is the source on disk, hot-reloaded, under the
real server — sign-in, API, logos all same-origin as in production. Without it
:8501 serves the committed bundle, which only `npm run build` changes: an edit
stays invisible there until you build. `--reload --bundle` serves the bundle
anyway, to check a build before committing it; a checkout without
`node_modules` falls back to it on its own.

`npm run dev` still works on its own (Vite's port, `/next-assets/`) and proxies `/api` to a locally running app, so the dev server talks to
the same endpoints production does — including the session cookie, which is why
you sign in at `localhost:8501` first. The dev URL carries Vite's `base`
(`/next-assets/`); the router reads past it.

## Where it is served

It is the app: `stocks.web.server` hands this document to `/` (once the landing
gate lets a visitor through) and to every page in `stocks.navigation.
SHELL_PATHS`, and the bundle to `/next-assets/`. `/next/*`, where it lived
while it was built, and `/legacy/*`, where the old app went once this replaced
it, redirect permanently to the same page at the root, query and all.

```bash
uv run stocks dashboard --reload
```

## Why the build output is committed

The bundle lands inside the Python package rather than in a sibling `dist/`, and
it is checked in. That is a real cost (a binary-ish diff on every rebuild) bought
for a real reason: `uv run stocks dashboard`, a source deploy to Cloud Run and
the Docker image all serve the pages without any of them needing Node. The
alternative — building in the image — means the app silently 404s on every
path that skips that step, including a plain local checkout.

`npm run build` is the only thing that should ever write those files. It runs
`prettier --check`, `tsc --noEmit` and `vitest run`, so a type error, an
unformatted file or a failing test fails the build rather than shipping.

It also builds `src/mcp/` — the view the Claude connector draws its portfolio
tools with (`connector/views.py`) — through `vite.mcp.config.ts`, into one
self-contained HTML file: a host fetches it as a single document and the frame
it draws it in can load nothing else. That build swaps React for Preact
(aliased, which is why knip is told `preact` is used), since the view is a few
pure components and React's runtime would be most of the file.

## What it shares with the Python side, and what it does not

Shared, by construction rather than by copying:

- **The numbers.** Every figure comes from `/api/v1`, which computes them with
  the domain functions in `src/stocks` — `analysis.history.price_history`
  shapes the bars — so nothing in this app re-derives a figure of its own.
- **The colours.** `server.py` inlines `ds_vars_css()` into the document, the
  same `--ag-*` block the landing uses. Nothing in `styles.css` hardcodes a
  hex, and the chart reads its palette back out of those custom properties.
  `tests/test_frontend_tokens.py` asserts every name this page reads is one
  `ds.tokens()` actually publishes — a name that is not does not fail, it
  quietly freezes at the fallback beside it and drifts.
- **The strings.** `/api/v1/i18n/{lang}` serves the same `locales/` fragments,
  English merged underneath, and `src/shell/i18n.tsx` does the same
  `{placeholder}` formatting `i18n.translate()` does.
- **The URL.** `?ticker=AAPL`, the query old links already carry, so every
  existing deep link keeps working.
- **The menu.** `/v1/nav` serves `stocks.navigation`, the table the rail and
  the phone tab bar are built from, so the menu offers what the server ships —
  and a page removed stops being offered. Desktop draws the grouped rail,
  phones the design's fixed four-destination bar, its glyphs inline SVG.
- **The typeface.** `server.py` injects the DS faces (`seo.FONTS_HREF`, the
  stylesheet the landing already links) into the document. Without it this page
  declared Instrument Sans and rendered the whole app in system-ui.
- **The search ranking.** `/api/v1/search` answers from `stocks.search`: which
  tier answers first, how the tiers dedup, and when the SEC group yields the
  lead to the worldwide one are decided in one place. The box here decides only
  the interaction, and a ticker opened from it is recorded so the box offers it
  back.

- **The page's own identity.** `/profile` resolves the header server-side:
  logo chip, the *resolved* symbol (an ISIN-keyed holding reads as its
  ticker), the company name, and the "in portfolio" badge. Deep links keep the
  stored label, because that is what the ledger is keyed on.
- **The window you drag out.** Zooming the price chart prints the change
  across it. The Streamlit page needed the whole price series shipped into a
  `data-` attribute and hand-written JS that survived `newPlot` purging its
  handlers off the div; here it is a listener over state already in memory.
  This is the one place where the rebuild is plainly less code doing more —
  worth naming, because most of the rest of it is not.
- **The comparison.** The financials chart carries what its caption promises
  and nothing less: hatched consensus revenue bars, a dashed EPS line
  on its own axis with the analyst min-max range shaded around it, per-bar YoY
  labels, and a divider where reported stops. Periods past the last published
  estimate are labelled *extrapolated*, not *consensus* — the API ships that
  flag (`revenue_extrapolated`, `eps_extrapolated`) precisely so no client can
  blur the two.
- **Who gets compared.** Nothing until you pick, from three sources: the
  watchlist, Yahoo's related names, and a free symbol
  search. Each peer is a fundamentals pull, so a default set spends those
  requests on a guess.

- **The phone layout.** Below 640px the page takes the design's phone
  arrangement rather than a narrowed desktop one: a price hero with the holding
  as 2×2 tiles, two range pills dropped (8 overflow a 360px viewport), the line
  chart by default, a date axis thinned to three labels, and the wide tables
  transposed into one card per row. `useMobile()` is a hook rather than a media
  query because those are data decisions, not box-model ones.
- **What each section actually says.** Not just its title: the fund card's
  turnover and duration tiles, its asset-class line, its sector bars and the
  caption saying the disclosed basket is a floor and not the whole fund; the
  insider block's four tiles (counts, net over the window, distinct people),
  the cluster-buying and selling-dominates readings, the monthly open-market
  flow and the signed-value caption; the P/E card's 1y/3y/5y/10y selector,
  its percentile band and the warning when the reconstructed multiple and the
  KPI grid's disagree by more than 20% (different EPS vintages, not a bug).
- **The coloured cues.** A verdict ships its tone (`verdict_tone`,
  `rsi_tone`) from the same bands `analysis.fundamentals` uses. Colouring by the
  label instead needs a rule per band and shows every unseen one — "net cash",
  "buybacks", "heavy dilution" — as neutral.

- **Your own trades on your own chart.** `/position` ships every fill, scaled
  to today's shares, and the chart marks them. Two things had to be right for
  that: the split adjustment (ledger prices are as-traded, Yahoo's bars are
  not) and the relabelling — a book fed by two brokers spells one holding two
  ways, and positions are built on the unified label.
- **What you can change from the header.** The favourite star, the tag groups
  and the alert rules all write to this account's watchlist through
  `/v1/watchlist`, and all of them upsert: starring or tagging a symbol that is
  only held — or only searched for — lists it. What an alert *asks for* is
  served, not hardcoded: `/v1/alert-types` publishes `config.ALERT_FORMS`, so
  a new alert type reaches the editor without the editor being edited.
- **Whose shares they are.** The header draws a brand mark per custodian beside
  the "in portfolio" badge, with its share of the position on the tooltip. The
  resolution is the API's (`/position` ships name, logo and share) rather than
  a key-to-brand table copied into a front end.
- **Coins get the block that applies.** A currency pair has no fundamentals,
  no insiders and nothing to compare against; `/crypto` answers with market
  cap, 24h volume, supply and the 52-week range, and the equity sections stay
  out of the way rather than rendering empty.

## Tests

Two runners, because there are two languages and they answer different
questions.

`npm --prefix frontend/app test` (vitest) covers the pure logic — the rules that
are wrong silently rather than loudly: growth measured against the magnitude of
the base (so a deepening loss does not read as +233%), a dividend's yield priced
against the close of its own day, an alert sent with the field its type does not
use. `npm run build` runs it, after `prettier --check` and `tsc --noEmit`, so
none of the three can be skipped on the way to a bundle.

`tests/test_ticker_parity.py` runs with the Python suite and watches
`frontend/app/src`. Between them: vitest says the page computes the right
thing, the parity test says it only says what the server can back.

## Is it holding up? — the parity harness

`tests/test_ticker_parity.py`, and it runs with the rest of the suite. No
browser and no screenshots. What it checks is that every word the page prints
and every path it calls exist on the Python side.

- **Every string the React page prints is a real key**, in English *and* in
  Spanish. An invented key falls through to itself, so it reads fine in English
  and ships `ticker.moat_caption` to a Spanish reader. This has caught that
  twice already.
- **Section and string parity went with the Streamlit page.** While both
  existed, every section and every string the old page rendered had to be
  printed here or waived in writing. The section check alone read as done
  while the React page said 75 fewer things than the old one — a fund card
  with no basket, an insider block with no monthly flow, a P/E card with no
  range selector; the string check is what closed that gap.
- **Every path the client calls exists on the server.** A typed client checks
  the shape it expects and nothing at all about the URL it asks for.

## What it cost

Counted rather than felt, for one page:

| | lines |
|---|---|
| the Streamlit page it replaced | 2,127 |
| the page as rebuilt, inside the shell | 6,240 |
| the shell it now lives in (every page) | 23,700 |
| new domain seams (`search`, `identity`, `analysis/history`, `accounts`) | 993 |
| `src/stocks/api` | 6,253 |

Roughly three times the code for the same page. The JavaScript is the part that
moved: the standalone build shipped **490 KB gzipped** because it loaded Plotly;
the shell draws its charts as SVG by hand and ships **77 KB gzipped** for the
whole app, with the ticker page's own chunk at 18 KB. That is the single largest
thing learned here, and it was learned by building the same page twice.

The first paint is still ~17 HTTP requests where the Streamlit app made one
websocket round trip. Anyone reading this to decide anything should start
from those numbers, not from how a page feels.

What is genuinely better is not the React part. It is the seams: the domain now
answers these questions in one place for every caller, and pushing them there
surfaced four real defects — a consensus band that was always null, a chart axis
dragged to zero, four "design tokens" that did not exist and silently used
hardcoded fallbacks, and trade markers that never drew on a position booked
under an ISIN.

Three of those were in the new code and never shipped. **The fourth was in the
Streamlit page**, had been for as long as the book had had two brokers in it,
and was fixed: `corporate.own_fills` does the relabelling and the split scaling
together, and `/position` calls it. That is the shape of the whole
argument for this work — not that React is better, but that a second caller
asks questions a single front end never had to answer out loud.

Known gaps, decided rather than overlooked:

- **No chat drawer and no guided tour on the page itself.** Both belong to the
  shell (`src/chat/`, `shell/Tour.tsx`), which draws them over every page.
- **The chart's event verticals say what they are.** A dotted line on a
  dividend or a results date with no text leaves the reader to guess which; the
  hover carries the dividend and its yield against *that day's* close, the EPS
  against the estimate with the surprise, and the two-session move across the
  print.
- **The marks are text glyphs, not icons.** The search rows draw ★ and ● for
  a favourite and a holding. The nav's own glyphs are inline SVG
  (`shell/Icon.tsx`): no icon font means no request and no flash of the word
  "pie_chart" before it arrives.
- **A write confirms itself, rather than raising a toast.** Starring fills the
  star, a tag appears as a chip, a rule joins the list above the form. Adding a
  toast layer would be feedback for feedback.
- **The three actions stay inline on a phone.** They are three buttons in a
  flex row that wraps, so a 390px row needs no kebab menu, and the panels
  anchor to the left edge so neither one opens off-screen.
- **Peer suggestions carry a name only for US filers.** `/peers` resolves them
  through the SEC map, which is free and already cached; a name for a foreign
  listing would be a network round trip per suggestion.
- **Chart titles are card headings, not canvas titles.** Each is the card's
  `<h2>`, which is how every other section on this page is titled.
- **Writes are session-only.** The watchlist routes take a signed-in session
  and refuse a bearer token (`api/deps.writer`), so this page can star, tag and
  set alerts while a script holding an API token cannot. That is the API's rule
  rather than this page's, and it is the reason the page never asks for a
  credential of its own.
- **Plotly, and then no Plotly.** The standalone page loaded the library: 1,545
  KB gzipped as the prebuilt bundle, 490 KB once `plotly.js/lib/core` was given
  only the three trace types the page draws. The shell draws the same charts as
  hand-written SVG and ships 77 KB for the entire app. Both numbers are real and
  the second one is why this entry is in the past tense.
