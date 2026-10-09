import { describe, expect, it } from "vitest";
import {
  CLEAR,
  applyFilter,
  bucket,
  findRows,
  includeParam,
  parseFilter,
  sectorsOf,
  sourcesOf,
  splitCoins,
} from "./filter";
import { BUDGET, buildPrompt } from "./prompt";
import { labelRank, placeLabels } from "./labels";
import { tipPlace } from "./QualityMap";
import type { Review, ReviewRow } from "./types";

const t = (key: string, slots?: Record<string, string | number>) =>
  slots ? `${key}(${Object.values(slots).join(",")})` : key;

function row(over: Partial<ReviewRow>): ReviewRow {
  return {
    ticker: "X",
    kind: "stock",
    sector: null,
    held: true,
    verdict: "hold",
    reasons: [],
    quality: 60,
    cheapness: 50,
    metrics: {},
    value: null,
    weight: null,
    risk_share: null,
    pnl: null,
    pnl_pct: null,
    target_weight: null,
    delta: null,
    tax: null,
    buy_after: null,
    watched: false,
    favorite: false,
    lists: [],
    ...over,
    symbol: over.symbol ?? over.ticker ?? "X",
  };
}

const review = (held: ReviewRow[], candidates: ReviewRow[] = []): Review => ({
  base: "EUR",
  as_of: "2026-10-09",
  total: 10_000,
  held,
  candidates,
  plan: { sells: 0, buys: 0, tax: null, tax_currency: "EUR" },
  unpriced: 0,
  jurisdiction: "es",
  added: [],
});

describe("review filter", () => {
  const amd = row({
    ticker: "AMD",
    sector: "Technology",
    weight: 0.15,
    delta: -500,
    tax: 80,
  });
  const jnj = row({ ticker: "JNJ", sector: "Healthcare", weight: 0.03, delta: 200 });
  const etf = row({ ticker: "XEON.DE", kind: "etf", weight: 0.004 });
  const bkng = row({ ticker: "BKNG", sector: "Consumer Cyclical", held: false });
  const data = review([amd, jnj, etf], [bkng]);

  it("files a row with no sector under what it is", () => {
    expect(bucket(etf)).toBe("funds");
    expect(bucket(row({ kind: "crypto" }))).toBe("crypto");
    expect(bucket(row({}))).toBe("unknown");
    expect(bucket(bkng)).toBe("consumer_cyclical");
  });

  it("reads the URL and ignores a band it does not know", () => {
    expect(parseFilter("technology,,technology", "7", "fav,bogus,list:AI")).toEqual({
      sectors: ["technology"],
      band: null,
      sources: ["fav", "list:AI"],
    });
  });

  it("cuts every list and re-adds the plan from what is left", () => {
    const tech = applyFilter(data, { ...CLEAR, sectors: ["technology"] });
    expect(tech.held.map((r) => r.ticker)).toEqual(["AMD"]);
    expect(tech.candidates).toEqual([]);
    expect(tech.plan).toMatchObject({ sells: 500, buys: 0, tax: 80 });
  });

  it("bands weigh held rows only", () => {
    const small = applyFilter(data, { ...CLEAR, band: "0" });
    expect(small.held.map((r) => r.ticker)).toEqual(["XEON.DE"]);
    expect(small.candidates.map((r) => r.ticker)).toEqual(["BKNG"]);
    expect(small.plan.tax).toBeNull();
  });

  it("opens on the book alone, unless nothing is held", () => {
    expect(parseFilter(null, null, null).sources).toEqual(["held"]);
    expect(parseFilter(null, null, null, false).sources).toEqual([]);
    expect(parseFilter(null, null, "all").sources).toEqual([]);
    expect(includeParam(["held"])).toBeUndefined();
    expect(includeParam([])).toBe("all");
    expect(includeParam([], false)).toBeUndefined();
    expect(includeParam(["held", "fav"])).toBe("held,fav");
  });

  it("includes what any picked source has, and always what was typed in", () => {
    const fav = row({ ticker: "ADBE", held: false, watched: true, favorite: true });
    const ai = row({ ticker: "CRWV", held: false, watched: true, lists: ["AI"] });
    const typed = row({ ticker: "NVDA", held: false });
    const read = { ...review([amd, jnj], [fav, ai, typed]), added: ["NVDA"] };
    const pick = (sources: string[]) => {
      const out = applyFilter(read, { ...CLEAR, sources });
      return [...out.held, ...out.candidates].map((r) => r.ticker);
    };
    expect(pick(["held"])).toEqual(["AMD", "JNJ", "NVDA"]);
    expect(pick(["fav", "list:AI"])).toEqual(["ADBE", "CRWV", "NVDA"]);
    expect(pick(["watch"])).toEqual(["ADBE", "CRWV", "NVDA"]);
    expect(sourcesOf(read)).toEqual([
      { key: "held", count: 2 },
      { key: "fav", count: 1 },
      { key: "watch", count: 2 },
      { key: "list:AI", count: 1 },
    ]);
  });

  it("finds rows by symbol or any word, case and accents aside", () => {
    const words = (r: ReviewRow) =>
      r.ticker === "AMD" ? ["Advanced Micro Devices", "Tecnología"] : [null];
    const find = (needle: string) =>
      findRows([amd, jnj, etf], needle, words).map((r) => r.ticker);
    expect(find("")).toEqual(["AMD", "JNJ", "XEON.DE"]);
    expect(find(" xeon ")).toEqual(["XEON.DE"]);
    expect(find("micro")).toEqual(["AMD"]);
    expect(find("tecnologia")).toEqual(["AMD"]);
    expect(find("zzz")).toEqual([]);
  });

  it("takes coins out of the read and keeps the held ones aside", () => {
    const sol = row({ ticker: "SOL-EUR", kind: "crypto", weight: 0.1 });
    const eth = row({ ticker: "ETH-EUR", kind: "crypto", held: false });
    const [book, coins] = splitCoins(review([amd, sol], [bkng, eth]));
    expect(book.held.map((r) => r.ticker)).toEqual(["AMD"]);
    expect(book.candidates.map((r) => r.ticker)).toEqual(["BKNG"]);
    expect(coins.map((r) => r.ticker)).toEqual(["SOL-EUR"]);
    expect(splitCoins(data)[0]).toBe(data);
  });

  it("sums no sales to zero, not minus zero", () => {
    const quiet = applyFilter(review([jnj]), CLEAR);
    expect(Object.is(quiet.plan.sells, 0)).toBe(true);
  });

  it("counts every bucket in the read", () => {
    expect(sectorsOf(data).map((s) => [s.key, s.count])).toContainEqual(["funds", 1]);
  });
});

