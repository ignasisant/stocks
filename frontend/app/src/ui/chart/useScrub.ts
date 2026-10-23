/**
 * How every chart is read: the one scrub behaviour.
 *
 * A pointer reads the day under it (a crosshair and the hover box), a finger
 * leaves its last reading up until the reader touches elsewhere, and the
 * keyboard walks the points. The three used to be wired by hand beside each
 * chart; this is the one place they are, so a chart cannot have the pointer
 * and forget the keys or the phone.
 *
 * - touch hold (`shell/useTouchHold`): `held` says a reading is up, `drop`
 *   puts it away on the next touch anywhere else;
 * - key walk (`shell/useKeyWalk`): arrows ±1, shift ±10, Home/End, Escape,
 *   and a keyboard focus opens the readout on the last point;
 * - what is spoken (`Spoken`) is only what a key moved to: `keyed` is false
 *   the moment a pointer takes over (`quiet`).
 */

import { type RefObject } from "react";
import { useKeyWalk } from "../../shell/useKeyWalk";
import { useTouchHold } from "../../shell/useTouchHold";

export { Spoken } from "../../shell/useKeyWalk";

export function useScrub({
  plot,
  at,
  last,
  set,
  held,
  drop,
}: {
  /** The element a touch counts as "on the chart". */
  plot: RefObject<Element | null>;
  /** The point read now, or null. */
  at: number | null;
  /** The last point's index; below 0 there is nothing to walk. */
  last: number;
  /** Moves the readout to a point, or puts it away with null. */
  set: (index: number | null) => void;
  /** Whether a reading is up that a touch elsewhere should put away. */
  held: boolean;
  /** Puts away everything a finger left up (crosshair, measured span). */
  drop: (none: null) => void;
}) {
  useTouchHold(plot, held, drop);
  return useKeyWalk({ at, last, set });
}
