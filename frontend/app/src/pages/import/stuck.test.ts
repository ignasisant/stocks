import { describe, expect, it } from "vitest";

import type { Outcome, Preview, Row } from "./api";
import { missed } from "./stuck";

const row = { row: 2, ticker: "ASML", duplicate: false } as unknown as Row;

function read(over: Partial<Preview> = {}): Outcome<Preview> {
  return {
    ok: true,
    value: {
      platform: "revolut",
      label: "Revolut",
      kind: "trades",
      unavailable: false,
      filename: "statement.csv",
      digest: "d",
      importable: [row, row],
      rejected: [],
      duplicates: 0,
      skipped: [],
      broker: "",
      needs_broker: false,
      ...over,
    },
  };
}

describe("missed", () => {
  it("is a reading that left nothing worth committing", () => {
    expect(missed(read())).toBe(false);
    expect(missed(read({ importable: [] }))).toBe(true);
    expect(missed(read({ importable: [row], rejected: [row, row] }))).toBe(true);
    expect(missed({ ok: false, refusal: { kind: "unreadable", detail: "" } })).toBe(
      true,
    );
    expect(missed({ ok: false, refusal: { kind: "too_large" } })).toBe(true);
  });

  it("is not a statement already in the book, a holdings report or a moved ledger", () => {
    const again = { ...row, duplicate: true } as Row;
    expect(missed(read({ importable: [again, again], duplicates: 2 }))).toBe(false);
    expect(
      missed(
        read({
          kind: "positions",
          importable: [],
          holdings: [{ row: 2, ticker: "ASML" }] as Preview["holdings"],
        }),
      ),
    ).toBe(false);
    expect(missed({ ok: false, refusal: { kind: "changed" } })).toBe(false);
    expect(missed(null)).toBe(false);
  });
});