describe("review prompt", () => {
  it("names each row with its verdict, weight, target and reasons", () => {
    const text = buildPrompt(
      review([
        row({
          ticker: "AMD",
          verdict: "sell",
          weight: 0.15,
          target_weight: 0,
          delta: -1500,
          reasons: ["expensive"],
          metrics: { pe_fwd: 30 },
        }),
      ]),
      t,
      "en",
      "Technology",
    );
    expect(text).toContain("review.prompt_filter(Technology)");
    expect(text).toMatch(/- AMD: review\.verdict_sell, 15\.0% → 0\.0%/);
    expect(text).toContain("review.reason_expensive");
    expect(text).toContain("kpi.pe_fwd.label 30.0x");
    expect(text.trim().endsWith("review.prompt_ask")).toBe(true);
  });

  it("stays under the chat's cap and counts what it left out", () => {
    const many = Array.from({ length: 200 }, (_, i) =>
      row({
        ticker: `T${i}`,
        symbol: `T${i}`,
        weight: 0.005,
        reasons: ["quality", "cheap"],
      }),
    );
    const text = buildPrompt(review(many), t, "en");
    expect(text.length).toBeLessThanOrEqual(BUDGET);
    expect(text).toMatch(/review\.prompt_more\(\d+\)/);
  });
});

describe("map tooltip placement", () => {
  const map = { width: 600, height: 300 };
  const box = { w: 200, h: 100 };

  it("sits centred above a dot with room over it", () => {
    expect(tipPlace({ cx: 300, cy: 200, r: 6 }, box, map)).toEqual({
      left: 200,
      top: 86,
    });
  });

  it("drops below a dot near the top", () => {
    expect(tipPlace({ cx: 300, cy: 40, r: 6 }, box, map)).toEqual({
      left: 200,
      top: 54,
    });
  });

  it("never leaves the map at either side or the bottom", () => {
    expect(tipPlace({ cx: 10, cy: 200, r: 4 }, box, map).left).toBe(8);
    expect(tipPlace({ cx: 595, cy: 200, r: 4 }, box, map).left).toBe(392);
    const tall = tipPlace({ cx: 300, cy: 90, r: 4 }, { w: 200, h: 250 }, map);
    expect(tall.top).toBe(42); // bottom edge at 300 - 8
  });
});

describe("map labels", () => {
  const area = { x0: 0, y0: 0, x1: 300, y1: 300 };
  const dot = (key: string, cx: number, cy: number) => ({
    key,
    cx,
    cy,
    r: 5,
    text: key,
  });

  it("puts a lone label to the right of its dot", () => {
    const spots = placeLabels([dot("AAPL", 100, 100)], area);
    expect(spots.get("AAPL")).toEqual({ x: 108, y: 104, anchor: "start" });
  });

  it("flips to the left at the right edge", () => {
    expect(placeLabels([dot("AAPL", 290, 100)], area).get("AAPL")?.anchor).toBe("end");
  });

  it("moves a second label off the first and drops one with nowhere to go", () => {
    const pile = [dot("MELI", 100, 100), dot("ZBRA", 100, 104), dot("CRM", 102, 102)];
    const spots = placeLabels(pile, area);
    expect(spots.get("MELI")?.anchor).toBe("start");
    expect(spots.get("ZBRA")?.anchor).toBe("end");
    expect(spots.has("CRM")).toBe(false);
    expect(spots.size).toBeLessThan(pile.length);
  });

  it("keeps clear of a blocked caption", () => {
    const caption = { x0: 105, y0: 90, x1: 200, y1: 110 };
    const spots = placeLabels([dot("AAPL", 100, 100)], area, [caption]);
    expect(spots.get("AAPL")?.anchor).toBe("end");
  });

  it("labels the moves first, then held names by weight", () => {
    const sell = row({ verdict: "sell", weight: 0.01 });
    const big = row({ verdict: "hold", weight: 0.2 });
    const small = row({ verdict: "hold", weight: 0.01 });
    const outside = row({ verdict: "watch", held: false, weight: null });
    const order = [outside, small, big, sell].sort((a, b) => {
      const [ra, rb] = [labelRank(a), labelRank(b)];
      return ra[0] - rb[0] || ra[1] - rb[1] || ra[2] - rb[2];
    });
    expect(order).toEqual([sell, big, small, outside]);
  });
});
