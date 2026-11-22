/**
 * Where the reader was in each thread, so coming back to it lands on the line
 * they were reading rather than the newest one.
 *
 * On a phone a ticker named in an answer closes the drawer to show its page,
 * and the panel goes with it: reopened, it would start again at the bottom,
 * and a long answer read halfway is then a scroll back up to find the place.
 * The same for the thread list and back. So the panel notes the spot as the
 * reader scrolls, and asks for it when the thread is drawn again.
 *
 * Only while it still means the same thing: the same turns as when they left
 * (a new answer since is what they come back to see, at the bottom), and not
 * long after (`KEEP_MS`, the window a page's own scroll is kept for). A spot
 * at the end is no spot: the bottom is where a thread opens anyway, and an
 * answer still being written keeps following it there.
 *
 * In memory: a reload opens on the newest turn, as a thread always did.
 */

import { KEEP_MS } from "../shell/router";

/** How close to the end counts as the end (the stick-to-bottom library's own). */
export const END_PX = 70;

type Spot = { top: number; turns: number; at: number };

const spots = new Map<string, Spot>();

/** The reader is at `top` in thread `id`, which has `turns` turns. */
export function note(
  id: string,
  top: number,
  turns: number,
  atEnd: boolean,
  now = Date.now(),
): void {
  if (atEnd) spots.delete(id);
  else spots.set(id, { top, turns, at: now });
}

/**
 * The reader left thread `id` now. Its age is counted from here, not from the
 * last scroll: ten minutes reading one screen and half a minute away is a
 * quick return.
 */
export function left(id: string, now = Date.now()): void {
  const spot = spots.get(id);
  if (spot) spot.at = now;
}

/** Where to put thread `id` back, drawn with `turns` turns, or null for the end. */
export function recall(id: string, turns: number, now = Date.now()): number | null {
  const spot = spots.get(id);
  if (!spot) return null;
  if (spot.turns !== turns || now - spot.at > KEEP_MS) {
    spots.delete(id);
    return null;
  }
  return spot.top;
}

/** Forget thread `id`'s spot: it was opened to show something at its end. */
export function forget(id: string): void {
  spots.delete(id);
}
