import { describe, expect, it } from "vitest";

import {
  HOME_CARDS,
  defaultLayout,
  moveSlot,
  resolveLayout,
  sameLayout,
  toggleSlot,
  visibleCards,
  type CardSpec,
} from "./cards";

const ids = (slots: { id: string }[]) => slots.map((slot) => slot.id);

describe("resolveLayout", () => {
  it("is the registry's own order when nothing was saved", () => {
    expect(resolveLayout(null)).toEqual(defaultLayout());
    expect(resolveLayout([])).toEqual(defaultLayout());
    // The optional cards start in the tray, everything else on the page.
    const hidden = resolveLayout(null).filter((slot) => slot.hidden);
    expect(ids(hidden)).toEqual(["risk", "dividends", "tax", "rotation"]);
  });

  it("keeps the reader's order and drops what it no longer knows", () => {
    const stored = [
      { id: "watchlist", hidden: false },
      { id: "gone_card", hidden: false },
      { id: "daily", hidden: true },
      { id: "watchlist", hidden: true },
    ];
    const layout = resolveLayout(stored);
    // `market` was not in the save and has no predecessor, so it opens the
    // page; the stored ones keep their order after it.
    expect(layout.slice(0, 2)).toEqual([
      { id: "market", hidden: false },
      { id: "watchlist", hidden: false },
    ]);
    expect(ids(layout).indexOf("watchlist")).toBeLessThan(ids(layout).indexOf("daily"));
    expect(layout.find((slot) => slot.id === "daily")?.hidden).toBe(true);
    expect(layout.some((slot) => slot.id === "gone_card")).toBe(false);
    // Every registry card exactly once.
    expect([...ids(layout)].sort()).toEqual(ids([...HOME_CARDS]).sort());
  });

  it("puts a card shipped after the save where the default order would", () => {
    const registry: CardSpec[] = [
      { id: "market", span: "full", optional: false, signedIn: false },
      { id: "daily", span: "full", optional: false, signedIn: true },
      { id: "glance", span: "full", optional: false, signedIn: true },
      { id: "risk", span: "half", optional: true, signedIn: true },
    ];
    const stored = [
      { id: "glance", hidden: false },
      { id: "daily", hidden: false },
    ];
    // `market` has no predecessor and opens the page; `risk` follows `glance`,
    // which precedes it by default, and arrives hidden.
    expect(resolveLayout(stored, registry)).toEqual([
      { id: "market", hidden: false },
      { id: "glance", hidden: false },
      { id: "risk", hidden: true },
      { id: "daily", hidden: false },
    ]);
  });
});

describe("visibleCards", () => {
  it("leaves out hidden cards, and somebody's own data for a guest", () => {
    const layout = resolveLayout(null);
    const signed = visibleCards(layout, false).map((card) => card.id);
    expect(signed).toContain("daily");
    expect(signed).not.toContain("risk");
    const guest = visibleCards(layout, true).map((card) => card.id);
    expect(guest).toEqual(["market", "extremes", "earnings", "watchlist"]);
  });
});

describe("editing", () => {
  it("moves one slot and leaves the input alone", () => {
    const layout = defaultLayout();
    const moved = moveSlot(layout, 1, 0);
    expect(ids(moved).slice(0, 2)).toEqual(["daily", "market"]);
    expect(ids(layout).slice(0, 2)).toEqual(["market", "daily"]);
    expect(moveSlot(layout, 0, 99)).toEqual(layout);
  });

  it("hides in place and shows again after the last shown card", () => {
    const layout = defaultLayout();
    const hidden = toggleSlot(layout, "daily");
    expect(hidden.find((slot) => slot.id === "daily")?.hidden).toBe(true);
    const shown = toggleSlot(hidden, "risk");
    const order = ids(shown.filter((slot) => !slot.hidden));
    expect(order[order.length - 1]).toBe("risk");
  });

  it("tells an unchanged layout from a changed one", () => {
    const layout = defaultLayout();
    expect(sameLayout(layout, defaultLayout())).toBe(true);
    expect(sameLayout(layout, toggleSlot(layout, "daily"))).toBe(false);
  });
});
