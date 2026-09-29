import { afterEach, describe, expect, it } from "vitest";
import { noteFreshness, resetFreshness, staleSince, subscribe } from "./freshness";

describe("freshness", () => {
  afterEach(resetFreshness);

  it("keeps the oldest mark across URLs and clears it when the source is back", () => {
    noteFreshness("/a", "2026-09-27T10:00:00+00:00");
    noteFreshness("/b", "2026-09-26T10:00:00+00:00");
    expect(staleSince()).toBe(Date.parse("2026-09-26T10:00:00+00:00"));
    noteFreshness("/b", null);
    expect(staleSince()).toBe(Date.parse("2026-09-27T10:00:00+00:00"));
    noteFreshness("/a", null);
    expect(staleSince()).toBeNull();
  });

  it("ignores a header it cannot read", () => {
    noteFreshness("/a", "yesterday-ish");
    expect(staleSince()).toBeNull();
  });

  it("tells subscribers only when the answer changes", () => {
    let told = 0;
    const off = subscribe(() => {
      told += 1;
    });
    noteFreshness("/a", "2026-09-27T10:00:00+00:00");
    noteFreshness("/a", "2026-09-27T10:00:00+00:00");
    noteFreshness("/c", "2026-09-28T10:00:00+00:00"); // newer: the oldest stands
    expect(told).toBe(1);
    off();
  });
});
