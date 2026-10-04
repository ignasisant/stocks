/**
 * What the Market card and the editor draw.
 *
 * Market: a move is coloured by what it means for a holder, not by its sign —
 * the VIX rising is red, gold rising is grey — a yield moves in basis points,
 * and a FRED series has no ticker page to open. The editor lists the shown
 * cards in order with the hidden ones in the tray below.
 *
 * Rendered to static markup with no catalog: a key prints as itself.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Editor from "./Editor";
import { Market } from "./Market";
import { defaultLayout } from "./cards";
import type { MarketGlance, MarketTile } from "./types";

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

const tile = (over: Partial<MarketTile>): MarketTile => ({
  key: "sp500",
  symbol: "^GSPC",
  group: "equity",
  unit: "percent",
  value: 5000,
  changes: { day: 0.01, week: 0.02, month: -0.03 },
  welcome: 1,
  state: "up",
  percentile: null,
  linkable: true,
  as_of: "2026-10-02",
  ...over,
});

const glance: MarketGlance = {
  score: 62,
  regime: "appetite",
  run: 4,
  history: [50, 52, 55, 57, 58, 60, 62],
  tiles: [
    tile({}),
    tile({
      key: "vix",
      symbol: "^VIX",
      group: "volatility",
      value: 18,
      changes: { day: 0.05 },
      welcome: -1,
      state: "down",
      percentile: 80,
    }),
    tile({
      key: "us10y",
      symbol: "DGS10",
      group: "rate",
      unit: "basis_points",
      value: 4.25,
      changes: { day: 3 },
      welcome: -1,
      state: null,
      linkable: false,
    }),
    tile({ key: "gold", symbol: "GC=F", group: "commodity", welcome: 0 }),
    tile({ key: "unknown_feed" }),
  ],
  breadth: { hits: 9, total: 13, window: 200 },
  as_of: "2026-10-02",
  unavailable: null,
};

describe("the Market card", () => {
  const html = renderToStaticMarkup(<Market data={glance} />);

  it("shows the Pulse's regime with its week's move", () => {
    expect(html).toContain("hm-regime-up");
    expect(html).toContain("<strong>62</strong>");
    expect(html).toContain("sentiment.regime_appetite");
    expect(html).toContain("home.market_regime_delta");
  });

  it("colours a move by what it means for a holder", () => {
    // The S&P up is good, the VIX up is bad, gold up is neither.
    const sp = html.slice(html.indexOf("home.market_tile_sp500"));
    expect(sp).toMatch(/hm-mtile-change hm-tone-up/);
    const vix = html.slice(html.indexOf("home.market_tile_vix"));
    expect(vix).toMatch(/hm-mtile-change hm-tone-down/);
    const gold = html.slice(html.indexOf("home.market_tile_gold"));
    expect(gold).toMatch(/hm-mtile-change hm-tone-flat/);
  });

  it("moves a yield in basis points and gives it no ticker page", () => {
    expect(html).toContain("home.market_bp");
    expect(html).toContain(
      '<div class="hm-mtile"><span class="hm-mtile-label">home.market_tile_us10y',
    );
    expect(html).not.toContain("DGS10");
    expect(html).toContain("home.market_vix_pct");
  });

  it("leaves out a feed it has no label for", () => {
    expect(html).not.toContain("unknown_feed");
    expect(html.match(/class="hm-mtile"/g)).toHaveLength(4);
  });

  it("closes on the breadth and the date", () => {
    expect(html).toContain("home.market_breadth");
    expect(html).toContain("home.market_as_of");
  });
});

describe("the editor", () => {
  it("lists the shown cards in order, then the tray", () => {
    const html = renderToStaticMarkup(
      <Editor layout={defaultLayout()} onClose={() => {}} />,
    );
    const at = (key: string) => html.indexOf(`<strong>${key}</strong>`);
    expect(at("home.card_market")).toBeLessThan(at("home.card_daily"));
    expect(at("home.card_watchlist")).toBeLessThan(html.indexOf("home.edit_tray"));
    expect(html.indexOf("home.edit_tray")).toBeLessThan(at("home.card_risk"));
    // The first row cannot go up, the last shown cannot go down — switched
    // off by aria, so focus is not dropped when a row lands there.
    expect(html.match(/class="hm-edit-icon" aria-disabled="true"/g)).toHaveLength(2);
  });
});
