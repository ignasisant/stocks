/** One pull, every screen: the reload waits for the slowest one to land. */

import { afterEach, describe, expect, it, vi } from "vitest";

import { isStandalone, onReloadAll, reloadAll } from "./resume";

const tab = (matches: boolean) =>
  vi.stubGlobal("window", { matchMedia: () => ({ matches }) });

afterEach(() => vi.unstubAllGlobals());

describe("reloadAll", () => {
  it("resolves with nothing listening", async () => {
    await expect(reloadAll()).resolves.toBeUndefined();
  });

  it("asks every screen and waits for the last one", async () => {
    const asked: string[] = [];
    let finish = () => {};
    const off = [
      onReloadAll(async () => {
        asked.push("book");
      }),
      onReloadAll(
        () =>
          new Promise<void>((resolve) => {
            asked.push("chart");
            finish = resolve;
          }),
      ),
    ];
    let done = false;
    const reload = reloadAll().then(() => {
      done = true;
    });
    await Promise.resolve();
    expect(asked).toEqual(["book", "chart"]);
    expect(done).toBe(false);
    finish();
    await reload;
    expect(done).toBe(true);
    off.forEach((stop) => stop());
  });

  it("forgets a screen that left", async () => {
    const listener = vi.fn(async () => {});
    onReloadAll(listener)();
    await reloadAll();
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("isStandalone", () => {
  it("is false in a browser tab", () => {
    tab(false);
    expect(isStandalone()).toBe(false);
  });

  it("reads the display mode, or iOS's own flag", () => {
    tab(true);
    expect(isStandalone()).toBe(true);
    tab(false);
    vi.stubGlobal("navigator", { standalone: true });
    expect(isStandalone()).toBe(true);
  });
});
