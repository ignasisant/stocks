import { describe, expect, it } from "vitest";

import { KEEP_MS } from "../shell/router";
import { forget, left, note, recall } from "./spot";

describe("thread spot", () => {
  it("puts a thread back where the reader was, with the same turns", () => {
    note("a", 420, 6, false, 1_000);
    left("a", 2_000);
    expect(recall("a", 6, 2_000 + KEEP_MS - 1)).toBe(420);
  });

  it("lands at the end once a turn came in since", () => {
    note("b", 420, 6, false, 1_000);
    expect(recall("b", 8, 1_500)).toBeNull();
    // Spent: the old spot is not found again either.
    expect(recall("b", 6, 1_600)).toBeNull();
  });

  it("counts the age from leaving, not from the last scroll", () => {
    note("c", 300, 4, false, 0);
    left("c", 10 * 60_000);
    expect(recall("c", 4, 10 * 60_000 + 30_000)).toBe(300);
    expect(recall("c", 4, 10 * 60_000 + KEEP_MS + 1)).toBeNull();
  });

  it("keeps no spot at the end, where a thread opens anyway", () => {
    note("d", 300, 4, false, 0);
    note("d", 900, 4, true, 10);
    expect(recall("d", 4, 20)).toBeNull();
  });

  it("forgets a thread opened to show its newest answer", () => {
    note("e", 300, 4, false, 0);
    forget("e");
    expect(recall("e", 4, 10)).toBeNull();
  });
});
