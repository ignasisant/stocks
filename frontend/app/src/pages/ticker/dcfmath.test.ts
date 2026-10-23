import { describe, expect, it } from "vitest";

import fixture from "./dcf.fixture.json";
import { valuePerShare } from "./dcfmath";

describe("valuePerShare", () => {
  it.each(fixture.cases)("agrees with the Python on %j", (c) => {
    const got = valuePerShare(
      c.fcf,
      c.growth,
      c.wacc,
      c.terminal,
      c.net_debt,
      c.shares,
    );
    if (c.value === null) expect(got).toBeNull();
    else expect(Math.abs((got as number) - c.value)).toBeLessThan(1e-9);
  });

  it("falls as WACC rises and rises with terminal growth", () => {
    const at = (w: number, g: number) =>
      valuePerShare(100, 0.06, w, g, 0, 10) as number;
    expect(at(0.07, 0.025)).toBeGreaterThan(at(0.08, 0.025));
    expect(at(0.09, 0.015)).toBeLessThan(at(0.09, 0.02));
  });
});
