/**
 * The page's ambient light: three soft washes in the brand's own hues
 * (purple 600, purple 800, chart blue 600) drifting behind the page.
 *
 * A trial, off unless asked for: `?ambient=1` turns it on for this browser,
 * `?ambient=0` turns it off again. The DS draws a flat page; this is the
 * candidate amendment, not a decision yet.
 *
 * `AmbientLight` is drawn behind the page (`Layout`); the chat drawer has its
 * own, `ChatAurora` (`Drawer`).
 *
 * The motion is all CSS (`styles.css`, `.ag-ambient`): transform only, one
 * full drift every minute and a half or more, none under reduced motion.
 */

const KEY = "ag-ambient";

function readFlag(): boolean {
  try {
    const asked = new URLSearchParams(window.location.search).get("ambient");
    if (asked === "1") window.localStorage.setItem(KEY, "1");
    if (asked === "0") window.localStorage.removeItem(KEY);
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

/** Read once: the flag is a trial switch, not a setting that changes mid-visit. */
const AMBIENT = typeof window !== "undefined" && readFlag();

/** The page's light, fixed to the viewport behind everything. */
export function AmbientLight() {
  if (!AMBIENT) return null;
  return (
    <div className="ag-ambient" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}

/**
 * The chat drawer's own light: an aurora that flows sideways along the foot
 * of the drawer, in the same three hues, and rises while an answer is being
 * written (`busy`). Same trial switch as the page's.
 */
export function ChatAurora({ busy }: { busy: boolean }) {
  if (!AMBIENT) return null;
  return (
    <div className="ag-aurora" aria-hidden="true" data-busy={busy || undefined}>
      <div className="ag-aurora-band">
        <span />
      </div>
    </div>
  );
}
