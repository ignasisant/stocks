/**
 * Opening the assistant after a while starts a new thread (`fresh.ts`).
 */

import { describe, expect, it } from "vitest";

import { IDLE_MS, TOPIC_MS, lastSeen, markSeen, onTopic, stale } from "./fresh";
import type { Conversation } from "./types";

const AT = Date.parse("2026-11-21T09:00:00Z");

function conv(over: Partial<Conversation> = {}): Conversation {
  return {
    id: "a",
    title: "Thread",
    title_auto: true,
    created: "2026-11-21T08:00:00+00:00",
    updated: "2026-11-21T09:00:00+00:00",
    messages: 4,
    active: true,
    ...over,
  };
}

function memory(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, v),
  };
}

describe("stale", () => {
  it("keeps a thread written on minutes ago", () => {
    expect(stale(conv(), 0, AT + 5 * 60_000)).toBe(false);
  });

  it("leaves a thread untouched since yesterday", () => {
    expect(stale(conv(), 0, AT + 24 * 3600_000)).toBe(true);
  });

  it("turns at the idle mark, not before", () => {
    expect(stale(conv(), 0, AT + IDLE_MS)).toBe(false);
    expect(stale(conv(), 0, AT + IDLE_MS + 1)).toBe(true);
  });

  it("counts the drawer open on it as being there", () => {
    const seen = AT + 3 * 3600_000;
    expect(stale(conv(), seen, seen + 60_000)).toBe(false);
    expect(stale(conv(), seen, seen + IDLE_MS + 1)).toBe(true);
  });

  it("never leaves an empty thread, one being answered, or the guide's", () => {
    const later = AT + 24 * 3600_000;
    expect(stale(conv({ messages: 0 }), 0, later)).toBe(false);
    expect(stale(conv({ answering: true }), 0, later)).toBe(false);
    expect(stale(conv(), 0, later, "a")).toBe(false);
    expect(stale(undefined, 0, later)).toBe(false);
  });

  it("reads an unparseable date as long ago", () => {
    expect(stale(conv({ updated: "" }), 0, AT)).toBe(true);
  });
});

describe("lastSeen", () => {
  it("is 0 before the drawer was ever closed, then what was marked", () => {
    const store = memory();
    expect(lastSeen(store)).toBe(0);
    markSeen(AT, store);
    expect(lastSeen(store)).toBe(AT);
  });

  it("survives storage that throws", () => {
    const broken = {
      getItem: () => {
        throw new Error("off");
      },
      setItem: () => {
        throw new Error("off");
      },
    } as unknown as Storage;
    expect(() => markSeen(AT, broken)).not.toThrow();
    expect(lastSeen(broken)).toBe(0);
  });
});

describe("onTopic", () => {
  const MIN = 60_000;
  const ago = (ms: number) => new Date(AT - ms).toISOString();
  const nvda = (over: Partial<Conversation> = {}) =>
    conv({ topics: ["ticker:NVDA"], ...over });

  it("continues the thread on screen when it is on the subject", () => {
    const list = [
      nvda({ id: "a", updated: ago(10 * MIN) }),
      nvda({ id: "b", updated: ago(MIN) }),
    ];
    expect(onTopic(list, "a", "ticker:NVDA", AT)).toBe("a");
  });

  it("opens the latest thread on the subject when the one on screen is not", () => {
    const list = [
      conv({ id: "a", topics: ["ticker:AMD"] }),
      nvda({ id: "b", updated: ago(40 * MIN) }),
      nvda({ id: "c", updated: ago(5 * MIN) }),
    ];
    expect(onTopic(list, "a", "ticker:NVDA", AT)).toBe("c");
  });

  it("starts a new one past the hour", () => {
    const list = [nvda({ id: "a", updated: ago(TOPIC_MS + MIN) })];
    expect(onTopic(list, "a", "ticker:NVDA", AT)).toBeNull();
  });

  it("does not count reading the thread on screen as using it", () => {
    const list = [nvda({ id: "a", updated: ago(3 * TOPIC_MS) })];
    expect(onTopic(list, "a", "ticker:NVDA", AT)).toBeNull();
  });

  it("goes under a thread whose first answer is still being written", () => {
    const list = [nvda({ id: "b", messages: 0, answering: true })];
    expect(onTopic(list, "a", "ticker:NVDA", AT)).toBe("b");
  });

  it("keeps a thread still being answered", () => {
    const list = [nvda({ id: "b", updated: ago(3 * TOPIC_MS), answering: true })];
    expect(onTopic(list, "a", "ticker:NVDA", AT)).toBe("b");
  });

  it("never picks an empty thread or one without the subject", () => {
    const list = [
      nvda({ id: "a", messages: 0 }),
      conv({ id: "b" }),
      conv({ id: "c", topics: ["plan"] }),
    ];
    expect(onTopic(list, "a", "ticker:NVDA", AT)).toBeNull();
  });
});
