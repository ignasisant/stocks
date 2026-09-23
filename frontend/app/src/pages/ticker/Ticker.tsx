/**
 * Ticker — one company, read top to bottom: what it costs, what the reader owns
 * of it, what it earns, what it is worth against its own history, how defensible
 * it looks, who inside it has been dealing, and who to compare it against.
 *
 * Same running order as `web/app_pages/ticker.py`, which is the specification.
 *
 * **The company is the URL.** `?ticker=AAPL` — the param the Streamlit page
 * reads and writes, and the one every ticker cell in this shell already links
 * with — so a bookmark, a chat link or a notification lands on the same stock
 * whichever front end serves it. Written with `setParams`, which is what makes
 * a reload and a shared link agree.
 *
 * **Every block degrades on its own.** Fourteen routes back this page and any
 * of them is a throttled Yahoo pull away from nothing, so each gets its own
 * query and its own failure. A dead insider feed costs the insider card, not
 * the price chart above it.
 *
 * **No Plotly here.** The Streamlit page and the standalone `/ticker` document
 * draw these charts with it; this shell has no Plotly dependency and a page is
 * not free to add one. The charts are SVG built from design tokens — see
 * `plot.tsx`. What is lost is the pan/box-select toolbar; what is kept is every
 * figure the hover boxes carried, plus drag-to-zoom on the price chart.
 *
 * Deliberately absent, because the shell owns them: the chat drawer and the
 * guided tour, and with them the page's "Analyse with AI" button.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
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
import { latest } from "./format";
import { PeerPicker } from "./Peers";
import { PositionTiles, PriceSection, isRange, type Range } from "./Price";
import { AssetStatsSection, KpiSourcesSection } from "./Reference";
import { askAssistant } from "../../shell/assistant";
import { Search } from "./Search";
import {
  ComparablesSection,
  FundSection,
  InsidersSection,
  MetricsSection,
  MoatSection,
} from "./Sections";
import { Card, Empty, useMobile } from "./ui";
import type { Custodian, Profile, TickerPosition, WatchlistEntry } from "./types";
import "./ticker.css";

const RANGE_KEY = "ag-range";
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

/**
 * Which analysis question this symbol deserves.
 *
 * A coin has no fundamentals and a fund has no business of its own, so both
 * get their own question rather than a company one that half applies. Read off
 * the payloads the page has already loaded: the header must not pay a lookup
 * to label a button, and a symbol still loading reads as a stock — the prompt
 * is a question, not a claim.
 */
function aiPromptKey(crypto: boolean, fund: boolean): string {
  if (crypto) return "ticker.ai_prompt_crypto";
  if (fund) return "ticker.ai_prompt_fund";
  return "ticker.ai_prompt";
}

