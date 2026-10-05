/**
 * The width an element actually has, followed as it changes.
 *
 * A chart drawn in a fixed viewBox scales its text with the frame: an 11px
 * label in a 720-unit frame prints at 5px in a 380px drawer and at 29px across
 * a full desktop row. Drawing the frame at the measured width instead keeps a
 * label the size it says, whether the chat drawer is shut, open or being
 * dragged wider.
 *
 * Measured before the first paint, so the chart does not draw a frame at the
 * fallback width and then jump; `fallback` is only what a render without
 * layout (the server, a test) sees. A callback ref rather than an effect: a
 * chart whose first render draws nothing yet (no data, no range) mounts its
 * box later, and an effect run once on mount would never see it.
 */

import { type RefCallback, useCallback, useState } from "react";

export function useWidth<T extends HTMLElement = HTMLDivElement>(
  fallback: number,
): [RefCallback<T>, number] {
  const [width, setWidth] = useState(fallback);
  const node = useCallback((el: T | null) => {
    if (!el) return;
    const first = Math.round(el.getBoundingClientRect().width);
    if (first > 0) setWidth(first);
    if (typeof ResizeObserver === "undefined") return;
    const seen = new ResizeObserver(([entry]) => {
      const next = Math.round(entry?.contentRect.width ?? 0);
      if (next > 0) setWidth(next);
    });
    seen.observe(el);
    return () => seen.disconnect();
  }, []);
  return [node, width];
}
