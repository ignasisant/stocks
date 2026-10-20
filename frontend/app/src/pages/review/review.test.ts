import { describe, expect, it } from "vitest";
import {
  CLEAR,
  applyFilter,
  planMoves,
  waitingMoves,
  bucket,
  findRows,
  includeParam,
  parseFilter,
  sectorsOf,
  sourcesOf,
  splitCoins,
} from "./filter";
import { askAgain, foreign, longDay, tipFigures } from "./format";
import { BUDGET, buildPrompt, noteText } from "./prompt";
import { countryName } from "./countries";
import { NARROW, lineSlots } from "./lines";
import { labelRank, placeLabels } from "./labels";
import {
  driftOf,
  gainOf,
  sampleTrail,
  TRAIL_MARK,
  tipPlace,
  trailOf,
} from "./QualityMap";
import type { Review, ReviewRow, ScorePoint } from "./types";

const t = (key: string, slots?: Record<string, string | number>) =>
  slots ? `${key}(${Object.values(slots).join(",")})` : key;

function row(over: Partial<ReviewRow>): ReviewRow {
  return {
    ticker: "X",
    kind: "stock",
    sector: null,
    country: null,
    currency: null,
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
  tax_status: "chosen",
  added: [],
  notes: [],
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

  it("carries the book's notes, a repurchase window included", () => {
    const text = buildPrompt(
      {
        ...review([row({ ticker: "AMD", weight: 0.2 })]),
        notes: [
          {
            key: "tax_offset",
            count: 1,
            sector: null,
            country: null,
            currency: null,
            weight: null,
            amount: 152,
            tickers: ["INTC"],
            day: "2026-12-12",
          },
        ],
      },
      t,
      "en",
    );
    expect(text).toMatch(/review\.note_tax_offset\(1,,.*,INTC\)/);
    expect(text).toContain("review.note_tax_offset_window(2026-12-12)");
  });

  it("tags a row quoted in another currency, and only that one", () => {
    const text = buildPrompt(
      review([
        row({ ticker: "AMD", sector: "Technology", currency: "USD", weight: 0.2 }),
        row({ ticker: "SAN.MC", currency: "EUR", weight: 0.1 }),
      ]),
      t,
      "en",
    );
    expect(text).toContain("- AMD (Technology, USD): ");
    expect(text).toContain("- SAN.MC: ");
  });

  it("words the country, currency, fund and cash notes", () => {
    const note = {
      count: 4,
      sector: null,
      country: null as string | null,
      currency: null as string | null,
      weight: 0.8,
      amount: null,
      tickers: [],
      day: null,
    };
    const say = (over: Partial<typeof note> & { key: string }) =>
      noteText({ ...note, ...over }, "EUR", t, "es");
    expect(say({ key: "country_heavy", country: "United States" })).toContain(
      "Estados Unidos",
    );
    expect(say({ key: "country_heavy", country: "Atlantis" })).toContain("Atlantis");
    expect(say({ key: "currency_heavy", currency: "USD" })).toMatch(
      /^review\.note_currency_heavy\(.*USD.*80,0/,
    );
    expect(say({ key: "fund_core" })).toMatch(/^review\.note_fund_core\(4,/);
    expect(say({ key: "cash_heavy" })).toMatch(/^review\.note_cash_heavy\(4,/);
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

describe("review currencies and countries", () => {
  it("calls a row foreign only when its currency is known and not the page's", () => {
    expect(foreign(row({ currency: "USD" }), "EUR")).toBe("USD");
    expect(foreign(row({ currency: "EUR" }), "EUR")).toBeNull();
    expect(foreign(row({ currency: null }), "EUR")).toBeNull();
  });

  it("prints a country in the reader's language, an unknown one as given", () => {
    expect(countryName("Spain", "en")).toBe("Spain");
    expect(countryName("United Kingdom", "es")).toBe("Reino Unido");
    expect(countryName("Narnia", "es")).toBe("Narnia");
  });
});

describe("review dates", () => {
  it("reads an API day in the reader's locale, not as ISO", () => {
    expect(longDay("2026-10-09", "en")).toBe("Oct 9, 2026");
    expect(longDay("2026-10-09", "es")).toBe("9 oct 2026");
  });

  it("hands back what it cannot read", () => {
    expect(longDay("soon", "en")).toBe("soon");
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
    const low = tipPlace({ cx: 300, cy: 250, r: 4 }, { w: 200, h: 100 }, map);
    expect(low.top).toBe(138); // above, clear of the dot
  });

  it("goes beside a dot when it is too tall for above or below", () => {
    const tall = { w: 200, h: 250 };
    // Right of it, the dot left uncovered (300 + 4 + 8).
    expect(tipPlace({ cx: 300, cy: 90, r: 4 }, tall, map)).toEqual({
      left: 312,
      top: 8,
    });
    // Near the right edge, left of it (500 - 4 - 8 - 200).
    expect(tipPlace({ cx: 500, cy: 150, r: 4 }, tall, map)).toEqual({
      left: 288,
      top: 25,
    });
  });

  it("keeps clear of the name's trail when a spot clear of it exists", () => {
    // Too tall for above or below: right of the dot is the usual place, but
    // the trail runs off that way, so the box goes left of the dot instead.
    const tall = { w: 200, h: 250 };
    const trail = sampleTrail([
      [560, 150],
      [300, 150],
    ]);
    expect(tipPlace({ cx: 300, cy: 150, r: 4 }, tall, map).left).toBe(312);
    const spot = tipPlace({ cx: 300, cy: 150, r: 4 }, tall, map, trail);
    expect(spot.left + tall.w).toBeLessThanOrEqual(296);
  });

  it("hides a stretch of line before a named step when it must hide one", () => {
    // Nearly as tall as the map: whatever it does, it covers some of a path
    // that crosses it, so it sits between the steps, not over one.
    const tall = { w: 200, h: 270 };
    const steps: [number, number][] = [
      [60, 250],
      [500, 60],
      [560, 150],
    ];
    const marks = steps.map(([x, y]): [number, number, number] => [x, y, TRAIL_MARK]);
    const spot = tipPlace({ cx: 560, cy: 150, r: 4 }, tall, map, [
      ...sampleTrail(steps),
      ...marks,
    ]);
    for (const [x] of steps) {
      expect(x < spot.left - 8 || x > spot.left + tall.w + 8).toBe(true);
    }
  });

  it("overlaps only when there is no room on any side", () => {
    const phone = { width: 340, height: 300 };
    const spot = tipPlace({ cx: 170, cy: 90, r: 4 }, { w: 300, h: 250 }, phone);
    expect(spot).toEqual({ left: 20, top: 42 });
  });
});

describe("map tooltip figures", () => {
  it("prints the tooltip's KPIs in order, each in its unit, and drops the missing", () => {
    const figures = tipFigures(
      { roic: 0.31, pe_fwd: 22.4, growth_pe: null, fcf_yield: 0.045, moat: 80 },
      "en",
    );
    expect(figures).toEqual([
      { key: "pe_fwd", value: "22.4x" },
      { key: "fcf_yield", value: "4.5%" },
      { key: "roic", value: "31.0%" },
    ]);
  });

  it("is empty for a name with no fundamentals", () => {
    expect(tipFigures({}, "en")).toEqual([]);
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

  it("keeps a label off the path drawn when a spot allows, but never drops it", () => {
    // A path running right out of the dot: the label goes another way.
    const path = Array.from({ length: 40 }, (_, k) => ({
      x0: 105 + k * 4,
      y0: 99,
      x1: 107 + k * 4,
      y1: 101,
    }));
    const spot = placeLabels([dot("SEZL", 100, 100)], area, [], path).get("SEZL");
    expect(spot?.anchor).not.toBe("start");
    // Paths all round: the label still shows, where it would have gone.
    const everywhere = [{ x0: 0, y0: 0, x1: 300, y1: 300 }];
    expect(
      placeLabels([dot("SEZL", 100, 100)], area, [], everywhere).get("SEZL"),
    ).toEqual({
      x: 108,
      y: 104,
      anchor: "start",
    });
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

describe("review lines", () => {
  it("fills the help copy with the book's own lines", () => {
    expect(lineSlots(NARROW, "es")).toMatchObject({
      small: "0,5\u00a0%",
      add_to: "5\u00a0%",
    });
    const wide = lineSlots(
      { concentrated: 0.15, small: 0.0025, add_to: 0.02, sector: 0.4 },
      "en",
    );
    expect(wide).toMatchObject({ small: "0.25%", add_to: "2%", concentrated: "15%" });
  });

  it("quotes the narrow line when the book is too small for a concentration", () => {
    expect(lineSlots({ ...NARROW, concentrated: null }, "en").concentrated).toBe("15%");
  });
});

describe("review outside buys", () => {
  const sell = row({ ticker: "AMD", verdict: "sell", delta: -900 });
  const add = row({ ticker: "JNJ", verdict: "add", delta: 200, sector: "Healthcare" });
  const buy = row({
    ticker: "BKNG",
    held: false,
    verdict: "buy",
    delta: 500,
    target_weight: 0.05,
    sector: "Consumer Cyclical",
  });
  const plain = row({ ticker: "MSFT", held: false, verdict: "buy" });
  const data = review([sell, add], [plain, buy]);

  it("counts an outside buy's money after a filter", () => {
    const cyc = applyFilter(data, { ...CLEAR, sectors: ["consumer_cyclical"] });
    expect(cyc.plan).toMatchObject({ sells: 0, buys: 500 });
    const both = applyFilter(data, {
      ...CLEAR,
      sectors: ["healthcare", "consumer_cyclical"],
    });
    expect(both.plan.buys).toBe(700);
  });

  it("lists outside buys after the held adds", () => {
    const { out, into } = planMoves(data);
    expect(out).toEqual([sell]);
    expect(into).toEqual([add, buy]);
  });
});

describe("review stay and new money", () => {
  const strong = row({ ticker: "ADBE", quality: 80, cheapness: 70, new_money: 300 });
  const fair = row({
    ticker: "PDD",
    quality: 60,
    cheapness: 55,
    new_money: 200,
    sector: "Technology",
  });
  const still = row({ ticker: "JNJ", reasons: ["close_call"] });
  const data = review([fair, still, strong]);

  it("lists the adds waiting for new money, best first", () => {
    expect(waitingMoves(data)).toEqual([strong, fair]);
  });

  it("re-adds the new money from what a filter leaves", () => {
    const tech = applyFilter(data, { ...CLEAR, sectors: ["technology"] });
    expect(tech.plan.new_money).toBe(200);
  });

  it("tells the chat the plan is to stay, and what waits for money", () => {
    const text = buildPrompt(data, t, "en");
    expect(text).toContain("review.prompt_stay");
    expect(text).not.toContain("review.prompt_plan");
    expect(text).toContain("review.prompt_wait(ADBE, PDD)");
  });
});

describe("review pending names", () => {
  it("refetches once when the read is partial", () => {
    const partial = { ...review([]), pending: 3 };
    expect(askAgain(partial, null, "EUR|")).toBe(true);
    expect(askAgain(partial, "EUR|", "EUR|")).toBe(false);
    expect(askAgain(partial, "EUR|", "USD|")).toBe(true);
    expect(askAgain(review([]), null, "EUR|")).toBe(false);
  });
});

describe("driftOf / gainOf", () => {
  const then = { quality: 60.4, cheapness: 40.4, source: "filings" as const };

  it("reads which way each score moved since the window opened", () => {
    expect(driftOf(30, then)).toBe("dear");
    expect(driftOf(55, then)).toBe("cheap");
    expect(gainOf(70, then)).toBe("better");
    expect(gainOf(50, then)).toBe("worse");
  });

  it("takes a move within the printed whole number as none", () => {
    expect(driftOf(40.2, then)).toBe("flat");
    expect(gainOf(59.6, then)).toBe("flat");
  });

  it("has no move without a past point or a score now", () => {
    expect(driftOf(40, null)).toBeNull();
    expect(gainOf(null, then)).toBeNull();
  });
});

describe("map trail", () => {
  const cheapness: Record<string, number> = { "2y": 20, "1y": 40, "6m": 60, "1m": 70 };
  const at = (step: string): ScorePoint | null => {
    const value = cheapness[step];
    return value === undefined
      ? null
      : { quality: 50, cheapness: value, source: "price" };
  };

  it("runs two years through every half year, oldest first, skipping a step it lacks", () => {
    expect(trailOf("2y", at).map((point) => point.cheapness)).toEqual([20, 40, 60]);
  });

  it("starts a short window at its own first day alone", () => {
    expect(trailOf("1m", at).map((point) => point.cheapness)).toEqual([70]);
    expect(trailOf("1y", at).map((point) => point.cheapness)).toEqual([40, 60]);
  });
});