export default function Page() {
  const t = useT();
  const base = useCurrency();
  const mobile = useMobile();
  const { params, setParams } = useRoute();

  // `ticker` is the param every other page links with and the one the Streamlit
  // page reads. `symbol` is accepted too and never written: the API names the
  // resolved symbol that way, and a link built from a payload field should not
  // be a dead end.
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

  // No company in the URL: the same default the Streamlit page picks — the first
  // favourite, then the rest of the watchlist.
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

  const pick = useCallback(
    (next: string) => {
      setParams({ ticker: next.trim().toUpperCase() });
      window.scrollTo(0, 0);
    },
    [setParams],
  );

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
  // Quote, calendar and holding do not depend on the range, so changing it
  // redraws the chart without re-fetching any of them.
  const quote = useApi(
    () => (ticker ? getQuote(ticker) : Promise.resolve(null)),
    [ticker],
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
  const metrics = useApi(
    () => (ticker ? getMetrics(ticker, base) : Promise.resolve(null)),
    [ticker, base],
  );
  const financials = useApi(
    () => (ticker ? getFinancials(ticker) : Promise.resolve(null)),
    [ticker],
  );
  const valuation = useApi(
    () => (ticker ? getValuation(ticker) : Promise.resolve(null)),
    [ticker],
  );
  const moat = useApi(
    () => (ticker ? getMoat(ticker) : Promise.resolve(null)),
    [ticker],
  );
  const insiders = useApi(
    () => (ticker ? getInsiders(ticker) : Promise.resolve(null)),
    [ticker],
  );
  const fund = useApi(
    () => (ticker ? getFund(ticker) : Promise.resolve(null)),
    [ticker],
  );

  const crypto = profile.state === "loaded" && profile.data?.is_crypto;
  const isFund = fund.state === "loaded" && Boolean(fund.data?.is_fund);
  const stats = useApi(
    () => (ticker && crypto ? getCrypto(ticker) : Promise.resolve(null)),
    [ticker, crypto],
  );
  const comps = useApi(
    () =>
      ticker && peers.length
        ? getComparables([ticker, ...peers])
        : Promise.resolve(null),
    [ticker, peers.join(",")],
  );

  const drawn = profile.state === "loaded" ? profile.data : null;
  const held = position.state === "loaded" ? position.data : null;
  // The last close the chart drew, which is what the holding is valued at:
  // `/position` reports cost in the position's own currency and prices nothing.
  const lastClose = bars.state === "loaded" ? latest(bars.data?.series.Close) : null;
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
        {held?.held ? (
          <span className="tk-badge">{t("ticker.in_portfolio")}</span>
        ) : null}
        <Custody marks={held?.custody ?? []} />
        {/* The assistant spends the operator's API keys and writes into a
            `chat.json` every anonymous visitor would share, and the drawer it
            opens is not mounted for a guest anyway — so the button that would
            open it goes with it rather than becoming one that does nothing. */}
        <SignedInOnly>
          {ticker ? (
            <button
              type="button"
              className="tk-ai"
              title={t("ticker.ai_analyze_help", { ticker })}
              onClick={() =>
                askAssistant(
                  t(aiPromptKey(Boolean(crypto), isFund), {
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
        <Search onPick={pick} />
      </header>

      {/* Nothing picked yet — the same invitation the Streamlit page opens with,
          rather than a column of empty cards. */}
      {!ticker ? (
        watchlist.state === "loading" ? (
          <Skeleton rows={6} />
        ) : (
          <Empty>{t("ticker.pick_prompt")}</Empty>
        )
      ) : (
        <>
          <Loaded query={bars} skeleton={<Skeleton rows={8} />}>
            {(data) => (
              <PriceSection
                bars={data}
                quote={quote.state === "loaded" ? quote.data : null}
                events={events.state === "loaded" ? (events.data?.earnings ?? []) : []}
                position={held}
                range={range}
                onRange={onRange}
                candles={candles ?? !mobile}
                onCandles={onCandles}
              />
            )}
          </Loaded>

          {/* On a phone the holding is already in the hero, as 2×2 tiles — the
              design's layout for a 390px screen, not a narrowed card. */}
          {!mobile && held?.held ? (
            <Card title={t("ticker.in_portfolio")}>
              <PositionTiles position={held} last={lastClose} t={t} />
            </Card>
          ) : null}

          {fund.state === "loaded" && fund.data?.is_fund ? (
            <FundSection fund={fund.data} />
          ) : null}

          {/* A coin pair has no fundamentals, no insiders and nothing to compare
              against, so it gets the block that does apply instead of a column
              of empty cards. */}
          {stats.state === "loaded" && stats.data ? (
            <AssetStatsSection stats={stats.data} />
          ) : null}

          {!crypto && metrics.state === "loaded" && metrics.data ? (
            <MetricsSection metrics={metrics.data} />
          ) : null}

          {financials.state === "loaded" && financials.data ? (
            <FinancialsChart data={financials.data} />
          ) : null}

          {valuation.state === "loaded" && valuation.data ? (
            <ValuationChart data={valuation.data} fundamentalPe={gridPe} />
          ) : null}

          {moat.state === "loaded" && moat.data ? (
            <MoatSection moat={moat.data} />
          ) : null}

          {!crypto && insiders.state === "loaded" && insiders.data ? (
            <InsidersSection insiders={insiders.data} />
          ) : null}

          {!crypto ? (
            <ComparablesSection comps={comps.state === "loaded" ? comps.data : null}>
              <PeerPicker
                ticker={ticker}
                watchlist={entries}
                peers={peers}
                onPeers={setPeers}
              />
            </ComparablesSection>
          ) : null}

          <KpiSourcesSection />
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
          <span className="tk-custody-name" key={mark.broker} title={title}>
            {name}
          </span>
        );
      })}
    </span>
  );
}
