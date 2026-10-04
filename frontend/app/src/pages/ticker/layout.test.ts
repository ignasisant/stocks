/**
 * The page's shape per kind of asset — what each kind is read by.
 *
 * The rows that matter are the ones the page got wrong: a money-market fund
 * drawn with an RSI that called cash "overbought", an index offered a
 * position block and an "Analyse" button. And the fallback: a kind the
 * server did not name must be the page as it always was.
 */

import { describe, expect, it } from "vitest";

import { ASSET_KINDS, ASSETS } from "../../shell/assets";
import { layout, resolveKind } from "./layout";

describe("layout", () => {
  it("draws a money-market fund by its yield, not its momentum", () => {
    const shape = layout("money_market");
    expect(shape.metrics).not.toContain("rsi");
    expect(shape.metrics).not.toContain("sma20");
    expect(shape.metrics).toEqual(["cash_yield", "policy", "ter"]);
    expect(shape.candles).toBe(false);
    expect(shape.overlays).toEqual([]);
    expect(shape.markers).toEqual([]);
    // The fund card, without a sector chart for a basket of deposits.
    expect(shape.sections.fund).toBe(true);
    expect(shape.sections.fundHoldings).toBe(false);
  });

  it("follows an index in points and offers nothing to hold", () => {
    const shape = layout("index");
    expect(shape.points).toBe(true);
    expect(shape.holdable).toBe(false);
    expect(shape.ai).toBeNull();
    expect(shape.sections.company).toBe(false);
    expect(Object.values(shape.sections).some(Boolean)).toBe(false);
  });

  it("only a share asks for the company sections", () => {
    const company = ASSET_KINDS.filter((kind) => layout(kind).sections.company);
    expect(company).toEqual(["stock"]);
  });

  it("only a coin is counted in units rather than shares", () => {
    const units = ASSET_KINDS.filter((kind) => layout(kind).units);
    expect(units).toEqual(["crypto"]);
  });

  it("reads a coin by its distance from the peak, not its SMA20", () => {
    const shape = layout("crypto");
    expect(shape.metrics).toEqual(["rsi", "ath_drawdown"]);
    expect(shape.markers).toEqual(["cycle"]);
    expect(shape.overlays).toContain("SMA20");
  });

  it("only a coin gets the cycle, positioning and holding cards", () => {
    for (const section of ["cycle", "positioning", "holding"] as const) {
      const kinds = ASSET_KINDS.filter((kind) => layout(kind).sections[section]);
      expect(kinds).toEqual(["crypto"]);
    }
  });

  it("an unnamed kind is a share", () => {
    expect(layout(null)).toBe(layout("stock"));
    expect(layout(null).metrics).toEqual(["rsi", "sma20"]);
    expect(layout(null).markers).toEqual(["results", "dividends"]);
  });

  it("every kind has a label and a line", () => {
    for (const kind of ASSET_KINDS) {
      expect(ASSETS[kind].label).toBe(`ticker.asset_${kind}`);
      expect(ASSETS[kind].help).toBe(`ticker.asset_${kind}_line`);
      expect(layout(kind).kind).toBe(kind);
    }
  });
});

describe("resolveKind", () => {
  const plain = { crypto: false, fund: false };

  it("takes the server's answer", () => {
    expect(resolveKind("money_market", plain)).toBe("money_market");
    expect(resolveKind("index", plain)).toBe("index");
  });

  it("falls back to the booleans without one", () => {
    expect(resolveKind(null, plain)).toBe("stock");
    expect(resolveKind(null, { crypto: true, fund: false })).toBe("crypto");
    expect(resolveKind(null, { crypto: false, fund: true })).toBe("equity_fund");
  });

  it("a basket overrules a share verdict", () => {
    expect(resolveKind("stock", { crypto: false, fund: true })).toBe("equity_fund");
  });
});
