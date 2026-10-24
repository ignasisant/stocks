/**
 * Translated strings, from the catalogs the server reads (`web/locales/`).
 *
 * `/api/v1/i18n/{lang}` serves them flat with English underneath, so a key the
 * translation is missing renders in English rather than as a dotted key on
 * screen. Nothing here ships a string of its own: a literal in a component is
 * a string that exists in one language, and this app has two.
 *
 * The catalog is fetched once for the whole session and held in context. It is
 * ~2300 keys, which is one request and a few tens of kilobytes — cheaper than
 * the per-page `prefix=` filtering it replaces, which cost a request per page
 * and left the shell unable to render a label before the page loaded.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { ApiError, get } from "./api";
import { setNumberLang } from "./numbers";
import { useApi } from "./useApi";

type Catalog = { lang: string; strings: Record<string, string> };

/** `ready` is false until the catalog has arrived (true outside a provider). */
const Strings = createContext<Catalog & { ready: boolean }>({
  lang: "en",
  strings: {},
  ready: true,
});

/**
 * `t("portfolio.tab_positions")`, with `{placeholder}` slots filled in.
 *
 * A missing key renders as the key itself. That is deliberate and matches the
 * Python side: a blank is invisible in review, and a dotted key on screen is a
 * bug report that writes itself.
 */
export function useT() {
  const { strings } = useContext(Strings);
  return (key: string, slots?: Record<string, string | number>) => {
    let value = strings[key] ?? key;
    for (const [name, slot] of Object.entries(slots ?? {})) {
      value = value.replaceAll(`{${name}}`, String(slot));
    }
    return value;
  };
}

/** The languages the catalogs ship — `stocks.web.i18n.LANGUAGES`. */
const LANGUAGES = ["en", "es"];

const PINNED = "guestLang";

/**
 * The browser's language among the ones we ship, read down the whole
 * preference list rather than its first entry: a Catalan browser lists
 * `ca, es, en`, and its reader wants the Spanish catalog, not the English
 * fallback the first entry alone would give. Spain's other co-official
 * languages land on Spanish too when nothing on the list is shipped.
 */
export function browserLang(languages: readonly string[]): string {
  const codes = languages.map((tag) => (tag.split(/[-_]/)[0] ?? "").toLowerCase());
  return (
    codes.find((code) => LANGUAGES.includes(code)) ??
    (codes.some((code) => ["ca", "gl", "eu"].includes(code)) ? "es" : "en")
  );
}

/**
 * The language a landing CTA pinned for this tab, or null.
 *
 * The landing links into the app with `?lang=` set to the language the visitor
 * was reading. The parameter would be gone after the first in-app navigation —
 * the router writes fresh query strings — so the choice is remembered in
 * `sessionStorage`, for the life of the tab. For a guest only: a signed-in
 * account has a stored preference, and a marketing link must not overrule it.
 */
export function pinnedLang(search: string, storage?: Storage | null): string | null {
  const asked = (new URLSearchParams(search).get("lang") ?? "").trim().toLowerCase();
  try {
    const store = storage ?? window.sessionStorage;
    if (LANGUAGES.includes(asked)) {
      store.setItem(PINNED, asked);
      return asked;
    }
    const kept = store.getItem(PINNED);
    return kept && LANGUAGES.includes(kept) ? kept : null;
  } catch {
    // Storage blocked: the parameter still counts on the page it arrived on.
    return LANGUAGES.includes(asked) ? asked : null;
  }
}

export function useLang(): string {
  return useContext(Strings).lang;
}

/**
 * Whether the catalog is in. For copy that is optional while it is not — a
 * loading caption — and would otherwise print its dotted keys on a slow start.
 */
export function useStringsReady(): boolean {
  return useContext(Strings).ready;
}

/** How many times a failed catalog is asked again, and the base wait between. */
const RETRIES = 5;
const RETRY_S = 3;

export function Translations({
  lang,
  children,
}: {
  lang: string;
  children: ReactNode;
}) {
  const catalog = useApi(() => get<Catalog>(`/i18n/${lang}`), [lang]);
  // Asked again when it fails, a few times. It is asked once per session, so
  // one refusal — a 429 from a burst of tabs, a dropped connection — otherwise
  // left every label in the app as its dotted key until a reload.
  const tries = useRef(0);
  useEffect(() => {
    if (catalog.state === "loaded") tries.current = 0;
    if (catalog.state !== "failed" || tries.current >= RETRIES) return;
    tries.current += 1;
    const after =
      catalog.error instanceof ApiError ? catalog.error.retryAfter : undefined;
    const timer = setTimeout(catalog.retry, (after ?? RETRY_S * tries.current) * 1000);
    return () => clearTimeout(timer);
  }, [catalog]);
  // A catalog that will not load must not blank the app: every key falls back
  // to itself, which is ugly and still navigable. Blocking here would turn a
  // CDN hiccup into a white screen.
  const loaded = catalog.state === "loaded" ? catalog.data : null;
  const value = useMemo(
    () => (loaded ? { ...loaded, ready: true } : { lang, strings: {}, ready: false }),
    [loaded, lang],
  );
  // Published before any child renders, so number helpers without a `lang`
  // argument spell figures in the same language as the words around them.
  setNumberLang(value.lang);
  // The document's own language too (WCAG 3.1.1): index.html ships `en`, and
  // a screen reader reading Spanish copy with English phonetics is noise.
  useEffect(() => {
    document.documentElement.lang = value.lang;
  }, [value.lang]);
  return <Strings.Provider value={value}>{children}</Strings.Provider>;
}
