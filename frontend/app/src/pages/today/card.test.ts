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
  POLL_MS,
  activeTab,
  badgeKey,
  compareOrder,
  leadersLaggards,
  linesOf,
  marketSplit,
  missingKeys,
  nextPoll,
  noteKey,
  notable,
  compareData,
  opens,
  safeUrl,
  sectionsOf,
  shows,
  sourceKey,
  stampOf,
  tabsOf,
  teaserOf,
  tone,
  wantsWriting,
} from "./card";
import type { DailyItem } from "../home/types";
import type { MarketCard, PersonalCard, TodayRow, TodaySection } from "./types";

const t = (key: string, slots?: Record<string, string | number>) =>
  slots ? `${key}:${Object.values(slots).join(",")}` : key;

function card(over: Partial<PersonalCard> = {}): PersonalCard {
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

describe("sectionsOf", () => {
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
  it("puts the fired alerts in their own section and the rest under watch", () => {
    const { alerts, watch: rest } = sectionsOf([watch, alert]);
    expect(alerts.map((i) => i.key)).toEqual(["alert_hit:AAPL"]);
    expect(rest.map((i) => i.key)).toEqual(["earnings:NVDA"]);
  });

  it("reads a line stored before sections as worth a look", () => {
    const { section: _, ...old } = watch;
    expect(sectionsOf([old]).watch).toEqual([old]);
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

describe("badgeKey", () => {
  it("drops the AI label from the default card once it is final", () => {
    expect(badgeKey({ pending: false, source: "llm" })).toBe("home.daily_badge");
    expect(badgeKey({ pending: true, source: "computed" })).toBe("home.daily_badge");
    expect(badgeKey({ pending: false, source: "computed" })).toBe(
      "home.daily_badge_computed",
    );
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

/* ---------------------------------------------------------- the Today page */

const item = (key: string, section: "alerts" | "watch" = "watch"): DailyItem => ({
  key,
  kind: "earnings",
  line: key,
  tickers: [],
  section,
});

const row = (key: string, data: TodayRow["data"] = {}): TodayRow => ({
  key,
  kind: "compare",
  line: key,
  tickers: [key],
  source: "computed",
  url: "",
  date: "",
  data,
});

const section = (id: TodaySection["id"], rows: TodayRow[]): TodaySection => ({
  id,
  title: id,
  rows,
  note: "",
  missing: [],
});

function market(over: Partial<MarketCard> = {}): MarketCard {
  return {
    session: "2026-10-12",
    built_at: 0,
    lang: "en",
    source: "computed",
    headline: "Risk on",
    lines: [],
    regime: null,
    breadth: null,
    rates: [],
    banks: [],
    sectors: [],
    inflation: [],
    crypto: null,
    index: null,
    missing: [],
    ...over,
  };
}

describe("teaserOf", () => {
  it("puts the fired alerts first and counts what the page holds besides", () => {
    const personal: PersonalCard = card({
      items: [item("a"), item("b"), item("alert", "alerts"), item("c")],
      today: [section("news", [row("n1"), row("n2")])],
    });
    const { lines, more } = teaserOf(personal);
    expect(lines.map((line) => line.key)).toEqual(["alert", "a", "b"]);
    expect(more).toBe(1 + 2);
  });

  it("reads the brief in place of worth-a-look when there is one", () => {
    const asked = { title: "NVDA", asks: [1], lines: [item("brief")], chart: null };
    const { lines, more } = teaserOf(
      card({ items: [item("watch")], sections: [asked] }),
    );
    expect(lines.map((line) => line.key)).toEqual(["brief"]);
    expect(more).toBe(0);
  });
});

describe("tabsOf / activeTab / shows", () => {
  it("offers only the tabs with something under them, All first", () => {
    const tabs = tabsOf({ market: null, personal: card() });
    expect(tabs.map((tab) => tab.id)).toEqual(["all"]);
  });

  it("counts what is read and leaves tables and reads uncounted", () => {
    const personal: PersonalCard = card({
      items: [item("alert", "alerts")],
      today: [
        section("news", [row("n1"), row("n2")]),
        section("compare", [row("NVDA")]),
      ],
    });
    const tabs = tabsOf({
      market: market({ source: "llm", lines: [{ topic: "rates", line: "10y up" }] }),
      personal,
    });
    expect(tabs).toEqual([
      { id: "all", count: null },
      { id: "alerts", count: 1 },
      { id: "compare", count: null },
      { id: "news", count: 2 },
      { id: "macro", count: null },
    ]);
  });

  it("leaves out a computed read's lines: they repeat its tiles", () => {
    const lines = [{ topic: "rates" as const, line: "10y at 5.22%" }];
    expect(marketSplit(market({ lines })).macro).toEqual([]);
    expect(marketSplit(market({ source: "llm", lines })).macro).toEqual(lines);
    const tabs = tabsOf({ market: market({ lines }), personal: null });
    expect(tabs.map((tab) => tab.id)).toEqual(["all"]);
  });

  it("opens the tab ?tab= names only when the page offers it", () => {
    const regime = { score: 60, key: "risk_on", run: 3, score_month: null };
    const tabs = tabsOf({ market: market({ regime }), personal: null });
    expect(activeTab(tabs, "trends")).toBe("trends");
    expect(activeTab(tabs, "news")).toBe("all");
    expect(activeTab(tabs, null)).toBe("all");
    expect(shows("all", "news")).toBe(true);
    expect(shows("trends", "news")).toBe(false);
  });
});

describe("leadersLaggards", () => {
  const sector = (ticker: string, month: number | null) => ({
    ticker,
    name: ticker,
    week: null,
    month,
  });

  it("ranks by the month and skips a sector with no month", () => {
    const sectors = [
      sector("XLK", 4),
      sector("XLE", -3),
      sector("XLU", 1),
      sector("XLF", null),
    ];
    const { leaders, laggards } = leadersLaggards(sectors, 3);
    expect(leaders.map((s) => s.ticker)).toEqual(["XLK", "XLU"]);
    expect(laggards.map((s) => s.ticker)).toEqual(["XLE"]);
  });

  it("never lists a sector behind the index as a leader", () => {
    const sectors = [
      sector("XLK", 3.4),
      sector("XLE", 2.1),
      sector("XLV", -0.5),
      sector("XLF", -5.2),
      sector("XLRE", -4.7),
      sector("XLB", -4),
      sector("XLU", -1),
    ];
    const { leaders, laggards } = leadersLaggards(sectors, 3);
    expect(leaders.map((s) => s.ticker)).toEqual(["XLK", "XLE"]);
    expect(laggards.map((s) => s.ticker)).toEqual(["XLF", "XLRE", "XLB"]);
  });
});

describe("comparisons", () => {
  it("calls a five-point gap or a proposed move notable", () => {
    expect(notable(compareData(row("A", { vs_sector_m6: 5 })))).toBe(true);
    expect(notable(compareData(row("A", { vs_sector_m6: -4.9 })))).toBe(false);
    expect(notable(compareData(row("A", { verdict: "trim" })))).toBe(true);
    expect(notable(compareData(row("A", { verdict: "hold" })))).toBe(false);
  });

  it("reads a figure that is not a number as unknown", () => {
    expect(compareData(row("A", { m6: "12" })).move).toBeNull();
  });

  it("reads the figures of the span asked for", () => {
    const data = { m1: 2, m6: 8, y1: 15, vs_sector_m1: -6, vs_sector_m6: 1 };
    expect(compareData(row("A", data), "m1")).toMatchObject({ move: 2, vs_sector: -6 });
    expect(compareData(row("A", data), "y1")).toMatchObject({
      move: 15,
      vs_sector: null,
    });
    expect(notable(compareData(row("A", data), "m1"))).toBe(true);
    expect(notable(compareData(row("A", data)))).toBe(false);
  });

  it("puts the notable rows first, the rest in the server's order", () => {
    const rows = [
      row("A"),
      row("B", { verdict: "sell" }),
      row("C"),
      row("D", { vs_sector_m6: 9 }),
    ];
    expect(compareOrder(rows).map((r) => r.key)).toEqual(["B", "D", "A", "C"]);
  });
});

describe("sources", () => {
  it("tags results by kind and the rest by source", () => {
    expect(sourceKey({ kind: "results", source: "8k" })).toBe("today.src_results");
    expect(sourceKey({ kind: "filing", source: "8k" })).toBe("today.src_8k");
    expect(sourceKey({ kind: "news", source: "yahoo" })).toBe("today.src_yahoo");
    expect(sourceKey({ kind: "compare", source: "computed" })).toBeNull();
  });

  it("names the sources that did not answer, unknown ones dropped", () => {
    expect(missingKeys(["yahoo", "nope", "edgar"])).toEqual([
      "today.src_yahoo",
      "today.src_edgar",
    ]);
  });
});

describe("nextPoll", () => {
  it("polls fast while the card is written, slowly while the market catches up", () => {
    expect(
      nextPoll({ market_stale: false, personal: card({ pending: true }) }, 0),
    ).toBe(POLL_MS);
    expect(nextPoll({ market_stale: true, personal: card() }, 0)).toBeGreaterThan(
      POLL_MS,
    );
    expect(nextPoll({ market_stale: false, personal: card() }, 0)).toBeNull();
  });

  it("stops at the cap however long the job runs", () => {
    expect(
      nextPoll({ market_stale: true, personal: card({ pending: true }) }, 60),
    ).toBeNull();
  });
});

describe("safeUrl", () => {
  it("opens http(s) and nothing else", () => {
    expect(safeUrl("https://www.sec.gov/x")).toBe("https://www.sec.gov/x");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("not a url")).toBeNull();
  });
});
