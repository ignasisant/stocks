/**
 * Asking every screen on show for the server's word again, at once.
 *
 * A Home Screen app on an iPhone has no address bar and no browser
 * pull-to-refresh, and iOS keeps it alive in the background for hours: the
 * figures it opened with are still the ones on screen the next morning. Two
 * ways out, both landing here — coming back to the app after a while
 * (`useReloadOnReturn`) and the shell's own pull (`PullRefresh`).
 *
 * Each mounted `useApi` listens and reloads in place: the figures stay up and
 * dim (`refreshing`) until the new ones land, so a reload is never a skeleton.
 */

import { useEffect } from "react";

/** Resolves once that screen's reload has landed or failed. */
type Listener = () => Promise<void>;

const listeners = new Set<Listener>();

export function onReloadAll(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Every screen asks again; resolves when the last one is back. */
export function reloadAll(): Promise<void> {
  return Promise.all([...listeners].map((listener) => listener())).then(() => {});
}

/** Away this long and the figures on screen are worth asking for again: a
 * glance at another app and back is not, a market session moving on is. */
const AWAY_MS = 120_000;

/** Opened from the Home Screen rather than in a browser tab. */
export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/**
 * Reload what is on screen when the reader comes back after `AWAY_MS`, and
 * when the page itself comes back from the back-forward cache, which restores
 * it as it was left without running anything.
 */
export function useReloadOnReturn(): void {
  useEffect(() => {
    let hiddenAt: number | null = null;
    const changed = () => {
      if (document.visibilityState === "hidden") {
        hiddenAt = Date.now();
        return;
      }
      const away = hiddenAt === null ? 0 : Date.now() - hiddenAt;
      hiddenAt = null;
      if (away >= AWAY_MS) void reloadAll();
    };
    const shown = (event: PageTransitionEvent) => {
      if (event.persisted) void reloadAll();
    };
    document.addEventListener("visibilitychange", changed);
    window.addEventListener("pageshow", shown);
    return () => {
      document.removeEventListener("visibilitychange", changed);
      window.removeEventListener("pageshow", shown);
    };
  }, []);
}
