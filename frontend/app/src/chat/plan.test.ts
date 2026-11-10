/**
 * Saving the chat's plan draft or entry checklist changes what Profile,
 * Review, the ticker page and the plan route serve, so those presses drop
 * their cached answers; nothing else does.
 */

import { describe, expect, it } from "vitest";

import { touched } from "./api";

const press = (surfaceId: string, name: string) => ({
  surfaceId,
  name,
  sourceComponentId: name,
  timestamp: "2026-10-30T10:00:00Z",
  context: {},
});

describe("a builder press", () => {
  it("forgets the plan's pages only on save", () => {
    expect(touched(press("plan_builder", "save"))).toEqual([
      "/plan",
      "/profile",
      "/review",
    ]);
    expect(touched(press("plan_builder", "draft"))).toEqual([]);
    expect(touched(press("rebalance", "save"))).toEqual([]);
  });

  it("forgets what reads the entry checklist when it is saved", () => {
    expect(touched(press("entry_builder", "save"))).toEqual([
      "/plan",
      "/review",
      "/ticker",
    ]);
  });
});
