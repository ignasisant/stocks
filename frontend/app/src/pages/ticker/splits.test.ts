import { describe, expect, it } from "vitest";
import { fields, offered, unrefused, type Done } from "./Splits";
import type { TickerSplit } from "./types";

const AMZN: TickerSplit = {
  date: "2022-06-06",
  ratio: 20,
  held_before: 1,
  held_after: 20,
  priced_at: 2050,
  priced_on: "2022-05-24",
  market_close: 104.1,
  currency: "USD",
  declined: false,
};
const REFUSED: TickerSplit = { ...AMZN, date: "1999-09-02", ratio: 2, declined: true };

describe("split repair", () => {
  it("writes on its own only what the reader never undid", () => {
    expect(unrefused([AMZN, REFUSED])).toEqual([AMZN]);
    expect(unrefused([REFUSED])).toEqual([]);
  });

  it("offers a refused split behind the button, not unasked", () => {
    expect(offered(null, [AMZN, REFUSED])).toEqual([REFUSED]);
    expect(offered(null, [AMZN])).toEqual([]);
  });

  it("offers back what was undone or failed to write", () => {
    const undone: Done = { kind: "undone", splits: [AMZN] };
    const failed: Done = { kind: "failed", splits: [AMZN] };
    expect(offered(undone, [])).toEqual([AMZN]);
    expect(offered(failed, [])).toEqual([AMZN]);
  });

  it("offers nothing while the repair stands", () => {
    const applied: Done = { kind: "applied", changeId: 7, splits: [AMZN] };
    expect(offered(applied, [AMZN, REFUSED])).toEqual([]);
  });

  it("states the buy price as it reads after the split", () => {
    const said = fields(AMZN);
    expect(said.ratio).toBe("20");
    expect(said.day).toBe("2022-05-24");
    expect(said.adjusted).toBe(fields({ ...AMZN, priced_at: 102.5, ratio: 1 }).price);
  });
});
