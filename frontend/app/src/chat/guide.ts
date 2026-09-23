/**
 * The walkthrough's API, and what the drawer needs to know about it.
 *
 * The state is the account's and lives on the server (`/guide`): the same
 * prefs keys and the same thread the Streamlit guide writes, so a reader who
 * started the walkthrough in one front end finds it where they left it in the
 * other. What lives here is only what belongs to this browser tab — whether
 * this load has already had its automatic open.
 */

import { get, send } from "../shell/api";

export type GuideStep = {
  id: string;
  icon: string;
  path: string | null;
  params: Record<string, string>;
  session: Record<string, string>;
  gated: boolean;
  done: boolean | null;
  title_key: string;
  body_key: string;
  cta_key: string | null;
};

export type GuideState = {
  surface: "chat" | "modal" | string;
  active: boolean;
  finished: boolean;
  step: GuideStep | null;
  /** Every step, so an older card can still send the reader to its page. */
  steps: GuideStep[];
  /** 1-based; 0 when the guide is not on a step. */
  index: number;
  of: number;
  thread: string | null;
  auto_open: boolean;
  /** The call appended to the guide's thread: re-read it. */
  changed: boolean;
};

export const readGuide = () => get<GuideState>("/guide");

export const startGuide = (body: { step?: string; auto?: boolean; lang?: string }) =>
  send<GuideState>("POST", "/guide/start", body);

export const syncGuide = (lang: string) =>
  send<GuideState>("POST", "/guide/sync", { lang });

export const advanceGuide = (lang: string) =>
  send<GuideState>("POST", "/guide/advance", { lang });

export const finishGuide = (reason: string) =>
  send<GuideState>("POST", "/guide/finish", { reason });

/**
 * Whether this tab has already evaluated the automatic open.
 *
 * Per tab, like the Streamlit guide's own "evaluated once per session" flag:
 * a reload in the same tab is the same visit, and reopening the drawer on
 * every one of them would spend all three automatic opens in a minute.
 */
const SEEN = "ag_guide_auto_seen";

export function autoSeen(): boolean {
  try {
    return window.sessionStorage.getItem(SEEN) === "1";
  } catch {
    // Storage blocked: behave as already seen. An automatic open that cannot
    // remember it happened would fire on every page of the visit.
    return true;
  }
}

export function markAutoSeen(): void {
  try {
    window.sessionStorage.setItem(SEEN, "1");
  } catch {
    // Nothing to remember it in; `autoSeen` already reads that as "seen".
  }
}

/** `:material/name:` — Streamlit's icon shortcode, which the stored copy carries. */
export const unshortcode = (text: string) =>
  text.replace(/:material\/[a-z0-9_]+:\s?/g, "");
