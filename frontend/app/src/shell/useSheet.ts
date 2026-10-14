/**
 * Overlays that leave the way they came, and can be flung away.
 *
 * `usePresence` keeps a closed overlay mounted for as long as its exit runs,
 * marked `data-leaving` for the stylesheet to animate. The exit is a CSS
 * transition, not a keyframe: re-opening mid-exit only drops the mark, and the
 * panel turns back from wherever it had got to instead of restarting.
 *
 * `useSwipeDismiss` lets a finger drag the overlay towards the edge it came
 * from. It follows the finger one to one, resists past its rest position, and
 * on release projects the throw — a quick flick dismisses from a short drag, a
 * slow drag has to cover half the panel — the way an iOS sheet does. Touch and
 * pen only: a mouse drags text, and has a Close button and Esc.
 */

import { type RefObject, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

/** The exit's length (ms), and the stylesheet's: `--ag-leave` in styles.css. */
const LEAVE_MS = 200;

function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Whether to draw an overlay that is `open`, and whether it is on its way out.
 *
 * Mounted from the render that opens it — not an effect later, which would
 * paint one frame without it — and for `LEAVE_MS` after it closes. Under
 * reduced motion there is no exit to wait for.
 */
export function usePresence(open: boolean): { mounted: boolean; leaving: boolean } {
  const [shown, setShown] = useState(open);
  if (open && !shown) setShown(true);
  useEffect(() => {
    if (open || !shown) return;
    const id = window.setTimeout(() => setShown(false), reducedMotion() ? 0 : LEAVE_MS);
    return () => window.clearTimeout(id);
  }, [open, shown]);
  return { mounted: open || shown, leaving: !open && shown };
}

/** Where a throw at `velocity` (px/ms) comes to rest, at UIScrollView's
    normal deceleration rate. */
function projection(velocity: number): number {
  const rate = 0.998;
  return (velocity * rate) / (1 - rate);
}

/** Past the rest position the panel follows less and less of the finger. */
export function rubberBand(offset: number, size: number): number {
  const c = 0.55;
  return -(1 - 1 / ((Math.abs(offset) * c) / size + 1)) * size;
}

/**
 * Whether a release `offset` px along the dismiss direction, moving at
 * `velocity` px/ms, throws a `size` px panel away: where it would coast to has
 * to be past half of it. A flick dismisses from a short drag; a slow drag has
 * to cover the distance; a drag pulled back towards rest stays.
 */
export function flung(offset: number, velocity: number, size: number): boolean {
  return offset > 0 && offset + projection(velocity) > size / 2;
}

/** How far a finger moves before the gesture is taken to be a swipe (px). */
const SLOP = 8;

/**
 * Drag `sheet` along `axis` (right or down) to dismiss it.
 *
 * `handle`, when given, is a selector the drag has to start on: the chat's
 * conversation has code blocks and tables that scroll sideways, so there only
 * the header drags. Elsewhere a gesture that starts mostly across the axis is
 * left to the page, which is how a vertical list inside a side panel still
 * scrolls.
 */
export function useSwipeDismiss(
  sheet: RefObject<HTMLElement | null>,
  axis: "x" | "y",
  onDismiss: () => void,
  { handle, enabled = true }: { handle?: string; enabled?: boolean } = {},
): void {
  // Read at release, so the listeners are not re-bound on every render that
  // hands a fresh closure.
  const dismiss = useRef(onDismiss);
  dismiss.current = onDismiss;

  useEffect(() => {
    const el = sheet.current;
    if (!el || !enabled) return;

    let id: number | null = null;
    let state: "pending" | "drag" = "pending";
    let start = { x: 0, y: 0 };
    let offset = 0;
    let last = { at: 0, offset: 0 };
    let velocity = 0;

    const size = () => (axis === "x" ? el.offsetWidth : el.offsetHeight) || 1;
    const place = (value: number) => {
      el.style.transform =
        axis === "x"
          ? `translate3d(${value}px, 0, 0)`
          : `translate3d(0, ${value}px, 0)`;
    };

    const down = (event: PointerEvent) => {
      if (event.pointerType === "mouse" || id !== null) return;
      const target = event.target as Element | null;
      if (handle && !target?.closest(handle)) return;
      if (target?.closest("input, textarea, select, [contenteditable]")) return;
      delete el.dataset.swiped;
      id = event.pointerId;
      state = "pending";
      start = { x: event.clientX, y: event.clientY };
      offset = 0;
      velocity = 0;
      last = { at: event.timeStamp, offset: 0 };
    };

    const move = (event: PointerEvent) => {
      if (event.pointerId !== id) return;
      const along = axis === "x" ? event.clientX - start.x : event.clientY - start.y;
      const across = axis === "x" ? event.clientY - start.y : event.clientX - start.x;
      if (state === "pending") {
        if (Math.abs(across) > SLOP && Math.abs(across) >= Math.abs(along)) {
          id = null; // a scroll, not ours
          return;
        }
        if (Math.abs(along) <= SLOP) return;
        state = "drag";
        el.setPointerCapture?.(event.pointerId);
        el.style.transition = "none";
      }
      offset = along >= 0 ? along : rubberBand(along, size());
      place(offset);
      const dt = event.timeStamp - last.at;
      if (dt > 0) velocity = (offset - last.offset) / dt;
      last = { at: event.timeStamp, offset };
    };

    const up = (event: PointerEvent) => {
      if (event.pointerId !== id) return;
      id = null;
      if (state !== "drag") return;
      // The press that ends a drag is not also a tap on what is under it.
      const swallow = (click: Event) => click.stopPropagation();
      window.addEventListener("click", swallow, { capture: true, once: true });
      window.setTimeout(() => window.removeEventListener("click", swallow, true), 0);

      if (event.type === "pointerup" && flung(offset, velocity, size())) {
        // Handed to the exit transition from where the finger let go: the
        // stylesheet's `[data-swiped]` exit runs off the edge, not back.
        el.dataset.swiped = "";
        el.style.transition = "";
        flushSync(() => dismiss.current());
        el.style.transform = "";
        return;
      }
      // Back to rest on a spring-like curve, from wherever it was.
      el.style.transition = "transform 320ms cubic-bezier(0.32, 0.72, 0, 1)";
      el.style.transform = "";
      const settle = () => {
        el.style.transition = "";
        el.removeEventListener("transitionend", settle);
      };
      el.addEventListener("transitionend", settle);
    };

    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    return () => {
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
  }, [sheet, axis, handle, enabled]);
}

/** Less of the window than this hidden (px) is toolbars moving, not a keyboard. */
const KEYBOARD_MIN = 120;

/**
 * Hold a full-height overlay to the part of the screen the keyboard leaves.
 *
 * iOS does not shrink the layout viewport for its keyboard: a fixed panel
 * keeps its full height, the composer at its foot goes under the keys, and
 * Safari pans the whole page up to show the field — the header with it. While
 * the visual viewport is short by a keyboard, the panel is sized and placed to
 * it instead (`data-keyboard` with `--kb-top` / `--kb-h`, chat.css), and the
 * home indicator's inset is dropped since the keys cover it.
 */
export function useKeyboardFit(
  panel: RefObject<HTMLElement | null>,
  enabled: boolean,
): void {
  useEffect(() => {
    const el = panel.current;
    const vv = typeof window === "undefined" ? undefined : window.visualViewport;
    if (!el || !vv || !enabled) return;
    const fit = () => {
      const hidden = window.innerHeight - vv.height;
      // A pinch-zoom shortens the visual viewport too, with no keyboard.
      if (hidden < KEYBOARD_MIN || vv.scale > 1.01) {
        delete el.dataset.keyboard;
        return;
      }
      el.dataset.keyboard = "";
      el.style.setProperty("--kb-top", `${vv.offsetTop}px`);
      el.style.setProperty("--kb-h", `${vv.height}px`);
    };
    fit();
    vv.addEventListener("resize", fit);
    vv.addEventListener("scroll", fit);
    return () => {
      vv.removeEventListener("resize", fit);
      vv.removeEventListener("scroll", fit);
      delete el.dataset.keyboard;
    };
  }, [panel, enabled]);
}
