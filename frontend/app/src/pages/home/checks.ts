/**
 * Which capabilities the first-run card lists, and where each one is switched
 * on. No React: this is the part worth testing on its own.
 *
 * Whether a capability is *on* is never decided here — `/onboarding` answers
 * that from the same registry the Streamlit card and the guided tour read. All
 * this file knows is which key in that payload a row shows, and which tour step
 * lands where the reader can act on it.
 */

import { canonical } from "../../shell/pages";
import type { TourStep } from "./types";

/** One capability, and where it is switched on. */
export type Row = {
  /** The key it reads in `setup` / `explore`. */
  key: string;
  /** Catalog key for the label. Never a string: this app renders in two. */
  label: string;
  /** The tour step whose target is where this is switched on. */
  step?: string;
  /** The Profile tab that step lands on — see `target()`. */
  tab?: string;
  /** Where to go when no step owns this row at all. */
  page?: string;
  /**
   * Drawn disabled for a guest. `home.py` disables every pill whose target
   * sits behind a sign-in — the import page, the assistant, Telegram, the
   * watchlist editor — rather than hiding it: a guest should see what an
   * account gets, and pressing into a wall is worse than a control that says
   * plainly it is not theirs yet. Search is the one that stays live.
   */
  signedIn?: boolean;
};

export const SETUP: Row[] = [
  // Sign-in has no step of its own. Done, it goes to Profile, where the
  // account settings and the log-out live, as Streamlit's done pill does;
  // pending — a guest — it is the sign-in link itself, which `Setup.tsx`
  // draws in place of this destination.
  { key: "login", label: "home.setup_google", page: "profile" },
  { key: "import", label: "home.setup_import", step: "import", signedIn: true },
  // The key gate lives inside the assistant drawer, which is not a page: the
  // registry says so with a null path, and `target()` leaves the row inert
  // rather than sending the reader somewhere that is not it.
  { key: "ai", label: "home.setup_ai", step: "assistant", signedIn: true },
  {
    key: "telegram",
    label: "home.setup_tg",
    step: "notify",
    tab: "notify",
    signedIn: true,
  },
];

export const EXPLORE: Row[] = [
  // Search is in the top bar on every page, so this points at the page a
  // looked-up ticker lands on rather than at a field it cannot focus from here.
  { key: "search", label: "home.explore_search", step: "market" },
  // Completable without the AI row above it ever going green: the assistant
  // answers on the keyless chain.
  { key: "ask", label: "home.explore_ask", step: "assistant", signedIn: true },
  {
    key: "watchlist",
    label: "home.explore_watchlist",
    step: "watchlist",
    tab: "watch",
    signedIn: true,
  },
];

/**
 * Where a row sends the reader: a page, or the assistant drawer, or nowhere.
 *
 * The drawer is not a route — the shell mounts it over every page — so a row
 * that explains it cannot be a link. It is still a control, which is why it is
 * a case here rather than the `null` it used to collapse into.
 */
export type Target =
  | { kind: "page"; page: string; params?: Record<string, string> }
  | { kind: "assistant" };

/**
 * The row's destination, taken from the payload rather than decided here.
 *
 * `null` means there is nowhere in this app to send the reader — the assistant
 * is a drawer the shell owns, not a route — and the row then states its
 * capability without pretending to be a control. The tour makes the same call
 * on the same signal: no path, no "take me there".
 *
 * `canonical()` because the registry names the Streamlit page
 * (`import_transactions`) and this app serves it at its own slug.
 */
export function target(row: Row, steps: TourStep[]): Target | null {
  if (row.page) return { kind: "page", page: row.page };
  const step = steps.find((entry) => entry.id === row.step);
  if (!step) return null;
  if (step.path === null) {
    // No page, but the registry says what it wants open. The assistant is the
    // only one of those, and a row that merely stated its capability was the
    // one row on the checklist that could not be acted on.
    return step.session?.chat_panel_open ? { kind: "assistant" } : null;
  }
  const params: Record<string, string> = { ...step.params };
  // The registry keeps a Profile tab in `Step.session` and the payload now
  // carries it; `row.tab` stays as the fallback for a deploy whose API predates
  // that, and falls away on its own the moment the payload speaks.
  const tab = step.session?.profile_tab ?? row.tab;
  if (tab && !params.tab) params.tab = tab;
  return {
    kind: "page",
    page: canonical(step.path),
    params: Object.keys(params).length ? params : undefined,
  };
}
