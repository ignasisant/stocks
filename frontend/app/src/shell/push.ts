/**
 * Web Push on this device: the daily summary, alerts, reminders and finished answers
 * as notifications when the app is not on screen.
 *
 * The browser does the subscribing — permission, then `pushManager.subscribe`
 * with the server's key — and the server keeps the result and sends the push
 * once an answer is written (`notify/webpush.py`). The worker that shows it
 * is `/sw.js`; it does nothing else, so registering it changes no page load.
 *
 * iPhone and iPad offer push only to the app added to the Home Screen
 * (iOS 16.4+): in a Safari tab `supported()` is false and the Profile says
 * how to get there instead.
 *
 * A browser has one subscription whoever is signed in, so a device belongs
 * to one account at a time: the one signed in on it. The app says so when it
 * opens (`claimPush`) and when it signs out (`releasePush`). Without that, an
 * account that switched notifications on here keeps sending them after
 * somebody else has signed in, and pressing one opens a thread that is not
 * in the book on screen.
 *
 * The other half is the beat: while an answer is being written, an app on
 * screen says so every `BEAT_MS`, and the server skips the push while a beat
 * is fresh. Somebody watching the answer arrive needs no notification of it.
 */

import { useEffect } from "react";
import { BASE, get, send } from "./api";
import { appleMobile } from "./install";
import { onSignOut } from "./keep";
import { isStandalone } from "./resume";
import { navigate } from "./router";
import { useGuest } from "./session";

/** `GET /push` — `routes.push.Push`. */
export type PushState = {
  /** Whether this deployment can push at all. False is not an error. */
  configured: boolean;
  /** The VAPID public key, base64url. */
  key: string | null;
  /** Whether this device's subscription is kept. */
  subscribed: boolean;
  /** Devices of this account that receive notifications, this one included. */
  devices: number;
};

const WORKER = "/sw.js";
const TOUCHES = { touches: ["/push"] };

export function supported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** An iPhone or iPad in a browser tab: push waits for the Home Screen app. */
export function needsInstall(): boolean {
  if (typeof window === "undefined") return false;
  return appleMobile() && !isStandalone();
}

export function permission(): NotificationPermission | "unsupported" {
  return supported() ? Notification.permission : "unsupported";
}

/** base64url to the bytes `applicationServerKey` takes. */
export function keyBytes(key: string): Uint8Array<ArrayBuffer> {
  const b64 = key.replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function registration(): Promise<ServiceWorkerRegistration> {
  return (
    (await navigator.serviceWorker.getRegistration("/")) ??
    (await navigator.serviceWorker.register(WORKER, { scope: "/" }))
  );
}

/** This device's subscription, if the browser holds one. */
async function current(): Promise<PushSubscription | null> {
  if (!supported()) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return (await reg?.pushManager.getSubscription()) ?? null;
}

/** The server's view, asked about this device's own subscription. */
export async function readPush(): Promise<PushState> {
  const sub = await current().catch(() => null);
  return get<PushState>("/push", { endpoint: sub?.endpoint });
}

/**
 * Ask for permission and subscribe. Must run from a tap: browsers refuse the
 * permission prompt otherwise. Resolves false when the reader said no.
 */
export async function enablePush(key: string, lang: string): Promise<boolean> {
  if ((await Notification.requestPermission()) !== "granted") return false;
  const reg = await registration();
  await navigator.serviceWorker.ready;
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(key),
    }));
  await send("POST", "/push/subscription", { ...sub.toJSON(), lang }, TOUCHES);
  return true;
}

export async function disablePush(): Promise<void> {
  const sub = await current();
  if (!sub) return;
  await send("POST", "/push/unsubscribe", { endpoint: sub.endpoint }, TOUCHES);
  await sub.unsubscribe();
}

/** A notification to this device now — the "does it work" button. */
export async function testPush(): Promise<void> {
  const sub = await current();
  if (!sub) return;
  await send("POST", "/push/test", { endpoint: sub.endpoint }, { touches: [] });
}

/* ------------------------------------------------------ whose device */

/** This device is the signed-in account's to notify, and nobody else's. */
export async function claimPush(): Promise<void> {
  const sub = await current();
  if (!sub) return;
  await send("POST", "/push/claim", { endpoint: sub.endpoint }, TOUCHES);
}

/**
 * The account is signing out here: nothing more is sent to this device until
 * somebody signs in on it. `keepalive`, so it still goes out when the page
 * leaves before it is answered.
 */
export async function releasePush(): Promise<void> {
  const sub = await current();
  if (!sub) return;
  await fetch(`${BASE}/push/release`, {
    method: "POST",
    credentials: "same-origin",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: sub.endpoint }),
  });
}

/**
 * Once per opening of the app, for a signed-in account: claim this device,
 * and release it on the way out. A refusal changes nothing on screen, and the
 * next opening says it again.
 */
export function useDeviceClaim(): void {
  const guest = useGuest();
  useEffect(() => {
    if (guest) return;
    claimPush().catch(() => undefined);
    return onSignOut(releasePush);
  }, [guest]);
}

/* ------------------------------------------------------------- the beat */

const BEAT_MS = 20_000;
const CLIENT = Math.random().toString(36).slice(2, 14);

function beat(visible: boolean): void {
  // keepalive: the hidden beat is sent as the page goes away.
  void fetch(`${BASE}/push/presence`, {
    method: "POST",
    credentials: "same-origin",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client: CLIENT, visible }),
  }).catch(() => {});
}

