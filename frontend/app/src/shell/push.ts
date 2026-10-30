/**
 * Web Push on this device: "your answer is ready" when the app is not on screen.
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
 * The other half is the beat: while an answer is being written, an app on
 * screen says so every `BEAT_MS`, and the server skips the push while a beat
 * is fresh. Somebody watching the answer arrive needs no notification of it.
 */

import { useEffect } from "react";
import { BASE, get, send } from "./api";

/** `GET /push` — `routes.push.Push`. */
export type PushState = {
  /** Whether this deployment can push at all. False is not an error. */
  configured: boolean;
  /** The VAPID public key, base64url. */
  key: string | null;
  /** Whether this device's subscription is kept. */
  subscribed: boolean;
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
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
  const standalone =
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return ios && !standalone;
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
