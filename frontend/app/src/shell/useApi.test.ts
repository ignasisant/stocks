/**
 * A stale answer is asked for again until it comes back live.
 *
 * The server refreshes behind every stale answer it gives, so the page asks
 * again a little later and swaps the figures in — quietly, a few times, then
 * it stops and leaves the stale line to say how old they are.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { noteFreshness, resetFreshness } from "./freshness";
import { FOLLOW_MS, followStale } from "./useApi";

const OLD = "2026-10-11T08:00:00+00:00";

/** A server whose answers stay stale for `staleFor` more asks. */
function server(staleFor: number) {
  let asks = 0;
  return {
    asks: () => asks,
    ask: () => {
      asks += 1;
      noteFreshness("/v1/book", asks <= staleFor ? OLD : null);
      return { result: Promise.resolve(asks), urls: new Set(["/v1/book"]) };
    },
  };
}

describe("followStale", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    resetFreshness();
  });

  it("asks nothing when the answer was live", async () => {
    const api = server(0);
    followStale(new Set(["/v1/book"]), api.ask, () => undefined);
    await vi.runAllTimersAsync();
    expect(api.asks()).toBe(0);
  });

  it("asks again until the answer comes back live, and shows it", async () => {
    noteFreshness("/v1/book", OLD);
    const api = server(1);
    const shown: number[] = [];
    followStale(new Set(["/v1/book"]), api.ask, (n) => shown.push(n));
    await vi.advanceTimersByTimeAsync(FOLLOW_MS[0]);
    expect(shown).toEqual([1]);
    await vi.advanceTimersByTimeAsync(FOLLOW_MS[1]);
    expect(shown).toEqual([1, 2]);
    await vi.runAllTimersAsync();
    expect(api.asks()).toBe(2);
  });

  it("gives up after its last try while the source stays down", async () => {
    noteFreshness("/v1/book", OLD);
    const api = server(Infinity);
    followStale(new Set(["/v1/book"]), api.ask, () => undefined);
    await vi.runAllTimersAsync();
    expect(api.asks()).toBe(FOLLOW_MS.length);
  });

  it("stops when the screen goes away", async () => {
    noteFreshness("/v1/book", OLD);
    const api = server(Infinity);
    const stop = followStale(new Set(["/v1/book"]), api.ask, () => undefined);
    stop();
    await vi.runAllTimersAsync();
    expect(api.asks()).toBe(0);
  });
});
