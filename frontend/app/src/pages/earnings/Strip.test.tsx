/**
 * The next-seven-days strip, the month in the address, the legend's counts and
 * the buy-back band: the pure parts, and the markup they draw.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  kindCounts,
  monthKey,
  monthsFrom,
  parseMonth,
  weighed,
  weightOf,
  within,
} from "./data";
import type { CalendarEvent, EarningsCalendar, RepurchaseWindow } from "./data";
import MonthGrid, { dotKinds } from "./MonthGrid";
import { Strip } from "./Strip";

const print = (ticker: string, date: string, days_until: number): CalendarEvent =>
  ({ ticker, date, days_until }) as CalendarEvent;

describe("the month in the address", () => {
  it("reads a valid month and nothing else", () => {
    expect(parseMonth("2026-12")).toEqual([2026, 12]);
    expect(parseMonth("2026-13")).toBeNull();
    expect(parseMonth("2026-1")).toBeNull();
    expect(parseMonth(null)).toBeNull();
  });

  it("counts months from today's, behind and ahead, across a year", () => {
    expect(monthsFrom("2026-11-16", 2026, 11)).toBe(0);
    expect(monthsFrom("2026-11-16", 2027, 2)).toBe(3);
    expect(monthsFrom("2026-11-16", 2026, 8)).toBe(-3);
    expect(monthKey(2026, 3)).toBe("2026-03");
  });
});

describe("the weights", () => {
  const weights = { AAPL: 0.12, MSFT: 0.08 };

  it("is null for a name with no weight, never zero", () => {
    expect(weightOf(weights, "AAPL")).toBe(0.12);
    expect(weightOf(weights, "NVDA")).toBeNull();
    expect(weightOf(undefined, "AAPL")).toBeNull();
  });

  it("sums only what is known, and says nothing when nothing is", () => {
    const events = [print("AAPL", "2026-11-17", 1), print("NVDA", "2026-11-18", 2)];
    expect(weighed(events, weights)).toBeCloseTo(0.12);
    expect(weighed([print("NVDA", "2026-11-18", 2)], weights)).toBeNull();
  });

  it("looks seven days ahead, today included, and not behind", () => {
    expect(within(0)).toBe(true);
    expect(within(7)).toBe(true);
    expect(within(8)).toBe(false);
    expect(within(-1)).toBe(false);
    expect(within(null)).toBe(false);
  });
});

describe("the strip", () => {
  const draw = (events: CalendarEvent[], weights?: Record<string, number>) =>
    renderToStaticMarkup(
      <Strip
        events={events}
        dividends={[]}
        deadlines={[]}
        windows={[]}
        banks={[]}
        weights={weights}
        onPick={() => {}}
      />,
    );

  it("lists what lands inside the week with the share of the book it carries", () => {
    const html = draw(
      [print("AAPL", "2026-11-17", 1), print("MSFT", "2026-11-18", 2)],
      { AAPL: 0.12, MSFT: 0.08 },
    );
    expect(html).toContain("earnings.strip_prints");
    expect(html).toContain("earnings.strip_weight");
    expect(html.match(/earnings\.strip_weighs/g)).toHaveLength(2);
    expect(html).toContain("AAPL");
  });

  it("leaves a print beyond the week out, and says so when nothing is left", () => {
    const html = draw([print("AAPL", "2026-12-20", 34)]);
    expect(html).toContain("earnings.strip_none");
    expect(html).not.toContain("earn-strip-list");
  });

  it("still lists the names when no weight is known", () => {
    const html = draw([print("AAPL", "2026-11-17", 1)]);
    expect(html).toContain("earn-strip-list");
    expect(html).not.toContain("earnings.strip_weigh");
  });
});

describe("the legend's counts", () => {
  const data = {
    upcoming: [print("AAPL", "2026-11-17", 1), print("NVDA", "2026-11-18", 2)],
    results: [{ ticker: "AAPL", date: "2026-10-30" }],
    dividends: [],
    tax_deadlines: [{ key: "a" }],
    repurchase_windows: [{ ticker: "AAPL" }],
    central_banks: [{ bank: "fed" }],
    groups: {},
  } as unknown as EarningsCalendar;

  it("counts every date a pill holds", () => {
    expect(kindCounts(data, null)).toMatchObject({
      earnings: 3,
      tax: 2,
      banks: 1,
      trades: 0,
      dividends: 0,
      markets: 0,
    });
  });

  it("cuts the name-bound kinds by the group, and leaves the reader's own", () => {
    expect(kindCounts(data, new Set(["AAPL"]))).toMatchObject({ earnings: 2, tax: 2 });
  });
});

describe("the grid", () => {
  const window: RepurchaseWindow = {
    ticker: "AAPL",
    sell_date: "2026-10-12",
    date: "2026-10-14",
    days_until: 0,
    loss: 100,
    currency: "USD",
    window: "2m",
  };

  const grid = (windows: RepurchaseWindow[]) =>
    renderToStaticMarkup(
      <MonthGrid
        year={2026}
        month={10}
        now="2026-10-02"
        events={[]}
        results={[]}
        deadlines={[]}
        windows={windows}
        banks={[]}
        dividends={[]}
        onPick={() => {}}
      />,
    );

  it("draws the buy-back window as one band over the days it runs", () => {
    const html = grid([window]);
    // Sold on the 12th, free on the 14th: the 12th and 13th carry the band.
    expect(html.match(/class="earn-band/g)).toHaveLength(2);
    expect(html).toContain('class="earn-band start"');
    expect(html).toContain('class="earn-band end"');
  });

  it("dims the days already gone and marks nothing on a window-free month", () => {
    const html = grid([]);
    expect(html).toContain("earn-day past");
    expect(html).not.toContain("earn-band");
  });

  it("gives a day a dot per kind, once each, for the phone", () => {
    const day = {
      events: [print("AAPL", "2026-10-28", 26), print("MSFT", "2026-10-28", 26)],
      results: [],
      deadlines: [],
      windows: [],
      banks: [],
      dividends: [],
    };
    expect(dotKinds(day)).toEqual(["print"]);
  });
});
