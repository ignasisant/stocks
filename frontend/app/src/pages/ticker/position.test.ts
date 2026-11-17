import { describe, expect, it } from "vitest";
import { heldPosition } from "./data";
import type { TickerPosition } from "./types";

const position: TickerPosition = {
  ticker: "NVDA",
  held: true,
  shares: 3,
  currency: "USD",
  cost_native: 300,
  avg_cost_native: 100,
  base: "EUR",
  value: 400,
  weight: 0.1,
  trades: [],
  brokers: {},
  custody: [],
};

describe("heldPosition", () => {
  it("is null while nothing landed", () => {
    expect(heldPosition(null)).toBeNull();
    expect(heldPosition(undefined)).toBeNull();
  });

  it("hands a whole answer back as it came", () => {
    expect(heldPosition(position)).toBe(position);
  });

  // Prod 2026-11-13 (safari/ios, /ticker?ticker=NVDA): a position with no
  // `trades` reached the split check and `trades.some` blanked the page.
  it("gives an answer that lost its lists empty ones, not a crash", () => {
    const { trades: _t, brokers: _b, custody: _c, ...partial } = position;
    const held = heldPosition(partial as unknown as TickerPosition);
    expect(held?.trades).toEqual([]);
    expect(held?.brokers).toEqual({});
    expect(held?.custody).toEqual([]);
    expect(held?.trades.some((fill) => fill.action === "buy")).toBe(false);
  });
});
