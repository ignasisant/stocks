/**
 * The measuring gesture every time-series chart shares: what moved between
 * two dates.
 *
 * On a touch screen it is two fingers on the plot, one on each date, read live
 * as they slide; lifting one freezes the span instead of falling back to the
 * reading under the finger still down, and the chart's own hold (see
 * `useTouchHold`) keeps it up after the lift like any reading. With a mouse it
 * is the secondary click — a trackpad's two-finger click — which drops an
 * anchor; the span then runs from it to the pointer until another secondary
 * click or the pointer leaving puts it away.
 *
 * The chart owns its pointer handlers and calls these first, each with the
 * pointer's x already in the chart's own units; one that returns true has
 * consumed the event and the chart's handler stops there. Passing no
 * `onSpan` makes every one a no-op that consumes nothing, so a chart can wire
 * the hook unconditionally and keep the browser's context menu.
 */

import { type MouseEvent, type PointerEvent, useRef } from "react";

/**
 * Two points on the x axis the reader is comparing, in the chart's units, in
 * the order they were placed.
 */
export type Span = [number, number];

export type SpanHandlers = {
  /** A pointer moved. True while two fingers measure: no reading under them. */
  move: (event: PointerEvent<Element>, x: number) => boolean;
  /**
   * A pointer went down. True for a second finger (the measure starts) and for
   * a mouse's secondary button (never a drag); a fresh single touch puts a
   * previous comparison away and returns false, so it still reads its bar.
   */
  down: (event: PointerEvent<Element>, x: number) => boolean;
  /** A pointer went up. True for a mouse's secondary button. */
  up: (event: PointerEvent<Element>) => boolean;
  /** The pointer left. A finger lifting is a leave too. */
  leave: (event: PointerEvent<Element>) => void;
  cancel: (event: PointerEvent<Element>) => void;
  /** The secondary click: drop the anchor, or put it and its span away. */
  menu: ((event: MouseEvent<Element>, x: number) => void) | undefined;
};

export function useSpan(onSpan?: (span: Span | null) => void): SpanHandlers {
  // The fingers on the plot right now, by pointer id, and whether this touch
  // became a two-finger one.
  const fingers = useRef(new Map<number, number>());
  const measuring = useRef(false);
  // The mouse's anchor, dropped by a secondary click.
  const anchor = useRef<number | null>(null);

  const pair = (): Span | null => {
    const [a, b] = [...fingers.current.values()];
    return a === undefined || b === undefined ? null : [a, b];
  };

  const lift = (id: number) => {
    fingers.current.delete(id);
    if (fingers.current.size === 0) measuring.current = false;
  };

  return {
    move(event, x) {
      if (!onSpan) return false;
      if (event.pointerType === "touch") {
        if (!fingers.current.has(event.pointerId)) return false;
        fingers.current.set(event.pointerId, x);
        if (!measuring.current) return false;
        const span = pair();
        if (span) onSpan(span);
        return true;
      }
      if (anchor.current !== null) onSpan([anchor.current, x]);
      return false;
    },
    down(event, x) {
      if (!onSpan) return false;
      if (event.pointerType === "touch") {
        fingers.current.set(event.pointerId, x);
        if (fingers.current.size >= 2) {
          measuring.current = true;
          const span = pair();
          if (span) onSpan(span);
          return true;
        }
        onSpan(null);
        return false;
      }
      return event.button !== 0;
    },
    up(event) {
      if (event.pointerType === "touch") {
        lift(event.pointerId);
        return false;
      }
      return Boolean(onSpan) && event.button !== 0;
    },
    leave(event) {
      if (event.pointerType === "touch") {
        lift(event.pointerId);
        return;
      }
      if (anchor.current !== null) {
        anchor.current = null;
        onSpan?.(null);
      }
    },
    cancel(event) {
      lift(event.pointerId);
    },
    menu: onSpan
      ? (event, x) => {
          event.preventDefault();
          if (anchor.current === null) {
            anchor.current = x;
            onSpan([x, x]);
          } else {
            anchor.current = null;
            onSpan(null);
          }
        }
      : undefined,
  };
}
