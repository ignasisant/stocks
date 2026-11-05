import { describe, expect, it } from "vitest";

import { VISIT_DAYS, asked, followUp, markAsked, recordVisit } from "./rate";
import { claimNudge } from "./tourPark";

function memory(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
}

const broken = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
} as unknown as Storage;

const day = (d: number) => new Date(2026, 10, d, 12);

describe("the rating prompt's visit count", () => {
  it("counts distinct days, not loads, and stops at VISIT_DAYS", () => {
    const store = memory();
    expect(recordVisit(day(1), store)).toBe(1);
    expect(recordVisit(day(1), store)).toBe(1);
    for (let d = 2; d < VISIT_DAYS; d++) recordVisit(day(d), store);
    expect(recordVisit(day(VISIT_DAYS - 1), store)).toBe(VISIT_DAYS - 1);
    expect(recordVisit(day(20), store)).toBe(VISIT_DAYS);
    expect(recordVisit(day(21), store)).toBe(VISIT_DAYS);
  });

  it("counts nothing when storage throws, so it never asks", () => {
    expect(recordVisit(day(1), broken)).toBe(0);
  });
});

describe("whether this browser already asked", () => {
  it("remembers the ask", () => {
    const store = memory();
    expect(asked(store)).toBe(false);
    markAsked(store);
    expect(asked(store)).toBe(true);
  });

  it("reads storage that throws as asked: a prompt that cannot remember would ask on every load", () => {
    expect(asked(broken)).toBe(true);
    expect(() => markAsked(broken)).not.toThrow();
  });
});

describe("the comment box's question", () => {
  it("asks what to fix after a low score and what works after a high one", () => {
    expect([1, 2, 3, 4, 5].map(followUp)).toEqual([
      "rate_low",
      "rate_low",
      "rate_low",
      "rate_high",
      "rate_high",
    ]);
  });
});

describe("one nudge per load", () => {
  it("hands the slot out once", () => {
    expect(claimNudge()).toBe(true);
    expect(claimNudge()).toBe(false);
  });
});
