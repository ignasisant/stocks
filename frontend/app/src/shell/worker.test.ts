/**
 * The service worker's answer to a pressed notification (`/sw.js`): the open
 * window is sent to the notification's page, whatever the browser lets the
 * worker do with that window.
 *
 * The worker is one plain script with `self` as its only global, so it is run
 * here against a stand-in for it.
 */

import { describe, expect, it } from "vitest";
import SOURCE from "../../../../src/stocks/web/assets/sw.js?raw";

const ORIGIN = "https://app.example";
const THREAD = "/?thread=c_1a2b3c4d";

type Client = {
  url: string;
  focus: () => Promise<unknown>;
  navigate?: (url: string) => Promise<unknown>;
  postMessage: (message: unknown) => void;
};

/** The worker's message to a window, without its timestamp. */
function said(message: unknown): string {
  const { at, ...rest } = message as { at?: unknown };
  return `message ${JSON.stringify(rest)}${typeof at === "number" ? " @" : ""}`;
}

const OPEN = said({ type: "open", url: THREAD, at: 1 });

/**
 * A window of the app and what the worker did to it. `answers`: the app's
 * shell is running there and says it took the press (`useWorkerOpen`).
 */
function appWindow(over: Partial<Client> = {}, answers = true) {
  const did: string[] = [];
  let reply: ((at: number) => void) | null = null;
  const client: Client = {
    url: `${ORIGIN}/portfolio`,
    focus: async () => did.push("focus"),
    navigate: async (url) => did.push(`navigate ${url}`),
    postMessage: (message) => {
      did.push(said(message));
      if (answers) reply?.((message as { at: number }).at);
    },
    ...over,
  };
  return { client, did, wire: (fn: (at: number) => void) => (reply = fn) };
}

type Win = ReturnType<typeof appWindow>;

/** Press a notification pointing at `url` with `open` windows on screen. */
async function press(open: Win[], url = THREAD, cacheWorks = true) {
  const handlers: Record<string, (event: unknown) => void> = {};
  const opened: string[] = [];
  const noted: Record<string, unknown> = {};
  const reported: unknown[] = [];
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (name: string, handler: (event: unknown) => void) => {
      handlers[name] = handler;
    },
    skipWaiting: () => undefined,
    caches: {
      open: async () => {
        if (!cacheWorks) throw new Error("no Cache API");
        return {
          put: async (key: string, response: Response) => {
            noted[key] = await response.json();
          },
        };
      },
    },
    clients: {
      claim: async () => undefined,
      matchAll: async () => open.map((w) => w.client),
      openWindow: async (href: string) => opened.push(href),
    },
  };
  const fetch = async (_: string, init: RequestInit) => {
    reported.push(JSON.parse(String(init.body)).via);
    return new Response(null, { status: 204 });
  };
  new Function("self", "fetch", SOURCE)(self, fetch);
  for (const w of open) {
    w.wire((at) => handlers.message?.({ data: { type: "took", at } }));
  }
  let settled: Promise<unknown> = Promise.resolve();
  handlers.notificationclick?.({
    action: "",
    notification: { close: () => undefined, data: { url } },
    waitUntil: (work: Promise<unknown>) => {
      settled = work;
    },
  });
  await settled;
  const note = noted["/__push/pending"] as { url?: string; at?: number } | undefined;
  return { opened, note: note ?? null, reported };
}

describe("a pressed notification", () => {
  it("tells the open app to go to the thread, and raises it", async () => {
    const app = appWindow();
    const { opened, reported } = await press([app]);
    expect(opened).toEqual([]);
    expect(app.did).toEqual([OPEN, "focus"]);
    expect(reported).toEqual(["window"]);
  });

  it("leaves a note of the press for an app that wakes up later", async () => {
    const asleep = appWindow({}, false);
    const { note } = await press([asleep]);
    expect(note?.url).toBe(THREAD);
    expect(typeof note?.at).toBe("number");
  });

  it("moves a window that does not answer itself", async () => {
    const silent = appWindow({}, false);
    await press([silent]);
    expect(silent.did).toEqual([OPEN, "focus", `navigate ${ORIGIN}${THREAD}`]);
    const without = appWindow({ navigate: undefined }, false);
    delete without.client.navigate;
    await press([without]);
    expect(without.did).toEqual([OPEN, "focus"]);
  });

  it("is not held up by a window that will not be raised", async () => {
    const hangs = appWindow({ focus: () => new Promise(() => undefined) });
    const { reported } = await press([hangs]);
    expect(hangs.did).toEqual([OPEN]);
    expect(reported).toEqual(["window"]);
    const refuses = appWindow({
      focus: async () => {
        throw new TypeError("Not allowed to focus a window.");
      },
    });
    await press([refuses]);
    expect(refuses.did).toEqual([OPEN]);
  });

  it("still sends the app there without the Cache API", async () => {
    const app = appWindow();
    const { note } = await press([app], THREAD, false);
    expect(note).toBeNull();
    expect(app.did[0]).toBe(OPEN);
  });

  it("opens a window on the thread when the app has none", async () => {
    const { opened, note, reported } = await press([]);
    expect(opened).toEqual([`${ORIGIN}${THREAD}`]);
    expect(note?.url).toBe(THREAD);
    expect(reported).toEqual(["opened"]);
  });

  it("never leaves the site", async () => {
    const app = appWindow();
    const { opened, note } = await press([app], "https://elsewhere.example/");
    expect(opened).toEqual([]);
    expect(app.did).toEqual([]);
    expect(note).toBeNull();
  });
});
