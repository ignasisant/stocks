/**
 * The market at a glance, first thing on the page: the morning's read in one
 * line per topic beside the risk regime and a strip of live quotes.
 *
 * The read and the regime come with the card (`chat/today_market.py`), written
 * once a morning for everyone; the quotes are asked for when the page opens
 * (`GET /market/quotes`, one upstream request for the strip) and never hold the
 * page up: until they land the strip is not drawn, and a symbol the feed could
 * not price is left out rather than shown as a zero. A computed read's lines
 * only repeat the tiles further down, so only the model's are listed here.
 */

import { useEffect, useState } from "react";
import { price } from "../../chat/chart";
import type { Quotes } from "../../api.gen";
import { Cancelled, get, withMemo } from "../../shell/api";
import { percent } from "../../shell/format";
import { useLang, useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { Badge } from "../../ui/Badge";
import { toneOf } from "../../ui/Kpi";
import type { MarketCard, MarketLine } from "./types";

/** The strip, in reading order: equities, then fear, money, metal, oil, coin.
 * `name` is an i18n key where the market has a common name in the reader's
 * language, a proper name otherwise. The 10-year yield is not here: it is the
 * first tile of Macro, with its month in basis points. `page: false` where the
 * ticker page has no layout for the kind (a currency pair, a future) and would
 * read it as a company with no business: that tile is not a link. */
const QUOTES = [
  { symbol: "^GSPC", name: "S&P 500" },
  { symbol: "^IXIC", name: "Nasdaq" },
  { symbol: "^STOXX50E", name: "Euro Stoxx 50" },
  { symbol: "^IBEX", name: "IBEX 35" },
  { symbol: "EEM", name: "today.quote_em" },
  { symbol: "^VIX", name: "VIX" },
  { symbol: "EURUSD=X", name: "EUR/USD", page: false },
  { symbol: "GC=F", name: "today.quote_gold", page: false },
  { symbol: "CL=F", name: "today.quote_oil", page: false },
  { symbol: "BTC-EUR", name: "Bitcoin" },
] as const;

const TOPICS: Record<MarketLine["topic"], string> = {
  trend: "today.topic_trend",
  sector: "today.topic_sector",
  rates: "today.topic_rates",
  macro: "today.topic_macro",
  crypto: "today.topic_crypto",
};

type Quote = Quotes["quotes"][number];

/** The strip's quotes by symbol; empty until they land or when they fail. */
function useQuotes(): Map<string, Quote> {
  const [quotes, setQuotes] = useState<Map<string, Quote>>(new Map());
  useEffect(() => {
    const scope = new AbortController();
    const tickers = QUOTES.map((quote) => quote.symbol).join(",");
    withMemo(() => get<Quotes>("/market/quotes", { tickers }), scope.signal).then(
      (answer) => {
        if (scope.signal.aborted) return;
        setQuotes(new Map(answer.quotes.map((quote) => [quote.ticker, quote])));
      },
      (error) => {
        // A strip that did not load is not drawn; the page is still whole.
        if (error instanceof Cancelled) return;
      },
    );
    return () => scope.abort();
  }, []);
  return quotes;
}

/** The regime's score on a half dial, 0 (fear) to 100 (appetite). */
function Dial({ regime }: { regime: NonNullable<MarketCard["regime"]> }) {
  const t = useT();
  const score = Math.max(0, Math.min(100, Math.round(regime.score)));
  // The arc is a half circle of radius 26: π·26 ≈ 81.7 long.
  const run = 81.7;
  const regimeName = t(`sentiment.regime_${regime.key}`);
  return (
    // The name carries the score too: a label alone would hide it from a
    // screen reader.
    <Link
      page="sentiment"
      className="td-dial"
      label={[
        `${score} · ${regimeName}`,
        regime.score_month !== null
          ? t("today.dial_month", { value: Math.round(regime.score_month) })
          : null,
        t("today.open_pulse"),
      ]
        .filter(Boolean)
        .join(" — ")}
    >
      <svg viewBox="0 0 64 36" width="64" height="36" aria-hidden="true">
        <path className="td-dial-track" d="M6 32 A26 26 0 0 1 58 32" />
        <path
          className="td-dial-fill"
          d="M6 32 A26 26 0 0 1 58 32"
          strokeDasharray={`${(score / 100) * run} ${run}`}
        />
      </svg>
      <span className="td-dial-text">
        <b>{score}</b>
        <small>
          {regimeName}
          {regime.score_month !== null
            ? ` · ${t("today.dial_month", { value: Math.round(regime.score_month) })}`
            : ""}
        </small>
      </span>
    </Link>
  );
}

export function MarketBrief({
  market,
  headline,
}: {
  market: MarketCard;
  /** Whether the market's headline is its own here; false when it is already
   * the page's headline (no card of the reader's own above it). */
  headline: boolean;
}) {
  const t = useT();
  const lang = useLang();
  const quotes = useQuotes();
  const lines = market.source === "llm" ? market.lines : [];
  const shown = QUOTES.filter((quote) => quotes.get(quote.symbol)?.price != null);
  if (!headline && !lines.length && !market.regime && !shown.length) return null;
  return (
    <section
      className={lines.length ? "td-sec td-brief" : "td-sec td-brief td-brief-short"}
      aria-labelledby="td-sec-brief"
    >
      <div className="td-brief-read">
        <header className="td-brief-head">
          <Badge tone={market.source === "llm" ? "brand" : "neutral"}>
            {t(
              market.source === "llm"
                ? "today.market_badge"
                : "today.market_badge_computed",
            )}
          </Badge>
        </header>
        <h2 className="td-brief-title" id="td-sec-brief">
          {headline && market.headline ? market.headline : t("today.sec_market")}
        </h2>
        {lines.length ? (
          <dl className="td-topics">
            {lines.map((line, n) => (
              <div key={n}>
                <dt>{t(TOPICS[line.topic] ?? "today.topic_macro")}</dt>
                <dd>{line.line}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
      {market.regime || shown.length ? (
        <div className="td-brief-side">
          {market.regime ? <Dial regime={market.regime} /> : null}
          {shown.length ? (
            <ul className="td-quotes">
              {shown.map((item) => {
                const { symbol, name } = item;
                const quote = quotes.get(symbol)!;
                // Under a twentieth of a point is flat: 0.0%, never "-0.0%".
                const flat = quote.pct != null && Math.abs(quote.pct) < 0.0005;
                const sign = flat ? "flat" : toneOf(quote.pct ?? null);
                const body = (
                  <>
                    <span className="td-quote-name">
                      {name.startsWith("today.") ? t(name) : name}
                    </span>
                    <b>{price(quote.price!, lang)}</b>
                    <small className={sign === "flat" ? undefined : `td-${sign}`}>
                      {quote.pct == null
                        ? t("home.na")
                        : flat
                          ? percent(0, { lang, digits: 1 })
                          : percent(quote.pct, { lang, digits: 1, signed: "always" })}
                    </small>
                  </>
                );
                return (
                  <li key={symbol}>
                    {"page" in item && item.page === false ? (
                      <div className="td-quote-tile">{body}</div>
                    ) : (
                      <Link
                        page="ticker"
                        params={{ ticker: symbol }}
                        className="td-quote-tile"
                      >
                        {body}
                      </Link>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : null}
          {shown.length ? (
            <p className="td-brief-note">{t("today.quotes_note")}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
