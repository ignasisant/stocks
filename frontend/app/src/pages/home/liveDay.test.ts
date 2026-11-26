import { describe, expect, it } from "vitest";
import { moving, quotedTime } from "./liveDay";
import type { Mover, Movers } from "./types";

const row = (active: boolean | null): Mover =>
  ({ ticker: "AAPL", pct: 0.01, active }) as Mover;
const day = (rows: Mover[]): Movers => ({
  window: "day",
  base: "EUR",
  gainers: rows,
  losers: [],
  basket: null,
  amount: null,
  positions: rows.length,
  unpriced: 0,
  as_of: null,
});

describe("moving", () => {
  it("polls only while some row is a move under way", () => {
    expect(moving(day([row(false), row(true)]))).toBe(true);
    expect(moving(day([row(false), row(null)]))).toBe(false);
    expect(moving(null)).toBe(false);
  });
});

describe("quotedTime", () => {
  it("reads the stamp on the reader's clock, nothing when unset", () => {
    expect(quotedTime("2026-11-26T14:05:00+00:00", "en")).toMatch(/\d{1,2}:05/);
    expect(quotedTime(null, "es")).toBeNull();
    expect(quotedTime("not a date", "es")).toBeNull();
  });

  it("dates a stamp from another day", () => {
    const now = new Date(2026, 10, 26, 10, 0);
    const today = new Date(2026, 10, 26, 9, 30).toISOString();
    const yesterday = new Date(2026, 10, 25, 21, 50).toISOString();
    expect(quotedTime(today, "en", now)).not.toMatch(/Nov/);
    expect(quotedTime(yesterday, "en", now)).toMatch(/Nov/);
  });
});
