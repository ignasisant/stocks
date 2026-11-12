import { describe, expect, it } from "vitest";

import type { Issue, Preview, Row } from "./api";
import { answered, changes, corrected } from "./fixes";

const issue = (key: string): Issue => ({
  severity: "warning",
  field: "ticker",
  key,
  params: {},
  message: key,
});

function row(ticker: string, extra: Partial<Row> = {}): Row {
  return {
    date: "2025-03-03",
    ticker,
    action: "buy",
    quantity: 3,
    price: 95,
    currency: "USD",
    fee: 0,
    note: "",
    issues: [],
    duplicate: false,
    gain: 0.1,
    ...extra,
  };
}

const doubt = issue("validate.ticker_doubt");
const unknown = issue("validate.unknown_ticker");
const oversell = issue("validate.oversell");

function preview(importable: Row[], extra: Partial<Preview> = {}): Preview {
  return {
    platform: "llm",
    label: "",
    kind: "trades",
    unavailable: false,
    filename: "extracto.csv",
    digest: "d",
    importable,
    rejected: [],
    duplicates: 0,
    skipped: [],
    broker: "",
    needs_broker: false,
    unlisted: [],
    doubted: [],
    ...extra,
  };
}

const AMT_TO_MU = { code: "AMT", currency: "USD", symbol: "MU" };

describe("corrected", () => {
  it("is the preview itself when the reader said nothing", () => {
    const read = preview([row("AMT")]);
    expect(corrected(read, [])).toBe(read);
  });

  it("renames the code's rows and takes the doubt with it", () => {
    const read = preview(
      [
        row("AMT", { issues: [doubt, oversell] }),
        row("AMT", { currency: "EUR", issues: [doubt] }),
        row("NVDA"),
      ],
      { doubted: ["AMT"] },
    );
    const shown = corrected(read, [AMT_TO_MU]);
    expect(shown.importable.map((r) => r.ticker)).toEqual(["MU", "AMT", "NVDA"]);
    expect(shown.importable[0]!.issues).toEqual([oversell]);
    expect(shown.importable[0]!.gain).toBeNull();
    // The euro rows were not asked about: still AMT, still doubted.
    expect(shown.doubted).toEqual(["AMT"]);
    expect(read.importable[0]!.ticker).toBe("AMT");
  });

  it("clears the doubt and nothing else when the ticker was right", () => {
    const read = preview([row("AMT", { issues: [doubt, unknown] })], {
      doubted: ["AMT"],
    });
    const shown = corrected(read, [{ code: "AMT", currency: "USD", symbol: "AMT" }]);
    expect(shown.importable[0]).toMatchObject({ ticker: "AMT", gain: 0.1 });
    expect(shown.importable[0]!.issues).toEqual([unknown]);
    expect(shown.doubted).toEqual([]);
  });

  it("no longer holds a renamed code unpriced", () => {
    const read = preview([row("MICRON", { issues: [unknown] })], {
      unlisted: ["MICRON"],
    });
    const shown = corrected(read, [{ code: "MICRON", currency: "USD", symbol: "MU" }]);
    expect(shown.unlisted).toEqual([]);
    expect(shown.importable[0]!.issues).toEqual([]);
  });

  it("leaves an older server's missing lists missing", () => {
    const read = preview([row("AMT")], { unlisted: undefined, doubted: undefined });
    const shown = corrected(read, [AMT_TO_MU]);
    expect(shown.unlisted).toBeUndefined();
    expect(shown.doubted).toBeUndefined();
  });
});

describe("answered", () => {
  it("adds an answer", () => {
    expect(answered([], AMT_TO_MU)).toEqual([AMT_TO_MU]);
  });

  it("folds a second change of the same rows into the first", () => {
    const again = answered([AMT_TO_MU], {
      code: "MU",
      currency: "USD",
      symbol: "MTE.DE",
    });
    expect(again).toEqual([{ code: "AMT", currency: "USD", symbol: "MTE.DE" }]);
  });

  it("takes a change back when the reader names the code again", () => {
    expect(
      answered([AMT_TO_MU], { code: "MU", currency: "USD", symbol: "AMT" }),
    ).toEqual([]);
  });

  it("lets a confirmed ticker be changed after all", () => {
    const kept = { code: "AMT", currency: "USD", symbol: "AMT" };
    expect(answered([kept], AMT_TO_MU)).toEqual([AMT_TO_MU]);
  });

  it("keeps another currency's answer apart", () => {
    const euro = { code: "AMT", currency: "EUR", symbol: "MTE.DE" };
    expect(answered([euro], AMT_TO_MU)).toEqual([euro, AMT_TO_MU]);
  });
});

describe("changes", () => {
  it("lists the tickers that changed, not the ones confirmed", () => {
    const kept = { code: "NVDA", currency: "USD", symbol: "NVDA" };
    expect(changes([kept, AMT_TO_MU])).toEqual([AMT_TO_MU]);
  });
});
