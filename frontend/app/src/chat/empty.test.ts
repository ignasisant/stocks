import { describe, expect, it } from "vitest";

import { heaviest, recentThreads, startersFor, tickerFamily } from "./Empty";
import type { Conversation } from "./types";

describe("heaviest", () => {
  it("names the heaviest priced position at half its weight", () => {
    expect(
      heaviest([
        { ticker: "MSFT", shares: 3, weight: 0.12 },
        { ticker: "NVDA", shares: 5, weight: 0.31 },
        { ticker: "SAN.MC", shares: 100, weight: 0.08 },
      ]),
    ).toEqual({ top: "NVDA", n: 16 });
  });

  it("skips unpriced and closed rows, so an unlisted ISIN is never named", () => {
    expect(
      heaviest([
        { ticker: "IE00B4L5Y983", shares: 10, weight: null },
        { ticker: "TSLA", shares: 0, weight: 0.5 },
        { ticker: "ASML.AS", shares: 1, weight: 0.01 },
      ]),
    ).toEqual({ top: "ASML.AS", n: 1 });
  });

  it("falls back to a held ticker at 5% when nothing is priced", () => {
    expect(heaviest([{ ticker: "VWCE.DE", shares: 2, weight: null }])).toEqual({
      top: "VWCE.DE",
      n: 5,
    });
  });
});

describe("startersFor", () => {
  const general = ["a", "b", "c", "d", "e"];

  it("puts the page's own questions first and caps the set at five", () => {
    expect(startersFor("today", general)).toEqual([
      "chat.starter_today_1",
      "chat.starter_today_2",
      "a",
      "b",
      "c",
    ]);
  });

  it("leaves the general set alone on a page with none of its own", () => {
    expect(startersFor("home", general)).toEqual(general);
  });
});

describe("tickerFamily", () => {
  it("asks a coin, a fund or an index nothing about results or rivals", () => {
    expect(tickerFamily("crypto", "MOODENG-EUR")).toBe("coin");
    expect(tickerFamily("equity_fund", "VWCE.DE")).toBe("fund");
    expect(tickerFamily("money_market", "XEON.DE")).toBe("fund");
    expect(tickerFamily("index", "^GSPC")).toBe("index");
    expect(tickerFamily("stock", "NVDA")).toBe("stock");
  });

  it("guesses from the symbol until the profile names the kind", () => {
    expect(tickerFamily(null, "MOODENG-EUR")).toBe("coin");
    expect(tickerFamily(undefined, "^IBEX")).toBe("index");
    expect(tickerFamily(null, "BRK-B")).toBe("stock");
    expect(tickerFamily(null, "PEPE24478-USD", true)).toBe("coin");
  });

  it("puts the family's questions in front of the general set", () => {
    expect(startersFor("ticker", ["a", "b"], ["c1", "c2"])).toEqual(["c1", "c2", "a", "b"]);
  });
});

describe("recentThreads", () => {
  const c = (id: string, updated: string, extra: Partial<Conversation> = {}) =>
    ({ id, title: id, updated, messages: 2, ...extra }) as Conversation;

  it("offers the two latest used threads, not the open, empty, daily or scheduled ones", () => {
    const got = recentThreads(
      [
        c("old", "2026-11-01"),
        c("new", "2026-11-14"),
        c("open", "2026-11-15"),
        c("empty", "2026-11-13", { messages: 0 }),
        c("daily", "2026-11-12", { daily: "2026-11-12" }),
        c("run", "2026-11-12", { scheduled: "job" }),
        c("mid", "2026-11-10"),
      ],
      "open",
    );
    expect(got.map((x) => x.id)).toEqual(["new", "mid"]);
  });
});
