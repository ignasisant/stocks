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
 * `X-Data-Updating-Since` is the same age said without the blame: the figures
 * are old — last night's closes on a quiet morning — but nothing refused; the
 * server is downloading today's behind this answer. Its own line
 * (`updatingSince`), because "the price source is not answering" on every
 * first visit of the day, with Yahoo answering, was the line crying wolf.
 *
 * `X-Data-Refreshing` is the milder word: the figures are recent, but the
 * server is refreshing them behind this answer. No line for it — only
 * `useApi` asking again a little later (`isRefreshing`).
 *
 * A URL's marks go with the last screen holding it (`holdUrls`): a page left
 * while its figures were old must not leave the line on the next page, which
 * never asked for them.
 */

import { useSyncExternalStore } from "react";

const since = new Map<string, number>();
const updating = new Map<string, number>();
const refreshing = new Set<string>();
const listeners = new Set<() => void>();
let oldest: number | null = null;
let oldestUpdating: number | null = null;

function earliest(marks: Map<string, number>): number | null {
  let next: number | null = null;
  for (const at of marks.values()) if (next === null || at < next) next = at;
  return next;
}

function recompute(): void {
  const next = earliest(since);
  const nextUpdating = earliest(updating);
  if (next === oldest && nextUpdating === oldestUpdating) return;
  oldest = next;
  oldestUpdating = nextUpdating;
  listeners.forEach((fn) => fn());
}

function noteIn(marks: Map<string, number>, key: string, header: string | null): void {
  const at = header ? Date.parse(header) : Number.NaN;
  if (Number.isNaN(at)) marks.delete(key);
  else marks.set(key, at);
  recompute();
}

/** Record what one response said (`null` = nothing: the figures are live). */
export function noteFreshness(url: string, header: string | null): void {
  noteIn(since, url, header);
}

/** Record whether one response said its old figures are being updated. */
export function noteUpdating(url: string, header: string | null): void {
  noteIn(updating, url, header);
}

/** Whether one URL's last answer was old, either way: worth asking again. */
export function isOld(url: string): boolean {
  return since.has(url) || updating.has(url);
}

/** The oldest updating-since across every URL, as epoch ms; `null` when none. */
export function updatingSince(): number | null {
  return oldestUpdating;
}

export function useUpdatingSince(): number | null {
  return useSyncExternalStore(subscribe, updatingSince);
}

/*
 * Which screens hold which URLs. A mark outlives a request but not every
 * screen that read it: once the last holder lets go, the URL's marks go too —
 * a moment later, so the next screen asking for the same URL takes it over
 * instead of the line blinking out and back.
 */
const holders = new Map<string, number>();

export function holdUrls(urls: Iterable<string>): () => void {
  const held = [...urls];
  for (const url of held) holders.set(url, (holders.get(url) ?? 0) + 1);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    for (const url of held) {
      const left = (holders.get(url) ?? 1) - 1;
      if (left > 0) holders.set(url, left);
      else holders.delete(url);
    }
    setTimeout(() => {
      for (const url of held) {
        if (holders.has(url)) continue;
        since.delete(url);
        updating.delete(url);
        refreshing.delete(url);
      }
      recompute();
    }, 0);
  };
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
  updating.clear();
  holders.clear();
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

/** Every URL whose last answer was stale or updating. */
export function staleUrls(): string[] {
  const keys = new Set([...since.keys(), ...updating.keys()]);
  return [...keys].filter((key) => key.startsWith("/"));
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
