import { describe, expect, it } from "vitest";

import { readFunds } from "./Funds";
import type { SectorFunds } from "./types";

describe("readFunds", () => {
  // A body kept from before `lines` replaced `top` must not take the Sector
  // page down at `fund.lines.map`.
  it("reads a fund without lines or podium as empty lists", () => {
    const old = { sector: "Technology", funds: [{ ticker: "XDWT.DE", top: [] }] };
    const body = readFunds(old as unknown as SectorFunds);
    expect(body.funds[0]?.lines).toEqual([]);
    expect(body.funds[0]?.podium).toEqual([]);
  });

  it("reads a body without funds as no card", () => {
    expect(readFunds({} as SectorFunds).funds).toEqual([]);
  });
});
