/**
 * What the app is still waiting on, for the banner in the corner.
 *
 * Every GET through `shell/api` is recorded here while it is out. Most answer
 * in tens of milliseconds and nobody should ever see them; the banner only
 * speaks for requests out longer than `SLOW_MS`, and names them by what they
 * are fetching — "Pricing your portfolio", "Insider filings (SEC)" — because
 * "loading…" says nothing about whether it is worth waiting for.
 *
 * Progress is per burst: a page opening fires a dozen requests, the bar
 * counts how many of *those* have landed, and the count resets once nothing
 * is out.
 */

import { useSyncExternalStore } from "react";

export const SLOW_MS = 1500;

/** Translation key per kind of request, first match wins. */
const KINDS: [RegExp, string][] = [
  [/\/ticker\/[^/]+\/insiders/, "activity.insiders"],
  [
    /\/ticker\/[^/]+\/(financials|metrics|moat|valuation|fund)/,
    "activity.fundamentals",
  ],
  [/\/(earnings|ticker\/[^/]+\/events)/, "activity.earnings"],
  [/\/(pulse|sectors)/, "activity.pulse"],
  [/\/(portfolio|movers|extremes|daily)/, "activity.book"],
  [
    /\/(home\/closes|market\/quotes|ticker\/[^/]+\/(bars|quote|position))/,
    "activity.prices",
  ],
];

export function kindOf(url: string): string {
  const path = url.split("?")[0] ?? url;
  return KINDS.find(([pattern]) => pattern.test(path))?.[1] ?? "activity.other";
}

type Out = { kind: string; since: number };

const out = new Map<number, Out>();
const listeners = new Set<() => void>();
let next = 0;
let total = 0;
let done = 0;
let snapshot: Activity = { slow: [], done: 0, total: 0 };
let timer: ReturnType<typeof setTimeout> | null = null;

export type Activity = {
  /** Distinct kinds of request out longer than `SLOW_MS`, oldest first. */
  slow: string[];
  done: number;
  total: number;
};

function publish(now = Date.now()): void {
  const slow: string[] = [];
  let soonest: number | null = null;
  for (const { kind, since } of [...out.values()].sort((a, b) => a.since - b.since)) {
    const due = since + SLOW_MS;
    if (due <= now) {
      if (!slow.includes(kind)) slow.push(kind);
    } else if (soonest === null || due < soonest) soonest = due;
  }
  const changed =
    slow.join() !== snapshot.slow.join() ||
    (slow.length > 0 && (done !== snapshot.done || total !== snapshot.total));
  if (changed) {
    snapshot = { slow, done, total };
    listeners.forEach((fn) => fn());
  }
  // Wake up when the next request crosses the line, not on a polling loop.
  if (timer !== null) clearTimeout(timer);
  timer = soonest === null ? null : setTimeout(() => publish(), soonest - now + 5);
}

/** Record a request going out; call the returned function when it lands. */
export function begin(url: string, now = Date.now()): () => void {
  if (out.size === 0) {
    total = 0;
    done = 0;
  }
  const id = next++;
  out.set(id, { kind: kindOf(url), since: now });
  total += 1;
  publish(now);
  return () => {
    if (!out.delete(id)) return;
    done += 1;
    publish();
  };
}

export function current(): Activity {
  return snapshot;
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function useActivity(): Activity {
  return useSyncExternalStore(subscribe, current);
}
