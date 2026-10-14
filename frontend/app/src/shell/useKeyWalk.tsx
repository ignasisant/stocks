/**
 * A chart's readout by keyboard, and what a screen reader hears of it.
 *
 * Every chart that reads a day under the pointer reads it under the arrow keys
 * too: the plot takes focus, arrows step one point (with shift, ten), Home and
 * End jump to the edges, Escape puts the readout away. Focus by keyboard opens
 * it on the last point — the one the headline already names — and a click's
 * focus opens nothing, since the pointer is already reading.
 *
 * What is spoken is only what the keys moved to. A pointer sweeping a chart
 * rewrites the readout sixty times a second; a live region on it would read
 * a flood, so the region stays empty until a key moves the readout and goes
 * quiet again as soon as a pointer takes over.
 */

import type { FocusEvent, KeyboardEvent } from "react";
import { useCallback, useState } from "react";

/** Where a key moves a readout at `at` on points 0..last; null = not ours. */
export function keyStep(
  key: string,
  shift: boolean,
  at: number,
  last: number,
): number | "clear" | null {
  if (key === "Escape") return "clear";
  const step = shift ? 10 : 1;
  const next =
    key === "ArrowLeft"
      ? at - step
      : key === "ArrowRight"
        ? at + step
        : key === "Home"
          ? 0
          : key === "End"
            ? last
            : null;
  return next === null ? null : Math.max(0, Math.min(last, next));
}

export function useKeyWalk({
  at,
  last,
  set,
}: {
  /** The point read now, or null when nothing is. */
  at: number | null;
  /** The last point's index; below 0 there is nothing to walk. */
  last: number;
  set: (index: number | null) => void;
}) {
  const [keyed, setKeyed] = useState(false);
  const quiet = useCallback(() => setKeyed(false), []);
  const props = {
    tabIndex: last >= 0 ? 0 : -1,
    onKeyDown: (event: KeyboardEvent) => {
      if (last < 0) return;
      const next = keyStep(event.key, event.shiftKey, at ?? last, last);
      if (next === null) return;
      event.preventDefault();
      setKeyed(next !== "clear");
      set(next === "clear" ? null : next);
    },
    onFocus: (event: FocusEvent<Element>) => {
      if (last < 0 || !event.currentTarget.matches(":focus-visible")) return;
      setKeyed(true);
      if (at === null) set(last);
    },
    onBlur: () => {
      setKeyed(false);
      set(null);
    },
  };
  return { props, keyed, quiet };
}

/**
 * The polite live region a keyed readout is spoken through: always mounted, so
 * the first step is announced too, and empty unless `text` is given.
 */
export function Spoken({ text }: { text: string | null }) {
  return (
    <span className="ag-sr" aria-live="polite">
      {text ?? ""}
    </span>
  );
}
