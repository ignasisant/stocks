/**
 * Which capabilities the start card lists, and where each one is switched
 * on. No React: this is the part worth testing on its own.
 *
 * Whether a capability is *on* is never decided here — `/onboarding` answers
 * that from the registry the guided tour reads (`stocks.web.onboarding`). All
 * this file knows is which key in that payload a row shows, and which tour step
 * lands where the reader can act on it.
 */

import { canonical } from "../../shell/pages";
import type { TourStep } from "./types";

/** One capability, and where it is switched on. */
export type Row = {
  /** The key it reads in `setup` / `explore`. */
  key: string;
  /** Catalog key for the label — a word or two: the icon carries the rest. */
  label: string;
  /** `Icon` name drawn in the row's node. */
  icon: string;
  /** Catalog key for the big button when this is the next thing to do. */
  cta?: string;
  /** The tour step whose target is where this is switched on. */
  step?: string;
  /** The Profile tab that step lands on — see `target()`. */
  tab?: string;
  /** Where to go when no step owns this row at all. */
  page?: string;
  /**
   * Drawn disabled for a guest, rather than hidden, when its target sits
   * behind a sign-in — the import page, the assistant, notifications, the
   * watchlist editor: a guest should see what an account gets, and pressing
   * into a wall is worse than a control that says plainly it is not theirs
   * yet. Search is the one that stays live.
   */
  signedIn?: boolean;
  /**
   * Catalog key of a request the row hands the assistant, in a fresh
   * conversation, instead of opening its step's page: the plan is built
   * faster by answering the chat's few questions than by filling the form.
   */
  ask?: string;
  /**
   * Worth having, not needed: the assistant answers without a key of the
   * reader's own, and notifications are a second place to read what Home says. Left
   * out of the card's count, so finishing the setup means signing in and
   * importing — not a 2/4 that reads as half a broken app.
   */
  optional?: boolean;
  /**
   * Answered by this browser, not by `/onboarding`: whether the app is
   * installed is a fact about the device, which the server cannot see.
   * `Setup.tsx` fills it in and drops the row where nothing can be installed.
   */
  device?: boolean;
};

export const SETUP: Row[] = [
  // Sign-in has no step of its own. Done, it goes to Profile, where the
  // account settings and the log-out live; pending — a guest — it is the
  // sign-in link itself, which `Setup.tsx` draws in place of this destination.
  {
    key: "login",
    label: "home.start_login",
    icon: "account_circle",
    cta: "home.start_go_login",
    page: "profile",
  },
  {
    key: "import",
    label: "home.start_import",
    icon: "upload_file",
    cta: "home.start_go_import",
    step: "import",
    signedIn: true,
  },
  // Right after the import, when there is a book to hold to a plan. The chat's
  // plan builder (`chat/plan_builder.py`) asks only what it does not know and
  // saves the profile with it; the form stays on Profile → My plan.
  {
    key: "plan",
    label: "home.start_plan",
    icon: "flag",
    cta: "home.start_go_plan",
    step: "plan",
    ask: "profile.plan_ask_prompt",
    signedIn: true,
    optional: true,
  },
  // The key gate lives inside the assistant drawer, which is not a page: the
  // registry says so with a null path, and `target()` leaves the row inert
  // rather than sending the reader somewhere that is not it.
  {
    key: "ai",
    label: "home.start_ai",
    icon: "auto_awesome",
    cta: "home.start_go_ai",
    step: "assistant",
    signedIn: true,
    optional: true,
  },
  {
    key: "notify",
    label: "home.start_notify",
    icon: "notifications",
    cta: "home.start_go_notify",
    step: "notify",
    tab: "notify",
    signedIn: true,
    optional: true,
  },
  // Last, and only where this browser can install (`shell/install.ts`): a
  // Chromium press opens the browser's own dialog in place, Safari on iPhone
  // and iPad lands on Preferences' App card, which says where Share keeps it.
  {
    key: "app",
    label: "home.start_app",
    icon: "install_mobile",
    cta: "home.start_go_app",
    step: "prefs",
    tab: "prefs",
    signedIn: true,
    optional: true,
    device: true,
  },
];

export const EXPLORE: Row[] = [
  // Search is in the top bar on every page, so this points at the page a
  // looked-up ticker lands on rather than at a field it cannot focus from here.
  { key: "search", label: "home.start_search", icon: "search", step: "market" },
  // Completable without the AI row above it ever going green: the assistant
  // answers on the keyless chain.
  {
    key: "ask",
    label: "home.start_ask",
    icon: "forum",
    step: "assistant",
    signedIn: true,
  },
  {
    key: "watchlist",
    label: "home.start_watchlist",
    icon: "star",
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
/** What this browser knows about installing, which `/onboarding` cannot. */
export type Device = {
  guest: boolean;
  /** `shell/install.ts`'s `installWay()`: null where nothing can be installed. */
  way: "prompt" | "ios" | null;
  installed: boolean;
};

/**
 * The start line: each `SETUP` row with whether it is done.
 *
 * Server rows read `/onboarding`'s `setup`; the device row reads the browser.
 * It shows only where there is something to do or done — an installed app,
 * or a browser that can install — and never to a guest, as the nudge is not
 * shown to one: the app is for coming back to one's own book.
 */
export function setupLine(
  setup: Record<string, boolean | undefined>,
  device: Device,
): { row: Row; on: boolean }[] {
  return SETUP.filter(
    (row) =>
      !row.device || (!device.guest && (device.installed || device.way !== null)),
  ).map((row) => ({
    row,
    on: row.device ? device.installed : setup[row.key] === true,
  }));
}

export type Target =
  | { kind: "page"; page: string; params?: Record<string, string> }
  | { kind: "assistant"; ask?: string };

/**
 * The row's destination, taken from the payload rather than decided here.
 *
 * `null` means there is nowhere in this app to send the reader — the assistant
 * is a drawer the shell owns, not a route — and the row then states its
 * capability without pretending to be a control. The tour makes the same call
 * on the same signal: no path, no "take me there".
 *
 * `canonical()` because the registry names a page by its Python slug
 * (`import_transactions`) and this app serves it at its own.
 */
export function target(row: Row, steps: TourStep[]): Target | null {
  if (row.page) return { kind: "page", page: row.page };
  if (row.ask) return { kind: "assistant", ask: row.ask };
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
