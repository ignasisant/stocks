/**
 * The page registry: one entry per screen, and the only place that knows them.
 *
 * `slug` is the URL segment. Where it differs from the Streamlit page's own
 * `url_path`, the old path is listed in `aliases` and resolves to the same
 * page: every bookmark and every shared link has to keep working across the
 * migration, and two of them do not match (Home is served at the root, and
 * Import is `import_transactions` because Streamlit derives a page's URL from
 * its filename). `tests/test_frontend_nav_parity.py` checks that every path
 * `stocks.navigation` ships is reachable here, so a page renamed on one side
 * and not the other fails a test instead of silently landing on Home.
 *
 * `label` is an i18n key, never a string: the nav renders in two languages.
 *
 * Each page is imported lazily so opening Home does not download the tax
 * engine's tables. The shell is the entry and is always paid for; a page is
 * paid for when it is opened.
 *
 * Every entry file is named after its page rather than `Page.tsx`. Rollup names
 * a chunk (and the stylesheet it pulls in) after the module that produced it,
 * so eight files called `Page` ship as Page.js, Page2.js, Page3.js — unreadable
 * in a network tab, and a set of names that silently renumber when one page is
 * added.
 */

import { lazy, type LazyExoticComponent } from "react";

export type Page = {
  slug: string;
  label: string;
  icon: string;
  component: LazyExoticComponent<() => React.ReactNode>;
  /** Paths that also mean this page — the Streamlit URL it is replacing. */
  aliases?: string[];
  /** Hidden from the nav — reachable by URL only (the bank's allowlist). */
  hidden?: boolean;
  /**
   * The i18n key of the rail group this page sits under — the `section` of its
   * `stocks.navigation.DESTINATIONS` entry. Absent is the top group (Home),
   * which Streamlit draws with no header at all.
   */
  section?: string;
};

export const PAGES: Page[] = [
  {
    slug: "home",
    label: "nav.home",
    icon: "home",
    component: lazy(() => import("../pages/home/Home")),
    // Streamlit serves the default page at the root; `read()` in the router
    // already turns an empty path into this slug, and the alias is here so the
    // parity check can see that "" is covered.
    aliases: [""],
  },
  {
    slug: "portfolio",
    label: "nav.portfolio",
    section: "nav.section_portfolio",
    icon: "pie_chart",
    component: lazy(() => import("../pages/portfolio/Portfolio")),
  },
  {
    slug: "import",
    label: "nav.import",
    section: "nav.section_portfolio",
    icon: "upload_file",
    component: lazy(() => import("../pages/import/Import")),
    aliases: ["import_transactions"],
  },
  {
    slug: "ticker",
    label: "nav.ticker",
    section: "nav.section_market",
    icon: "query_stats",
    component: lazy(() => import("../pages/ticker/Ticker")),
    // In the rail, as it is in the Streamlit menu: without a ticker the page
    // opens on its own picker, which is a destination in its own right — and
    // hiding it left a reader with no way to look a symbol up except the
    // search box.
  },
  {
    slug: "sentiment",
    label: "nav.sentiment",
    section: "nav.section_market",
    icon: "speed",
    component: lazy(() => import("../pages/sentiment/Sentiment")),
  },
  {
    slug: "sector",
    label: "nav.sector",
    section: "nav.section_market",
    icon: "donut_small",
    component: lazy(() => import("../pages/sector/Sector")),
  },
  {
    slug: "earnings",
    label: "nav.earnings",
    section: "nav.section_market",
    icon: "calendar_month",
    component: lazy(() => import("../pages/earnings/Earnings")),
  },
  {
    slug: "profile",
    label: "nav.profile",
    section: "nav.section_account",
    icon: "account_circle",
    component: lazy(() => import("../pages/profile/Profile")),
  },
  {
    slug: "bank",
    label: "nav.bank",
    section: "nav.section_account",
    icon: "account_balance",
    component: lazy(() => import("../pages/bank/Bank")),
    // Hidden for the same reason the Streamlit page is absent from
    // `st.navigation`: the feature is an allowlist that fails closed, and a
    // rail entry every account can see would be one most of them cannot use.
    // It is reachable by URL — which is what the bank's redirect needs it to
    // be — and the day the allowlist widens, this line is the whole change.
    hidden: true,
  },
];

/**
 * The phone tab bar's four, by slug — `stocks.navigation.BOTTOM_NAV`, which is
 * what the DS mobile spec fits in a 360px row with legible labels. Every other
 * rail entry is behind the bar's "More". `tests/test_frontend_nav_parity.py`
 * holds the two lists together.
 */
export const BOTTOM = ["home", "portfolio", "sector", "profile"];

/**
 * The rail's entries under their headers, in registry order — the shape of
 * `stocks.navigation.sections()`. Consecutive pages sharing a section form one
 * group, so the order of `PAGES` is the order of the menu.
 */
export function sections(pages: Page[] = PAGES): { section?: string; pages: Page[] }[] {
  const groups: { section?: string; pages: Page[] }[] = [];
  for (const page of pages) {
    if (page.hidden) continue;
    const last = groups[groups.length - 1];
    if (last && last.section === page.section) last.pages.push(page);
    else groups.push({ section: page.section, pages: [page] });
  }
  return groups;
}

export function pageFor(slug: string): Page {
  return (
    PAGES.find((page) => page.slug === slug || (page.aliases ?? []).includes(slug)) ??
    PAGES[0]!
  );
}

/** The canonical slug for a path, so an old URL can be rewritten to the new one. */
export function canonical(slug: string): string {
  return pageFor(slug).slug;
}
