/**
 * Where a parked tour is, and what each way out of the modal does to it.
 *
 * Pure, so the rules that decide whether an account is stamped can be tested
 * without a DOM — and those rules are the whole point of this file. The line
 * is drawn in one place: **leaving to look at something is not leaving.**
 * Closing the guided tour with X or Escape parks it in a strip above the page,
 * and a what's-new card's "take me there" parks the list on the card it was
 * on. Neither stamps anything. Only the ways *out* do — finishing, "end tour",
 * "skip the rest", the list's own X — because those are the reader saying they
 * are done, and a parked list abandoned half-read is still owed.
 *
 * The walkthrough comes in two lengths: "tour" is the section guide, one stop
 * per menu entry, drawn as a card beside the page it is showing; "all" is
 * every stop, in the dialog. Both park and both retire the same way; only
 * "news" differs.
 *
 * The parked position lives in `sessionStorage`: one tab, gone when the tab
 * is, and it survives a reload.
 */

export type Mode = "tour" | "all" | "news";

/** A tour that is running: which list, which item, and whether the modal is up. */
export type Place = { mode: Mode; at: number; open: boolean };

/**
 * What the component has to do after an action: stamp, and how. `walked` is
 * the walkthrough answered (`/onboarding/seen`): it retires the tour, catches
 * the account up and withdraws Home's offer in one write. `finished` adds that
 * every stop was shown, which strikes the tips of the pages it stood on.
 */
export type Stamp = { done?: boolean; walked?: boolean; finished?: boolean } | null;

export type Action =
  /** X, Escape, the scrim. */
  | "dismiss"
  /** A step's or card's "take me there". */
  | "goto"
  /** "Skip the tutorial", "end tour" on the strip, or the dialog's way out. */
  | "finish"
  /** Next on the section guide's last stop: the reader was shown every page. */
  | "complete"
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
      // The tour parks; what's new does not. That asymmetry is deliberate:
      // the tour is what the reader came for, the news list is an
      // interruption, and closing an interruption means "enough".
      return place.mode === "news"
        ? { place: null, stamp: {} }
        : { place: { ...place, open: false }, stamp: null };
    case "goto":
      // Parked on the same item, so the strip can bring the reader back to
      // exactly where they left — and the rest of the list with them.
      return { place: { ...place, open: false }, stamp: null };
    case "finish":
      // Done with the walkthrough retires it, and stamps the release too: a
      // first-timer who has just seen everything has no "what's new" to catch
      // up on. Skipping is the same answer as finishing, so Home stops
      // offering what was just turned down.
      return { place: null, stamp: { walked: true } };
    case "complete":
      // The same answer, and one thing more: the guide stood on every page
      // and said what it is for, so those pages owe no first-visit tip. A
      // skip never earns this; the reader saw none of them.
      return { place: null, stamp: { walked: true, finished: true } };
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
    if (parsed.mode !== "tour" && parsed.mode !== "all" && parsed.mode !== "news") {
      return null;
    }
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
 * The walkthrough, then "what's new", then the investor-profile nudge — one
 * modal per first load, and the nudge only when neither of the others took the
 * slot. The tour decides asynchronously (it has to fetch `/onboarding` first),
 * so the nudge waits on this rather than racing it. Settled exactly once; later
 * calls are ignored.
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

/**
 * One nudge dialog per load: the profile nudge and the rating prompt both
 * claim this before they open, so a reader who just answered one is not met by
 * the other thirty seconds later. False when the slot was already taken.
 */
let nudged = false;

export function claimNudge(): boolean {
  if (nudged) return false;
  nudged = true;
  return true;
}

/**
 * Whether the tour, the welcome or "what's new" is on screen, open or parked.
 * A page's first-visit tip (`PageTip`) waits while it is: two guides talking
 * at once is one too many, and the tour is the one the reader asked for.
 */
let touring = false;
const touringListeners = new Set<() => void>();

export function setTouring(on: boolean): void {
  if (on === touring) return;
  touring = on;
  for (const listener of touringListeners) listener();
}

export function isTouring(): boolean {
  return touring;
}

export function onTouring(listener: () => void): () => void {
  touringListeners.add(listener);
  return () => touringListeners.delete(listener);
}

/**
 * The section the guide is standing on, for the menu to point at: a page's
 * slug, `ASSISTANT` for the stop that is a panel, or null when no guide is up.
 * The guide and the menu are siblings in the shell, so the stop travels here
 * rather than through either one's props.
 */
export const ASSISTANT = "assistant";

let stop: string | null = null;
const stopListeners = new Set<() => void>();

export function setGuideStop(next: string | null): void {
  if (next === stop) return;
  stop = next;
  for (const listener of stopListeners) listener();
}

export function guideStop(): string | null {
  return stop;
}

export function onGuideStop(listener: () => void): () => void {
  stopListeners.add(listener);
  return () => stopListeners.delete(listener);
}
