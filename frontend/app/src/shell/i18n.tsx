/**
 * Translated strings, from the same catalogs the Streamlit pages read.
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

import { createContext, useContext, type ReactNode } from "react";
import { get } from "./api";
import { useApi } from "./useApi";

type Catalog = { lang: string; strings: Record<string, string> };

const Strings = createContext<Catalog>({ lang: "en", strings: {} });

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
 * The language a landing CTA pinned for this tab, or null.
 *
 * The landing links into the app with `?lang=` set to the language the visitor
 * was reading, and Streamlit honours it for a signed-out session
 * (`landing.consume_params`). Here the parameter would be gone after the first
 * in-app navigation — the router writes fresh query strings — so the choice is
 * remembered in `sessionStorage`, the same lifetime as the Streamlit session
 * state it mirrors. For a guest only: a signed-in account has a stored
 * preference, and a marketing link must not overrule it.
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

export function Translations({
  lang,
  children,
}: {
  lang: string;
  children: ReactNode;
}) {
  const catalog = useApi(() => get<Catalog>(`/i18n/${lang}`), [lang]);
  // A catalog that will not load must not blank the app: every key falls back
  // to itself, which is ugly and still navigable. Blocking here would turn a
  // CDN hiccup into a white screen.
  const value = catalog.state === "loaded" ? catalog.data : { lang, strings: {} };
  return <Strings.Provider value={value}>{children}</Strings.Provider>;
}
