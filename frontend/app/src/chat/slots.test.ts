import { describe, expect, it } from "vitest";
import { closeTime, daysLabel, weekdayNames, whenLabel } from "./slots";

const t = (key: string, slots?: Record<string, string | number>) =>
  key === "chat.sched_when"
    ? `${slots?.days} · ${slots?.time}`
    : key === "chat.sched_close_at"
      ? `close ~${slots?.time}`
      : key;
const names = weekdayNames("en");

describe("weekdayNames", () => {
  it("starts the week on Monday", () => {
    expect(names).toHaveLength(7);
    expect(names[0]).toBe("Mon");
    expect(names[6]).toBe("Sun");
  });
});

describe("daysLabel", () => {
  it("names the common sets in words", () => {
    expect(daysLabel([0, 1, 2, 3, 4], names, t)).toBe("chat.sched_weekdays");
    expect(daysLabel([6, 5, 4, 3, 2, 1, 0], names, t)).toBe("chat.sched_every_day");
    expect(daysLabel([], names, t)).toBe("chat.sched_no_days");
  });

  it("lists any other set in week order, once each", () => {
    expect(daysLabel([6, 0, 6], names, t)).toBe("Mon, Sun");
  });
});

describe("whenLabel", () => {
  it("says the days and the time, or that it is off", () => {
    expect(
      whenLabel({ on: true, time: "22:30", days: [0, 1, 2, 3, 4] }, names, t),
    ).toBe("chat.sched_weekdays · 22:30");
    expect(whenLabel({ on: false, time: "22:30", days: [6] }, names, t)).toBe(
      "chat.sched_off",
    );
  });
});

describe("closeTime", () => {
  it("is 16:30 New York on the reader's clock", () => {
    const june = new Date("2026-06-10T12:00:00Z");
    expect(closeTime("America/New_York", june)).toBe("16:30");
    expect(closeTime("Europe/Madrid", june)).toBe("22:30");
    expect(closeTime("Asia/Tokyo", june)).toBe("05:30");
  });

  it("follows the weeks the two sides change clocks on different Sundays", () => {
    // 2026-03-10: New York is on summer time, Madrid not yet.
    expect(closeTime("Europe/Madrid", new Date("2026-03-10T12:00:00Z"))).toBe("21:30");
    expect(closeTime("Europe/Madrid", new Date("2026-01-10T12:00:00Z"))).toBe("22:30");
  });

  it("falls back to the browser's clock on a zone Intl does not know", () => {
    expect(closeTime("Not/AZone", new Date("2026-06-10T12:00:00Z"))).toMatch(
      /^\d\d:\d\d$/,
    );
  });
});

describe("whenLabel after the close", () => {
  it("says the close instead of the kept time", () => {
    const slot = { on: true, time: "08:30", days: [0, 1, 2, 3, 4], close: true };
    expect(whenLabel(slot, names, t, "Europe/Madrid")).toMatch(
      /^chat\.sched_weekdays · close ~\d\d:30$/,
    );
  });
});
