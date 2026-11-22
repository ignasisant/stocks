/**
 * Whether opening the assistant picks the last thread back up or starts clean.
 *
 * Back within minutes, the reader is still on the same subject: the follow-up
 * belongs under the question just asked. Back the next day, the question they
 * came with is almost never about yesterday's thread, and landing in it means
 * either asking off-topic under an old answer or hunting for "New" first. So
 * a thread left alone longer than `IDLE_MS` is not reopened; a blank one is,
 * with the old one a tap away in the list.
 *
 * "Left alone" is both: nothing written on it (`updated`), and the drawer not
 * open on it (`seen`, kept per device). Reading an old thread for an hour and
 * closing the drawer for a minute is not leaving it.
 */

import type { Conversation } from "./types";

/** Away longer than this, the assistant opens on a new thread. */
export const IDLE_MS = 30 * 60_000;

const KEY = "chatSeen";

/** When this device last had the drawer open, ms since epoch; 0 if never. */
export function lastSeen(storage?: Storage | null): number {
  try {
    const raw = (storage ?? window.localStorage).getItem(KEY);
    const at = raw ? Number(raw) : 0;
    return Number.isFinite(at) ? at : 0;
  } catch {
    return 0;
  }
}

export function markSeen(now = Date.now(), storage?: Storage | null): void {
  try {
    (storage ?? window.localStorage).setItem(KEY, String(now));
  } catch {
    // Storage off: the thread's own `updated` still decides, which only
    // misjudges someone who read without writing.
  }
}

/**
 * Whether `open` was left long enough ago that the drawer should start a new
 * thread instead. Never an empty thread (it already is new), never one still
 * being answered (the reader is waiting on it), never `keep` (the guide's).
 */
export function stale(
  open: Conversation | undefined,
  seen: number,
  now: number,
  keep: string | null = null,
): boolean {
  if (!open || !open.messages || open.answering || open.id === keep) return false;
  const written = Date.parse(open.updated);
  const last = Math.max(Number.isFinite(written) ? written : 0, seen);
  return now - last > IDLE_MS;
}

/** A thread on a page's subject is picked back up within this long. */
export const TOPIC_MS = 60 * 60_000;

/**
 * Where a page's question on `topic` ("ticker:NVDA", "plan"…) goes: the id of
 * the thread to continue, or null for a new one. The thread on screen wins
 * when it is on the subject; otherwise the latest thread that is. Either only
 * if written on within `TOPIC_MS` — an hour later the same company is a new
 * question, and a thread on another subject is never interrupted with it.
 * Reading a thread does not count: on a desk the drawer stays open beside the
 * page, and the hour would never run out.
 *
 * One still being answered is in use now, though its first question is not
 * on disk yet (`messages` 0): a second angle pressed meanwhile goes under it.
 */
export function onTopic(
  threads: readonly Conversation[],
  activeId: string | null,
  topic: string,
  now: number,
): string | null {
  const used = (c: Conversation) => {
    if (c.answering) return now;
    const written = Date.parse(c.updated);
    return Number.isFinite(written) ? written : 0;
  };
  const fits = threads
    .filter((c) => (c.messages || c.answering) && c.topics?.includes(topic))
    .filter((c) => now - used(c) <= TOPIC_MS);
  const active = fits.find((c) => c.id === activeId);
  if (active) return active.id;
  const latest = fits.sort((a, b) => used(b) - used(a))[0];
  return latest?.id ?? null;
}
