/**
 * A finger's reading outlives the finger.
 *
 * On a phone the hand is over the plot for as long as it scrubs, so the
 * figures are only really read once it lifts: a chart that cleared its
 * crosshair on the lift showed the reading only while it could not be seen.
 * So a touch leaves the last day up, and this puts it away the moment the
 * reader touches anywhere else on the page — the one dismissal a phone has,
 * since tapping blank page moves no focus on iOS and no pointer ever leaves.
 *
 * `held` is whether a reading is up; `clear` is called with null to drop it
 * (a state setter, so it is stable and the listener is not re-bound on every
 * move of the scrub).
 */

import { type RefObject, useEffect } from "react";

export function useTouchHold(
  plot: RefObject<Element | null>,
  held: boolean,
  clear: (none: null) => void,
): void {
  useEffect(() => {
    if (!held || typeof document === "undefined") return;
    const away = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && plot.current?.contains(target)) return;
      clear(null);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [held, plot, clear]);
}
