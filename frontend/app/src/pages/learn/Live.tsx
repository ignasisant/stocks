/**
 * The lesson's example, as it stands today: a real name from the app, with the
 * figures the Ticker page already serves (`/ticker/<symbol>/quote` and
 * `/metrics`). A figure that cannot be had is left out rather than guessed, and
 * a card with nothing to show is not drawn at all.
 */

import { get } from "../../shell/api";
import { Icon } from "../../shell/Icon";
import { money } from "../../shell/format";
import { useLang, useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import type { Live, LiveMetrics as Metrics, LiveQuote as Quote } from "./types";

/** How far below the price the lesson's limit order sits. */
const LIMIT_BELOW = 0.02;

const KPI: Record<string, string> = { cap: "market_cap", pe: "pe_ttm" };

type Figures = { quote: Quote | null; metrics: Metrics | null };

const at = (ticker: string) => `/ticker/${encodeURIComponent(ticker)}`;

/** One figure's text, or null when this name has none today. */
export function figure(
  fact: string,
  { quote, metrics }: Figures,
  lang: string,
): string | null {
  if (fact === "price" || fact === "limit") {
    const price = quote?.price;
    if (typeof price !== "number") return null;
    const value = fact === "limit" ? price * (1 - LIMIT_BELOW) : price;
    return money(value, { currency: quote?.currency ?? undefined, lang, digits: 2 });
  }
  const kpi = metrics?.kpis.find((k) => k.key === KPI[fact]);
  return kpi && kpi.value !== null && kpi.formatted !== "n/a" ? kpi.formatted : null;
}

export default function LiveCard({ live }: { live: Live }) {
  const t = useT();
  const lang = useLang();
  const needsMetrics = live.facts.some((f) => f in KPI);
  const query = useApi<Figures>(async () => {
    const [quote, metrics] = await Promise.all([
      get<Quote>(at(live.ticker) + "/quote").catch(() => null),
      needsMetrics
        ? get<Metrics>(at(live.ticker) + "/metrics").catch(() => null)
        : null,
    ]);
    return { quote, metrics };
  }, [live.ticker, needsMetrics]);
  if (query.state !== "loaded") return null;
  const shown = live.facts
    .map((fact) => [fact, figure(fact, query.data, lang)] as const)
    .filter((pair): pair is readonly [string, string] => pair[1] !== null);
  if (shown.length === 0) return null;
  return (
    <section className="lr-live" aria-labelledby="lr-live-h">
      <div className="lr-live-head">
        <h2 className="lr-live-title" id="lr-live-h">
          {t("learn.live_title")}
        </h2>
        <Link
          className="ag-btn lr-live-open"
          page="ticker"
          params={{ ticker: live.ticker }}
        >
          {t("learn.live_open", { ticker: live.ticker })}
          <Icon name="arrow_forward" size={16} />
        </Link>
      </div>
      <TickerCell ticker={live.ticker} className="lr-live-tick" />
      <dl className="lr-facts">
        {shown.map(([fact, text]) => (
          <div key={fact}>
            <dt>{t(`learn.live_${fact}`)}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
      <p className="lr-live-why">{live.why}</p>
    </section>
  );
}
