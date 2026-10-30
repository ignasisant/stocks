/**
 * TopStocks as an app on this device: whether it can be offered, and when.
 *
 * Chromium (Chrome, Edge, Android, Samsung Internet) fires
 * `beforeinstallprompt` once the manifest qualifies. It is kept here, its own
 * mini-infobar suppressed, and `install()` replays it from a press — the only
 * moment the browser accepts it, and only once. Safari on iPhone and iPad has
 * no such event: the most the app can do is say where the Share sheet keeps
 * "Add to Home Screen". Everywhere else (Firefox, desktop Safari with its own
 * "Open in web app" banner, an in-app browser that cannot install at all)
 * nothing is offered and nothing is said.
 *
 * Wired from `main.tsx`, before React: the event can fire before the shell
 * mounts, and one that is missed is gone until the next load.
 *
 * When to ask is per device, not per account, because installing is: a no on
 * the laptop says nothing about the phone. Asked once, on the `VISIT_DAYS`th
 * day this browser opened the app; the Profile keeps the offer for later.
 */

import { useSyncExternalStore } from "react";

import { isStandalone } from "./resume";

type InstallEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

/** How this device installs: the browser's own dialog, the Share sheet, or not. */
export type InstallWay = "prompt" | "ios" | null;

/** The days of use before the nudge: somebody who came back, not a first look. */
export const VISIT_DAYS = 3;

const VISITS = "installVisitDays";
const ASKED = "installAsked";

let deferred: InstallEvent | null = null;
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((listener) => listener());

export function watchInstall(): void {
  if (typeof window === "undefined") return;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferred = event as InstallEvent;
    changed();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    markAsked();
    changed();
  });
  if (!isStandalone()) recordVisit();
}

/** iPhone, iPad, iPod. iPadOS reports a Mac, so a Mac with a touchscreen is one. */
export function appleMobile(
  ua = navigator.userAgent,
  touches = navigator.maxTouchPoints,
): boolean {
  return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && touches > 1);
}

/** Safari itself: other iOS browsers keep the item elsewhere, in-app ones lack it. */
export function iosSafari(
  ua = navigator.userAgent,
  touches = navigator.maxTouchPoints,
): boolean {
  return (
    appleMobile(ua, touches) &&
    !/CriOS|FxiOS|EdgiOS|GSA\/|FBAN|FBAV|Instagram|Line\//.test(ua)
  );
}

export function installWay(): InstallWay {
  if (typeof window === "undefined" || isStandalone()) return null;
  if (deferred) return "prompt";
  return iosSafari() ? "ios" : null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useInstallWay(): InstallWay {
  return useSyncExternalStore(subscribe, installWay, () => null);
}

/** The browser's dialog. True when accepted; the event is spent either way. */
export async function install(): Promise<boolean> {
  const event = deferred;
  if (!event) return false;
  deferred = null;
  changed();
  await event.prompt();
  const { outcome } = await event.userChoice;
  return outcome === "accepted";
}

function localDay(now: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function readDays(store: Storage): string[] {
  try {
    const parsed: unknown = JSON.parse(store.getItem(VISITS) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((d) => typeof d === "string") : [];
  } catch {
    return [];
  }
}

/** Stamps today and says how many distinct days are known, up to `VISIT_DAYS`.
 *  Storage that throws counts nothing: a nudge that cannot count never fires. */
export function recordVisit(now = new Date(), storage?: Storage): number {
  try {
    const store = storage ?? window.localStorage;
    const today = localDay(now);
    const days = readDays(store);
    if (!days.includes(today)) {
      store.setItem(VISITS, JSON.stringify([...days, today].slice(-VISIT_DAYS)));
    }
    return Math.min(VISIT_DAYS, new Set([...days, today]).size);
  } catch {
    return 0;
  }
}

export function visitDays(storage?: Storage): number {
  try {
    return readDays(storage ?? window.localStorage).length;
  } catch {
    return 0;
  }
}

/** Whether this browser was already asked. Storage that throws reads as "yes":
 *  a nudge that cannot remember it asked would ask on every load. */
export function asked(storage?: Storage): boolean {
  try {
    return (storage ?? window.localStorage).getItem(ASKED) === "1";
  } catch {
    return true;
  }
}

export function markAsked(storage?: Storage): void {
  try {
    (storage ?? window.localStorage).setItem(ASKED, "1");
  } catch {
    // `asked()` already reads a throwing store as "asked".
  }
}

/** Test seam: a captured event, as the browser would hand it over. */
export function _setDeferred(event: InstallEvent | null): void {
  deferred = event;
  changed();
}
