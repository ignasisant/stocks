/**
 * The answers kept between visits (`shell/keep`), through `shell/api`: what a
 * screen opening may be shown before the network answers, and whose it is.
 *
 * Node only, like the other shell tests — `fetch` is stubbed and the shelf is a
 * Map, since there is no IndexedDB here.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fromKept, get, invalidate, withMemo } from "./api";
import { setShelf, type Kept, type Shelf } from "./keep";

function ok(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers(),
    json: async () => body,
  } as unknown as Response;
}

function mapShelf() {
  const answers = new Map<string, Kept>();
  let meta: { owner: string; build: string } | undefined;
  const shelf: Shelf = {
    read: async (url) => answers.get(url),
    write: async (kept) => {
      answers.set(kept.url, kept);
    },
    meta: async () => meta,
    reset: async (next) => {
      answers.clear();
      meta = next;
    },
    trim: async () => undefined,
  };
  return { shelf, answers };
}

/** A fetch whose answers are released by hand, one URL at a time. */
function held(bodies: Record<string, unknown>) {
  const waiting = new Map<string, () => void>();
  const stub = vi.fn(
    (url: string) =>
      new Promise<Response>((resolve) => {
        if (url.endsWith("/me")) resolve(ok(bodies[url]));
        else waiting.set(url, () => resolve(ok(bodies[url])));
      }),
  );
  return { stub, release: (url: string) => waiting.get(url)?.() };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

/** A live `/me` landing, as the session's first fetch does. */
async function signIn() {
  await withMemo(() => get("/me"));
  await flush();
}

describe("kept answers", () => {
  let store: ReturnType<typeof mapShelf>;

  beforeEach(() => {
    store = mapShelf();
    setShelf(store.shelf);
  });

  afterEach(() => {
    invalidate();
    setShelf(null);
    vi.unstubAllGlobals();
  });

  it("answers a first open from the last visit, while the live request runs", async () => {
    const { stub, release } = held({
      "/api/v1/me": { kind: "session", email: "a@x" },
      "/api/v1/book": { n: 2 },
    });
    vi.stubGlobal("fetch", stub);
    await signIn();
    const at = Date.now() - 3_600_000;
    store.answers.set("/api/v1/book", { url: "/api/v1/book", at, body: { n: 1 } });

    const first = fromKept(() => get("/book"));
    expect(await first.answer).toEqual({ n: 1 });
    expect(first.keptAt()).toBe(at);

    // The same request, still out: the second run joins it.
    const live = withMemo(() => get("/book"));
    release("/api/v1/book");
    expect(await live).toEqual({ n: 2 });
    expect(stub).toHaveBeenCalledTimes(2);
    await flush();
    expect(store.answers.get("/api/v1/book")?.body).toEqual({ n: 2 });
  });

  it("is live, not kept, when nothing was kept", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        ok(url.endsWith("/me") ? { kind: "guest" } : { n: 3 }),
      ),
    );
    await signIn();
    const first = fromKept(() => get("/book"));
    expect(await first.answer).toEqual({ n: 3 });
    expect(first.keptAt()).toBeNull();
  });

  it("answers nothing before /me has said who is asking", async () => {
    const { stub, release } = held({ "/api/v1/book": { n: 2 } });
    vi.stubGlobal("fetch", stub);
    store.answers.set("/api/v1/book", {
      url: "/api/v1/book",
      at: Date.now(),
      body: { n: 1 },
    });
    const first = fromKept(() => get("/book"));
    release("/api/v1/book");
    expect(await first.answer).toEqual({ n: 2 });
    expect(first.keptAt()).toBeNull();
  });

  it("empties the shelf for a different account", async () => {
    const me = { kind: "session", email: "a@x" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ok(url.endsWith("/me") ? me : { n: 9 })),
    );
    await signIn();
    await withMemo(() => get("/book"));
    await flush();
    expect(store.answers.has("/api/v1/book")).toBe(true);

    invalidate();
    me.email = "b@x";
    await signIn();
    expect(store.answers.size).toBe(0);
  });

  it("never answers /me from the shelf", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ok({ kind: "session", email: "a@x" })),
    );
    await signIn();
    store.answers.set("/api/v1/me", {
      url: "/api/v1/me",
      at: Date.now(),
      body: { kind: "session", email: "someone@else" },
    });
    invalidate();
    const first = fromKept(() => get("/me"));
    expect(await first.answer).toEqual({ kind: "session", email: "a@x" });
    expect(first.keptAt()).toBeNull();
  });

  it("ignores an answer older than a week", async () => {
    const { stub, release } = held({
      "/api/v1/me": { kind: "guest" },
      "/api/v1/book": { n: 2 },
    });
    vi.stubGlobal("fetch", stub);
    await signIn();
    store.answers.set("/api/v1/book", {
      url: "/api/v1/book",
      at: Date.now() - 8 * 86_400_000,
      body: { n: 1 },
    });
    const first = fromKept(() => get("/book"));
    release("/api/v1/book");
    expect(await first.answer).toEqual({ n: 2 });
  });
});
