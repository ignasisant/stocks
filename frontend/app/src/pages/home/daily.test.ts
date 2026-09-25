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

import { stampOf, wantsWriting } from "./Daily";
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
