/**
 * Browser errors, sent to the server log.
 *
 * A JavaScript error never reaches the server on its own — a render that
 * threw, a promise nobody awaited — so before this the only trace of a screen
 * that broke was a reader who wrote in about it. Each one now goes to
 * `POST /client-error` and lands in the production log as `client.error`,
 * beside whatever the server logged for the same account
 * (`routes/client_error.py`, which also masks it).
 *
 * Only ours, and only news: an error the API already logged (`ApiError`), one
 * a navigation cancelled, a dropped connection, a browser extension's script —
 * none of them is a bug in this bundle, and reporting them would bury the ones
 * that are. A loop is cut off after a handful per page load.
 */
import { ApiError, BASE, Cancelled, NotSignedIn } from "./api";

export type CrashKind = "error" | "rejection" | "render";

const MAX_PER_LOAD = 5;
const seen = new Set<string>();

/** What a dropped connection says, per browser. Not a bug in the bundle. */
const OFFLINE = [
  "Failed to fetch",
  "Load failed",
  "NetworkError when attempting to fetch resource.",
  "The network connection was lost.",
];

/** Benign by spec: the browser deferred a resize notification. */
const NOISE = ["ResizeObserver loop"];

/**
 * What a lazy page says when its chunk is gone, per browser. A tab opened
 * before a deploy still asks for the old hashed file, which the new build no
 * longer serves: the cure is the new `index.html`, not a bug report.
 */
const STALE_CHUNK = [
  "Failed to fetch dynamically imported module",
  "Importing a module script failed",
  "error loading dynamically imported module",
  "Unable to preload CSS",
];

/** sessionStorage slot: when this tab last reloaded for a stale chunk. */
const RELOADED = "ts.staleChunkReload";

/** A reload that did not cure it within this long is not a stale chunk. */
const RELOAD_GUARD_MS = 60_000;

/** Set once a reload is under way: what breaks while the page unloads is moot. */
let reloading = false;

export function staleChunk(message: string): boolean {
  return STALE_CHUNK.some((text) => message.startsWith(text));
}

/**
 * Reload once to pick up the new build. False when this tab already tried in
 * the last minute (the chunk is really missing, so report it), or when
 * storage is unavailable and the guard cannot be kept.
 */
export function reloadForNewBuild(now = Date.now()): boolean {
  try {
    const last = Number(window.sessionStorage.getItem(RELOADED) ?? 0);
    if (now - last < RELOAD_GUARD_MS) return false;
    window.sessionStorage.setItem(RELOADED, String(now));
  } catch {
    return false;
  }
  reloading = true;
  window.location.reload();
  return true;
}

function described(error: unknown): { name: string; message: string; stack: string } {
  if (error instanceof Error) {
    return { name: error.name, message: error.message, stack: error.stack ?? "" };
  }
  // A thrown string, or a DOMException in a runtime where it is not an Error.
  const { name, message } = (error ?? {}) as { name?: unknown; message?: unknown };
  return {
    name: typeof name === "string" && name ? name : "Error",
    message: typeof message === "string" ? message : String(error),
    stack: "",
  };
}

/** Whether this error is somebody else's, or not an error at all. */
export function ignored(error: unknown, message: string): boolean {
  if (
    error instanceof ApiError ||
    error instanceof Cancelled ||
    error instanceof NotSignedIn
  )
    return true;
  if ((error as { name?: unknown } | null)?.name === "AbortError") return true;
  if (OFFLINE.includes(message)) return true;
  return NOISE.some((text) => message.startsWith(text));
}

/** The first frame that points into a script, as `url:line:col`. */
export function topFrame(stack: string): string {
  return stack.match(/(https?:\/\/[^\s()]+:\d+:\d+)/)?.[1] ?? "";
}

/** The screen, named as feedback names it: `ticker?symbol=AAPL&tab=fees`. */
function where(): string {
  const { pathname, search } = window.location;
  return `${pathname.replace(/^\/+/, "") || "home"}${search}`.slice(0, 120);
}

/** Send one error, unless it is ignored, already sent, or one too many. */
export function report(kind: CrashKind, error: unknown, component = ""): void {
  const { name, message, stack } = described(error);
  if (reloading || ignored(error, message)) return;
  if (staleChunk(message) && reloadForNewBuild()) return;
  const src = topFrame(stack);
  const key = `${name}|${message}|${src}`;
  if (seen.has(key) || seen.size >= MAX_PER_LOAD) return;
  seen.add(key);
  // keepalive: the error may be the last thing this page does before the
  // reader reloads it, and the report should still arrive.
  fetch(`${BASE}/client-error`, {
    method: "POST",
    credentials: "same-origin",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kind,
      name: name.slice(0, 64),
      message: message.slice(0, 500),
      where: where(),
      src: src.slice(0, 300),
      stack: stack.slice(0, 4000),
      component: component.trim().slice(0, 2000),
    }),
  }).catch(() => undefined);
}

/**
 * Listen for what React does not see: a throw in an event handler or a timer,
 * and a rejected promise nobody handled. Renders are reported by the root's
 * own hooks (`main.tsx`), which also carry the component stack.
 */
export function listen(): void {
  window.addEventListener("error", (event) => {
    // A script from another origin (an extension, an injected widget) shows
    // up as "Script error." with no file, or with a file that is not ours.
    if (event.filename && !event.filename.startsWith(window.location.origin)) return;
    if (!event.error && event.message === "Script error.") return;
    report("error", event.error ?? event.message);
  });
  window.addEventListener("unhandledrejection", (event) => {
    report("rejection", event.reason);
  });
  // Vite's own signal that a lazy chunk or its CSS failed to load; handled
  // here, the import never rejects into a page's error boundary.
  window.addEventListener("vite:preloadError", (event) => {
    if (reloadForNewBuild()) event.preventDefault();
  });
}

/** Tests only: forget what was sent, and any reload under way. */
export function _reset(): void {
  seen.clear();
  reloading = false;
}
