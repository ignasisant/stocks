/**
 * What the 52-week extremes card draws.
 *
 * Two runs, highs then lows, each under its own heading; a row says how far
 * from the edge, a word at it. An empty run drops its heading too.
 *
 * Rendered to static markup with no catalog: a key prints as itself.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExtremesCard } from "./Extremes";
import type { Extreme, Extremes } from "./types";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
    localStorage: { getItem: () => null, setItem: () => {} },
  });
  vi.stubGlobal("document", { documentElement: {} });
});
afterEach(() => vi.unstubAllGlobals());

const row = (ticker: string, edge: string, distance: number | null): Extreme => ({
  ticker,
  price: 100,
  edge,
  distance,
});

const draw = (extremes: Extreme[]) => {
  const data: Extremes = { extremes, scanned: 10 };
  return renderToStaticMarkup(
    <ExtremesCard query={{ state: "loaded", data, reload: () => {} } as never} />,
  );
};

describe("ExtremesCard", () => {
  it("heads the highs before the lows", () => {
    const html = draw([row("MSFT", "high", null), row("AAPL", "low", 0.012)]);
    const highs = html.indexOf("home.extremes_highs");
    const lows = html.indexOf("home.extremes_lows");
    expect(highs).toBeGreaterThan(-1);
    expect(lows).toBeGreaterThan(highs);
    expect(html.indexOf("MSFT")).toBeLessThan(lows);
    expect(html.lastIndexOf("AAPL")).toBeGreaterThan(lows);
  });

  it("says the edge in a word and the gap as a signed percentage", () => {
    const html = draw([row("MSFT", "high", null), row("AAPL", "low", 0.012)]);
    expect(html).toContain("home.at_high");
    expect(html).toMatch(/\+1[.,]2\s?%/);
    expect(html).not.toContain("home.at_low");
  });

  it("leaves out a run with no names", () => {
    const html = draw([row("MSFT", "high", -0.01)]);
    expect(html).toContain("home.extremes_highs");
    expect(html).not.toContain("home.extremes_lows");
  });
});
