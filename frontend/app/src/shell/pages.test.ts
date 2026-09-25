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

import { PAGES, canonical, pageFor, sections } from "./pages";

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

  it("lists the ticker page in the rail, under Market", () => {
    // The Streamlit menu has it (`stocks.navigation.DESTINATIONS`); without a
    // symbol it opens on its own picker.
    expect(pageFor("ticker").hidden).toBeFalsy();
    expect(pageFor("ticker").section).toBe("nav.section_market");
  });

  it("groups the rail the way the Streamlit menu does", () => {
    // `stocks.navigation.sections()`: Home alone with no header, then
    // Portfolio, Market and Account — in that order, bank left out.
    expect(sections().map((group) => group.section)).toEqual([
      undefined,
      "nav.section_portfolio",
      "nav.section_market",
      "nav.section_account",
    ]);
    expect(sections()[2]!.pages.map((page) => page.slug)).toEqual([
      "ticker",
      "sentiment",
      "sector",
      "earnings",
    ]);
    expect(
      sections()
        .flatMap((group) => group.pages)
        .some((p) => p.hidden),
    ).toBe(false);
  });
});
