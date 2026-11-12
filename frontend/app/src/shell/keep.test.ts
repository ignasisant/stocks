/**
 * The answers kept between visits (`shell/keep`), through `shell/api`: what a
 * screen opening may be shown before the network answers, and whose it is.
 *
 * Node only, like the other shell tests — `fetch` is stubbed and the shelf is a
 * Map, since there is no IndexedDB here.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fromKept, get, invalidate, withMemo } from "./api";
import { forgetKept, setShelf, stow, stowed, type Kept, type Shelf } from "./keep";

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
    reset: async (next, spare) => {
      for (const key of [...answers.keys()]) {
        if (!spare || !key.startsWith(spare)) answers.delete(key);
      }
      meta = next;
    },
    trim: async (max, prefix = "") => {
      const under = [...answers.values()]
        .filter((kept) => kept.url.startsWith(prefix))
        .sort((a, b) => a.at - b.at);
      for (const kept of under.slice(0, Math.max(0, under.length - max))) {
        answers.delete(kept.url);
      }
    },
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

  it("empties the shelf when a screen painted from it crashed", async () => {
    // The crash cancels the live request that would have replaced the kept
    // answer, so without this every launch repaints the one that threw.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        ok(url.endsWith("/me") ? { kind: "session", email: "a@x" } : { tiles: [] }),
      ),
    );
    await signIn();
    store.answers.set("/api/v1/home/market", {
      url: "/api/v1/home/market",
      at: Date.now(),
      body: { score: 50 },
    });
    expect(await fromKept(() => get("/home/market")).answer).toEqual({ score: 50 });

    forgetKept();
    await flush();
    expect(store.answers.size).toBe(0);

    invalidate();
    await signIn();
    const next = fromKept(() => get("/home/market"));
    expect(await next.answer).toEqual({ tiles: [] });
    expect(next.keptAt()).toBeNull();
  });

  it("keeps the shelf through a crash it played no part in", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        ok(url.endsWith("/me") ? { kind: "guest" } : { n: 3 }),
      ),
    );
    await signIn();
    await withMemo(() => get("/book"));
    await flush();
    forgetKept();
    await flush();
    expect(store.answers.has("/api/v1/book")).toBe(true);
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

describe("the reader's own things", () => {
  let store: ReturnType<typeof mapShelf>;
  const me = { kind: "session", email: "a@x" };

  beforeEach(() => {
    store = mapShelf();
    setShelf(store.shelf);
    me.email = "a@x";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ok(url.endsWith("/me") ? me : { n: 1 })),
    );
  });

  afterEach(() => {
    invalidate();
    setShelf(null);
    vi.unstubAllGlobals();
  });

  it("are held on the device and handed back", async () => {
    await signIn();
    stow("shot:1", "data:image/jpeg;base64,AAAA");
    await flush();
    expect(await stowed("shot:1")).toBe("data:image/jpeg;base64,AAAA");
    expect(await stowed("shot:2")).toBeUndefined();
  });

  it("are not held before /me has said whose they are", async () => {
    stow("shot:1", "data:image/jpeg;base64,AAAA");
    await flush();
    expect(store.answers.size).toBe(0);
    expect(await stowed("shot:1")).toBeUndefined();
  });

  it("go with the account that stowed them", async () => {
    await signIn();
    stow("shot:1", "data:image/jpeg;base64,AAAA");
    await flush();

    invalidate();
    me.email = "b@x";
    await signIn();
    expect(await stowed("shot:1")).toBeUndefined();
    expect(store.answers.size).toBe(0);
  });

  it("outlive a release that empties the answers", async () => {
    await signIn();
    await withMemo(() => get("/book"));
    stow("shot:1", "data:image/jpeg;base64,AAAA");
    await flush();
    expect(store.answers.has("/api/v1/book")).toBe(true);
    // The shelf as an older build left it.
    const stamped = await store.shelf.meta();
    await store.shelf.reset({ owner: stamped!.owner, build: "an older build" }, "");
    store.answers.set("/api/v1/book", { url: "/api/v1/book", at: Date.now(), body: 1 });
    store.answers.set("own:shot:1", {
      url: "own:shot:1",
      at: Date.now(),
      body: "data:image/jpeg;base64,AAAA",
    });

    invalidate();
    await signIn();
    expect(store.answers.has("/api/v1/book")).toBe(false);
    expect(await stowed("shot:1")).toBe("data:image/jpeg;base64,AAAA");
  });

  it("are forgotten after a week", async () => {
    await signIn();
    store.answers.set("own:shot:1", {
      url: "own:shot:1",
      at: Date.now() - 8 * 86_400_000,
      body: "data:image/jpeg;base64,AAAA",
    });
    expect(await stowed("shot:1")).toBeUndefined();
  });

  it("are two dozen at most, the oldest dropped at the next visit", async () => {
    await signIn();
    for (let i = 0; i < 30; i++) {
      store.answers.set(`own:shot:${i}`, {
        url: `own:shot:${i}`,
        at: Date.now() - (30 - i) * 1000,
        body: "data:image/jpeg;base64,AAAA",
      });
    }
    store.answers.set("/api/v1/book", { url: "/api/v1/book", at: 1, body: 1 });

    invalidate();
    await signIn();
    expect(await stowed("shot:5")).toBeUndefined();
    expect(await stowed("shot:6")).toBe("data:image/jpeg;base64,AAAA");
    expect(await stowed("shot:29")).toBe("data:image/jpeg;base64,AAAA");
    // The answers are counted on their own.
    expect(store.answers.has("/api/v1/book")).toBe(true);
  });
});
