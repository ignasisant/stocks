/**
 * What a URL means, including the bookmarks this app inherited.
 *
 * `routeFor` is the pure half of the router: the redirects that would hurt if
 * they were wrong are the old `/?ticker=SYM` links, which Streamlit served from
 * any page and which live on in bookmarks and old digests.
 */

import { describe, expect, it } from "vitest";

import { routeFor } from "./router";

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
