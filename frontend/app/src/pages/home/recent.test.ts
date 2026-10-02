import { describe, expect, it } from "vitest";

import { owedTotal, recentRows } from "./recent";
import type { Transaction, UnbookedDividend } from "./types";

const tx = (date: string, ticker: string, action = "buy"): Transaction => ({
  id: null,
  date,
  ticker,
  action,
  quantity: 1,
  price: 1,
  currency: "EUR",
  fee: 0,
  note: "",
});

const owed = (ex_date: string, ticker: string): UnbookedDividend => ({
  ticker,
  ex_date,
  per_share: 0.5,
  shares: 10,
  currency: "USD",
  gross: 5,
  amount: 4.6,
});

describe("recentRows", () => {
  it("folds the dividends a statement never reached into one row", () => {
    const rows = recentRows(
      [tx("2026-07-31", "RMS.PA", "dividend"), tx("2026-07-24", "TTD")],
      [owed("2026-07-28", "PEP"), owed("2026-09-12", "KO")],
      5,
    );
    expect(rows.map((row) => [row.kind, row.date])).toEqual([
      ["owed", "2026-09-12"],
      ["ledger", "2026-07-31"],
      ["ledger", "2026-07-24"],
    ]);
    const group = rows[0];
    if (group?.kind !== "owed") throw new Error("no grouped row");
    expect(group.since).toBe("2026-07-28");
    expect(group.dividends.map((p) => p.ticker)).toEqual(["KO", "PEP"]);
  });

  it("leaves a gap older than the strip's span out of it", () => {
    const ledger = ["09-01", "08-24", "08-17", "08-10", "08-03"].map((day) =>
      tx(`2026-${day}`, "TTD"),
    );
    const old = owed("2025-07-01", "NA9");
    expect(recentRows(ledger, [old], 5).map((row) => row.kind)).toEqual(
      Array(5).fill("ledger"),
    );
    const rows = recentRows(ledger, [old, owed("2026-09-12", "KO")], 5);
    expect(rows.map((row) => [row.kind, row.date])).toEqual([
      ["estimated", "2026-09-12"],
      ["ledger", "2026-09-01"],
      ["ledger", "2026-08-24"],
      ["ledger", "2026-08-17"],
      ["ledger", "2026-08-10"],
    ]);
  });

  it("keeps the count and puts the receipt first on a shared day", () => {
    const rows = recentRows(
      [tx("2026-07-24", "TTD"), tx("2026-07-17", "FSLR")],
      [owed("2026-07-24", "KO")],
      2,
    );
    expect(rows.map((row) => row.kind)).toEqual(["ledger", "estimated"]);
  });

  it("is the ledger alone while the estimates have not come back", () => {
    const ledger = [tx("2026-07-24", "TTD")];
    expect(recentRows(ledger, [], 5)).toEqual([
      { kind: "ledger", date: "2026-07-24", tx: ledger[0] },
    ]);
  });
});

describe("owedTotal", () => {
  it("sums the group, or gives no total when a payment has no rate", () => {
    expect(owedTotal([owed("2026-09-12", "KO"), owed("2026-08-28", "PEP")])).toBe(9.2);
    expect(
      owedTotal([
        owed("2026-09-12", "KO"),
        { ...owed("2026-08-28", "PEP"), amount: null },
      ]),
    ).toBeNull();
  });
});
