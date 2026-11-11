/**
 * Ticker — one company, read top to bottom: what it costs, what the reader owns
 * of it, what it earns, what it is worth against its own history, how defensible
 * it looks, who inside it has been dealing, and who to compare it against.
 *
 * **The company is the URL.** `?ticker=AAPL` — the param every ticker cell in
 * this shell already links with — so a bookmark, a chat link or a notification
 * lands on the same stock. Written with `setParams`, which is what makes a
 * reload and a shared link agree.
 *
 * **Every block degrades on its own.** Fourteen routes back this page and any
 * of them is a throttled Yahoo pull away from nothing, so each gets its own
 * query and its own failure. A dead insider feed costs the insider card, not
 * the price chart above it.
 *
 * **The kind decides the page.** The search box finds shares, funds, coins and
 * indices alike, and a money-market fund read as a share is RSI calling cash
 * "overbought". The header names the kind with one line on what to read, and
 * `layout.ts` says which figures, averages and sections that kind gets.
 *
 * **No Plotly here.** This shell has no charting dependency and a page is not
 * free to add one. The charts are SVG built from design tokens — see
 * `plot.tsx`. There is no pan/box-select toolbar; there is every figure a
 * hover box needs, plus drag-to-zoom on the price chart.
 *
 * Deliberately absent, because the shell owns them: the chat drawer and the
 * guided tour, and with them the page's "Analyse with AI" button.
 */

