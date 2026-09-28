/**
 * The GET memo in `api.ts`: what may answer from memory, and what must not.
 *
 * Node only, like the other shell tests — `fetch` is stubbed, no DOM.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { get, invalidate, send, withMemo } from "./api";
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
