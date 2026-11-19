/**
 * The Home Screen app's screen, given back after the keyboard leaves.
 *
 * iOS 26 has a bug in apps opened from the Home Screen: once the soft keyboard
 * has been up, the box `position: fixed` is laid out against can stay short
 * after it goes down. The tab bar, the toasts and the assistant's launcher
 * then float a keyboard's height above the foot of the screen, over the page,
 * until the app is killed (WebKit 297779, Apple forums 800125). Nothing of
 * ours is pinned: a reload does not cure it, a force-quit does.
 *
 * A probe (`.ag-vp-probe`, styles.css) sits fixed to every edge of that box,
 * invisible, so its height is the box's. When a keyboard goes down (a text
 * field lets go of the focus, or the visual viewport grows with no field
 * focused), the probe and the window's sizes are checked against the tallest
 * the window has been at this width and orientation. Short by more than
 * `STUCK_PX` and the probe is taken out of layout and put back in one
 * synchronous reflow, which can make WebKit measure the window again — the
 * probe, not the document, so no scroller and no entrance animation is reset.
 * The sizes before and after go to `/viewport-stuck` (`api/routes/launch.py`),
 * so the log says which size was stuck and whether this cured it, along with
 * how tall the window was while the keyboard was up.
 *
 * iPhone and iPad Home Screen apps only: a Safari tab has its own toolbars
 * moving the sizes, and nothing else has been seen to do this.
 */

import type { ViewportStuck } from "../api.gen";
import { BASE } from "./api";
import { appleMobile } from "./install";
import { isStandalone } from "./resume";

/** Short by less than this is rounding and toolbars, not a stuck window. */
export const STUCK_PX = 20;
/** The keyboard's own animation is over by then on every iPhone measured. */
const SETTLE_MS = 400;
/** One report per this long: a stuck window is one fact, not one per tap. */
const REPORT_EVERY_MS = 60_000;
/** Cures tried per launch that did not take; after them, only reports. */
const MAX_TRIES = 3;

const NOT_TYPED = new Set([
  "button",
  "checkbox",
  "radio",
  "range",
  "file",
  "submit",
  "reset",
]);

/** Whether focus on `el` raises a soft keyboard. */
export function isTextField(el: EventTarget | null): boolean {
  return (
    el instanceof HTMLElement &&
    (el.isContentEditable ||
      el instanceof HTMLTextAreaElement ||
      (el instanceof HTMLInputElement && !NOT_TYPED.has(el.type)))
  );
}

export type Sizes = {
  /** `innerHeight`. */
  inner: number;
  /** `visualViewport.height` and `.offsetTop`: the part on screen. */
  vv: number;
  top: number;
  /** `documentElement.clientHeight`. */
  client: number;
  /** The probe's height: the box fixed elements are laid out against. */
  fixed: number;
};

function sizes(probe: HTMLElement): Sizes {
  const vv = window.visualViewport;
  return {
    inner: window.innerHeight,
    vv: Math.round(vv?.height ?? window.innerHeight),
    top: Math.round(vv?.offsetTop ?? 0),
    client: document.documentElement.clientHeight,
    fixed: Math.round(probe.getBoundingClientRect().height),
  };
}

/** The screen's height in this orientation, in CSS pixels. */
function screenHeight(): number {
  const landscape = (screen.orientation?.type ?? "").startsWith("landscape");
  const [a, b] = [screen.width, screen.height];
  return landscape ? Math.min(a, b) : Math.max(a, b);
}

/** A keyboard never changes the window's width: an iPad's split view does. */
function shape(): string {
  const turned =
    screen.orientation?.type ??
    (screen.width > screen.height ? "landscape" : "portrait");
  return `${turned}:${window.innerWidth}`;
}

/**
 * How far short of its full height the window is, in px: the window and the
 * fixed box against the tallest the window has been in this shape, and the
 * part of it on screen. 0 when nothing is short. Not against the screen:
 * under the default status bar a healthy window is shorter than it.
 */
export function shortBy(now: Sizes, tallest: number): number {
  return Math.max(
    0,
    tallest - now.inner,
    tallest - now.fixed,
    now.inner - (now.vv + now.top),
    now.top,
  );
}

/** Take the probe out of layout and back in: WebKit measures the window again. */
function remeasure(probe: HTMLElement): void {
  probe.style.display = "none";
  void probe.offsetHeight;
  probe.style.display = "";
  void probe.offsetHeight;
}

function frames(): Promise<void> {
  return new Promise((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
  );
}

/** Best effort, like `/launch`: a report that does not arrive is one line fewer. */
function report(body: ViewportStuck): void {
  if (typeof fetch !== "function") return;
  fetch(`${BASE}/viewport-stuck`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => undefined);
}

export function watchViewport(): void {
  if (typeof window === "undefined" || !isStandalone() || !appleMobile()) return;

  const probe = document.createElement("div");
  probe.className = "ag-vp-probe";
  probe.setAttribute("aria-hidden", "true");
  document.body.append(probe);

  const tallest = new Map<string, number>();
  const note = () => {
    if (isTextField(document.activeElement)) return;
    const key = shape();
    tallest.set(key, Math.max(tallest.get(key) ?? 0, window.innerHeight));
  };
  note();

  let timer: number | undefined;
  let reportedAt = -Infinity;
  let checking = false;
  let failed = 0;
  // The shortest the window got while a field held the focus: whether iOS
  // shrinks it for the keyboard at all (`interactive-widget` in index.html).
  let typing = Infinity;

  const check = async () => {
    if (checking || isTextField(document.activeElement)) return;
    const vv = window.visualViewport;
    if (vv && vv.scale > 1.01) return;
    const top = tallest.get(shape()) ?? window.innerHeight;
    const before = sizes(probe);
    if (shortBy(before, top) <= STUCK_PX) {
      note();
      typing = Infinity;
      return;
    }
    checking = true;
    const tried = failed < MAX_TRIES;
    if (tried) remeasure(probe);
    await frames();
    const after = sizes(probe);
    checking = false;
    const healed = shortBy(after, top) <= STUCK_PX;
    if (healed) note();
    else if (tried) failed += 1;
    const now = Date.now();
    if (now - reportedAt < REPORT_EVERY_MS) return;
    reportedAt = now;
    report({
      inner: before.inner,
      vv: before.vv,
      top: before.top,
      client: before.client,
      fixed: before.fixed,
      tallest: top,
      screen: screenHeight(),
      typing: Number.isFinite(typing) ? typing : 0,
      after_inner: after.inner,
      after_vv: after.vv,
      after_top: after.top,
      after_fixed: after.fixed,
      tried,
      healed,
    });
    typing = Infinity;
  };

  const later = () => {
    if (isTextField(document.activeElement)) {
      typing = Math.min(typing, window.innerHeight);
      return;
    }
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void check(), SETTLE_MS);
  };

  document.addEventListener("focusout", (event) => {
    if (isTextField(event.target)) {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void check(), SETTLE_MS);
    }
  });
  window.visualViewport?.addEventListener("resize", later);
  window.addEventListener("resize", later);
  window.addEventListener("orientationchange", later);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") later();
  });
}
