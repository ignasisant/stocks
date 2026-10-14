/**
 * What a URL means, including the bookmarks this app inherited.
 *
 * `routeFor` is the pure half of the router: the redirects that would hurt if
 * they were wrong are the old `/?ticker=SYM` links, which the old app served
 * from any page and which live on in bookmarks and old digests.
 */

import { describe, expect, it, vi } from "vitest";

import { depth, push, routeFor } from "./router";

describe("routeFor", () => {
  it("opens the page the path names", () => {
    expect(routeFor("portfolio", "?tab=fees").page).toBe("portfolio");
    expect(routeFor("", "").page).toBe("home");
  });

  it("sends an old ?ticker= bookmark to the ticker page, from any page", () => {
    expect(routeFor("", "?ticker=ASML.AS").page).toBe("ticker");
    expect(routeFor("earnings", "?ticker=AAPL").page).toBe("ticker");
    expect(routeFor("", "?ticker=ASML.AS").params.get("ticker")).toBe("ASML.AS");
  });

  it("does not jump for an empty ticker", () => {
    expect(routeFor("sector", "?ticker=").page).toBe("sector");
  });
});

describe("depth", () => {
  it("counts the in-app steps a visit has taken, from history's own state", () => {
    let state: unknown = null;
    vi.stubGlobal("window", {
      history: {
        get state() {
          return state;
        },
        pushState: (next: unknown) => {
          state = next;
        },
      },
    });
    try {
      expect(depth()).toBe(0);
      push("/app/portfolio");
      push("/app/ticker?ticker=AAPL");
      expect(depth()).toBe(2);
      state = { depth: 1 }; // the browser's back button
      expect(depth()).toBe(1);
      state = { other: true };
      expect(depth()).toBe(0);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
