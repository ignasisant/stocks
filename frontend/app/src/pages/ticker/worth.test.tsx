/**
 * The valuation frame names a reason only for the methods it draws, and the
 * peer bars draw nothing without the rivals' band. Static markup, no catalog:
 * copy comes out as its key.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PeerBars, WorthSection } from "./Worth";
import type { Analysts, Comparables, Dcf } from "./types";

const dcf = { reason: null, value: 64, price: 100, currency: "USD" } as Dcf;
const analysts = {
  covered: true,
  price: 100,
  currency: "USD",
  analysts: 12,
  targets: { low: 80, median: 170, high: 220 },
} as Analysts;
const comps: Comparables = {
  tickers: ["S", "A", "B", "C"],
  labels: ["P/E (TTM)"],
  keys: ["pe_ttm"],
  lower_better: [true],
  rows: { S: ["30.0x"] },
  medals: {},
  peer_median: ["20.0x"],
  peer_range: [""],
  outliers: {},
};

describe("WorthSection", () => {
  it("draws a row and a reason per method it has a figure for", () => {
    const html = renderToStaticMarkup(
      <WorthSection dcf={dcf} analysts={analysts} comps={comps} />,
    );
    expect(html).toContain("ticker.worth_dcf");
    expect(html).toContain("ticker.worth_analysts");
    expect(html).toContain("ticker.worth_peers");
    expect(html).toContain("ticker.worth_why_peers");
  });

  it("draws nothing with no figure, and no 'why' for a lone method", () => {
    expect(renderToStaticMarkup(<WorthSection />)).toBe("");
    const one = renderToStaticMarkup(<WorthSection dcf={dcf} />);
    expect(one).toContain("ticker.worth_dcf");
    expect(one).not.toContain("ticker.worth_why_head");
  });
});

describe("PeerBars", () => {
  it("is one bar per banded row, and nothing without them", () => {
    expect(renderToStaticMarkup(<PeerBars comps={comps} />)).toContain(
      "tk-peerbar-fill",
    );
    expect(renderToStaticMarkup(<PeerBars comps={null} />)).toBe("");
  });
});