/**
 * While `active` (an answer is being written), tell the server whether the
 * app is on screen. Nothing at all while idle: the beat only matters to a
 * push that only an answer sends.
 */
export function useOnScreenBeat(active: boolean): void {
  useEffect(() => {
    if (!active || typeof document === "undefined") return;
    const tick = () => beat(!document.hidden);
    tick();
    const timer = window.setInterval(() => {
      if (!document.hidden) tick();
    }, BEAT_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [active]);
}

/** The path in the worker's `{type: "open", url}`, or null for anything else. */
export function workerTarget(data: unknown): string | null {
  const said = data as { type?: unknown; url?: unknown } | null;
  if (said?.type !== "open" || typeof said.url !== "string") return null;
  if (!said.url.startsWith("/") || said.url.startsWith("//")) return null;
  return said.url;
}

/* The worker's note of a pressed notification (`sw.js`, `remember`). */
const PENDING_CACHE = "topstocks-push";
const PENDING_KEY = "/__push/pending";
/** A note older than this is a press nobody followed: left alone. */
export const PENDING_MS = 120_000;

/** One press: where it goes and when it happened (the worker's clock). */
export type Press = { url: string; at: number };

/** The press a worker's note or message names, or null for anything else. */
function pressOf(said: unknown): Press | null {
  const at = (said as { at?: unknown } | null)?.at;
  const url = workerTarget({
    type: "open",
    url: (said as { url?: unknown } | null)?.url,
  });
  return url && typeof at === "number" ? { url, at } : null;
}

/** The note's press if it is fresh, else null. */
export function pendingPress(note: unknown, now: number): Press | null {
  const press = pressOf(note);
  return press && now - press.at <= PENDING_MS ? press : null;
}

/**
 * Take the worker's note, if one is there: read once and gone, so the press
 * opens its page once. Null without the Cache API or with nothing pending.
 */
export async function takePending(): Promise<Press | null> {
  if (typeof caches === "undefined") return null;
  try {
    const cache = await caches.open(PENDING_CACHE);
    const hit = await cache.match(PENDING_KEY);
    if (!hit) return null;
    await cache.delete(PENDING_KEY);
    return pendingPress(await hit.json(), Date.now());
  } catch {
    return null;
  }
}

/** How the page got there, filed as `push.opened` — best effort. */
function opened(via: "message" | "pending"): void {
  void fetch(`${BASE}/push/opened`, {
    method: "POST",
    credentials: "same-origin",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ via }),
  }).catch(() => {});
}

/**
 * Deciding what to do with a press, however it arrived. The same press can
 * come twice — the worker's message and its note — and opens once; two
 * presses on the same thread are two presses. A note for the address the
 * page was opened on (the worker's `openWindow`) is already on screen.
 */
export function pressTaker(
  boot: string,
  go: (url: string) => void,
  report: (via: "message" | "pending") => void,
) {
  const taken = new Set<number>();
  let first = true;
  return (press: Press | null, via: "message" | "pending"): boolean => {
    if (!press) return false;
    const atBoot = first && via === "pending" && press.url === boot;
    first = false;
    if (taken.has(press.at)) return false;
    taken.add(press.at);
    if (atBoot) return false;
    report(via);
    go(press.url);
    return true;
  };
}

/**
 * The address the app was opened on, read before the drawer takes `?thread=`
 * off it.
 */
const BOOT_URL =
  typeof location === "undefined" ? "" : location.pathname + location.search;

/** The worker may still be writing its note when the app comes to the front;
 * a worker started cold takes longest. */
const RECHECK_MS = [0, 500, 1500, 4000];

/**
 * A notification pressed while this window was open: the page goes to its
 * address itself (`sw.js`). Two ways it hears of it — the worker's message,
 * when the page is running to receive it, and the worker's note, read on
 * opening and each time the app comes back to the front, for an iPhone app
 * woken by the press. Same origin only, and only a path, never somewhere
 * else. The page answers the message (`took`), so the worker knows not to
 * move the window itself.
 */
export function useWorkerOpen(): void {
  useEffect(() => {
    const take = pressTaker(BOOT_URL, navigate, opened);
    const worker =
      typeof navigator === "undefined" ? undefined : navigator.serviceWorker;
    const heard = (event: MessageEvent) => {
      if (!workerTarget(event.data)) return;
      const press = pressOf(event.data);
      if (press) {
        (event.source as ServiceWorker | null)?.postMessage({
          type: "took",
          at: press.at,
        });
      }
      take(press, "message");
    };
    worker?.addEventListener("message", heard);

    const timers: number[] = [];
    const look = () => {
      if (document.visibilityState !== "visible") return;
      for (const t of timers.splice(0)) window.clearTimeout(t);
      for (const ms of RECHECK_MS) {
        timers.push(
          window.setTimeout(() => {
            void takePending().then((press) => take(press, "pending"));
          }, ms),
        );
      }
    };
    look();
    document.addEventListener("visibilitychange", look);
    window.addEventListener("pageshow", look);
    return () => {
      worker?.removeEventListener("message", heard);
      document.removeEventListener("visibilitychange", look);
      window.removeEventListener("pageshow", look);
      for (const t of timers) window.clearTimeout(t);
    };
  }, []);
}
