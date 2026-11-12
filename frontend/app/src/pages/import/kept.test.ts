import { beforeEach, describe, expect, it } from "vitest";
import type { Outcome, Preview, Staged } from "./api";
import { fixesOf, forget, keep, keepFixes, preview, restored } from "./kept";
import { NO_WIPE } from "./Wipe";

const statement = (filename: string): Staged => ({ filename, content: "", bytes: 1 });
const answer = { ok: true, value: {} } as Outcome<Preview>;

function counted() {
  let asked = 0;
  const ask = () => {
    asked += 1;
    return Promise.resolve(answer);
  };
  return { ask, asked: () => asked };
}

describe("the kept statement", () => {
  beforeEach(() => keep(null, NO_WIPE, ""));

  it("is read back as it was left", () => {
    const staged = statement("a.pdf");
    keep(staged, NO_WIPE, "revolut");
    expect(restored()?.staged).toBe(staged);
    expect(restored()?.platform).toBe("revolut");
    keep(null, NO_WIPE, "revolut");
    expect(restored()).toBeNull();
  });

  it("asks the model once per statement, platform and wipe", async () => {
    const staged = statement("a.pdf");
    keep(staged, NO_WIPE, "revolut");
    const { ask, asked } = counted();
    await preview("revolut", staged, false, ask);
    await preview("revolut", staged, false, ask);
    expect(asked()).toBe(1);
    await preview("revolut", staged, true, ask);
    await preview("trading212", staged, true, ask);
    expect(asked()).toBe(3);
  });

  it("asks again after a write, and for another statement", async () => {
    const staged = statement("a.pdf");
    keep(staged, NO_WIPE, "revolut");
    const { ask, asked } = counted();
    await preview("revolut", staged, false, ask);
    forget();
    await preview("revolut", staged, false, ask);
    expect(asked()).toBe(2);
    const other = statement("b.pdf");
    keep(other, NO_WIPE, "revolut");
    await preview("revolut", other, false, ask);
    expect(asked()).toBe(3);
  });

  it("does not keep a failure", async () => {
    const staged = statement("a.pdf");
    keep(staged, NO_WIPE, "revolut");
    await expect(
      preview("revolut", staged, false, () => Promise.reject(new Error("down"))),
    ).rejects.toThrow("down");
    const { ask, asked } = counted();
    await preview("revolut", staged, false, ask);
    expect(asked()).toBe(1);
  });

  it("keeps the reader's ticker fixes for the reading they were made on", () => {
    const staged = statement("a.pdf");
    const fix = { code: "AMT", currency: "USD", symbol: "MU" };
    keepFixes("d:llm", [fix]);
    expect(fixesOf("d:llm")).toEqual([]);
    keep(staged, NO_WIPE, "auto");
    keepFixes("d:llm", [fix]);
    // A write asks the preview again; the same bytes read to the same names.
    forget();
    keep(staged, { ...NO_WIPE }, "auto");
    expect(fixesOf("d:llm")).toEqual([fix]);
    expect(fixesOf("d:revolut")).toEqual([]);
    keep(statement("b.pdf"), NO_WIPE, "auto");
    expect(fixesOf("d:llm")).toEqual([]);
  });

  it("shares an answer still on its way", async () => {
    const staged = statement("a.pdf");
    keep(staged, NO_WIPE, "revolut");
    const { ask, asked } = counted();
    const first = preview("revolut", staged, false, ask);
    const second = preview("revolut", staged, false, ask);
    expect(second).toBe(first);
    expect(asked()).toBe(1);
  });
});
