import { describe, expect, it } from "vitest";
import { foldedAtFirst } from "./Tables";
import type { ReviewRow, Verdict } from "./types";
import {
  closeCall,
  closeCalls,
  groupByVerdict,
  hasMoves,
  mapKeys,
  mapMark,
  verdictMark,
  parseVerdicts,
  pickVerdicts,
  verdictCounts,
  verdictParam,
} from "./verdicts";

const row = (over: Partial<ReviewRow> & { ticker: string }): ReviewRow =>
  ({
    symbol: over.ticker,
    held: true,
    verdict: "hold",
    reasons: [],
    quality: null,
    cheapness: null,
    target_weight: null,
    delta: null,
    tax: null,
    ...over,
  }) as ReviewRow;

const near = (over: Partial<ReviewRow> & { ticker: string }) =>
  row({ reasons: ["close_call"], ...over });

describe("parseVerdicts / verdictParam", () => {
  it("reads ?v= in reading order and drops unknown words", () => {
    expect(parseVerdicts("hold, sell,nope,buy")).toEqual(["sell", "hold", "buy"]);
    expect(parseVerdicts(null)).toEqual([]);
    expect(parseVerdicts("")).toEqual([]);
  });

  it("writes nothing for an empty pick", () => {
    expect(verdictParam([])).toBeUndefined();
    expect(verdictParam(["sell", "add"])).toBe("sell,add");
  });
});

describe("counts, picks and groups", () => {
  const rows = [
    row({ ticker: "A", verdict: "hold" }),
    row({ ticker: "B", verdict: "sell" }),
    row({ ticker: "C", verdict: "hold" }),
    row({ ticker: "D", verdict: "add" }),
  ];

  it("counts only the verdicts present, in reading order", () => {
    expect(verdictCounts(rows)).toEqual([
      { verdict: "sell", count: 1 },
      { verdict: "add", count: 1 },
      { verdict: "hold", count: 2 },
    ]);
  });

  it("picks every row when nothing is picked", () => {
    expect(pickVerdicts(rows, [])).toBe(rows);
    expect(pickVerdicts(rows, ["hold"]).map((one) => one.ticker)).toEqual(["A", "C"]);
  });

  it("groups in reading order, keeping the server's order inside", () => {
    expect(
      groupByVerdict(rows).map((group) => [
        group.verdict,
        group.rows.map((one) => one.ticker),
      ]),
    ).toEqual([
      ["sell", ["B"]],
      ["add", ["D"]],
      ["hold", ["A", "C"]],
    ]);
  });

  it("folds the holds of a long book with something else to read", () => {
    const long = [
      ...rows,
      row({ ticker: "E" }),
      row({ ticker: "F" }),
      row({ ticker: "G" }),
    ];
    expect([...foldedAtFirst(long, false)]).toEqual(["hold"]);
    // Picked, short, or all holds: everything opens.
    expect(foldedAtFirst(long, true).size).toBe(0);
    expect(foldedAtFirst(rows, false).size).toBe(0);
    const holds = long.map((one) => ({ ...one, verdict: "hold" as Verdict }));
    expect(foldedAtFirst(holds, false).size).toBe(0);
  });
});

describe("hasMoves", () => {
  it("is false when every row has no target, no money and no tax", () => {
    expect(
      hasMoves([row({ ticker: "A" }), row({ ticker: "B", delta: 0, tax: 0 })]),
    ).toBe(false);
  });

  it("is true for a target, money to move or a tax", () => {
    expect(hasMoves([row({ ticker: "A", target_weight: 0.05 })])).toBe(true);
    expect(hasMoves([row({ ticker: "A", delta: -120 })])).toBe(true);
    expect(hasMoves([row({ ticker: "A", tax: 30 })])).toBe(true);
  });
});

