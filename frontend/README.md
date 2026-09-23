# frontend/

The React rebuild, and the record of the experiment that decided to keep going.

```
frontend/app/                source — the shell and every page (see its README)
src/stocks/web/static/app/   the build output — committed, see below
```

There was a second directory here until 2026-09-19: `frontend/ticker`, one page
rebuilt on its own to measure what the rebuild would cost. It is gone, and what
it measured is written down at the bottom of this file. Its page now lives in
the shell as `pages/ticker/`, which is where every page lives.

## Running it

```bash
npm --prefix frontend/app install
npm --prefix frontend/app run dev      # proxies /api to :8501
npm --prefix frontend/app run build    # format, types, tests, then the bundle
```

`run dev` proxies `/api` to a locally running app, so the dev server talks to
the same endpoints production does — including the session cookie, which is why
you sign in at `localhost:8501` first. The dev URL carries Vite's `base`
(`/next-assets/`), not `/next`.

## Turning it on

Off by default. `[app] react_app = true` in `.streamlit/secrets.toml` (or
`REACT_APP=1`) makes `/next` serve the shell. Every Streamlit page stays where
it is and stays the one a visitor lands on: an unfinished rebuild must not be
reachable by guessing a URL, and the two are meant to be read side by side at
the same account on the same data.

