/**
 * How old the figures on screen are, when the API had to say so.
 *
 * A response built from the last good data — the price source refused and the
 * server answered from its memo — carries `X-Data-Stale-Since`. `shell/api`
 * records it per URL here, and the shell shows one line for the oldest of
 * them: a reader looking at a Tuesday close on a Thursday deserves to know.
 * A later answer for the same URL without the header clears its mark, so the
 * line goes away by itself once the source is back.
 */

import { useSyncExternalStore } from "react";

const since = new Map<string, number>();
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
  recompute();
}

export function useStaleSince(): number | null {
  return useSyncExternalStore(subscribe, staleSince);
}
