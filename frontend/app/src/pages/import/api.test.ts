import { afterEach, describe, expect, it, vi } from "vitest";

import { acceptOf, nameOf, reportUnreadable } from "./api";

const KINDS = ["csv", "pdf", "xlsx"];

describe("acceptOf", () => {
  it("offers a CSV under every type it is saved as, not only its extension", () => {
    const accept = acceptOf(KINDS).split(",");
    expect(accept).toEqual(expect.arrayContaining([".csv", ".pdf", ".xlsx"]));
    // `text/csv` is the one that matters: Chrome on Android asks the picker
    // for `text/comma-separated-values` when told `.csv`, and a DEGIRO
    // download saved as `text/csv` came up greyed out.
    expect(accept).toEqual(
      expect.arrayContaining([
        "text/csv",
        "text/comma-separated-values",
        "application/vnd.ms-excel",
      ]),
    );
  });

  it("keeps an extension it has no types for", () => {
    expect(acceptOf(["ofx"])).toBe(".ofx");
  });
});

describe("nameOf", () => {
  it("leaves a named file alone", () => {
    expect(nameOf(new File(["x"], "Revolut.csv", { type: "text/csv" }), KINDS)).toBe(
      "Revolut.csv",
    );
  });

  it("gives a file shared without an extension the one its type says", () => {
    const shared = new File(["x"], "statement 2026", {
      type: "text/comma-separated-values",
    });
    expect(nameOf(shared, KINDS)).toBe("statement 2026.csv");
  });

  it("does not rename an extension nothing reads", () => {
    const old = new File(["x"], "book.xls", { type: "application/vnd.ms-excel" });
    expect(nameOf(old, KINDS)).toBe("book.xls");
  });
});

describe("reportUnreadable", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the browser's error and never throws when the report fails", async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError("offline"));
    vi.stubGlobal("fetch", fetch);
    const failure = { name: "NotReadableError", message: "could not be read" };
    reportUnreadable("revolut", "Revolut.csv", new Blob(["abc"]), failure);
    await Promise.resolve();
    const [path, init] = fetch.mock.calls[0]!;
    expect(String(path)).toContain("/import/client-failure");
    expect(JSON.parse(init.body)).toEqual({
      platform: "revolut",
      filename: "Revolut.csv",
      bytes: 3,
      error: "NotReadableError",
      message: "could not be read",
    });
  });
});
