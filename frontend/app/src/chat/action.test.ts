/**
 * The trade form's Review: live only once the form is a trade the server
 * would plan (`tools.trade_args` on the other side).
 */

import { describe, expect, it } from "vitest";

import { tradeReady } from "./ActionCard";
import { typedUnits } from "./a2ui";

const whole = { trade: "sell", quantity: "50", price: "26,51", date: "2026-10-09" };

describe("a trade form", () => {
  it("is ready with a side, shares and a price above zero, and a day", () => {
    expect(tradeReady(whole)).toBe(true);
    expect(tradeReady({ ...whole, price: "26.51" })).toBe(true);
  });

  it("waits for every field", () => {
    expect(tradeReady(null)).toBe(false);
    expect(tradeReady({ ...whole, trade: "" })).toBe(false);
    expect(tradeReady({ ...whole, quantity: "" })).toBe(false);
    expect(tradeReady({ ...whole, quantity: "0" })).toBe(false);
    expect(tradeReady({ ...whole, price: "ewq" })).toBe(false);
    expect(tradeReady({ ...whole, date: "" })).toBe(false);
  });

  it("takes a fund's sum in place of its units, at the price", () => {
    const bySum = { ...whole, quantity: "", amount: "1000" };
    expect(tradeReady(bySum)).toBe(true);
    expect(tradeReady({ ...bySum, price: "" })).toBe(false);
    expect(tradeReady({ ...bySum, amount: "0" })).toBe(false);
    expect(typedUnits("", "1000", "422,62")).toBeCloseTo(1000 / 422.62, 9);
    expect(typedUnits("2", "1000", "422,62")).toBe(2);
    expect(typedUnits("", "1000", "")).toBeNaN();
  });
});
