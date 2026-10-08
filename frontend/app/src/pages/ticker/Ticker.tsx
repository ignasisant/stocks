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

import { useCallback, useEffect, useMemo, useState } from "react";
import { useApi } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { useRoute } from "../../shell/router";
import { Actions } from "./Actions";
import { SignIn, SignedInOnly } from "../../shell/guest";
import { FinancialsChart, ValuationChart } from "./Charts";
import {
  getBars,
  getComparables,
  getCrypto,
  getCryptoCycle,
  getCryptoHolding,
  getCryptoPositioning,
  getEvents,
  getFinancials,
  getFund,
  getInsiders,
  getMetrics,
  getMoat,
  getPosition,
  getProfile,
  getQuote,
  getValuation,
  getWatchlist,
} from "./data";
import { PeerPicker } from "./Peers";
import { PriceSection, isRange, type Range } from "./Price";
import { SplitRepair } from "./Splits";
import { AssetStatsSection, KpiSourcesSection } from "./Reference";
import { CycleSection, HoldingSection, PositioningSection } from "./Crypto";
import { askAssistant } from "../../shell/assistant";
import {
  ComparablesSection,
  FundSection,
  InsidersSection,
  MetricsSection,
  MoatSection,
} from "./Sections";
import { Empty, useMobile } from "./ui";
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

  useEffect(() => {
    if (asked || !fallback) return;
    setParams({ ticker: fallback });
  }, [asked, fallback, setParams]);

  const ticker = asked || null;

  const onRange = useCallback((next: Range) => {
    setRange(next);
    remember(RANGE_KEY, next);
  }, []);

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
  const bars = useApi(
    () => (ticker ? getBars(ticker, range) : Promise.resolve(null)),
    [ticker, range],
  );
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
  const shown: Range = offered && !offered.includes(range) ? "max" : range;
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

  // What kind of symbol this is decides what the page draws at all
  // (`layout.ts`). A coin gets its own cards and nothing below; a fund gets
  // its profile and nothing below; an index gets its chart and nothing below.
  // Everything under those — results, fundamentals, valuation, moat, insiders,
  // comps and the KPI sources — is a company's, and for the rest it would be a
  // column of empty cards that each cost a fetch.
  //
  // The kind is the profile's (`stocks.data.asset_kind`). A fund is also
  // whatever `/fund` says once it answers — a catalog fund Yahoo files as a
  // share must not get company cards; until then the profile's catalog guess
  // stands in, so a fund page does not flash them. A failed profile reads as a
  // company: the sections degrade on their own.
  const drawn = profile.state === "loaded" ? profile.data : null;
  const fundSays =
    fund.state === "loaded" ? Boolean(fund.data?.is_fund) : Boolean(drawn?.is_fund);
  const kind = resolveKind(assetKind(drawn?.asset), {
    crypto: Boolean(drawn?.is_crypto),
    fund: fundSays,
  });
  const shape = layout(kind);
  const crypto = shape.sections.stats;
  const company = profile.state !== "loading" && shape.sections.company;
  // Named once the profile has answered: a label that flips from "Share" to
  // "Money market" as the page loads is a wrong answer shown first.
  const named = drawn ? ASSETS[kind] : null;

  const metrics = useApi(
    () => (ticker && company ? getMetrics(ticker, base) : Promise.resolve(null)),
    [ticker, base, company],
  );
  const financials = useApi(
    () => (ticker && company ? getFinancials(ticker) : Promise.resolve(null)),
    [ticker, company],
  );
  const valuation = useApi(
    () => (ticker && company ? getValuation(ticker) : Promise.resolve(null)),
    [ticker, company],
  );
  const moat = useApi(
    () => (ticker && company ? getMoat(ticker) : Promise.resolve(null)),
    [ticker, company],
  );
  const insiders = useApi(
    () => (ticker && company ? getInsiders(ticker) : Promise.resolve(null)),
    [ticker, company],
  );

  const stats = useApi(
    () => (ticker && crypto ? getCrypto(ticker) : Promise.resolve(null)),
    [ticker, crypto],
  );
  const cycle = useApi(
    () =>
      ticker && shape.sections.cycle ? getCryptoCycle(ticker) : Promise.resolve(null),
    [ticker, shape.sections.cycle],
  );
  const positioning = useApi(
    () =>
      ticker && shape.sections.positioning
        ? getCryptoPositioning(ticker)
        : Promise.resolve(null),
    [ticker, shape.sections.positioning],
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
        {drawn?.logo ? <img className="tk-logo" src={drawn.logo} alt="" /> : null}
        <div className="tk-names">
          {/* The RESOLVED symbol. A ledger keeps whatever the broker wrote,
              because that string is the audit trail — and "US81762P1021" tells
              nobody it is ServiceNow. The URL and every link keep the original. */}
          <h1>{drawn?.symbol || ticker || "—"}</h1>
          {drawn?.name &&
          drawn.name.toUpperCase() !== (drawn.symbol || "").toUpperCase() ? (
            <span className="tk-name">{drawn.name}</span>
          ) : null}
        </div>
        {/* What this is, before whether the reader owns it: the search box
            finds shares, funds, coins and indices alike, and each is read by
            different figures. */}
        {named ? (
          <Badge title={named.help ? t(named.help) : undefined}>{t(named.label)}</Badge>
        ) : null}
        {held?.held ? <Badge>{t("ticker.in_portfolio")}</Badge> : null}
        <Custody marks={held?.custody ?? []} />
        {/* The assistant spends the operator's API keys and writes into a
            `chat.json` every anonymous visitor would share, and the drawer it
            opens is not mounted for a guest anyway — so the button that would
            open it goes with it rather than becoming one that does nothing. */}
        {/* The question is the kind's: a coin has no fundamentals, a fund no
            business of its own, and an index nothing to buy — so no button. A
            symbol still loading reads as a share: the prompt is a question,
            not a claim. */}
        <SignedInOnly>
          {ticker && shape.ai ? (
            <button
              type="button"
              className="tk-ai"
              title={t("ticker.ai_analyze_help", { ticker })}
              onClick={() =>
                askAssistant(
                  t(shape.ai ?? "ticker.ai_prompt", {
                    ticker,
                    name: drawn?.name || ticker,
                  }),
                )
              }
            >
              {mobile ? "✨" : t("ticker.ai_analyze")}
            </button>
          ) : null}
        </SignedInOnly>
        {/* One swap covers three controls: the star, the tag menu and the
            price alert are all somebody's own edits to their own list, and all
            three live inside `<Actions>`. A guest is offered the thing that
            would make them theirs instead. */}
        {ticker ? (
          <SignedInOnly fallback={<SignIn className="ag-btn tk-signin" />}>
            <Actions ticker={ticker} entry={entry} onEntry={onEntry} />
          </SignedInOnly>
        ) : null}
        {/* No search box here: the shell's top-bar search is the one way to
            change company — two boxes that both navigate is one too many, and
            only the shell's keeps the recents. */}
      </header>
      {/* The one line on what the kind is and what to read it by — a reader
          who searched "xeon" learns here it is cash, not a share. */}
      {named?.help ? <p className="tk-kind-line">{t(named.help)}</p> : null}

      {/* Nothing picked yet — an invitation rather than a column of empty
          cards. */}
      {!ticker ? (
        watchlist.state === "loading" ? (
          <Skeleton rows={6} />
        ) : (
          <Empty>{t("ticker.pick_prompt")}</Empty>
        )
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
            query={bars}
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
          />

          {/* A fund stops here. */}
          {shape.sections.fund && fund.state === "loaded" && fund.data?.is_fund ? (
            <FundSection fund={fund.data} holdings={shape.sections.fundHoldings} />
          ) : null}

          {/* …and a coin pair here: no statements, no Form 4, no comps. */}
          {/* Your coin first — the line no market source has — then where it
              sits in its cycle, then how the leveraged crowd holds it. */}
          {coinHolding.state === "loaded" && coinHolding.data ? (
            <HoldingSection holding={coinHolding.data} coin={coin} />
          ) : null}
          {cycle.state === "loaded" && cycle.data ? (
            <CycleSection cycle={cycle.data} coin={coin} />
          ) : null}
          {positioning.state === "loaded" && positioning.data ? (
            <PositioningSection data={positioning.data} />
          ) : null}
          {crypto && stats.state === "loaded" && stats.data ? (
            <AssetStatsSection stats={stats.data} />
          ) : null}

          {/* A company: annual results, then the KPI grid, then the multiple
              against its own history. */}
          {financials.state === "loaded" && financials.data ? (
            <FinancialsChart data={financials.data} />
          ) : null}

          {metrics.state === "loaded" && metrics.data ? (
            <MetricsSection metrics={metrics.data} />
          ) : null}

          {valuation.state === "loaded" && valuation.data ? (
            <ValuationChart data={valuation.data} fundamentalPe={gridPe} />
          ) : null}

          {moat.state === "loaded" && moat.data ? (
            <MoatSection moat={moat.data} />
          ) : null}

          {insiders.state === "loaded" && insiders.data ? (
            <InsidersSection insiders={insiders.data} />
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

          {company ? <KpiSourcesSection /> : null}
        </>
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
