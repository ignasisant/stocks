/**
 * What the market card at the top of Today draws from the morning's read.
 *
 * The model's lines are listed by topic; a computed read's are not (they only
 * repeat the tiles below). The market's headline is the card's title only
 * where the page's own headline is someone else's; the regime is a dial that
 * opens Pulse. Quotes arrive after the first paint, so a static render has
 * none and draws no strip.
 *
 * Rendered to static markup with no catalog: a key prints as itself.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MarketBrief } from "./Brief";
import type { MarketCard } from "./types";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});
afterEach(() => vi.unstubAllGlobals());

const market = (over: Partial<MarketCard> = {}): MarketCard =>
  ({
    session: "2026-11-12",
    built_at: 0,
    lang: "es",
    source: "llm",
    headline: "Wall Street cierra en máximos",
    lines: [
      { topic: "trend", line: "El S&P 500 encadena tres semanas al alza." },
      { topic: "rates", line: "El 10 años baja 12 pb en el mes." },
    ],
    regime: { score: 62, key: "risk_on", run: 4, score_month: 48 },
    breadth: null,
    rates: [],
    banks: [],
    sectors: [],
    inflation: [],
    crypto: null,
    index: null,
    ...over,
  }) as MarketCard;

describe("the market card", () => {
  it("lists the model's lines under their topic", () => {
    const html = renderToStaticMarkup(<MarketBrief market={market()} headline />);
    expect(html).toContain("today.topic_trend");
    expect(html).toContain("today.topic_rates");
    expect(html).toContain("tres semanas al alza");
  });

  it("titles itself with the market's headline only when the page's is the reader's", () => {
    const own = renderToStaticMarkup(<MarketBrief market={market()} headline />);
    expect(own).toContain("Wall Street cierra en máximos");
    const page = renderToStaticMarkup(
      <MarketBrief market={market()} headline={false} />,
    );
    expect(page).not.toContain("Wall Street cierra en máximos");
    expect(page).toContain("today.sec_market");
  });

  it("leaves a computed read's lines to the tiles below", () => {
    const html = renderToStaticMarkup(
      <MarketBrief market={market({ source: "computed" })} headline />,
    );
    expect(html).not.toContain("today.topic_trend");
    expect(html).toContain("today.market_badge_computed");
  });

  it("draws the regime as a dial, its score and a month ago", () => {
    const html = renderToStaticMarkup(<MarketBrief market={market()} headline />);
    expect(html).toContain("td-dial");
    expect(html).toContain("<b>62</b>");
    expect(html).toContain("sentiment.regime_risk_on");
    expect(html).toContain("today.dial_month");
  });

  it("draws no quote strip before the quotes land", () => {
    const html = renderToStaticMarkup(<MarketBrief market={market()} headline />);
    expect(html).not.toContain("td-quotes");
    expect(html).not.toContain("today.quotes_note");
  });

  it("draws nothing with nothing to say", () => {
    const html = renderToStaticMarkup(
      <MarketBrief
        market={market({ source: "computed", regime: null })}
        headline={false}
      />,
    );
    expect(html).toBe("");
  });
});
