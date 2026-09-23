/**
 * How wide the drawer is, and where that is remembered.
 *
 * The same three presets the Streamlit panel offers (`web/chat_core._WIDTHS`)
 * and the same drag handle beside them, written to the same custom property
 * under the same localStorage key: a reader who widened the drawer in the app
 * finds it wide here, and the two surfaces cannot disagree about a choice that
 * is about this screen.
 *
 * Per browser rather than in `/prefs` for that reason — how much of a monitor
 * a conversation may take is a property of the monitor, not of the account.
 */

export const WIDTHS = [
  { key: "compact", css: "380px", icon: "width_normal" },
  { key: "wide", css: "720px", icon: "width_wide" },
  { key: "full", css: "100vw", icon: "fullscreen" },
] as const;

export type WidthKey = (typeof WIDTHS)[number]["key"];

/** The key the Streamlit drawer stores its width under. */
const STORED = "chatPanelWidth";

/** The clamp the drag handle honours — `chat_core._MIN_WIDTH/_MAX_WIDTH`. */
const MIN_WIDTH = 320;
const MAX_WIDTH = 1500;

/** The preset a stored width belongs to, or null for a hand-dragged one. */
function keyFor(css: string | null): WidthKey | null {
  return WIDTHS.find((w) => w.css === css)?.key ?? null;
}

/**
 * The width this browser last chose, as a preset — or null when it is none of
 * them, because it was dragged or because nothing is stored at all.
 *
 * Null rather than a fallback on purpose: none of the three buttons should
 * look pressed for a width that no button produces, and the default 420px is
 * not one of the three either.
 */
export function storedWidth(): WidthKey | null {
  try {
    return keyFor(window.localStorage.getItem(STORED));
  } catch {
    // Private windows and blocked site data throw on the read itself.
    return null;
  }
}

/** Write a CSS length onto the document, and remember it for the next load. */
function put(css: string): void {
  document.documentElement.style.setProperty("--chat-w", css);
  try {
    window.localStorage.setItem(STORED, css);
  } catch {
    // The panel has already resized; only the memory of it is lost.
  }
}

/** Apply a preset: the property the panel is sized by, and the memory of it. */
export function applyWidth(key: WidthKey): void {
  const width = WIDTHS.find((w) => w.key === key);
  if (width) put(width.css);
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

/** Size the panel mid-drag. Deliberately not stored: the release does that. */
export function applyPixels(px: number): void {
  document.documentElement.style.setProperty("--chat-w", `${px}px`);
}

/** Keep a dragged width, and say which preset it lands on — usually none. */
export function rememberPixels(px: number): WidthKey | null {
  put(`${px}px`);
  return keyFor(`${px}px`);
}

/**
 * Put a stored width back on the document.
 *
 * Called when the panel mounts, because the property lives on the document
 * and a reload clears it — without this a drawer stored at "full" would open
 * at 420px and only widen on the next press.
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
  // declaration and stretches the panel across the page. The Streamlit drawer
  // rewrites them once too, and whichever surface opens first does it.
  const css = /^\d+$/.test(raw) ? `${raw}px` : raw;
  // A dragged width is honoured as-is: it is this browser's choice too, and
  // the panel's own `min(..., 100vw)` keeps an absurd one on screen.
  if (css === raw) document.documentElement.style.setProperty("--chat-w", css);
  else put(css);
}
