/**
 * Answers that land on a thread nobody is looking at.
 *
 * A reader who asks something and moves to another thread leaves the first
 * answer to finish on the server (`api/runs.py`). Without this the only way to
 * learn it had landed was to go back and look. The list says which threads are
 * still being answered (`Conversation.answering`), and while one the panel is
 * not showing is, the list is read again every few seconds; a thread that
 * stops answering has landed, and is unread until it is opened.
 *
 * Three ways to say so, from quietest to loudest: a dot on its row (and on the
 * header's way to the list), a toast with an "Open" (`ui/toast.ts`), and a count in the tab's
 * title while the tab is in the background. No sound and no system
 * notification: both need a setting to turn them off, and the drawer has none
 * yet.
 *
 * Session-only. A reload loses the dots, which is the right side to err on:
 * the thread itself has the answer.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Conversation } from "./types";

/** How often the list is read while another thread is answering (ms). */
const POLL_MS = 5000;

/** One answer that landed on a thread the reader was not on. */
export type Landed = {
  id: string;
  title: string;
  /** False when the thread has no new turns: refused, or stopped elsewhere. */
  ok: boolean;
};

/**
 * Compare a fresh list with the threads being watched, and say which landed.
 *
 * `watch` maps a thread being answered off-screen to the turns it had when it
 * was first seen answering, and is updated in place: a thread starts being
 * watched, or stops — because it landed, because it is the one on screen now
 * (its run is followed there), or because it is gone.
 */
export function landed(
  watch: Map<string, number>,
  list: readonly Conversation[],
  active: string | null,
): Landed[] {
  const out: Landed[] = [];
  const listed = new Set(list.map((c) => c.id));
  for (const id of [...watch.keys()]) if (!listed.has(id)) watch.delete(id);
  for (const conv of list) {
    if (conv.id === active) {
      watch.delete(conv.id);
      continue;
    }
    const before = watch.get(conv.id);
    if (conv.answering) {
      if (before === undefined) watch.set(conv.id, conv.messages);
      continue;
    }
    if (before === undefined) continue;
    watch.delete(conv.id);
    out.push({ id: conv.id, title: conv.title, ok: conv.messages > before });
  }
  return out;
}

const COUNTED = /^\(\d+\) /;

/** The tab's title with `n` in front, or without a count at 0. */
export function counted(title: string, n: number): string {
  const bare = title.replace(COUNTED, "");
  return n > 0 ? `(${n}) ${bare}` : bare;
}

/**
 * Watch `threads` for answers landing off-screen. `poll` reads the list again;
 * it is called only while some thread other than `active` is answering.
 */
export function useLanded(
  threads: Conversation[] | null,
  active: string | null,
  poll: () => void,
) {
  const watch = useRef(new Map<string, number>());
  const [unread, setUnread] = useState<ReadonlySet<string>>(() => new Set());
  const [notice, setNotice] = useState<Landed | null>(null);
  // Landed while the tab was in the background; the title carries the count
  // until the reader is back.
  const away = useRef(0);

  useEffect(() => {
    if (!threads) return;
    const done = landed(watch.current, threads, active);
    const listed = new Set(threads.map((c) => c.id));
    setUnread((prev) => {
      const next = new Set([...prev].filter((id) => listed.has(id) && id !== active));
      for (const { id } of done) next.add(id);
      return next.size === prev.size && [...next].every((id) => prev.has(id))
        ? prev
        : next;
    });
    if (!done.length) return;
    setNotice(done[done.length - 1] ?? null);
    if (typeof document !== "undefined" && document.hidden) {
      away.current += done.length;
      document.title = counted(document.title, away.current);
    }
  }, [threads, active]);

  // The thread opened is read: its dot and its notice go.
  useEffect(() => {
    if (!active) return;
    setNotice((now) => (now?.id === active ? null : now));
  }, [active]);

  useEffect(() => {
    const back = () => {
      if (document.hidden || !away.current) return;
      away.current = 0;
      document.title = counted(document.title, 0);
    };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, []);

  const waiting = !!threads?.some((c) => c.answering && c.id !== active);
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(poll, POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, poll]);

  const dismiss = useCallback(() => setNotice(null), []);
  return { unread, notice, dismiss };
}
