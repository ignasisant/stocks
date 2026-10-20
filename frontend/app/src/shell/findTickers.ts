/**
 * Every ticker field's lookup — the top bar, the pickers, the watchlist adder.
 *
 * A query's answer barely moves (a listing stays listed, and the server keeps
 * Yahoo's side for every account), so a field typed back to "asm" after "asml"
 * asks nothing. Kept for a minute rather than the visit: the own-list rows
 * carry the ★/● marks, which a star toggled on another screen changes.
 */

import { get } from "./api";

type Results<M> = { query: string; matches: M[] };

const KEEP_MS = 60_000;
const MAX_KEPT = 200;

const kept = new Map<string, { at: number; answer: Promise<unknown> }>();

/**
 * `/search` for `q`, shared with every field that asked the same thing in the
 * last minute. `world: false` leaves out the worldwide (Yahoo) tier — the
 * answer a box can draw while the full one is still on its way.
 */
export function findTickers<M>(
  q: string,
  { limit, world = true }: { limit?: number; world?: boolean } = {},
): Promise<Results<M>> {
  const term = q.trim();
  const key = `${limit ?? ""}|${world ? "" : "local"}|${term.toUpperCase()}`;
  const hit = kept.get(key);
  if (hit && Date.now() - hit.at < KEEP_MS) return hit.answer as Promise<Results<M>>;
  const answer = get<Results<M>>("/search", {
    q: term,
    limit,
    world: world ? undefined : "false",
  });
  kept.delete(key);
  kept.set(key, { at: Date.now(), answer });
  if (kept.size > MAX_KEPT) kept.delete(kept.keys().next().value as string);
  // A failure is not an answer: the next keystroke on this query asks again.
  answer.catch(() => {
    if (kept.get(key)?.answer === answer) kept.delete(key);
  });
  return answer;
}

/** Drop every kept answer — after a write that changes the own-list rows. */
export function forgetSearches(): void {
  kept.clear();
}
