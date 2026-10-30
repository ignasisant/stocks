/**
 * The measuring gesture every time-series chart shares: what moved between
 * two dates.
 *
 * On a touch screen it is a finger held still on a date until the anchor drops
 * (`HOLD_MS`), then slid to the other; or two fingers on the plot, one on each
 * date. Either is read live as it slides. A quick swipe stays the scrub that
 * reads one day, and a finger that starts to move before the anchor drops is
 * that swipe. Lifting freezes the span instead of falling back to the reading
 * under a finger still down, and the chart's own hold (see `useTouchHold`)
 * keeps it up after the lift like any reading. With a mouse it is the
 * secondary click — a trackpad's two-finger click — which drops an anchor; the
 * span then runs from it to the pointer until another secondary click or the
 * pointer leaving puts it away.
 *
 * The chart owns its pointer handlers and calls these first, each with the
 * pointer's x already in the chart's own units; one that returns true has
 * consumed the event and the chart's handler stops there. Passing no
 * `onSpan` makes every one a no-op that consumes nothing, so a chart can wire
 * the hook unconditionally and keep the browser's context menu.
 */

import { type MouseEvent, type PointerEvent, useEffect, useState } from "react";

/**
 * Two points on the x axis the reader is comparing, in the chart's units, in
 * the order they were placed.
 */
export type Span = [number, number];

export type SpanHandlers = {
  /** A pointer moved. True while a span is being measured: no reading under it. */
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

/** How long a finger rests on a date before it becomes the span's anchor. */
export const HOLD_MS = 300;

/** How far, in CSS pixels, a resting finger may drift and still be resting. */
const HOLD_SLOP = 8;

/** What the gesture remembers between events. */
export type SpanState = {
  /** The fingers on the plot right now, by pointer id, at their chart x. */
  fingers: Map<number, number>;
  /** Whether this touch became a two-finger one. */
  measuring: boolean;
  /** The finger resting toward an anchor: where it went down, and its timer. */
  resting: {
    id: number;
    clientX: number;
    clientY: number;
    timer: ReturnType<typeof setTimeout>;
  } | null;
  /** The finger that dropped an anchor by resting, and the anchor's x. */
  pinned: { id: number; x: number } | null;
  /** The mouse's anchor, dropped by a secondary click. */
  anchor: number | null;
  /** Stops the page scrolling under a pinned finger; null while none is. */
  unblock: (() => void) | null;
};

export function spanState(): SpanState {
  return {
    fingers: new Map(),
    measuring: false,
    resting: null,
    pinned: null,
    anchor: null,
    unblock: null,
  };
}

/**
 * A pinned finger slides sideways, but nothing stops it drifting down too,
 * and `touch-action: pan-y` would hand that drift to the page as a scroll —
 * cancelling the pointer mid-measure. Touch moves are cancelled at the
 * document until it lifts; the listener has to be native, since React's is
 * passive and cannot.
 */
function blockScroll(): () => void {
  if (typeof document === "undefined") return () => {};
  const stop = (event: TouchEvent) => {
    if (event.cancelable) event.preventDefault();
  };
  document.addEventListener("touchmove", stop, { passive: false });
  return () => document.removeEventListener("touchmove", stop);
}

/** The handlers over `state`; `onSpan` is read at call time, so it may change. */
export function spanHandlers(
  state: SpanState,
  onSpan: () => ((span: Span | null) => void) | undefined,
): SpanHandlers {
  const pair = (): Span | null => {
    const [a, b] = [...state.fingers.values()];
    return a === undefined || b === undefined ? null : [a, b];
  };

  const settle = () => {
    if (state.resting) clearTimeout(state.resting.timer);
    state.resting = null;
  };

  const unpin = () => {
    state.pinned = null;
    state.unblock?.();
    state.unblock = null;
  };

  const lift = (id: number) => {
    state.fingers.delete(id);
    if (state.resting?.id === id) settle();
    if (state.pinned?.id === id) unpin();
    if (state.fingers.size === 0) state.measuring = false;
  };

  return {
    move(event, x) {
      const report = onSpan();
      if (!report) return false;
      if (event.pointerType === "touch") {
        if (!state.fingers.has(event.pointerId)) return false;
        state.fingers.set(event.pointerId, x);
        const rest = state.resting;
        if (
          rest?.id === event.pointerId &&
          Math.hypot(event.clientX - rest.clientX, event.clientY - rest.clientY) >
            HOLD_SLOP
        ) {
          settle();
        }
        if (state.pinned?.id === event.pointerId) {
          report([state.pinned.x, x]);
          return true;
        }
        if (!state.measuring) return false;
        const span = pair();
        if (span) report(span);
        return true;
      }
      if (state.anchor !== null) report([state.anchor, x]);
      return false;
    },
    down(event, x) {
      const report = onSpan();
      if (!report) return false;
      if (event.pointerType === "touch") {
        state.fingers.set(event.pointerId, x);
        if (state.fingers.size >= 2) {
          settle();
          unpin();
          state.measuring = true;
          const span = pair();
          if (span) report(span);
          return true;
        }
        report(null);
        settle();
        const id = event.pointerId;
        state.resting = {
          id,
          clientX: event.clientX,
          clientY: event.clientY,
          timer: setTimeout(() => {
            state.resting = null;
            const at = state.fingers.get(id);
            if (at === undefined || state.fingers.size !== 1) return;
            state.pinned = { id, x: at };
            state.unblock = blockScroll();
            report([at, at]);
            if (typeof navigator !== "undefined") navigator.vibrate?.(8);
          }, HOLD_MS),
        };
        return false;
      }
      return event.button !== 0;
    },
    up(event) {
      if (event.pointerType === "touch") {
        lift(event.pointerId);
        return false;
      }
      return Boolean(onSpan()) && event.button !== 0;
    },
    leave(event) {
      if (event.pointerType === "touch") {
        lift(event.pointerId);
        return;
      }
      if (state.anchor !== null) {
        state.anchor = null;
        onSpan()?.(null);
      }
    },
    cancel(event) {
      lift(event.pointerId);
    },
    menu: onSpan()
      ? (event, x) => {
          event.preventDefault();
          // A long press fires this too on Android: the resting finger is
          // already dropping its own anchor, so the mouse's stays down.
          if (state.fingers.size > 0) return;
          const report = onSpan();
          if (state.anchor === null) {
            state.anchor = x;
            report?.([x, x]);
          } else {
            state.anchor = null;
            report?.(null);
          }
        }
      : undefined,
  };
}

export function useSpan(onSpan?: (span: Span | null) => void): SpanHandlers {
  // A state object, not React state: the gesture mutates it on every pointer
  // event and must not render for it.
  const [state] = useState(spanState);
  useEffect(
    () => () => {
      if (state.resting) clearTimeout(state.resting.timer);
      state.unblock?.();
    },
    [state],
  );
  return spanHandlers(state, () => onSpan);
}
