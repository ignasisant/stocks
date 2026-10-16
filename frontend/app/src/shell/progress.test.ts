import { describe, expect, it } from "vitest";
import { type Job, barShare } from "./progress";
import { hintFor } from "./Loading";

const job = (over: Partial<Job>): Job => ({
  step: "prices.tail",
  done: 0,
  total: 0,
  elapsed_s: 0,
  step_elapsed_s: 0,
  expected_s: null,
  ...over,
});

describe("barShare", () => {
  it("follows the server's count of names when it has one", () => {
    expect(barShare(job({ done: 40, total: 80 }), 11, 12)).toEqual({
      share: 0.5,
      measured: true,
    });
  });

  it("guesses from the last run's time, and never reads as finished", () => {
    expect(barShare(job({ step_elapsed_s: 10, expected_s: 20 }), 0, 1)).toEqual({
      share: 0.5,
      measured: false,
    });
    expect(barShare(job({ step_elapsed_s: 60, expected_s: 20 }), 0, 1).share).toBe(
      0.95,
    );
  });

  it("falls back to the page's own requests, then to a sweep", () => {
    expect(barShare(null, 3, 4)).toEqual({ share: 0.75, measured: true });
    expect(barShare(null, 0, 1)).toEqual({ share: null, measured: false });
  });
});

describe("hintFor", () => {
  it("says nothing for a short wait and more as it grows", () => {
    expect(hintFor(3, null)).toBeNull();
    expect(hintFor(8, null)).toBe("activity.hint_slow");
    expect(hintFor(30, null)).toBe("activity.hint_long");
    expect(hintFor(75, null)).toBe("activity.hint_very_long");
  });

  it("prefers the server's own estimate when it knows one", () => {
    expect(hintFor(30, 42)).toBe("activity.expected");
    expect(hintFor(30, 1)).toBe("activity.hint_long");
  });
});
