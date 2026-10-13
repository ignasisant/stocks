/**
 * How old the figures on screen are, when the API had to say so.
 *
 * A response built from the last good data — the price source refused and the
 * server answered from its memo — carries `X-Data-Stale-Since`. `shell/api`
 * records it per URL here, and the shell shows one line for the oldest of
 * them: a reader looking at a Tuesday close on a Thursday deserves to know.
 * A later answer for the same URL without the header clears its mark, so the
 * line goes away by itself once the source is back.
 *
 * `X-Data-Refreshing` is the milder word: the figures are recent, but the
 * server is refreshing them behind this answer. No line for it — only
 * `useApi` asking again a little later (`isRefreshing`).
 */

import { useSyncExternalStore } from "react";

const since = new Map<string, number>();
const refreshing = new Set<string>();
const listeners = new Set<() => void>();
let oldest: number | null = null;

function recompute(): void {
  let next: number | null = null;
  for (const at of since.values()) if (next === null || at < next) next = at;
  if (next === oldest) return;
  oldest = next;
  listeners.forEach((fn) => fn());
}

/** Record what one response said (`null` = nothing: the figures are live). */
export function noteFreshness(url: string, header: string | null): void {
  const at = header ? Date.parse(header) : Number.NaN;
  if (Number.isNaN(at)) since.delete(url);
  else since.set(url, at);
  recompute();
}

/** Record whether one response said newer figures are on the way. */
export function noteRefreshing(url: string, header: string | null): void {
  if (header) refreshing.add(url);
  else refreshing.delete(url);
}

/** Whether one URL's last answer said the server was refreshing it. */
export function isRefreshing(url: string): boolean {
  return refreshing.has(url);
}

/** When one URL's last answer said its figures were from, as epoch ms. */
export function staleAt(url: string): number | null {
  return since.get(url) ?? null;
}

/** The oldest stale-since across every URL, as epoch ms; `null` when none. */
export function staleSince(): number | null {
  return oldest;
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function resetFreshness(): void {
  since.clear();
  refreshing.clear();
  recompute();
}

export function useStaleSince(): number | null {
  return useSyncExternalStore(subscribe, staleSince);
}
