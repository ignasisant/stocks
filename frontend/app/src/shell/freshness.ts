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
  retries.clear();
  kept.clear();
  recompute();
  recomputeRetry();
}

export function useStaleSince(): number | null {
  return useSyncExternalStore(subscribe, staleSince);
}

/*
 * What the stale line says it is doing about it.
 *
 * "Se actualizan solos" was a promise the line could not show being kept:
 * `useApi.followStale` asked again on its schedule in silence, and stopped
 * after its last try while the line kept promising. These say, per follow,
 * when the next try is due (`due`, epoch ms) or that one is out now (`0`),
 * so the line can count down, say "retrying…", and once nobody is trying any
 * more, offer the press itself (`retryStale`).
 *
 * And the figures the last visit left (`shell/keep`): drawn at once, but not
 * live until the same fetch answers again. `keptSince` marks them while that
 * fetch is out, so the line can say they are the last visit's and being
 * brought up to date — rather than pass for live.
 */

const retries = new Map<string, number>();
const kept = new Map<string, number>();
const retryListeners = new Set<RetryListener>();
let retrySnap: Retry = { due: null, asking: false };
let keptOldest: number | null = null;

export type Retry = {
  /** When the soonest scheduled re-ask goes out, epoch ms; null when none. */
  due: number | null;
  /** Whether a re-ask is out right now. */
  asking: boolean;
};

function recomputeRetry(): void {
  let due: number | null = null;
  let asking = false;
  for (const at of retries.values()) {
    if (at === 0) asking = true;
    else if (due === null || at < due) due = at;
  }
  let oldestKept: number | null = null;
  for (const at of kept.values())
    if (oldestKept === null || at < oldestKept) oldestKept = at;
  if (due !== retrySnap.due || asking !== retrySnap.asking) retrySnap = { due, asking };
  keptOldest = oldestKept;
  listeners.forEach((fn) => fn());
}

/** One follow's next try: `at` (epoch ms), `0` while asking, null when done. */
export function noteRetry(id: string, at: number | null): void {
  if (at === null) retries.delete(id);
  else retries.set(id, at);
  recomputeRetry();
}

/** Kept figures on screen for `id` since `at` (epoch ms), or null once live. */
export function noteKept(id: string, at: number | null): void {
  if (at === null) kept.delete(id);
  else kept.set(id, at);
  recomputeRetry();
}

export function currentRetry(): Retry {
  return retrySnap;
}

export function keptSince(): number | null {
  return keptOldest;
}

export function useRetry(): Retry {
  return useSyncExternalStore(subscribe, currentRetry);
}

/** The oldest kept answer still waiting for its live one, as epoch ms. */
export function useKeptSince(): number | null {
  return useSyncExternalStore(subscribe, keptSince);
}

/** Every URL whose last answer was stale. */
export function staleUrls(): string[] {
  return [...since.keys()].filter((key) => key.startsWith("/"));
}

/**
 * Ask every screen holding stale figures to fetch them again, now. Returns
 * the URLs some screen took; `useApi.retryNow` asks for the rest itself.
 */
export function retryStale(): Set<string> {
  const taken = new Set<string>();
  retryListeners.forEach((fn) => {
    for (const url of fn() ?? []) taken.add(url);
  });
  return taken;
}

/** A screen's half of the press: ask again, and say which URLs it took. */
type RetryListener = () => Iterable<string> | void;

export function onRetryStale(fn: RetryListener): () => void {
  retryListeners.add(fn);
  return () => {
    retryListeners.delete(fn);
  };
}
