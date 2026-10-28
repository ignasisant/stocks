/**
 * Run `fn` once the browser has nothing more pressing — after the first
 * paint and the page's own requests — and within `timeout` ms regardless.
 * Returns the cancel. `setTimeout` where `requestIdleCallback` is missing
 * (Safari before 18), a beat later rather than at once: the point is to let
 * the paint go first.
 */
export function onIdle(fn: () => void, timeout = 2000): () => void {
  if (typeof requestIdleCallback === "function") {
    const id = requestIdleCallback(() => fn(), { timeout });
    return () => cancelIdleCallback(id);
  }
  const id = setTimeout(fn, 250);
  return () => clearTimeout(id);
}
