/**
 * The movers card draws every name, each side strongest first: the biggest
 * gain and the worst loss open their halves. "Strongest" is the percentage or
 * the money the move was worth.
 */

import { describe, expect, it } from "vitest";

import { moveMoney, moverSides } from "./Glance";
import type { Mover } from "./types";

const row = (ticker: string, pct: number): Mover => ({ ticker, pct });
const pcts = (rows: Mover[]) => rows.map((r) => r.pct);
const tickers = (rows: Mover[]) => rows.map((r) => r.ticker);

// As `/movers?all=true` sends them: each side strongest first.
const GAINERS = [
  row("SHOP", 0.0483),
  row("META", 0.0326),
  row("RVMD", 0.0221),
  row("DXCM", 0.0215),
];
const LOSERS = [
  row("MNDY", -0.0472),
  row("ORCL", -0.0277),
  row("ESTC", -0.0276),
  row("FIG", -0.0262),
];

describe("moverSides", () => {
  it("opens each side on its strongest move, the worst loss first", () => {
    const { gainers, losers } = moverSides({ gainers: GAINERS, losers: LOSERS });
    expect(pcts(gainers)).toEqual([0.0483, 0.0326, 0.0221, 0.0215]);
    expect(pcts(losers)).toEqual([-0.0472, -0.0277, -0.0276, -0.0262]);
  });

  it("draws every name, however many moved", () => {
    const many = Array.from({ length: 30 }, (_, i) => row(`T${i}`, -0.001 * (i + 1)));
    expect(moverSides({ gainers: [], losers: many }).losers).toHaveLength(30);
  });

  it("ranks on money when asked, the biggest loss first", () => {
    // A small move on a big position outweighs a big move on a small one.
    const values: Record<string, number> = {
      SHOP: 500,
      META: 20_000,
      RVMD: 1_000,
      DXCM: 3_000,
      MNDY: 200,
      ORCL: 15_000,
      ESTC: 4_000,
      FIG: 900,
    };
    const worth = (r: Mover) => moveMoney(r.pct, values[r.ticker]);
    const { gainers, losers } = moverSides(
      { gainers: GAINERS, losers: LOSERS },
      "money",
      worth,
    );
    expect(tickers(gainers)).toEqual(["META", "DXCM", "SHOP", "RVMD"]);
    expect(tickers(losers)).toEqual(["ORCL", "ESTC", "FIG", "MNDY"]);
  });

  it("puts a row with no money figure at the end of its side", () => {
    const worth = (r: Mover) =>
      r.ticker === "SHOP" || r.ticker === "MNDY" ? null : moveMoney(r.pct, 1000);
    const { gainers, losers } = moverSides(
      { gainers: GAINERS, losers: LOSERS },
      "money",
      worth,
    );
    expect(gainers.at(-1)?.ticker).toBe("SHOP");
    expect(losers.at(-1)?.ticker).toBe("MNDY");
  });

  it("leaves a side empty when nothing moved that way", () => {
    expect(moverSides({ gainers: [], losers: [row("MSFT", -0.01)] })).toEqual({
      gainers: [],
      losers: [row("MSFT", -0.01)],
    });
    expect(moverSides({ gainers: GAINERS, losers: [] }).losers).toEqual([]);
  });

  it("leaves the response it was handed alone", () => {
    const losers = [...LOSERS];
    const gainers = [...GAINERS];
    moverSides({ gainers, losers }, "money", (r) => moveMoney(r.pct, 100));
    moverSides({ gainers, losers });
    expect(losers).toEqual(LOSERS);
    expect(gainers).toEqual(GAINERS);
  });
});

describe("moveMoney", () => {
  it("is the value now less the value at the window's start", () => {
    // 1 100 now after +10 %: it was 1 000, so +100.
    expect(moveMoney(0.1, 1100)).toBeCloseTo(100);
    // 900 now after −10 %: it was 1 000, so −100.
    expect(moveMoney(-0.1, 900)).toBeCloseTo(-100);
  });

  it("says nothing without a value or with an impossible move", () => {
    expect(moveMoney(0.1, null)).toBeNull();
    expect(moveMoney(0.1, undefined)).toBeNull();
    expect(moveMoney(-1, 100)).toBeNull();
    expect(moveMoney(Number.NaN, 100)).toBeNull();
  });
});
