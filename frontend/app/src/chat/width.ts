/**
 * How wide the drawer is, and where that is remembered.
 *
 * A drag handle on the panel's edge, written to one custom property
 * (`--chat-w`) and kept under one localStorage key. Builds with the three
 * header presets stored `380px`, `720px` or `100vw` there; any of them is
 * still a width, and is honoured as one.
 *
 * Per browser rather than in `/prefs` — how much of a monitor a conversation
 * may take is a property of the monitor, not of the account.
 */

import { rubberBand } from "../shell/useSheet";

/** Where the width is kept. Older builds wrote here too, so it stays. */
const STORED = "chatPanelWidth";

/** The clamp the drag handle honours. */
const MIN_WIDTH = 320;
const MAX_WIDTH = 1500;

/** Write a CSS length onto the document, and remember it for the next load. */
function put(css: string): void {
  document.documentElement.style.setProperty("--chat-w", css);
  try {
    window.localStorage.setItem(STORED, css);
  } catch {
    // The panel has already resized; only the memory of it is lost.
  }
}

/** The width a wide table is read at: the old "Wide" preset. */
export const WIDE = 720;

/**
 * Take the panel to where a wide table holds — 720px, or the whole window
 * when 720px would be most of it anyway — and keep it there: the reader asked
 * for room, and the next wide answer should not ask again.
 */
export function widen(): void {
  put(window.innerWidth >= 1100 ? `${WIDE}px` : "100vw");
}

/**
 * The width the panel would have if the pointer were released here.
 *
 * The drawer is glued to the right edge, so its width is whatever is left of
 * the viewport to the right of the cursor — clamped, and never wider than the
 * window itself on a screen narrower than the minimum.
 */
export function widthAt(clientX: number): number {
  const room = window.innerWidth - clientX;
  return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth, room));
}

/** How far past a limit a drag may stretch the panel, at most. */
const GIVE = 96;

/**
 * The width mid-drag: `widthAt`, except that past a limit the panel follows
 * the pointer a little, with growing resistance, instead of stopping dead.
 * A hard stop reads as a broken handle; give says "this is the end" and the
 * release springs back to the limit `widthAt` gives. The resistance is the
 * sheets' (`rubberBand`): near 1:1 at first, flattening towards `GIVE`.
 */
export function stretchAt(clientX: number): number {
  const room = window.innerWidth - clientX;
  const low = MIN_WIDTH;
  const high = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth));
  const give = (past: number) => -rubberBand(past, GIVE);
  if (room < low) return low - give(low - room);
  if (room > high) return high + give(room - high);
  return room;
}

/**
 * Let the next width change animate, for a moment: the release of a drag
 * stretched past a limit, springing back to it (`[data-chat-settle]` in
 * chat.css). Off again at once, since mid-drag the width tracks the pointer.
 */
export function settle(): void {
  const root = document.documentElement;
  root.dataset.chatSettle = "";
  window.setTimeout(() => delete root.dataset.chatSettle, 240);
}

/** Size the panel mid-drag. Deliberately not stored: the release does that. */
export function applyPixels(px: number): void {
  document.documentElement.style.setProperty("--chat-w", `${px}px`);
}

/** Keep a dragged width. */
export function rememberPixels(px: number): void {
  put(`${px}px`);
}

/**
 * Put a stored width back on the document.
 *
 * Called when the panel mounts, because the property lives on the document
 * and a reload clears it — without this a drawer dragged wide would open at
 * 420px and only widen on the next drag.
 */
export function restoreWidth(): void {
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(STORED);
  } catch {
    return;
  }
  const raw = (stored ?? "").trim();
  if (!raw) return;
  // Bare integers are what every build before the presets wrote, and they must
  // get their unit back: `min(380, 100vw)` is invalid, which drops the width
  // declaration and stretches the panel across the page. Rewritten once, here.
  const css = /^\d+$/.test(raw) ? `${raw}px` : raw;
  // A dragged width is honoured as-is: it is this browser's choice too, and
  // the panel's own `min(..., 100vw)` keeps an absurd one on screen.
  if (css === raw) document.documentElement.style.setProperty("--chat-w", css);
  else put(css);
}

/**
 * Take the panel to a width for a while — the import review at the window's
 * full width — without touching what this browser remembers. Returns the way
 * back: the width the document had before, or none if it had none.
 */
export function borrowWidth(css: string): () => void {
  const style = document.documentElement.style;
  const before = style.getPropertyValue("--chat-w");
  style.setProperty("--chat-w", css);
  return () => {
    if (before) style.setProperty("--chat-w", before);
    else style.removeProperty("--chat-w");
  };
}
