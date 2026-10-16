import { describe, expect, it } from "vitest";
import { PER_SIDE, drawnMoves } from "./PlanChart";
import type { ReviewRow } from "./types";

const row = (symbol: string) => ({ ticker: symbol, symbol }) as ReviewRow;

describe("drawnMoves", () => {
  it("keeps the biggest of each side, in order", () => {
    const out = ["A", "B", "C", "D"].map(row);
    const into = ["E", "F"].map(row);
    expect(drawnMoves(out, into)).toEqual({
      sells: ["A", "B", "C"],
      adds: ["E", "F"],
      left: 1,
    });
    expect(PER_SIDE).toBe(3);
  });

  it("never draws SPY twice or a name on both sides", () => {
    const out = ["spy", "A"].map(row);
    const into = ["A", "B"].map(row);
    const drawn = drawnMoves(out, into);
    expect(drawn.sells).toEqual(["A"]);
    expect(drawn.adds).toEqual(["B"]);
  });
});
