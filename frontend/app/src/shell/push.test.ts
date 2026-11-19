import { afterEach, describe, expect, it, vi } from "vitest";
import { onSignOut, signOut } from "./keep";
import {
  PENDING_MS,
  claimPush,
  keyBytes,
  pendingPress,
  pressTaker,
  releasePush,
  takePending,
  workerTarget,
} from "./push";

describe("keyBytes", () => {
  it("reads base64url without padding, as the server sends the VAPID key", () => {
    // 0xfb 0xff 0xbf is "-_-_" in base64url and "+/+/" in plain base64.
    expect(Array.from(keyBytes("-_-_"))).toEqual([0xfb, 0xff, 0xbf]);
    expect(Array.from(keyBytes("AQ"))).toEqual([1]);
  });

  it("is the 65-byte uncompressed point a P-256 key encodes to", () => {
    const key = "B" + "A".repeat(86);
    expect(keyBytes(key).length).toBe(65);
    expect(keyBytes(key)[0]).toBe(4);
  });
});

describe("workerTarget", () => {
  it("is the path a pressed notification points at", () => {
    expect(workerTarget({ type: "open", url: "/?thread=c_1a2b3c4d" })).toBe(
      "/?thread=c_1a2b3c4d",
    );
  });

  it("takes only a path on this site, and only the worker's own message", () => {
    expect(
      workerTarget({ type: "open", url: "https://elsewhere.example/" }),
    ).toBeNull();
    expect(workerTarget({ type: "open", url: "//elsewhere.example/" })).toBeNull();
    expect(workerTarget({ type: "other", url: "/today" })).toBeNull();
    expect(workerTarget({ type: "open" })).toBeNull();
    expect(workerTarget(null)).toBeNull();
  });
});

describe("the worker's note of a press", () => {
  const NOW = 1_000_000;

  it("is the page a press just now pointed at", () => {
    expect(pendingPress({ url: "/review?thread=c_1", at: NOW - 3_000 }, NOW)).toEqual({
      url: "/review?thread=c_1",
      at: NOW - 3_000,
    });
  });

  it("is nothing once it is old, malformed or off the site", () => {
    expect(
      pendingPress({ url: "/?thread=c_1", at: NOW - PENDING_MS - 1 }, NOW),
    ).toBeNull();
    expect(pendingPress({ url: "/?thread=c_1" }, NOW)).toBeNull();
    expect(
      pendingPress({ url: "https://elsewhere.example/", at: NOW }, NOW),
    ).toBeNull();
    expect(pendingPress(null, NOW)).toBeNull();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("is taken once: the second look finds nothing", async () => {
    const store = new Map<string, string>();
    store.set(
      "/__push/pending",
      JSON.stringify({ url: "/?thread=c_1", at: Date.now() }),
    );
    vi.stubGlobal("caches", {
      open: async () => ({
        match: async (key: string) => {
          const body = store.get(key);
          return body === undefined
            ? undefined
            : { json: async () => JSON.parse(body) };
        },
        delete: async (key: string) => store.delete(key),
      }),
    });
    expect((await takePending())?.url).toBe("/?thread=c_1");
    expect(await takePending()).toBeNull();
  });
});

describe("taking a press", () => {
  function taker(boot = "/today") {
    const went: string[] = [];
    const via: string[] = [];
    const take = pressTaker(
      boot,
      (url) => went.push(url),
      (v) => via.push(v),
    );
    return { take, went, via };
  }

  it("opens a press once, though it comes as a message and as a note", () => {
    const { take, went, via } = taker();
    const press = { url: "/?thread=c_1", at: 5 };
    expect(take(press, "message")).toBe(true);
    expect(take(press, "pending")).toBe(false);
    expect(went).toEqual(["/?thread=c_1"]);
    expect(via).toEqual(["message"]);
  });

  it("opens the next answer on the same thread too", () => {
    const { take, went } = taker();
    take({ url: "/?thread=c_1", at: 5 }, "pending");
    take({ url: "/?thread=c_1", at: 9 }, "pending");
    expect(went).toEqual(["/?thread=c_1", "/?thread=c_1"]);
  });

  it("leaves alone the note of a press that opened this very window", () => {
    const { take, went, via } = taker("/?thread=c_1");
    expect(take({ url: "/?thread=c_1", at: 5 }, "pending")).toBe(false);
    expect(went).toEqual([]);
    expect(via).toEqual([]);
    // A later press on that thread is a new one.
    expect(take({ url: "/?thread=c_1", at: 9 }, "pending")).toBe(true);
  });

  it("does nothing with nothing", () => {
    const { take, went } = taker();
    expect(take(null, "pending")).toBe(false);
    expect(went).toEqual([]);
  });
});

/* ------------------------------------------------------ whose device */

const ENDPOINT = "https://push.example/send/abc";

type Call = { url: string; method: string; body: unknown; keepalive: boolean };

/** A browser holding `endpoint` as its subscription (none: null), and what it sent. */
function device(endpoint: string | null) {
  const calls: Call[] = [];
  vi.stubGlobal("window", { PushManager: {}, Notification: {} });
  vi.stubGlobal("navigator", {
    serviceWorker: {
      getRegistration: async () => ({
        pushManager: {
          getSubscription: async () => (endpoint ? { endpoint } : null),
        },
      }),
    },
  });
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({
      url: String(url),
      method: init.method ?? "GET",
      body: init.body ? JSON.parse(String(init.body)) : undefined,
      keepalive: init.keepalive === true,
    });
    return { ok: true, status: 204, headers: new Headers() } as unknown as Response;
  });
  return calls;
}

