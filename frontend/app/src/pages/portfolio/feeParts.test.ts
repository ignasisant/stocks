import { describe, expect, it } from "vitest";
import { feeParts, perThousand } from "./feeParts";
import type { BrokerCost } from "./api";

const row = (over: Partial<BrokerCost>): BrokerCost => ({
  broker: "x",
  trades: 1,
  volume: 1000,
  commission: 1,
  other_fees: 0,
  spread: 2,
  spread_bps: null,
  measured: 1,
  skipped: 0,
  outside_range: 0,
  total: null,
  cost_pct: null,
  ...over,
});

describe("feeParts", () => {
  it("splits each broker in three, largest total first, spread beats count as zero", () => {
    const parts = feeParts([
      row({ broker: "a", commission: 1, spread: -3 }),
      row({ broker: "b", commission: 2, other_fees: 1, spread: 4 }),
    ]);
    expect(parts.map((p) => p.broker)).toEqual(["b", "a"]);
    expect(parts[0]).toMatchObject({ commission: 2, other: 1, spread: 4, total: 7 });
    expect(parts[1]!.total).toBe(1);
  });
});

describe("perThousand", () => {
  it("scales a fraction to a thousand traded", () => {
    expect(perThousand(0.005)).toBeCloseTo(5);
    expect(perThousand(null)).toBeNull();
  });
});
