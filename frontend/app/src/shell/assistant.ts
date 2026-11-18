/**
 * How a page hands a question to the assistant, without knowing it exists.
 *
 * The Ticker page's "Analyse with AI" is one press that opens the drawer with
 * the company already asked about. The drawer is a sibling of the page,
 * mounted once by the shell, and neither may import the other — a page that
 * reached into `src/chat/` would be a page that breaks when the drawer moves.
 *
 * So the shell owns the seam and both sides talk to it: a page calls `ask()`,
 * the drawer listens. That is also why it is an event and not state — the
 * question is a thing that happened, not a value to be read; a second press on
 * the same button has to ask again, which a state holding the same string
 * would not do.
 */

import { useEffect, useState, useSyncExternalStore } from "react";
import { keepDraft } from "../chat/draft";

/**
 * The angles the Ticker page's "Analyse with AI" offers. The server writes
 * the brief each one stands for (`chat/brief.py`) — lenses, position, report
 * dates, structure — so the prompt shown is a label, not the instructions.
 */
export type Brief = "full" | "bear" | "earnings" | "fit";

/**
 * `null` is "just open it" — the drawer opens and asks nothing. `fresh` asks
 * in a new conversation rather than the one on screen; `brief` names the
 * angle the server expands the prompt into.
 */
type Listener = (prompt: string | null, fresh?: boolean, brief?: Brief) => void;

const listeners = new Set<Listener>();

/**
 * Ask the assistant something, from anywhere.
 *
 * A no-op when nothing is listening. An account's listener is the drawer; a
 * guest's is the locked drawer (`chat/Locked.tsx`), which shows the question
 * and keeps it for after the sign-in rather than answering it.
 */
export function askAssistant(
  prompt: string,
  { fresh = false, brief }: { fresh?: boolean; brief?: Brief } = {},
): void {
  const text = prompt.trim();
  if (!text) return;
  for (const listener of listeners) listener(text, fresh, brief);
}

/**
 * Open the assistant without asking it anything.
 *
 * The tour has a stop at the assistant and the Home checklist has a row for
 * it, and both mean "here is where it lives" rather than a question. Sending
 * a made-up prompt to get the panel open would spend the reader's daily
 * allowance on a question they did not ask.
 */
export function openAssistant(): void {
  for (const listener of listeners) listener(null);
}

const closers = new Set<() => void>();

/**
 * Put the assistant away. Only for a panel this code opened itself: the
 * guide's assistant stop opens it, and once the guide has moved on or ended
 * the page it left the reader on should not stay narrowed by a drawer they
 * never asked for. A drawer the reader opened is theirs to close.
 */
export function closeAssistant(): void {
  for (const close of closers) close();
}

/** Subscribe to `closeAssistant`. The drawer is the only caller. */
export function useAssistantCloses(handler: () => void): void {
  useEffect(() => {
    closers.add(handler);
    return () => {
      closers.delete(handler);
    };
  }, [handler]);
}

/** Narrowest page the open drawer leaves before it covers it instead (px). */
const PAGE_MIN = 560;

/**
 * Whether a drawer this wide leaves the page readable beside it, or covers it.
 *
 * The same sum as the padding rule in `chat/chat.css`: the menu, the drawer
 * (which past 60% of the window overlaps rather than taking more off the
 * page) and the gap between them. Here rather than in the drawer because the
 * guide asks it too, before opening the panel at its assistant stop: a panel
 * that would land on top of the guide's card is offered, not opened.
 */
export function roomBeside(drawerWidth: number): boolean {
  const nav = document.querySelector<HTMLElement>(".ag-nav");
  const drawer = Math.min(drawerWidth, window.innerWidth * 0.6);
  const taken = (nav?.offsetWidth ?? 0) + drawer + 20;
  return window.innerWidth - taken >= PAGE_MIN;
}

/**
 * The width the drawer would open at, in px: `--chat-w` as the panel's own
 * rule reads it (`min(var(--chat-w, 420px), 100vw)`). The drawer puts the
 * remembered width on the document when it mounts, so this is right before
 * the panel has ever been opened.
 */
export function drawerWidth(): number {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue("--chat-w")
    .trim();
  const n = Number.parseFloat(raw);
  const px = !Number.isFinite(n)
    ? 420
    : raw.endsWith("vw")
      ? (window.innerWidth * n) / 100
      : n;
  return Math.min(px, window.innerWidth);
}

const fillListeners = new Set<() => void>();

/**
 * Open the assistant with words already in its field — written, never sent.
 *
 * The prompt is a stem the reader finishes ("I hold: 10 NVDA at 120…"), so
 * sending it would book somebody else's example and spend an answer on it.
 * It goes through the same one-shot slot a guest's question rides across the
 * sign-in (`chat/draft.ts`): a composer that mounts later takes it on mount,
 * one already on screen is told to. Nothing listening (no drawer) loses it,
 * like the others.
 */