describe("whose device this is", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("claims the device's subscription for the account signed in", async () => {
    const calls = device(ENDPOINT);
    await claimPush();
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "POST", body: { endpoint: ENDPOINT } });
    expect(calls[0]?.url).toMatch(/\/push\/claim$/);
  });

  it("releases it with a request that outlives the page", async () => {
    const calls = device(ENDPOINT);
    await releasePush();
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "POST",
      body: { endpoint: ENDPOINT },
      keepalive: true,
    });
    expect(calls[0]?.url).toMatch(/\/push\/release$/);
  });

  it("says nothing for a device that never subscribed", async () => {
    const calls = device(null);
    await claimPush();
    await releasePush();
    expect(calls).toEqual([]);
  });
});

describe("signing out", () => {
  afterEach(() => vi.unstubAllGlobals());

  /** Sign out with `task` registered; the order things happened in. */
  async function leave(task: (did: string[]) => Promise<unknown>) {
    const did: string[] = [];
    vi.stubGlobal("window", {
      location: { assign: (to: string) => did.push(`go ${to}`) },
    });
    vi.stubGlobal("fetch", async (url: string) => {
      did.push(`post ${url}`);
      return { ok: true, status: 204 } as unknown as Response;
    });
    const off = onSignOut(() => task(did));
    try {
      await signOut();
    } finally {
      off();
    }
    return did;
  }

  it("runs what needs the session before the session ends", async () => {
    const did = await leave(async (log) => {
      await Promise.resolve();
      log.push("release");
    });
    expect(did).toEqual(["release", "post /auth/logout", "go /"]);
  });

  it("still signs out when that fails", async () => {
    const did = await leave(async () => {
      throw new Error("offline");
    });
    expect(did).toEqual(["post /auth/logout", "go /"]);
  });

  it("does not wait for ever on it", async () => {
    vi.useFakeTimers();
    try {
      const left = leave(() => new Promise(() => undefined));
      await vi.advanceTimersByTimeAsync(1_000);
      expect(await left).toEqual(["post /auth/logout", "go /"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("forgets a task that was taken back", async () => {
    const ran: string[] = [];
    onSignOut(async () => ran.push("release"))();
    await leave(async () => undefined);
    expect(ran).toEqual([]);
  });
});
