/**
 * Put a scroll back where the reader left it, and hold it there while what it
 * scrolls fills in.
 *
 * A screen comes back before its content does: a lazy page renders a
 * skeleton, the kept figures arrive a moment later, a chat thread draws its
 * charts after its text. Set once, the scroll is clamped to whatever was tall
 * enough on that frame and lands short — or it lands, and the browser's scroll
 * anchoring then carries it down with whatever element it happened to sit on
 * as the cards above grow to their real height. So it is put back each frame
 * it drifts, for `SETTLE_MS`, and never against the reader: the first wheel,
 * touch, press or key of theirs ends it.
 */

const SETTLE_MS = 2000;

const INPUT = ["wheel", "touchstart", "pointerdown", "keydown"] as const;

/** Scroll `target` (the page, or a scrolling region) to `y`. Returns the stop. */
export function holdScroll(target: Window | HTMLElement, y: number): () => void {
  const put = () => {
    if (target instanceof HTMLElement) target.scrollTop = y;
    else target.scrollTo(0, y);
  };
  // The top is always there to land on, and holding it would fight a page
  // that scrolls itself to what its link pointed at.
  if (y <= 0) {
    put();
    return () => {};
  }
  const got = () => (target instanceof HTMLElement ? target.scrollTop : target.scrollY);
  const until = performance.now() + SETTLE_MS;
  let frame = 0;
  const stop = () => {
    cancelAnimationFrame(frame);
    for (const name of INPUT) window.removeEventListener(name, stop, true);
  };
  const step = () => {
    if (Math.abs(got() - y) > 2) put();
    if (performance.now() < until) frame = requestAnimationFrame(step);
    else stop();
  };
  // Anywhere, not only on what is held: the composer and the way back down sit
  // outside a chat thread's scrolling region.
  for (const name of INPUT)
    window.addEventListener(name, stop, { capture: true, passive: true });
  step();
  return stop;
}
