/**
 * Which conversations sit as tabs over a wide drawer, and where that is kept.
 *
 * A tab is a thread the reader has had open, not a second kind of thread:
 * closing one leaves the thread in the list, answer and all. So the strip is
 * a short list of ids, nothing more — titles, dots and order of recency come
 * from the thread list it is laid over.
 *
 * Per browser rather than in `/prefs`, like the drawer's width: which threads
 * are worth a tab is a property of this sitting, not of the account. Ids the
 * account does not have (deleted, or another account's on a shared browser)
 * drop out as soon as the list is known.
 */

import type { Conversation } from "./types";

const KEY = "ag.chat.tabs";

/** More than this and the titles are cut to a few letters at 720px. */
export const MAX_TABS = 5;

export function readTabs(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((id) => typeof id === "string") : [];
  } catch {
    return [];
  }
}

export function saveTabs(tabs: string[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(tabs));
  } catch {
    /* private window, blocked storage — the strip just forgets */
  }
}

/**
 * The strip once `active` is on it and `threads` has been checked against it.
 *
 * A new tab goes on the end, so the others stay where the hand left them.
 * Past the cap the leftmost one goes — unless it is still being answered,
 * since that one is the reason to keep a tab at all. `threads` null means the
 * list has not loaded yet, and nothing is pruned on a guess. The active id is
 * never pruned: a thread just created is active before the list knows it.
 */
export function fit(
  tabs: string[],
  active: string | null,
  threads: Conversation[] | null,
): string[] {
  let next = tabs;
  if (threads) {
    const known = new Set(threads.map((c) => c.id));
    next = next.filter((id) => id === active || known.has(id));
  }
  if (active && !next.includes(active)) next = [...next, active];
  while (next.length > MAX_TABS) {
    const busy = new Set((threads ?? []).filter((c) => c.answering).map((c) => c.id));
    const drop = next.find((id) => id !== active && !busy.has(id)) ?? next[0];
    next = next.filter((id) => id !== drop);
  }
  return next;
}

/**
 * The strip without `id`, and the tab to open in its place — the one to its
 * right, else to its left — when `id` is the one on screen. Null otherwise:
 * closing a tab in the background moves nobody.
 */
export function close(
  tabs: string[],
  id: string,
  active: string | null,
): { tabs: string[]; open: string | null } {
  const at = tabs.indexOf(id);
  const next = tabs.filter((t) => t !== id);
  if (id !== active || at < 0) return { tabs: next, open: null };
  return { tabs: next, open: next[at] ?? next[at - 1] ?? null };
}

export function same(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((id, n) => id === b[n]);
}
