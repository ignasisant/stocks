/**
 * The statement on screen, kept for the reader's way back.
 *
 * A warned row links to its ticker, and following it is a navigation: the page
 * unmounts, and with it the staged file, the wipe and the preview — which is
 * the model reading the statement, seconds and a call on the free chain. The
 * back button has to land on the review the reader left, at the row they
 * pressed, not on an empty drop zone that asks for the file again.
 *
 * So the page mirrors what it holds here and reads it back on mount. In memory
 * only: a statement's bytes are the reader's trades, and browser storage would
 * keep them after the tab is closed. A reload starts over, which is what a
 * reload means.
 *
 * The preview is kept as its promise, not its answer: a reader who leaves
 * while the model is still reading comes back to the same reading, not to a
 * second one. Anything that writes forgets it (`forget`), because the preview
 * is validated against the ledger the write just moved.
 */

import type { Outcome, Preview, Staged } from "./api";
import type { WipeChoice } from "./Wipe";

/**
 * The link the reader pressed, how far down the screen it sat, and which
 * folds were open around it — by their order on the page.
 */
type Anchor = { href: string; nth: number; top: number; open: number[] };

type Kept = {
  staged: Staged;
  wipe: WipeChoice;
  /** The platform the statement was staged under. */
  platform: string;
  answer?: { platform: string; wipe: boolean; outcome: Promise<Outcome<Preview>> };
  anchor?: Anchor;
};

let kept: Kept | null = null;

/** What the page held when it was left, if it held a statement. */
export const restored = (): Readonly<Kept> | null => kept;

/**
 * Mirror the page. A different statement drops the answer and the anchor,
 * which were about the old one; the same statement under a new wipe keeps
 * them, and `preview` simply misses on the wipe.
 */
export function keep(staged: Staged | null, wipe: WipeChoice, platform: string): void {
  if (!staged) {
    kept = null;
    return;
  }
  kept =
    kept?.staged === staged ? { ...kept, wipe, platform } : { staged, wipe, platform };
}

/** Drop the answer: something wrote, and it was validated against the old book. */
export function forget(): void {
  if (kept) delete kept.answer;
}

/**
 * The preview of `staged`, asked once per statement, platform and wipe. A
 * refusal is an answer and stays; a failure is not, and the next ask retries.
 */
export function preview(
  platform: string,
  staged: Staged,
  wipe: boolean,
  ask: () => Promise<Outcome<Preview>>,
): Promise<Outcome<Preview>> {
  const held = kept?.staged === staged ? kept : null;
  const answer = held?.answer;
  if (answer && answer.platform === platform && answer.wipe === wipe)
    return answer.outcome;
  const outcome = ask();
  if (held) {
    held.answer = { platform, wipe, outcome };
    outcome.catch(() => {
      if (held.answer?.outcome === outcome) delete held.answer;
    });
  }
  return outcome;
}

const plainClick = (event: MouseEvent) =>
  event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey;

/**
 * Note the link a click inside `root` is following, as the router's `Link`
 * reads a click: only a plain left one leaves the page.
 */
export function mark(root: HTMLElement | null, event: MouseEvent): void {
  if (!kept || !root || !plainClick(event)) return;
  const link = (event.target as Element | null)?.closest?.("a[href]");
  const href = link?.getAttribute("href");
  if (!link || !href || !root.contains(link)) return;
  const same = [...root.querySelectorAll("a[href]")].filter(
    (other) => other.getAttribute("href") === href,
  );
  kept.anchor = {
    href,
    nth: same.indexOf(link),
    top: link.getBoundingClientRect().top,
    open: [...root.querySelectorAll("details")].flatMap((fold, at) =>
      fold.open ? [at] : [],
    ),
  };
}

/**
 * Put the pressed link back where it was on screen, once. The folds open then
 * are opened first — the skipped rows are behind two — or the row would be
 * there and unseen, and the page too short to scroll it back up.
 */
export function land(root: HTMLElement | null): void {
  const anchor = kept?.anchor;
  if (!kept || !anchor || !root) return;
  delete kept.anchor;
  const link = [...root.querySelectorAll("a[href]")].filter(
    (other) => other.getAttribute("href") === anchor.href,
  )[anchor.nth];
  if (!link) return;
  const folds = [...root.querySelectorAll("details")];
  for (const at of anchor.open) {
    const fold = folds[at];
    if (fold) fold.open = true;
  }
  // Into view first, for the frames that scroll on their own (the full list
  // does), then the page alone, to the height it was pressed at.
  link.scrollIntoView({ block: "nearest" });
  window.scrollBy(0, link.getBoundingClientRect().top - anchor.top);
}
