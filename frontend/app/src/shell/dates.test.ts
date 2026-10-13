import { describe, expect, it } from "vitest";

import { calendarDay } from "./dates";

describe("calendarDay", () => {
  it("prints day, short month and year in the reader's language", () => {
    expect(calendarDay("2026-10-12", "en")).toBe("12 Oct 2026");
    expect(calendarDay("2026-10-12", "es")).toMatch(/^12 oct\.? 2026$/);
  });

  it("keeps an instant's day and hands back what is not a date", () => {
    expect(calendarDay("2026-10-12T23:59:00Z", "en")).toBe("12 Oct 2026");
    expect(calendarDay("n/a", "en")).toBe("n/a");
    expect(calendarDay(null, "en")).toBe("");
  });
});
