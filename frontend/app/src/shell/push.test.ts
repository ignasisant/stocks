import { afterEach, describe, expect, it, vi } from "vitest";
import { onSignOut, signOut } from "./keep";
import { claimPush, keyBytes, releasePush, workerTarget } from "./push";

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
