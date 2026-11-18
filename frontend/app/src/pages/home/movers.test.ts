/**
 * The movers card draws every name, each side strongest first: the biggest
 * gain and the worst loss open their halves. "Strongest" is the percentage or
 * the money the move was worth.
 */

import { describe, expect, it } from "vitest";

import { atQuote, moveMoney, moverSides, preOnly } from "./Glance";
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

describe("preOnly", () => {
  // Before the US open: `pct` is yesterday with the premarket on top,
  // `pre_pct` the premarket by itself.
  const pre = (ticker: string, pct: number, pre_pct: number): Mover => ({
    ticker,
    pct,
    pre_pct,
    premarket: true,
    active: true,
    in_session: false,
  });
  const open = (ticker: string, pct: number): Mover => ({
    ticker,
    pct,
    active: true,
    in_session: true,
  });
  // US extended hours with no print, or a market that is shut.
  const shut = (ticker: string, pct: number, active: boolean): Mover => ({
    ticker,
    pct,
    active,
    in_session: false,
  });

  it("reads a premarket row by its premarket alone", () => {
    const { gainers } = preOnly({ gainers: [pre("SEZL", 0.0543, 0.012)], losers: [] });
    expect(gainers).toEqual([
      { ...pre("SEZL", 0.0543, 0.012), pct: 0.012, premarket: false },
    ]);
  });

  it("keeps a name whose own market is open on its session", () => {
    const { gainers, losers } = preOnly({
      gainers: [open("SOL-EUR", 0.0192)],
      losers: [open("SAN.MC", -0.004)],
    });
    expect(tickers(gainers)).toEqual(["SOL-EUR"]);
    expect(pcts(losers)).toEqual([-0.004]);
  });

  it("leaves out a name that is not trading now", () => {
    const { gainers, losers } = preOnly({
      gainers: [shut("MNDY", 0.0263, true)],
      losers: [shut("7203.T", -0.01, false)],
    });
    expect(gainers).toEqual([]);
    expect(losers).toEqual([]);
  });

  it("splits the sides again on the premarket's own sign", () => {
    // Up yesterday and down this morning is a loser now, and the reverse.
    const { gainers, losers } = preOnly({
      gainers: [pre("HUBS", 0.0472, -0.003), pre("ADBE", 0.001, 0.02)],
      losers: [pre("DUOL", -0.03, 0.01), pre("SHOP", -0.02, -0.015)],
    });
    expect(tickers(gainers)).toEqual(["ADBE", "DUOL"]);
    expect(tickers(losers)).toEqual(["SHOP", "HUBS"]);
  });

  it("drops a premarket that has not moved", () => {
    const { gainers, losers } = preOnly({
      gainers: [pre("DSGX", 0.007, 0)],
      losers: [],
    });
    expect([...gainers, ...losers]).toEqual([]);
  });
});

describe("atQuote", () => {
  it("moves a close-priced figure to the premarket print", () => {
    expect(atQuote(100, { pre_pct: 0.02 })).toBeCloseTo(102);
  });

  it("leaves every other row alone", () => {
    expect(atQuote(100, {})).toBe(100);
    expect(atQuote(100, { pre_pct: null })).toBe(100);
    expect(atQuote(null, { pre_pct: 0.02 })).toBeNull();
  });

  it("makes the premarket alone worth the close value times the move", () => {
    // 1,000 at the close, +2 % before the bell: 20 gained, on 1,020 now.
    expect(moveMoney(0.02, atQuote(1000, { pre_pct: 0.02 }))).toBeCloseTo(20);
  });
});
