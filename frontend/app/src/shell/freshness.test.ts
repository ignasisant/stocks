import { afterEach, describe, expect, it, vi } from "vitest";
import {
  currentRetry,
  holdUrls,
  noteUpdating,
  updatingSince,
  keptSince,
  noteKept,
  noteRetry,
  onRetryStale,
  retryStale,
  isRefreshing,
  noteFreshness,
  noteRefreshing,
  resetFreshness,
  staleSince,
  subscribe,
} from "./freshness";

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

  it("keeps updating marks apart from stale ones", () => {
    noteUpdating("/a", "2026-09-27T10:00:00+00:00");
    expect(updatingSince()).toBe(Date.parse("2026-09-27T10:00:00+00:00"));
    expect(staleSince()).toBeNull();
    noteUpdating("/a", null);
    expect(updatingSince()).toBeNull();
  });

  it("drops a URL's marks once the last screen holding it lets go", () => {
    vi.useFakeTimers();
    try {
      noteFreshness("/a", "2026-09-27T10:00:00+00:00");
      noteUpdating("/b", "2026-09-27T10:00:00+00:00");
      const first = holdUrls(["/a", "/b"]);
      const second = holdUrls(["/a"]);
      first();
      vi.runAllTimers();
      expect(staleSince()).not.toBeNull(); // the second screen still shows /a
      expect(updatingSince()).toBeNull();
      second();
      vi.runAllTimers();
      expect(staleSince()).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("hands a URL over to the next screen asking for it", () => {
    vi.useFakeTimers();
    try {
      noteFreshness("/a", "2026-09-27T10:00:00+00:00");
      const left = holdUrls(["/a"]);
      left();
      holdUrls(["/a"]); // the next page mounts in the same commit
      vi.runAllTimers();
      expect(staleSince()).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
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

  it("marks a URL refreshing without a stale line, until an answer says otherwise", () => {
    noteRefreshing("/a", "1");
    expect(isRefreshing("/a")).toBe(true);
    expect(staleSince()).toBeNull();
    noteRefreshing("/a", null);
    expect(isRefreshing("/a")).toBe(false);
  });

  it("keeps the soonest retry, and says when one is out", () => {
    noteRetry("a", 30_000);
    noteRetry("b", 15_000);
    expect(currentRetry()).toEqual({ due: 15_000, asking: false });
    noteRetry("b", 0);
    expect(currentRetry()).toEqual({ due: 30_000, asking: true });
    noteRetry("a", null);
    noteRetry("b", null);
    expect(currentRetry()).toEqual({ due: null, asking: false });
  });

  it("marks the last visit's figures until the live ones land", () => {
    noteKept("a", 2_000);
    noteKept("b", 1_000);
    expect(keptSince()).toBe(1_000);
    noteKept("b", null);
    expect(keptSince()).toBe(2_000);
    noteKept("a", null);
    expect(keptSince()).toBeNull();
  });

  it("hands the stale line's press to every screen listening", () => {
    let heard = 0;
    const stop = onRetryStale(() => {
      heard += 1;
    });
    retryStale();
    stop();
    retryStale();
    expect(heard).toBe(1);
  });
});
