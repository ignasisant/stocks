/**
 * Where a parked tour is, and what each way out of the modal does to it.
 *
 * Pure, so the rules that decide whether an account is stamped can be tested
 * without a DOM — and those rules are the whole point of this file. The
 * Streamlit tour (`web/onboarding.py`) draws the line in one place: **leaving
 * to look at something is not leaving.** Closing the guided tour with X or
 * Escape parks it in a strip above the page (`_minimize`), and a what's-new
 * card's "take me there" parks the list on the card it was on (`_news_park`).
 * Neither stamps anything. Only the ways *out* do — finishing, "end tour",
 * "skip the rest", the list's own X — because those are the reader saying they
 * are done, and a parked list abandoned half-read is still owed.
 *
 * The parked position lives in `sessionStorage`: the same lifetime as the
 * Streamlit session state it mirrors (one tab, gone when the tab is), and it
 * survives a reload, which is the one thing a single-page app does that a
 * Streamlit rerun never did.
 */

export type Mode = "tour" | "news";

/** A tour that is running: which list, which item, and whether the modal is up. */
export type Place = { mode: Mode; at: number; open: boolean };

/** What the component has to do after an action: stamp, and how. */
export type Stamp = { done?: boolean } | null;

export type Action =
  /** X, Escape, the scrim. */
  | "dismiss"
  /** A step's or card's "take me there". */
  | "goto"
  /** Finish on the last step, or "end tour" on the strip. */
  | "finish"
  /** "Skip the rest" / "Done" on the news list, or its strip's close. */
  | "news_done";

/**
 * The next place, and whether the account is stamped — for one action.
 *
 * Returns `place: null` when the tour is over and nothing stays on screen.
 */
export function after(
  place: Place,
  action: Action,
): { place: Place | null; stamp: Stamp } {
  switch (action) {
    case "dismiss":
      // The tour parks; what's new does not. That asymmetry is Streamlit's
      // (`on_dismiss=_minimize` for one dialog, `_dismiss_news` for the other)
      // and it is deliberate: the tour is what the reader came for, the news
      // list is an interruption, and closing an interruption means "enough".
      return place.mode === "tour"
        ? { place: { ...place, open: false }, stamp: null }
        : { place: null, stamp: {} };
    case "goto":
      // Parked on the same item, so the strip can bring the reader back to
      // exactly where they left — and the rest of the list with them.
      return { place: { ...place, open: false }, stamp: null };
    case "finish":
      // Done with the walkthrough retires it, and stamps the release too: a
      // first-timer who has just seen everything has no "what's new" to catch
      // up on (`_exit_tour`).
      return { place: null, stamp: { done: true } };
    case "news_done":
      return { place: null, stamp: {} };
  }
}

const KEY = "tourParked";

/** The parked tour for this tab, or null. Unreadable storage reads as none. */
export function readPark(storage?: Storage | null): { mode: Mode; at: number } | null {
  try {
    const raw = (storage ?? window.sessionStorage).getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { mode?: unknown; at?: unknown };
    if (parsed.mode !== "tour" && parsed.mode !== "news") return null;
    const at = Number(parsed.at);
    return {
      mode: parsed.mode,
      at: Number.isFinite(at) && at >= 0 ? Math.floor(at) : 0,
    };
  } catch {
    return null;
  }
}

/** Remember (or, with null, forget) where the tour is parked in this tab. */
export function writePark(
  place: { mode: Mode; at: number } | null,
  storage?: Storage | null,
): void {
  try {
    const store = storage ?? window.sessionStorage;
    if (place) store.setItem(KEY, JSON.stringify({ mode: place.mode, at: place.at }));
    else store.removeItem(KEY);
  } catch {
    // Private windows throw on the write. The strip still works for the life
    // of this document; it just will not survive a reload.
  }
}

/** Clamp a parked index into a list that may have shrunk since it was saved. */
export function clamp(at: number, length: number): number {
  return Math.min(Math.max(at, 0), Math.max(length - 1, 0));
}

/**
 * Whether the first load of this document already interrupted the reader.
 *
 * Streamlit's rule (`app.py`): the walkthrough, then "what's new", then the
 * investor-profile nudge — one modal per first load, and the nudge only when
 * neither of the others took the slot. The tour decides asynchronously (it has
 * to fetch `/onboarding` first), so the nudge waits on this rather than racing
 * it. Settled exactly once; later calls are ignored.
 */
let settleFirstLoad: (interrupted: boolean) => void = () => undefined;
const firstLoadDecided = new Promise<boolean>((resolve) => {
  settleFirstLoad = resolve;
});

export function firstLoadInterrupted(interrupted: boolean): void {
  settleFirstLoad(interrupted);
}

export function whenFirstLoadDecided(): Promise<boolean> {
  return firstLoadDecided;
}
