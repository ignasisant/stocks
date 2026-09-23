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
  /** Hidden from the nav — reached from a ticker cell, not from the rail. */
  hidden?: boolean;
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
    icon: "pie_chart",
    component: lazy(() => import("../pages/portfolio/Portfolio")),
  },
  {
    slug: "sentiment",
    label: "nav.sentiment",
    icon: "speed",
    component: lazy(() => import("../pages/sentiment/Sentiment")),
  },
  {
    slug: "sector",
    label: "nav.sector",
    icon: "donut_small",
    component: lazy(() => import("../pages/sector/Sector")),
  },
  {
    slug: "earnings",
    label: "nav.earnings",
    icon: "calendar_month",
    component: lazy(() => import("../pages/earnings/Earnings")),
  },
  {
    slug: "import",
    label: "nav.import",
    icon: "upload_file",
    component: lazy(() => import("../pages/import/Import")),
    aliases: ["import_transactions"],
  },
  {
    slug: "profile",
    label: "nav.profile",
    icon: "account_circle",
    component: lazy(() => import("../pages/profile/Profile")),
  },
  {
    slug: "bank",
    label: "nav.bank",
    icon: "account_balance",
    component: lazy(() => import("../pages/bank/Bank")),
    // Hidden for the same reason the Streamlit page is absent from
    // `st.navigation`: the feature is an allowlist that fails closed, and a
    // rail entry every account can see would be one most of them cannot use.
    // It is reachable by URL — which is what the bank's redirect needs it to
    // be — and the day the allowlist widens, this line is the whole change.
    hidden: true,
  },
  {
    slug: "ticker",
    label: "nav.ticker",
    icon: "query_stats",
    component: lazy(() => import("../pages/ticker/Ticker")),
    hidden: true,
  },
];

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
