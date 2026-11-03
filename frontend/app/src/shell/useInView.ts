/**
 * Whether an element has come into view — once.
 *
 * A long page asks for everything at once on arrival: every card's query fires
 * on mount, and the cards below the fold spend the connection and the server
 * on figures nobody is looking at yet. Mounting a card only when its slot
 * nears the viewport sends the first requests to what is on screen, and the
 * rest as the reader scrolls to them.
 *
 * A latch, not a live reading: once seen, seen. A card that has loaded stays
 * loaded when the reader scrolls past it and back, rather than unmounting and
 * asking again. The watch starts half a viewport early (`AHEAD`), so at a
 * normal scrolling pace the card is drawn by the time it arrives, not a
 * skeleton the reader waits on.
 *
 * Where nothing can watch the viewport — a server render, a test, a browser
 * without the observer — everything is seen at once: the page then loads the
 * way it always did, and nothing is left blank.
 *
 * Near the viewport is not on screen while the assistant covers the page —
 * a phone's drawer is the whole screen. A slot that comes near then waits for
 * the drawer to close: the reader went to the assistant to read an answer,
 * and the cards underneath would be asking the same one server for figures
 * nobody can see.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { isPhone } from "../chat/phone";

/** How far outside the viewport counts as "in view": half a viewport below
 * and above, so a slot loads a scroll ahead of the reader. */
const AHEAD = "50% 0px";

/** Whether this runtime can watch the viewport at all. */
export function canObserve(): boolean {
  return typeof IntersectionObserver !== "undefined";
}

/** Whether the open assistant covers the whole page (`Drawer.tsx` marks it). */
export function covered(): boolean {
  return (
    typeof document !== "undefined" &&
    !!document.documentElement.dataset.chat &&
    isPhone()
  );
}

function useCovered(): boolean {
  const [now, setNow] = useState(covered);
  useEffect(() => {
    if (typeof MutationObserver === "undefined") return;
    const follow = () => setNow(covered());
    follow();
    const watch = new MutationObserver(follow);
    watch.observe(document.documentElement, { attributeFilter: ["data-chat"] });
    return () => watch.disconnect();
  }, []);
  return now;
}

/**
 * `[ref, seen]`: attach `ref` to the element to watch; `seen` turns true
 * when it nears the viewport and stays true. `eager` marks it seen from the
 * start — the lead slot of a page, which is on screen on arrival and must
 * not flash a placeholder for the frame the observer takes to say so.
 */
export function useInView<T extends Element>(
  eager = false,
): [(node: T | null) => void, boolean] {
  const [near, setNear] = useState(() => eager || !canObserve());
  const hidden = useCovered();
  const [seen, setSeen] = useState(() => near && !covered());
  useEffect(() => {
    if ((eager || near) && !hidden) setSeen(true);
  }, [eager, near, hidden]);
  const watcher = useRef<IntersectionObserver | null>(null);
  // A callback ref rather than an object one: the observer attaches the
  // moment the node mounts, and lets go the moment it leaves, with no effect
  // ordering to get right.
  const ref = useCallback(
    (node: T | null) => {
      watcher.current?.disconnect();
      watcher.current = null;
      if (node === null || near) return;
      const io = new IntersectionObserver(
        (entries) => {
          if (!entries.some((entry) => entry.isIntersecting)) return;
          io.disconnect();
          watcher.current = null;
          setNear(true);
        },
        { rootMargin: AHEAD },
      );
      io.observe(node);
      watcher.current = io;
    },
    [near],
  );
  useEffect(() => () => watcher.current?.disconnect(), []);
  return [ref, seen];
}