```bash
REACT_APP=1 uv run streamlit run src/stocks/web/server.py --server.port 8599
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

## What it shares with the app, and what it does not

Shared, by construction rather than by copying:

- **The numbers.** Every figure comes from `/api/v1`, which computes them with
  the same domain functions the pages call — `analysis.history.price_history`
  shapes the bars for both, so the two front ends cannot draw different charts
  for the same range.
- **The colours.** `server.py` inlines `ds_vars_css()` into the document, the
  same `--ag-*` block the Streamlit app and the landing use. Nothing in
  `styles.css` hardcodes a hex, and the chart reads its palette back out of
  those custom properties. `tests/test_frontend_tokens.py` asserts every name
  this page reads is one `ds.tokens()` actually publishes — a name that is not
  does not fail, it quietly freezes at the fallback beside it and drifts.
- **The strings.** `/api/v1/i18n/{lang}` serves the same `locales/` fragments,
  English merged underneath, and `src/i18n.ts` does the same `{placeholder}`
  formatting `i18n.t()` does.
- **The URL.** `?ticker=AAPL`, exactly as the Streamlit page reads and writes
  it, so every existing deep link keeps working.
- **The menu.** `/v1/nav` serves `stocks.navigation`, the table `st.navigation`
  and the phone tab bar are now built from as well, so a page added to the app
  appears in this shell without a line being written here — and a page removed
  stops being offered. Desktop draws the grouped rail, phones the design's
  fixed four-destination bar, with the same Material Symbols glyphs the app
  draws because the document links the same subset of that font.
- **The typeface.** `server.py` injects the DS faces (`seo.FONTS_HREF`, the
  stylesheet the landing already links) into the document. Without it this page
  declared Instrument Sans and rendered the whole app in system-ui.
- **The search ranking.** `/api/v1/search` answers from `stocks.search`, which
  is the module the Streamlit top bar reads too: which tier answers first, how
  the tiers dedup, and when the SEC group yields the lead to the worldwide one
  are decided in one place. The box here decides only the interaction, and a
  ticker opened from it is recorded so the app's own box offers it back.

- **The page's own identity.** `/profile` resolves the header the way the app
  does: logo chip, the *resolved* symbol (an ISIN-keyed holding reads as its
  ticker), the company name, and the "in portfolio" badge. Deep links keep the
  stored label, because that is what the ledger is keyed on.
- **The window you drag out.** Zooming the price chart prints the change
  across it. In Streamlit that needs the whole price series shipped into a
  `data-` attribute and hand-written JS that survives `newPlot` purging its
  handlers off the div; here it is a listener over state already in memory.
  This is the one place where the rebuild is plainly less code doing more —
  worth naming, because most of the rest of it is not.
- **The comparison.** The financials chart carries what the app's caption
  promises and nothing less: hatched consensus revenue bars, a dashed EPS line
  on its own axis with the analyst min-max range shaded around it, per-bar YoY
  labels, and a divider where reported stops. Periods past the last published
  estimate are labelled *extrapolated*, not *consensus* — the API ships that
  flag (`revenue_extrapolated`, `eps_extrapolated`) precisely so neither front
  end can blur the two.
- **Who gets compared.** Nothing until you pick, from the same three sources
  the app offers: the watchlist, Yahoo's related names, and a free symbol
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
  ways, and positions are built on the unified label. **The Streamlit page
  filters the raw ledger here, so it draws no markers at all on a position
  whose fills were booked under an ISIN.** That one is a fix, not parity.
- **What you can change from the header.** The favourite star, the tag groups
  and the alert rules all write to this account's watchlist through
  `/v1/watchlist`, and all of them upsert: starring or tagging a symbol that is
  only held — or only searched for — lists it, exactly as the app behaves. What
  an alert *asks for* is served, not hardcoded: `/v1/alert-types` publishes
  `config.ALERT_FORMS`, the same table the app's widget reads, so a new alert
  type reaches both editors without either being edited.
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
thing, the parity test says it is the *same* thing the Streamlit page says.

## Is it holding up? — the parity harness

`tests/test_ticker_parity.py`, and it runs with the rest of the suite. No
browser and no screenshots: two renderers will never agree pixel for pixel, and
a diff of that is noise. What it checks is whether the two front ends make the
same claims in the same words.

- **Every string the React page prints is a real key**, in English *and* in
  Spanish. An invented key falls through to itself, so it reads fine in English
  and ships `ticker.moat_caption` to a Spanish reader. This has caught that
  twice already.
- **Every section the Streamlit page renders is ported or waived in writing.**
  A new `st.subheader(tr(...))` in `app_pages/ticker.py` fails the test until
  somebody either builds it here or adds it to `WAIVED` with a reason. That is
  the difference between a parity harness and a parity memory. The waiver list
  is currently empty: all eight sections are ported.
- **Every string the Streamlit page prints is printed here or waived too.** The
  section check turned out to be much weaker than it reads: all eight sections
  were "ported" while the React page said 75 fewer things than the app —
  a fund card with no basket and no exposure, an insider block with no monthly
  flow and no Value column, a P/E card with no range selector, a KPI grid whose
  labels arrived in English because the API had baked them in, and a chart whose
  event verticals carried no text. `WAIVED_STRINGS` now holds exactly two
  entries, both the assistant button, which belongs to the app shell.
- **Every path the client calls exists on the server.** A typed client checks
  the shape it expects and nothing at all about the URL it asks for.

## What it cost

Counted rather than felt, for one page:

| | lines |
|---|---|
| the Streamlit page it replaces | 2,127 |
| the page as rebuilt, inside the shell | 6,240 |
| the shell it now lives in (every page) | 23,700 |
| new domain seams (`search`, `identity`, `analysis/history`, `accounts`) | 993 |
| `src/stocks/api` | 6,253 |

Roughly three times the code for the same page. The JavaScript is the part that
moved: the standalone build shipped **490 KB gzipped** because it loaded Plotly;
the shell draws its charts as SVG by hand and ships **77 KB gzipped** for the
whole app, with the ticker page's own chunk at 18 KB. That is the single largest
thing learned here, and it was learned by building the same page twice.

The first paint is still ~17 HTTP requests where Streamlit makes one websocket
round trip. Anyone reading this to decide anything should start from those
numbers, not from how a page feels.

What is genuinely better is not the React part. It is the seams: the domain now
answers these questions in one place for both callers, and pushing them there
surfaced four real defects — a consensus band that was always null, a chart axis
dragged to zero, four "design tokens" that did not exist and silently used
hardcoded fallbacks, and trade markers that never drew on a position booked
under an ISIN.

Three of those were in the new code and never shipped. **The fourth was in the
Streamlit page**, had been for as long as the book has had two brokers in it,
and is fixed: `corporate.own_fills` now does the relabelling and the split
scaling together, and both front ends call it. That is the shape of the whole
argument for this work — not that React is better, but that a second caller
asks questions a single front end never had to answer out loud.

Known gaps, decided rather than overlooked:

- **No chat drawer and no guided tour.** Both belong to the app shell, not to
  this page; rebuilding them here would duplicate the largest piece of state in
  the codebase (`web/chat_core.py` alone is ~3.6k lines) for an experiment.
- **The chart's event verticals say what they are.** A dotted line on a
  dividend or a results date with no text leaves the reader to guess which; the
  hover carries the dividend and its yield against *that day's* close, the EPS
  against the estimate with the surprise, and the two-session move across the
  print.
- **Two marks are emoji, not Material icons.** The search rows draw ★ and 💼
  where the app draws `:material/star:` and `:material/work:`. The tiers the app
  already marks with emoji (🪙 🧺 🔎 🌐) are identical. The nav's own glyphs are
  inline SVG (`shell/Icon.tsx`): no icon font means no request and no flash of
  the word "pie_chart" before it arrives.
- **A write confirms itself, rather than raising a toast.** Starring fills the
  star, a tag appears as a chip, a rule joins the list above the form; the app
  toasts because its own rerun can otherwise finish with nothing visibly
  different. Adding a toast layer here would be feedback for feedback.
- **The three actions stay inline on a phone.** The app folds them into a kebab
  menu because three Streamlit controls do not fit a 390px row; these are three
  buttons in a flex row that wraps, and the panels anchor to the left edge so
  neither one opens off-screen.
- **Peer suggestions carry a name only for US filers.** `/peers` resolves them
  through the SEC map, which is free and already cached; a name for a foreign
  listing would be a network round trip per suggestion. The app resolves them
  one by one because it draws them as pills with a logo.
- **Chart titles are card headings, not canvas titles.** The app puts the title
  inside the Plotly canvas (`chart_layout`); here it is the card's `<h2>`, which
  is how every other section on this page is titled.
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
