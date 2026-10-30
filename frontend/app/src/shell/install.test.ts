import { afterEach, describe, expect, it, vi } from "vitest";
import {
  VISIT_DAYS,
  _setDeferred,
  appleMobile,
  asked,
  install,
  installWay,
  iosSafari,
  markAsked,
  recordVisit,
  visitDays,
} from "./install";

function memory(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, String(value)),
  };
}

const broken = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
} as unknown as Storage;

const SAFARI_IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const CHROME_IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0 Mobile/15E148 Safari/604.1";
const IPAD_DESKTOP =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";

describe("which device", () => {
  it("reads an iPad asking for the desktop site as one, by its touchscreen", () => {
    expect(appleMobile(IPAD_DESKTOP, 5)).toBe(true);
    expect(appleMobile(IPAD_DESKTOP, 0)).toBe(false);
    expect(appleMobile(SAFARI_IPHONE, 5)).toBe(true);
  });

  it("offers the Share-sheet steps only in Safari itself", () => {
    expect(iosSafari(SAFARI_IPHONE, 5)).toBe(true);
    expect(iosSafari(CHROME_IPHONE, 5)).toBe(false);
    expect(iosSafari(`${SAFARI_IPHONE} Instagram 300.0`, 5)).toBe(false);
  });
});

describe("visits", () => {
  it("counts distinct days, not loads", () => {
    const store = memory();
    const day = (d: number) => new Date(2026, 9, d, 12);
    expect(recordVisit(day(1), store)).toBe(1);
    expect(recordVisit(day(1), store)).toBe(1);
    expect(recordVisit(day(2), store)).toBe(2);
    expect(recordVisit(day(5), store)).toBe(VISIT_DAYS);
    expect(visitDays(store)).toBe(VISIT_DAYS);
  });

  it("keeps only the last few days", () => {
    const store = memory();
    for (let d = 1; d <= 10; d++) recordVisit(new Date(2026, 9, d, 12), store);
    expect(visitDays(store)).toBe(VISIT_DAYS);
  });

  it("never reaches the threshold when storage throws", () => {
    expect(recordVisit(new Date(), broken)).toBe(0);
    expect(visitDays(broken)).toBe(0);
  });
});

describe("asked", () => {
  it("is remembered once marked", () => {
    const store = memory();
    expect(asked(store)).toBe(false);
    markAsked(store);
    expect(asked(store)).toBe(true);
  });

  it("reads a throwing store as already asked", () => {
    expect(asked(broken)).toBe(true);
    expect(() => markAsked(broken)).not.toThrow();
  });
});

describe("install", () => {
  afterEach(() => {
    _setDeferred(null);
    vi.unstubAllGlobals();
  });

  it("is nothing once the app runs standalone", () => {
    vi.stubGlobal("window", { matchMedia: () => ({ matches: true }) });
    _setDeferred(
      Object.assign(new Event("beforeinstallprompt"), {
        prompt: () => Promise.resolve(),
        userChoice: Promise.resolve({ outcome: "accepted" as const }),
      }),
    );
    expect(installWay()).toBeNull();
  });

  it("replays the kept event once and reports the choice", async () => {
    // A desktop Chrome tab: no iOS fallback once the event is spent.
    vi.stubGlobal("window", { matchMedia: () => ({ matches: false }) });
    vi.stubGlobal("navigator", { userAgent: "Chrome/130", maxTouchPoints: 0 });
    const prompt = vi.fn(() => Promise.resolve());
    _setDeferred(
      Object.assign(new Event("beforeinstallprompt"), {
        prompt,
        userChoice: Promise.resolve({ outcome: "accepted" as const }),
      }),
    );
    expect(installWay()).toBe("prompt");
    await expect(install()).resolves.toBe(true);
    expect(prompt).toHaveBeenCalledOnce();
    // Spent: the browser accepts `prompt()` once per event.
    expect(installWay()).toBeNull();
    await expect(install()).resolves.toBe(false);
  });
});
