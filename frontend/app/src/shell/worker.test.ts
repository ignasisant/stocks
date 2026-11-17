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

/** A window of the app and what the worker did to it. */
function appWindow(over: Partial<Client> = {}) {
  const did: string[] = [];
  const client: Client = {
    url: `${ORIGIN}/portfolio`,
    focus: async () => did.push("focus"),
    navigate: async (url) => did.push(`navigate ${url}`),
    postMessage: (message) => did.push(`message ${JSON.stringify(message)}`),
    ...over,
  };
  return { client, did };
}

/** Press a notification pointing at `url` with `open` windows on screen. */
async function press(open: Client[], url = THREAD) {
  const handlers: Record<string, (event: unknown) => void> = {};
  const opened: string[] = [];
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (name: string, handler: (event: unknown) => void) => {
      handlers[name] = handler;
    },
    skipWaiting: () => undefined,
    clients: {
      claim: async () => undefined,
      matchAll: async () => open,
      openWindow: async (href: string) => opened.push(href),
    },
  };
  new Function("self", SOURCE)(self);
  let settled: Promise<unknown> = Promise.resolve();
  handlers.notificationclick?.({
    action: "",
    notification: { close: () => undefined, data: { url } },
    waitUntil: (work: Promise<unknown>) => {
      settled = work;
    },
  });
  await settled;
  return opened;
}

describe("a pressed notification", () => {
  it("raises the open window and sends it to the thread", async () => {
    const { client, did } = appWindow();
    expect(await press([client])).toEqual([]);
    expect(did).toEqual(["focus", `navigate ${ORIGIN}${THREAD}`]);
  });

  it("still sends the window to the thread when the browser will not raise it", async () => {
    const { client, did } = appWindow({
      focus: async () => {
        throw new TypeError("Not allowed to focus a window.");
      },
    });
    expect(await press([client])).toEqual([]);
    expect(did).toEqual([`navigate ${ORIGIN}${THREAD}`]);
  });

  it("tells the page to move itself when the worker may not move it", async () => {
    const refused = appWindow({
      navigate: async () => {
        throw new TypeError("This service worker is not the client's active one.");
      },
    });
    await press([refused.client]);
    expect(refused.did).toEqual([
      "focus",
      `message ${JSON.stringify({ type: "open", url: THREAD })}`,
    ]);
    const without = appWindow({ navigate: undefined });
    delete without.client.navigate;
    await press([without.client]);
    expect(without.did.at(-1)).toBe(
      `message ${JSON.stringify({ type: "open", url: THREAD })}`,
    );
  });

  it("opens a window on the thread when the app has none", async () => {
    expect(await press([])).toEqual([`${ORIGIN}${THREAD}`]);
  });

  it("never leaves the site", async () => {
    const { client, did } = appWindow();
    expect(await press([client], "https://elsewhere.example/")).toEqual([]);
    expect(did).toEqual([]);
  });
});
