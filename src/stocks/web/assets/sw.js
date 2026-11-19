/*
 * The service worker: Web Push and nothing else.
 *
 * Served at /sw.js (`server.service_worker`) so its scope is the whole app.
 * No fetch handler on purpose — no offline cache to go stale under a deploy;
 * the page loads from the network exactly as it does without this file.
 *
 * A push carries {title, body, url, tag, actions?} (`notify/render.py`).
 * Pressing the notification sends an open TopStocks window to `url` (a
 * message, and a note it reads when it comes to the front), or opens one
 * there; pressing one of its `actions` buttons does the same with that
 * action's own url.
 */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "TopStocks", {
      body: data.body || "",
      tag: data.tag || undefined,
      icon: "/lp/icon-192.png",
      badge: "/lp/icon-192.png",
      actions: (data.actions || []).map((a) => ({ action: a.action, title: a.title })),
      data: {
        url: data.url || "/",
        actions: Object.fromEntries((data.actions || []).map((a) => [a.action, a.url])),
      },
    }),
  );
});

/*
 * Where a pressed notification is going, kept until the page takes it
 * (`shell/push.ts`, `takePending`). An iPhone app woken from the background
 * by the press came back on the page it was left on, with no load of the
 * thread (prod 2026-11-19): whatever the worker told that window did not
 * arrive. The page reads this note when it comes back to the front, so the
 * press lands whichever way the browser lets it through. Same key every
 * time: a newer press replaces it.
 */
const PENDING_CACHE = "topstocks-push";
const PENDING_KEY = "/__push/pending";

async function remember(press) {
  try {
    const cache = await self.caches.open(PENDING_CACHE);
    await cache.put(
      PENDING_KEY,
      new Response(JSON.stringify(press), {
        headers: { "Content-Type": "application/json" },
      }),
    );
  } catch (_) {
    /* no Cache API: the message and openWindow still carry it */
  }
}

/* What the worker did, filed as `push.opened` (`routes/push.py`). */
function report(via) {
  return fetch("/api/v1/push/opened", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ via }),
  }).catch(() => undefined);
}

/* A promise that may never settle (focus on a backgrounded app) gets `ms`. */
function bounded(promise, ms) {
  return Promise.race([
    Promise.resolve(promise).catch(() => undefined),
    new Promise((resolve) => setTimeout(resolve, ms)),
  ]);
}

/* The page's answer to a press it took (`useWorkerOpen`), by the press's `at`. */
const acks = new Map();
self.addEventListener("message", (event) => {
  const said = event.data || {};
  if (said.type === "took") acks.get(said.at)?.();
});

function answered(at, ms) {
  return bounded(
    new Promise((resolve) => acks.set(at, () => resolve(true))),
    ms,
  ).finally(() => acks.delete(at));
}

/* How long a running page has to answer before the worker moves it itself. */
const ACK_MS = 1000;

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data || {};
  const picked = (event.action && data.actions?.[event.action]) || data.url || "/";
  const target = new URL(picked, self.location.origin);
  if (target.origin !== self.location.origin) return;
  const press = { url: target.pathname + target.search, at: Date.now() };
  event.waitUntil(
    (async () => {
      // First, before anything that can hang: the note the page falls back on.
      await remember(press);
      const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const client = open.find((c) => new URL(c.url).origin === target.origin);
      // The press's activation is spent quickly: open or raise first, report after.
      if (!client) {
        const opened = self.clients.openWindow(target.href);
        await bounded(report("opened"), 2000);
        return opened;
      }
      // The app moves itself (`useWorkerOpen`): a route change in place, no
      // reload, on a page this worker does not control too.
      const heard = answered(press.at, ACK_MS);
      client.postMessage({ type: "open", ...press });
      await bounded(client.focus(), ACK_MS);
      // No answer: a page without the app's shell, or one not running yet.
      // Move it the old way; the note still waits for one that wakes later.
      if (!(await heard) && "navigate" in client) {
        await bounded(client.navigate(target.href), 2000);
      }
      await bounded(report("window"), 2000);
      return undefined;
    })(),
  );
});
