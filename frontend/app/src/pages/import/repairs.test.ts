import { describe, expect, it } from "vitest";

import { isDemo, namedBy } from "./api";
import type { Move, SplitGap } from "./api";
import { pastedFile } from "./paste";
import { moveKey, names, ratioLabel, splitKey } from "./repairs";

function gap(fields: Partial<SplitGap>): SplitGap {
  return {
    ticker: "NVDA",
    date: "2024-06-10",
    ratio: 10,
    held_before: 40,
    held_after: 400,
    priced_at: 131.1,
    priced_on: "2024-05-02",
    market_close: 13.11,
    currency: "USD",
    ...fields,
  };
}

function move(fields: Partial<Move>): Move {
  return {
    ticker_out: "US0378331005",
    ticker_in: "AAPL",
    quantity: 20,
    broker_out: "degiro",
    broker_in: "revolut",
    date_out: "2025-02-03",
    date_in: "2025-02-07",
    booked_at: 230.5,
    basis_out: 173.2,
    basis_in: 173.2,
    phantom_gain: 1146,
    currency: "USD",
    rekey: true,
    out_ids: [12, 9],
    in_id: 31,
    ...fields,
  };
}

describe("naming a proposal", () => {
  it("names a split by the two fields the apply route takes", () => {
    expect(splitKey(gap({}))).toBe("NVDA|2024-06-10");
    // One ticker, two splits: the reader can believe one and not the other.
    expect(splitKey(gap({ date: "2021-07-20" }))).not.toBe(splitKey(gap({})));
  });

  it("names a move by its ledger ids, order-independently", () => {
    // The scan is free to return them in any order; the same move must not read
    // as two different proposals when it does.
    expect(moveKey(move({ out_ids: [9, 12] }))).toBe(
      moveKey(move({ out_ids: [12, 9] })),
    );
    // Two equal parcels leaving the same broker on the same day differ in
    // nothing but these ids, which is why they and not the ticker are the name.
    expect(moveKey(move({ out_ids: [13] }))).not.toBe(moveKey(move({ out_ids: [12] })));
    expect(moveKey(move({ in_id: null }))).not.toBe(moveKey(move({ in_id: 31 })));
  });
});

describe("the ratio", () => {
  it("prints whole and fractional ratios as the page always has", () => {
    expect(ratioLabel(20)).toBe("20:1");
    expect(ratioLabel(1.5)).toBe("1.5:1");
  });
});

describe("a typed confirmation", () => {
  const email = "reader@example.com";

  it("arms only on the address, however it was typed", () => {
    expect(names(" Reader@Example.com ", email)).toBe(true);
    expect(names("reader@example.co", email)).toBe(false);
  });

  it("never arms when there is no address to match", () => {
    // A token session has no email, and an empty box must not read as one.
    expect(names("", "")).toBe(false);
  });
});

describe("rows that were never real", () => {
  it("reads the demo mark the way the ledger writes it", () => {
    expect(isDemo("demo Apple")).toBe(true);
    expect(isDemo("Demo")).toBe(true);
    expect(isDemo("demonstration account")).toBe(false);
    expect(isDemo("revolut AAPL")).toBe(false);
    expect(isDemo("")).toBe(false);
  });
});

describe("the example statement's own name", () => {
  it("takes the filename the server put in the header", () => {
    // The extension picks the branch inside a parser, so this is not cosmetic.
    expect(namedBy('attachment; filename="revolut_sample.csv"')).toBe(
      "revolut_sample.csv",
    );
    expect(namedBy("attachment; filename=statement.pdf")).toBe("statement.pdf");
  });

  it("says so when the response named nothing", () => {
    expect(namedBy(null)).toBe(null);
    expect(namedBy("attachment")).toBe(null);
  });
});

describe("a pasted statement", () => {
  const CSV = "Type,Product,Started Date\nBUY - MARKET,AAPL,2024-03-12";

  /** `btoa` over bytes, the way `base64 -i file | pbcopy` produces them. */
  const b64 = (bytes: number[], padTo: number) =>
    btoa(String.fromCharCode(...bytes) + "A".repeat(Math.max(0, padTo - bytes.length)));

  it("takes plain text as the CSV it is", () => {
    const file = pastedFile(CSV, ["csv"]);
    expect("wrong" in file).toBe(false);
    if (!("wrong" in file)) expect(file.filename).toBe("pasted.csv");
  });

  it("does not mistake a short all-letters CSV for base64", () => {
    const file = pastedFile("date,ticker\nabcd,AAPL", ["csv", "pdf"]);
    if (!("wrong" in file)) expect(file.filename).toBe("pasted.csv");
  });

  it("names a base64 PDF by its magic bytes, not by what it is called", () => {
    const file = pastedFile(b64([0x25, 0x50, 0x44, 0x46], 96), ["csv", "pdf"]);
    expect("wrong" in file).toBe(false);
    if (!("wrong" in file)) expect(file.filename).toBe("pasted.pdf");
  });

  it("refuses a format this platform has no parser for", () => {
    // A PDF pasted at the generic CSV importer: named here rather than failing
    // deep inside a parser that reads only text.
    expect(pastedFile(b64([0x25, 0x50, 0x44, 0x46], 96), ["csv"])).toEqual({
      wrong: "pdf",
    });
    expect(pastedFile(b64([0x50, 0x4b, 0x03, 0x04], 96), ["csv", "pdf"])).toEqual({
      wrong: "xlsx",
    });
  });
});
