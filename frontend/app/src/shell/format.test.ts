import { describe, expect, it } from "vitest";
import { DASH, compact, decimal, money, moneyIn, percent, shares } from "./format";

describe("shell/format", () => {
  it("hands back null, never a zero, for a missing figure", () => {
    expect(money(null, { currency: "EUR" })).toBeNull();
    expect(percent(undefined)).toBeNull();
    expect(decimal(Number.NaN)).toBeNull();
    expect(shares(null)).toBeNull();
    expect(compact(null)).toBeNull();
    expect(DASH).toBe("—");
  });

  it("prints money in the reader's language, grouped", () => {
    expect(money(1234.5, { currency: "EUR", lang: "en", digits: 2 })).toBe("€1,234.50");
    expect(money(1234.5, { lang: "es", digits: 2 })).toBe("1.234,50");
  });

  it('tells `signed: true` from `signed: "always"` on an exact zero', () => {
    expect(decimal(0, { lang: "en", signed: true })).toBe("0.00");
    expect(decimal(0, { lang: "en", signed: "always" })).toBe("+0.00");
    expect(decimal(1.5, { lang: "en", signed: true })).toBe("+1.50");
  });

  it("falls back to the code for a currency Intl does not know", () => {
    expect(money(12, { currency: "ZZZZZZ", lang: "en" })).toBe("12 ZZZZZZ");
  });

  it("compacts past a thousand with the suffix after the last digit", () => {
    const k = moneyIn("en", "EUR");
    expect(money(12500, { currency: "EUR", lang: "en", compact: true })).toBe("€12.5k");
    expect(money(950, { currency: "EUR", lang: "en", compact: true })).toBe("€950");
    expect(k(950)).toBe("€950");
  });

  it("keeps the Intl percent apart from the tables' tight one", () => {
    expect(percent(0.1234, { lang: "es" })).toBe("12,3\u00a0%");
    expect(percent(0.1234, { lang: "es", tight: true })).toBe("12,3%");
    expect(percent(5.2, { lang: "en", points: true, signed: "always" })).toBe("+5.2%");
  });

  it("scales a compact figure with the sign ahead of the mark", () => {
    expect(compact(-1.2e6, { prefix: "$", digits: 1 })).toBe("-$1.2M");
    expect(compact(950)).toBe("950");
  });
});
