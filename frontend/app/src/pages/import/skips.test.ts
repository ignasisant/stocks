import { describe, expect, it } from "vitest";

import type { SkippedRow } from "./api";
import { OTHER, groupSkips, located, splitReason } from "./skips";

const CASH = "cash movement — not position-affecting";
const SPLIT = "stock split — ratio derived at validation, or add manually";

function cash(date: string, type = "CASH TOP-UP"): SkippedRow {
  return {
    row: 2,
    type,
    reason: CASH,
    reason_key: "import.skip_cash",
    manual: false,
    date,
    ticker: "",
    quantity: 0,
    amount: 100,
    currency: "EUR",
  };
}

describe("groupSkips", () => {
  it("gathers a statement's repeats under one reason, a step by hand first", () => {
    const rows = [
      cash("2025-12-01"),
      cash("2025-08-04"),
      cash("2026-01-10", "CASH WITHDRAWAL"),
      {
        row: 95,
        type: "STOCK SPLIT",
        reason: SPLIT,
        reason_key: "import.skip_split",
        manual: true,
        date: "2026-05-25",
        ticker: "MEQA",
        quantity: 0,
        amount: 129.4,
        currency: "EUR",
      },
    ];
    const groups = groupSkips(rows);
    expect(groups.map((g) => g.stem)).toEqual([
      "import.skip_split",
      "import.skip_cash",
    ]);
    const money = groups[1]!;
    expect(money.rows).toHaveLength(3);
    expect(money.types).toEqual([
      ["CASH TOP-UP", 2],
      ["CASH WITHDRAWAL", 1],
    ]);
    expect(money.span).toEqual(["2025-08-04", "2026-01-10"]);
    // Oldest first, whatever order the statement's sections listed them in.
    expect(money.rows.map((row) => row.date)).toEqual([
      "2025-08-04",
      "2025-12-01",
      "2026-01-10",
    ]);
  });

  it("puts unnamed one-off reasons in one group, not a heading apiece", () => {
    const rows: SkippedRow[] = [
      { row: 3, type: "buy", reason: "unreadable date '31/02'" },
      { row: 4, type: "buy", reason: "unreadable date '30/02'" },
      { row: 5, type: "x", reason: "no symbol" },
      { row: 6, type: "x", reason: "no symbol" },
    ];
    const groups = groupSkips(rows);
    expect(groups.map((g) => [g.stem, g.reason, g.rows.length])).toEqual([
      [null, "no symbol", 2],
      [OTHER, "", 2],
    ]);
  });

  it("keeps a lone unnamed reason as its own heading", () => {
    const groups = groupSkips([
      { row: 0, type: "file", reason: "no parser recognised this file" },
    ]);
    expect(groups.map((g) => [g.stem, g.reason])).toEqual([
      [null, "no parser recognised this file"],
    ]);
    expect(groups[0]!.span).toBeNull();
  });
});

describe("a skip's fields", () => {
  it("tells a row from a remark about the file", () => {
    expect(located({ row: 0, type: "file", reason: "x" })).toBe(false);
    expect(located({ row: 2, type: "fee", reason: "x", amount: 1.5 })).toBe(true);
    expect(located({ row: 2, type: "fee", reason: "x", isin: "ES0171996087" })).toBe(
      true,
    );
  });

  it("splits an unnamed reason where the parsers do", () => {
    expect(splitReason("accrued dividend — not cash yet")).toEqual([
      "Accrued dividend",
      "not cash yet",
    ]);
    expect(splitReason("no symbol")).toEqual(["No symbol", ""]);
  });
});
