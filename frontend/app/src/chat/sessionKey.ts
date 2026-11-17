/**
 * A provider key held for this tab only — "this session only", in a front end
 * whose session is a browser tab.
 *
 * An unremembered key answers every turn of the visit and is gone when the
 * tab is. The closest thing a single-page app has is `sessionStorage` — one
 * tab, survives a reload, never shared with another tab, cleared when the tab
 * closes — so the key lives there and nowhere else. The server never stores
 * it: each request that needs it (`/chat/state`, `/chat/runs`, the attachment
 * mapper, the walkthrough's narration) carries it in `X-Chat-Provider` +
 * `X-Chat-Key`, and `api/routes/chat/preferences.py` uses it for that request alone.
 *
 * It is also the only way to use a key of your own on a deployment that has no
 * encryption secret, where `PUT /chat/keys` answers 503 rather than write a
 * key in the clear.
 *
 * Not `localStorage`: a key that outlived the tab would be a stored key in all
 * but name, kept in the one place on the machine with none of the encryption
 * or the 90-day expiry the server applies to a stored one.
 */

import { useSyncExternalStore } from "react";

const SLOT = "ag_chat_session_key";

/** Fired on this window when the tab starts or stops holding a key. The
 * browser's own `storage` event only reaches other tabs, and no other tab
 * shares this slot. */
const CHANGED = "ag:session-key";

function announce(): void {
  window.dispatchEvent(new Event(CHANGED));
}

export type SessionKey = { provider: string; key: string };

/** The key this tab holds, or null. Storage blocked reads as none. */
export function readSessionKey(): SessionKey | null {
  try {
    const raw = window.sessionStorage.getItem(SLOT);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SessionKey>;
    return typeof parsed.provider === "string" &&
      typeof parsed.key === "string" &&
      parsed.key
      ? { provider: parsed.provider, key: parsed.key }
      : null;
  } catch {
    return null;
  }
}

/**
 * Hold a key for this tab. False when the browser will not keep it — private
 * mode with storage blocked — which the caller says out loud: a key that was
 * accepted and then silently not used would read as the provider refusing it.
 */
export function holdSessionKey(held: SessionKey): boolean {
  try {
    window.sessionStorage.setItem(SLOT, JSON.stringify(held));
    announce();
    return true;
  } catch {
    return false;
  }
}

export function dropSessionKey(): void {
  try {
    window.sessionStorage.removeItem(SLOT);
    announce();
  } catch {
    // Nothing was held, then.
  }
}

/** The headers that carry the held key, or none. Never logged, never a URL. */
export function keyHeaders(): Record<string, string> {
  const held = readSessionKey();
  return held ? { "X-Chat-Provider": held.provider, "X-Chat-Key": held.key } : {};
}

/**
 * `/onboarding`'s `setup` with the key this tab holds counted as a key.
 *
 * The server only knows a stored key, so an account answering on a key kept
 * for the session read "no key" on Home's start card and in Profile's count
 * while the drawer beside them said otherwise. Merged here, once, for every
 * screen that draws that state; the key itself never leaves the tab for it.
 * `held` comes from `useSessionKeyHeld`, so a key typed in the drawer shows
 * on the page behind it at once rather than on its next load.
 */
export function withSessionKey<S extends Record<string, boolean | undefined>>(
  setup: S,
  held: boolean,
): S {
  return setup.ai || !held ? setup : { ...setup, ai: true };
}

function subscribe(listener: () => void): () => void {
  window.addEventListener(CHANGED, listener);
  return () => window.removeEventListener(CHANGED, listener);
}

/** Whether this tab holds a key, re-rendering when that changes. */
export function useSessionKeyHeld(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => readSessionKey() !== null,
    () => false,
  );
}
