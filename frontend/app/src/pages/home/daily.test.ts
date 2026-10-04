/**
 * The two decisions the daily card makes on its own: when to ask the server to
 * write today's briefing, and what the stamp under the badge says.
 *
 * Both are small and both fail quietly. Asking too eagerly spends the reader's
 * free allowance on a card that already stands; the stamp printing "Today" over
 * yesterday's card is how a reader mistakes a briefing written before the open
 * for this morning's.
 */

import { describe, expect, it } from "vitest";

import {
  linesOf,
  opens,
  noteKey,
  sectioned,
  sectionsOf,
  stampOf,
  tone,
  wantsWriting,
} from "./Daily";
import type { DailyCard } from "./types";

const t = (key: string, slots?: Record<string, string | number>) =>
  slots ? `${key}:${Object.values(slots).join(",")}` : key;

function card(over: Partial<DailyCard> = {}): DailyCard {
  return {
    day: "2026-09-24",
    headline: "Two names carry the week",
    bullets: [],
    focus: [],
    as_of: "2026-09-23",
    lang: "en",
    source: "llm",
    action_day: "2026-09-24",
    cutoff_hour: 9,
    fresh: true,
    generated: null,
    pending: false,
    items: [],
    upgradable: false,
    analysed: [],
    ...over,
  };
}

describe("wantsWriting", () => {
  it("leaves a card that stands alone", () => {
    expect(wantsWriting(card(), null)).toBe(false);
  });

  it("asks for a card that no longer stands, once per action day", () => {
    const stale = card({ fresh: false });
    expect(wantsWriting(stale, null)).toBe(true);
    expect(wantsWriting(stale, "2026-09-24")).toBe(false);
  });

  it("never doubles a generation that is already out", () => {
    expect(wantsWriting(card({ fresh: false, pending: true }), null)).toBe(false);
  });

  it("asks once more for a written card over a stand-in that stands", () => {
    const standIn = card({ source: "computed", upgradable: true });
    expect(wantsWriting(standIn, null)).toBe(true);
    expect(wantsWriting(standIn, "2026-09-24")).toBe(false);
  });
});

describe("linesOf / opens", () => {
  const item = {
    key: "earnings:NVDA",
    kind: "earnings",
    line: "NVDA reports",
    tickers: ["NVDA"],
  };

  it("reads the keyed items when the card has them", () => {
    expect(linesOf(card({ items: [item], bullets: ["NVDA reports"] }))).toEqual([item]);
  });

  it("falls back to the bullets of a card stored before keys", () => {
    expect(linesOf(card({ bullets: ["a", "b"] })).map((i) => i.key)).toEqual([
      "line:0",
      "line:1",
    ]);
  });

  it("offers an analysis only on a line with a trigger behind it", () => {
    expect(opens(item)).toBe(true);
    expect(linesOf(card({ bullets: ["Portfolio +0.4% today"] })).some(opens)).toBe(
      false,
    );
  });
});

describe("sectionsOf / sectioned", () => {
  const alert = {
    key: "alert_hit:AAPL",
    kind: "alert_hit",
    line: "AAPL crossed 260",
    tickers: ["AAPL"],
    section: "alerts" as const,
  };
  const watch = {
    key: "earnings:NVDA",
    kind: "earnings",
    line: "NVDA reports",
    tickers: ["NVDA"],
    section: "watch" as const,
  };
  const book = {
    index: "S&P 500",
    currency: "EUR",
    rows: [{ window: "day" as const, pct: 0.8, amount: 120, index_pct: 0.3 }],
    chart: [],
  };

  it("puts the fired alerts in their own section and the rest under watch", () => {
    const { alerts, watch: rest } = sectionsOf([watch, alert]);
    expect(alerts.map((i) => i.key)).toEqual(["alert_hit:AAPL"]);
    expect(rest.map((i) => i.key)).toEqual(["earnings:NVDA"]);
  });

  it("reads a line stored before sections as worth a look", () => {
    const { section: _, ...old } = watch;
    expect(sectionsOf([old]).watch).toEqual([old]);
  });

  it("keeps a plain list when the card has nothing besides it", () => {
    expect(sectioned(card(), 0)).toBe(false);
    expect(sectioned(card({ book: null, sections: [] }), 0)).toBe(false);
  });

  it("draws sections once there is a book, a brief section or an alert", () => {
    expect(sectioned(card({ book }), 0)).toBe(true);
    expect(sectioned(card({ book: { ...book, rows: [] } }), 0)).toBe(false);
    const asked = { title: "NVDA", asks: [1], lines: [watch], chart: null };
    expect(sectioned(card({ sections: [asked] }), 0)).toBe(true);
    expect(sectioned(card(), 1)).toBe(true);
  });
});

describe("noteKey", () => {
  const base = { pending: false, source: "llm", brief: "" as const };

  it("leaves a written card to the disclaimer", () => {
    expect(noteKey(base)).toBeNull();
    expect(noteKey({ ...base, brief: "written" })).toBeNull();
  });

  it("says the stand-in is waiting on the brief when that is what is written", () => {
    expect(noteKey({ ...base, pending: true, brief: "pending" })).toBe(
      "home.daily_brief_wait",
    );
    expect(noteKey({ ...base, pending: true })).toBe("home.daily_computed_wait");
  });

  it("never passes the default card off as the brief answered", () => {
    expect(noteKey({ ...base, source: "computed", brief: "missed" })).toBe(
      "home.daily_brief_missed",
    );
    expect(noteKey({ ...base, source: "computed" })).toBe("home.daily_computed_note");
  });
});

describe("tone", () => {
  it("colours a move and leaves a level in ink", () => {
    expect(tone("+12,1%")).toBe("up");
    expect(tone("-1.520 €")).toBe("down");
    expect(tone("22,6%")).toBeNull();
    expect(tone("—")).toBeNull();
  });
});

describe("stampOf", () => {
  const now = new Date(2026, 8, 24, 11, 30);

  it("prints today's clock when the card says when it was written", () => {
    const written = new Date(2026, 8, 24, 9, 5).getTime() / 1000;
    expect(stampOf(card({ generated: written }), t, now)).toBe(
      "home.daily_today:09:05",
    );
  });

  it("prints Today alone for a card from before the field existed", () => {
    expect(stampOf(card(), t, now)).toBe("home.daily_today_no_time");
  });

  it("dates an older card instead of calling it today's", () => {
    expect(stampOf(card({ day: "2026-09-23" }), t, now)).toBe("23 home.mon_9");
  });
});
