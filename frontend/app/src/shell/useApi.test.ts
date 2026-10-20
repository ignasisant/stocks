/**
 * A stale answer is asked for again until it comes back live.
 *
 * The server refreshes behind every stale answer it gives, so the page asks
 * again a little later and swaps the figures in — quietly, a few times, then
 * it stops and leaves the stale line to say how old they are.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  currentRetry,
  noteFreshness,
  noteRefreshing,
  onRetryStale,
  resetFreshness,
  staleSince,
} from "./freshness";
import { FOLLOW_MS, followStale, retryNow } from "./useApi";

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

  it("asks again behind an answer the server is refreshing, not after", async () => {
    noteRefreshing("/v1/book", "1");
    let asks = 0;
    const ask = () => {
      asks += 1;
      noteRefreshing("/v1/book", null);
      return { result: Promise.resolve(asks), urls: new Set(["/v1/book"]) };
    };
    const shown: number[] = [];
    followStale(new Set(["/v1/book"]), ask, (n) => shown.push(n));
    await vi.advanceTimersByTimeAsync(FOLLOW_MS[0]);
    expect(shown).toEqual([1]);
    await vi.runAllTimersAsync();
    expect(asks).toBe(1);
  });

  it("stops when the screen goes away", async () => {
    noteFreshness("/v1/book", OLD);
    const api = server(Infinity);
    const stop = followStale(new Set(["/v1/book"]), api.ask, () => undefined);
    stop();
    await vi.runAllTimersAsync();
    expect(api.asks()).toBe(0);
  });

  it("says when the next try is due, while it is out, and when it gave up", async () => {
    vi.setSystemTime(0);
    noteFreshness("/v1/book", OLD);
    let release: (n: number) => void = () => undefined;
    const ask = () => ({
      result: new Promise<number>((resolve) => (release = resolve)),
      urls: new Set(["/v1/book"]),
    });
    const stop = followStale(new Set(["/v1/book"]), ask, () => undefined, "card");
    expect(currentRetry()).toEqual({ due: FOLLOW_MS[0], asking: false });
    await vi.advanceTimersByTimeAsync(FOLLOW_MS[0]);
    expect(currentRetry()).toEqual({ due: null, asking: true });
    release(1);
    await vi.advanceTimersByTimeAsync(0);
    expect(currentRetry().due).toBe(FOLLOW_MS[0] + FOLLOW_MS[1]);
    stop();
    expect(currentRetry()).toEqual({ due: null, asking: false });
  });

  it("announces nothing once the source is back", async () => {
    noteFreshness("/v1/book", OLD);
    const api = server(0);
    followStale(new Set(["/v1/book"]), api.ask, () => undefined, "card");
    await vi.runAllTimersAsync();
    expect(currentRetry()).toEqual({ due: null, asking: false });
  });

  it("a failed try ends the follow and its countdown", async () => {
    noteFreshness("/v1/book", OLD);
    const ask = () => ({
      result: Promise.reject(new Error("down")),
      urls: new Set(["/v1/book"]),
    });
    followStale(new Set(["/v1/book"]), ask, () => undefined, "card");
    await vi.runAllTimersAsync();
    expect(currentRetry()).toEqual({ due: null, asking: false });
  });
});

describe("retryNow", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    resetFreshness();
  });

  /** A server answering `status`, live (no stale header), counting asks. */
  function answering(status: number) {
    const asked: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        asked.push(url);
        return new Response(JSON.stringify({}), { status });
      }),
    );
    return asked;
  }

  it("asks again for a stale URL no screen holds, and the line clears", async () => {
    const asked = answering(200);
    noteFreshness("/api/v1/portfolio/risk", OLD);
    retryNow();
    expect(currentRetry().asking).toBe(true);
    await vi.waitFor(() => expect(currentRetry().asking).toBe(false));
    expect(asked).toEqual(["/api/v1/portfolio/risk"]);
    expect(staleSince()).toBeNull();
  });

  it("leaves a URL a screen took to that screen", async () => {
    const asked = answering(200);
    noteFreshness("/api/v1/portfolio/summary", OLD);
    const stop = onRetryStale(() => ["/api/v1/portfolio/summary"]);
    retryNow();
    stop();
    expect(asked).toEqual([]);
  });

  it("drops the mark of a URL that now fails for good", async () => {
    answering(404);
    noteFreshness("/api/v1/gone", OLD);
    retryNow();
    await vi.waitFor(() => expect(currentRetry().asking).toBe(false));
    expect(staleSince()).toBeNull();
  });

  it("keeps the mark while the source is still down", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ reason: "throttled" }), { status: 503 }),
      ),
    );
    noteFreshness("/api/v1/portfolio/risk", OLD);
    retryNow();
    await vi.waitFor(() => expect(currentRetry().asking).toBe(false));
    expect(staleSince()).toBe(Date.parse(OLD));
  });
});
