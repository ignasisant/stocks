/**
 * The tabs over a wide drawer (`strip.ts`): which ids are on the strip, which
 * one goes past the cap, and where closing the open one lands.
 */

import { describe, expect, it } from "vitest";

import { MAX_TABS, close, fit } from "./strip";
import type { Conversation } from "./types";

function conv(id: string, answering = false): Conversation {
  return {
    id,
    title: `Thread ${id}`,
    title_auto: true,
    created: "2026-10-30T09:00:00Z",
    updated: "2026-10-30T09:00:00Z",
    messages: 2,
    active: false,
    answering,
  };
}

describe("the strip", () => {
  it("puts the thread on screen on the end, once", () => {
    const list = [conv("a"), conv("b")];
    expect(fit(["a"], "b", list)).toEqual(["a", "b"]);
    expect(fit(["a", "b"], "a", list)).toEqual(["a", "b"]);
  });

  it("drops ids the account does not have, but never the one on screen", () => {
    // "n" was just created: active before the list has caught up with it.
    expect(fit(["a", "gone"], "n", [conv("a")])).toEqual(["a", "n"]);
  });

  it("prunes nothing before the list has loaded", () => {
    expect(fit(["a", "b"], "c", null)).toEqual(["a", "b", "c"]);
  });

  it("lets the leftmost go past the cap, unless it is still answering", () => {
    const ids = Array.from({ length: MAX_TABS }, (_, n) => `t${n}`);
    const list = [...ids.map((id) => conv(id, id === "t0")), conv("new")];
    expect(fit(ids, "new", list)).toEqual([...ids.filter((id) => id !== "t1"), "new"]);
  });
});

describe("closing a tab", () => {
  it("moves nobody when it is not the open one", () => {
    expect(close(["a", "b", "c"], "a", "b")).toEqual({ tabs: ["b", "c"], open: null });
  });

  it("opens the tab to the right of the open one, else the one to its left", () => {
    expect(close(["a", "b", "c"], "b", "b")).toEqual({ tabs: ["a", "c"], open: "c" });
    expect(close(["a", "b", "c"], "c", "c")).toEqual({ tabs: ["a", "b"], open: "b" });
  });
});
