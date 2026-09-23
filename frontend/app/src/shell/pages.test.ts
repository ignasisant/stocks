/**
 * The page registry resolves the URLs this app inherited, not just its own.
 *
 * `pageFor` falls back to Home for anything it does not recognise, which is
 * right for a typo and wrong for a bookmark: two of the Streamlit paths this
 * shell replaces do not match its slugs — Home is served at the root, and
 * Import is `import_transactions` because Streamlit derives a page's URL from
 * its filename. Without the aliases both of those load the dashboard and look
 * like they worked.
 *
 * `tests/test_frontend_nav_parity.py` checks the same thing from the other
 * side, against `stocks.navigation`. This one checks the resolution itself.
 */

import { describe, expect, it } from "vitest";

import { PAGES, canonical, pageFor } from "./pages";

describe("the page registry", () => {
  it("resolves a slug to its own page", () => {
    for (const page of PAGES) {
      expect(pageFor(page.slug).slug).toBe(page.slug);
    }
  });

  it("resolves the Streamlit URL each page replaced", () => {
    expect(canonical("import_transactions")).toBe("import");
    expect(canonical("")).toBe("home");
  });

  it("does not let an alias shadow a real slug", () => {
    const claimed = PAGES.flatMap((page) => [page.slug, ...(page.aliases ?? [])]);
    expect(new Set(claimed).size).toBe(claimed.length);
  });

  it("falls back to the first page for something it has never heard of", () => {
    expect(pageFor("nope").slug).toBe(PAGES[0]!.slug);
  });

  it("keeps the ticker page out of the rail", () => {
    // Reached from a ticker cell, not from the menu — it has no place in a
    // list of sections and would be the only entry with no section.
    expect(pageFor("ticker").hidden).toBe(true);
  });
});
