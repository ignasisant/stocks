/**
 * What the document carried for the shell to start with.
 *
 * The server writes the two answers every page used to wait on — `/me`, who
 * is asking, and `/prefs`, what they have set — into the document as a JSON
 * block (`web/server.py`, `_boot_tag`), plus the stamp under which the string
 * catalog is immutable. Read once, synchronously, before anything is fetched:
 * the first paint then owes the network nothing but the catalog, which the
 * document preloads, and the page's own figures.
 *
 * Absent (the dev server without the API, the MCP views, the tests, a server
 * that failed to build it) the shell fetches the pair as it always did. Every
 * field is checked before it is trusted: the block is the server's, but a
 * shape it did not mean to send must not crash the one component that renders
 * before the error boundary does.
 */

import type { Me, Prefs } from "./session";

/** The block's `id`, as `web/server.py` writes it. */
const BOOT_ID = "ag-boot";

export type Boot = {
  me: Me;
  prefs: Prefs;
  /** The catalog stamp: `?v=` on `/i18n/{lang}` makes the answer immutable. */
  i18n: string;
};

/** `text` as a boot block, or null for anything that is not one. */
export function parseBoot(text: string | null | undefined): Boot | null {
  if (!text) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const { me, prefs, i18n } = parsed as Record<string, unknown>;
  if (!me || typeof me !== "object" || !prefs || typeof prefs !== "object") return null;
  if (typeof (me as { kind?: unknown }).kind !== "string") return null;
  if (typeof (prefs as { currency?: unknown }).currency !== "string") return null;
  return {
    me: me as Me,
    prefs: prefs as Prefs,
    i18n: typeof i18n === "string" ? i18n : "",
  };
}

let read: Boot | null | undefined;

/** The document's boot block, read once; null where there is none. */
export function boot(): Boot | null {
  if (read === undefined) {
    read =
      typeof document === "undefined"
        ? null
        : parseBoot(document.getElementById(BOOT_ID)?.textContent);
  }
  return read;
}