describe("closeCall", () => {
  it("is null for a row the server did not mark", () => {
    expect(closeCall(row({ ticker: "A", quality: 70, cheapness: 60 }))).toBeNull();
  });

  it("measures a weak held name to the sale line by its higher score", () => {
    const call = closeCall(near({ ticker: "A", quality: 38, cheapness: 36 }));
    expect(call).toMatchObject({ side: "sell", axis: "quality", line: 35, points: 4 });
    // From exactly the line one point still has to go.
    expect(closeCall(near({ ticker: "B", quality: 35, cheapness: 30 }))?.points).toBe(
      1,
    );
  });

  it("measures a clean held name to the add line by its larger shortfall", () => {
    const call = closeCall(near({ ticker: "A", quality: 63, cheapness: 51.2 }));
    // Quality is 2 short of 65, price 3.8 short of 55: price decides.
    expect(call).toMatchObject({ side: "add", axis: "cheapness", line: 55, points: 4 });
  });

  it("measures an outside name to a buy", () => {
    const call = closeCall(
      near({ ticker: "A", held: false, quality: 58, cheapness: 54 }),
    );
    expect(call).toMatchObject({ side: "buy", axis: "quality", line: 65, points: 7 });
  });

  it("gives no distance when the scores do not say which line", () => {
    const blank = { side: null, points: null, axis: null, line: null };
    expect(closeCall(near({ ticker: "A" }))).toMatchObject(blank);
    // Held, between the lines: neither a sale nor an add by the scores.
    expect(closeCall(near({ ticker: "B", quality: 50, cheapness: 45 }))).toMatchObject(
      blank,
    );
    // Over both add lines and still held back by something else.
    expect(closeCall(near({ ticker: "C", quality: 80, cheapness: 70 }))).toMatchObject(
      blank,
    );
  });

  it("lists the nearest first and the ones without a distance last", () => {
    const calls = closeCalls([
      near({ ticker: "FAR", held: false, quality: 50, cheapness: 54 }),
      near({ ticker: "NONE" }),
      near({ ticker: "NEAR", quality: 36, cheapness: 30 }),
      row({ ticker: "SKIP" }),
    ]);
    expect(calls.map((call) => call.row.ticker)).toEqual(["NEAR", "FAR", "NONE"]);
  });
});

describe("mapMark", () => {
  it("colours a name by the move it is, close calls apart from quiet holds", () => {
    const at = (verdict: Verdict, reasons: string[] = []) =>
      mapMark(row({ ticker: "X", verdict, reasons }));
    expect(at("sell")).toBe("sell");
    expect(at("trim")).toBe("trim");
    expect(at("pass")).toBe("sell");
    expect(at("add")).toBe("add");
    expect(at("hold")).toBe("still");
    expect(at("hold", ["close_call"])).toBe("near");
    expect(at("watch")).toBe("watch");
    expect(at("watch", ["close_call"])).toBe("near");
    expect(at("buy")).toBe("buy");
    expect(at("bet")).toBe("bet");
    expect(at("core")).toBe("still");
  });
});

describe("mapKeys", () => {
  it("lists each colour worn once, its verdicts in reading order, quiet holds left out", () => {
    const keys = mapKeys([
      row({ ticker: "A", verdict: "pass", held: false }),
      row({ ticker: "B", verdict: "hold" }),
      row({ ticker: "C", verdict: "sell" }),
      row({ ticker: "D", verdict: "hold", reasons: ["close_call"] }),
      row({ ticker: "E", verdict: "buy", held: false }),
    ]);
    expect(keys).toEqual([
      { mark: "sell", verdicts: ["sell", "pass"] },
      { mark: "near", verdicts: ["hold"] },
      { mark: "buy", verdicts: ["buy"] },
    ]);
  });
});

describe("verdictMark", () => {
  it("gives the bar, the chips and the map one colour per verdict", () => {
    expect(verdictMark("sell")).toBe("sell");
    expect(verdictMark("pass")).toBe("sell");
    expect(verdictMark("trim")).toBe("trim");
    expect(verdictMark("add")).toBe("add");
    expect(verdictMark("buy")).toBe("buy");
    expect(verdictMark("bet")).toBe("bet");
    expect(verdictMark("watch")).toBe("watch");
    expect(verdictMark("hold")).toBe("still");
  });
});
