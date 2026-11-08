/**
 * A typed value once the typing stops.
 *
 * Every ticker field asks a search per settled value, not per keystroke: a
 * five-letter symbol is one request, not five, and a shared cloud IP that asks
 * Yahoo per keystroke gets throttled. An empty value settles at once —
 * clearing a field asks for nothing, so there is nothing to wait for.
 */

import { useEffect, useState } from "react";

/** The wait between the last keystroke and the request it settles into. */
export const TYPING_MS = 220;

export function useDebounced<T>(value: T, ms: number = TYPING_MS): T {
  const [settled, setSettled] = useState(value);
  const empty = value === "" || value === null || value === undefined;
  useEffect(() => {
    if (empty) {
      setSettled(value);
      return;
    }
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms, empty]);
  return empty ? value : settled;
}
