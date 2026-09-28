import { afterEach, describe, expect, it, vi } from "vitest";
import { SLOW_MS, begin, current, kindOf } from "./activity";

describe("activity", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("names a request by what it fetches", () => {
    expect(kindOf("/api/v1/ticker/AAPL/insiders")).toBe("activity.insiders");
    expect(kindOf("/api/v1/ticker/AAPL/metrics?base=EUR")).toBe(
      "activity.fundamentals",
    );
    expect(kindOf("/api/v1/portfolio/positions?base=EUR")).toBe("activity.book");
    expect(kindOf("/api/v1/home/closes")).toBe("activity.prices");
    expect(kindOf("/api/v1/ticker/AAPL/bars?range=1y")).toBe("activity.prices");
    expect(kindOf("/api/v1/watchlist")).toBe("activity.other");
  });

  it("stays silent for fast requests and speaks for slow ones", () => {
    vi.useFakeTimers();
    const fast = begin("/api/v1/watchlist");
    const slow = begin("/api/v1/portfolio/positions");
    fast();
    expect(current().slow).toEqual([]);
    vi.advanceTimersByTime(SLOW_MS + 10);
    expect(current().slow).toEqual(["activity.book"]);
    expect(current()).toMatchObject({ done: 1, total: 2 });
    slow();
    expect(current().slow).toEqual([]);
  });

  it("counts progress per burst", () => {
    vi.useFakeTimers();
    const a = begin("/api/v1/portfolio/summary");
    a();
    const b = begin("/api/v1/ticker/X/insiders"); // nothing out before: new burst
    vi.advanceTimersByTime(SLOW_MS + 10);
    expect(current()).toMatchObject({ done: 0, total: 1 });
    b();
  });
});
