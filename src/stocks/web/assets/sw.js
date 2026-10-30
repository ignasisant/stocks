/*
 * The service worker: Web Push and nothing else.
 *
 * Served at /sw.js (`server.service_worker`) so its scope is the whole app.
 * No fetch handler on purpose — no offline cache to go stale under a deploy;
 * the page loads from the network exactly as it does without this file.
 *
 * A push carries {title, body, url, tag} (`notify/webpush.py`). Pressing the
 * notification focuses an open TopStocks window and sends it to `url`, or
 * opens one there.
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
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/", self.location.origin);
  if (target.origin !== self.location.origin) return;
  event.waitUntil(
    (async () => {
      const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of open) {
        if (new URL(client.url).origin !== target.origin) continue;
        await client.focus();
        // The page reads ?thread= on navigation (chat/Drawer.tsx).
        if ("navigate" in client) return client.navigate(target.href);
        return undefined;
      }
      return self.clients.openWindow(target.href);
    })(),
  );
});
