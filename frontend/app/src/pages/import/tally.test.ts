import { describe, expect, it } from "vitest";
import type { Move, Row } from "./api";
import {
  barSegments,
  byImpact,
  culprits,
  heldSet,
  kindsOf,
  newPositions,
} from "./tally";

const row = (action: string, ticker: string, over: Partial<Row> = {}): Row => ({
  date: "2024-01-02",
  ticker,
  action,
  quantity: 1,
  price: 10,
  currency: "EUR",
  fee: 0,
  note: "",
  issues: [],
  duplicate: false,
  ...over,
});

const labels = {
  importable: "a",
  warned: "b",
  rejected: "c",
  duplicates: "d",
  skipped: "e",
};

describe("barSegments", () => {
  it("carves warned rows out of the importable ones and drops empty tiers", () => {
    const parts = barSegments(
      { importable: 10, warned: 2, rejected: 0, duplicates: 0, skipped: 2 },
      labels,
    );
    expect(parts.map((part) => [part.id, part.n])).toEqual([
      ["im-importable", 8],
      ["im-warned", 2],
      ["im-skipped", 2],
    ]);
    expect(parts.reduce((sum, part) => sum + part.share, 0)).toBeCloseTo(1);
  });

  it("is empty when nothing was read", () => {
    expect(
      barSegments(
        { importable: 0, warned: 0, rejected: 0, duplicates: 0, skipped: 0 },
        labels,
      ),
    ).toEqual([]);
  });
});

describe("newPositions", () => {
  it("lists each bought ticker the book lacks once, ignoring case", () => {
    const rows = [
      row("buy", "nvda"),
      row("buy", "NVDA"),
      row("buy", "AAPL"),
      row("sell", "TSLA"),
    ];
    expect(newPositions(rows, heldSet(["aapl"]))).toEqual(["NVDA"]);
  });
});

describe("kindsOf", () => {
  it("counts by kind and leaves out what the commit refused", () => {
    const sent = [
      row("buy", "A"),
      row("buy", "B"),
      row("sell", "A"),
      row("dividend", "A"),
    ];
    expect(kindsOf(sent, [row("buy", "B")])).toEqual({
      buys: 1,
      sells: 1,
      dividends: 1,
      other: 0,
    });
  });
});

describe("culprits", () => {
  it("names the columns of the issues of one severity", () => {
    const issue = (severity: string, field: string) => ({
      severity,
      field,
      key: "k",
      params: {},
      message: "m",
    });
    const found = culprits(
      [issue("error", "quantity"), issue("warning", "price"), issue("error", "")],
      "error",
    );
    expect([...found]).toEqual(["quantity"]);
  });
});

describe("byImpact", () => {
  it("puts the biggest phantom gain first and unknown ones last", () => {
    const move = (gain: number | null) => ({ phantom_gain: gain }) as Move;
    expect(
      byImpact([move(5), move(null), move(-40), move(12)]).map((m) => m.phantom_gain),
    ).toEqual([-40, 12, 5, null]);
  });
});
