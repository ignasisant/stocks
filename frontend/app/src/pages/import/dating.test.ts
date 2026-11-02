import { describe, expect, it } from "vitest";

import type { Holding } from "./api";
import {
  MAX_PRICE,
  MIN_DAY,
  boughtAs,
  currencyProblem,
  dayProblem,
  priceOf,
  priceProblem,
  today,
  undated,
} from "./dating";

const NOW = "2026-11-02";

const AAPL: Holding = {
  row: 2,
  ticker: "AAPL",
  isin: "US0378331005",
  quantity: 10,
  currency: "USD",
  cost: 150.123456,
};

describe("priceOf", () => {
  it("reads either decimal mark, and the earlier one as thousands", () => {
    expect(priceOf("150,25")).toBe(150.25);
    expect(priceOf(" 150.25 ")).toBe(150.25);
    expect(priceOf("1.805,50")).toBe(1805.5);
    expect(priceOf("1,805.50")).toBe(1805.5);
  });

  it("is null for nothing, zero or words", () => {
    expect(priceOf("")).toBeNull();
    expect(priceOf("0")).toBeNull();
    expect(priceOf("abc")).toBeNull();
    expect(priceOf("-3")).toBeNull();
  });

  it("is null for anything that is not one plain number", () => {
    for (const text of [
      "1e5",
      "12abc",
      "1,2,3",
      "1.2.3",
      "Infinity",
      "NaN",
      "0x10",
      "+5",
      "€150",
      "150 €",
      ".",
      ",",
    ]) {
      expect(priceOf(text), text).toBeNull();
    }
    expect(priceOf("0,0001")).toBe(0.0001);
  });

  it("is null past the cap, a pasted total rather than a share price", () => {
    expect(priceOf(String(MAX_PRICE))).toBe(MAX_PRICE);
    expect(priceOf("1000000001")).toBeNull();
    expect(priceOf("9".repeat(400))).toBeNull();
  });
});

describe("the field rules", () => {
  it("says nothing about an empty field: not wrong, only not done", () => {
    expect(priceProblem("")).toBeNull();
    expect(priceProblem("  ")).toBeNull();
    expect(dayProblem("", NOW)).toBeNull();
    expect(currencyProblem("")).toBeNull();
  });

  it("names a price that is not a number above zero", () => {
    expect(priceProblem("150,25")).toBeNull();
    expect(priceProblem("abc")).toBe("import.hold_bad_price");
    expect(priceProblem("0")).toBe("import.hold_bad_price");
    expect(priceProblem("-1")).toBe("import.hold_bad_price");
  });

  it("refuses a day after today, and takes today itself", () => {
    expect(dayProblem(NOW, NOW)).toBeNull();
    expect(dayProblem("2026-11-03", NOW)).toBe("import.hold_future");
    expect(dayProblem("2099-01-01", NOW)).toBe("import.hold_future");
  });

  it("refuses a day before the ledger's floor", () => {
    expect(dayProblem(MIN_DAY, NOW)).toBeNull();
    expect(dayProblem("1989-12-31", NOW)).toBe("import.hold_old");
    expect(dayProblem("0203-05-01", NOW)).toBe("import.hold_old");
  });

  it("refuses a day the calendar does not have, or not written as one", () => {
    for (const text of [
      "2024-02-30",
      "2023-02-29",
      "2024-13-01",
      "2024-00-10",
      "2024-04-31",
      "01/03/2024",
      "2024-3-1",
      "yesterday",
    ]) {
      expect(dayProblem(text, NOW), text).toBe("import.hold_bad_date");
    }
    expect(dayProblem("2024-02-29", NOW)).toBeNull();
  });

  it("names a currency that is not three letters", () => {
    expect(currencyProblem("usd")).toBeNull();
    expect(currencyProblem("EU")).toBe("import.hold_bad_currency");
    expect(currencyProblem("EU1")).toBe("import.hold_bad_currency");
    expect(currencyProblem("€")).toBe("import.hold_bad_currency");
  });

  it("reads today off the reader's own calendar, not UTC's", () => {
    // 00:30 on 3 November where the reader is; UTC may still say the 2nd.
    expect(today(new Date(2026, 10, 3, 0, 30))).toBe("2026-11-03");
    expect(today(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });
});

describe("boughtAs", () => {
  it("opens with the report's cost and currency, and no day", () => {
    expect(undated(AAPL)).toEqual({ price: "150.1235", date: "", currency: "USD" });
    expect(undated({ ...AAPL, cost: null }).price).toBe("");
  });

  it("is a buy of the whole line once dated, under the line that was priced", () => {
    const dating = { ...undated(AAPL), date: "2024-03-01", symbol: "AAPL" };
    expect(boughtAs(AAPL, dating)).toMatchObject({
      date: "2024-03-01",
      ticker: "AAPL",
      action: "buy",
      quantity: 10,
      price: 150.1235,
      currency: "USD",
      fee: 0,
    });
    const isin = { ...AAPL, ticker: "US0378331005" };
    expect(boughtAs(isin, { ...dating, symbol: undefined })?.ticker).toBe(
      "US0378331005",
    );
  });

  it("leaves out a line with no day, no price or no currency", () => {
    const ready = { ...undated(AAPL), date: "2024-03-01" };
    expect(boughtAs(AAPL, undefined)).toBeNull();
    expect(boughtAs(AAPL, { ...ready, date: "" })).toBeNull();
    expect(boughtAs(AAPL, { ...ready, price: "" })).toBeNull();
    expect(boughtAs(AAPL, { ...ready, currency: "" })).toBeNull();
    expect(boughtAs(AAPL, { ...ready, currency: "eur" })?.currency).toBe("EUR");
  });

  it("leaves out a line whose day or price breaks a rule", () => {
    const ready = { ...undated(AAPL), date: "2024-03-01" };
    expect(boughtAs(AAPL, ready, NOW)).not.toBeNull();
    expect(boughtAs(AAPL, { ...ready, date: "2026-11-03" }, NOW)).toBeNull();
    expect(boughtAs(AAPL, { ...ready, date: NOW }, NOW)?.date).toBe(NOW);
    expect(boughtAs(AAPL, { ...ready, date: "2024-02-30" }, NOW)).toBeNull();
    expect(boughtAs(AAPL, { ...ready, date: "1989-12-31" }, NOW)).toBeNull();
    expect(boughtAs(AAPL, { ...ready, price: "abc" }, NOW)).toBeNull();
    expect(boughtAs(AAPL, { ...ready, price: "0" }, NOW)).toBeNull();
    expect(boughtAs(AAPL, { ...ready, currency: "EU" }, NOW)).toBeNull();
  });
});
