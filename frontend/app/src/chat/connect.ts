/**
 * A provider key minted by signing in, instead of pasted — OAuth PKCE, run in
 * the reader's browser.
 *
 * The flow is OpenRouter's (openrouter.ai/docs, "OAuth PKCE"): send the reader
 * to the provider's authorize page with the SHA-256 of a random verifier, the
 * provider sends them back to this page with `?code=`, and the code plus the
 * verifier buy a key that belongs to the reader and spends their own credits.
 * The server is told only the URLs (`ProviderInfo.connect_url`) and never
 * holds the verifier: the key it ends up with arrives through `PUT /chat/keys`
 * exactly as a typed one would, or stays in this tab (`sessionKey.ts`) when
 * the reader did not ask for it to be remembered.
 *
 * The verifier waits in `sessionStorage` across the round trip, which is what
 * makes a forged return harmless: a link carrying somebody else's `?code=`
 * finds no verifier in this tab, or one the code was not issued against, and
 * the provider refuses the trade. It is single use — taken off storage the
 * moment the reader lands back — and dies with the code's own ten minutes.
 */

import { ApiError } from "../shell/api";
import { readState, storeKey } from "./api";
import { keyError } from "./format";
import { dropSessionKey, holdSessionKey, readSessionKey } from "./sessionKey";
import type { ChatState } from "./types";

const SLOT = "ag_chat_connect";

/** OpenRouter's authorization codes are good for ten minutes. */
const TTL_MS = 10 * 60 * 1000;

/** A sign-in this tab started and has not finished. */
export type Pending = {
  provider: string;
  verifier: string;
  /** Where the code is traded for the key (`ProviderInfo.connect_token_url`). */
  tokenUrl: string;
  /** Store the key on the account (true), or hold it for this tab only. */
  remember: boolean;
  /** The query the page had when the reader left, put back on return. */
  back: string;
  at: number;
};

/** A return from a provider's sign-in, waiting for the settings to finish it. */
export type ConnectAsk = { code: string; pending: Pending };

function base64url(bytes: Uint8Array): string {
  let raw = "";
  for (const byte of bytes) raw += String.fromCharCode(byte);
  return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** 32 random bytes, base64url — 43 characters, inside RFC 7636's 43–128. */
export function newVerifier(): string {
  const bytes = new Uint8Array(32);
  globalThis.crypto.getRandomValues(bytes);
  return base64url(bytes);
}

/** The S256 challenge for a verifier (RFC 7636 §4.2). */
export async function challengeFor(verifier: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return base64url(new Uint8Array(digest));
}

/**
 * The sign-in this tab left for, taken off storage, or null.
 *
 * Null for none, for one past the code's lifetime, and for storage that will
 * not answer — all three mean the same thing to the caller: a `?code=` on
 * the URL is not one this tab asked for.
 */
export function takeConnect(now = Date.now()): Pending | null {
  try {
    const raw = window.sessionStorage.getItem(SLOT);
    window.sessionStorage.removeItem(SLOT);
    if (!raw) return null;
    const held = JSON.parse(raw) as Partial<Pending>;
    if (
      typeof held.provider !== "string" ||
      typeof held.verifier !== "string" ||
      typeof held.tokenUrl !== "string" ||
      typeof held.at !== "number" ||
      now - held.at > TTL_MS
    ) {
      return null;
    }
    return {
      provider: held.provider,
      verifier: held.verifier,
      tokenUrl: held.tokenUrl,
      remember: held.remember === true,
      back: typeof held.back === "string" ? held.back : "",
      at: held.at,
    };
  } catch {
    return null;
  }
}

/**
 * Where to send the reader to sign in, with the verifier saved for the return.
 *
 * The callback is this page without its query: the provider appends `?code=`,
 * and a callback that already carried one would be at the mercy of how it
 * joins the two. The query goes into `back` instead and the drawer puts it
 * back. Null when the tab will not keep the verifier — private mode with
 * storage blocked — because a sign-in whose return cannot be finished would
 * spend a key on the provider's side for nothing.
 */
export async function connectUrl(
  provider: {
    id: string;
    connect_url?: string | null;
    connect_token_url?: string | null;
  },
  remember: boolean,
  label: string,
): Promise<string | null> {
  if (!provider.connect_url || !provider.connect_token_url) return null;
  const verifier = newVerifier();
  const pending: Pending = {
    provider: provider.id,
    verifier,
    tokenUrl: provider.connect_token_url,
    remember,
    back: window.location.search,
    at: Date.now(),
  };
  try {
    window.sessionStorage.setItem(SLOT, JSON.stringify(pending));
  } catch {
    return null;
  }
  const query = new URLSearchParams({
    callback_url: `${window.location.origin}${window.location.pathname}`,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
    // What the key is called on the reader's own provider dashboard, so they
    // can tell which app holds it when they come to revoke it.
    key_label: label,
  });
  return `${provider.connect_url}?${query}`;
}

/**
 * Trade the code the provider sent back for the reader's key.
 *
 * Straight to the provider, never through this app's server: the verifier
 * never leaves the tab, and no cookie goes with it. Throws on any refusal —
 * an expired code, a used one, a verifier it was not issued against — and the
 * caller has one thing to say about all of them: start again.
 */
export async function exchange(code: string, pending: Pending): Promise<string> {
  const response = await fetch(pending.tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code,
      code_verifier: pending.verifier,
      code_challenge_method: "S256",
    }),
    credentials: "omit",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) throw new Error(`connect refused: ${response.status}`);
  const body = (await response.json()) as { key?: unknown };
  if (typeof body.key !== "string" || !body.key) throw new Error("connect: no key");
  return body.key;
}

/** A sign-in that ended without a key, with the locale key that says why. */
export class ConnectFailed extends Error {
  constructor(readonly key: string) {
    super(key);
  }
}

/**
 * Finish a sign-in: trade the code, keep the key the way the reader chose
 * before leaving, and answer with the state that now says who answers.
 *
 * The same two places a typed key goes (`Settings.tsx`'s `save`): stored on
 * the account, superseding whatever this tab held for the provider, or held
 * by this tab alone.
 */
export async function finishConnect(
  code: string,
  pending: Pending,
): Promise<ChatState> {
  let key: string;
  try {
    key = await exchange(code, pending);
  } catch {
    throw new ConnectFailed("chat.connect_failed");
  }
  if (!pending.remember) {
    if (!holdSessionKey({ provider: pending.provider, key })) {
      throw new ConnectFailed("chat.key_session_blocked");
    }
    return readState();
  }
  try {
    const next = await storeKey(pending.provider, key);
    if (readSessionKey()?.provider === pending.provider) dropSessionKey();
    return next;
  } catch (failure) {
    throw new ConnectFailed(
      failure instanceof ApiError ? keyError(failure.status) : "chat.api_error",
    );
  }
}
