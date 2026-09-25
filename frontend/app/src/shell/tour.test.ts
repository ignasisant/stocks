/**
 * Parking the tour, and the one interruption a first load gets.
 *
 * The rules worth a test are the ones that decide whether an account is
 * stamped: leaving to look at a feature must not mark a release as read, and
 * closing the guided tour must park it rather than end it — the two things the
 * shell used to get wrong (`web/onboarding.py` `_minimize`, `_news_park`).
 */

import { describe, expect, it } from "vitest";

import { firstLoad } from "./Tour";
import { after, clamp, readPark, writePark, type Place } from "./tourPark";
import { pinnedLang } from "./i18n";
import { bannerDismissed, dismissBanner } from "./guest";

function memory(): Storage {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
    clear: () => data.clear(),
    key: () => null,
    get length() {
      return data.size;
    },
  } as Storage;
}

const tour: Place = { mode: "tour", at: 3, open: true };
const news: Place = { mode: "news", at: 1, open: true };

describe("after", () => {
  it("parks the guided tour on X, without stamping", () => {
    expect(after(tour, "dismiss")).toEqual({
      place: { ...tour, open: false },
      stamp: null,
    });
  });

  it("parks either list on 'take me there', on the same item", () => {
    expect(after(tour, "goto")).toEqual({
      place: { ...tour, open: false },
      stamp: null,
    });
    // The rest of the release stays owed: no stamp.
    expect(after(news, "goto")).toEqual({
      place: { ...news, open: false },
      stamp: null,
    });
  });

  it("stamps what's new when it is closed — that is the way out", () => {
    expect(after(news, "dismiss")).toEqual({ place: null, stamp: {} });
    expect(after(news, "news_done")).toEqual({ place: null, stamp: {} });
  });

  it("retires the tour only when it is finished or ended", () => {
    expect(after(tour, "finish")).toEqual({ place: null, stamp: { done: true } });
  });
});

describe("the parked position", () => {
  it("round-trips through the tab's storage, and forgets", () => {
    const store = memory();
    writePark({ mode: "news", at: 2 }, store);
    expect(readPark(store)).toEqual({ mode: "news", at: 2 });
    writePark(null, store);
    expect(readPark(store)).toBeNull();
  });

  it("reads garbage as nothing parked", () => {
    const store = memory();
    store.setItem("tourParked", "{nope");
    expect(readPark(store)).toBeNull();
    store.setItem("tourParked", JSON.stringify({ mode: "other", at: 1 }));
    expect(readPark(store)).toBeNull();
  });

  it("clamps into a list that shrank since it was saved", () => {
    expect(clamp(9, 4)).toBe(3);
    expect(clamp(-1, 4)).toBe(0);
  });
});

describe("firstLoad", () => {
  const steps = [{}, {}, {}] as never[];
  const card = [{}] as never[];
  const modal = { surface: "modal", finished: true };

  it("brings a parked strip back instead of reopening at step one", () => {
    const out = firstLoad({ steps, news: [], tour_done: false }, modal, false, {
      mode: "tour",
      at: 2,
    });
    expect(out).toEqual({
      place: { mode: "tour", at: 2, open: false },
      interrupted: false,
    });
  });

  it("opens the tour for a newcomer, then what's new for one who finished", () => {
    expect(
      firstLoad({ steps, news: card, tour_done: false }, modal, false, null).place,
    ).toEqual({ mode: "tour", at: 0, open: true });
    expect(
      firstLoad({ steps, news: card, tour_done: true }, modal, false, null).place,
    ).toEqual({ mode: "news", at: 0, open: true });
  });

  it("never opens itself for a guest", () => {
    const out = firstLoad({ steps, news: card, tour_done: false }, modal, true, null);
    expect(out).toEqual({ place: null, interrupted: false, forget: false });
  });

  it("counts the conversational guide as the first load's interruption", () => {
    const out = firstLoad(
      { steps, news: card, tour_done: false },
      { surface: "chat", finished: false },
      false,
      null,
    );
    expect(out.place).toBeNull();
    expect(out.interrupted).toBe(true);
  });
});

describe("pinnedLang", () => {
  it("honours a landing CTA's ?lang= and keeps it for the tab", () => {
    const store = memory();
    expect(pinnedLang("?lang=es", store)).toBe("es");
    expect(pinnedLang("", store)).toBe("es");
  });

  it("ignores a language nobody ships", () => {
    expect(pinnedLang("?lang=xx", memory())).toBeNull();
  });
});

describe("the guest banner's dismiss", () => {
  it("is remembered per banner, for the tab", () => {
    const store = memory();
    expect(bannerDismissed("home", store)).toBe(false);
    dismissBanner("home", store);
    expect(bannerDismissed("home", store)).toBe(true);
    expect(bannerDismissed("portfolio", store)).toBe(false);
  });
});
