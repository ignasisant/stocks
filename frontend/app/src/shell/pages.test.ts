/**
 * The page registry resolves the URLs this app inherited, not just its own.
 *
 * `pageFor` falls back to Home for anything it does not recognise, which is
 * right for a typo and wrong for a bookmark: two of the paths old links carry
 * do not match its slugs — Home is served at the root, and Import at
 * `import_transactions`. Without the aliases both of those load the dashboard
 * and look like they worked.
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

  it("resolves the old paths links still carry", () => {
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
    // The menu has it (`stocks.navigation.DESTINATIONS`); without a symbol it
    // opens on its own picker.
    expect(pageFor("ticker").hidden).toBeFalsy();
    expect(pageFor("ticker").section).toBe("nav.section_market");
  });

  it("groups the rail the way the navigation table does", () => {
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

  it("puts bank in the Account group for a reader allowed to use it", () => {
    // The rail is drawn before anyone knows who is reading, so hidden is the
    // default; `/me` saying this account is on the allowlist is what reveals
    // it, and it belongs under Account rather than as a group of its own.
    const account = sections(undefined, ["bank"]).find(
      (group) => group.section === "nav.section_account",
    );
    expect(account!.pages.map((page) => page.slug)).toContain("bank");
    expect(
      sections()
        .flatMap((group) => group.pages)
        .map((page) => page.slug),
    ).not.toContain("bank");
  });

  it("reveals nothing a reader was not named for", () => {
    // Revealing is per slug, not a switch that opens every hidden page.
    expect(
      sections(undefined, ["nope"])
        .flatMap((group) => group.pages)
        .map((page) => page.slug),
    ).not.toContain("bank");
  });
});
