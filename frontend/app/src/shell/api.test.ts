/**
 * The GET memo in `api.ts`: what may answer from memory, and what must not.
 *
 * Node only, like the other shell tests — `fetch` is stubbed, no DOM.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  Cancelled,
  TIMEOUT_MS,
  get,
  invalidate,
  isTransient,
  scoped,
  send,
  withMemo,
} from "./api";
import { resetFreshness, staleSince } from "./freshness";

function ok(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers(),
    json: async () => body,
  } as unknown as Response;
}

describe("get memo", () => {
  afterEach(() => {
    invalidate();
    vi.unstubAllGlobals();
  });

  it("shares one request across memoized callers", async () => {
    const stub = vi.fn(async () => ok({ n: 1 }));
    vi.stubGlobal("fetch", stub);
    const [a, b] = await Promise.all([
      withMemo(() => get("/x")),
      withMemo(() => get("/x")),
    ]);
    expect(a).toEqual({ n: 1 });
    expect(b).toEqual({ n: 1 });
    expect(stub).toHaveBeenCalledTimes(1);
    await withMemo(() => get("/x"));
    expect(stub).toHaveBeenCalledTimes(1);
  });

  it("keys on the query as well as the path", async () => {
    const stub = vi.fn(async () => ok({}));
    vi.stubGlobal("fetch", stub);
    await withMemo(() => get("/x", { window: "day" }));
    await withMemo(() => get("/x", { window: "week" }));
    expect(stub).toHaveBeenCalledTimes(2);
  });

  it("a get outside withMemo always reaches the server", async () => {
    const stub = vi.fn(async () => ok({}));
    vi.stubGlobal("fetch", stub);
    await get("/x");
    await get("/x");
    expect(stub).toHaveBeenCalledTimes(2);
  });

  it("a write drops the memo", async () => {
    const stub = vi.fn(async () => ok({}));
    vi.stubGlobal("fetch", stub);
    await withMemo(() => get("/x"));
    await send("POST", "/y", {});
    await withMemo(() => get("/x"));
    expect(stub).toHaveBeenCalledTimes(3);
  });

  it("records how old the server said the figures are", async () => {
    const stub = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ "X-Data-Stale-Since": "2026-09-27T10:00:00+00:00" }),
        json: async () => ({}),
      } as unknown as Response)
      .mockResolvedValue(ok({}));
    vi.stubGlobal("fetch", stub);
    await get("/x");
    expect(staleSince()).toBe(Date.parse("2026-09-27T10:00:00+00:00"));
    await get("/x");
    expect(staleSince()).toBeNull();
    resetFreshness();
  });

  it("a failure is not kept", async () => {
    const stub = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        statusText: "unavailable",
        headers: new Headers(),
        json: async () => ({ detail: "down", reason: "offline" }),
      } as unknown as Response)
      .mockResolvedValue(ok({ n: 2 }));
    vi.stubGlobal("fetch", stub);
    await expect(withMemo(() => get("/x"))).rejects.toThrow("503");
    expect(await withMemo(() => get("/x"))).toEqual({ n: 2 });
    expect(stub).toHaveBeenCalledTimes(2);
  });
});

describe("timeout", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("gives up on a request the server never answers", async () => {
    vi.useFakeTimers();
    // A fetch that only ever ends by being aborted, as a hung upstream does.
    const stub = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_, reject) =>
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          ),
        ),
    );
    vi.stubGlobal("fetch", stub);
    const answer = get("/ticker/MUA/insiders").catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(TIMEOUT_MS + 10);
    const error = await answer;
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ reason: "timeout" });
    expect(isTransient(error)).toBe(true);
  });
});

describe("abandoned requests", () => {
  afterEach(() => {
    invalidate();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  // A fetch that only ends by being aborted, recording that it was.
  function hanging() {
    const aborted: string[] = [];
    const stub = vi.fn(
      (url: string, init: RequestInit) =>
        new Promise<Response>((_, reject) =>
          init.signal?.addEventListener("abort", () => {
            aborted.push(url);
            reject(new DOMException("aborted", "AbortError"));
          }),
        ),
    );
    vi.stubGlobal("fetch", stub);
    return { stub, aborted };
  }

  it("cancels a request once its only caller has left", async () => {
    vi.useFakeTimers();
    const { aborted } = hanging();
    const scope = new AbortController();
    const answer = scoped(scope.signal, () => get("/x")).catch((e: unknown) => e);
    scope.abort();
    await vi.advanceTimersByTimeAsync(1);
    expect(aborted).toEqual(["/api/v1/x"]);
    expect(await answer).toBeInstanceOf(Cancelled);
    expect(isTransient(await answer)).toBe(false);
  });

  it("keeps a shared request for the caller still waiting", async () => {
    vi.useFakeTimers();
    const { stub, aborted } = hanging();
    const one = new AbortController();
    const two = new AbortController();
    void withMemo(() => get("/x"), one.signal).catch(() => undefined);
    void withMemo(() => get("/x"), two.signal).catch(() => undefined);
    expect(stub).toHaveBeenCalledTimes(1);
    one.abort();
    await vi.advanceTimersByTimeAsync(1);
    expect(aborted).toEqual([]);
    two.abort();
    await vi.advanceTimersByTimeAsync(1);
    expect(aborted).toHaveLength(1);
  });

  it("survives a remount that rejoins before the tick", async () => {
    vi.useFakeTimers();
    const { stub, aborted } = hanging();
    const first = new AbortController();
    void withMemo(() => get("/x"), first.signal).catch(() => undefined);
    first.abort();
    void withMemo(() => get("/x"), new AbortController().signal);
    await vi.advanceTimersByTimeAsync(1);
    expect(stub).toHaveBeenCalledTimes(1);
    expect(aborted).toEqual([]);
  });

  it("never cancels a request somebody asked for unscoped", async () => {
    vi.useFakeTimers();
    const { aborted } = hanging();
    const scope = new AbortController();
    void withMemo(() => get("/x"), scope.signal).catch(() => undefined);
    void withMemo(() => get("/x")).catch(() => undefined);
    scope.abort();
    await vi.advanceTimersByTimeAsync(1);
    expect(aborted).toEqual([]);
  });

  it("a cancelled request is not kept in the memo", async () => {
    vi.useFakeTimers();
    hanging();
    const scope = new AbortController();
    const answer = withMemo(() => get("/x"), scope.signal).catch(() => undefined);
    scope.abort();
    await vi.advanceTimersByTimeAsync(1);
    await answer;
    const stub = vi.fn(async () => ok({ n: 1 }));
    vi.stubGlobal("fetch", stub);
    expect(await withMemo(() => get("/x"))).toEqual({ n: 1 });
    expect(stub).toHaveBeenCalledTimes(1);
  });
});
