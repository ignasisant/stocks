/**
 * How the page felt, sent to the server log.
 *
 * The server times its routes; it cannot see when the reader first saw a
 * figure (LCP), whether a tap answered at once (INP), or whether the page
 * jumped under them (CLS). The browser measures those, and once per page load
 * — as the reader leaves it, when the numbers are final — they go to
 * `POST /vitals` as one report, which the server files as `client.vital`
 * events beside everything else it logged (`routes/vitals.py`).
 *
 * With them, what the numbers were taken against: which page, how it was
 * arrived at (a fresh visit, a reload, back/forward), and whether the first
 * paint drew figures kept from the last visit (`shell/keep`) — the two
 * halves of "was it fast" this app can act on.
 *
 * `keepalive`, like the error report: the page is being left as this goes
 * out. Best effort throughout; a report that does not arrive is one number
 * fewer, never something a reader can notice.
 */
import { onCLS, onINP, onLCP, onTTFB, type Metric } from "web-vitals";
import { BASE } from "./api";
import { usedKept } from "./keep";

type Report = { name: Metric["name"]; value: number; rating: Metric["rating"] };

const pending = new Map<string, Report>();
let sent = false;

/** The page, as the router names it: the first path segment, or `home`. */
function where(): string {
  const slug = window.location.pathname.replace(/^\/+/, "").split("/")[0] ?? "";
  return (slug || "home").slice(0, 40);
}

/** `navigate`, `reload` or `back_forward`, as the browser reports it. */
function navigation(): string {
  const entry = performance.getEntriesByType?.("navigation")[0] as
    PerformanceNavigationTiming | undefined;
  return entry?.type ?? "";
}

/** Send what has been measured so far, once. */
export function flush(): void {
  if (sent || pending.size === 0) return;
  sent = true;
  const body = JSON.stringify({
    metrics: [...pending.values()].map((m) => ({
      name: m.name,
      value: Math.round(m.value * 10_000) / 10_000,
      rating: m.rating,
    })),
    where: where(),
    nav: navigation(),
    kept: usedKept(),
  });
  fetch(`${BASE}/vitals`, {
    method: "POST",
    credentials: "same-origin",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body,
  }).catch(() => undefined);
}

function note(metric: Metric): void {
  pending.set(metric.name, {
    name: metric.name,
    value: metric.value,
    rating: metric.rating,
  });
}

/**
 * Start measuring. Called once, at boot. The report goes out when the tab is
 * hidden or the page unloads — after the library has finalised each metric,
 * which it does on the same signal, and before this listener because it was
 * registered first.
 */
export function watchVitals(): void {
  if (typeof window === "undefined" || typeof fetch !== "function") return;
  try {
    onTTFB(note);
    onLCP(note);
    onCLS(note);
    onINP(note);
  } catch {
    return;
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });
  window.addEventListener("pagehide", flush);
}

/** Tests only. */
export function _reset(): void {
  pending.clear();
  sent = false;
}
