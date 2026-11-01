import { describe, expect, it } from "vitest";
import { daysLabel, weekdayNames, whenLabel } from "./slots";

const t = (key: string, slots?: Record<string, string | number>) =>
  key === "chat.sched_when" ? `${slots?.days} · ${slots?.time}` : key;
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
