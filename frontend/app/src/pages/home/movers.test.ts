/**
 * The movers card reads as one list, best to worst: gainers biggest first,
 * then losers mildest first so the worst loss is the last row. The server
 * sends both sides strongest first; the cut must keep the strongest of each
 * before the losers are flipped, whatever the size of the book.
 */

import { describe, expect, it } from "vitest";

import { moverSides } from "./Glance";
import type { Mover } from "./types";

const row = (ticker: string, pct: number): Mover => ({ ticker, pct });
const pcts = (rows: Mover[]) => rows.map((r) => r.pct);

// As `/home/movers` sends them: each side strongest first.
const GAINERS = [
  row("SHOP", 4.83),
  row("META", 3.26),
  row("RVMD", 2.21),
  row("DXCM", 2.15),
];
const LOSERS = [
  row("MNDY", -4.72),
  row("ORCL", -2.77),
  row("ESTC", -2.76),
  row("FIG", -2.62),
];

describe("moverSides", () => {
  it("puts the worst loss last, so the card reads best to worst", () => {
    const { gainers, losers } = moverSides({ gainers: GAINERS, losers: LOSERS }, 5);
    expect(pcts(gainers)).toEqual([4.83, 3.26, 2.21, 2.15]);
    expect(pcts(losers)).toEqual([-2.62, -2.76, -2.77, -4.72]);
    const all = pcts([...gainers, ...losers]);
    expect(all).toEqual([...all].sort((a, b) => b - a));
  });

  it("cuts to the strongest moves on each side before flipping", () => {
    const { gainers, losers } = moverSides({ gainers: GAINERS, losers: LOSERS }, 3);
    expect(gainers.map((r) => r.ticker)).toEqual(["SHOP", "META", "RVMD"]);
    // The three worst, not the three mildest — MNDY stays, at the bottom.
    expect(losers.map((r) => r.ticker)).toEqual(["ESTC", "ORCL", "MNDY"]);
  });

  it("draws what a small book has, fewer rows than asked", () => {
    const { gainers, losers } = moverSides(
      { gainers: [row("AAPL", 1.2)], losers: [row("MSFT", -3), row("NVDA", -0.4)] },
      5,
    );
    expect(pcts(gainers)).toEqual([1.2]);
    expect(pcts(losers)).toEqual([-0.4, -3]);
  });

  it("leaves a side empty when nothing moved that way", () => {
    expect(moverSides({ gainers: [], losers: [row("MSFT", -1)] }, 5)).toEqual({
      gainers: [],
      losers: [row("MSFT", -1)],
    });
    expect(moverSides({ gainers: GAINERS, losers: [] }, 5).losers).toEqual([]);
  });

  it("leaves the response it was handed alone", () => {
    const losers = [...LOSERS];
    moverSides({ gainers: GAINERS, losers }, 5);
    moverSides({ gainers: GAINERS, losers }, 5);
    expect(losers).toEqual(LOSERS);
  });
});
