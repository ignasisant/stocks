/**
 * Saving the chat's plan draft changes what Profile, Review and the plan
 * route serve, so that press drops their cached answers; nothing else does.
 */

import { describe, expect, it } from "vitest";

import { savesPlan } from "./api";

const press = (surfaceId: string, name: string) => ({
  surfaceId,
  name,
  sourceComponentId: name,
  timestamp: "2026-10-30T10:00:00Z",
  context: {},
});

describe("a plan builder press", () => {
  it("forgets the plan's pages only on save", () => {
    expect(savesPlan(press("plan_builder", "save"))).toBe(true);
    expect(savesPlan(press("plan_builder", "draft"))).toBe(false);
    expect(savesPlan(press("rebalance", "save"))).toBe(false);
  });
});
