/**
 * The Crypto tab's table: one block, four units.
 *
 * Fear & Greed is an index (points, no "pp"), DVOL a volatility (%), BTC
 * dominance a share (pp changes) and the stablecoin supply dollars (fractional
 * changes). A shared formatter would misprint three of them, so each is
 * asserted. Rendered to static markup against the shipped English catalog.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import strings from "../../../../../src/stocks/web/locales/en/sentiment.json";
import { Detail } from "./Detail";
import type { TrendBlock, TrendRow } from "./types";

vi.mock("../../shell/router", () => ({
  useRoute: () => ({
    params: new URLSearchParams("tab=crypto"),
    setParams: () => {},
  }),
}));

// The shipped English catalog, so labels and the band print as a reader sees them.
const catalog = strings as Record<string, string>;
/** A catalog string as static markup spells it ("Fear &amp; Greed"). */
const markup = (key: string) =>
  (catalog[`sentiment.${key}`] ?? key).replaceAll("&", "&amp;");
vi.mock("../../shell/i18n", async (original) => ({
  ...(await original<typeof import("../../shell/i18n")>()),
  useT: () =>
    Object.assign((key: string) => catalog[key] ?? key, {
      has: (key: string) => key in catalog,
    }),
}));

const row = (over: Partial<TrendRow>): TrendRow =>
  ({
    key: "",
    name: "",
    value: null,
    changes: {},
    spark: [],
    state: "unknown",
    percentile: null,
    percentile_then: null,
    welcome: 0,
    weight: null,
    as_of: "2026-11-25",
    ...over,
  }) as TrendRow;

const crypto: TrendBlock = {
  block: "crypto",
  unit: "points",
  expected: 5,
  rows: [
    row({
      key: "fear_greed",
      name: "extreme_fear",
      value: 12,
      changes: { week: -48, month: -48, quarter: -48 },
      percentile: 3,
      percentile_then: 50,
      welcome: 0,
    }),
    row({
      key: "dvol_btc",
      value: 48,
      changes: { week: -4 },
      percentile: 30,
      welcome: -1,
    }),
    row({ key: "btc_dominance", value: 57.5, changes: { week: 0.4 } }),
    row({
      key: "stablecoins",
      value: 2.8e11,
      changes: { month: -0.05, quarter: 0.02 },
      welcome: 1,
    }),
  ],
} as TrendBlock;

describe("crypto tab", () => {
  const html = renderToStaticMarkup(
    <Detail tables={{ blocks: [crypto] }} capture={null} onRetry={() => {}} />,
  );

  it("names each reading and the Fear & Greed band", () => {
    for (const key of [
      "crypto_title",
      "crypto_fear_greed",
      "fg_extreme_fear",
      "crypto_dvol_btc",
      "crypto_btc_dominance",
      "crypto_stablecoins",
    ]) {
      expect(html).toContain(markup(key));
    }
  });

  it("prints each row in its own unit", () => {
    expect(html).toMatch(/>12</);
    expect(html).toContain("p3 (50)");
    expect(html).toContain("48%");
    expect(html).toContain("57.5%");
    expect(html).toContain("$280B");
    expect(html).toContain(">+0.4pp<");
    expect(html).toContain(">-5.0%<");
  });

  it("does not call index-point moves percentage points", () => {
    const fearGreed = html.slice(
      html.indexOf(markup("crypto_fear_greed")),
      html.indexOf(markup("crypto_dvol_btc")),
    );
    expect(fearGreed).toMatch(/48</);
    expect(fearGreed).not.toContain("pp");
  });
});
