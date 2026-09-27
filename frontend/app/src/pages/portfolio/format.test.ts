import { describe, expect, it } from "vitest";

import { compactMoneyIn } from "./format";

// Intl's es-EUR formatting puts a non-breaking space before the symbol.
const NBSP = " ";

describe("compactMoneyIn", () => {
  it("shortens past a thousand, in both locales' currency placement", () => {
    expect(compactMoneyIn("es", "EUR")(150000)).toBe(`150k${NBSP}€`);
    expect(compactMoneyIn("en", "EUR")(150000)).toBe("€150k");
  });

  it("keeps the half-step a nice-ticks ladder can land on", () => {
    expect(compactMoneyIn("es", "EUR")(7500)).toBe(`7,5k${NBSP}€`);
  });

  it("leaves anything under a thousand alone", () => {
    expect(compactMoneyIn("es", "EUR")(999)).toBe(`999${NBSP}€`);
  });

  it("scales into millions past a thousand of them", () => {
    expect(compactMoneyIn("en", "EUR")(1500000)).toBe("€1.5M");
  });

  it("keeps the sign ahead of the digits", () => {
    expect(compactMoneyIn("en", "EUR")(-12500)).toBe("-€12.5k");
  });

  it("passes null and undefined through, like moneyIn does", () => {
    expect(compactMoneyIn("en", "EUR")(null)).toBeNull();
    expect(compactMoneyIn("en", "EUR")(undefined)).toBeNull();
  });
});
