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

import { useEffect, useSyncExternalStore } from "react";
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

let working = false;
const busyListeners = new Set<() => void>();

/**
 * The drawer says whether it is writing an answer (or following a detached
 * run) while it is shut, so the phone tab bar's Assistant item can show what
 * the floating button used to: the assistant is at it. Same state source as
 * that button — the drawer's own `busy`.
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
