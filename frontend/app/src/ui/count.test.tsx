/**
 * A refreshed figure counts to its new value: the one number in the caller's
 * string is read, reprinted the same way every frame, and a string that does
 * not hold one comparable number is left to swap.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Count, countable, printFigure, readFigure } from "./Count";

describe("reading the figure", () => {
  it("reads Spanish money, signs and percentages", () => {
    expect(readFigure("138.857 €", "es")).toMatchObject({
      value: 138857,
      digits: 0,
      head: "",
      tail: " €",
      grouped: true,
    });
    expect(readFigure("-5.176 €", "es")?.value).toBe(-5176);
    expect(readFigure("+16,7 %", "es")).toMatchObject({
      value: 16.7,
      digits: 1,
      sign: "+",
    });
    expect(readFigure("−0,40%", "es")?.value).toBe(-0.4);
  });

  it("reads English, with the sign ahead of the currency", () => {
    expect(readFigure("-$1,234.56", "en")).toMatchObject({
      value: -1234.56,
      head: "$",
      signAt: "lead",
    });
  });

  it("gives up on no number or two", () => {
    expect(readFigure("—", "es")).toBeNull();
    expect(readFigure("12 de 30", "es")).toBeNull();
  });
});

describe("counting between two figures", () => {
  it("needs the same unit and decimals", () => {
    const es = (t: string) => readFigure(t, "es");
    expect(countable(es("138.857 €"), es("138.912 €"))).toBe(true);
    expect(countable(es("138.857 €"), es("138.857 €"))).toBe(false);
    expect(countable(es("16,7 %"), es("16,72 %"))).toBe(false);
    expect(countable(es("100 €"), es("100 $"))).toBe(false);
  });

  it("prints each frame as the caller would", () => {
    const from = readFigure("+9.331 €", "es")!;
    const to = readFigure("-1.204 €", "es")!;
    expect(printFigure(4200.4, from, to, "es")).toBe("+4.200 €");
    expect(printFigure(-0.3, from, to, "es")).toBe("+0 €");
    expect(printFigure(-850, from, to, "es")).toBe("-850 €");
    const usd = readFigure("$1,234.56", "en")!;
    expect(printFigure(-12.5, usd, readFigure("-$20.00", "en")!, "en")).toBe("-$12.50");
  });

  it("keeps thousands bare when the caller does", () => {
    const from = readFigure("9411", "es")!;
    expect(printFigure(9500, from, readFigure("9600", "es")!, "es")).toBe("9500");
  });
});

describe("the first render", () => {
  it("draws the figure as given", () => {
    expect(renderToStaticMarkup(<Count text="138.857 €" tint />)).toBe(
      '<span class="ag-count">138.857 €</span>',
    );
  });
});
