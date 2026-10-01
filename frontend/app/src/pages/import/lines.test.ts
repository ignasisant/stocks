import { describe, expect, it } from "vitest";

import type { Row, VenueOption } from "./api";
import { ranked, tradedAs, verdict } from "./lines";

function row(
  date: string,
  action: string,
  price: number,
  extra: Partial<Row> = {},
): Row {
  return {
    date,
    ticker: "MEQA",
    action,
    quantity: 1,
    price,
    currency: "EUR",
    fee: 0,
    note: "revolut",
    issues: [],
    duplicate: false,
    ...extra,
  };
}

function option(symbol: string, agrees: boolean | null): VenueOption {
  return { symbol, name: "Merlin Properties", exchange: "", close: null, agrees };
}

describe("tradedAs", () => {
  it("sends the code's priced trades, newest first", () => {
    const traded = tradedAs(
      [
        row("2024-12-20", "buy", 11),
        row("2025-01-02T10:00:00", "sell", 12.2),
        row("2025-01-03", "dividend", 0.3),
        row("2025-01-04", "buy", 0),
        row("2025-01-05", "buy", 50, { ticker: "SIE" }),
      ],
      "MEQA",
    );
    expect(traded).toEqual({
      currency: "EUR",
      fills: [
        { date: "2025-01-02", price: 12.2 },
        { date: "2024-12-20", price: 11 },
      ],
    });
  });

  it("keeps to the currency of the latest trade", () => {
    const traded = tradedAs(
      [row("2025-01-02", "buy", 12), row("2025-02-01", "buy", 13, { currency: "USD" })],
      "MEQA",
    );
    expect(traded?.currency).toBe("USD");
    expect(traded?.fills).toEqual([{ date: "2025-02-01", price: 13 }]);
  });

  it("has nothing to check a line against without a priced trade", () => {
    expect(tradedAs([row("2025-01-03", "dividend", 0.3)], "MEQA")).toBeNull();
  });
});

describe("ranked", () => {
  it("puts the lines that closed near the fills first, else keeps the order", () => {
    const options = [
      option("MEQA.F", false),
      option("MRL.BE", null),
      option("MRL.MC", true),
      option("MEQA.SG", false),
    ];
    expect(ranked(options).map((o) => o.symbol)).toEqual([
      "MRL.MC",
      "MRL.BE",
      "MEQA.F",
      "MEQA.SG",
    ]);
    expect(options.map(verdict)).toEqual(["differs", "unknown", "agrees", "differs"]);
  });
});
