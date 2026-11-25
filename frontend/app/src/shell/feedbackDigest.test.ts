import { describe, expect, it } from "vitest";

import { digestOf } from "./Feedback";

describe("digestOf", () => {
  it("names a file the way failed_files keeps it (sha256, 16 hex)", async () => {
    // Same bytes as tests/test_failed_files.py STATEMENT.
    const blob = new Blob(["date,ticker\n2025-01-02,ACME\n"]);
    expect(await digestOf(blob)).toBe("9d37262e7f242439");
  });
});
