/**
 * The vitals report: one per page load, final values only, with what the
 * numbers were measured against.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

/** The callbacks `watchVitals` hands the library, by metric. */
const listeners = vi.hoisted(() => new Map<string, (metric: unknown) => void>());

vi.mock("web-vitals", () => ({
  onTTFB: (report: (metric: unknown) => void) => listeners.set("TTFB", report),
  onLCP: (report: (metric: unknown) => void) => listeners.set("LCP", report),
  onCLS: (report: (metric: unknown) => void) => listeners.set("CLS", report),
  onINP: (report: (metric: unknown) => void) => listeners.set("INP", report),
}));

import { _reset, flush, watchVitals } from "./vitals";

function browser(pathname: string) {
  const posts: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", (url: string, init: { body: string }) => {
    posts.push({ url, body: JSON.parse(init.body) });
    return Promise.resolve({});
  });
  vi.stubGlobal("window", {
    location: { pathname },
    addEventListener: () => undefined,
  });
  vi.stubGlobal("document", { addEventListener: () => undefined });
  vi.stubGlobal("performance", { getEntriesByType: () => [{ type: "reload" }] });
  return posts;
}

afterEach(() => {
  vi.unstubAllGlobals();
  listeners.clear();
  _reset();
});

describe("the vitals report", () => {
  it("goes out once, with each metric's last value, against the page it measured", () => {
    const posts = browser("/portfolio/");
    watchVitals();
    listeners.get("LCP")!({ name: "LCP", value: 1234.56789, rating: "good" });
    // The library reports a metric again as it grows; the last word counts.
    listeners.get("LCP")!({ name: "LCP", value: 1300.1, rating: "needs-improvement" });
    listeners.get("CLS")!({ name: "CLS", value: 0.012345678, rating: "good" });
    flush();
    flush();
    expect(posts).toHaveLength(1);
    expect(posts[0]!.url.endsWith("/vitals")).toBe(true);
    expect(posts[0]!.body).toEqual({
      metrics: [
        { name: "LCP", value: 1300.1, rating: "needs-improvement" },
        { name: "CLS", value: 0.0123, rating: "good" },
      ],
      where: "portfolio",
      nav: "reload",
      kept: false,
    });
  });

  it("sends nothing when nothing was measured", () => {
    const posts = browser("/");
    watchVitals();
    flush();
    expect(posts).toHaveLength(0);
  });
});
