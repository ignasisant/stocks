/**
 * How a page hands a question to the assistant, without knowing it exists.
 *
 * The Ticker page's "Analyse with AI" is one press that opens the drawer with
 * the company already asked about. In Streamlit that is `chat_core.ask()`,
 * which reruns the whole script; here the drawer is a sibling of the page,
 * mounted once by the shell, and neither may import the other — a page that
 * reached into `src/chat/` would be a page that breaks when the drawer moves.
 *
 * So the shell owns the seam and both sides talk to it: a page calls `ask()`,
 * the drawer listens. That is also why it is an event and not state — the
 * question is a thing that happened, not a value to be read; a second press on
 * the same button has to ask again, which a state holding the same string
 * would not do.
 */

import { useEffect } from "react";

/** `null` is "just open it" — the drawer opens and asks nothing. */
type Listener = (prompt: string | null) => void;

const listeners = new Set<Listener>();

/**
 * Ask the assistant something, from anywhere.
 *
 * A no-op when nothing is listening — the drawer is only mounted for a
 * signed-in reader, and a button that throws for a guest is worse than one
 * that does nothing. Callers gate on the session themselves where the button
 * should not be drawn at all.
 */
export function askAssistant(prompt: string): void {
  const text = prompt.trim();
  if (!text) return;
  for (const listener of listeners) listener(text);
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

/** Subscribe to those questions. The drawer is the only caller. */
export function useAssistantAsks(handler: Listener): void {
  useEffect(() => {
    listeners.add(handler);
    return () => {
      listeners.delete(handler);
    };
  }, [handler]);
}
