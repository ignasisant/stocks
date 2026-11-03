/**
 * The decision `useInView` makes on first render — the one a server render or
 * a test can see. Where the viewport can be watched a slot starts as a
 * placeholder unless marked eager; where it cannot, everything is drawn at
 * once rather than left blank.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { canObserve, covered, useInView } from "./useInView";

function Probe({ eager }: { eager?: boolean }) {
  const [ref, seen] = useInView<HTMLDivElement>(eager);
  return <div ref={ref}>{seen ? "card" : "placeholder"}</div>;
}

class StillObserver {
  observe() {}
  disconnect() {}
}

afterEach(() => vi.unstubAllGlobals());

describe("useInView", () => {
  it("starts as a placeholder where the viewport can be watched", () => {
    vi.stubGlobal("IntersectionObserver", StillObserver);
    expect(canObserve()).toBe(true);
    expect(renderToStaticMarkup(<Probe />)).toContain("placeholder");
  });

  it("draws an eager slot from the first frame", () => {
    vi.stubGlobal("IntersectionObserver", StillObserver);
    expect(renderToStaticMarkup(<Probe eager />)).toContain("card");
  });

  it("holds even an eager slot while the assistant covers a phone's page", () => {
    vi.stubGlobal("IntersectionObserver", StillObserver);
    vi.stubGlobal("document", { documentElement: { dataset: { chat: "overlay" } } });
    vi.stubGlobal("window", { matchMedia: () => ({ matches: true }) });
    expect(covered()).toBe(true);
    expect(renderToStaticMarkup(<Probe eager />)).toContain("placeholder");
  });

  it("does not hold a slot beside a drawer that leaves the page on screen", () => {
    vi.stubGlobal("IntersectionObserver", StillObserver);
    vi.stubGlobal("document", { documentElement: { dataset: { chat: "open" } } });
    vi.stubGlobal("window", { matchMedia: () => ({ matches: false }) });
    expect(covered()).toBe(false);
    expect(renderToStaticMarkup(<Probe eager />)).toContain("card");
  });

  it("draws everything where nothing can watch the viewport", () => {
    expect(canObserve()).toBe(false);
    expect(renderToStaticMarkup(<Probe />)).toContain("card");
  });
});