export function fillAssistant(text: string): void {
  const stem = text.trim();
  if (!stem) return;
  keepDraft(stem);
  openAssistant();
  for (const listener of fillListeners) listener();
}

/** Subscribe to those fills. The composer is the only caller. */
export function useAssistantFills(handler: () => void): void {
  useEffect(() => {
    fillListeners.add(handler);
    return () => {
      fillListeners.delete(handler);
    };
  }, [handler]);
}

const attachListeners = new Set<(file: File) => void>();
const takerWatchers = new Set<() => void>();

function takersChanged(): void {
  for (const watcher of takerWatchers) watcher();
}

/**
 * Open the assistant with a statement to import, as if it had been dropped on
 * the conversation. The Import page's "Import with the assistant" — the
 * drawer reads it with the same reader the page uses and shows the rows
 * before anything is written: a second way to the same import. A no-op with
 * nothing listening, like the others: a guest's locked drawer cannot import.
 */
export function attachAssistant(file: File): void {
  for (const listener of attachListeners) listener(file);
}

/** Subscribe to those statements. The drawer is the only caller. */
export function useAssistantAttach(handler: (file: File) => void): void {
  useEffect(() => {
    attachListeners.add(handler);
    takersChanged();
    return () => {
      attachListeners.delete(handler);
      takersChanged();
    };
  }, [handler]);
}

/**
 * Whether anything would take `attachAssistant` — an account's drawer. A
 * subscription, not a read: the drawer registers in an effect, after a page
 * loaded straight from its URL has already drawn once.
 */
export function useAssistantTakesFiles(): boolean {
  return useSyncExternalStore(
    (watcher) => {
      takerWatchers.add(watcher);
      return () => takerWatchers.delete(watcher);
    },
    () => attachListeners.size > 0,
    () => false,
  );
}

const threadListeners = new Set<(cid: string) => void>();

/**
 * Open the assistant on one conversation — Home's daily card has one of its
 * own, filed by the server, and its "Ask" lands the reader there so the
 * question is asked with the card above it. A no-op with nothing listening,
 * like the others.
 */
export function openThread(cid: string): void {
  for (const listener of threadListeners) listener(cid);
}

/** Subscribe to those opens. The drawer is the only caller. */
export function useAssistantThreads(handler: (cid: string) => void): void {
  useEffect(() => {
    threadListeners.add(handler);
    return () => {
      threadListeners.delete(handler);
    };
  }, [handler]);
}

/** Subscribe to those questions. The drawer is the only caller. */
export function useAssistantAsks(handler: Listener): void {
  useEffect(() => {
    listeners.add(handler);
    return () => {
      listeners.delete(handler);
    };
  }, [handler]);
}

const changeListeners = new Set<(kind: string) => void>();

/**
 * The drawer says an action the reader approved went through (`kind` is the
 * proposal's: "set_criteria", "favorite"…), so a page already drawing what it
 * changed can read it again. Without it the exit rules saved from the chat
 * stayed "none yet" in the open journal panel until a reload.
 */
export function announceChange(kind: string): void {
  for (const listener of changeListeners) listener(kind);
}

/**
 * How many `kind` changes have gone through since mount: a count to put in a
 * `useApi` dependency list, which re-asks the server past the memo when it
 * moves.
 */
export function useAssistantChanges(kind: string): number {
  const [count, setCount] = useState(0);
  useEffect(() => {
    const listener = (changed: string) => {
      if (changed === kind) setCount((n) => n + 1);
    };
    changeListeners.add(listener);
    return () => {
      changeListeners.delete(listener);
    };
  }, [kind]);
  return count;
}

let working = false;
const busyListeners = new Set<() => void>();

/**
 * The drawer says whether it is writing an answer (or following a detached
 * run) while it is shut, so the phone tab bar's Assistant item can show
 * the assistant is at it. Same state source as the floating button — the
 * drawer's own `busy`.
 */
export function setAssistantWorking(next: boolean): void {
  if (working === next) return;
  working = next;
  for (const listener of busyListeners) listener();
}

export function useAssistantWorking(): boolean {
  return useSyncExternalStore(
    (listener) => {
      busyListeners.add(listener);
      return () => busyListeners.delete(listener);
    },
    () => working,
    () => false,
  );
}

let unread = false;
const unreadListeners = new Set<() => void>();

/**
 * An answer landed on a thread the reader was not on (`chat/landed.ts`), and
 * the drawer is shut: the phone tab bar's Assistant item carries the dot the
 * floating button carries elsewhere.
 */
export function setAssistantUnread(next: boolean): void {
  if (unread === next) return;
  unread = next;
  for (const listener of unreadListeners) listener();
}

export function useAssistantUnread(): boolean {
  return useSyncExternalStore(
    (listener) => {
      unreadListeners.add(listener);
      return () => unreadListeners.delete(listener);
    },
    () => unread,
    () => false,
  );
}