import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { type Query, useApi } from "../../shell/useApi";
import { useInView } from "../../shell/useInView";
import { Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { useCurrency, useGuest } from "../../shell/session";
import { useRoute } from "../../shell/router";
import { Actions, type Mine } from "./Actions";
import { SignIn, SignedInOnly } from "../../shell/guest";
import { AnalystsSection } from "./Analysts";
import { FinancialsChart, ValuationChart } from "./Charts";
import { DcfSection } from "./Dcf";
import {
  getAnalysts,
  getOptions,
  getBars,
  getComparables,
  getCrypto,
  getCryptoCycle,
  getCryptoHolding,
  getFundFit,
  getCryptoPositioning,
  getEvents,
  getFinancials,
  getFund,
  getInsiders,
  getShorts,
  getMetrics,
  getDcf,
  getMoat,
  getPosition,
  getProfile,
  getQuote,
  getTrend,
  getValuation,
  getLastViewed,
  getWatchlist,
} from "./data";
import { CompareSection } from "./Compare";
import { PeerPicker } from "./Peers";
import { PriceSection, isRange, type Range } from "./Price";
import { SplitRepair } from "./Splits";
import { AssetStatsSection, KpiSourcesSection } from "./Reference";
import { CycleSection, HoldingSection, PositioningSection } from "./Crypto";
import { AiAsk } from "./AiAsk";
import { TickerShare } from "./Share";
import {
  ComparablesSection,
  FundSection,
  InsidersSection,
  ShortsSection,
  MetricsSection,
  MoatSection,
} from "./Sections";
import { FundFitSection } from "./FundFit";
import { Card, Empty, useMobile } from "./ui";
import type { Custodian, Profile, TickerPosition, WatchlistEntry } from "./types";
import "./ticker.css";
import { Badge } from "../../ui/Badge";
import { ASSETS, assetKind } from "../../shell/assets";
import { layout, resolveKind } from "./layout";

const RANGE_KEY = "ag-range";
const noop = () => undefined;
const CANDLES_KEY = "ag-candles";

/**
 * Per-viewer conveniences only, and every one of them reads fine as a default.
 *
 * Storage can throw in a private window or with site data blocked, and it never
 * reaches another device — which is exactly why the company itself lives in the
 * URL and only the chart's shape lives here.
 */
function remembered(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function remember(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private window, blocked storage — the page works without it */
  }
}

export default function Page() {
  const t = useT();
  const base = useCurrency();
  const mobile = useMobile();
  const { params, setParams } = useRoute();

  // `ticker` is the param every other page links with. `symbol` is accepted too
  // and never written: the API names the resolved symbol that way, and a link
  // built from a payload field should not be a dead end.
  const asked = (params.get("ticker") ?? params.get("symbol") ?? "")
    .trim()
    .toUpperCase();

  const [range, setRange] = useState<Range>(() => {
    const stored = remembered(RANGE_KEY, "1y");
    return isRange(stored) ? stored : "1y";
  });
  // Candles on a 390px screen are three pixels wide, so a phone defaults to the
  // line chart and a desktop to candles. `null` is "never chosen" — a reader who
  // picked once keeps their pick on both.
  const [candles, setCandles] = useState<boolean | null>(() => {
    const stored = remembered(CANDLES_KEY, "");
    return stored === "" ? null : stored === "1";
  });
  // Empty on purpose and reset whenever the company changes: each peer is a
  // fundamentals pull, so nothing is compared until a reader asks for one.
  const [peers, setPeers] = useState<string[]>([]);
  useEffect(() => setPeers([]), [asked]);
  // The reader's alerts and rules here, as the header's actions read them,
  // for the line of their own marks under the price.
  const [mine, setMine] = useState<Mine | null>(null);

  const watchlist = useApi(() => getWatchlist(), []);
  // A write comes back with the whole row, so the star, the chips and the peer
  // picker read the answer rather than costing a second fetch of the list — and
  // a symbol that was only held or only searched for appears here the moment it
  // is starred, which is what makes that upsert visible.
  const [written, setWritten] = useState<WatchlistEntry[]>([]);
  const onEntry = useCallback((entry: WatchlistEntry) => {
    setWritten((all) => [
      ...all.filter((one) => one.ticker.toUpperCase() !== entry.ticker.toUpperCase()),
      entry,
    ]);
  }, []);
  const entries = useMemo(() => {
    const listed = watchlist.state === "loaded" ? watchlist.data.entries : [];
    const merged = new Map(listed.map((entry) => [entry.ticker.toUpperCase(), entry]));
    for (const entry of written) merged.set(entry.ticker.toUpperCase(), entry);
    return [...merged.values()];
  }, [watchlist, written]);

  // No company in the URL: the first favourite, then the rest of the watchlist.
  const fallback = useMemo(() => {
    const ordered = [
      ...entries.filter((entry) => entry.favorite),
      ...entries.filter((entry) => !entry.favorite),
    ];
    return ordered[0]?.ticker ?? null;
  }, [entries]);

  // The page is the last company the reader looked at; the watchlist's first
  // favourite is only for an account that has looked at none. undefined while
  // that is still being asked, so the fallback does not win the race. A guest
  // has no searches of its own to ask for.
  const guest = useGuest();
  const [lastViewed, setLastViewed] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    if (asked) return;
    if (guest) {
      setLastViewed(null);
      return;
    }
    let live = true;
    getLastViewed()
      .then((last) => live && setLastViewed(last))
      .catch(() => live && setLastViewed(null));
    return () => {
      live = false;
    };
  }, [asked, guest]);

  useEffect(() => {
    if (asked || lastViewed === undefined) return;
    const next = lastViewed ?? fallback;
    if (next) setParams({ ticker: next });
  }, [asked, lastViewed, fallback, setParams]);

  const ticker = asked || null;

  const onCandles = useCallback((next: boolean) => {
    setCandles(next);
    remember(CANDLES_KEY, next ? "1" : "0");
  }, []);

  // The header is what tells a reader the page landed on the company they asked
  // for, so it is its own query and the first one to answer.
  const profile = useApi(
    () => (ticker ? getProfile(ticker) : Promise.resolve<Profile | null>(null)),
    [ticker],
  );
  // Quote, calendar and holding do not depend on the range, so changing it
  // redraws the chart without re-fetching any of them.
  const quote = useApi(
    () => (ticker ? getQuote(ticker, base) : Promise.resolve(null)),
    [ticker, base],
  );
  const events = useApi(
    () => (ticker ? getEvents(ticker) : Promise.resolve(null)),
    [ticker],
  );
  const position = useApi(
    () =>
      ticker ? getPosition(ticker, base) : Promise.resolve<TickerPosition | null>(null),
    [ticker, base],
  );
  const fund = useApi(
    () => (ticker ? getFund(ticker) : Promise.resolve(null)),
    [ticker],
  );
  // Once per symbol, beside the quote: the range pills redraw the chart, not
  // the trend. A money-market or bond fund answers empty without a download.
  const trend = useApi(
    () => (ticker ? getTrend(ticker) : Promise.resolve(null)),
    [ticker],
  );

  // What kind of symbol this is decides what the page draws at all
  // (`layout.ts`). A coin gets its own cards and nothing below; a fund gets
  // its profile and nothing below; an index gets its chart and nothing below.
  // Everything under those — results, fundamentals, valuation, analysts, moat,
  // insiders, comps and the KPI sources — is a company's, and for the rest it
  // would be a column of empty cards that each cost a fetch.
  //
  // The kind is the profile's (`stocks.data.asset_kind`). A fund is also
  // whatever `/fund` says once it answers — a catalog fund Yahoo files as a
  // share must not get company cards; until then the profile's catalog guess
  // stands in, so a fund page does not flash them. A failed profile reads as a
  // company: the sections degrade on their own.
  const drawn = profile.state === "loaded" ? profile.data : null;
  // No such symbol: a typo through the search's "analyze" row, or a stale
  // link. The header says so and the page stops — fourteen cards each saying
  // "no data" is the same answer told badly, and every one of them a fetch.
  const absent = drawn?.found === false;
  const fundSays =
    fund.state === "loaded" ? Boolean(fund.data?.is_fund) : Boolean(drawn?.is_fund);
  const kind = resolveKind(assetKind(drawn?.asset), {
    crypto: Boolean(drawn?.is_crypto),
    fund: fundSays,
  });
  const shape = layout(kind);

  // A fund or an index opens on its long line (`layout.ts` `opens`), not on
  // the range a share's page last showed. A pick on the page holds while the
  // reader stays on it, and only a share's or a coin's pick is remembered for
  // the next company: a week chosen on a stock must not open every ETF on a
  // week, nor its whole history chosen on an ETF every stock on its whole history. An index
  // is named by its caret before the profile answers.
  const [picked, setPicked] = useState<{ ticker: string; range: Range } | null>(null);
  const opens = shape.opens ?? (ticker?.startsWith("^") ? "max" : null);
  const own = picked && picked.ticker === ticker ? picked.range : null;
  const chartRange: Range = own ?? opens ?? range;
  const onRange = useCallback(
    (next: Range) => {
      if (ticker) setPicked({ ticker, range: next });
      if (opens) return;
      setRange(next);
      remember(RANGE_KEY, next);
    },
    [ticker, opens],
  );
  const bars = useApi(
    () => (ticker ? getBars(ticker, chartRange) : Promise.resolve(null)),
    [ticker, chartRange],
  );
  // Until the profile names the kind, bars asked on the reader's last range
  // may be a share's week on what turns out to be an ETF: the chart waits
  // rather than draw a week and then swap it for five years.
  const chartReady = own !== null || opens !== null || profile.state !== "loading";
  // The ranges this company's history fills, as its last bars answered. Held
  // in state so the pills do not all come back while the next range loads,
  // and tagged with the company so the previous one's never apply here.
  const [fills, setFills] = useState<{ ticker: string; ranges: Range[] } | null>(null);
  useEffect(() => {
    if (bars.state !== "loaded" || !bars.data?.ranges?.length) return;
    setFills({ ticker: bars.data.ticker, ranges: bars.data.ranges.filter(isRange) });
  }, [bars]);
  const offered = fills && fills.ticker === ticker ? fills.ranges : null;
  // A remembered "5Y" on a stock two years old is not re-fetched as "max":
  // five years trimmed from a two-year history already IS the whole of it.
  // Only the pill and the period line change, and the reader's pick stays
  // stored for the next company that has five years to show.
  const shown: Range = offered && !offered.includes(chartRange) ? "max" : chartRange;
  const crypto = shape.sections.stats;
  const company = profile.state !== "loading" && shape.sections.company && !absent;
  // Named once the profile has answered: a label that flips from "Share" to
  // "Money market" as the page loads is a wrong answer shown first.
  const named = drawn && !absent ? ASSETS[kind] : null;

  // The sections a reader could see so far on this company (`Slot`). The rest
  // are not asked for: on a phone they are folded headings, and on any screen
  // they are pages down — a dozen requests queued ahead of what the reader
  // went to next.
  const [seen, setSeen] = useState<{ ticker: string | null; ids: ReadonlySet<SlotId> }>(
    () => ({ ticker: null, ids: new Set() }),
  );
  const onSeen = useCallback(
    (id: SlotId) =>
      setSeen((prev) =>
        prev.ticker !== ticker
          ? { ticker, ids: new Set([id]) }
          : prev.ids.has(id)
            ? prev
            : { ticker, ids: new Set(prev.ids).add(id) },
      ),
    [ticker],
  );
  const wanted = (id: SlotId) => seen.ticker === ticker && seen.ids.has(id);
  const wantsMetrics = wanted("fundamentals") || wanted("valuation");
  const wantsFinancials = wanted("results");
  const wantsDcf = wanted("dcf");
  const wantsMoat = wanted("moat");
  const wantsInsiders = wanted("insiders");
  const wantsShorts = wanted("shorts");
  const wantsAnalysts = wanted("analysts");
  const wantsCycle = wanted("cycle");
  const wantsPositioning = wanted("positioning");

  // `undefined` is "not asked yet" and `null` the server's "nothing": a slot
  // holds its heading on the first and gives way on the second (`settled`).
  const metrics = useApi(
    () =>
      ticker && company && wantsMetrics
        ? getMetrics(ticker, base)
        : Promise.resolve(undefined),
    [ticker, base, company, wantsMetrics],
  );
  const financials = useApi(
    () =>
      ticker && company && wantsFinancials
        ? getFinancials(ticker)
        : Promise.resolve(undefined),
    [ticker, company, wantsFinancials],
  );
  const valuation = useApi(
    () => (ticker && company ? getValuation(ticker) : Promise.resolve(null)),
    [ticker, company],
  );
  const dcf = useApi(
    () => (ticker && company && wantsDcf ? getDcf(ticker) : Promise.resolve(undefined)),
    [ticker, company, wantsDcf],
  );
  const moat = useApi(
    () =>
      ticker && company && wantsMoat ? getMoat(ticker) : Promise.resolve(undefined),
    [ticker, company, wantsMoat],
  );
  const insiders = useApi(
    () =>
      ticker && company && wantsInsiders
        ? getInsiders(ticker)
        : Promise.resolve(undefined),
    [ticker, company, wantsInsiders],
  );
  // Beside the insiders, not after them: its own request, painted when it lands.
  const shorts = useApi(
    () =>
      ticker && company && wantsShorts ? getShorts(ticker) : Promise.resolve(undefined),
    [ticker, company, wantsShorts],
  );
  const analysts = useApi(
    () =>
      ticker && company && wantsAnalysts
        ? getAnalysts(ticker)
        : Promise.resolve(undefined),
    [ticker, company, wantsAnalysts],
  );

  // Its own request: cold it is a handful of option chains, and the card
  // draws without it.
  const options = useApi(
    () =>
      ticker && company && wantsAnalysts ? getOptions(ticker) : Promise.resolve(null),
    [ticker, company, wantsAnalysts],
  );

  const stats = useApi(
    () => (ticker && crypto ? getCrypto(ticker) : Promise.resolve(null)),
    [ticker, crypto],
  );
  const cycle = useApi(
    () =>
      ticker && shape.sections.cycle && wantsCycle
        ? getCryptoCycle(ticker)
        : Promise.resolve(undefined),
    [ticker, shape.sections.cycle, wantsCycle],
  );
  const positioning = useApi(
    () =>
      ticker && shape.sections.positioning && wantsPositioning
        ? getCryptoPositioning(ticker)
        : Promise.resolve(undefined),
    [ticker, shape.sections.positioning, wantsPositioning],
  );
  // Only for a coin the book holds: `/position` answers first, and a coin
  // nobody holds costs no replay.
  const holds = Boolean(
    shape.sections.holding && position.state === "loaded" && position.data?.held,
  );
  const coinHolding = useApi(
    () => (ticker && holds ? getCryptoHolding(ticker, base) : Promise.resolve(null)),
    [ticker, base, holds],
  );
  // A fund against the reader's book: an account's question, so never asked
  // for a guest, and not for a cash fund whose basket is deposits.
  const fits = Boolean(
    !guest &&
    shape.sections.fundHoldings &&
    fund.state === "loaded" &&
    fund.data?.is_fund &&
    !fund.data.closed_end,
  );
  const fit = useApi(
    () => (ticker && fits ? getFundFit(ticker, base) : Promise.resolve(null)),
    [ticker, base, fits],
  );
  const coin = (drawn?.symbol || ticker || "").split("-")[0] ?? "";
  const comps = useApi(
    () =>
      ticker && peers.length
        ? getComparables([ticker, ...peers])
        : Promise.resolve(null),
    [ticker, peers.join(",")],
  );

  const held = position.state === "loaded" ? position.data : null;
  const entry =
    entries.find((one) => one.ticker.toUpperCase() === (ticker ?? "")) ?? null;
  // The grid's own P/E, for the valuation card's vintage warning: the two are
  // reconstructed from different feeds and legitimately diverge around earnings.
  const gridPe =
    metrics.state === "loaded"
      ? ((metrics.data?.kpis.find((kpi) => kpi.key === "pe_ttm")?.value as
          number | null) ?? null)
      : null;

  return (
    <div className="tk-page">
      <header className="tk-header">
        <div className="tk-id">
          {drawn?.logo ? <img className="tk-logo" src={drawn.logo} alt="" /> : null}
          <div className="tk-names">
            <div className="tk-title">
              {/* The RESOLVED symbol. A ledger keeps whatever the broker wrote,
                  because that string is the audit trail — and "US81762P1021"
                  tells nobody it is ServiceNow. The URL and every link keep the
                  original. */}
              <h1>{drawn?.symbol || ticker || "—"}</h1>
              {drawn?.name &&
              drawn.name.toUpperCase() !== (drawn.symbol || "").toUpperCase() ? (
                <span className="tk-name">{drawn.name}</span>
              ) : null}
            </div>
            {/* What this is, before whether the reader owns it: the search box
                finds shares, funds, coins and indices alike, and each is read
                by different figures. Then the reader's own: held, where, and
                the groups they filed it under. */}
            {named || held?.held || held?.custody?.length || entry?.tags.length ? (
              <div className="tk-meta">
                {named ? <Badge>{t(named.label)}</Badge> : null}
                {held?.held ? <Badge>{t("ticker.in_portfolio")}</Badge> : null}
                <Custody marks={held?.custody ?? []} />
                {entry?.tags.map((tag) => (
                  <span className="tk-group" key={tag}>
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        {/* One primary action, and the rest as icons beside it: the star is a
            state one press flips, so it stays in sight; alerts, tags, the
            journal and sharing are "More". */}
        {ticker && !absent ? (
          <div className="tk-acts">
            {/* Drawn for a guest too: it opens the locked assistant
                (`chat/Locked.tsx`), which shows the question and keeps it for
                after the sign-in — the button is the reason to make an
                account. The question is the kind's: a coin has no
                fundamentals, a fund no business of its own, and an index
                nothing to buy — so no button. A symbol still loading reads as
                a share: the prompt is a question, not a claim. */}
            {shape.ai ? (
              <AiAsk
                ticker={ticker}
                name={drawn?.name || ticker}
                prompt={shape.ai}
                angles={shape.kind === "stock"}
              />
            ) : null}
            {/* Every action but sharing is somebody's own edit to their own
                list; a guest is offered the sign-in that would make them
                theirs, and the share alone — a menu of one row is no menu. */}
            <div className="tk-tools">
              <SignedInOnly
                fallback={
                  <>
                    <TickerShare ticker={ticker} name={drawn?.name} />
                    <SignIn className="ag-btn tk-signin" />
                  </>
                }
              >
                <Actions
                  ticker={ticker}
                  name={drawn?.name ?? ""}
                  held={!!held?.held}
                  entry={entry}
                  onEntry={onEntry}
                  onMine={setMine}
                />
              </SignedInOnly>
            </div>
          </div>
        ) : null}
        {/* No search box here: the shell's top-bar search is the one way to
            change company — two boxes that both navigate is one too many, and
            only the shell's keeps the recents. */}
      </header>

      {/* Nothing picked yet — an invitation rather than a column of empty
          cards. */}
      {!ticker ? (
        watchlist.state === "loading" ? (
          <Skeleton rows={6} />
        ) : (
          <Empty>{t("ticker.pick_prompt")}</Empty>
        )
      ) : absent ? (
        <Empty>{t("ticker.not_found", { ticker })}</Empty>
      ) : (
        <>
          {/* The bars go down as a query: the price card keeps its range and
              chart controls through a failed fetch and shows the error in the
              chart's slot. */}
          {/* Before the figures it corrects: a missing split makes every one
              of them wrong, so the line that says so is read first. */}
          {shape.holdable ? (
            <SplitRepair
              ticker={ticker}
              position={held}
              onChanged={position.state === "loaded" ? position.reload : noop}
            />
          ) : null}
          <PriceSection
            query={chartReady ? bars : { state: "loading" }}
            quote={quote.state === "loaded" ? quote.data : null}
            events={events.state === "loaded" ? (events.data?.earnings ?? []) : []}
            position={held}
            range={shown}
            offered={offered}
            onRange={onRange}
            candles={candles ?? !mobile}
            onCandles={onCandles}
            shape={shape}
            fund={fund.state === "loaded" ? fund.data : null}
            stats={stats.state === "loaded" ? stats.data : null}
            cycle={events.state === "loaded" ? (events.data?.cycle ?? []) : []}
            valuation={valuation.state === "loaded" ? valuation.data : null}
            trend={trend.state === "loaded" ? trend.data : null}
            ticker={ticker}
            mine={mine}
          />

          {/* Compare sits one card from the foot of the page, whatever the
              kind: the figures a reader came for go first, and "did it beat
              the index" closes the read. A fund and an index have one card
              under the price, so there it is the card after the price. */}
          {shape.compare && !shape.sections.company && !crypto ? (
            <Slot
              key={`compare:${ticker}`}
              id="compare"
              title={t("ticker.compare")}
              note={t("ticker.compare_note", { base })}
              ready={wanted("compare")}
              onSeen={onSeen}
            >
              <CompareSection ticker={ticker} base={base} />
            </Slot>
          ) : null}

          {/* A fund stops here. */}
          {shape.sections.fund && fund.state === "loaded" && fund.data?.is_fund ? (
            <FundSection fund={fund.data} holdings={shape.sections.fundHoldings} />
          ) : null}
          {fund.state === "loaded" &&
          fund.data &&
          fit.state === "loaded" &&
          fit.data ? (
            <FundFitSection fund={fund.data} fit={fit.data} />
          ) : null}

          {/* …and a coin pair here: no statements, no Form 4, no comps. */}
          {/* Your coin first — the line no market source has — then where it
              sits in its cycle, then how the leveraged crowd holds it. */}
          {coinHolding.state === "loaded" && coinHolding.data ? (
            <HoldingSection holding={coinHolding.data} coin={coin} />
          ) : null}
          {shape.sections.cycle ? (
            <Slot
              key={`cycle:${ticker}`}
              id="cycle"
              title={t("ticker.cycle_title")}
              ready={settled(cycle)}
              onSeen={onSeen}
            >
              {cycle.state === "loaded" && cycle.data ? (
                <CycleSection cycle={cycle.data} coin={coin} />
              ) : null}
            </Slot>
          ) : null}
          {shape.sections.positioning ? (
            <Slot
              key={`positioning:${ticker}`}
              id="positioning"
              title={t("ticker.positioning_title")}
              ready={settled(positioning)}
              onSeen={onSeen}
            >
              {positioning.state === "loaded" && positioning.data ? (
                <PositioningSection data={positioning.data} coin={coin} />
              ) : null}
            </Slot>
          ) : null}
          {shape.compare && crypto ? (
            <Slot
              key={`compare:${ticker}`}
              id="compare"
              title={t("ticker.compare")}
              note={t("ticker.compare_note", { base })}
              ready={wanted("compare")}
              onSeen={onSeen}
            >
              <CompareSection ticker={ticker} base={base} />
            </Slot>
          ) : null}
          {crypto && stats.state === "loaded" && stats.data ? (
            <AssetStatsSection stats={stats.data} />
          ) : null}

          {/* A company: annual results, then the KPI grid, then the multiple
              against its own history. */}
          {company ? (
            <>
              <Slot
                key={`results:${ticker}`}
                id="results"
                title={t("ticker.chart_annual_title")}
                ready={settled(financials)}
                onSeen={onSeen}
              >
                {financials.state === "loaded" && financials.data ? (
                  <FinancialsChart data={financials.data} />
                ) : null}
              </Slot>

              <Slot
                key={`fundamentals:${ticker}`}
                id="fundamentals"
                title={t("ticker.fundamentals")}
                ready={settled(metrics)}
                onSeen={onSeen}
              >
                {metrics.state === "loaded" && metrics.data ? (
                  <MetricsSection metrics={metrics.data} />
                ) : null}
              </Slot>

              {/* Its figures are the price card's too, so they are already
                  here; the slot waits for the grid's P/E it is checked
                  against. */}
              <Slot
                key={`valuation:${ticker}`}
                id="valuation"
                title={t("ticker.valuation_history")}
                ready={wanted("valuation") && settled(metrics) && settled(valuation)}
                onSeen={onSeen}
              >
                {valuation.state === "loaded" && valuation.data ? (
                  <ValuationChart
                    data={valuation.data}
                    fundamentalPe={gridPe}
                    trades={held?.trades ?? []}
                  />
                ) : null}
              </Slot>

              <Slot
                key={`dcf:${ticker}`}
                id="dcf"
                title={t("ticker.dcf")}
                ready={settled(dcf)}
                onSeen={onSeen}
              >
                {dcf.state === "loaded" && dcf.data ? (
                  <DcfSection dcf={dcf.data} />
                ) : null}
              </Slot>

              {/* What the street makes of it, right after what it is priced at. */}
              <Slot
                key={`analysts:${ticker}`}
                id="analysts"
                title={t("ticker.analysts")}
                ready={settled(analysts)}
                onSeen={onSeen}
              >
                {analysts.state === "loaded" && analysts.data ? (
                  <AnalystsSection
                    data={analysts.data}
                    options={options.state === "loaded" ? options.data : null}
                  />
                ) : null}
              </Slot>

              <Slot
                key={`moat:${ticker}`}
                id="moat"
                title={t("ticker.moat")}
                ready={settled(moat)}
                onSeen={onSeen}
              >
                {moat.state === "loaded" && moat.data ? (
                  <MoatSection moat={moat.data} />
                ) : null}
              </Slot>

              <Slot
                key={`insiders:${ticker}`}
                id="insiders"
                title={t("ticker.insider_activity")}
                ready={settled(insiders)}
                onSeen={onSeen}
              >
                {insiders.state === "loaded" && insiders.data ? (
                  <InsidersSection insiders={insiders.data} />
                ) : null}
              </Slot>

              <Slot
                key={`shorts:${ticker}`}
                id="shorts"
                title={t("ticker.shorts_title")}
                ready={settled(shorts)}
                onSeen={onSeen}
              >
                {shorts.state === "loaded" && shorts.data ? (
                  <ShortsSection shorts={shorts.data} />
                ) : null}
              </Slot>
            </>
          ) : null}

          {company ? (
            <ComparablesSection comps={comps.state === "loaded" ? comps.data : null}>
              <PeerPicker
                ticker={ticker}
                watchlist={entries}
                peers={peers}
                onPeers={setPeers}
              />
            </ComparablesSection>
          ) : null}

          {/* Not before the profile answers: alone under the price card it
              would count as seen, and be asked for before the sections that
              then come in above it. */}
          {shape.compare && company ? (
            <Slot
              key={`compare:${ticker}`}
              id="compare"
              title={t("ticker.compare")}
              note={t("ticker.compare_note", { base })}
              ready={wanted("compare")}
              onSeen={onSeen}
            >
              <CompareSection ticker={ticker} base={base} />
            </Slot>
          ) : null}

          {company ? <KpiSourcesSection /> : null}
        </>
      )}
    </div>
  );
}

/** The sections below the price that wait to be seen; each is its card's fold id. */
type SlotId =
  | "results"
  | "fundamentals"
  | "valuation"
  | "dcf"
  | "analysts"
  | "moat"
  | "insiders"
  | "shorts"
  | "compare"
  | "cycle"
  | "positioning";

/** Answered or failed — not a query still waiting to be asked or to answer. */
function settled(query: Query<unknown>): boolean {
  return query.state === "loaded"
    ? query.data !== undefined
    : query.state !== "loading";
}

/**
 * A section below the price, asked for once a reader could see it: near the
 * viewport (`useInView`, which also waits while a phone's assistant covers the
 * page) and on show — on a phone the cards fold to their headings, and a
 * folded one shows nothing to fetch for.
 *
 * Until it is `ready` it holds its own card, folded under the same id and
 * heading, so a phone's index of headings is there from the start and the
 * section opens where the reader opened it.
 */
function Slot({
  id,
  title,
  note,
  ready,
  onSeen,
  children,
}: {
  id: SlotId;
  title: string;
  note?: string;
  ready: boolean;
  onSeen: (id: SlotId) => void;
  children: ReactNode;
}) {
  const [ref, near] = useInView<HTMLDivElement>();
  const [shown, setShown] = useState(false);
  const show = useCallback(() => setShown(true), []);
  useEffect(() => {
    if (near && shown) onSeen(id);
  }, [near, shown, id, onSeen]);
  return (
    <div ref={ref} className="tk-slot">
      {ready ? (
        children
      ) : (
        <Card fold={id} title={title} note={note} onShown={show}>
          <Skeleton rows={4} />
        </Card>
      )}
    </div>
  );
}

/**
 * Whose account the shares sit in: one brand mark per custodian, with its share
 * of the position on the tooltip.
 *
 * The two buckets that are not brands — a hand-entered row, and shares no
 * import note attributes — carry no logo and no name, because theirs is a
 * translated string. They read as a name pill rather than as a gap.
 */
function Custody({ marks }: { marks: Custodian[] }) {
  const t = useT();
  if (marks.length === 0) return null;
  return (
    <span className="tk-custody">
      {marks.map((mark) => {
        const name = mark.name || t(`portfolio.broker_${mark.broker}`);
        // The share only says something when there is more than one holder.
        const title =
          marks.length > 1 ? `${name} · ${Math.round(mark.share * 100)}%` : name;
        return mark.logo ? (
          <img
            className="tk-custody-mark"
            key={mark.broker}
            src={mark.logo}
            alt={title}
            title={title}
          />
        ) : (
          <Badge key={mark.broker} title={title}>
            {name}
          </Badge>
        );
      })}
    </span>
  );
}
