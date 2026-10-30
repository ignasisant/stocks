/**
 * The touch half of the measuring gesture: a finger held still drops the
 * anchor and the slide that follows is the span, while a finger that moves
 * first stays the one-day scrub.
 */

import type { PointerEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HOLD_MS, type Span, spanHandlers, spanState } from "./useSpan";

function touch(id: number, clientX = 0, clientY = 0) {
  return {
    pointerType: "touch",
    pointerId: id,
    clientX,
    clientY,
  } as PointerEvent<Element>;
}

function setup() {
  const seen: (Span | null)[] = [];
  const onSpan = (span: Span | null) => seen.push(span);
  const state = spanState();
  return { seen, state, span: spanHandlers(state, () => onSpan) };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useSpan on touch", () => {
  it("drops the anchor after a still hold and measures the slide from it", () => {
    const { seen, span } = setup();
    expect(span.down(touch(1, 100, 50), 10)).toBe(false);
    expect(span.move(touch(1, 103, 51), 10)).toBe(false);
    vi.advanceTimersByTime(HOLD_MS);
    expect(seen.at(-1)).toEqual([10, 10]);
    expect(span.move(touch(1, 160, 50), 25)).toBe(true);
    expect(seen.at(-1)).toEqual([10, 25]);
  });

  it("keeps the span when the finger lifts", () => {
    const { seen, state, span } = setup();
    span.down(touch(1), 4);
    vi.advanceTimersByTime(HOLD_MS);
    span.move(touch(1, 50), 9);
    span.up(touch(1, 50));
    span.leave(touch(1, 50));
    expect(seen.at(-1)).toEqual([4, 9]);
    expect(state.pinned).toBeNull();
    expect(state.unblock).toBeNull();
  });

  it("leaves a quick swipe to the scrub", () => {
    const { seen, span } = setup();
    span.down(touch(1, 100, 50), 10);
    span.move(touch(1, 130, 50), 14);
    vi.advanceTimersByTime(HOLD_MS);
    expect(span.move(touch(1, 160, 50), 18)).toBe(false);
    expect(seen).toEqual([null]);
  });

  it("drops no anchor for a finger lifted before the hold", () => {
    const { seen, span } = setup();
    span.down(touch(1), 10);
    span.up(touch(1));
    vi.advanceTimersByTime(HOLD_MS);
    expect(seen).toEqual([null]);
  });

  it("still measures between two fingers", () => {
    const { seen, span } = setup();
    span.down(touch(1), 3);
    expect(span.down(touch(2), 12)).toBe(true);
    expect(seen.at(-1)).toEqual([3, 12]);
    vi.advanceTimersByTime(HOLD_MS);
    expect(seen.at(-1)).toEqual([3, 12]);
  });
});
